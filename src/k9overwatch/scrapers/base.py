"""Abstract base class for all K9-Overwatch scrapers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator, Optional

from ..models.pet_record import PetRecord


class StructuralChangeError(Exception):
    """Raised when a scraper fails to find critical DOM elements, indicating a site layout change."""
    pass


@dataclass
class ScraperConfig:
    """Runtime configuration injected into every scraper."""
    search_lat: float
    search_lon: float
    search_radius_miles: int = 25
    lookback_hours: int = 48           # for incremental polling
    max_pages: Optional[int] = None    # None = fetch all pages
    rate_limit_seconds: float = 1.5    # minimum delay between page requests
    extra: dict = field(default_factory=dict)  # source-specific overrides


class BaseScraper(ABC):
    """
    Abstract base class for all K9-Overwatch scrapers.

    Each scraper:
    1. Fetches raw data from its source
    2. Yields normalized PetRecord objects via scrape()
    3. Respects rate limits
    4. Supports check_active() for staleness verification

    Scrapers do NOT write to the database — that is the job runner's responsibility.
    """

    SOURCE_NAME: str              # class-level constant, e.g. "indylostpetalert"
    SUPPORTS_INCREMENTAL: bool = True   # False if source can't filter by date

    def __init__(self, config: ScraperConfig):
        self.config = config
        self._records_fetched: int = 0
        self._records_new: int = 0
        self._errors: list[Exception] = []

    @abstractmethod
    async def scrape(
        self,
        after: Optional[datetime] = None,
    ) -> AsyncIterator[PetRecord]:
        """
        Yield normalized PetRecord objects.
        `after` enables incremental polling — only records newer than this datetime.
        Must be an async generator (use `yield` or `yield from`).
        """
        ...

    @abstractmethod
    async def check_active(self, source_id: str) -> bool:
        """
        Verify a specific record is still active on the source.
        Returns False if the listing is gone, reunited, or removed.
        """
        ...

    def _record_error(self, exc: Exception, context: str = "") -> None:
        self._errors.append(exc)

    @property
    def stats(self) -> dict:
        return {
            "source": self.SOURCE_NAME,
            "records_fetched": self._records_fetched,
            "error_count": len(self._errors),
        }
