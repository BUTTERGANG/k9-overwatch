"""In-process rate limiting for sensitive, unauthenticated routes.

Fixed-window counter keyed by client IP + route name. Deliberately in-memory —
adequate for the current single-process deployment (see scheduler/lock.py for
the same single-instance assumption elsewhere in this codebase). If this ever
runs behind multiple workers/replicas, back this with a shared store instead.
"""
from __future__ import annotations

import time

from fastapi import HTTPException, Request, status

_WINDOW_SECONDS = 60
_buckets: dict[str, list[float]] = {}


def reset() -> None:
    """Clear all tracked windows. Used by tests to avoid cross-test bleed."""
    _buckets.clear()


def rate_limit(name: str, limit: int, window_seconds: int = _WINDOW_SECONDS):
    """FastAPI dependency factory: at most `limit` requests per `window_seconds` per client IP."""

    async def _check(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        key = f"{name}:{ip}"
        now = time.monotonic()
        cutoff = now - window_seconds
        bucket = _buckets.setdefault(key, [])
        while bucket and bucket[0] < cutoff:
            bucket.pop(0)
        if len(bucket) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
            )
        bucket.append(now)

    return _check
