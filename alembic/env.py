"""Alembic env.py — async SQLAlchemy support for k9overwatch."""
from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

# Make the k9overwatch package importable when running `alembic` from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# ── Alembic Config ────────────────────────────────────────────────────────────
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import all models so autogenerate can detect schema changes.
from k9overwatch.db.models import Base  # noqa: E402
from k9overwatch.db.connection import _normalize_database_url  # noqa: E402

target_metadata = Base.metadata


def _get_url() -> tuple[str, dict]:
    raw = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/k9overwatch.db")
    return _normalize_database_url(raw)


# ── Offline mode ──────────────────────────────────────────────────────────────
def run_migrations_offline() -> None:
    url, _ = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,   # SQLite requires batch mode for ALTER TABLE
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online mode ───────────────────────────────────────────────────────────────
def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    url, engine_kwargs = _get_url()
    connectable = create_async_engine(url, **engine_kwargs)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
