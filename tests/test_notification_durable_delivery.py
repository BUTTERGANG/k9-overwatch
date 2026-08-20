"""Durable delivery for reunion-critical notifications (match + contact).

These cover the gap that inline SMTP sending used to have: a match/contact
alert is persisted to the NotificationQueue and delivered by a worker with
bounded exponential backoff, so a transient provider outage never drops the
"we found your pet" email. The dedupe_key makes repeated matching passes
idempotent.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from k9overwatch.db.models import ContactRequest, NotificationQueue
from k9overwatch.db.repository import PetRepository, UserRepository
from k9overwatch.matching.signals import MatchResult
from k9overwatch.models.pet_record import PetRecord
from k9overwatch.notifications import (
    MatchEvent,
    notify_contact_request,
    notify_new_match,
)


async def _build_match_event(db_session, email="owner@example.com", pet_name="Rex"):
    """Create an instant-preference user + lost/found pair, returning the event."""
    users = UserRepository(db_session)
    user = await users.create(email, "password123", "Sam")
    await users.save_prefs(user.id, frequency="instant", min_confidence="low")
    repo = PetRepository(db_session)
    lost, _ = await repo.upsert(
        PetRecord(
            source="user",
            source_id="lost-durable-1",
            record_type="lost",
            animal_type="dog",
            name=pet_name,
            owner_id=user.id,
        ),
        owner_id=user.id,
    )
    found, _ = await repo.upsert(
        PetRecord(
            source="shelter",
            source_id="found-durable-1",
            record_type="found",
            animal_type="dog",
            name=pet_name,
            city="Indianapolis",
        )
    )
    await db_session.commit()
    result = MatchResult.from_signals(
        str(lost.id), str(found.id), "lost_found", {"name_exact": 0.4}
    )
    return MatchEvent(lost, found, result), user


async def _queued_rows(db_session) -> list[NotificationQueue]:
    rows = (await db_session.execute(select(NotificationQueue))).scalars().all()
    return list(rows)


@pytest.mark.asyncio
async def test_instant_match_notification_is_persisted_durably(db_session):
    event, _ = await _build_match_event(db_session)
    queued = await notify_new_match(db_session, event)

    assert queued is True
    rows = await _queued_rows(db_session)
    assert len(rows) == 1
    row = rows[0]
    assert row.kind == "match"
    assert row.status == "pending"
    assert row.attempts == 0
    assert row.user_id == event.lost_pet.owner_id
    assert "Rex" in row.body


@pytest.mark.asyncio
async def test_instant_match_dedupe_key_prevents_duplicate_enqueue(db_session):
    event, _ = await _build_match_event(db_session)

    first = await notify_new_match(db_session, event)
    second = await notify_new_match(db_session, event)

    assert first is True
    assert second is False  # same user + pet pair => suppressed
    assert len(await _queued_rows(db_session)) == 1


@pytest.mark.asyncio
async def test_match_notification_delivered_and_marked_sent(db_session):
    """In dev (no SMTP) the worker logs/skips but marks the alert sent, so the
    queue doesn't pile up with unsendable rows."""
    event, _ = await _build_match_event(db_session)
    assert (await notify_new_match(db_session, event)) is True

    from k9overwatch.notifications import flush_notification_queue

    sent = await flush_notification_queue(db_session)
    assert sent == 1
    rows = await _queued_rows(db_session)
    assert rows[0].status == "sent"
    assert rows[0].sent_at is not None
    assert rows[0].next_attempt_at is None


@pytest.mark.asyncio
async def test_delivery_failure_retries_with_backoff_then_gives_up(db_session):
    event, _ = await _build_match_event(db_session)
    assert (await notify_new_match(db_session, event)) is True
    row = (await _queued_rows(db_session))[0]
    repo = PetRepository(db_session)
    t0 = datetime(2026, 8, 20, 4, 0)

    for i in range(1, 6):  # exact max = 5 attempts
        claimed = await repo.claim_notification_queue(limit=10, now=t0)
        assert claimed and claimed[0].id == row.id
        claimed_row = claimed[0]
        assert claimed_row.attempts == i
        await repo.mark_notification_failed(
            claimed_row, f"provider down ({i})", now=t0
        )
        # Advance well past the largest backoff cap (3600s) so the next attempt
        # is eligible regardless of the exponential delay.
        t0 += timedelta(seconds=7200)

    assert row.attempts == 5
    assert row.status == "failed"
    assert row.next_attempt_at is None  # gave up after max attempts
    # No further claims are possible once attempts == max.
    assert await repo.claim_notification_queue(limit=10, now=t0) == []


@pytest.mark.asyncio
async def test_contact_notification_is_persisted_durably(db_session):
    users = UserRepository(db_session)
    recipient = await users.create("owner@example.com", "password123", "Sam")
    requester = await users.create("finder@example.com", "password123", "Alex")
    repo = PetRepository(db_session)
    pet, _ = await repo.upsert(
        PetRecord(
            source="user",
            source_id="contact-pet-1",
            record_type="lost",
            animal_type="dog",
            name="Rex",
            owner_id=recipient.id,
        ),
        owner_id=recipient.id,
    )
    contact = ContactRequest(
        pet_id=pet.id,
        requester_id=requester.id,
        recipient_id=recipient.id,
        message="I think I found your dog!",
    )
    db_session.add(contact)
    await db_session.flush()
    await db_session.commit()

    queued = await notify_contact_request(db_session, contact, pet)

    assert queued is True
    rows = await _queued_rows(db_session)
    assert len(rows) == 1
    assert rows[0].kind == "contact"
    assert rows[0].user_id == recipient.id
    assert rows[0].dedupe_key == f"contact:{contact.id}"
    assert "I think I found your dog!" in rows[0].body