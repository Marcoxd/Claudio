"""División de cuentas compartidas: por partes iguales, por ítems o a medida."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    SPLIT_CUSTOM,
    SPLIT_EQUAL,
    SPLIT_ITEMS,
    Person,
    Settlement,
    Split,
    SplitShare,
    Transaction,
)
from app.money import D, ZERO, prorate, split_evenly, total
from app.services.periods import today

ME = None  # clave del participante "yo"


@dataclass
class ShareResult:
    person_id: int | None
    amount: Decimal
    item_ids: list[int]


def _attach(tx: Transaction, mode: str, include_me: bool, results: list[ShareResult],
            note: str | None = None) -> Split:
    """Reemplaza la división de una transacción por `results`."""
    split = Split(mode=mode, include_me=include_me, note=note)
    split.shares = [
        SplitShare(
            person_id=r.person_id,
            amount=r.amount,
            item_ids=",".join(str(i) for i in r.item_ids) or None,
            settled=r.person_id is None,
        )
        for r in results
    ]
    tx.split = split
    mine = next((r.amount for r in results if r.person_id is ME), ZERO)
    tx.my_share = D(mine)
    return split


def equal_split(
    tx: Transaction, person_ids: list[int], include_me: bool = True
) -> list[ShareResult]:
    participants: list[int | None] = ([ME] if include_me else []) + list(person_ids)
    if not participants:
        return [ShareResult(ME, D(tx.amount), [])]
    amounts = split_evenly(D(tx.amount), len(participants))
    return [ShareResult(p, a, []) for p, a in zip(participants, amounts)]


def custom_split(
    tx: Transaction, amounts: dict[int | None, Decimal]
) -> list[ShareResult]:
    """Montos explícitos por persona; el resto (si falta) queda para mí."""
    results = [ShareResult(pid, D(amt), []) for pid, amt in amounts.items()]
    assigned = total(r.amount for r in results)
    rest = D(D(tx.amount) - assigned)
    if rest != 0:
        mine = next((r for r in results if r.person_id is ME), None)
        if mine:
            mine.amount = D(mine.amount + rest)
        else:
            results.insert(0, ShareResult(ME, rest, []))
    return results


def items_split(
    tx: Transaction,
    assignment: dict[int, list[int | None]],
    include_me: bool = True,
) -> list[ShareResult]:
    """Divide por ítems de la factura.

    `assignment` mapea id de ítem -> lista de participantes que lo consumieron
    (None = yo). Impuestos, propina, descuentos y cualquier diferencia contra el
    total se prorratean según lo consumido por cada quien.
    """
    items = {i.id: i for i in tx.items if i.kind == "item"}
    extras = [i for i in tx.items if i.kind != "item"]

    subtotals: dict[int | None, Decimal] = {}
    owned: dict[int | None, list[int]] = {}
    for item_id, participants in assignment.items():
        item = items.get(item_id)
        if item is None or not participants:
            continue
        parts = split_evenly(D(item.total), len(participants))
        for participant, part in zip(participants, parts):
            subtotals[participant] = D(subtotals.get(participant, ZERO) + part)
            owned.setdefault(participant, []).append(item_id)

    if include_me and ME not in subtotals:
        subtotals[ME] = ZERO
        owned.setdefault(ME, [])

    if not subtotals:
        return [ShareResult(ME, D(tx.amount), [])]

    keys = list(subtotals.keys())
    base = total(subtotals.values())
    extra_amount = D(D(tx.amount) - base)  # impuestos + propina - descuentos + ajuste
    del extras  # ya está contenido en la diferencia contra el total
    spread = prorate(extra_amount, [subtotals[k] for k in keys]) if extra_amount else [ZERO] * len(keys)

    return [
        ShareResult(k, D(subtotals[k] + s), owned.get(k, []))
        for k, s in zip(keys, spread)
    ]


def apply_split(
    tx: Transaction,
    mode: str,
    *,
    person_ids: list[int] | None = None,
    include_me: bool = True,
    assignment: dict[int, list[int | None]] | None = None,
    amounts: dict[int | None, Decimal] | None = None,
    note: str | None = None,
) -> Split:
    if mode == SPLIT_EQUAL:
        results = equal_split(tx, person_ids or [], include_me)
    elif mode == SPLIT_ITEMS:
        results = items_split(tx, assignment or {}, include_me)
    elif mode == SPLIT_CUSTOM:
        results = custom_split(tx, amounts or {})
    else:
        raise ValueError(f"modo de división desconocido: {mode}")
    results = [r for r in results if r.amount != 0 or r.person_id is ME]
    return _attach(tx, mode, include_me, results, note)


def clear_split(tx: Transaction) -> None:
    tx.split = None
    tx.my_share = None


# ------------------------------------------------------------------ deudas


@dataclass
class PersonBalance:
    person: Person
    owes_me: Decimal
    shares: list[SplitShare]


async def balances(session: AsyncSession) -> list[PersonBalance]:
    """Cuánto me debe cada persona por gastos compartidos sin saldar."""
    rows = (
        await session.execute(
            select(SplitShare)
            .options(
                selectinload(SplitShare.person),
                selectinload(SplitShare.split).selectinload(Split.transaction),
            )
            .where(SplitShare.person_id.is_not(None), SplitShare.settled.is_(False))
        )
    ).scalars().all()

    grouped: dict[int, list[SplitShare]] = {}
    for share in rows:
        grouped.setdefault(share.person_id, []).append(share)

    out: list[PersonBalance] = []
    for person_id, shares in grouped.items():
        person = shares[0].person
        if person is None:
            continue
        out.append(
            PersonBalance(person=person, owes_me=total(s.amount for s in shares), shares=shares)
        )
    out.sort(key=lambda b: b.owes_me, reverse=True)
    return out


async def settle_person(
    session: AsyncSession,
    person_id: int,
    amount: Decimal | None = None,
    date: dt.date | None = None,
    note: str | None = None,
) -> Decimal:
    """Registra que una persona me pagó. Salda las deudas más antiguas primero.

    Con `amount=None` salda todo lo pendiente. Devuelve el monto saldado.
    """
    date = date or today()
    pending = (
        await session.execute(
            select(SplitShare)
            .where(SplitShare.person_id == person_id, SplitShare.settled.is_(False))
            .order_by(SplitShare.id)
        )
    ).scalars().all()

    remaining = total(s.amount for s in pending) if amount is None else D(amount)
    settled = ZERO
    for share in pending:
        if remaining <= 0:
            break
        if D(share.amount) <= remaining:
            share.settled = True
            share.settled_at = date
            remaining = D(remaining - D(share.amount))
            settled = D(settled + D(share.amount))
        else:
            # pago parcial: se parte la deuda en dos
            rest = D(D(share.amount) - remaining)
            share.amount = remaining
            share.settled = True
            share.settled_at = date
            session.add(
                SplitShare(
                    split_id=share.split_id,
                    person_id=share.person_id,
                    amount=rest,
                    item_ids=share.item_ids,
                    settled=False,
                )
            )
            settled = D(settled + remaining)
            remaining = ZERO

    session.add(
        Settlement(person_id=person_id, date=date, amount=settled, note=note)
    )
    await session.flush()
    return settled


async def get_or_create_person(session: AsyncSession, name: str) -> Person:
    name = name.strip()
    person = (
        await session.execute(
            select(Person).where(func.lower(Person.name) == name.lower())
        )
    ).scalar_one_or_none()
    if person is None:
        person = Person(name=name)
        session.add(person)
        await session.flush()
    return person
