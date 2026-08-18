"""Singleton guard for scheduler processes.

PostgreSQL uses a connection-scoped advisory lock. SQLite and other local
backends use a non-blocking OS file lock, which is safe across processes on a
single host and requires no database schema or production service.
"""
from __future__ import annotations

import asyncio
import fcntl
import os
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import text

from ..db.connection import get_engine

_LOCK_KEY = 7_481_293


class InProcessSchedulerLock:
    """Small synchronous compatibility lock for callers needing local-only guard."""

    def __init__(self) -> None:
        self._held = False

    def acquire(self) -> bool:
        if self._held:
            return False
        self._held = True
        return True

    def release(self) -> None:
        self._held = False


class SchedulerSingletonLock:
    """Keep at most one scheduler active per process/database or host."""

    def __init__(self, database_url: str | None = None, engine=None) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL", "")
        self.engine = engine
        self.connection = None
        self._context = None
        self._file = None

    def _is_postgres(self) -> bool:
        if self.engine is not None:
            dialect = getattr(self.engine, "dialect", None)
            if dialect is not None:
                return getattr(dialect, "name", "") == "postgresql"
        return urlparse(self.database_url).scheme.startswith(("postgres", "postgresql"))

    async def acquire(self) -> bool:
        if self._is_postgres():
            engine = self.engine or get_engine()
            context = engine.connect()
            connection = await context.__aenter__()
            try:
                result = await connection.execute(
                    text("SELECT pg_try_advisory_lock(:lock_key)"),
                    {"lock_key": _LOCK_KEY},
                )
                if not result.scalar_one():
                    await context.__aexit__(None, None, None)
                    return False
            except Exception:
                await context.__aexit__(None, None, None)
                raise
            self.connection = connection
            self._context = context
            return True

        path = Path(os.getenv("SCHEDULER_LOCK_FILE", "/tmp/k9-overwatch-scheduler.lock"))
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handle = await asyncio.to_thread(path.open, "a+")
        try:
            await asyncio.to_thread(fcntl.flock, file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            await asyncio.to_thread(file_handle.close)
            return False
        self._file = file_handle
        return True

    async def release(self) -> None:
        if self.connection is not None:
            try:
                await self.connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": _LOCK_KEY},
                )
            finally:
                if self._context is not None:
                    await self._context.__aexit__(None, None, None)
                self._context = None
                self.connection = None
        if self._file is not None:
            try:
                await asyncio.to_thread(fcntl.flock, self._file.fileno(), fcntl.LOCK_UN)
            finally:
                await asyncio.to_thread(self._file.close)
                self._file = None
