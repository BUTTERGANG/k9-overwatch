"""LostMyDoggie scraper — Cloudflare protected, ColdFusion HTML.

Card structure (confirmed from live page):
  .box_icon — card container (20 per page)
    a[href*='petid='] — link to detail (contains ID)
    h4 — pet name
    h6 (first) — "Lost  Male Dog" (status + gender + type)
    h6 (second) — "CITY, STATE\\nZIP"
    ul.custom li — [breed, colors, "Lost/Found: YYYY-MM-DD"]
    img.img-responsive — photo (relative URL)
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import AsyncIterator, Optional

from .base_browser import BrowserBaseScraper
from ...models.pet_record import PetRecord
from ...normalizers.lostmydoggie import LostMyDoggieNormalizer


class LostMyDoggieScraper(BrowserBaseScraper):
    SOURCE_NAME = "lostmydoggie"
    STEALTH_REQUIRED = True

    BASE_URL = "https://www.lostmydoggie.com/missing-pets.cfm"
    SITE_URL = "https://www.lostmydoggie.com"
    PER_PAGE = 20

    # petkindid: 1=dogs, 2=cats
    # alerttypeid: 1=lost, 3=found
    SEARCHES = [
        (1, 1, "dog", "lost"),
        (1, 3, "dog", "found"),
        (2, 1, "cat", "lost"),
        (2, 3, "cat", "found"),
    ]

    def __init__(self, config):
        super().__init__(config)
        self.normalizer = LostMyDoggieNormalizer()
        self.zip_code = config.extra.get("zip_code", "46201")

    async def _scrape_with_page(self, page, after: Optional[datetime]) -> AsyncIterator[PetRecord]:
        for petkindid, alerttypeid, animal_type, record_type in self.SEARCHES:
            async for record in self._scrape_search(
                page, petkindid, alerttypeid, animal_type, record_type, after
            ):
                yield record

    async def _scrape_search(
        self, page, petkindid: int, alerttypeid: int,
        animal_type: str, record_type: str, after: Optional[datetime]
    ) -> AsyncIterator[PetRecord]:
        page_num = 1
        start_r1 = 1

        while True:
            if self.config.max_pages and page_num > self.config.max_pages:
                break

            url = (
                f"{self.BASE_URL}"
                f"?petkindid={petkindid}"
                f"&alerttypeid={alerttypeid}"
                f"&zipcode={self.zip_code}"
                f"&radius={self.config.search_radius_miles}"
                f"&page_number={page_num}"
                f"&startr1={start_r1}"
                f"&sort=OrderDate"
            )

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
            except Exception as exc:
                self._record_error(exc, f"LostMyDoggie page {page_num}")
                break

            cards = await page.query_selector_all(".box_icon")
            if not cards:
                if page_num == 1:
                    from ..base import StructuralChangeError
                    raise StructuralChangeError("No '.box_icon' cards found on page 1. Site layout may have changed.")
                break

            page_yielded = False
            for card in cards:
                try:
                    data = await self._extract_card(card)
                    if not data:
                        continue
                    record = self.normalizer.normalize(data, animal_type, record_type)
                    if record:
                        self._records_fetched += 1
                        page_yielded = True

                        if after and record.date_event:
                            event_dt = datetime.combine(record.date_event, datetime.min.time())
                            if event_dt < after:
                                return

                        yield record
                except Exception as exc:
                    self._record_error(exc, "LostMyDoggie card")

            if not page_yielded:
                break

            page_num += 1
            start_r1 += self.PER_PAGE
            await asyncio.sleep(self.config.rate_limit_seconds)

    async def _extract_card(self, card) -> Optional[dict]:
        """Extract structured fields from a .box_icon card element."""
        # Pet ID from link href
        link = await card.query_selector("a[href*='petid=']")
        href = await link.get_attribute("href") if link else ""
        m = re.search(r"petid=(\d+)", href)
        if not m:
            return None
        pet_id = m.group(1)

        # Name
        name_el = await card.query_selector("h4")
        name = (await name_el.inner_text()).strip() if name_el else None

        # h6 elements: first=status/gender/type, second=location
        h6_els = await card.query_selector_all("h6")
        status_line = (await h6_els[0].inner_text()).strip() if len(h6_els) > 0 else ""
        location_raw = (await h6_els[1].inner_text()).strip() if len(h6_els) > 1 else ""

        # li items: breed, colors, date
        li_els = await card.query_selector_all("ul.custom li")
        details = [(await li.inner_text()).strip() for li in li_els]

        # Photo — thumbnail is at pet_images/thumbs/{id}.jpg;
        # full-res at pet_images/{id}.jpg (same server, ~80KB, accessible without auth)
        img = await card.query_selector("img.img-responsive")
        img_src = await img.get_attribute("src") if img else None
        thumbnail_url = None
        full_photo_url = None
        if img_src:
            if not img_src.startswith("http"):
                img_src = f"{self.SITE_URL}/{img_src}"
            thumbnail_url = img_src
            full_photo_url = img_src.replace("/thumbs/", "/")

        return {
            "pet_id": pet_id,
            "name": name,
            "status_line": status_line,
            "location_raw": location_raw,
            "details": details,
            "thumbnail_url": thumbnail_url,
            "full_photo_url": full_photo_url,
            "detail_url": f"{self.SITE_URL}/details.cfm?petid={pet_id}",
        }

    async def check_active(self, source_id: str) -> bool:
        return True  # LostMyDoggie requires Playwright for any check
