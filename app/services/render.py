"""Render de borradores y textos que necesitan tocar la base de datos."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.money import D
from app.models import ACCOUNT_CREDIT, KIND_EXPENSE, Account, Category, Person
from app.services.cards import place_purchase
from app.services.format import draft_summary, placement_text


async def describe_draft(session: AsyncSession, payload: dict) -> tuple[str, bool]:
    category_name = ""
    if payload.get("category_id"):
        cat = await session.get(Category, payload["category_id"])
        if cat:
            category_name = cat.label()
    account_name = ""
    placement = None
    if payload.get("account_id"):
        acc = await session.get(Account, payload["account_id"])
        if acc:
            account_name = acc.name
            if acc.type == ACCOUNT_CREDIT and payload["kind"] == KIND_EXPENSE:
                placement = place_purchase(
                    acc,
                    dt.date.fromisoformat(payload["date"]),
                    D(payload["amount"]),
                    int(payload.get("installments") or 1),
                )

    people_names: list[str] = []
    ids = payload.get("people_ids") or []
    if ids and payload.get("split_mode"):
        rows = (
            await session.execute(select(Person).where(Person.id.in_(ids)))
        ).scalars().all()
        people_names = [p.name for p in rows]

    described = dict(payload, placement=placement_text(placement) if placement else "")
    text = draft_summary(described, category_name, account_name, people_names)
    return text, bool(payload.get("items"))
