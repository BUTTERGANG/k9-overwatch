"""Tests for display-layer pin fuzzing of ZIP-centroid geocodes."""
from __future__ import annotations

import pytest

from k9overwatch.geocoding.display_fuzz import (
    MAX_OFFSET_M,
    MIN_OFFSET_M,
    fuzz_lat_lon,
    fuzz_offset_meters,
    offset_distance_m,
)


def test_fuzz_is_deterministic_per_source_id():
    a = fuzz_lat_lon(39.7684, -86.1581, "24petconnect:12345")
    b = fuzz_lat_lon(39.7684, -86.1581, "24petconnect:12345")
    assert a == b


def test_different_source_ids_get_different_offsets():
    a = fuzz_lat_lon(39.7684, -86.1581, "source-a:1")
    b = fuzz_lat_lon(39.7684, -86.1581, "source-b:2")
    assert a != b


def test_offset_magnitude_within_annulus_bounds():
    for source_id in [f"src:{i}" for i in range(50)]:
        dlat_m, dlon_m = fuzz_offset_meters(source_id)
        dist = (dlat_m**2 + dlon_m**2) ** 0.5
        assert MIN_OFFSET_M <= dist < MAX_OFFSET_M


def test_fuzz_distance_between_original_and_display_pin_bounded():
    for i in range(20):
        new_lat, new_lon = fuzz_lat_lon(39.7684, -86.1581, f"src:{i}")
        dist = offset_distance_m(39.7684, -86.1581, new_lat, new_lon)
        assert MIN_OFFSET_M <= dist <= MAX_OFFSET_M * 1.01


@pytest.fixture
def client(db_session):
    """TestClient with the DB dependency pointed at the in-memory session."""
    import httpx

    from k9overwatch.web.dependencies import get_db
    from k9overwatch.web.main import app

    async def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    yield httpx.AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_geojson_fuzzes_only_zip_centroid_records(client, db_session):
    from datetime import date, timedelta

    from k9overwatch.db.repository import PetRepository
    from k9overwatch.models.enums import GeocodeConfidence, GeocodeSource

    from .conftest import make_indy_record

    today = date.today()
    repo = PetRepository(db_session)
    zip_rec = make_indy_record(
        source_id="zip-1",
        date_event=today - timedelta(days=1),
        lat=39.79,
        lon=-86.16,
        location_text="46205",
        geocode_source=GeocodeSource.ZIP_CENTROID.value,
        geocode_confidence=GeocodeConfidence.LOW.value,
    )
    street_rec = make_indy_record(
        source_id="street-1",
        date_event=today - timedelta(days=1),
        lat=39.80,
        lon=-86.17,
        geocode_source=GeocodeSource.NOMINATIM.value,
        geocode_confidence=GeocodeConfidence.HIGH.value,
    )
    await repo.upsert(zip_rec)
    await repo.upsert(street_rec)
    await db_session.flush()

    async with client as c:
        resp = await c.get("/api/map/geojson?sw_lat=39&sw_lng=-87&ne_lat=40&ne_lng=-85")
    assert resp.status_code == 200
    feats = {f["properties"]["id"]: f for f in resp.json()["features"]}

    zip_feat = next(f for f in feats.values() if f["properties"]["name"] == "Buddy" and f["properties"]["location_text"] == "46205")
    street_feat = next(f for f in feats.values() if f["properties"]["location_text"] == "4521 N. Keystone Ave, Indianapolis, Marion County")

    # ZIP-centroid pin is moved off the true centroid by 0.5–1 km...
    zlon, zlat = zip_feat["geometry"]["coordinates"]
    dist = offset_distance_m(39.79, -86.16, zlat, zlon)
    assert MIN_OFFSET_M <= dist <= MAX_OFFSET_M * 1.01
    # ...but keeps its honest "ZIP code area" badge.
    assert zip_feat["properties"]["geocode_confidence"] == GeocodeConfidence.LOW.value
    assert zip_feat["properties"]["geocode_source"] == GeocodeSource.ZIP_CENTROID.value

    # Street-level geocode stays exactly where it is.
    slon, slat = street_feat["geometry"]["coordinates"]
    assert slat == pytest.approx(39.80)
    assert slon == pytest.approx(-86.17)
