"""Tests for the geocoding service: providers, cache, and ZIP fallback."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from k9overwatch.geocoding.geocoder import (
    _ZIP_CENTROIDS,
    GeocodeResult,
    GeocodingService,
    _normalize_address,
)
from k9overwatch.models.enums import GeocodeConfidence, GeocodeSource

from .conftest import make_indy_record, make_petfbi_record

# ── _normalize_address ────────────────────────────────────────────────────────

class TestNormalizeAddress:
    def test_lowercases(self):
        result = _normalize_address("Indianapolis, IN")
        assert result == result.lower()
        assert "indianapolis" in result
        assert "in" in result

    def test_strips_punctuation(self):
        result = _normalize_address("4521 N. Keystone Ave., Indianapolis, IN")
        assert "," not in result
        assert "." not in result

    def test_collapses_whitespace(self):
        result = _normalize_address("  too   many   spaces  ")
        assert "  " not in result
        assert result == result.strip()


# ── ZIP centroids ─────────────────────────────────────────────────────────────

class TestZipCentroids:
    def test_known_indianapolis_zip(self):
        assert "46201" in _ZIP_CENTROIDS
        lat, lon = _ZIP_CENTROIDS["46201"]
        assert 39.0 < lat < 40.5
        assert -87.0 < lon < -85.0

    def test_centroid_coordinates_reasonable(self):
        for zip_code, (lat, lon) in _ZIP_CENTROIDS.items():
            assert 24.0 < lat < 50.0, f"Lat out of US range for {zip_code}"
            assert -130.0 < lon < -65.0, f"Lon out of US range for {zip_code}"


# ── PetRecord.needs_geocoding ─────────────────────────────────────────────────

class TestNeedsGeocoding:
    def test_needs_geocoding_has_location_no_coords(self):
        record = make_indy_record(lat=None, lon=None)
        assert record.needs_geocoding() is True

    def test_no_geocoding_needed_has_coords(self):
        record = make_petfbi_record()  # has lat/lon
        assert record.needs_geocoding() is False

    def test_no_geocoding_needed_no_address(self):
        record = make_indy_record(lat=None, lon=None, location_text=None, zip=None)
        assert record.needs_geocoding() is False


# ── PetRecord.geocoding_address ───────────────────────────────────────────────

class TestGeocodingAddress:
    def test_uses_location_text(self):
        record = make_indy_record(location_text="4521 N. Keystone Ave, Indianapolis, Marion County")
        addr = record.geocoding_address()
        assert "4521 N. Keystone" in addr
        assert "IN" in addr  # state appended

    def test_falls_back_to_zip(self):
        record = make_indy_record(location_text=None, zip="46205", state=None)
        addr = record.geocoding_address()
        assert addr == "46205"

    def test_returns_none_if_no_address(self):
        record = make_indy_record(location_text=None, zip=None)
        assert record.geocoding_address() is None


# ── GeocodingService ──────────────────────────────────────────────────────────

class TestGeocodingService:
    def _make_service(self, session, providers=None):
        return GeocodingService(session=session, providers=providers or [])

    @pytest.mark.asyncio
    async def test_skips_record_with_coordinates(self, db_session):
        """Records that already have coordinates are returned unchanged."""
        record = make_petfbi_record()  # has native lat/lon
        service = self._make_service(db_session)
        result = await service.geocode(record)
        assert result.lat == pytest.approx(39.8689)
        assert result.geocode_source == "petfbi_native"

    @pytest.mark.asyncio
    async def test_zip_centroid_fallback(self, db_session):
        """When all providers fail, falls back to ZIP centroid."""
        record = make_indy_record(lat=None, lon=None, location_text=None, zip="46201")
        service = self._make_service(db_session, providers=[])
        result = await service.geocode(record)
        assert result.lat is not None
        assert result.geocode_source == "zip_centroid"
        assert result.geocode_confidence == "low"

    @pytest.mark.asyncio
    async def test_zip_centroid_coordinates_correct(self, db_session):
        record = make_indy_record(lat=None, lon=None, location_text=None, zip="46201")
        service = self._make_service(db_session, providers=[])
        result = await service.geocode(record)
        expected_lat, expected_lon = _ZIP_CENTROIDS["46201"]
        assert result.lat == pytest.approx(expected_lat)
        assert result.lon == pytest.approx(expected_lon)

    @pytest.mark.asyncio
    async def test_provider_called_when_no_cache(self, db_session):
        """Provider geocode() is called when cache misses."""
        mock_provider = AsyncMock()
        mock_provider.geocode.return_value = GeocodeResult(
            lat=39.77,
            lon=-86.11,
            geocode_source=GeocodeSource.NOMINATIM,
            geocode_confidence=GeocodeConfidence.HIGH,
        )
        record = make_indy_record(lat=None, lon=None)
        service = self._make_service(db_session, providers=[mock_provider])
        result = await service.geocode(record)
        mock_provider.geocode.assert_called_once()
        assert result.lat == pytest.approx(39.77)
        assert result.geocode_source == "nominatim"

    @pytest.mark.asyncio
    async def test_provider_cascade_uses_first_success(self, db_session):
        """First successful provider wins; second is not called."""
        provider_a = AsyncMock()
        provider_a.geocode.return_value = GeocodeResult(
            lat=39.77, lon=-86.11,
            geocode_source=GeocodeSource.NOMINATIM,
            geocode_confidence=GeocodeConfidence.HIGH,
        )
        provider_b = AsyncMock()
        record = make_indy_record(lat=None, lon=None)
        service = self._make_service(db_session, providers=[provider_a, provider_b])
        await service.geocode(record)
        provider_a.geocode.assert_called_once()
        provider_b.geocode.assert_not_called()

    @pytest.mark.asyncio
    async def test_provider_cascade_skips_failed_provider(self, db_session):
        """Falls through to second provider when first returns None."""
        provider_a = AsyncMock()
        provider_a.geocode.return_value = None
        provider_b = AsyncMock()
        provider_b.geocode.return_value = GeocodeResult(
            lat=39.77, lon=-86.11,
            geocode_source=GeocodeSource.GOOGLE,
            geocode_confidence=GeocodeConfidence.HIGH,
        )
        record = make_indy_record(lat=None, lon=None)
        service = self._make_service(db_session, providers=[provider_a, provider_b])
        result = await service.geocode(record)
        assert result.geocode_source == "google"

    @pytest.mark.asyncio
    async def test_unknown_zip_no_centroid(self, db_session):
        """ZIP not in centroid dict → coordinates remain None."""
        record = make_indy_record(lat=None, lon=None, location_text=None, zip="99999")
        service = self._make_service(db_session, providers=[])
        result = await service.geocode(record)
        assert result.lat is None

    @pytest.mark.asyncio
    async def test_no_address_no_geocoding(self, db_session):
        """Record with no location text or ZIP is returned as-is."""
        record = make_indy_record(lat=None, lon=None, location_text=None, zip=None)
        service = self._make_service(db_session, providers=[])
        result = await service.geocode(record)
        assert result.lat is None

    @pytest.mark.asyncio
    async def test_geocode_batch(self, db_session):
        """geocode_batch processes all records."""
        records = [
            make_indy_record(lat=None, lon=None, location_text=None, zip="46201", source_id=f"r{i}")
            for i in range(3)
        ]
        service = self._make_service(db_session, providers=[])
        results = await service.geocode_batch(records)
        assert len(results) == 3
        # ZIP centroid fallback should have resolved all
        for r in results:
            assert r.lat is not None
