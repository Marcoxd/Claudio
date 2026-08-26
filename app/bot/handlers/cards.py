"""Tarjetas de crédito: cortes, cuotas y pagos."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import card_actions
from app.models import Account, CardPayment
from app.money import D, ZERO
from app.services.cards import (
    card_balance,
    credit_cards,
    cut_day_of,
    due_day_of,
    future_commitments,
    statement,
)
from app.services.format import date_es, money
from app.services.periods import current_period, period_label, today
from app.services.reports import statement_due_in

router = Router(name="cards")


async def _cards_text(session: AsyncSession) -> tuple[str, list]:
    cards = await credit_cards(session)
    if not cards:
        return (
            "Todavía no tienes tarjetas registradas.\n"
            "Agrégalas con /setup: nombre, día de corte y día de pago.",
            [],
        )
    period = current_period()
    lines = [f"<b>Tarjetas</b> · {period_label(period)}", ""]
    statements = []
    grand_total = ZERO
    for card in cards:
        target = statement_due_in(period, cut_day_of(card), due_day_of(card))
        summary = await statement(session, card, target)
        statements.append(summary)
        grand_total = D(grand_total + summary.to_pay)

        if summary.is_overdue:
            when = f"venció el {date_es(summary.due_date)}"
        elif summary.days_left == 0:
            when = "vence hoy"
        elif summary.days_left <= 5:
            when = f"vence en {summary.days_left} días"
        else:
            when = f"vence {date_es(summary.due_date)}"

        lines.append(f"<b>{card.name}</b> · {money(summary.to_pay)}")
        lines.append(f"Corte {date_es(summary.cut_date)} · {when}")
        if summary.others_share > 0:
            lines.append(f"De eso, {money(summary.others_share)} es de otros.")
        deferred = [i for i in summary.installments if i.count > 1]
        if deferred:
            plural = "cuota" if len(deferred) == 1 else "cuotas"
            lines.append(f"{len(deferred)} {plural} de diferidos en este corte.")
        if card.credit_limit:
            used = await card_balance(session, card)
            lines.append(
                f"Cupo libre {money(D(D(card.credit_limit) - used))} "
                f"de {money(card.credit_limit)}."
            )
        lines.append("")

    lines.append(f"<b>Total a pagar este mes: {money(grand_total)}</b>")
    return "\n".join(lines), statements


@router.message(Command("tarjetas"))
@router.message(F.text == "Tarjetas")
async def cmd_cards(message: Message, session: AsyncSession) -> None:
    text, statements = await _cards_text(session)
    await message.answer(text, reply_markup=card_actions(statements) if statements else None)


@router.callback_query(F.data == "c:future")
async def cb_future(callback: CallbackQuery, session: AsyncSession) -> None:
    period = current_period()
    lines = ["<b>Cuotas ya comprometidas</b>", ""]
    for card in await credit_cards(session):
        rows = await future_commitments(session, card, period, months=6)
        rows = [(p, a) for p, a in rows if a > 0]
        if not rows:
            continue
        lines.append(f"<b>{card.name}</b>")
        for p, amount in rows:
            lines.append(f"   {period_label(p)}: {money(amount)}")
        lines.append("")
    if len(lines) <= 2:
        lines.append("No hay cuotas futuras registradas.")
    await callback.message.answer("\n".join(lines))
    await callback.answer()


@router.callback_query(F.data.startswith("c:pay:"))
async def cb_pay(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, account_id, period = callback.data.split(":")
    card = await session.get(Account, int(account_id))
    if card is None:
        await callback.answer("Tarjeta no encontrada", show_alert=True)
        return
    summary = await statement(session, card, period)
    if summary.to_pay <= 0:
        await callback.answer("Ese corte ya está pagado", show_alert=True)
        return
    session.add(
        CardPayment(
            account_id=card.id,
            date=summary.due_date,
            amount=summary.to_pay,
            statement_period=period,
            note="Pago total del corte",
        )
    )
    await session.flush()
    await callback.message.answer(
        f"Registrado el pago de <b>{money(summary.to_pay)}</b> a {card.name} "
        f"(corte {period_label(period)})."
    )
    await callback.answer("Pago registrado")


@router.message(Command("pagar"))
async def cmd_pay(message: Message, session: AsyncSession) -> None:
    """/pagar visa 250  → registra un abono parcial."""
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer(
            "Uso: <code>/pagar visa 250</code>\n"
            "Registra un abono a esa tarjeta contra el corte que vence este mes."
        )
        return
    name, raw_amount = " ".join(parts[1:-1]), parts[-1]
    cards = await credit_cards(session)
    card = next((c for c in cards if name.lower() in c.name.lower()), None)
    if card is None:
        await message.answer(
            "No encontré esa tarjeta. Tienes: " + ", ".join(c.name for c in cards)
        )
        return
    try:
        amount = D(raw_amount)
    except Exception:
        await message.answer("No entendí el monto.")
        return
    period = statement_due_in(current_period(), cut_day_of(card), due_day_of(card))
    session.add(
        CardPayment(account_id=card.id, date=today(),
                    amount=amount, statement_period=period, note="Abono")
    )
    await session.flush()
    summary = await statement(session, card, period)
    await message.answer(
        f"Abono de {money(amount)} a <b>{card.name}</b>.\n"
        f"Queda pendiente <b>{money(summary.to_pay)}</b> del corte {period_label(period)}."
    )
