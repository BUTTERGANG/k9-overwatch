"""
End-to-end pipeline integration test.

Tests the full cycle without network access:
  PetRecord objects → DB upsert → geocoding → matching engine → match storage

Validates that each layer hands off correctly to the next.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from k9overwatch.db.repository import PetRepository
from k9overwatch.geocoding.geocoder import GeocodingService, GeocodeResult
from k9overwatch.matching.deduplicator import Deduplicator, DEDUP_MIN_SCORE
from k9overwatch.matching.lost_found_matcher import LostFoundMatcher, LOST_FOUND_MIN_SCORE
from k9overwatch.models.enums import AnimalType, GeocodeConfidence, GeocodeSource, Gender, RecordType

from .conftest import (
    make_indy_record,
    make_pawboost_record,
    make_petfbi_record,
    make_petconnect24_record,
    make_lostmydoggie_record,
)


# ── Upsert pipeline ───────────────────────────────────────────────────────────

class TestUpsertPipeline:
    @pytest.mark.asyncio
    async def test_upsert_creates_new_record(self, db_session):
        repo = PetRepository(db_session)
        record = make_indy_record()
        row, created = await repo.upsert(record)
        assert created is True
        assert row.id is not None
        assert row.source == "indylostpetalert"
        assert row.source_id == "12345"

    @pytest.mark.asyncio
    async def test_upsert_deduplicates_same_source_id(self, db_session):
        repo = PetRepository(db_session)
        record = make_indy_record()
        _, created1 = await repo.upsert(record)
        _, created2 = await repo.upsert(record)
        assert created1 is True
        assert created2 is False

    @pytest.mark.asyncio
    async def test_upsert_all_five_sources(self, db_session):
        repo = PetRepository(db_session)
        records = [
            make_indy_record(),
            make_pawboost_record(),
            make_petfbi_record(),
            make_petconnect24_record(),
            make_lostmydoggie_record(),
        ]
        for record in records:
            row, created = await repo.upsert(record)
            assert created is True, f"Expected new record for {record.source}"

        # Verify all 5 are in DB
        for record in records:
            fetched = await repo.get_by_key(record.source, record.source_id)
            assert fetched is not None
            assert fetched.source == record.source

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_description(self, db_session):
        repo = PetRepository(db_session)
        record = make_indy_record(description="Original description")
        await repo.upsert(record)

        updated = make_indy_record(description="Updated with more details")
        row, created = await repo.upsert(updated)
        assert created is False
        assert row.description == "Updated with more details"

    @pytest.mark.asyncio
    async def test_upsert_preserves_geocoords_on_update(self, db_session):
        repo = PetRepository(db_session)
        record = make_indy_record(lat=39.77, lon=-86.11)
        await repo.upsert(record)

        # Re-upsert without coords; existing coords should be preserved
        updated = make_indy_record(lat=None, lon=None)
        row, _ = await repo.upsert(updated)
        assert row.lat == pytest.approx(39.77)

    @pytest.mark.asyncio
    async def test_petfbi_native_coords_stored(self, db_session):
        repo = PetRepository(db_session)
        record = make_petfbi_record()  # has lat/lon from API
        row, _ = await repo.upsert(record)
        assert row.lat == pytest.approx(39.8689)
        assert row.lon == pytest.approx(-86.1397)
        assert row.geocode_source == "petfbi_native"
        assert row.geocode_confidence == "high"

    @pytest.mark.asyncio
    async def test_mark_inactive(self, db_session):
        repo = PetRepository(db_session)
        record = make_indy_record()
        await repo.upsert(record)
        await repo.mark_inactive("indylostpetalert", "12345")
        row = await repo.get_by_key("indylostpetalert", "12345")
        assert row.active is False

    @pytest.mark.asyncio
    async def test_scraper_state_stored(self, db_session):
        repo = PetRepository(db_session)
        await repo.update_scraper_state(
            "indylostpetalert",
            success=True,
            records_fetched=200,
            records_new=15,
        )
        state = await repo.get_scraper_state("indylostpetalert")
        assert state is not None
        assert state.last_run_success is True
        assert state.records_fetched == 200
        assert state.records_new == 15


# ── Geocoding pipeline ────────────────────────────────────────────────────────

class TestGeocodingPipeline:
    @pytest.mark.asyncio
    async def test_zip_centroid_fills_coords(self, db_session):
        """A record with only a ZIP gets coordinates via the centroid fallback."""
        service = GeocodingService(session=db_session, providers=[])
        record = make_indy_record(lat=None, lon=None, location_text=None, zip="46205")
        enriched = await service.geocode(record)
        assert enriched.lat is not None
        assert enriched.geocode_source == "zip_centroid"

    @pytest.mark.asyncio
    async def test_native_coords_skipped(self, db_session):
        """PetFBI record with native coords is not re-geocoded."""
        service = GeocodingService(session=db_session, providers=[])
        record = make_petfbi_record()
        original_lat = record.lat
        enriched = await service.geocode(record)
        assert enriched.lat == original_lat
        assert enriched.geocode_source == "petfbi_native"

    @pytest.mark.asyncio
    async def test_geocoded_coords_persist_to_db(self, db_session):
        """Geocoded coords survive the upsert cycle."""
        service = GeocodingService(session=db_session, providers=[])
        repo = PetRepository(db_session)

        record = make_indy_record(lat=None, lon=None, location_text=None, zip="46201")
        record = await service.geocode(record)
        assert record.lat is not None

        row, _ = await repo.upsert(record)
        assert row.lat == pytest.approx(record.lat)
        assert row.geocode_source == "zip_centroid"


# ── Matching engine pipeline ──────────────────────────────────────────────────

class TestMatchingPipeline:
    def _make_pet_row(self, db_session, record):
        """Synchronous helper: build a PetRow-like object from a PetRecord for matching tests."""
        from k9overwatch.db.models import PetRow
        import uuid
        row = PetRow(
            id=str(uuid.uuid4()),
            source=record.source,
            source_id=record.source_id,
            record_type=str(record.record_type),
            animal_type=str(record.animal_type) if record.animal_type else None,
            name=record.name,
            breed=record.breed,
            color_primary=record.color_primary,
            color_secondary=record.color_secondary,
            gender=str(record.gender) if record.gender else None,
            date_event=record.date_event,
            lat=record.lat,
            lon=record.lon,
            zip=record.zip,
            description=record.description,
            microchip_number=record.microchip_number,
            active=True,
        )
        return row

    def test_dedup_finds_same_pet_cross_source(self, db_session):
        """Two records for the same lost dog from different sources score above dedup threshold."""
        dedup = Deduplicator()

        # Same dog on IndyLostPetAlert and PawBoost
        indy = self._make_pet_row(db_session, make_indy_record(
            source="indylostpetalert",
            name="Buddy",
            breed="Labrador Mix",
            color_primary="Black",
            gender=Gender.MALE,
            date_event=date(2026, 3, 20),
            zip="46205",
            lat=39.82, lon=-86.13,
        ))
        paw = self._make_pet_row(db_session, make_pawboost_record(
            source="pawboost",
            name="Buddy",
            breed="Labrador Mix",
            color_primary="Black",
            gender=Gender.MALE,
            date_event=date(2026, 3, 20),
            zip="46205",
            lat=39.82, lon=-86.13,
        ))

        results = dedup.find_duplicates(indy, [paw])
        assert len(results) == 1
        assert results[0].score >= DEDUP_MIN_SCORE
        assert results[0].match_type == "dedup"

    def test_dedup_ignores_different_species(self, db_session):
        """Dog and cat records should never be deduped."""
        dedup = Deduplicator()
        dog = self._make_pet_row(db_session, make_indy_record(
            animal_type=AnimalType.DOG, zip="46205", date_event=date(2026, 3, 20)
        ))
        cat = self._make_pet_row(db_session, make_petconnect24_record(
            animal_type=AnimalType.CAT, zip="46205", date_event=date(2026, 3, 20)
        ))
        dog.animal_type = "dog"
        cat.animal_type = "cat"
        results = dedup.find_duplicates(dog, [cat])
        assert results == []

    def test_lost_found_matcher_finds_match(self, db_session):
        """A lost dog matches a found dog nearby on the same day."""
        matcher = LostFoundMatcher()

        lost = self._make_pet_row(db_session, make_indy_record(
            record_type=RecordType.LOST,
            animal_type=AnimalType.DOG,
            name="Rex",
            breed="Golden Retriever",
            color_primary="Golden",
            gender=Gender.MALE,
            date_event=date(2026, 3, 20),
            lat=39.82, lon=-86.13,
            zip="46205",
        ))
        lost.record_type = "lost"

        found = self._make_pet_row(db_session, make_petconnect24_record(
            record_type=RecordType.FOUND,
            animal_type=AnimalType.DOG,
            name=None,
            breed="Golden Retriever",
            color_primary="Golden",
            gender=Gender.MALE,
            date_event=date(2026, 3, 22),  # 2 days after
            lat=39.82, lon=-86.13,
            zip="46205",
        ))
        found.record_type = "found"
        found.animal_type = "dog"

        results = matcher.find_matches(lost, [found])
        assert len(results) == 1
        assert results[0].score >= LOST_FOUND_MIN_SCORE
        assert results[0].match_type == "lost_found"

    def test_lost_found_matcher_rejects_outside_window(self, db_session):
        """A found date 91+ days after lost date is outside the window."""
        matcher = LostFoundMatcher()

        lost = self._make_pet_row(db_session, make_indy_record(
            record_type=RecordType.LOST,
            animal_type=AnimalType.DOG,
            date_event=date(2026, 1, 1),
            zip="46205",
        ))
        lost.record_type = "lost"
        lost.animal_type = "dog"

        found = self._make_pet_row(db_session, make_petconnect24_record(
            record_type=RecordType.FOUND,
            animal_type=AnimalType.DOG,
            date_event=date(2026, 4, 5),  # 94 days later
            zip="46205",
        ))
        found.record_type = "found"
        found.animal_type = "dog"

        results = matcher.find_matches(lost, [found])
        assert results == []

    def test_lost_found_matcher_requires_lost_record(self, db_session):
        """Passing a found record as the 'lost' side returns no matches."""
        matcher = LostFoundMatcher()
        found1 = self._make_pet_row(db_session, make_petconnect24_record())
        found1.record_type = "found"
        found2 = self._make_pet_row(db_session, make_pawboost_record())
        found2.record_type = "found"

        results = matcher.find_matches(found1, [found2])
        assert results == []


# ── Match storage pipeline ────────────────────────────────────────────────────

class TestMatchStoragePipeline:
    @pytest.mark.asyncio
    async def test_save_and_retrieve_match(self, db_session):
        """A MatchResult can be saved and retrieved from the DB."""
        from k9overwatch.matching.signals import MatchResult

        repo = PetRepository(db_session)

        # Upsert two pets to get their DB IDs
        row_a, _ = await repo.upsert(make_indy_record())
        row_b, _ = await repo.upsert(make_pawboost_record())

        match = MatchResult(
            pet_a_id=row_a.id,
            pet_b_id=row_b.id,
            match_type="dedup",
            score=0.75,
            confidence="high",
            signals_fired={"breed_exact": 0.15, "zip_match": 0.20, "name_exact": 0.15,
                           "geo_very_close": 0.25},
        )
        saved = await repo.save_match(match)
        assert saved is True

        # Retrieve matches for pet_a
        matches = await repo.get_matches_for_pet(row_a.id)
        assert len(matches) == 1
        assert matches[0].score == pytest.approx(0.75)
        assert matches[0].match_type == "dedup"

    @pytest.mark.asyncio
    async def test_duplicate_match_not_saved_twice(self, db_session):
        """Saving the same match pair twice returns False on the second attempt."""
        from k9overwatch.matching.signals import MatchResult

        repo = PetRepository(db_session)
        row_a, _ = await repo.upsert(make_indy_record())
        row_b, _ = await repo.upsert(make_pawboost_record())

        match = MatchResult(
            pet_a_id=row_a.id,
            pet_b_id=row_b.id,
            match_type="lost_found",
            score=0.55,
            confidence="medium",
            signals_fired={"breed_exact": 0.15, "zip_match": 0.20},
        )
        first = await repo.save_match(match)
        second = await repo.save_match(match)
        assert first is True
        assert second is False

    @pytest.mark.asyncio
    async def test_full_cycle_upsert_geocode_match_save(self, db_session):
        """Full pipeline: upsert two records → geocode → run matcher → save match."""
        from k9overwatch.matching.signals import MatchResult

        repo = PetRepository(db_session)
        geo_service = GeocodingService(session=db_session, providers=[])

        # Two dogs with matching attributes, same ZIP (no native coords)
        lost_record = make_indy_record(
            source_id="lost_dog_1",
            record_type=RecordType.LOST,
            animal_type=AnimalType.DOG,
            name="Buddy",
            breed="Labrador Mix",
            color_primary="Black",
            gender=Gender.MALE,
            date_event=date(2026, 3, 20),
            lat=None, lon=None,
            location_text=None,
            zip="46205",
        )
        found_record = make_petconnect24_record(
            source_id="found_dog_1",
            record_type=RecordType.FOUND,
            animal_type=AnimalType.DOG,
            name=None,
            breed="Labrador Mix",
            color_primary="Black",
            gender=Gender.MALE,
            date_event=date(2026, 3, 22),
            lat=None, lon=None,
            location_text=None,
            zip="46205",
        )

        # Geocode both (ZIP centroid)
        lost_record = await geo_service.geocode(lost_record)
        found_record = await geo_service.geocode(found_record)
        assert lost_record.lat is not None
        assert found_record.lat is not None

        # Upsert
        lost_row, _ = await repo.upsert(lost_record)
        found_row, _ = await repo.upsert(found_record)

        # Run lost→found matcher
        matcher = LostFoundMatcher()
        from k9overwatch.db.models import PetRow
        import uuid

        def row_to_petrow(row):
            """Refresh the PetRow from the session after upsert."""
            return row  # already a PetRow with id set

        results = matcher.find_matches(lost_row, [found_row])
        assert len(results) >= 1, "Expected at least one lost→found match"
        assert results[0].score >= LOST_FOUND_MIN_SCORE

        # Save the match
        saved = await repo.save_match(results[0])
        assert saved is True

        # Verify retrievable
        saved_matches = await repo.get_matches_for_pet(lost_row.id)
        assert len(saved_matches) == 1
        assert saved_matches[0].match_type == "lost_found"
