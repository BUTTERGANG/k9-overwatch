"""SQLAlchemy async engine and session factory."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

load_dotenv()

_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/k9overwatch.db")
        connect_args = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_async_engine(url, echo=False, connect_args=connect_args)
    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _session_factory


@asynccontextmanager
async def get_session():
    """Async context manager yielding an AsyncSession."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """Create all tables if they don't exist."""
    import os
    os.makedirs("data", exist_ok=True)
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Backfill schema for existing dev DBs: add columns/tables added after first
    # deploy. Guarded so it's safe to run every startup.
    await _migrate_existing_db()


async def _migrate_existing_db():
    """Idempotent schema migrations for SQLite dev DBs created before new columns."""
    from sqlalchemy import text

    async with get_engine().connect() as conn:
        # owner_id column on pets (accounts feature)
        existing_cols = await conn.run_sync(
            lambda c: [r[1] for r in c.execute(text("PRAGMA table_info(pets)")).fetchall()]
        )
        if "owner_id" not in existing_cols:
            await conn.execute(text("ALTER TABLE pets ADD COLUMN owner_id TEXT"))
        # New tables (users, notification_prefs)
        await conn.run_sync(Base.metadata.create_all)
        await conn.commit()
