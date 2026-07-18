"""
API-level tests for the map buckets + geojson endpoints.

Uses httpx ASGITransport against the real FastAPI app, with the get_db
dependency overridden to the in-memory test session so no real DB is touched.
"""
from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest

from k9overwatch.db.repository import PetRepository
from k9overwatch.models.enums import RecordType
from k9overwatch.web.dependencies import get_db
from k9overwatch.web.main import app

from .conftest import make_indy_record


@pytest.fixture
def client(db_session):
    """TestClient with the DB dependency pointed at the in-memory session."""
    async def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    yield httpx.AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_buckets_endpoint_shape_and_counts(client, db_session):
    repo = PetRepository(db_session)
    today = date.today()
    for i, age in enumerate([2, 10, 25, 100]):
        await repo.upsert(make_indy_record(
            source_id=f"b{i}", date_event=today - timedelta(days=age),
        ))
    await db_session.flush()

    async with client as c:
        resp = await c.get("/api/map/buckets")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 4
    keys = [b["key"] for b in body["buckets"]]
    assert keys == ["week", "fortnight", "month", "older"]
    # Every bucket carries a human-friendly label for non-technical users.
    assert all(b["label"] for b in body["buckets"])
    counts = {b["key"]: b["count"] for b in body["buckets"]}
    assert counts == {"week": 1, "fortnight": 1, "month": 1, "older": 1}


@pytest.mark.asyncio
async def test_geojson_includes_age_bucket(client, db_session):
    repo = PetRepository(db_session)
    await repo.upsert(make_indy_record(
        source_id="geo1", record_type=RecordType.LOST,
        date_event=date.today() - timedelta(days=3),
        lat=39.77, lon=-86.15,
    ))
    await db_session.flush()

    async with client as c:
        resp = await c.get("/api/map/geojson", params={
            "sw_lat": 39.0, "sw_lng": -87.0, "ne_lat": 40.5, "ne_lng": -85.0,
            "days": 90,
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["features"][0]["properties"]["age_bucket"] == "week"


@pytest.mark.asyncio
async def test_geojson_keeps_records_without_date_event(client, db_session):
    """A listing with no parsed date_event must still appear on the map.

    The live scrapers often leave date_event null; dropping nulls would hide
    real pets from the map entirely (this was a regression we fixed).
    """
    repo = PetRepository(db_session)
    await repo.upsert(make_indy_record(
        source_id="nodate", record_type=RecordType.LOST,
        date_event=None,  # no parsed date
        lat=39.77, lon=-86.15,
    ))
    await db_session.flush()

    async with client as c:
        resp = await c.get("/api/map/geojson", params={
            "sw_lat": 39.0, "sw_lng": -87.0, "ne_lat": 40.5, "ne_lng": -85.0,
            "days": 30,  # tight window — a null-date record must still show
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1  # null-date record is NOT dropped from the map
    assert data["features"][0]["properties"]["age_bucket"] in ("week", "fortnight", "month", "older")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/map", "/pets", "/pets/results", "/matches", "/admin", "/login", "/register", "/report", "/account"])
async def test_html_pages_render(client, db_session, path):
    """
    Guard against broken TemplateResponse signatures / template syntax:
    every page-level route must return renderable HTML, not a 500.
    Starlette's newer TemplateResponse requires request-first; a regression
    here previously surfaced only in the browser, never in tests.
    """
    repo = PetRepository(db_session)
    await repo.upsert(make_indy_record(
        source_id="render1", date_event=date.today() - timedelta(days=2),
        lat=39.77, lon=-86.15,
    ))
    await db_session.flush()

    async with client as c:
        resp = await c.get(path)
    # Auth-gated pages legitimately redirect to /login when anonymous.
    assert resp.status_code in (200, 302, 303), f"{path} returned {resp.status_code}"
    if resp.status_code == 200:
        assert "text/html" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_pet_detail_renders_with_lens_button(client, db_session):
    """Detail page renders and shows the 'See similar photos' link when a photo exists."""
    repo = PetRepository(db_session)
    row, _ = await repo.upsert(make_indy_record(
        source_id="detail1", thumbnail_url="https://example.com/dog.jpg",
        date_event=date.today() - timedelta(days=2),
    ))
    await db_session.flush()

    async with client as c:
        resp = await c.get(f"/pets/{row.id}")
    assert resp.status_code == 200
    assert "See similar photos" in resp.text
    assert "lens.google.com" in resp.text
