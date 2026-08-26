"""Datos iniciales: categorías y cuentas por defecto."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ACCOUNT_CASH, KIND_EXPENSE, KIND_INCOME, Account, Category

DEFAULT_CATEGORIES: list[tuple[str, str, str, bool]] = [
    # (nombre, emoji, tipo, esencial)
    ("Comida", "🍽️", KIND_EXPENSE, False),
    ("Supermercado", "🛒", KIND_EXPENSE, True),
    ("Transporte", "🚗", KIND_EXPENSE, True),
    ("Combustible", "⛽", KIND_EXPENSE, True),
    ("Vivienda", "🏠", KIND_EXPENSE, True),
    ("Servicios", "💡", KIND_EXPENSE, True),
    ("Internet y teléfono", "📶", KIND_EXPENSE, True),
    ("Salud", "💊", KIND_EXPENSE, True),
    ("Educación", "📚", KIND_EXPENSE, False),
    ("Entretenimiento", "🎬", KIND_EXPENSE, False),
    ("Ropa", "👕", KIND_EXPENSE, False),
    ("Suscripciones", "🔁", KIND_EXPENSE, False),
    ("Mascotas", "🐾", KIND_EXPENSE, False),
    ("Regalos", "🎁", KIND_EXPENSE, False),
    ("Préstamos", "🏦", KIND_EXPENSE, True),
    ("Tarjeta de crédito", "💳", KIND_EXPENSE, True),
    ("Otros", "📦", KIND_EXPENSE, False),
    ("Sueldo", "💼", KIND_INCOME, False),
    ("Asesoramiento", "🧑‍💻", KIND_INCOME, False),
    ("Extras", "✨", KIND_INCOME, False),
]

DEFAULT_ACCOUNTS = [("Efectivo", ACCOUNT_CASH)]


async def seed_defaults(session: AsyncSession) -> None:
    existing = set(
        (await session.execute(select(Category.name))).scalars().all()
    )
    for name, emoji, kind, essential in DEFAULT_CATEGORIES:
        if name not in existing:
            session.add(
                Category(name=name, emoji=emoji, kind=kind, is_essential=essential)
            )

    accounts = set((await session.execute(select(Account.name))).scalars().all())
    for name, type_ in DEFAULT_ACCOUNTS:
        if name not in accounts:
            session.add(Account(name=name, type=type_))
    await session.flush()
