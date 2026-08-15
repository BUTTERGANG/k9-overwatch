"""
Smoke + unit tests for active-listing age bucketing.

Two tiers:
  * Offline (always runs in CI): synthetic records with known ages must land in
    the right bucket, and the fallback chain (date_event → days_since_event →
    scrape age) must behave when dates are missing.
  * Live smoke (skipped without network / RUN_LIVE_SMOKE=1): actually scrape a
    source, persist to a temp DB, and assert listings are retrieved AND bucketed.
"""
from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta

import pytest

from k9overwatch.db.repository import (
    AGE_BUCKETS,
    PetRepository,
    age_bucket,
    effective_age_days,
)
from k9overwatch.models.enums import RecordType

from .conftest import make_indy_record

# ── Pure helpers ────────────────────────────────────────────────────────────────

class TestBucketBoundaries:
    @pytest.mark.parametrize("days,expected", [
        (0, "week"), (7, "week"),
        (8, "fortnight"), (14, "fortnight"),
        (15, "month"), (30, "month"),
        (31, "older"), (400, "older"),
    ])
    def test_age_bucket_edges(self, days, expected):
        assert age_bucket(days) == expected

    def test_effective_age_prefers_date_event(self):
        d = date.today() - timedelta(days=10)
        # date_event wins even if days_since_event disagrees
        assert effective_age_days(d, 999, None) == 10

    def test_effective_age_falls_back_to_days_since_plus_scrape(self):
        scraped = datetime.now(UTC) - timedelta(days=3)
        # 5 days old at scrape time + 3 days since scrape = 8
        assert effective_age_days(None, 5, scraped) == 8

    def test_effective_age_falls_back_to_scrape_age(self):
        scraped = datetime.now(UTC) - timedelta(days=12)
        assert effective_age_days(None, None, scraped) == 12

    def test_effective_age_all_missing_is_zero(self):
        assert effective_age_days(None, None, None) == 0

    def test_no_negative_ages(self):
        future = date.today() + timedelta(days=5)
        assert effective_age_days(future, None, None) == 0


# ── Repository bucketing over a real (in-memory) DB ─────────────────────────────

class TestActiveAgeBuckets:
    @pytest.mark.asyncio
    async def test_buckets_count_active_by_age(self, db_session):
        repo = PetRepository(db_session)
        today = date.today()
        # One record per bucket
        ages = {"week": 3, "fortnight": 10, "month": 25, "older": 90}
        for i, (_, age) in enumerate(ages.items()):
            await repo.upsert(make_indy_record(
                source_id=f"age-{i}",
                date_event=today - timedelta(days=age),
                record_type=RecordType.LOST,
            ))
        buckets = await repo.get_active_age_buckets()
        assert buckets == {"week": 1, "fortnight": 1, "month": 1, "older": 1}
        assert set(buckets) == set(AGE_BUCKETS)

    @pytest.mark.asyncio
    async def test_inactive_records_excluded(self, db_session):
        repo = PetRepository(db_session)
        row, _ = await repo.upsert(make_indy_record(
            source_id="inactive", date_event=date.today() - timedelta(days=2),
        ))
        row.active = False
        await db_session.flush()
        buckets = await repo.get_active_age_buckets()
        assert sum(buckets.values()) == 0

    @pytest.mark.asyncio
    async def test_record_type_filter(self, db_session):
        repo = PetRepository(db_session)
        await repo.upsert(make_indy_record(
            source_id="lost-1", record_type=RecordType.LOST,
            date_event=date.today() - timedelta(days=2),
        ))
        await repo.upsert(make_indy_record(
            source_id="found-1", record_type=RecordType.FOUND,
            date_event=date.today() - timedelta(days=2),
        ))
        lost = await repo.get_active_age_buckets(record_type="lost")
        assert lost["week"] == 1
        assert sum(lost.values()) == 1

    @pytest.mark.asyncio
    async def test_missing_date_still_bucketed(self, db_session):
        """A listing with no date_event must not vanish — it falls back."""
        repo = PetRepository(db_session)
        row, _ = await repo.upsert(make_indy_record(
            source_id="nodate", date_event=None, days_since_event=20,
        ))
        # force a deterministic scrape time (today) so age == days_since_event
        row.scraped_at = datetime.now(UTC)
        await db_session.flush()
        buckets = await repo.get_active_age_buckets()
        assert sum(buckets.values()) == 1
        assert buckets["month"] == 1  # 20 days → month bucket


# ── Live smoke test (opt-in) ────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_LIVE_SMOKE") != "1",
    reason="live network smoke test; set RUN_LIVE_SMOKE=1 to run",
)
async def test_live_scrape_retrieves_and_buckets(db_session):
    """
    End-to-end: scrape IndyLostPetAlert, persist, and confirm we both
    RETRIEVE listings and ORGANIZE them into age buckets.
    """
    from k9overwatch.scrapers.base import ScraperConfig
    from k9overwatch.scrapers.http.indy_lost_pet_alert import IndyLostPetAlertScraper

    scraper = IndyLostPetAlertScraper(ScraperConfig(
        search_lat=39.7684, search_lon=-86.1581,
        search_radius_miles=25, max_pages=1,
    ))
    repo = PetRepository(db_session)
    n = 0
    async for record in scraper.scrape():
        await repo.upsert(record)
        n += 1
    await db_session.flush()

    assert n > 0, "expected to retrieve at least one live listing"
    buckets = await repo.get_active_age_buckets()
    assert sum(buckets.values()) == n, "every active listing must be bucketed"
