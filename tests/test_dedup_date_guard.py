"""Deduplicator's internal date guard: pairs with event dates > DEDUP_MAX_AGE_DAYS apart never match."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from k9overwatch.db.models import PetRow
from k9overwatch.matching.deduplicator import DEDUP_MAX_AGE_DAYS, Deduplicator


def _row(**overrides) -> PetRow:
    base = dict(
        source="pawboost",
        source_id="pb-1",
        record_type="lost",
        animal_type="dog",
        name="Buddy",
        breed="Labrador Retriever",
        color_primary="Black",
        gender="male",
        date_event=date(2026, 5, 1),
        zip="46205",
        lat=39.82,
        lon=-86.13,
        description="Friendly black lab, blue collar.",
        active=True,
    )
    base.update(overrides)
    return PetRow(**base)


@pytest.fixture()
def dedup() -> Deduplicator:
    return Deduplicator()


def test_dates_100_days_apart_still_within_guard(dedup):
    """100 days apart is inside the 180-day guard: otherwise-identical fields still dedup
    (this is the widening past the 90-day candidate window)."""
    a = _row(source="pawboost", date_event=date(2026, 5, 1))
    b = _row(source="indylostpetalert", source_id="indy-1", date_event=date(2026, 8, 9))
    assert (date(2026, 8, 9) - date(2026, 5, 1)).days == 100
    assert len(dedup.find_duplicates(a, [b])) == 1


def test_dates_beyond_guard_never_match(dedup):
    """More than DEDUP_MAX_AGE_DAYS apart → hard skip even with identical fields."""
    a = _row(source="pawboost", date_event=date(2026, 5, 1))
    b = _row(
        source="indylostpetalert",
        source_id="indy-1",
        date_event=date(2026, 5, 1) + timedelta(days=DEDUP_MAX_AGE_DAYS + 1),
    )
    assert dedup.find_duplicates(a, [b]) == []


def test_dates_within_bound_still_match(dedup):
    a = _row(source="pawboost", date_event=date(2026, 5, 1))
    b = _row(
        source="indylostpetalert",
        source_id="indy-1",
        # Just inside the bound; identical otherwise.
        date_event=date(2026, 5, 1) + timedelta(days=DEDUP_MAX_AGE_DAYS),
    )
    results = dedup.find_duplicates(a, [b])
    assert len(results) == 1
    assert results[0].match_type == "dedup"


@pytest.mark.parametrize("missing_on", ["record", "candidate"])
def test_missing_date_on_either_side_is_not_skipped(dedup, missing_on):
    """A >bound gap only skips when BOTH dates exist; missing dates keep old behavior."""
    far_date = date(2026, 5, 1) + timedelta(days=DEDUP_MAX_AGE_DAYS + 30)
    a = _row(source="pawboost", date_event=None if missing_on == "record" else date(2026, 5, 1))
    b = _row(
        source="indylostpetalert",
        source_id="indy-1",
        date_event=far_date if missing_on == "record" else None,
    )
    # Without the guard this would be scored normally — verify no hard skip:
    # identical fields otherwise should still produce a match.
    assert len(dedup.find_duplicates(a, [b])) == 1
