"""BrowserBaseScraper — Playwright lifecycle management for all browser scrapers."""
from __future__ import annotations

import os
from abc import abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime

from ...models.pet_record import PetRecord
from ..base import BaseScraper


class BrowserBaseScraper(BaseScraper):
    """
    Extends BaseScraper for sources requiring Playwright.
    Manages one browser instance per scrape() call.
    """

    STEALTH_REQUIRED: bool = True   # False for PetFBI (AWS WAF ≠ Cloudflare)
    BROWSER_ARGS: list = []         # Extra chromium launch args (e.g. disable automation flags)

    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )

    async def scrape(self, after: datetime | None = None) -> AsyncIterator[PetRecord]:
        """Wrap _scrape_with_page in browser lifecycle management."""
        try:
            from playwright.async_api import async_playwright
        except ImportError as err:
            raise ImportError(
                "playwright is required for browser scrapers. "
                "Install with: pip install 'k9overwatch[browser]'"
            ) from err

        headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() != "false"

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless, args=self.BROWSER_ARGS)
            context = await browser.new_context(
                user_agent=self.USER_AGENT,
                viewport={"width": 1280, "height": 800},
                locale="en-US",
            )

            if self.STEALTH_REQUIRED:
                await self._apply_stealth(context)

            await self._setup_context(context)
            page = await context.new_page()

            try:
                async for record in self._scrape_with_page(page, after):
                    yield record
            finally:
                await browser.close()

    @abstractmethod
    async def _scrape_with_page(
        self,
        page,
        after: datetime | None,
    ) -> AsyncIterator[PetRecord]:
        """Source-specific scraping logic given an active Playwright Page."""
        ...

    async def _setup_context(self, context) -> None:
        """Hook for subclasses to configure the browser context (init scripts, permissions, etc.)."""
        pass

    @staticmethod
    async def _apply_stealth(context) -> None:
        """Apply anti-fingerprinting patches to the browser context."""
        try:
            from playwright_stealth import Stealth
            await Stealth().apply_stealth_async(context)
        except ImportError:
            pass  # playwright-stealth not installed; proceed without it
