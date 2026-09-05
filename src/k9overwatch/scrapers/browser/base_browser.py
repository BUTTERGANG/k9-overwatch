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

    # ── Liveness check (per-source staleness) ────────────────────────────
    # Subclasses set markers that appear on "listing gone" pages and, when the
    # detail URL can be built from the source_id alone, override detail_url().

    NOT_FOUND_MARKERS: tuple[str, ...] = ()
    CHECK_TIMEOUT_MS: int = 20_000

    def detail_url(self, source_id: str) -> str | None:
        """Detail-page URL for a record, or None if not reconstructable."""
        return None

    async def check_active(
        self,
        source_id: str,
        source_url: str | None = None,
    ) -> bool:
        """
        Shared browser-backed liveness check for Playwright sources.

        Loads the listing page and treats it as inactive when the server
        returns 404 or the body contains a not-found marker. Fails OPEN
        (returns True) when the check can't be performed — a bot-protection
        challenge or timeout must never deactivate a possibly-live listing.
        """
        url = source_url or self.detail_url(source_id)
        if not url:
            return True
        try:
            status, text = await self._fetch_page_status_and_text(url)
        except Exception:
            return True
        if status == 404:
            return False
        lowered = (text or "").lower()
        return not any(marker in lowered for marker in self.NOT_FOUND_MARKERS)

    async def _fetch_page_status_and_text(self, url: str) -> tuple[int, str]:
        """Load one page in a throwaway stealth browser; return (status, body text)."""
        from playwright.async_api import async_playwright

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
                page = await context.new_page()
                response = await page.goto(
                    url, wait_until="domcontentloaded", timeout=self.CHECK_TIMEOUT_MS,
                )
                status = response.status if response else 200
                try:
                    text = await page.inner_text("body")
                except Exception:
                    text = await page.content()
                return status, text
            finally:
                await browser.close()

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
