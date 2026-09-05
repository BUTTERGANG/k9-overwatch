"""Consent-gated EXIF GPS in the owner report-upload flow."""
from __future__ import annotations

import io

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.repository import UserRepository
from k9overwatch.geocoding.exif_gps import extract_gps, strip_gps
from k9overwatch.models.enums import GeocodeConfidence, GeocodeSource
from k9overwatch.web.auth import COOKIE_NAME, csrf_token_for, make_session_token
from k9overwatch.web.main import app
from k9overwatch.web.routers import reports

from .test_accounts_reports import VALID_JPEG
from .test_exif_gps import _jpeg_with_gps

INDY_LAT = (39, 46, 6.0)
INDY_LON = (86, 9, 29.0)


@pytest.fixture
async def client(db_session):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from k9overwatch.db import connection as db_conn
    from k9overwatch.web import dependencies as deps

    engine = db_session.bind
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    db_conn._engine = engine
    db_conn._session_factory = factory

    async def _override():
        async with factory() as s:
            yield s

    app.dependency_overrides[deps.get_db] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def _gps_jpeg() -> bytes:
    return _jpeg_with_gps(INDY_LAT, INDY_LON)


@pytest.mark.asyncio
async def test_consent_on_geocodes_from_exif_and_skips_cascade(
    client, db_session, tmp_path, monkeypatch
):
    """Consented GPS photo → EXACT/EXIF_GPS pin; address cascade never runs."""
    monkeypatch.setattr(reports, "UPLOAD_DIR", str(tmp_path))

    async def explode(self, address):  # cascade must NOT be invoked
        raise AssertionError("geocode cascade must be skipped for EXIF GPS")

    from k9overwatch.geocoding.providers.nominatim import NominatimProvider

    monkeypatch.setattr(NominatimProvider, "geocode", explode)

    user = await UserRepository(db_session).create("exif@example.com", "password123")
    await db_session.commit()

    resp = await client.post(
        "/report",
        data={
            "record_type": "lost",
            "location_text": "somewhere in Indy",
            "use_photo_location": "on",
            "csrf_token": csrf_token_for(user.id),
        },
        files=[("files", ("dog.jpg", io.BytesIO(_gps_jpeg()), "image/jpeg"))],
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(user.id)}"},
    )
    assert resp.status_code == 302
    assert "located_from_photo=1" in resp.headers["location"]

    row_id = resp.headers["location"].split("/")[-1].split("?")[0]
    from sqlalchemy import select

    from k9overwatch.db.models import PetRow

    row = (await db_session.execute(select(PetRow).where(PetRow.id == row_id))).scalar_one()
    assert row.lat == pytest.approx(39.7683, abs=1e-3)
    assert row.lon == pytest.approx(86.1581, abs=1e-3)
    assert row.geocode_source == GeocodeSource.EXIF_GPS.value
    assert row.geocode_confidence == GeocodeConfidence.EXACT.value


@pytest.mark.asyncio
async def test_consent_off_stores_stripped_photo_and_uses_cascade(
    client, db_session, tmp_path, monkeypatch
):
    """No consent: GPS-tagged photo is sanitized on disk; geocodes via address."""
    monkeypatch.setattr(reports, "UPLOAD_DIR", str(tmp_path))

    async def fake_geocode(self, address):
        from k9overwatch.geocoding.geocoder import GeocodeResult

        return GeocodeResult(
            lat=39.7684,
            lon=-86.1581,
            geocode_source=GeocodeSource.NOMINATIM,
            geocode_confidence=GeocodeConfidence.HIGH,
        )

    from k9overwatch.geocoding.providers.nominatim import NominatimProvider

    monkeypatch.setattr(NominatimProvider, "geocode", fake_geocode)

    user = await UserRepository(db_session).create("nogps@example.com", "password123")
    await db_session.commit()

    resp = await client.post(
        "/report",
        data={
            "record_type": "lost",
            "location_text": "Downtown Indianapolis",
            "csrf_token": csrf_token_for(user.id),
        },
        files=[("files", ("dog.jpg", io.BytesIO(_gps_jpeg()), "image/jpeg"))],
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(user.id)}"},
    )
    assert resp.status_code == 302
    assert "located_from_photo" not in resp.headers["location"]

    # The stored file has no GPS metadata even though the upload carried it.
    stored = list(tmp_path.iterdir())
    assert len(stored) == 1
    assert extract_gps(stored[0].read_bytes()) is None


@pytest.mark.asyncio
async def test_consent_on_without_gps_falls_back_to_cascade(
    client, db_session, tmp_path, monkeypatch
):
    """Consent given but the photo has no GPS tags → normal cascade runs."""
    monkeypatch.setattr(reports, "UPLOAD_DIR", str(tmp_path))

    async def fake_geocode(self, address):
        from k9overwatch.geocoding.geocoder import GeocodeResult

        return GeocodeResult(
            lat=39.7684,
            lon=-86.1581,
            geocode_source=GeocodeSource.NOMINATIM,
            geocode_confidence=GeocodeConfidence.MEDIUM,
        )

    from k9overwatch.geocoding.providers.nominatim import NominatimProvider

    monkeypatch.setattr(NominatimProvider, "geocode", fake_geocode)

    user = await UserRepository(db_session).create("plain@example.com", "password123")
    await db_session.commit()

    resp = await client.post(
        "/report",
        data={
            "record_type": "lost",
            "location_text": "Fountain Square",
            "use_photo_location": "on",
            "csrf_token": csrf_token_for(user.id),
        },
        files=[("files", ("dog.jpg", io.BytesIO(strip_gps(VALID_JPEG)), "image/jpeg"))],
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(user.id)}"},
    )
    assert resp.status_code == 302
    assert "located_from_photo" not in resp.headers["location"]


@pytest.mark.asyncio
async def test_consent_on_still_strips_gps_from_disk_copy(
    client, db_session, tmp_path, monkeypatch
):
    """Privacy invariant: even a consented upload stores GPS-stripped bytes."""
    monkeypatch.setattr(reports, "UPLOAD_DIR", str(tmp_path))

    async def fake_geocode(self, address):
        from k9overwatch.geocoding.geocoder import GeocodeResult

        return GeocodeResult(
            lat=39.7684,
            lon=-86.1581,
            geocode_source=GeocodeSource.NOMINATIM,
            geocode_confidence=GeocodeConfidence.MEDIUM,
        )

    from k9overwatch.geocoding.providers.nominatim import NominatimProvider

    monkeypatch.setattr(NominatimProvider, "geocode", fake_geocode)

    user = await UserRepository(db_session).create("strip@example.com", "password123")
    await db_session.commit()

    resp = await client.post(
        "/report",
        data={
            "record_type": "found",
            "location_text": "",
            "use_photo_location": "on",
            "zip": "46205",
            "csrf_token": csrf_token_for(user.id),
        },
        files=[("files", ("dog.jpg", io.BytesIO(_gps_jpeg()), "image/jpeg"))],
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(user.id)}"},
    )
    assert resp.status_code == 302
    stored = list(tmp_path.iterdir())
    assert len(stored) == 1
    assert extract_gps(stored[0].read_bytes()) is None
