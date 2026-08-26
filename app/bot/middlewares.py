"""Middlewares: sesión de base de datos y control de acceso."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Setting

log = logging.getLogger(__name__)

OWNER_KEY = "owner_id"


class DbSessionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict[str, Any]):
        async with SessionLocal() as session:
            data["session"] = session
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise


async def get_owner_id(session) -> int | None:
    row = (
        await session.execute(select(Setting).where(Setting.key == OWNER_KEY))
    ).scalar_one_or_none()
    if row and row.value.lstrip("-").isdigit():
        return int(row.value)
    return None


async def set_owner_id(session, user_id: int) -> None:
    row = (
        await session.execute(select(Setting).where(Setting.key == OWNER_KEY))
    ).scalar_one_or_none()
    if row is None:
        session.add(Setting(key=OWNER_KEY, value=str(user_id)))
    else:
        row.value = str(user_id)
    await session.flush()


class AuthMiddleware(BaseMiddleware):
    """Solo el dueño (y los IDs permitidos) pueden usar el bot.

    Si no hay dueño configurado, el primer usuario que escriba queda como dueño.
    Así se entrega el bot ya instalado y el cliente se registra solo.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ):
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        session = data["session"]
        allowed = settings.allowed_ids
        owner = await get_owner_id(session)

        if owner is None and not allowed:
            await set_owner_id(session, user.id)
            await session.commit()
            owner = user.id
            log.info("Dueño registrado automáticamente: %s", user.id)

        if user.id == owner or user.id in allowed:
            data["is_owner"] = user.id == owner
            return await handler(event, data)

        text = (
            "🔒 Este bot es privado.\n\n"
            f"Tu ID de Telegram es <code>{user.id}</code>.\n"
            "Pídele al administrador que lo agregue a <code>ALLOWED_USER_IDS</code>."
        )
        if isinstance(event, Message):
            await event.answer(text)
        elif isinstance(event, CallbackQuery):
            await event.answer("Bot privado", show_alert=True)
        return None
