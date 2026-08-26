"""Gastos fijos e ingresos recurrentes: materialización mes a mes."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ACCOUNT_CREDIT,
    KIND_EXPENSE,
    KIND_INCOME,
    STATUS_DONE,
    STATUS_PLANNED,
    Account,
    FixedExpense,
    RecurringIncome,
    Transaction,
)
from app.money import D
from app.services.cards import build_installments
from app.services.periods import clamp_day, in_range, parse_period, today


async def ensure_period_materialized(session: AsyncSession, period: str) -> list[Transaction]:
    """Crea las transacciones 'planeadas' del mes para fijos e ingresos recurrentes.

    Es idempotente: si ya existe la transacción de ese fijo en ese mes, no hace nada.
    """
    year, month = parse_period(period)
    created: list[Transaction] = []

    fixed = (
        await session.execute(select(FixedExpense).where(FixedExpense.active.is_(True)))
    ).scalars().all()
    existing_fixed = set(
        (
            await session.execute(
                select(Transaction.fixed_expense_id).where(
                    Transaction.period == period,
                    Transaction.fixed_expense_id.is_not(None),
                )
            )
        ).scalars().all()
    )
    for item in fixed:
        if item.id in existing_fixed:
            continue
        if not in_range(period, item.start_period, item.end_period):
            continue
        tx = Transaction(
            kind=KIND_EXPENSE,
            status=STATUS_PLANNED,
            date=clamp_day(year, month, item.due_day),
            amount=D(item.amount),
            description=item.name,
            category_id=item.category_id,
            account_id=item.account_id,
            fixed_expense_id=item.id,
            period=period,
            source="fixed",
        )
        session.add(tx)
        created.append(tx)

    incomes = (
        await session.execute(
            select(RecurringIncome).where(RecurringIncome.active.is_(True))
        )
    ).scalars().all()
    existing_income = set(
        (
            await session.execute(
                select(Transaction.recurring_income_id).where(
                    Transaction.period == period,
                    Transaction.recurring_income_id.is_not(None),
                )
            )
        ).scalars().all()
    )
    for item in incomes:
        if item.id in existing_income:
            continue
        if not in_range(period, item.start_period, item.end_period):
            continue
        tx = Transaction(
            kind=KIND_INCOME,
            status=STATUS_PLANNED,
            date=clamp_day(year, month, item.pay_day),
            amount=D(item.amount),
            description=item.name,
            account_id=item.account_id,
            recurring_income_id=item.id,
            period=period,
            income_type="sueldo",
            source="fixed",
        )
        session.add(tx)
        created.append(tx)

    await session.flush()
    return created


async def mark_paid(
    session: AsyncSession,
    transaction: Transaction,
    date: dt.date | None = None,
    account_id: int | None = None,
) -> Transaction:
    """Confirma un gasto/ingreso planeado. Si va con tarjeta, genera la cuota."""
    transaction.status = STATUS_DONE
    if date:
        transaction.date = date
    if account_id:
        transaction.account_id = account_id
    if transaction.account_id and not transaction.installments:
        account = await session.get(Account, transaction.account_id)
        if account and account.type == ACCOUNT_CREDIT and transaction.kind == KIND_EXPENSE:
            for inst in build_installments(transaction, account):
                session.add(inst)
    await session.flush()
    return transaction


async def pending_this_month(session: AsyncSession, period: str) -> list[Transaction]:
    await ensure_period_materialized(session, period)
    rows = (
        await session.execute(
            select(Transaction)
            .where(
                Transaction.period == period,
                Transaction.status == STATUS_PLANNED,
                Transaction.kind == KIND_EXPENSE,
            )
            .order_by(Transaction.date)
        )
    ).scalars().all()
    return list(rows)


async def upcoming(session: AsyncSession, days: int = 7) -> list[Transaction]:
    """Fijos que vencen en los próximos `days` días y siguen pendientes."""
    ref = today()
    limit = ref + dt.timedelta(days=days)
    rows = (
        await session.execute(
            select(Transaction)
            .where(
                Transaction.status == STATUS_PLANNED,
                Transaction.kind == KIND_EXPENSE,
                Transaction.date >= ref,
                Transaction.date <= limit,
            )
            .order_by(Transaction.date)
        )
    ).scalars().all()
    return list(rows)


async def overdue(session: AsyncSession) -> list[Transaction]:
    rows = (
        await session.execute(
            select(Transaction)
            .where(
                Transaction.status == STATUS_PLANNED,
                Transaction.kind == KIND_EXPENSE,
                Transaction.date < today(),
            )
            .order_by(Transaction.date)
        )
    ).scalars().all()
    return list(rows)
