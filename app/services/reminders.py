"""Recordatorios diarios: tarjetas por vencer y gastos fijos pendientes."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.money import total
from app.services.cards import credit_cards, cut_day_of, due_day_of, statement
from app.services.fixed import overdue, upcoming
from app.services.format import date_es, money
from app.services.periods import current_period, today
from app.services.reports import statement_due_in

WARN_DAYS = (7, 3, 1, 0)


async def build_reminder(session: AsyncSession) -> str | None:
    """Texto del recordatorio del día, o None si no hay nada que avisar."""
    blocks: list[str] = []

    cards: list[str] = []
    for card in await credit_cards(session):
        period = statement_due_in(current_period(), cut_day_of(card), due_day_of(card))
        summary = await statement(session, card, period)
        if summary.to_pay <= 0:
            continue
        days = summary.days_left
        if days < 0:
            cards.append(
                f"⚠️ <b>{card.name}</b>: {money(summary.to_pay)} <b>vencida</b> "
                f"desde el {date_es(summary.due_date)}"
            )
        elif days in WARN_DAYS:
            when = "hoy" if days == 0 else f"en {days} día{'s' if days > 1 else ''}"
            cards.append(f"🔔 <b>{card.name}</b>: {money(summary.to_pay)} vence {when}")
        # aviso del corte
        if summary.cut_date == today():
            cards.append(f"✂️ Hoy corta <b>{card.name}</b>: lo que compres ya cae al siguiente mes")
    if cards:
        blocks.append("💳 <b>Tarjetas</b>\n" + "\n".join(cards))

    late = await overdue(session)
    if late:
        blocks.append(
            "⏰ <b>Fijos vencidos</b>\n"
            + "\n".join(f"• {t.description} — {money(t.amount)} (venció {date_es(t.date)})" for t in late[:8])
            + f"\nTotal: <b>{money(total(t.amount for t in late))}</b>"
        )

    soon = [t for t in await upcoming(session, days=3)]
    if soon:
        blocks.append(
            "🗓️ <b>Se vienen</b>\n"
            + "\n".join(f"• {t.description} — {money(t.amount)} el {date_es(t.date)}" for t in soon[:8])
        )

    if not blocks:
        return None
    return "\n\n".join(blocks)
