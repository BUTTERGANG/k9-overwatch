"""
ScraperScheduler — APScheduler-based polling loop for all data sources.

Usage:
    python -m k9overwatch.scheduler.runner
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from ..db.connection import init_db
from ..scrapers.base import ScraperConfig
from .jobs import (
    check_stale_records,
    expire_stale_listings,
    flush_digest_notifications,
    flush_saved_search_notifications,
    regeocode_pending_records,
    run_matching_pass,
    run_scraper,
)
from .lock import SchedulerSingletonLock

load_dotenv()
logger = logging.getLogger(__name__)

def _config() -> ScraperConfig:
    return ScraperConfig(
        search_lat=float(os.getenv("SEARCH_LAT", "39.7684")),
        search_lon=float(os.getenv("SEARCH_LON", "-86.1581")),
        search_radius_miles=int(os.getenv("SEARCH_RADIUS_MILES", "25")),
        rate_limit_seconds=float(os.getenv("HTTP_RATE_LIMIT_SECONDS", "1.5")),
        extra={"zip_code": os.getenv("SEARCH_ZIP", "46201")},
    )


def build_scraper_jobs() -> list[tuple[str, type, int, int]]:
    """Return the scraper job specs to register."""
    from ..scrapers.browser.lostmydoggie import LostMyDoggieScraper
    from ..scrapers.browser.pawboost import PawBoostScraper
    from ..scrapers.browser.petfbi import PetFBIScraper
    from ..scrapers.http.indy_lost_pet_alert import IndyLostPetAlertScraper
    from ..scrapers.http.petconnect24 import PetConnect24Scraper

    jobs: list[tuple[str, type, int, int]] = [
        ("indy_lost_pet_alert", IndyLostPetAlertScraper, 15, 0),
        ("petconnect24", PetConnect24Scraper, 30, 1),
        ("pawboost", PawBoostScraper, 35, 4),
        ("petfbi", PetFBIScraper, 40, 7),
        ("lostmydoggie", LostMyDoggieScraper, 45, 10),
    ]
    return jobs


class ScraperScheduler:

    def build(self) -> AsyncIOScheduler:
        scheduler = AsyncIOScheduler(timezone="UTC")
        cfg = _config()
        now = datetime.now(UTC)

        # Production cadence is defined per source in README: 15–45 minutes.
        # Use interval triggers (rather than the old twice-daily cron) so a
        # missed web-process tick is coalesced without silently creating a
        # 12-hour freshness gap.  Initial runs remain staggered at startup.
        scraper_jobs = build_scraper_jobs()
        for job_id, scraper_class, interval_minutes, startup_offset in scraper_jobs:
            scheduler.add_job(
                run_scraper,
                "interval",
                minutes=interval_minutes,
                id=job_id,
                args=[scraper_class, cfg],
                kwargs={"run_matching": True},
                max_instances=1,
                coalesce=True,
                next_run_time=now + timedelta(minutes=startup_offset),
            )

        # Matching runs every 30 minutes, after startup scraper offsets have
        # completed.  It is intentionally independent of scraper intervals.
        scheduler.add_job(
            run_matching_pass,
            "interval", minutes=30,
            id="matching_pass",
            max_instances=1,
            coalesce=True,
            next_run_time=now + timedelta(minutes=20),
        )

        # ── Full re-match — refreshes scores / surfaces late candidates ───────
        # Idempotent: save_match upserts in place (unless a human rejected it).
        # Bounded to the last 120 days so it stays roughly O(records^2)-bounded.
        scheduler.add_job(
            run_matching_pass,
            "cron", hour=4, minute=0,
            id="rematch_pass",
            kwargs={"rematch": True, "rematch_window_days": 120},
            max_instances=1,
            coalesce=True,
        )

        # ── Staleness check — marks old records inactive ───────────────────────
        scheduler.add_job(
            check_stale_records,
            "cron", hour="6,18", minute="0",
            id="staleness_check",
            max_instances=1,
            coalesce=True,
        )

        # ── Re-geocode backstop — retries records left without coordinates by a
        #    transient provider failure (mainly user reports, geocoded only once
        #    at submit time). Scraped records self-heal on the source's next scrape. ──
        scheduler.add_job(
            regeocode_pending_records,
            "interval", minutes=20,
            id="regeocode_pending_records",
            kwargs={"limit": 100},
            max_instances=1,
            coalesce=True,
            next_run_time=now + timedelta(minutes=5),
        )

        # ── Age-based expiry — source-agnostic fallback so resolved/found pets
        #    eventually leave the map (the per-source check only covers Indy). ──
        scheduler.add_job(
            expire_stale_listings,
            "interval", hours=24,
            id="expire_stale_listings",
            kwargs={"max_age_days": 120},
            max_instances=1,
            coalesce=True,
        )

        # ── Match digest — coalesced daily email (respects per-user prefs) ────
        scheduler.add_job(
            flush_digest_notifications,
            "cron", hour=19, minute=0,
            id="match_digest",
            max_instances=1,
            coalesce=True,
        )

        # ── Saved-search queue — frequent delivery with durable retries ──────
        scheduler.add_job(
            flush_saved_search_notifications,
            "interval", minutes=5,
            id="saved_search_notifications",
            max_instances=1,
            coalesce=True,
        )

        return scheduler


async def main():
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    logger.info("Initializing database...")
    await init_db()

    lock = SchedulerSingletonLock()
    if not await lock.acquire():
        logger.error("Another scheduler instance already holds the singleton lock")
        return

    scheduler = ScraperScheduler().build()
    logger.info("Starting scheduler...")
    scheduler.start()

    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
    finally:
        scheduler.shutdown()
        await lock.release()


if __name__ == "__main__":
    asyncio.run(main())
