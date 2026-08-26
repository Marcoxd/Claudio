"""Lógica de tarjetas de crédito: cortes, cuotas (diferidos) y estados de cuenta."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    ACCOUNT_CREDIT,
    Account,
    CardPayment,
    Installment,
    Transaction,
)
from app.money import D, ZERO, split_evenly, total
from app.services.periods import (
    add_months,
    clamp_day,
    parse_period,
    period_of,
    today,
)

DEFAULT_CUT_DAY = 20
DEFAULT_DUE_DAY = 10


def cut_day_of(account: Account) -> int:
    return account.cut_day or DEFAULT_CUT_DAY


def due_day_of(account: Account) -> int:
    return account.due_day or DEFAULT_DUE_DAY


def statement_period_for(purchase_date: dt.date, cut_day: int) -> str:
    """Estado de cuenta al que cae una compra.

    Si la compra es hasta el día de corte, entra en el corte de ese mismo mes;
    si es después, entra en el corte del mes siguiente.
    """
    period = period_of(purchase_date)
    if purchase_date.day <= cut_day:
        return period
    return add_months(period, 1)


def cut_date_for(statement_period: str, cut_day: int) -> dt.date:
    year, month = parse_period(statement_period)
    return clamp_day(year, month, cut_day)


def statement_window(statement_period: str, cut_day: int) -> tuple[dt.date, dt.date]:
    """Rango de fechas que abarca un corte: del día siguiente al corte anterior."""
    end = cut_date_for(statement_period, cut_day)
    previous = cut_date_for(add_months(statement_period, -1), cut_day)
    return previous + dt.timedelta(days=1), end


def due_date_for(statement_period: str, cut_day: int, due_day: int) -> dt.date:
    """Fecha máxima de pago del estado de cuenta que cierra en `statement_period`."""
    year, month = parse_period(statement_period)
    if due_day > cut_day:
        return clamp_day(year, month, due_day)
    nxt = add_months(statement_period, 1)
    ny, nm = parse_period(nxt)
    return clamp_day(ny, nm, due_day)


def build_installments(
    transaction: Transaction, account: Account, count: int | None = None
) -> list[Installment]:
    """Genera las cuotas de una compra con tarjeta (1 = corriente, n = diferido)."""
    if account.type != ACCOUNT_CREDIT:
        return []
    count = max(1, int(count or transaction.installments_total or 1))
    cut = cut_day_of(account)
    due = due_day_of(account)
    base_period = statement_period_for(transaction.date, cut)
    amounts = split_evenly(D(transaction.amount), count)

    out: list[Installment] = []
    for i, amount in enumerate(amounts):
        period = add_months(base_period, i)
        out.append(
            Installment(
                transaction=transaction,
                account_id=account.id,
                number=i + 1,
                count=count,
                amount=amount,
                statement_period=period,
                due_date=due_date_for(period, cut, due),
            )
        )
    return out


@dataclass
class Placement:
    """Dónde cae una compra: en qué corte entra y cuándo se paga."""

    period: str
    cut_date: dt.date
    due_date: dt.date
    count: int
    last_period: str
    last_due_date: dt.date
    installment_amount: Decimal

    @property
    def is_deferred(self) -> bool:
        return self.count > 1


def place_purchase(
    account: Account, date: dt.date, amount: Decimal, count: int = 1
) -> Placement | None:
    """Calcula el corte de una compra sin necesidad de guardarla.

    Sirve para decirle al usuario, antes de confirmar, en qué mes le van a
    cobrar lo que acaba de anotar.
    """
    if account.type != ACCOUNT_CREDIT:
        return None
    cut, due = cut_day_of(account), due_day_of(account)
    count = max(1, int(count or 1))
    period = statement_period_for(date, cut)
    last = add_months(period, count - 1)
    return Placement(
        period=period,
        cut_date=cut_date_for(period, cut),
        due_date=due_date_for(period, cut, due),
        count=count,
        last_period=last,
        last_due_date=due_date_for(last, cut, due),
        installment_amount=split_evenly(D(amount), count)[0] if amount else ZERO,
    )


@dataclass
class StatementSummary:
    account: Account
    period: str
    cut_date: dt.date
    due_date: dt.date
    charges: Decimal = ZERO           # lo que el banco cobra en este corte
    others_share: Decimal = ZERO      # parte de amigos incluida en esos cargos
    paid: Decimal = ZERO              # pagos ya registrados contra este corte
    installments: list[Installment] = field(default_factory=list)

    @property
    def to_pay(self) -> Decimal:
        return D(self.charges - self.paid)

    @property
    def my_real_cost(self) -> Decimal:
        """Del corte, cuánto es gasto realmente mío."""
        return D(self.charges - self.others_share)

    @property
    def days_left(self) -> int:
        return (self.due_date - today()).days

    @property
    def is_overdue(self) -> bool:
        return self.to_pay > 0 and self.due_date < today()


async def statement(
    session: AsyncSession, account: Account, period: str
) -> StatementSummary:
    """Estado de cuenta de una tarjeta para el corte que cierra en `period`."""
    cut, due = cut_day_of(account), due_day_of(account)
    rows = (
        await session.execute(
            select(Installment)
            .options(selectinload(Installment.transaction))
            .where(
                Installment.account_id == account.id,
                Installment.statement_period == period,
            )
            .order_by(Installment.id)
        )
    ).scalars().all()
    rows = sorted(
        rows,
        key=lambda i: (i.transaction.date if i.transaction else dt.date.min, i.id),
    )

    payments = (
        await session.execute(
            select(CardPayment).where(
                CardPayment.account_id == account.id,
                CardPayment.statement_period == period,
            )
        )
    ).scalars().all()

    others = ZERO
    for inst in rows:
        tx = inst.transaction
        if tx and tx.my_share is not None and D(tx.amount) > 0:
            ratio = (D(tx.amount) - D(tx.my_share)) / D(tx.amount)
            others += D(D(inst.amount) * ratio)

    return StatementSummary(
        account=account,
        period=period,
        cut_date=cut_date_for(period, cut),
        due_date=due_date_for(period, cut, due),
        charges=total(i.amount for i in rows),
        others_share=D(others),
        paid=total(p.amount for p in payments),
        installments=list(rows),
    )


async def credit_cards(session: AsyncSession) -> list[Account]:
    return list(
        (
            await session.execute(
                select(Account)
                .where(Account.type == ACCOUNT_CREDIT, Account.active.is_(True))
                .order_by(Account.name)
            )
        ).scalars().all()
    )


async def all_statements(session: AsyncSession, period: str) -> list[StatementSummary]:
    return [await statement(session, card, period) for card in await credit_cards(session)]


async def future_commitments(
    session: AsyncSession, account: Account, from_period: str, months: int = 12
) -> list[tuple[str, Decimal]]:
    """Cuotas ya comprometidas hacia adelante (útil para diferidos)."""
    periods = [add_months(from_period, i) for i in range(months)]
    rows = (
        await session.execute(
            select(Installment).where(
                Installment.account_id == account.id,
                Installment.statement_period.in_(periods),
            )
        )
    ).scalars().all()
    by_period: dict[str, Decimal] = {p: ZERO for p in periods}
    for inst in rows:
        by_period[inst.statement_period] = D(
            by_period[inst.statement_period] + D(inst.amount)
        )
    return [(p, by_period[p]) for p in periods]


async def card_balance(session: AsyncSession, account: Account) -> Decimal:
    """Saldo total pendiente de la tarjeta (todo lo cargado menos todo lo pagado)."""
    charges = (
        await session.execute(
            select(Installment.amount).where(Installment.account_id == account.id)
        )
    ).scalars().all()
    payments = (
        await session.execute(
            select(CardPayment.amount).where(CardPayment.account_id == account.id)
        )
    ).scalars().all()
    return D(total(charges) - total(payments))
