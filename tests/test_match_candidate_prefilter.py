"""Tests for SQL-level bounding-box pre-filtering in find_match_candidates (B4/B5)."""

from __future__ import annotations

import math
from datetime import date

from sqlalchemy import event

from k9overwatch.db.models import PetRow
from k9overwatch.db.repository import PetRepository
from k9overwatch.models.enums import AnimalType, RecordType
from k9overwatch.models.pet_record import PetRecord


def _rec(source_id: str, **kw) -> PetRecord:
    return PetRecord(
        source="test", source_id=source_id,
        record_type=RecordType.LOST, animal_type=AnimalType.DOG,
        date_event=date(2026, 8, 1), **kw,
    )


async def _seed(db_session, rows: list[dict]) -> None:
    for r in rows:
        db_session.add(PetRow(
            source="other", source_id=r["sid"], record_type="found", animal_type="dog",
            active=True,
            lat=r.get("lat"), lon=r.get("lon"),
            date_event=date(2026, 8, 1),
        ))
    await db_session.commit()


async def test_bbox_filter_is_applied_in_sql(db_session):
    """The candidate query's SQL text must contain lat/lon BETWEEN bounding box."""
    captured: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        if "FROM pets" in statement or "from pets" in statement:
            captured.append(statement)

    engine = db_session.bind
    event.listen(engine.sync_engine, "before_cursor_execute", _capture)
    try:
        repo = PetRepository(db_session)
        await repo.find_match_candidates(
            _rec("self", lat=39.77, lon=-86.16), search_radius_miles=15.0
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _capture)

    assert captured, "expected a candidate query to run"
    stmt = "\n".join(captured)
    assert "lat BETWEEN" in stmt or "lat between" in stmt.lower()
    assert "lon BETWEEN" in stmt or "lon between" in stmt.lower()


async def test_candidates_equivalent_to_brute_force_haversine(db_session):
    """Result set matches a brute-force Python haversine filter on fixture data."""
    # Mix of in-radius, out-of-radius, no-coords, wrong animal type, inactive.
    fixture = [
        {"sid": "near", "lat": 39.80, "lon": -86.20},
        {"sid": "far", "lat": 40.90, "lon": -87.50},
        {"sid": "nocoords"},
        {"sid": "edge", "lat": 39.95, "lon": -86.30},
        {"sid": "far2", "lat": 38.20, "lon": -85.00},
    ]
    await _seed(db_session, fixture)

    repo = PetRepository(db_session)
    record = _rec("self", lat=39.77, lon=-86.16)
    got = {r.source_id for r in await repo.find_match_candidates(record, search_radius_miles=15.0)}

    def hav(lat2, lon2):
        R = 3958.8
        p1, p2 = math.radians(39.77), math.radians(lat2)
        dp = math.radians(lat2 - 39.77)
        dl = math.radians(lon2 + 86.16)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    expected = {
        f["sid"] for f in fixture
        if f.get("lat") is None or hav(f["lat"], f["lon"]) <= 15.0
    }
    assert got == expected == {"near", "nocoords", "edge"}


async def test_no_coordinates_on_record_skips_geo_filter(db_session):
    """When the record itself has no coordinates, no geo filtering happens."""
    await _seed(db_session, [
        {"sid": "anywhere", "lat": 10.0, "lon": 10.0},
    ])
    repo = PetRepository(db_session)
    got = await repo.find_match_candidates(_rec("self"), search_radius_miles=15.0)
    assert [r.source_id for r in got] == ["anywhere"]
