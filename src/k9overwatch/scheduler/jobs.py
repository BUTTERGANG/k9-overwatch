"""
Job functions for each scraper source.
Each job: scrape → geocode → upsert → run matching pass.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Type

from ..db.connection import get_session
from ..db.repository import PetRepository
from ..geocoding.geocoder import GeocodingService
from ..geocoding.providers.nominatim import NominatimProvider
from ..matching.deduplicator import Deduplicator
from ..matching.lost_found_matcher import LostFoundMatcher
from ..models.pet_record import PetRecord
from ..scrapers.base import BaseScraper, ScraperConfig

logger = logging.getLogger(__name__)


def _make_geocoder_from_env(session) -> GeocodingService:
    """Build a GeocodingService using env-configured providers."""
    provider = os.getenv("GEOCODE_PROVIDER", "nominatim")
    providers = []
    if provider == "google":
        from ..geocoding.providers.google import GoogleMapsProvider
        providers.append(GoogleMapsProvider())
    # Always include Nominatim as fallback
    providers.append(NominatimProvider())
    return GeocodingService(session, providers)


async def run_scraper(
    scraper_class: Type[BaseScraper],
    config: ScraperConfig,
    *,
    run_matching: bool = True,
) -> dict:
    """
    Generic pipeline for any scraper:
    1. Load high-water mark from DB
    2. Scrape (incremental if supported)
    3. Geocode each record
    4. Upsert to DB
    5. Run deduplication + lost→found matching on new records
    6. Update scraper state
    """
    source = scraper_class.SOURCE_NAME
    records_fetched = 0
    records_new = 0
    errors = 0
    new_rows = []

    async with get_session() as session:
        repo = PetRepository(session)
        geocoder = _make_geocoder_from_env(session)
        scraper = scraper_class(config)

        # Get high-water mark for incremental polling
        state = await repo.get_scraper_state(source)
        after: Optional[datetime] = None
        if state and state.last_record_at and scraper_class.SUPPORTS_INCREMENTAL:
            # Look back a bit to catch records that arrived late
            after = state.last_record_at - timedelta(hours=2)
            logger.info(f"[{source}] Incremental scrape after {after.isoformat()}")
        else:
            logger.info(f"[{source}] Full scrape")

        highest_date: Optional[datetime] = None

        try:
            async for record in scraper.scrape(after=after):
                records_fetched += 1
                try:
                    # Geocode if needed (skips PetFBI which provides native coords)
                    if record.needs_geocoding():
                        record = await geocoder.geocode(record)

                    # Track highest date seen for next high-water mark
                    if record.date_posted:
                        if highest_date is None or record.date_posted > highest_date:
                            highest_date = record.date_posted

                    row, created = await repo.upsert(record)
                    if created:
                        records_new += 1
                        new_rows.append(row)

                except Exception as exc:
                    errors += 1
                    logger.error(f"[{source}] Error processing record {record.source_id}: {exc}")

        except Exception as exc:
            logger.error(f"[{source}] Scraper failed: {exc}")
            await repo.update_scraper_state(
                source, success=False, error_message=str(exc)
            )
            # Re-fetch state to check consecutive errors
            state = await repo.get_scraper_state(source)
            if state and state.consecutive_errors >= 3:
                logger.critical(
                    f"[{source}] ALERT: Scraper has failed {state.consecutive_errors} "
                    f"times in a row! Target website structure may have changed. "
                    f"Error: {exc}"
                )
            raise

        # Update scraper state
        await repo.update_scraper_state(
            source,
            success=True,
            records_fetched=records_fetched,
            records_new=records_new,
            last_record_at=highest_date,
        )

        logger.info(
            f"[{source}] Done: {records_fetched} fetched, {records_new} new, {errors} errors"
        )

    # Run matching on newly ingested records
    if run_matching and new_rows:
        await run_matching_pass(new_row_ids=[row.id for row in new_rows])

    return {
        "source": source,
        "records_fetched": records_fetched,
        "records_new": records_new,
        "errors": errors,
    }


async def run_matching_pass(new_row_ids: Optional[list[str]] = None) -> dict:
    """
    Run deduplication and lost→found matching.
    If new_row_ids is provided, only check those records against existing records.
    Otherwise, runs a full pass on unmatched active records.
    """
    dedup_found = 0
    matches_found = 0
    deduplicator = Deduplicator()
    matcher = LostFoundMatcher()

    async with get_session() as session:
        repo = PetRepository(session)

        # Get records to process
        if new_row_ids:
            from sqlalchemy import select
            from ..db.models import PetRow
            result = await session.execute(
                select(PetRow).where(PetRow.id.in_(new_row_ids))
            )
            records_to_check = result.scalars().all()
        else:
            records_to_check = await repo.get_unmatched_records(limit=500)

        for record in records_to_check:
            # Find candidates for both dedup and lost→found
            candidates = await repo.find_match_candidates(
                _row_to_fingerprint(record),
                search_radius_miles=15.0,
                date_window_days=60,
            )

            # Deduplication
            dedup_results = deduplicator.find_duplicates(record, candidates)
            for result in dedup_results:
                saved = await repo.save_match(result)
                if saved:
                    dedup_found += 1
                    logger.info(
                        f"DEDUP [{result.confidence}] score={result.score:.2f} "
                        f"signals={list(result.signals_fired.keys())}"
                    )

            # Lost→Found matching
            if record.record_type == "lost":
                lf_results = matcher.find_matches(record, candidates)
                for result in lf_results:
                    saved = await repo.save_match(result)
                    if saved:
                        matches_found += 1
                        logger.info(
                            f"LOST→FOUND [{result.confidence}] score={result.score:.2f} "
                            f"signals={list(result.signals_fired.keys())}"
                        )

    logger.info(f"Matching pass: {dedup_found} dedup, {matches_found} lost→found")
    return {"dedup_found": dedup_found, "matches_found": matches_found}


def _row_to_fingerprint(row) -> "PetRecord":
    """Convert a PetRow to a minimal PetRecord for candidate queries."""
    from ..models.pet_record import PetRecord
    from ..models.enums import RecordType, AnimalType
    from datetime import date as date_type
    return PetRecord(
        source=row.source,
        source_id=row.source_id,
        record_type=row.record_type,
        animal_type=row.animal_type,
        breed=row.breed,
        color_primary=row.color_primary,
        gender=row.gender,
        date_event=row.date_event,
        lat=row.lat,
        lon=row.lon,
        zip=row.zip,
        city=row.city,
        description=row.description,
        microchip_number=row.microchip_number,
    )


async def check_stale_records(stale_hours: int = 48) -> dict:
    """
    For sources that support check_active(), verify records that haven't been
    seen recently and mark them inactive if they're gone.
    Only runs against IndyLostPetAlert (has direct WP REST endpoint).
    """
    from ..scrapers.http.indy_lost_pet_alert import IndyLostPetAlertScraper
    from ..scrapers.base import ScraperConfig
    import os

    config = ScraperConfig(
        search_lat=float(os.getenv("SEARCH_LAT", "39.7684")),
        search_lon=float(os.getenv("SEARCH_LON", "-86.1581")),
    )
    scraper = IndyLostPetAlertScraper(config)
    deactivated = 0

    async with get_session() as session:
        repo = PetRepository(session)
        stale = await repo.get_stale_records("indylostpetalert", older_than_hours=stale_hours)
        for row in stale:
            is_active = await scraper.check_active(row.source_id)
            if not is_active:
                await repo.mark_inactive("indylostpetalert", row.source_id)
                deactivated += 1

    logger.info(f"Staleness check: {deactivated} records deactivated")
    return {"deactivated": deactivated}
