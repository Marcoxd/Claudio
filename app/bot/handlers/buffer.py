"""El colchón: dinero ajeno que uso y debo reponer."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.money import D
from app.services import buffer as buffer_service
from app.services.format import bar, date_es, money

router = Router(name="buffer")


@router.message(Command("colchon", "colchón"))
@router.message(F.text == "🛏️ Colchón")
async def cmd_buffer(message: Message, session: AsyncSession) -> None:
    state = await buffer_service.state(session)
    if state.total <= 0:
        await message.answer(
            f"🛏️ <b>{settings.buffer_name}</b>\n\n"
            "Todavía no has definido cuánto dinero ajeno tienes de colchón.\n"
            "Usa <code>/colchontotal 500</code> para fijarlo.\n\n"
            "Después basta con que escribas <i>«saqué 80 del colchón»</i> o "
            "<i>«repuse 80 al colchón»</i>."
        )
        return

    icon = "🟢" if state.debt == 0 else ("🟡" if state.pct_used < 50 else "🔴")
    lines = [
        f"🛏️ <b>{state.name}</b> <i>(no es tuyo)</i>",
        "",
        f"Total asignado   <code>{money(state.total)}</code>",
        f"Disponible       <code>{money(state.available)}</code>",
        f"Debes reponer    <code>{money(state.debt)}</code>  {icon}",
        "",
        f"<code>{bar(state.pct_used)}</code> {state.pct_used:.0f}% usado",
    ]

    history = await buffer_service.history(session, limit=8)
    if history:
        lines.append("\n📜 <b>Últimos movimientos</b>")
        for mv in history:
            sign = "➖" if mv.direction == "use" else "➕"
            lines.append(f"{sign} {date_es(mv.date)} {money(mv.amount)} · {mv.note or ''}".rstrip())

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
        f"🛏️ {settings.buffer_name} fijado en <b>{money(amount)}</b>.\n"
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
        f"➕ Repuesto {money(amount)}.\nTe falta reponer <b>{money(state.debt)}</b>."
    )
