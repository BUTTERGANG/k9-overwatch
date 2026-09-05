"""Tests for per-source staleness/inactive checking beyond IndyLostPetAlert.

Covers:
  - BrowserBaseScraper.check_active() shared Playwright-backed liveness check
    (status-code + not-found-marker heuristics, fail-open on errors).
  - Real browser scrapers (pawboost, petfbi, lostmydoggie) build the right
    detail URL / markers for their source.
  - jobs.check_stale_records() runs against ALL sources, not just
    indylostpetalert, and deactivates records whose check fails.
"""
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from k9overwatch.db.repository import PetRepository
from k9overwatch.models.enums import AnimalType, RecordType
from k9overwatch.models.pet_record import PetRecord
from k9overwatch.scheduler import jobs
from k9overwatch.scrapers.base import ScraperConfig
from k9overwatch.scrapers.browser.base_browser import BrowserBaseScraper
from k9overwatch.scrapers.browser.lostmydoggie import LostMyDoggieScraper
from k9overwatch.scrapers.browser.pawboost import PawBoostScraper
from k9overwatch.scrapers.browser.petfbi import PetFBIScraper

CONFIG = ScraperConfig(search_lat=39.7684, search_lon=-86.1581)


class _FakePageFetcher(BrowserBaseScraper):
    """Browser scraper whose network fetch is replaced with canned results."""

    SOURCE_NAME = "fake-browser"
    NOT_FOUND_MARKERS = ("page not found", "no longer available")

    def __init__(self, config, result=(200, "A happy dog")):
        super().__init__(config)
        self.result = result
        self.error: Exception | None = None
        self.requested_urls: list[str] = []

    async def _scrape_with_page(self, page, after):
        if False:
            yield None

    def detail_url(self, source_id):
        return f"https://example.com/listing/{source_id}"

    async def _fetch_page_status_and_text(self, url):
        self.requested_urls.append(url)
        if self.error:
            raise self.error
        return self.result


# ── BrowserBaseScraper.check_active heuristics ───────────────────────────────


@pytest.mark.asyncio
async def test_check_active_false_on_404_status():
    scraper = _FakePageFetcher(CONFIG, result=(404, "anything"))
    assert await scraper.check_active("123") is False


@pytest.mark.asyncio
async def test_check_active_false_on_not_found_marker_text():
    scraper = _FakePageFetcher(CONFIG, result=(200, "Sorry, this Page Not Found"))
    assert await scraper.check_active("123") is False


@pytest.mark.asyncio
async def test_check_active_true_on_healthy_page():
    scraper = _FakePageFetcher(CONFIG, result=(200, "Lost Male Dog — Indianapolis"))
    assert await scraper.check_active("123") is True


@pytest.mark.asyncio
async def test_check_active_fails_open_on_fetch_error():
    scraper = _FakePageFetcher(CONFIG)
    scraper.error = RuntimeError("cloudflare challenge")
    assert await scraper.check_active("123") is True


@pytest.mark.asyncio
async def test_check_active_prefers_source_url_over_detail_url():
    scraper = _FakePageFetcher(CONFIG)
    await scraper.check_active("123", source_url="https://example.com/landing/pet/slug-123/")
    assert scraper.requested_urls == ["https://example.com/landing/pet/slug-123/"]


@pytest.mark.asyncio
async def test_check_active_true_when_no_url_available():
    # PawBoost can't build a detail URL from the id alone; without a stored
    # source_url there is nothing to check, so it must fail open.
    scraper = PawBoostScraper(CONFIG)

    async def _fail(self, url):  # pragma: no cover — must never be reached
        raise AssertionError("should not fetch without a URL")

    with patch.object(PawBoostScraper, "_fetch_page_status_and_text", _fail):
        assert await scraper.check_active("123") is True


# ── Per-source URL construction ──────────────────────────────────────────────


def test_pawboost_has_no_reconstructable_detail_url():
    # PawBoost detail URLs embed a slug; only the stored source_url works.
    assert PawBoostScraper(CONFIG).detail_url("123") is None


def test_petfbi_detail_url_uses_report_page():
    assert PetFBIScraper(CONFIG).detail_url("4711") == "https://petfbi.org/report/4711"


def test_lostmydoggie_detail_url_uses_details_cfm():
    url = LostMyDoggieScraper(CONFIG).detail_url("473213")
    assert url == "https://www.lostmydoggie.com/details.cfm?petid=473213"


@pytest.mark.parametrize(
    ("scraper_cls", "source_id", "source_url"),
    [
        (PawBoostScraper, "999", "https://www.pawboost.com/landing/pet/abc-slug-46201/"),
        (PetFBIScraper, "4711", None),
        (LostMyDoggieScraper, "473213", None),
    ],
)
@pytest.mark.asyncio
async def test_real_browser_scrapers_check_liveness_via_page(scraper_cls, source_id, source_url):
    scraper = scraper_cls(CONFIG)

    async def _fake_fetch(self, url):
        return (200, "page not found")

    with patch.object(type(scraper), "_fetch_page_status_and_text", _fake_fetch):
        assert await scraper.check_active(source_id, source_url=source_url) is False


# ── jobs.check_stale_records covers all sources ──────────────────────────────


def _record(source: str, source_id: str) -> PetRecord:
    return PetRecord(
        source=source,
        source_id=source_id,
        record_type=RecordType.LOST,
        animal_type=AnimalType.DOG,
        name=f"Pet {source_id}",
        location_text="Indianapolis, IN",
        city="Indianapolis",
        state="IN",
        zip="46201",
        country="US",
    )


class _StubScraper:
    def __init__(self, active_ids, source):
        self.active_ids = active_ids
        self.source = source
        self.checked: list[str] = []

    async def check_active(self, source_id, source_url=None):
        self.checked.append(source_id)
        return source_id in self.active_ids


@pytest.mark.asyncio
async def test_check_stale_records_runs_against_all_sources(db_session, monkeypatch):
    repo = PetRepository(db_session)
    now = datetime.now(UTC).replace(tzinfo=None)
    # Two stale pawboost rows and one stale petfbi row.
    await repo.upsert(_record("pawboost", "PB-1"))
    await repo.upsert(_record("pawboost", "PB-2"))
    await repo.upsert(_record("petfbi", "PF-1"))
    from sqlalchemy import select

    from k9overwatch.db.models import PetRow

    rows = list((await db_session.execute(select(PetRow))).scalars().all())
    for row in rows:
        row.last_checked_at = now - timedelta(hours=72)
    await db_session.commit()

    stubs = {
        "pawboost": _StubScraper(active_ids={"PB-2"}, source="pawboost"),   # PB-1 dies
        "petfbi": _StubScraper(active_ids=set(), source="petfbi"),          # PF-1 dies
    }

    def fake_get_session():
        @asynccontextmanager
        async def _cm():
            yield db_session
        return _cm()

    monkeypatch.setattr(jobs, "get_session", fake_get_session)
    monkeypatch.setattr(jobs, "build_staleness_scrapers", lambda config: stubs)

    result = await jobs.check_stale_records(stale_hours=48)

    assert stubs["pawboost"].checked == ["PB-1", "PB-2"]
    assert stubs["petfbi"].checked == ["PF-1"]
    assert result["deactivated"] == 2
    assert result["per_source"] == {"pawboost": 1, "petfbi": 1}

    remaining = {r.source_id: r.active for r in (await db_session.execute(select(PetRow))).scalars().all()}
    assert remaining == {"PB-1": False, "PB-2": True, "PF-1": False}


def test_build_staleness_scrapers_includes_all_five_sources():
    scrapers = jobs.build_staleness_scrapers(CONFIG)
    assert set(scrapers) == {
        "indylostpetalert",
        "24petconnect",
        "pawboost",
        "petfbi",
        "lostmydoggie",
    }
