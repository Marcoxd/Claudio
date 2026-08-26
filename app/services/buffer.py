"""El colchón: dinero que uso pero que no es mío."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import BUFFER_ADJUST, BUFFER_REPAY, BUFFER_USE, BufferMovement, Setting
from app.money import D, ZERO, total
from app.services.periods import today

TOTAL_KEY = "buffer_total"


@dataclass
class BufferState:
    total: Decimal      # cuánto dinero ajeno tengo asignado al colchón
    used: Decimal       # cuánto he sacado
    repaid: Decimal     # cuánto he repuesto
    name: str

    @property
    def debt(self) -> Decimal:
        """Lo que me falta reponer."""
        return D(max(ZERO, D(self.used - self.repaid)))

    @property
    def available(self) -> Decimal:
        return D(self.total - self.debt)

    @property
    def pct_used(self) -> float:
        if self.total <= 0:
            return 0.0
        return float(min(Decimal("1"), self.debt / self.total)) * 100


async def get_total(session: AsyncSession) -> Decimal:
    row = (
        await session.execute(select(Setting).where(Setting.key == TOTAL_KEY))
    ).scalar_one_or_none()
    if row is None:
        return D(settings.buffer_initial)
    return D(row.value or 0)


async def set_total(session: AsyncSession, amount: Decimal) -> Decimal:
    amount = D(amount)
    row = (
        await session.execute(select(Setting).where(Setting.key == TOTAL_KEY))
    ).scalar_one_or_none()
    if row is None:
        session.add(Setting(key=TOTAL_KEY, value=str(amount)))
    else:
        row.value = str(amount)
    session.add(
        BufferMovement(date=today(), direction=BUFFER_ADJUST, amount=amount,
                       note="Ajuste del total del colchón")
    )
    await session.flush()
    return amount


async def state(session: AsyncSession) -> BufferState:
    moves = (await session.execute(select(BufferMovement))).scalars().all()
    return BufferState(
        total=await get_total(session),
        used=total(m.amount for m in moves if m.direction == BUFFER_USE),
        repaid=total(m.amount for m in moves if m.direction == BUFFER_REPAY),
        name=settings.buffer_name,
    )


async def move(
    session: AsyncSession,
    direction: str,
    amount: Decimal,
    note: str | None = None,
    date: dt.date | None = None,
    transaction_id: int | None = None,
) -> BufferMovement:
    mv = BufferMovement(
        date=date or today(),
        direction=direction,
        amount=D(amount),
        note=note,
        transaction_id=transaction_id,
    )
    session.add(mv)
    await session.flush()
    return mv


async def use(session: AsyncSession, amount, note=None, date=None, transaction_id=None):
    return await move(session, BUFFER_USE, amount, note, date, transaction_id)


async def repay(session: AsyncSession, amount, note=None, date=None):
    return await move(session, BUFFER_REPAY, amount, note, date)


async def history(session: AsyncSession, limit: int = 30) -> list[BufferMovement]:
    rows = (
        await session.execute(
            select(BufferMovement)
            .where(BufferMovement.direction != BUFFER_ADJUST)
            .order_by(BufferMovement.date.desc(), BufferMovement.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)
