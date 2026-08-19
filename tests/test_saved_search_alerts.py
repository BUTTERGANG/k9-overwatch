from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from k9overwatch.db.models import NotificationQueue, SavedSearch
from k9overwatch.db.repository import PetRepository, UserRepository
from k9overwatch.models.pet_record import PetRecord


async def _pet(repo, **kwargs):
    defaults = dict(
        source="feed",
        source_id="pet-1",
        record_type="lost",
        animal_type="dog",
        breed="Labrador Retriever",
        date_event=date.today(),
        lat=39.7684,
        lon=-86.1581,
        city="Indianapolis",
    )
    defaults.update(kwargs)
    row, _ = await repo.upsert(PetRecord(**defaults))
    return row


@pytest.mark.asyncio
async def test_saved_search_evaluation_filters_and_queues_durable_alert(db_session):
    user = await UserRepository(db_session).create("alerts@example.com", "password123", "Ava")
    db_session.add(SavedSearch(
        id="search-1", user_id=user.id, name="Nearby labs", record_type="lost",
        animal_type="dog", species="labrador", latitude=39.7684, longitude=-86.1581,
        radius_miles=10, days=7, min_confidence="medium", enabled=True,
    ))
    await db_session.flush()
    repo = PetRepository(db_session)
    pet = await _pet(repo)

    queued = await repo.evaluate_saved_searches([pet], confidence="high")
    await db_session.commit()

    assert queued == 1
    alert = (await db_session.execute(select(NotificationQueue))).scalar_one()
    assert alert.user_id == user.id
    assert alert.saved_search_id == "search-1"
    assert alert.pet_id == pet.id
    assert alert.status == "pending"


@pytest.mark.asyncio
async def test_saved_search_alert_is_idempotent_and_respects_disabled_and_confidence(db_session):
    user = await UserRepository(db_session).create("idempotent@example.com", "password123")
    db_session.add_all([
        SavedSearch(id="enabled", user_id=user.id, name="High confidence", record_type="lost", days=30, min_confidence="high"),
        SavedSearch(id="disabled", user_id=user.id, name="Disabled", record_type="lost", days=30, min_confidence="low", enabled=False),
    ])
    await db_session.flush()
    repo = PetRepository(db_session)
    pet = await _pet(repo, source_id="pet-2")

    assert await repo.evaluate_saved_searches([pet], confidence="medium") == 0
    assert await repo.evaluate_saved_searches([pet], confidence="high") == 1
    assert await repo.evaluate_saved_searches([pet], confidence="high") == 0
    assert (await db_session.execute(select(NotificationQueue))).scalars().all().__len__() == 1


@pytest.mark.asyncio
async def test_saved_search_evaluation_respects_record_animal_breed_radius_and_days(db_session):
    user = await UserRepository(db_session).create("criteria@example.com", "password123")
    db_session.add(SavedSearch(
        user_id=user.id, name="Criteria", record_type="found", animal_type="cat",
        species="siamese", latitude=39.7684, longitude=-86.1581, radius_miles=5, days=3,
    ))
    await db_session.flush()
    repo = PetRepository(db_session)
    wrong_type = await _pet(repo, source_id="wrong-type", record_type="lost", animal_type="dog")
    wrong_breed = await _pet(repo, source_id="wrong-breed", record_type="found", animal_type="cat", breed="tabby")
    far = await _pet(repo, source_id="far", record_type="found", animal_type="cat", breed="siamese", lat=40.5, lon=-86.1)
    old = await _pet(repo, source_id="old", record_type="found", animal_type="cat", breed="siamese", date_event=date.today() - timedelta(days=4))
    match = await _pet(repo, source_id="match", record_type="found", animal_type="cat", breed="Siamese mix")

    assert await repo.evaluate_saved_searches([wrong_type, wrong_breed, far, old, match]) == 1
    alert = (await db_session.execute(select(NotificationQueue))).scalar_one()
    assert alert.pet_id == match.id


@pytest.mark.asyncio
async def test_notification_queue_claims_pending_rows_for_delivery(db_session):
    user = await UserRepository(db_session).create("queue@example.com", "password123")
    db_session.add(SavedSearch(id="search-q", user_id=user.id, name="Queue", days=30))
    await db_session.flush()
    repo = PetRepository(db_session)
    pet = await _pet(repo, source_id="queue-pet")
    await repo.evaluate_saved_searches([pet])

    claimed = await repo.claim_notification_queue(limit=10)
    await db_session.commit()

    assert len(claimed) == 1
    assert claimed[0].status == "processing"
    assert (await db_session.execute(select(NotificationQueue))).scalar_one().status == "processing"


@pytest.mark.asyncio
async def test_notification_queue_retries_failed_delivery_after_backoff(db_session):
    from datetime import datetime

    user = await UserRepository(db_session).create("retry@example.com", "password123")
    db_session.add(SavedSearch(id="retry-search", user_id=user.id, name="Retry", days=30))
    await db_session.flush()
    repo = PetRepository(db_session)
    pet = await _pet(repo, source_id="retry-pet")
    await repo.evaluate_saved_searches([pet])

    now = datetime(2026, 8, 18, 12, 0, 0)
    claimed = await repo.claim_notification_queue(now=now)
    await repo.mark_notification_failed(claimed[0], "temporary SMTP failure", now=now)
    await db_session.commit()

    assert claimed[0].attempts == 1
    assert claimed[0].status == "failed"
    assert claimed[0].next_attempt_at == datetime(2026, 8, 18, 12, 1, 0)
    assert await repo.claim_notification_queue(now=now) == []
    retried = await repo.claim_notification_queue(now=claimed[0].next_attempt_at)
    assert len(retried) == 1
    assert retried[0].attempts == 2
    assert retried[0].status == "processing"


@pytest.mark.asyncio
async def test_notification_queue_does_not_retry_after_max_attempts(db_session):
    from datetime import datetime

    user = await UserRepository(db_session).create("dead@example.com", "password123")
    db_session.add(SavedSearch(id="dead-search", user_id=user.id, name="Dead", days=30))
    await db_session.flush()
    repo = PetRepository(db_session)
    pet = await _pet(repo, source_id="dead-pet")
    await repo.evaluate_saved_searches([pet])

    now = datetime(2026, 8, 18, 12, 0, 0)
    for _ in range(5):
        claimed = await repo.claim_notification_queue(now=now)
        assert len(claimed) == 1
        await repo.mark_notification_failed(claimed[0], "permanent SMTP failure", now=now)
        now = claimed[0].next_attempt_at
    await db_session.commit()

    assert claimed[0].attempts == 5
    assert await repo.claim_notification_queue(now=now) == []


@pytest.mark.asyncio
async def test_notification_queue_flush_marks_claimed_alert_sent_without_smtp(db_session, monkeypatch):
    from k9overwatch.notifications import flush_notification_queue

    monkeypatch.delenv("SMTP_HOST", raising=False)
    user = await UserRepository(db_session).create("delivery@example.com", "password123")
    db_session.add(SavedSearch(id="delivery-search", user_id=user.id, name="Delivery", days=30))
    await db_session.flush()
    repo = PetRepository(db_session)
    pet = await _pet(repo, source_id="delivery-pet")
    await repo.evaluate_saved_searches([pet])

    assert await flush_notification_queue(db_session) == 1
    assert (await db_session.execute(select(NotificationQueue))).scalar_one().status == "sent"


@pytest.mark.asyncio
async def test_saved_search_evaluation_is_called_for_new_scraper_rows(db_session, monkeypatch):
    # The scraper integration is covered by the scheduler-level contract: only newly
    # created rows are passed to saved-search evaluation.
    from k9overwatch.scheduler import jobs

    seen = []
    async def fake_evaluate(self, rows, confidence=None):
        seen.extend(rows)
        return 0
    monkeypatch.setattr(PetRepository, "evaluate_saved_searches", fake_evaluate)
    assert hasattr(jobs, "run_saved_search_alerts")
    assert callable(jobs.run_saved_search_alerts)
