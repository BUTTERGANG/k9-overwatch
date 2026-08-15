"""
Additional repository tests covering previously untested code paths:
  - mark_inactive_bulk()
  - GeocodeCache savepoint / duplicate-insert resilience
  - get_stale_records() with fresh, stale, and NULL last_checked_at records
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from k9overwatch.db.models import GeocodeCache
from k9overwatch.db.repository import PetRepository
from k9overwatch.geocoding.geocoder import GeocodeResult, GeocodingService
from k9overwatch.models.enums import GeocodeConfidence, GeocodeSource

from .conftest import make_indy_record

# ── mark_inactive_bulk ────────────────────────────────────────────────────────

class TestMarkInactiveBulk:
    @pytest.mark.asyncio
    async def test_bulk_deactivates_unseen_records(self, db_session):
        """
        Seed 3 active records from the same source. Call mark_inactive_bulk with
        only one source_id in seen_ids. Verify the other two become inactive.
        """
        repo = PetRepository(db_session)

        rec_a = make_indy_record(source_id="A001")
        rec_b = make_indy_record(source_id="A002")
        rec_c = make_indy_record(source_id="A003")

        row_a, _ = await repo.upsert(rec_a)
        row_b, _ = await repo.upsert(rec_b)
        row_c, _ = await repo.upsert(rec_c)

        # Only A001 was seen in the latest scrape
        deactivated = await repo.mark_inactive_bulk("indylostpetalert", seen_source_ids={"A001"})

        assert deactivated == 2

        # A001 must still be active
        refreshed_a = await repo.get_by_key("indylostpetalert", "A001")
        assert refreshed_a.active is True

        # A002 and A003 must now be inactive
        refreshed_b = await repo.get_by_key("indylostpetalert", "A002")
        refreshed_c = await repo.get_by_key("indylostpetalert", "A003")
        assert refreshed_b.active is False
        assert refreshed_c.active is False

    @pytest.mark.asyncio
    async def test_bulk_with_all_ids_seen_deactivates_none(self, db_session):
        """When all source_ids are in seen_ids, nothing is deactivated."""
        repo = PetRepository(db_session)

        await repo.upsert(make_indy_record(source_id="B001"))
        await repo.upsert(make_indy_record(source_id="B002"))

        count = await repo.mark_inactive_bulk("indylostpetalert", seen_source_ids={"B001", "B002"})
        assert count == 0


# ── GeocodeCache savepoint behavior ──────────────────────────────────────────

class TestGeocodeCache:
    @pytest.mark.asyncio
    async def test_duplicate_cache_insert_does_not_raise(self, db_session):
        """
        Seed a GeocodeCache row directly. Call _save_cache() with the same
        address key. The savepoint should absorb the IntegrityError without
        propagating it or corrupting the outer transaction.
        """
        # Seed an existing cache entry, then expunge it from the session so we
        # mimic the real production scenario where the duplicate insert comes
        # from a session that doesn't already have the row in its identity map.
        # (Without expunge, SQLA emits an identity-key-conflict SAWarning before
        # the DB-level IntegrityError that _save_cache is meant to handle.)
        original = GeocodeCache(
            address_key="4521 n keystone ave indianapolis in",
            lat=39.82,
            lon=-86.11,
            geocode_source="nominatim",
            geocode_confidence="high",
        )
        db_session.add(original)
        await db_session.flush()
        db_session.expunge(original)

        # Build a GeocodingService and try to save a duplicate
        service = GeocodingService(session=db_session, providers=[])
        duplicate_result = GeocodeResult(
            lat=39.99,  # different coords — should be ignored
            lon=-86.00,
            geocode_source=GeocodeSource.NOMINATIM,
            geocode_confidence=GeocodeConfidence.HIGH,
        )

        # Must not raise
        await service._save_cache("4521 n keystone ave indianapolis in", duplicate_result)

        # Original row must be unchanged
        result = await db_session.execute(
            select(GeocodeCache).where(
                GeocodeCache.address_key == "4521 n keystone ave indianapolis in"
            )
        )
        row = result.scalar_one()
        assert row.lat == pytest.approx(39.82)
        assert row.lon == pytest.approx(-86.11)

    @pytest.mark.asyncio
    async def test_cache_hit_count_increments_on_second_lookup(self, db_session):
        """Looking up the same address twice should increment hit_count."""
        service = GeocodingService(session=db_session, providers=[])

        # First call: cache miss → ZIP centroid result written
        record = make_indy_record(lat=None, lon=None, location_text=None, zip="46205")
        await service.geocode(record)

        # Second call on same address: cache hit — hit_count bumped
        record2 = make_indy_record(lat=None, lon=None, location_text=None, zip="46205")
        await service.geocode(record2)

        # The ZIP centroid path does NOT call _save_cache, so we test via a
        # provider path. Instead, seed the cache and verify _check_cache increments.
        seed = GeocodeCache(
            address_key="test address key",
            lat=39.77,
            lon=-86.15,
            geocode_source="nominatim",
            geocode_confidence="high",
            hit_count=1,
        )
        db_session.add(seed)
        await db_session.flush()

        result = await service._check_cache("test address key")
        assert result is not None

        refreshed = await db_session.get(GeocodeCache, "test address key")
        assert refreshed.hit_count == 2


# ── get_stale_records ─────────────────────────────────────────────────────────

class TestGetStaleRecords:
    @pytest.mark.asyncio
    async def test_returns_stale_and_null_but_not_fresh(self, db_session):
        """
        Seed three records:
          - fresh: last_checked_at = now (should NOT be returned)
          - stale: last_checked_at = 72 hours ago (should be returned)
          - null_checked: last_checked_at = NULL (should always be returned)

        get_stale_records(older_than_hours=48) must return only stale + null.
        """
        repo = PetRepository(db_session)

        now = datetime.now(UTC).replace(tzinfo=None)

        # Fresh record (checked just now)
        fresh_rec = make_indy_record(source_id="FRESH001")
        row_fresh, _ = await repo.upsert(fresh_rec)
        row_fresh.last_checked_at = now
        await db_session.flush()

        # Stale record (checked 72 hours ago — older than 48h threshold)
        stale_rec = make_indy_record(source_id="STALE001")
        row_stale, _ = await repo.upsert(stale_rec)
        row_stale.last_checked_at = now - timedelta(hours=72)
        await db_session.flush()

        # NULL last_checked_at record
        null_rec = make_indy_record(source_id="NULL001")
        row_null, _ = await repo.upsert(null_rec)
        row_null.last_checked_at = None
        await db_session.flush()

        stale_rows = await repo.get_stale_records("indylostpetalert", older_than_hours=48)
        stale_ids = {r.source_id for r in stale_rows}

        assert "FRESH001" not in stale_ids
        assert "STALE001" in stale_ids
        assert "NULL001" in stale_ids

    @pytest.mark.asyncio
    async def test_returns_empty_when_all_fresh(self, db_session):
        """No stale records returned when everything was checked recently."""
        repo = PetRepository(db_session)
        now = datetime.now(UTC).replace(tzinfo=None)

        rec = make_indy_record(source_id="FRESH002")
        row, _ = await repo.upsert(rec)
        row.last_checked_at = now
        await db_session.flush()

        stale_rows = await repo.get_stale_records("indylostpetalert", older_than_hours=48)
        assert stale_rows == []

    @pytest.mark.asyncio
    async def test_only_returns_records_from_requested_source(self, db_session):
        """Records from a different source are not included in results."""
        repo = PetRepository(db_session)

        # Stale record from source "indylostpetalert"
        indy_rec = make_indy_record(source_id="INDY_STALE")
        row_indy, _ = await repo.upsert(indy_rec)
        row_indy.last_checked_at = None
        await db_session.flush()

        # Stale record from source "pawboost"
        from .conftest import make_pawboost_record
        paw_rec = make_pawboost_record(source_id="PAW_STALE")
        row_paw, _ = await repo.upsert(paw_rec)
        row_paw.last_checked_at = None
        await db_session.flush()

        # Only ask for indylostpetalert
        stale_rows = await repo.get_stale_records("indylostpetalert", older_than_hours=1)
        sources = {r.source for r in stale_rows}
        assert sources == {"indylostpetalert"}
