"""24petconnect scraper — ASP.NET HTML POST, no bot protection."""
from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from datetime import datetime

import aiohttp
from bs4 import BeautifulSoup

from ...models.pet_record import PetRecord
from ...normalizers.petconnect24 import PetConnect24Normalizer
from ..base import BaseScraper, ScraperConfig


class PetConnect24Scraper(BaseScraper):
    SOURCE_NAME = "24petconnect"
    SUPPORTS_INCREMENTAL = False   # No date filter in the API

    BASE_URL = "https://24petconnect.com/PetHarbor/getAdoptableAnimalsByLatLon"
    DETAIL_BASE = "https://24petconnect.com/LostFound/Details"
    PAGE_SIZE = 30
    SEARCH_TYPES = ("LOST", "FOUND", "ADOPT")

    def __init__(self, config: ScraperConfig):
        super().__init__(config)
        self.normalizer = PetConnect24Normalizer()

    def _build_payload(self, search_type: str, offset: int = 0) -> dict:
        return {
            "model[SearchType]": search_type,
            "model[Latitude]": str(self.config.search_lat),
            "model[Longitude]": str(self.config.search_lon),
            "model[Miles]": str(self.config.search_radius_miles),
            "model[LocationChanged]": "true",
            "model[URLName]": "LostFound",
            "model[AnimalFilter][SearchType]": search_type,
            "model[AnimalFilter][URLName]": "LostFound",
            "model[AnimalFilter][SortBy]": "days",   # freshest first
            "model[Skip]": str(offset),
            "model[Take]": str(self.PAGE_SIZE),
        }

    async def scrape(
        self,
        after: datetime | None = None,
    ) -> AsyncIterator[PetRecord]:
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://24petconnect.com/LostFound",
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            for search_type in self.SEARCH_TYPES:
                if self.config.max_pages == 0:
                    continue
                async for record in self._scrape_search_type(session, search_type):
                    yield record

    async def _scrape_search_type(
        self, session: aiohttp.ClientSession, search_type: str
    ) -> AsyncIterator[PetRecord]:
        offset = 0
        total = None
        page = 0

        while True:
            if self.config.max_pages and page >= self.config.max_pages:
                break

            payload = self._build_payload(search_type, offset)
            try:
                async with session.post(
                    self.BASE_URL,
                    data=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    resp.raise_for_status()
                    html = await resp.text()
            except aiohttp.ClientError as exc:
                self._record_error(exc, f"{search_type} offset={offset}")
                break

            # Extract total count from embedded JS
            if total is None:
                count_match = re.search(r"globalAnimalCount\s*=\s*(\d+)", html)
                total = int(count_match.group(1)) if count_match else 0
                if total == 0:
                    break

            soup = BeautifulSoup(html, "lxml")
            cards = soup.select("div.gridResult")
            if not cards:
                if page == 0 and total > 0:
                    from ..base import StructuralChangeError
                    raise StructuralChangeError(f"No gridResult cards found despite total={total}. HTML layout may have changed.")
                break

            for card in cards:
                try:
                    record = self.normalizer.normalize(card, search_type)
                    self._records_fetched += 1
                    yield record
                except Exception as exc:
                    self._record_error(exc, f"card in {search_type}")

            offset += self.PAGE_SIZE
            page += 1
            if offset >= total:
                break

            await asyncio.sleep(self.config.rate_limit_seconds)

    async def check_active(self, source_id: str) -> bool:
        """Check if a detail page exists for this animal."""
        # Try public shelter code first; fall back to others
        url = f"{self.DETAIL_BASE}/Public/{source_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 404:
                        return False
                    text = await resp.text()
                    # PetHarbor shows "not found" text when animal is removed
                    return "not found" not in text.lower() and "no longer available" not in text.lower()
        except Exception:
            return True
