"""Motor de base de datos y sesión async."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models import Base

_url = settings.database_url
if _url.startswith("sqlite"):
    path = _url.split("///", 1)[-1]
    if path and path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(
    _url,
    echo=os.getenv("SQL_ECHO") == "1",
    pool_pre_ping=not _url.startswith("sqlite"),
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from app.services.seed import seed_defaults

    async with session_scope() as s:
        await seed_defaults(s)
