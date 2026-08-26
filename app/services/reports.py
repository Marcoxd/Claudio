"""Reportes: resumen mensual, cuánto puedo gastar, categorías, flujo."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ACCOUNT_CREDIT,
    KIND_EXPENSE,
    KIND_INCOME,
    STATUS_DONE,
    Account,
    Transaction,
)
from app.money import D, ZERO, total
from app.services import buffer as buffer_service
from app.services.cards import (
    StatementSummary,
    credit_cards,
    cut_day_of,
    due_day_of,
    statement,
)
from app.services.fixed import ensure_period_materialized
from app.services.periods import add_months, period_bounds
from app.services.splits import balances


def statement_due_in(period: str, cut_day: int, due_day: int) -> str:
    """Qué corte se paga durante `period`, dados los días de corte y de pago."""
    return period if due_day > cut_day else add_months(period, -1)


@dataclass
class CategoryLine:
    name: str
    emoji: str
    amount: Decimal
    essential: bool = False

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.name}".strip()


@dataclass
class MonthReport:
    period: str
    income_received: Decimal = ZERO
    income_expected: Decimal = ZERO
    fixed_paid: Decimal = ZERO
    fixed_pending: Decimal = ZERO
    cash_variable: Decimal = ZERO          # gastos variables ya pagados sin tarjeta
    card_charged: Decimal = ZERO           # compras del mes hechas con tarjeta
    cards_due: Decimal = ZERO              # lo que toca pagar de tarjetas este mes
    cards_paid: Decimal = ZERO
    others_owe_me: Decimal = ZERO
    statements: list[StatementSummary] = field(default_factory=list)
    by_category: list[CategoryLine] = field(default_factory=list)
    buffer: "buffer_service.BufferState | None" = None
    transactions: list[Transaction] = field(default_factory=list)

    @property
    def income_total(self) -> Decimal:
        return D(self.income_received + self.income_expected)

    @property
    def fixed_total(self) -> Decimal:
        return D(self.fixed_paid + self.fixed_pending)

    @property
    def cards_remaining(self) -> Decimal:
        return D(max(ZERO, self.cards_due - self.cards_paid))

    @property
    def committed(self) -> Decimal:
        """Todo lo que sí o sí sale este mes."""
        return D(self.fixed_total + self.cards_due)

    @property
    def spent_so_far(self) -> Decimal:
        """Dinero que ya salió del bolsillo este mes."""
        return D(self.fixed_paid + self.cash_variable + self.cards_paid)

    @property
    def available_to_spend(self) -> Decimal:
        """Cuánto me queda para gastar libremente este mes."""
        return D(
            self.income_total
            - self.fixed_total
            - self.cards_due
            - self.cash_variable
        )

    @property
    def real_expenses(self) -> Decimal:
        """Gasto real del mes (lo mío, sin la parte de amigos)."""
        return D(self.fixed_total + self.cash_variable + self.card_charged)

    @property
    def net(self) -> Decimal:
        return D(self.income_total - self.real_expenses)


async def month_report(
    session: AsyncSession, period: str, materialize: bool = True
) -> MonthReport:
    if materialize:
        await ensure_period_materialized(session, period)

    report = MonthReport(period=period)

    txs = (
        await session.execute(
            select(Transaction)
            .where(Transaction.period == period)
            .order_by(Transaction.date.desc(), Transaction.id.desc())
        )
    ).scalars().all()
    report.transactions = list(txs)

    credit_ids = {
        a.id
        for a in (
            await session.execute(select(Account).where(Account.type == ACCOUNT_CREDIT))
        ).scalars().all()
    }

    by_cat: dict[str, CategoryLine] = {}
    for tx in txs:
        amount = D(tx.effective_amount())
        if tx.kind == KIND_INCOME:
            if tx.status == STATUS_DONE:
                report.income_received = D(report.income_received + amount)
            else:
                report.income_expected = D(report.income_expected + amount)
            continue

        if tx.fixed_expense_id:
            if tx.status == STATUS_DONE:
                report.fixed_paid = D(report.fixed_paid + amount)
            else:
                report.fixed_pending = D(report.fixed_pending + amount)
        elif tx.status == STATUS_DONE:
            if tx.account_id in credit_ids:
                report.card_charged = D(report.card_charged + amount)
            else:
                report.cash_variable = D(report.cash_variable + amount)

        if tx.status == STATUS_DONE or tx.fixed_expense_id:
            cat = tx.category
            key = cat.name if cat else "Sin categoría"
            line = by_cat.setdefault(
                key,
                CategoryLine(
                    name=key,
                    emoji=cat.emoji if cat else "❓",
                    amount=ZERO,
                    essential=bool(cat and cat.is_essential),
                ),
            )
            line.amount = D(line.amount + amount)

    report.by_category = sorted(by_cat.values(), key=lambda c: c.amount, reverse=True)

    for card in await credit_cards(session):
        target = statement_due_in(period, cut_day_of(card), due_day_of(card))
        summary = await statement(session, card, target)
        report.statements.append(summary)
        report.cards_due = D(report.cards_due + summary.charges)
        report.cards_paid = D(report.cards_paid + summary.paid)

    report.others_owe_me = total(b.owes_me for b in await balances(session))
    report.buffer = await buffer_service.state(session)
    return report


async def cashflow(session: AsyncSession, months: int = 6, end: str | None = None):
    """Serie de ingresos vs gastos de los últimos `months` meses."""
    from app.services.periods import current_period

    end = end or current_period()
    out = []
    for i in range(months - 1, -1, -1):
        period = add_months(end, -i)
        r = await month_report(session, period, materialize=False)
        out.append(
            {
                "period": period,
                "income": float(r.income_total),
                "expenses": float(r.real_expenses),
                "net": float(r.net),
            }
        )
    # No dibujar los meses iniciales sin ningún movimiento: aplanan el gráfico.
    while len(out) > 2 and out[0]["income"] == 0 and out[0]["expenses"] == 0:
        out.pop(0)
    return out


async def recent_transactions(session: AsyncSession, limit: int = 20) -> list[Transaction]:
    from sqlalchemy.orm import selectinload

    rows = (
        await session.execute(
            select(Transaction)
            .options(selectinload(Transaction.installments))
            .where(Transaction.status == STATUS_DONE)
            .order_by(Transaction.date.desc(), Transaction.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


async def period_totals(session: AsyncSession, period: str) -> dict[str, Decimal]:
    start, end = period_bounds(period)
    rows = (
        await session.execute(
            select(Transaction).where(
                Transaction.date >= start,
                Transaction.date <= end,
                Transaction.status == STATUS_DONE,
            )
        )
    ).scalars().all()
    return {
        "income": total(t.effective_amount() for t in rows if t.kind == KIND_INCOME),
        "expense": total(t.effective_amount() for t in rows if t.kind == KIND_EXPENSE),
    }
