"""Google Maps Geocoding API provider ($5/1000 requests, 40K/month free)."""
from __future__ import annotations

import os

import aiohttp

from ...models.enums import GeocodeConfidence, GeocodeSource
from ..geocoder import BaseGeocodeProvider, GeocodeResult


class GoogleMapsProvider(BaseGeocodeProvider):
    BASE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("GOOGLE_MAPS_API_KEY", "")
        if not self.api_key:
            raise ValueError("GOOGLE_MAPS_API_KEY environment variable not set")

    async def geocode(self, address: str) -> GeocodeResult | None:
        params = {"address": address, "key": self.api_key, "region": "us"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.BASE_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()

            if data.get("status") != "OK" or not data.get("results"):
                return None

            result = data["results"][0]
            location = result["geometry"]["location"]
            location_type = result["geometry"].get("location_type", "")

            if location_type in ("ROOFTOP", "RANGE_INTERPOLATED"):
                confidence = GeocodeConfidence.HIGH
            elif location_type == "GEOMETRIC_CENTER":
                confidence = GeocodeConfidence.MEDIUM
            else:
                confidence = GeocodeConfidence.LOW

            return GeocodeResult(
                lat=location["lat"],
                lon=location["lng"],
                geocode_source=GeocodeSource.GOOGLE,
                geocode_confidence=confidence,
                raw_response=result,
            )

        except Exception:
            return None
