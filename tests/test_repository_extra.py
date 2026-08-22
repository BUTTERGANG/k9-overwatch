"""
Additional repository tests covering previously untested code paths:
  - mark_inactive_bulk()
  - GeocodeCache savepoint / duplicate-insert resilience
  - get_stale_records() with fresh, stale, and NULL last_checked_at records
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from k9overwatch.db.models import GeocodeCache
from k9overwatch.db.repository import PetRepository
from k9overwatch.geocoding.geocoder import GeocodeResult, GeocodingService
from k9overwatch.models.enums import AnimalType, GeocodeConfidence, GeocodeSource, RecordType

from .conftest import make_indy_record, make_pawboost_record

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


# ── Cross-source deduplication ──────────────────────────────────────────────


class TestCrossSourceDedup:
    """find_cross_source_duplicates identifies the same pet on different sources."""

    @pytest.mark.asyncio
    async def test_finds_duplicate_from_other_source(self, db_session):
        """A new PawBoost lost dog that matches an existing IndyLostPetAlert lost dog
        by animal_type, breed, color, location, and date should be found as a duplicate."""
        repo = PetRepository(db_session)

        # Seed an existing record from indylostpetalert
        existing = await repo.upsert(
            make_indy_record(
                source="indylostpetalert",
                source_id="EXIST001",
                animal_type=AnimalType.DOG,
                breed="Labrador Mix",
                breed_normalized="labrador retriever",
                color_primary="Black",
                lat=39.7684,
                lon=-86.1581,
                date_event=date(2026, 3, 20),
            )
        )
        existing_row, _ = existing

        # New record from pawboost — same details, different source
        new_record = make_pawboost_record(
            source="pawboost",
            source_id="PB-DUP001",
            animal_type=AnimalType.DOG,
            breed="Labrador Retriever Mix",
            color_primary="Black",
            lat=39.7700,
            lon=-86.1600,
            date_event=date(2026, 3, 20),
        )
        new_row, _ = await repo.upsert(new_record)

        # Search from the new record's perspective
        duplicates = await repo.find_cross_source_duplicates(new_record, new_row)

        # Should find the existing record
        dup_ids = {r.id for r, _ in duplicates}
        assert existing_row.id in dup_ids

        # Should have scored it >0
        score = next(s for r, s in duplicates if r.id == existing_row.id)
        assert score > 0.0

    @pytest.mark.asyncio
    async def test_does_not_match_different_breed(self, db_session):
        """Different breed should not produce a match."""
        repo = PetRepository(db_session)

        # Seed a cat
        existing, _ = await repo.upsert(
            make_indy_record(
                source="indylostpetalert",
                source_id="EXIST002",
                animal_type=AnimalType.CAT,
                breed="Domestic Shorthair",
                color_primary="Black",
                lat=39.7684,
                lon=-86.1581,
                date_event=date(2026, 3, 20),
            )
        )

        # New record — same type/location but different breed
        new_record = make_indy_record(
            source="pawboost",
            source_id="PB-DUP002",
            animal_type=AnimalType.CAT,
            breed="Siamese",
            color_primary="Black",
            lat=39.7700,
            lon=-86.1600,
            date_event=date(2026, 3, 20),
        )
        new_row, _ = await repo.upsert(new_record)

        duplicates = await repo.find_cross_source_duplicates(new_record, new_row)
        dup_ids = {r.id for r, _ in duplicates}

        # Siamese vs Domestic Shorthair — no breed match
        assert existing.id not in dup_ids

    @pytest.mark.asyncio
    async def test_does_not_match_same_source(self, db_session):
        """Records from the same source should not be flagged as cross-source duplicates."""
        repo = PetRepository(db_session)

        existing, _ = await repo.upsert(
            make_indy_record(source="indylostpetalert", source_id="EXIST003")
        )
        new_record = make_indy_record(
            source="indylostpetalert",
            source_id="EXIST003B",  # different source_id, same source
            breed="Labrador Mix",
            color_primary="Black",
            lat=39.7684,
            lon=-86.1581,
            date_event=date(2026, 3, 20),
        )
        new_row, _ = await repo.upsert(new_record)

        duplicates = await repo.find_cross_source_duplicates(new_record, new_row)
        dup_ids = {r.id for r, _ in duplicates}
        assert existing.id not in dup_ids

    @pytest.mark.asyncio
    async def test_does_not_match_different_record_type(self, db_session):
        """Lost↔Found should NOT be matched by cross-source dedup (that's lost→found matching)."""
        repo = PetRepository(db_session)

        # Seed a LOST record
        existing, _ = await repo.upsert(
            make_indy_record(
                source="indylostpetalert",
                source_id="EXIST004",
                record_type=RecordType.LOST,
                animal_type=AnimalType.DOG,
                breed="Beagle",
                color_primary="Brown",
                lat=39.7684,
                lon=-86.1581,
                date_event=date(2026, 3, 20),
            )
        )

        # New FOUND record — same animal, different type
        new_record = make_indy_record(
            source="pawboost",
            source_id="PB-DUP004",
            record_type=RecordType.FOUND,  # different type!
            animal_type=AnimalType.DOG,
            breed="Beagle",
            color_primary="Brown",
            lat=39.7700,
            lon=-86.1600,
            date_event=date(2026, 3, 20),
        )
        new_row, _ = await repo.upsert(new_record)

        duplicates = await repo.find_cross_source_duplicates(new_record, new_row)
        dup_ids = {r.id for r, _ in duplicates}
        assert existing.id not in dup_ids

    @pytest.mark.asyncio
    async def test_does_not_match_outside_date_window(self, db_session):
        """Records with date_event outside 48h window should not match."""
        repo = PetRepository(db_session)

        existing, _ = await repo.upsert(
            make_indy_record(
                source="indylostpetalert",
                source_id="EXIST005",
                animal_type=AnimalType.DOG,
                breed="Labrador Mix",
                color_primary="Black",
                lat=39.7684,
                lon=-86.1581,
                date_event=date(2026, 3, 1),  # 19 days before
            )
        )

        new_record = make_indy_record(
            source="pawboost",
            source_id="PB-DUP005",
            animal_type=AnimalType.DOG,
            breed="Labrador Mix",
            color_primary="Black",
            lat=39.7700,
            lon=-86.1600,
            date_event=date(2026, 3, 20),  # 19 days later
        )
        new_row, _ = await repo.upsert(new_record)

        duplicates = await repo.find_cross_source_duplicates(
            new_record, new_row, date_window_hours=48
        )
        dup_ids = {r.id for r, _ in duplicates}
        assert existing.id not in dup_ids

    @pytest.mark.asyncio
    async def test_does_not_match_outside_radius(self, db_session):
        """Records beyond the search radius should not match."""
        repo = PetRepository(db_session)

        # Indianapolis
        existing, _ = await repo.upsert(
            make_indy_record(
                source="indylostpetalert",
                source_id="EXIST006",
                animal_type=AnimalType.DOG,
                breed="Poodle",
                color_primary="White",
                lat=39.7684,
                lon=-86.1581,
                date_event=date(2026, 3, 20),
            )
        )

        # Chicago (far away)
        new_record = make_indy_record(
            source="pawboost",
            source_id="PB-DUP006",
            animal_type=AnimalType.DOG,
            breed="Poodle",
            color_primary="White",
            lat=41.8781,
            lon=-87.6298,
            date_event=date(2026, 3, 20),
        )
        new_row, _ = await repo.upsert(new_record)

        duplicates = await repo.find_cross_source_duplicates(
            new_record, new_row, search_radius_miles=5.0
        )
        dup_ids = {r.id for r, _ in duplicates}
        assert existing.id not in dup_ids

    @pytest.mark.asyncio
    async def test_link_duplicates_creates_match(self, db_session):
        """link_duplicates should create a PetMatch with match_type='dedup'."""
        repo = PetRepository(db_session)

        row_a, _ = await repo.upsert(
            make_indy_record(source="indylostpetalert", source_id="LINK_A")
        )
        row_b, _ = await repo.upsert(
            make_pawboost_record(source="pawboost", source_id="LINK_B")
        )

        linked = await repo.link_duplicates(row_a, row_b, score=0.65)
        assert linked is True

        # Verify the match was persisted
        matches = await repo.get_matches_for_pet(row_a.id)
        assert len(matches) == 1
        assert matches[0].match_type == "dedup"
        assert matches[0].score == pytest.approx(0.65, abs=0.1)
        # score is passed through from_signals with cap at 1.0, but the signals_fired
        # dict has cross_source_dedup=0.65, so score should be ~0.65
        assert "cross_source_dedup" in matches[0].signals_fired

    @pytest.mark.asyncio
    async def test_link_duplicates_idempotent(self, db_session):
        """Linking the same pair twice should update, not duplicate."""
        repo = PetRepository(db_session)

        row_a, _ = await repo.upsert(
            make_indy_record(source="indylostpetalert", source_id="IDEM_A")
        )
        row_b, _ = await repo.upsert(
            make_pawboost_record(source="pawboost", source_id="IDEM_B")
        )

        # Link twice
        await repo.link_duplicates(row_a, row_b, score=0.50)
        linked = await repo.link_duplicates(row_a, row_b, score=0.70)

        # Second call returns False (updated, not created)
        assert linked is False

        matches = await repo.get_matches_for_pet(row_a.id)
        assert len(matches) == 1
        # Score should be refreshed to the higher value
        assert matches[0].score == pytest.approx(0.70, abs=0.1)

    @pytest.mark.asyncio
    async def test_end_to_end_scraper_pipeline(self, db_session):
        """Simulate the scraper pipeline: upsert two matching records from different
        sources and verify the cross-source dedup links them."""
        repo = PetRepository(db_session)

        # Step 1: Upsert a record from indylostpetalert
        record_a = make_indy_record(
            source="indylostpetalert",
            source_id="E2E_INDY",
            animal_type=AnimalType.DOG,
            breed="Golden Retriever",
            color_primary="Golden",
            lat=39.7684,
            lon=-86.1581,
            date_event=date(2026, 3, 20),
        )
        row_a, created_a = await repo.upsert(record_a)
        assert created_a is True

        # Step 2: Upsert a matching record from pawboost
        record_b = make_pawboost_record(
            source="pawboost",
            source_id="E2E_PAW",
            breed="Golden Retriever",
            color_primary="Golden",
            lat=39.7700,
            lon=-86.1600,
            date_event=date(2026, 3, 20),
        )
        row_b, created_b = await repo.upsert(record_b)
        assert created_b is True

        # Step 3: Run cross-source dedup from the new record's perspective
        duplicates = await repo.find_cross_source_duplicates(record_b, row_b)
        assert len(duplicates) >= 1
        dup_ids = {r.id for r, _ in duplicates}
        assert row_a.id in dup_ids

        # Step 4: Link the duplicates
        score = next(s for r, s in duplicates if r.id == row_a.id)
        linked = await repo.link_duplicates(row_b, row_a, score)
        assert linked is True

        # Step 5: Verify the match
        matches = await repo.get_matches_for_pet(row_a.id)
        assert len(matches) == 1
        assert matches[0].match_type == "dedup"
        assert matches[0].score > 0.0
