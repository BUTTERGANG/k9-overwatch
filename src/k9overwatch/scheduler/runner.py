"""
ScraperScheduler — APScheduler-based polling loop for all data sources.

Usage:
    python -m k9overwatch.scheduler.runner
"""
from __future__ import annotations

import asyncio
import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from ..db.connection import init_db
from ..scrapers.base import ScraperConfig
from .jobs import (
    check_stale_records,
    expire_stale_listings,
    flush_digest_notifications,
    run_matching_pass,
    run_scraper,
)

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


class ScraperScheduler:

    def build(self) -> AsyncIOScheduler:
        from ..scrapers.browser.lostmydoggie import LostMyDoggieScraper
        from ..scrapers.browser.pawboost import PawBoostScraper
        from ..scrapers.browser.petfbi import PetFBIScraper
        from ..scrapers.http.indy_lost_pet_alert import IndyLostPetAlertScraper
        from ..scrapers.http.petconnect24 import PetConnect24Scraper

        scheduler = AsyncIOScheduler(timezone="UTC")
        cfg = _config()

        # ── Phase 1: HTTP scrapers (fast, cheap) ──────────────────────────────
        scheduler.add_job(
            run_scraper,
            "interval", minutes=15,
            id="indy_lost_pet_alert",
            args=[IndyLostPetAlertScraper, cfg],
            kwargs={"run_matching": True},
            max_instances=1,
            coalesce=True,
        )
        scheduler.add_job(
            run_scraper,
            "interval", minutes=30,
            id="petconnect24",
            args=[PetConnect24Scraper, cfg],
            kwargs={"run_matching": False},  # matching runs in its own job
            max_instances=1,
            coalesce=True,
        )

        # ── Phase 2: Browser scrapers (Playwright — use longer intervals) ─────
        scheduler.add_job(
            run_scraper,
            "interval", minutes=35,
            id="pawboost",
            args=[PawBoostScraper, cfg],
            kwargs={"run_matching": False},
            max_instances=1,
            coalesce=True,
        )
        scheduler.add_job(
            run_scraper,
            "interval", minutes=40,
            id="petfbi",
            args=[PetFBIScraper, cfg],
            kwargs={"run_matching": False},
            max_instances=1,
            coalesce=True,
        )
        scheduler.add_job(
            run_scraper,
            "interval", minutes=45,
            id="lostmydoggie",
            args=[LostMyDoggieScraper, cfg],
            kwargs={"run_matching": False},
            max_instances=1,
            coalesce=True,
        )

        # ── Matching pass — runs after all scrapers have had a chance to run ──
        scheduler.add_job(
            run_matching_pass,
            "interval", minutes=30,
            id="matching_pass",
            max_instances=1,
            coalesce=True,
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
            "interval", hours=6,
            id="staleness_check",
            max_instances=1,
            coalesce=True,
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

        return scheduler


async def main():
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    logger.info("Initializing database...")
    await init_db()

    scheduler = ScraperScheduler().build()

    logger.info("Starting scheduler...")
    scheduler.start()

    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
