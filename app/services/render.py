"""Render de borradores y textos que necesitan tocar la base de datos."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, Category, Person
from app.services.format import draft_summary


async def describe_draft(session: AsyncSession, payload: dict) -> tuple[str, bool]:
    category_name = ""
    if payload.get("category_id"):
        cat = await session.get(Category, payload["category_id"])
        if cat:
            category_name = cat.label()
    account_name = ""
    if payload.get("account_id"):
        acc = await session.get(Account, payload["account_id"])
        if acc:
            account_name = acc.name

    people_names: list[str] = []
    ids = payload.get("people_ids") or []
    if ids and payload.get("split_mode"):
        rows = (
            await session.execute(select(Person).where(Person.id.in_(ids)))
        ).scalars().all()
        people_names = [p.name for p in rows]

    text = draft_summary(payload, category_name, account_name, people_names)
    return text, bool(payload.get("items"))
