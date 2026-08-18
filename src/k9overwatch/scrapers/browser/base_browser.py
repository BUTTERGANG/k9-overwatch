"""BrowserBaseScraper — Playwright lifecycle management for all browser scrapers."""
from __future__ import annotations

import os
import shutil
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
        """Wrap the browser lifecycle and retry a failed browser session once.

        A fresh Playwright process/context is used for each retry.  This recovers
        from transient Chromium crashes and expired bot-protection sessions while
        preserving the original exception when all attempts fail.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError as err:
            raise ImportError(
                "playwright is required for browser scrapers. "
                "Install with: pip install 'k9overwatch[browser]'"
            ) from err

        retries = max(0, int(os.getenv("BROWSER_SCRAPE_RETRIES", "1")))
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                async for record in self._scrape_browser_attempt(async_playwright, after):
                    yield record
                return
            except Exception as exc:
                last_error = exc
                self._record_error(exc, f"browser session attempt {attempt + 1}")
                if attempt < retries:
                    continue
        assert last_error is not None
        raise last_error

    async def _scrape_browser_attempt(self, async_playwright, after: datetime | None):
        """Run one isolated browser session; callers decide whether to retry."""
        headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() != "false"
        chromium_path = (
            os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
            or shutil.which("chromium")
            or shutil.which("chromium-browser")
            or None
        )
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless, args=self.BROWSER_ARGS,
                executable_path=chromium_path,
            )
            context = await browser.new_context(
                user_agent=self.USER_AGENT,
                viewport={"width": 1280, "height": 800}, locale="en-US",
            )
            try:
                if self.STEALTH_REQUIRED:
                    await self._apply_stealth(context)
                await self._setup_context(context)
                page = await context.new_page()
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
        """Hook for subclasses to configure the browser context (init scripts, permissions)."""
        pass

    @staticmethod
    async def _apply_stealth(context) -> None:
        """Apply anti-fingerprinting patches to the browser context."""
        try:
            from playwright_stealth import Stealth
            await Stealth().apply_stealth_async(context)
        except ImportError:
            pass  # playwright-stealth not installed; proceed without it
