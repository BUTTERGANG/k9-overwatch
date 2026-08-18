from datetime import datetime, timedelta

import pytest

from k9overwatch.db.models import ScraperState
from k9overwatch.scheduler.runner import SchedulerSingletonLock, ScraperScheduler
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


@pytest.mark.asyncio
async def test_sqlite_scheduler_lock_is_exclusive(tmp_path, monkeypatch):
    lock_path = tmp_path / "scheduler.lock"
    monkeypatch.setenv("SCHEDULER_LOCK_FILE", str(lock_path))
    first = SchedulerSingletonLock("sqlite+aiosqlite:///test.db")
    second = SchedulerSingletonLock("sqlite+aiosqlite:///test.db")

    assert await first.acquire() is True
    assert await second.acquire() is False

    await first.release()
    assert await second.acquire() is True
    await second.release()


@pytest.mark.asyncio
async def test_postgres_scheduler_lock_uses_try_advisory_lock():
    class FakeResult:
        def scalar_one(self):
            return True

    class FakeConnection:
        def __init__(self):
            self.statements = []

        async def execute(self, statement, params=None):
            self.statements.append((str(statement), params))
            return FakeResult()

        async def close(self):
            pass

    class FakeConnect:
        def __init__(self, connection):
            self.connection = connection

        async def __aenter__(self):
            return self.connection

        async def __aexit__(self, *args):
            pass

    class FakeEngine:
        def __init__(self, connection):
            self.connection = connection

        def connect(self):
            return FakeConnect(self.connection)

    connection = FakeConnection()
    lock = SchedulerSingletonLock("postgresql+asyncpg://db", engine=FakeEngine(connection))

    assert await lock.acquire() is True
    await lock.release()
    assert "pg_try_advisory_lock" in connection.statements[0][0]
    assert "pg_advisory_unlock" in connection.statements[1][0]
