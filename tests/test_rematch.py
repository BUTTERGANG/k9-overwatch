"""
Tests for the re-match / re-scoring logic in the matching engine and repository.

These cover the gaps that existed before:
  * A newly-ingested FOUND report must surface a match for an already-known LOST pet
    (reverse direction), not only the other way around.
  * Matching must be idempotent: re-running the pass updates an existing match's
    score/confidence in place (e.g. after geocoding fills in coordinates) instead
    of creating duplicates or silently doing nothing.
  * A human-rejected match is preserved and never auto-overwritten.
  * The re-match pool (`get_matchable_records`) includes records that already
    participate in a match, so they keep getting reconsidered.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from k9overwatch.db.models import PetRow
from k9overwatch.db.repository import PetRepository
from k9overwatch.matching.lost_found_matcher import LOST_FOUND_MIN_SCORE, LostFoundMatcher
from k9overwatch.matching.signals import MatchResult
from k9overwatch.models.enums import AnimalType, Gender, RecordType

from .conftest import make_indy_record, make_petconnect24_record


def _row(db_session, record, **overrides):
    """Build and persist a PetRow from a PetRecord factory."""
    import uuid

    r = record(**overrides)
    row = PetRow(
        id=str(uuid.uuid4()),
        source=r.source,
        source_id=r.source_id,
        record_type=str(r.record_type),
        animal_type=str(r.animal_type) if r.animal_type else None,
        name=r.name,
        breed=r.breed,
        color_primary=r.color_primary,
        color_secondary=r.color_secondary,
        gender=str(r.gender) if r.gender else None,
        date_event=r.date_event,
        lat=r.lat,
        lon=r.lon,
        zip=r.zip,
        description=r.description,
        microchip_number=r.microchip_number,
        active=True,
    )
    db_session.add(row)
    return row


class TestReverseMatching:
    """A new FOUND report should match an already-stored LOST pet."""

    def test_found_to_lost_reverse(self, db_session):
        matcher = LostFoundMatcher()
        lost = _row(
            db_session, make_indy_record,
            record_type=RecordType.LOST, animal_type=AnimalType.DOG,
            name="Rex", breed="Golden Retriever", color_primary="Golden",
            gender=Gender.MALE, date_event=date(2026, 3, 20),
            lat=39.82, lon=-86.13, zip="46205",
        )
        found = _row(
            db_session, make_petconnect24_record,
            record_type=RecordType.FOUND, animal_type=AnimalType.DOG,
            name=None, breed="Golden Retriever", color_primary="Golden",
            gender=Gender.MALE, date_event=date(2026, 3, 22),
            lat=39.82, lon=-86.13, zip="46205",
        )

        # Found report is the "new" record; lost is the candidate pool.
        results = matcher.find_reverse_matches(found, [lost])
        assert len(results) == 1
        assert results[0].score >= LOST_FOUND_MIN_SCORE
        assert results[0].match_type == "lost_found"

    def test_reverse_ignores_non_lost_candidates(self, db_session):
        matcher = LostFoundMatcher()
        found = _row(
            db_session, make_petconnect24_record, record_type=RecordType.FOUND,
            animal_type=AnimalType.DOG, date_event=date(2026, 3, 22), zip="46205",
        )
        other_found = _row(
            db_session, make_indy_record, record_type=RecordType.FOUND,
            animal_type=AnimalType.DOG, date_event=date(2026, 3, 20), zip="46205",
        )
        assert matcher.find_reverse_matches(found, [other_found]) == []

    def test_reverse_and_forward_agree_on_score(self, db_session):
        """Score is symmetric regardless of which side is "new"."""
        matcher = LostFoundMatcher()
        lost = _row(
            db_session, make_indy_record,
            record_type=RecordType.LOST, animal_type=AnimalType.DOG,
            breed="Golden Retriever", color_primary="Golden", gender=Gender.MALE,
            date_event=date(2026, 3, 20), lat=39.82, lon=-86.13, zip="46205",
        )
        found = _row(
            db_session, make_petconnect24_record,
            record_type=RecordType.FOUND, animal_type=AnimalType.DOG,
            breed="Golden Retriever", color_primary="Golden", gender=Gender.MALE,
            date_event=date(2026, 3, 22), lat=39.82, lon=-86.13, zip="46205",
        )
        forward = matcher.find_matches(lost, [found])
        reverse = matcher.find_reverse_matches(found, [lost])
        assert forward and reverse
        assert forward[0].score == pytest.approx(reverse[0].score)


class TestMatchUpsert:
    """save_match must refresh existing matches and respect human rejection."""

    @pytest.mark.asyncio
    async def test_rescoring_updates_existing_match(self, db_session):
        repo = PetRepository(db_session)
        a, _ = await repo.upsert(make_indy_record(source_id="ra"))
        b, _ = await repo.upsert(make_petconnect24_record(source_id="rb"))

        # First save: a low score
        first = MatchResult(
            pet_a_id=a.id, pet_b_id=b.id, match_type="lost_found",
            score=0.35, confidence="low",
            signals_fired={"zip_match": 0.20, "color_primary_match": 0.10},
        )
        assert await repo.save_match(first) is True

        # Re-run with better data → higher score
        improved = MatchResult(
            pet_a_id=a.id, pet_b_id=b.id, match_type="lost_found",
            score=0.80, confidence="high",
            signals_fired={"zip_match": 0.20, "color_primary_match": 0.10,
                           "geo_very_close": 0.25, "breed_exact": 0.15,
                           "name_exact": 0.15},
        )
        assert await repo.save_match(improved) is False  # updated, not new

        matches = await repo.get_matches_for_pet(a.id)
        assert len(matches) == 1
        assert matches[0].score == pytest.approx(0.80)
        assert matches[0].confidence == "high"

    @pytest.mark.asyncio
    async def test_human_rejection_preserved(self, db_session):
        repo = PetRepository(db_session)
        a, _ = await repo.upsert(make_indy_record(source_id="ra"))
        b, _ = await repo.upsert(make_petconnect24_record(source_id="rb"))

        first = MatchResult(
            pet_a_id=a.id, pet_b_id=b.id, match_type="lost_found",
            score=0.40, confidence="medium",
            signals_fired={"zip_match": 0.20, "color_primary_match": 0.10},
        )
        await repo.save_match(first)

        # Human reviews and rejects
        m = (await repo.get_matches_for_pet(a.id))[0]
        m.reviewed = True
        m.confirmed = False
        await db_session.flush()

        # Re-match pass would try to overwrite with a higher score; must be ignored
        second = MatchResult(
            pet_a_id=a.id, pet_b_id=b.id, match_type="lost_found",
            score=0.90, confidence="high",
            signals_fired={"zip_match": 0.20, "color_primary_match": 0.10,
                           "geo_very_close": 0.25, "breed_exact": 0.15,
                           "name_exact": 0.15, "microchip_match": 0.50},
        )
        assert await repo.save_match(second) is False
        matches = await repo.get_matches_for_pet(a.id)
        assert matches[0].score == pytest.approx(0.40)  # unchanged
        assert matches[0].confirmed is False


class TestRematchPool:
    """get_matchable_records must re-include already-matched records."""

    @pytest.mark.asyncio
    async def test_matchable_includes_matched_records(self, db_session):
        repo = PetRepository(db_session)
        a, _ = await repo.upsert(make_indy_record(source_id="ra"))
        b, _ = await repo.upsert(make_petconnect24_record(source_id="rb"))

        # A pre-existing match between a and b
        match = MatchResult(
            pet_a_id=a.id, pet_b_id=b.id, match_type="lost_found",
            score=0.40, confidence="medium", signals_fired={"zip_match": 0.20},
        )
        await repo.save_match(match)

        # get_unmatched_records would EXCLUDE both a and b
        unmatched = await repo.get_unmatched_records()
        unmatched_ids = {r.id for r in unmatched}
        assert a.id not in unmatched_ids
        assert b.id not in unmatched_ids

        # get_matchable_records INCLUDES them so re-match can refresh the score
        matchable = await repo.get_matchable_records()
        matchable_ids = {r.id for r in matchable}
        assert a.id in matchable_ids
        assert b.id in matchable_ids

    @pytest.mark.asyncio
    async def test_matchable_window_bounding(self, db_session):
        repo = PetRepository(db_session)
        # Old record (outside the 120-day window)
        old = make_indy_record(source_id="old", date_event=date(2020, 1, 1),
                               lat=None, lon=None, location_text=None, zip="46205")
        row_old, _ = await repo.upsert(old)
        row_old.date_event = date(2020, 1, 1)
        await db_session.flush()

        # Recent record (inside window)
        recent = make_indy_record(source_id="recent", date_event=date(2026, 3, 20),
                                  lat=None, lon=None, location_text=None, zip="46205")
        row_recent, _ = await repo.upsert(recent)

        since = date.today() - timedelta(days=120)
        matchable = await repo.get_matchable_records(since_date=since)
        ids = {r.id for r in matchable}
        assert row_recent.id in ids
        assert row_old.id not in ids
