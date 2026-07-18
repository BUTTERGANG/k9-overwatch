"""OpenStreetMap Nominatim geocoding provider (free, 1 req/sec)."""
from __future__ import annotations

import asyncio
import os

import aiohttp

from ...models.enums import GeocodeConfidence, GeocodeSource
from ..geocoder import BaseGeocodeProvider, GeocodeResult


class NominatimProvider(BaseGeocodeProvider):
    BASE_URL = "https://nominatim.openstreetmap.org/search"
    RATE_LIMIT = 1.1  # slightly above 1 req/sec per OSM terms

    def __init__(self):
        user_agent = os.getenv("NOMINATIM_USER_AGENT", "k9overwatch/1.0")
        self.headers = {"User-Agent": user_agent, "Accept-Language": "en"}
        self._last_request: float = 0.0

    async def geocode(self, address: str) -> GeocodeResult | None:
        # Enforce rate limit
        now = asyncio.get_event_loop().time()
        wait = self.RATE_LIMIT - (now - self._last_request)
        if wait > 0:
            await asyncio.sleep(wait)

        params = {
            "q": address,
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 1,
            "countrycodes": "us,ca",
        }

        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(self.BASE_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    self._last_request = asyncio.get_event_loop().time()
                    if resp.status != 200:
                        return None
                    data = await resp.json()

            if not data:
                return None

            hit = data[0]
            lat = float(hit["lat"])
            lon = float(hit["lon"])

            # Determine confidence from result type
            place_type = hit.get("type", "")
            place_class = hit.get("class", "")
            importance = float(hit.get("importance", 0))

            if place_type in ("house", "building") or place_class == "building":
                confidence = GeocodeConfidence.HIGH
            elif place_type in ("road", "pedestrian", "street") or importance > 0.4:
                confidence = GeocodeConfidence.HIGH
            elif place_type in ("postcode", "suburb", "neighbourhood"):
                confidence = GeocodeConfidence.MEDIUM
            else:
                confidence = GeocodeConfidence.MEDIUM

            return GeocodeResult(
                lat=lat,
                lon=lon,
                geocode_source=GeocodeSource.NOMINATIM,
                geocode_confidence=confidence,
                raw_response=hit,
            )

        except Exception:
            return None
