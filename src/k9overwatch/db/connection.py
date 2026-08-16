"""SQLAlchemy async engine and session factory."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

load_dotenv()

_engine = None
_session_factory = None


def _normalize_database_url(url: str) -> tuple[str, dict]:
    """
    Ensure the URL uses an async-compatible driver scheme.
    Returns (normalized_url, engine_kwargs).
    asyncpg does not support libpq query params like sslmode — strip them
    and translate to engine kwargs instead.
    """
    engine_kwargs: dict = {}

    if url.startswith("postgresql://") or url.startswith("postgres://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("sqlite://") and "+aiosqlite" not in url:
        url = url.replace("sqlite://", "sqlite+aiosqlite://", 1)

    # asyncpg does not support libpq query params — strip them all
    # and translate the important ones to connect_args instead.
    if url.startswith("postgresql+asyncpg://"):
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)

        sslmode = params.pop("sslmode", [None])[0]
        # Strip other libpq-only params asyncpg rejects
        for libpq_param in ("channel_binding", "sslcert", "sslkey", "sslrootcert",
                             "connect_timeout", "options", "gssencmode"):
            params.pop(libpq_param, None)

        # Translate sslmode → asyncpg ssl connect_arg
        if sslmode in ("require", "verify-ca", "verify-full"):
            engine_kwargs["connect_args"] = {"ssl": True}
        elif sslmode == "disable":
            engine_kwargs["connect_args"] = {"ssl": False}

        new_query = urlencode({k: v[0] for k, v in params.items()})
        url = urlunparse(parsed._replace(query=new_query))

    return url, engine_kwargs


def get_engine():
    global _engine
    if _engine is None:
        raw_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/k9overwatch.db")
        url, engine_kwargs = _normalize_database_url(raw_url)
        if url.startswith("sqlite"):
            engine_kwargs.setdefault("connect_args", {})["check_same_thread"] = False
        _engine = create_async_engine(url, echo=False, **engine_kwargs)
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
    raw_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/k9overwatch.db")
    normalized_url, _ = _normalize_database_url(raw_url)
    if normalized_url.startswith("sqlite"):
        os.makedirs("data", exist_ok=True)
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Backfill schema for existing dev DBs: add columns/tables added after first
    # deploy. Guarded so it's safe to run every startup.
    await _migrate_existing_db()


async def _migrate_existing_db():
    """Idempotent schema migrations for dev/prod DBs created before new columns."""
    from sqlalchemy import inspect, text

    async with get_engine().connect() as conn:
        # owner_id column on pets (accounts feature). Uses SQLAlchemy's reflection
        # API rather than raw PRAGMA so this works on both SQLite and Postgres.
        existing_cols = await conn.run_sync(
            lambda c: [col["name"] for col in inspect(c).get_columns("pets")]
        )
        if "owner_id" not in existing_cols:
            await conn.execute(text("ALTER TABLE pets ADD COLUMN owner_id TEXT"))
        if "owner_report_status" not in existing_cols:
            await conn.execute(text("ALTER TABLE pets ADD COLUMN owner_report_status TEXT"))
        # New tables (users, notification_prefs)
        await conn.run_sync(Base.metadata.create_all)
        # Add the map query index for existing SQLite databases. PostgreSQL
        # deployments should use their migration system for this index.
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_pets_active_date_lat_lon "
            "ON pets (active, date_event, lat, lon)"
        ))
        await conn.commit()
