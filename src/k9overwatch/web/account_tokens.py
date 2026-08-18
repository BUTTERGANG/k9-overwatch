"""Secure account-action tokens and provider-independent email queueing."""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.models import AccountToken, EmailQueue, User

TOKEN_TTLS = {"email_verification": timedelta(hours=24), "password_reset": timedelta(hours=1)}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


async def issue_token(
    db: AsyncSession, user: User, purpose: str, *, ttl: timedelta | None = None
) -> AccountToken:
    if purpose not in TOKEN_TTLS:
        raise ValueError("unsupported token purpose")
    raw_token = secrets.token_urlsafe(32)
    token = AccountToken(
        user_id=user.id,
        purpose=purpose,
        token_hash=_hash(raw_token),
        expires_at=_now() + (ttl or TOKEN_TTLS[purpose]),
    )
    db.add(token)
    await db.flush()
    token.raw_token = raw_token
    action = "verify your email" if purpose == "email_verification" else "reset your password"
    route = {
        "email_verification": "/account/email-verification",
        "password_reset": "/reset-password",
    }[purpose]
    db.add(EmailQueue(
        user_id=user.id,
        recipient=user.email,
        kind=purpose,
        subject=f"K9-Overwatch: {action}",
        body=f"Use this one-time link to {action}: {route}?token={raw_token}",
    ))
    return token


async def consume_token(
    db: AsyncSession, raw_token: str, purpose: str, *, user_id: str | None = None
) -> AccountToken | None:
    now = _now()
    conditions = [
        AccountToken.token_hash == _hash(raw_token),
        AccountToken.purpose == purpose,
        AccountToken.used_at.is_(None),
        AccountToken.expires_at > now,
    ]
    if user_id:
        conditions.append(AccountToken.user_id == user_id)
    result = await db.execute(
        update(AccountToken)
        .where(*conditions)
        .values(used_at=now)
    )
    if result.rowcount != 1:
        return None
    await db.flush()
    return (await db.execute(select(AccountToken).where(
        AccountToken.token_hash == _hash(raw_token), AccountToken.purpose == purpose,
    ))).scalar_one()
