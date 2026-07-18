"""IndyLostPetAlert scraper — WordPress REST API, no bot protection."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime

import aiohttp

from ...models.pet_record import PetRecord
from ...normalizers.indy_lost_pet_alert import IndyNormalizer
from ..base import BaseScraper, ScraperConfig


class IndyLostPetAlertScraper(BaseScraper):
    SOURCE_NAME = "indylostpetalert"
    SUPPORTS_INCREMENTAL = True

    BASE_URL = "https://www.indylostpetalert.com/wp-json/wp/v2/posts"
    PER_PAGE = 100  # max allowed by WP REST API

    # Category IDs for filtering
    ALL_TYPE_CATEGORIES = "19,20,21"  # lost, found, sighting

    # Fields to request (reduces response payload)
    FIELDS = "id,date,date_gmt,modified,slug,title,content,excerpt,link,categories,tags,jetpack_featured_media_url"

    def __init__(self, config: ScraperConfig):
        super().__init__(config)
        self.normalizer = IndyNormalizer()

    async def scrape(
        self,
        after: datetime | None = None,
    ) -> AsyncIterator[PetRecord]:
        """Yield PetRecords from IndyLostPetAlert, newest first."""
        params = {
            "categories": self.ALL_TYPE_CATEGORIES,
            "per_page": self.PER_PAGE,
            "orderby": "date",
            "order": "desc",
            "_fields": self.FIELDS,
        }
        if after:
            params["after"] = after.strftime("%Y-%m-%dT%H:%M:%S")

        page = 1
        total_pages = 1

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            while page <= total_pages:
                if self.config.max_pages and page > self.config.max_pages:
                    break

                params["page"] = page
                try:
                    async with session.get(
                        self.BASE_URL,
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as resp:
                        if resp.status == 400:
                            break  # WP returns 400 when page > total_pages
                        resp.raise_for_status()

                        if page == 1:
                            total_pages = int(resp.headers.get("X-WP-TotalPages", 1))

                        posts = await resp.json()

                except aiohttp.ClientError as exc:
                    self._record_error(exc, f"page {page}")
                    break

                for post in posts:
                    try:
                        record = self.normalizer.normalize(post)
                        self._records_fetched += 1
                        yield record
                    except Exception as exc:
                        self._record_error(exc, f"post {post.get('id')}")

                page += 1
                if page <= total_pages:
                    await asyncio.sleep(self.config.rate_limit_seconds)

    async def check_active(self, source_id: str) -> bool:
        """Check if a WP post still exists and is published."""
        url = f"{self.BASE_URL}/{source_id}"
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 404:
                        return False
                    resp.raise_for_status()
                    post = await resp.json()
                    return post.get("status") == "publish"
        except Exception:
            return True  # assume active on network error (don't falsely deactivate)
