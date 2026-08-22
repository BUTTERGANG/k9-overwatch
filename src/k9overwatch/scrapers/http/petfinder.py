"""Petfinder API v2 scraper — OAuth2 JSON API, no bot protection."""
from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import datetime

import aiohttp

from ...models.pet_record import PetRecord
from ...normalizers.petfinder import PetfinderNormalizer
from ..base import BaseScraper, ScraperConfig

_API_BASE = "https://api.petfinder.com/v2"
_TOKEN_URL = f"{_API_BASE}/oauth2/token"
_ANIMALS_URL = f"{_API_BASE}/animals"

# Petfinder API categories to fetch
_SEARCH_STATUSES = ("adoptable", "lost", "found")

_PAGE_LIMIT = 100  # max per page


class PetfinderScraper(BaseScraper):
    """Scrape animal listings from Petfinder.com's official API v2.

    Requires ``PETFINDER_API_KEY`` and ``PETFINDER_API_SECRET`` environment
    variables for client_credentials OAuth2 authentication.
    """

    SOURCE_NAME = "petfinder"
    SUPPORTS_INCREMENTAL = True

    def __init__(self, config: ScraperConfig):
        super().__init__(config)
        self.normalizer = PetfinderNormalizer()
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # ── Token management ────────────────────────────────────────────────────

    async def _ensure_token(self, session: aiohttp.ClientSession) -> str:
        """Return a valid OAuth2 bearer token, refreshing if necessary."""
        now = asyncio.get_event_loop().time()
        if self._token and now < self._token_expires_at - 60:
            return self._token

        api_key = os.getenv("PETFINDER_API_KEY")
        api_secret = os.getenv("PETFINDER_API_SECRET")
        if not api_key or not api_secret:
            raise RuntimeError(
                "PETFINDER_API_KEY and PETFINDER_API_SECRET must be set"
            )

        async with session.post(
            _TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": api_key,
                "client_secret": api_secret,
            },
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            resp.raise_for_status()
            body = await resp.json()
            token: str = body["access_token"]
            self._token = token
            expires_in = body.get("expires_in", 3600)
            self._token_expires_at = now + float(expires_in)
            return self._token

    # ── Scrape ──────────────────────────────────────────────────────────────

    async def scrape(
        self,
        after: datetime | None = None,
    ) -> AsyncIterator[PetRecord]:
        """Yield PetRecords from Petfinder, newest first."""
        headers = {
            "Accept": "application/json",
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            # Fetch all status types
            for status in _SEARCH_STATUSES:
                if self.config.max_pages == 0:
                    continue
                async for record in self._scrape_status(session, status, after):
                    yield record

    async def _scrape_status(
        self,
        session: aiohttp.ClientSession,
        status: str,
        after: datetime | None = None,
    ) -> AsyncIterator[PetRecord]:
        """Fetch one status category (adoptable, lost, found) with pagination."""
        token = await self._ensure_token(session)

        page = 1
        total_pages = 1

        params: dict = {
            "status": status,
            "limit": _PAGE_LIMIT,
            "sort": "recent",
        }

        # Petfinder API doesn't have a direct "after" param for animals,
        # but we can use "before" and "after" date filters on published_at.
        # However, the simplest approach: set a reasonable limit.
        # The API supports location-based search too.
        if self.config.search_lat and self.config.search_lon:
            params["location"] = f"{self.config.search_lat},{self.config.search_lon}"
            params["distance"] = self.config.search_radius_miles

        while page <= total_pages:
            if self.config.max_pages and page > self.config.max_pages:
                break

            params["page"] = page

            try:
                async with session.get(
                    _ANIMALS_URL,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 401:
                        # Token expired, refresh and retry once
                        self._token = None
                        token = await self._ensure_token(session)
                        # Re-issue with fresh token
                        async with session.get(
                            _ANIMALS_URL,
                            params=params,
                            headers={"Authorization": f"Bearer {token}"},
                            timeout=aiohttp.ClientTimeout(total=30),
                        ) as retry_resp:
                            retry_resp.raise_for_status()
                            body = await retry_resp.json()
                    elif resp.status == 404:
                        break  # No more results
                    else:
                        resp.raise_for_status()
                        body = await resp.json()

                pagination = body.get("pagination", {})
                if page == 1:
                    if pagination.get("total_count", 0) == 0:
                        break
                    total_pages = pagination.get("total_pages", 1)

                animals = body.get("animals", [])
                for animal in animals:
                    try:
                        record = self.normalizer.normalize(animal)
                        # Incremental filter: skip if published before `after`
                        if after and record.date_posted and record.date_posted < after:
                            continue
                        self._records_fetched += 1
                        yield record
                    except Exception as exc:
                        self._record_error(exc, f"animal {animal.get('id')}")

                page += 1
                if page <= total_pages:
                    await asyncio.sleep(self.config.rate_limit_seconds)

            except aiohttp.ClientError as exc:
                self._record_error(exc, f"{status} page {page}")
                break

    # ── Active check ────────────────────────────────────────────────────────

    async def check_active(
        self, source_id: str, source_url: str | None = None
    ) -> bool:
        """Check if an animal still exists via the single-animal endpoint."""
        url = f"{_ANIMALS_URL}/{source_id}"
        try:
            headers = {"Accept": "application/json"}
            async with aiohttp.ClientSession(headers=headers) as session:
                token = await self._ensure_token(session)
                async with session.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 404:
                        return False
                    resp.raise_for_status()
                    data = await resp.json()
                    animal = data.get("animal", {})
                    status = animal.get("status", "")
                    # "adopted" and "removed" count as inactive
                    return status.lower() in ("adoptable", "lost", "found")
        except Exception:
            return True  # assume active on network error