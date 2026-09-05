"""IndyHumane scraper — Shelterluv embed, plain HTML, no bot protection."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime

import aiohttp
from bs4 import BeautifulSoup

from ...models.enums import AnimalType
from ...models.pet_record import PetRecord
from ...normalizers.indyhumane import IndyHumaneNormalizer
from ..base import BaseScraper, ScraperConfig


class IndyHumaneScraper(BaseScraper):
    SOURCE_NAME = "indyhumane"
    SUPPORTS_INCREMENTAL = False  # No date filter — full scrape each time

    PAGES = [
        ("dogs", "https://indyhumane.org/adopt/adoptable-dogs/", AnimalType.DOG),
        ("cats", "https://indyhumane.org/adopt/adoptable-cats/", AnimalType.CAT),
    ]

    def __init__(self, config: ScraperConfig):
        super().__init__(config)
        self.normalizer = IndyHumaneNormalizer()

    async def scrape(
        self,
        after: datetime | None = None,
    ) -> AsyncIterator[PetRecord]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            for slug, url, animal_type in self.PAGES:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        resp.raise_for_status()
                        html = await resp.text()
                except Exception as exc:
                    self._record_error(exc, f"fetch {slug}")
                    continue

                soup = BeautifulSoup(html, "lxml")
                cards = soup.select("div.sla-card")
                if not cards:
                    self._record_error(
                        Exception(f"No sla-card divs found on {url}"),
                        "parse",
                    )
                    continue

                for card in cards:
                    try:
                        record = self.normalizer.normalize(card, animal_type)
                        if record:
                            self._records_fetched += 1
                            yield record
                    except Exception as exc:
                        self._record_error(exc, f"normalize card on {slug}")

                await asyncio.sleep(0.5)

    async def check_active(
        self, source_id: str, source_url: str | None = None
    ) -> bool:
        """Check if a pet is still listed on IndyHumane."""
        url = f"https://indyhumane.org/adopt/adopt-me/?id={source_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    return resp.status == 200
        except Exception:
            return True  # fail-open