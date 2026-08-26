"""El colchón: dinero ajeno que uso y debo reponer."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.money import D
from app.services import buffer as buffer_service
from app.services.format import block, date_es, money, row

router = Router(name="buffer")


@router.message(Command("colchon", "colchón"))
@router.message(F.text == "Colchón")
async def cmd_buffer(message: Message, session: AsyncSession) -> None:
    state = await buffer_service.state(session)
    if state.total <= 0:
        await message.answer(
            f"<b>{settings.buffer_name}</b>\n\n"
            "Todavía no defines cuánto dinero ajeno tienes de colchón.\n"
            "Fíjalo con <code>/colchontotal 500</code>.\n\n"
            "Después basta con escribir <i>«saqué 80 del colchón»</i> o "
            "<i>«repuse 80 al colchón»</i>."
        )
        return

    lines = [
        f"<b>{state.name}</b>",
        "<i>Este dinero no es tuyo.</i>",
        "",
        block(
            [
                row("Total asignado", money(state.total)),
                row("Disponible", money(state.available)),
                row("Por reponer", money(state.debt)),
            ]
        ),
    ]

    history = await buffer_service.history(session, limit=8)
    if history:
        lines += ["", "<b>Últimos movimientos</b>"]
        for mv in history:
            verb = "sacaste" if mv.direction == "use" else "repusiste"
            note = f" · {mv.note}" if mv.note else ""
            lines.append(f"{date_es(mv.date)} · {verb} {money(mv.amount)}{note}")

    await message.answer("\n".join(lines))


@router.message(Command("colchontotal"))
async def cmd_set_total(message: Message, session: AsyncSession) -> None:
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("Uso: <code>/colchontotal 500</code>")
        return
    try:
        amount = D(parts[1].replace("$", ""))
    except Exception:
        await message.answer("No entendí el monto.")
        return
    await buffer_service.set_total(session, amount)
    await message.answer(
        f"{settings.buffer_name} fijado en <b>{money(amount)}</b>.\n"
        "Ese dinero no cuenta como tuyo en el resumen."
    )


@router.message(Command("colchonrepongo", "repongo"))
async def cmd_repay(message: Message, session: AsyncSession) -> None:
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("Uso: <code>/repongo 50</code>")
        return
    try:
        amount = D(parts[1].replace("$", ""))
    except Exception:
        await message.answer("No entendí el monto.")
        return
    await buffer_service.repay(session, amount, note="Reposición manual")
    state = await buffer_service.state(session)
    await message.answer(
        f"Repuesto {money(amount)}. Te falta reponer <b>{money(state.debt)}</b>."
    )
