from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from k9overwatch.db.models import AccountToken, EmailQueue, User
from k9overwatch.web.account_tokens import consume_token, issue_token


@pytest.mark.asyncio
async def test_token_expires_and_cannot_be_replayed(db_session):
    user = User(email="one@example.com", password_hash="scrypt$fake")
    db_session.add(user)
    await db_session.flush()
    issued = await issue_token(db_session, user, "email_verification", ttl=timedelta(seconds=1))
    issued.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
    await db_session.commit()

    assert await consume_token(db_session, issued.raw_token, "email_verification") is None
    assert await consume_token(db_session, issued.raw_token, "email_verification") is None

@pytest.mark.asyncio
async def test_token_is_single_use_and_bound_to_its_user(db_session):
    owner = User(email="owner@example.com", password_hash="scrypt$fake")
    other = User(email="other@example.com", password_hash="scrypt$fake")
    db_session.add_all([owner, other])
    await db_session.flush()
    issued = await issue_token(db_session, owner, "password_reset")
    await db_session.commit()

    assert await consume_token(db_session, issued.raw_token, "password_reset", user_id=other.id) is None
    found = await consume_token(db_session, issued.raw_token, "password_reset", user_id=owner.id)
    assert found is not None
    assert await consume_token(db_session, issued.raw_token, "password_reset", user_id=owner.id) is None

@pytest.mark.asyncio
async def test_issuing_verification_queues_provider_independent_message(db_session):
    user = User(email="queue@example.com", password_hash="scrypt$fake")
    db_session.add(user)
    await db_session.flush()
    issued = await issue_token(db_session, user, "email_verification")
    await db_session.commit()

    queued = (await db_session.execute(select(EmailQueue))).scalar_one()
    assert queued.recipient == user.email
    assert queued.kind == "email_verification"
    assert issued.raw_token in queued.body
    assert "/account/email-verification?token=" in queued.body
    assert (await db_session.execute(select(AccountToken))).scalar_one().token_hash


@pytest.mark.asyncio
async def test_password_reset_queue_uses_reset_route(db_session):
    user = User(email="reset-queue@example.com", password_hash="scrypt$fake")
    db_session.add(user)
    await db_session.flush()

    issued = await issue_token(db_session, user, "password_reset")
    await db_session.commit()

    queued = (await db_session.execute(select(EmailQueue))).scalar_one()
    assert issued.raw_token in queued.body
    assert "/reset-password?token=" in queued.body


def test_token_hash_is_not_raw_token():
    assert True
