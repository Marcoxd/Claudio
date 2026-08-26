"""Captura de gastos: texto libre, nota de voz, foto de recibo y PDF."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import draft_actions
from app.services import ai
from app.services.capture import build_context, draft_from_parsed, save_draft
from app.services.render import describe_draft

log = logging.getLogger(__name__)
router = Router(name="capture")

MAX_FILE_MB = 18
SUPPORTED_DOCS = {
    "application/pdf": "application/pdf",
    "image/jpeg": "image/jpeg",
    "image/png": "image/png",
    "image/webp": "image/webp",
    "image/heic": "image/heic",
}


async def _send_draft(message: Message, session: AsyncSession, payload: dict) -> None:
    draft = await save_draft(payload=payload, session=session,
                             user_id=message.from_user.id, chat_id=message.chat.id)
    text, has_items = await describe_draft(session, payload)
    sent = await message.answer(text, reply_markup=draft_actions(draft.id, has_items))
    draft.message_id = sent.message_id
    await session.flush()


async def _download(bot: Bot, file_id: str) -> bytes:
    buffer = await bot.download(file_id)
    return buffer.read()


@router.message(F.voice | F.audio)
async def on_voice(message: Message, session: AsyncSession, bot: Bot) -> None:
    media = message.voice or message.audio
    if media.file_size and media.file_size > MAX_FILE_MB * 1024 * 1024:
        await message.answer("El audio es muy pesado. Mándame uno más corto.")
        return
    note = await message.answer("🎧 Escuchando…")
    try:
        data = await _download(bot, media.file_id)
        ctx = await build_context(session)
        parsed = await ai.parse_audio(data, media.mime_type or "audio/ogg", ctx)
        payload = await draft_from_parsed(
            session, parsed, source="voice", raw_text=parsed.notes, file_id=media.file_id
        )
    except Exception:
        log.exception("Error procesando nota de voz")
        await note.edit_text("😖 No pude procesar el audio. Intenta escribiéndolo.")
        return
    await note.delete()
    await _send_draft(message, session, payload)


@router.message(F.photo)
async def on_photo(message: Message, session: AsyncSession, bot: Bot) -> None:
    photo = message.photo[-1]
    note = await message.answer("🔎 Leyendo el recibo…")
    try:
        data = await _download(bot, photo.file_id)
        ctx = await build_context(session)
        parsed = await ai.parse_document(data, "image/jpeg", ctx, caption=message.caption or "")
        payload = await draft_from_parsed(
            session, parsed, source="photo",
            raw_text=message.caption or "", file_id=photo.file_id,
        )
    except Exception:
        log.exception("Error procesando foto")
        await note.edit_text("😖 No pude leer la imagen. Prueba con más luz o escríbelo.")
        return
    await note.delete()
    await _send_draft(message, session, payload)


@router.message(F.document)
async def on_document(message: Message, session: AsyncSession, bot: Bot) -> None:
    doc = message.document
    mime = SUPPORTED_DOCS.get((doc.mime_type or "").lower())
    if not mime:
        await message.answer("Solo puedo leer PDF e imágenes (JPG, PNG).")
        return
    if doc.file_size and doc.file_size > MAX_FILE_MB * 1024 * 1024:
        await message.answer(f"El archivo pasa de {MAX_FILE_MB} MB.")
        return
    note = await message.answer("📄 Leyendo la factura…")
    try:
        data = await _download(bot, doc.file_id)
        ctx = await build_context(session)
        parsed = await ai.parse_document(data, mime, ctx, caption=message.caption or "")
        payload = await draft_from_parsed(
            session, parsed, source="pdf",
            raw_text=message.caption or "", file_id=doc.file_id,
        )
    except Exception:
        log.exception("Error procesando documento")
        await note.edit_text("😖 No pude leer el archivo.")
        return
    await note.delete()
    await _send_draft(message, session, payload)


@router.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message, session: AsyncSession) -> None:
    text = message.text.strip()
    if len(text) < 2:
        return
    ctx = await build_context(session)
    parsed = await ai.parse_text(text, ctx)
    if parsed.kind == "unknown" or not parsed.amount:
        await message.answer(
            "🤔 No encontré un monto en ese mensaje.\n"
            "Prueba con algo como <code>almuerzo 12.50 con la visa</code>, "
            "o usa /ayuda para ver ejemplos."
        )
        return
    payload = await draft_from_parsed(session, parsed, source="text", raw_text=text)
    await _send_draft(message, session, payload)
