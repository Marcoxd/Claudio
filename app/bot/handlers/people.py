"""Deudas de gastos compartidos con amigos."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import debts_actions
from app.models import Person
from app.money import D, total
from app.services.format import date_es, money
from app.services.splits import balances, settle_person

router = Router(name="people")


@router.message(Command("deudas"))
@router.message(F.text == "🤝 Deudas")
async def cmd_debts(message: Message, session: AsyncSession) -> None:
    rows = await balances(session)
    if not rows:
        await message.answer(
            "🤝 Nadie te debe nada ahora mismo.\n\n"
            "Cuando anotes un gasto compartido (<i>«cena 96 con Ana y Luis»</i> o "
            "dividiendo un recibo por ítems) aparecerá aquí."
        )
        return

    lines = ["🤝 <b>Te deben</b>", ""]
    for b in rows:
        lines.append(f"👤 <b>{b.person.name}</b> — {money(b.owes_me)}")
        for share in b.shares[:5]:
            tx = share.split.transaction if share.split else None
            if tx:
                lines.append(f"    • {date_es(tx.date)} {tx.description[:28]} — {money(share.amount)}")
        if len(b.shares) > 5:
            lines.append(f"    … y {len(b.shares) - 5} gastos más")
        lines.append("")
    lines.append(f"<b>Total por cobrar: {money(total(b.owes_me for b in rows))}</b>")
    await message.answer("\n".join(lines), reply_markup=debts_actions(rows))


@router.callback_query(F.data.startswith("p:settle:"))
async def cb_settle(callback: CallbackQuery, session: AsyncSession) -> None:
    person_id = int(callback.data.split(":")[2])
    person = await session.get(Person, person_id)
    settled = await settle_person(session, person_id, note="Saldado desde el bot")
    await callback.message.answer(
        f"✅ {person.name if person else 'Persona'} saldó <b>{money(settled)}</b>. Cuentas claras."
    )
    await callback.answer("Saldado")


@router.message(Command("cobre", "cobré"))
async def cmd_partial(message: Message, session: AsyncSession) -> None:
    """/cobre Ana 20 → abono parcial de una deuda."""
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer("Uso: <code>/cobre Ana 20</code>")
        return
    name, raw = " ".join(parts[1:-1]), parts[-1]
    rows = await balances(session)
    match = next((b for b in rows if name.lower() in b.person.name.lower()), None)
    if match is None:
        await message.answer("No encontré a esa persona con deudas pendientes.")
        return
    try:
        amount = D(raw.replace("$", ""))
    except Exception:
        await message.answer("No entendí el monto.")
        return
    settled = await settle_person(session, match.person.id, amount, note="Abono parcial")
    remaining = D(match.owes_me - settled)
    await message.answer(
        f"✅ {match.person.name} abonó {money(settled)}.\n"
        + (f"Aún debe <b>{money(remaining)}</b>." if remaining > 0 else "Quedó al día 🎉")
    )
