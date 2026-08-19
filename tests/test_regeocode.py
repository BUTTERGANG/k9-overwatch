"""
Tests for the re-geocode backstop: `get_records_missing_coordinates` and the
`regeocode_pending_records` job.

A geocode can fail at ingestion time (provider rate-limited, timeout) and, for a
user-submitted report, is never retried otherwise — the report silently stays off
the map and unmatchable. This backstop finds active records with address text but
no coordinates and retries them.
"""
from __future__ import annotations

import uuid

import pytest

from k9overwatch.db.models import PetRow
from k9overwatch.db.repository import PetRepository
from k9overwatch.geocoding.geocoder import GeocodeResult
from k9overwatch.geocoding.providers.nominatim import NominatimProvider
from k9overwatch.models.enums import GeocodeConfidence, GeocodeSource


def _row(**overrides) -> PetRow:
    defaults = dict(
        id=str(uuid.uuid4()),
        source="user",
        source_id=f"user-{uuid.uuid4().hex[:8]}",
        record_type="lost",
        animal_type="dog",
        location_text="Indianapolis, IN",
        state="IN",
        country="US",
        active=True,
        lat=None,
        lon=None,
    )
    defaults.update(overrides)
    return PetRow(**defaults)


class TestGetRecordsMissingCoordinates:
    async def test_returns_active_rows_with_address_but_no_coords(self, db_session):
        pending = _row()
        db_session.add(pending)
        await db_session.flush()

        repo = PetRepository(db_session)
        rows = await repo.get_records_missing_coordinates()

        assert [r.id for r in rows] == [pending.id]

    async def test_excludes_rows_that_already_have_coordinates(self, db_session):
        db_session.add(_row(lat=39.7684, lon=-86.1581))
        await db_session.flush()

        repo = PetRepository(db_session)
        assert await repo.get_records_missing_coordinates() == []

    async def test_excludes_inactive_rows(self, db_session):
        db_session.add(_row(active=False))
        await db_session.flush()

        repo = PetRepository(db_session)
        assert await repo.get_records_missing_coordinates() == []

    async def test_excludes_rows_with_no_address_text_or_zip(self, db_session):
        db_session.add(_row(location_text=None, zip=None))
        await db_session.flush()

        repo = PetRepository(db_session)
        assert await repo.get_records_missing_coordinates() == []

    async def test_includes_rows_with_only_zip(self, db_session):
        row = _row(location_text=None, zip="46201")
        db_session.add(row)
        await db_session.flush()

        repo = PetRepository(db_session)
        assert [r.id for r in await repo.get_records_missing_coordinates()] == [row.id]


@pytest.mark.asyncio
async def test_regeocode_pending_records_fills_in_coordinates_and_matches(db_session, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from k9overwatch.db import connection as db_conn
    from k9overwatch.scheduler import jobs

    engine = db_session.bind
    factory = async_sessionmaker(engine, class_=type(db_session), expire_on_commit=False)
    saved_engine, saved_factory = db_conn._engine, db_conn._session_factory
    db_conn._engine, db_conn._session_factory = engine, factory

    async def fake_geocode(self, address):
        return GeocodeResult(
            lat=39.7684, lon=-86.1581,
            geocode_source=GeocodeSource.NOMINATIM,
            geocode_confidence=GeocodeConfidence.HIGH,
        )
    monkeypatch.setattr(NominatimProvider, "geocode", fake_geocode)

    matched_ids = []
    async def fake_matching_pass(new_row_ids=None, **kwargs):
        matched_ids.extend(new_row_ids or [])
        return {"dedup_found": 0, "matches_found": 0}
    monkeypatch.setattr(jobs, "run_matching_pass", fake_matching_pass)

    pending = _row()
    pending_id, source_id = pending.id, pending.source_id
    db_session.add(pending)
    await db_session.commit()

    try:
        result = await jobs.regeocode_pending_records(limit=10)
    finally:
        db_conn._engine, db_conn._session_factory = saved_engine, saved_factory

    assert result == {"checked": 10, "regeocoded": 1}
    assert matched_ids == [pending_id]

    db_session.expire_all()  # the job wrote through a separate session
    repo = PetRepository(db_session)
    row = await repo.get_by_key("user", source_id)
    assert row.lat == pytest.approx(39.7684)
    assert row.lon == pytest.approx(-86.1581)
    assert row.geocode_source == str(GeocodeSource.NOMINATIM)


@pytest.mark.asyncio
async def test_regeocode_pending_records_leaves_row_alone_on_provider_failure(db_session, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from k9overwatch.db import connection as db_conn
    from k9overwatch.scheduler import jobs

    engine = db_session.bind
    factory = async_sessionmaker(engine, class_=type(db_session), expire_on_commit=False)
    saved_engine, saved_factory = db_conn._engine, db_conn._session_factory
    db_conn._engine, db_conn._session_factory = engine, factory

    async def failing_geocode(self, address):
        return None
    monkeypatch.setattr(NominatimProvider, "geocode", failing_geocode)

    pending = _row()
    db_session.add(pending)
    await db_session.commit()

    try:
        result = await jobs.regeocode_pending_records(limit=10)
    finally:
        db_conn._engine, db_conn._session_factory = saved_engine, saved_factory

    assert result == {"checked": 10, "regeocoded": 0}

    repo = PetRepository(db_session)
    row = await repo.get_by_key("user", pending.source_id)
    assert row.lat is None
