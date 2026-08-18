from datetime import datetime, timedelta

import pytest

from k9overwatch.db.models import ScraperState
from k9overwatch.scheduler.runner import ScraperScheduler
from k9overwatch.scrapers.base import ScraperConfig
from k9overwatch.scrapers.browser.base_browser import BrowserBaseScraper
from k9overwatch.web.routers.admin import scraper_health


class _RetryingBrowserScraper(BrowserBaseScraper):
    SOURCE_NAME = "test-browser"

    def __init__(self, config):
        super().__init__(config)
        self.attempts = 0

    async def _scrape_browser_attempt(self, async_playwright, after):
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("transient chromium failure")
        if False:
            yield None

    async def _scrape_with_page(self, page, after):
        if False:
            yield None

    async def check_active(self, source_id):
        return True


def test_production_scraper_intervals_match_readme_cadence():
    scheduler = ScraperScheduler().build()
    jobs = {job.id: job for job in scheduler.get_jobs()}

    expected = {
        "indy_lost_pet_alert": 15,
        "petconnect24": 30,
        "pawboost": 35,
        "petfbi": 40,
        "lostmydoggie": 45,
    }
    for job_id, minutes in expected.items():
        job = jobs[job_id]
        assert job.trigger.interval == timedelta(minutes=minutes)
        assert job.max_instances == 1
        assert job.coalesce is True

    assert jobs["matching_pass"].trigger.interval == timedelta(minutes=30)
    if scheduler.running:
        scheduler.shutdown(wait=False)


def test_scraper_health_reports_pending_error_and_staleness():
    now = datetime(2026, 8, 18, 12, 0)

    assert scraper_health(ScraperState(source="pawboost"), now=now) == "pending"
    assert scraper_health(
        ScraperState(
            source="pawboost",
            last_run_at=now - timedelta(minutes=1),
            last_run_success=False,
        ),
        now=now,
    ) == "error"
    assert scraper_health(
        ScraperState(
            source="pawboost",
            last_run_at=now - timedelta(minutes=51),
            last_run_success=True,
        ),
        now=now,
    ) == "stale"
    assert scraper_health(
        ScraperState(
            source="pawboost",
            last_run_at=now - timedelta(minutes=40),
            last_run_success=True,
        ),
        now=now,
    ) == "healthy"


@pytest.mark.asyncio
async def test_browser_scraper_retries_transient_session_failure(monkeypatch):
    monkeypatch.setenv("BROWSER_SCRAPE_RETRIES", "1")
    scraper = _RetryingBrowserScraper(
        config=ScraperConfig(search_lat=0, search_lon=0)
    )

    records = [record async for record in scraper.scrape()]

    assert records == []
    assert scraper.attempts == 2
    assert len(scraper._errors) == 1
