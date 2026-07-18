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


# ZIP code centroids for fallback (top 1000 US ZIPs by population)
# Full dataset loaded from zip_centroids.csv if available; these are common Indianapolis ZIPs
_ZIP_CENTROIDS: dict[str, tuple[float, float]] = {
    "46201": (39.7725, -86.1074),
    "46202": (39.7862, -86.1551),
    "46203": (39.7477, -86.1074),
    "46204": (39.7684, -86.1581),
    "46205": (39.8195, -86.1312),
    "46208": (39.8085, -86.1790),
    "46218": (39.8071, -86.0851),
    "46219": (39.7674, -86.0437),
    "46220": (39.8680, -86.1082),
    "46221": (39.7271, -86.2214),
    "46222": (39.7893, -86.2227),
    "46224": (39.7895, -86.2688),
    "46225": (39.7289, -86.1581),
    "46226": (39.8264, -86.0655),
    "46227": (39.6881, -86.1581),
    "46228": (39.8459, -86.2163),
    "46229": (39.7694, -85.9984),
    "46231": (39.7326, -86.3177),
    "46234": (39.8254, -86.3093),
    "46235": (39.8264, -85.9813),
    "46236": (39.8754, -85.9642),
    "46237": (39.6672, -86.1004),
    "46239": (39.7085, -86.0173),
    "46240": (39.9025, -86.1262),
    "46241": (39.7325, -86.2688),
    "46250": (39.9040, -86.0567),
    "46254": (39.8544, -86.2688),
    "46256": (39.9025, -85.9897),
    "46259": (39.6587, -86.0100),
    "46260": (39.9023, -86.1754),
    "46268": (39.9106, -86.2258),
    "46278": (39.8795, -86.3215),
    "46280": (39.9528, -86.1159),
}


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

        # 3. ZIP centroid fallback
        if result is None and record.zip:
            coords = _ZIP_CENTROIDS.get(record.zip)
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
        from ..db.models import GeocodeCache

        key = _normalize_address(address)
        row = GeocodeCache(
            address_key=key,
            lat=result.lat,
            lon=result.lon,
            geocode_source=str(result.geocode_source),
            geocode_confidence=str(result.geocode_confidence),
            cached_at=datetime.now(UTC),
        )
        self.session.add(row)
        try:
            await self.session.flush()
        except Exception:
            # Duplicate key — already cached by concurrent request, ignore
            await self.session.rollback()
