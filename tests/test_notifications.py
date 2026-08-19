"""Regression coverage for owner match notifications."""
from __future__ import annotations

from datetime import date

import pytest

from k9overwatch.db.repository import PetRepository, UserRepository
from k9overwatch.matching.signals import MatchResult
from k9overwatch.models.pet_record import PetRecord
from k9overwatch.notifications import MatchEvent, _digest, notify_new_match


@pytest.mark.asyncio
async def test_digest_notification_is_queued_for_owner_submitted_lost_pet(db_session):
    users = UserRepository(db_session)
    user = await users.create("owner@example.com", "password123", "Sam")
    repo = PetRepository(db_session)
    lost, _ = await repo.upsert(
        PetRecord(
            source="user",
            source_id="lost-1",
            record_type="lost",
            animal_type="dog",
            name="Rex",
            owner_id=user.id,
            date_event=date.today(),
        ),
        owner_id=user.id,
    )
    found, _ = await repo.upsert(
        PetRecord(
            source="shelter",
            source_id="found-1",
            record_type="found",
            animal_type="dog",
            name="Rex",
            city="Indianapolis",
            date_event=date.today(),
        )
    )
    await db_session.commit()
    _digest.clear()

    result = MatchResult.from_signals(
        str(lost.id), str(found.id), "lost_found", {"name_exact": 0.15, "geo_close": 0.15, "breed_exact": 0.15}
    )
    queued = await notify_new_match(db_session, MatchEvent(lost, found, result))

    assert queued is True
    assert list(_digest) == [user.email]
    assert len(_digest[user.email]) == 1
    assert "Rex" in _digest[user.email][0][1]
    _digest.clear()


@pytest.mark.asyncio
async def test_found_side_notification_targets_the_lost_pet_owner(db_session):
    users = UserRepository(db_session)
    user = await users.create("owner@example.com", "password123", "Sam")
    repo = PetRepository(db_session)
    lost, _ = await repo.upsert(
        PetRecord(
            source="user",
            source_id="lost-1",
            record_type="lost",
            animal_type="dog",
            name="Rex",
            owner_id=user.id,
            date_event=date.today(),
        ),
        owner_id=user.id,
    )
    found, _ = await repo.upsert(
        PetRecord(
            source="shelter",
            source_id="found-1",
            record_type="found",
            animal_type="dog",
            name="Rex",
            date_event=date.today(),
        )
    )
    await db_session.commit()
    _digest.clear()

    result = MatchResult.from_signals(
        str(found.id), str(lost.id), "lost_found", {"name_exact": 0.15, "geo_close": 0.15, "breed_exact": 0.15}
    )
    from k9overwatch.scheduler.jobs import _maybe_notify

    await _maybe_notify(db_session, found, result, [lost])

    assert list(_digest) == [user.email]
    _digest.clear()


@pytest.mark.asyncio
async def test_found_side_notification_uses_other_pet_when_found_is_match_b(db_session):
    users = UserRepository(db_session)
    user = await users.create("owner-reversed@example.com", "password123", "Sam")
    repo = PetRepository(db_session)
    lost, _ = await repo.upsert(
        PetRecord(
            source="user",
            source_id="lost-reversed",
            record_type="lost",
            animal_type="dog",
            name="Rex",
            owner_id=user.id,
            date_event=date.today(),
        ),
        owner_id=user.id,
    )
    found, _ = await repo.upsert(
        PetRecord(
            source="shelter",
            source_id="found-reversed",
            record_type="found",
            animal_type="dog",
            name="Rex",
            date_event=date.today(),
        )
    )
    await db_session.commit()
    _digest.clear()

    result = MatchResult.from_signals(
        str(lost.id), str(found.id), "lost_found", {"name_exact": 0.40}
    )
    from k9overwatch.scheduler.jobs import _maybe_notify

    await _maybe_notify(db_session, found, result, [lost])

    assert list(_digest) == [user.email]
    _digest.clear()
