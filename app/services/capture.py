"""Pipeline de captura: de lo que interpretó la IA a una transacción guardada."""
from __future__ import annotations

import datetime as dt
import json
import unicodedata
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ACCOUNT_CREDIT,
    KIND_EXPENSE,
    KIND_INCOME,
    SPLIT_EQUAL,
    STATUS_DONE,
    Account,
    Category,
    Draft,
    Person,
    ReceiptItem,
    Transaction,
)
from app.money import D, total
from app.services import buffer as buffer_service
from app.services.ai import ParsedCapture
from app.services.cards import build_installments
from app.services.periods import period_of, today
from app.services.splits import apply_split


def _flat(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", (text or "").lower())
        if unicodedata.category(c) != "Mn"
    ).strip()


async def build_context(session: AsyncSession) -> dict:
    cats = (await session.execute(select(Category))).scalars().all()
    accounts = (
        await session.execute(select(Account).where(Account.active.is_(True)))
    ).scalars().all()
    people = (
        await session.execute(select(Person).where(Person.active.is_(True)))
    ).scalars().all()
    from app.config import settings

    return {
        "today": today().isoformat(),
        "currency": settings.currency,
        "categories": [c.name for c in cats],
        "accounts": [c.name + (f" ({c.alias})" if c.alias else "") for c in accounts],
        "people": [p.name for p in people],
    }


async def _match_category(session: AsyncSession, name: str, kind: str) -> int | None:
    if not name:
        return None
    cats = (await session.execute(select(Category))).scalars().all()
    target = _flat(name)
    for c in cats:
        if _flat(c.name) == target:
            return c.id
    for c in cats:
        if target and (target in _flat(c.name) or _flat(c.name) in target):
            return c.id
    default = "Otros" if kind == KIND_EXPENSE else "Extras"
    return next((c.id for c in cats if c.name == default), None)


async def _match_account(session: AsyncSession, name: str) -> int | None:
    if not name:
        return None
    accounts = (
        await session.execute(select(Account).where(Account.active.is_(True)))
    ).scalars().all()
    target = _flat(name)
    for a in accounts:
        if _flat(a.name) == target or (a.alias and _flat(a.alias) == target):
            return a.id
    for a in accounts:
        if target in _flat(a.name) or (a.alias and target in _flat(a.alias)):
            return a.id
        if _flat(a.name) in target:
            return a.id
    return None


async def default_account_id(session: AsyncSession) -> int | None:
    row = (
        await session.execute(
            select(Account).where(Account.active.is_(True)).order_by(Account.id)
        )
    ).scalars().first()
    return row.id if row else None


async def draft_from_parsed(
    session: AsyncSession,
    parsed: ParsedCapture,
    *,
    source: str = "text",
    raw_text: str = "",
    file_id: str | None = None,
) -> dict[str, Any]:
    kind = KIND_INCOME if parsed.kind == "income" else KIND_EXPENSE
    try:
        date = dt.date.fromisoformat(parsed.date) if parsed.date else today()
    except ValueError:
        date = today()
    if date > today() + dt.timedelta(days=1):
        date = today()

    account_id = await _match_account(session, parsed.account)
    if account_id is None:
        account_id = await default_account_id(session)

    people_ids: list[int] = []
    for name in parsed.people:
        person = (
            await session.execute(
                select(Person).where(Person.name.ilike(name.strip()))
            )
        ).scalar_one_or_none()
        if person is None:
            person = Person(name=name.strip().title())
            session.add(person)
            await session.flush()
        people_ids.append(person.id)

    items = [
        {
            "name": i.name[:150] or "Ítem",
            "quantity": float(i.quantity or 1),
            "unit_price": float(i.unit_price or 0),
            "total": float(i.total or 0),
            "kind": i.kind,
        }
        for i in parsed.items
        if (i.total or i.unit_price)
    ]

    amount = D(parsed.amount)
    if amount <= 0 and items:
        amount = total(i["total"] for i in items)

    return {
        "kind": kind,
        "amount": float(amount),
        "date": date.isoformat(),
        "description": (parsed.description or parsed.merchant or "Gasto")[:200],
        "merchant": parsed.merchant[:120] or None,
        "category_id": await _match_category(session, parsed.category, kind),
        "account_id": account_id,
        "installments": max(1, int(parsed.installments or 1)),
        "income_type": parsed.income_type or (None if kind == KIND_EXPENSE else "otro"),
        "items": items,
        "people_ids": people_ids,
        "split_mode": parsed.split_mode or ("equal" if people_ids else ""),
        "include_me": True,
        "buffer_direction": parsed.buffer_direction or "",
        "source": source,
        "raw_text": (raw_text or parsed.notes or "")[:2000],
        "file_id": file_id,
        "confidence": parsed.confidence,
        "notes": parsed.notes or "",
    }


async def commit_draft(session: AsyncSession, payload: dict[str, Any]) -> Transaction:
    """Persiste un borrador confirmado como transacción real."""
    date = dt.date.fromisoformat(payload["date"])
    tx = Transaction(
        kind=payload["kind"],
        status=STATUS_DONE,
        date=date,
        period=period_of(date),
        amount=D(payload["amount"]),
        description=payload["description"],
        merchant=payload.get("merchant"),
        category_id=payload.get("category_id"),
        account_id=payload.get("account_id"),
        installments_total=int(payload.get("installments") or 1),
        income_type=payload.get("income_type"),
        source=payload.get("source", "manual"),
        raw_text=payload.get("raw_text"),
        file_id=payload.get("file_id"),
        notes=payload.get("notes") or None,
    )
    for item in payload.get("items") or []:
        tx.items.append(
            ReceiptItem(
                name=item["name"],
                quantity=D(item.get("quantity") or 1),
                unit_price=D(item.get("unit_price") or 0) or None,
                total=D(item.get("total") or 0),
                kind=item.get("kind", "item"),
            )
        )
    session.add(tx)
    await session.flush()

    if payload.get("split_mode") == SPLIT_EQUAL and payload.get("people_ids"):
        apply_split(
            tx,
            SPLIT_EQUAL,
            person_ids=list(payload["people_ids"]),
            include_me=bool(payload.get("include_me", True)),
        )
        await session.flush()
    elif payload.get("assign"):
        from app.models import SPLIT_ITEMS

        line_items = [i for i in tx.items if i.kind == "item"]
        assignment: dict[int, list[int | None]] = {}
        for index, participants in payload["assign"].items():
            position = int(index)
            if position >= len(line_items):
                continue
            assignment[line_items[position].id] = [
                None if p in ("me", None) else int(p) for p in participants
            ]
        if assignment:
            apply_split(
                tx, SPLIT_ITEMS, assignment=assignment,
                include_me=bool(payload.get("include_me", True)),
            )
            await session.flush()
    elif payload.get("shares"):
        from app.models import SPLIT_CUSTOM

        amounts = {
            (None if k in ("me", "None", None) else int(k)): D(v)
            for k, v in payload["shares"].items()
        }
        apply_split(tx, SPLIT_CUSTOM, amounts=amounts)
        await session.flush()

    if tx.kind == KIND_EXPENSE and tx.account_id:
        account = await session.get(Account, tx.account_id)
        if account and account.type == ACCOUNT_CREDIT:
            for inst in build_installments(tx, account, tx.installments_total):
                session.add(inst)

    direction = payload.get("buffer_direction")
    if direction in ("use", "repay"):
        await buffer_service.move(
            session,
            direction,
            D(payload["amount"]),
            note=tx.description,
            date=date,
            transaction_id=tx.id,
        )

    await session.flush()
    return tx


# ------------------------------------------------------------------ drafts


async def save_draft(
    session: AsyncSession, user_id: int, chat_id: int, payload: dict, state: str = "review"
) -> Draft:
    draft = Draft(
        user_id=user_id,
        chat_id=chat_id,
        payload=json.dumps(payload, ensure_ascii=False, default=str),
        state=state,
    )
    session.add(draft)
    await session.flush()
    return draft


async def load_draft(session: AsyncSession, draft_id: int) -> tuple[Draft, dict] | tuple[None, None]:
    draft = await session.get(Draft, draft_id)
    if draft is None:
        return None, None
    return draft, json.loads(draft.payload)


async def update_draft(session: AsyncSession, draft: Draft, payload: dict, state: str | None = None) -> None:
    draft.payload = json.dumps(payload, ensure_ascii=False, default=str)
    if state:
        draft.state = state
    await session.flush()


async def delete_draft(session: AsyncSession, draft: Draft) -> None:
    await session.delete(draft)
    await session.flush()
