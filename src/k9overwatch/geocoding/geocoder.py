"""GeocodingService — orchestrates providers, cache, and ZIP fallback."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.enums import GeocodeConfidence, GeocodeSource
from ..models.pet_record import PetRecord


@dataclass
class GeocodeResult:
    lat: float
    lon: float
    geocode_source: GeocodeSource
    geocode_confidence: GeocodeConfidence
    raw_response: dict | None = None


class BaseGeocodeProvider(ABC):
    @abstractmethod
    async def geocode(self, address: str) -> GeocodeResult | None:
        ...


# Session-level cache so zipcodes lookups are only done once per ZIP per process.
_ZIP_CENTROIDS: dict[str, tuple[float, float]] = {}


def _get_zip_centroid(zip_code: str) -> tuple[float, float] | None:
    """
    Return (lat, lon) for a US ZIP code.
    Uses a process-level cache backed by the `zipcodes` package which ships
    with a complete US dataset — no network calls, no external downloads.
    Falls back to None if the ZIP is unknown.
    """
    if zip_code in _ZIP_CENTROIDS:
        return _ZIP_CENTROIDS[zip_code]

    try:
        import zipcodes  # lightweight package, data bundled at install time
        matches = zipcodes.matching(zip_code)
        if matches:
            z = matches[0]
            lat = float(z["lat"])
            lon = float(z["long"])
            _ZIP_CENTROIDS[zip_code] = (lat, lon)
            return (lat, lon)
    except Exception:
        pass

    _ZIP_CENTROIDS[zip_code] = None  # type: ignore[assignment]  # negative cache
    return None


def _normalize_address(address: str) -> str:
    """Normalize address string for cache key lookup."""
    addr = address.lower().strip()
    addr = re.sub(r"[,\.]+", " ", addr)
    addr = re.sub(r"\s+", " ", addr)
    return addr


class GeocodingService:
    """
    Geocodes address strings to (lat, lon).
    - Skips records that already have coordinates (PetFBI native)
    - Checks DB cache first
    - Cascades through providers in priority order
    - Falls back to ZIP centroid if all providers fail
    """

    def __init__(
        self,
        session: AsyncSession,
        providers: list[BaseGeocodeProvider],
    ):
        self.session = session
        self.providers = providers

    async def geocode(self, record: PetRecord) -> PetRecord:
        """
        Enrich record.lat/lon in place if needed.
        Returns the (modified) record.
        """
        if not record.needs_geocoding():
            return record

        address = record.geocoding_address()
        if not address:
            return record

        # 1. Cache lookup
        result = await self._check_cache(address)

        # 2. Provider cascade
        if result is None:
            for provider in self.providers:
                result = await provider.geocode(address)
                if result is not None:
                    await self._save_cache(address, result)
                    break

        # 3. ZIP centroid fallback (nationwide via `zipcodes` package)
        if result is None and record.zip:
            coords = _get_zip_centroid(record.zip)
            if coords:
                result = GeocodeResult(
                    lat=coords[0],
                    lon=coords[1],
                    geocode_source=GeocodeSource.ZIP_CENTROID,
                    geocode_confidence=GeocodeConfidence.LOW,
                )

        if result is not None:
            record.lat = result.lat
            record.lon = result.lon
            record.geocode_source = result.geocode_source
            record.geocode_confidence = result.geocode_confidence

        return record

    async def geocode_batch(
        self,
        records: list[PetRecord],
        skip_if_has_coords: bool = True,
    ) -> list[PetRecord]:
        """Geocode a list of records, respecting the Nominatim rate limit automatically."""
        results = []
        for record in records:
            if skip_if_has_coords and not record.needs_geocoding():
                results.append(record)
                continue
            results.append(await self.geocode(record))
        return results

    # ── Cache helpers ─────────────────────────────────────────────────────────

    async def _check_cache(self, address: str) -> GeocodeResult | None:
        from sqlalchemy import select, update

        from ..db.models import GeocodeCache

        key = _normalize_address(address)
        stmt = select(GeocodeCache).where(GeocodeCache.address_key == key)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None

        # Increment hit count
        await self.session.execute(
            update(GeocodeCache)
            .where(GeocodeCache.address_key == key)
            .values(hit_count=row.hit_count + 1)
        )

        return GeocodeResult(
            lat=row.lat,
            lon=row.lon,
            geocode_source=GeocodeSource(row.geocode_source),
            geocode_confidence=GeocodeConfidence(row.geocode_confidence),
        )

    async def _save_cache(self, address: str, result: GeocodeResult) -> None:
        from sqlalchemy.exc import IntegrityError

        from ..db.models import GeocodeCache

        key = _normalize_address(address)
        row = GeocodeCache(
            address_key=key,
            lat=result.lat,
            lon=result.lon,
            geocode_source=str(result.geocode_source),
            geocode_confidence=str(result.geocode_confidence),
            cached_at=datetime.now(UTC).replace(tzinfo=None),
        )
        try:
            async with self.session.begin_nested():  # SAVEPOINT
                self.session.add(row)
                await self.session.flush()
        except IntegrityError:
            # Duplicate cache entry — a concurrent request already wrote it.
            # begin_nested() rolls back only the savepoint, leaving the outer
            # transaction (including any pet upserts) intact.
            pass
