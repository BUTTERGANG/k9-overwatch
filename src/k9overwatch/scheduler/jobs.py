"""
Job functions for each scraper source.
Each job: scrape → geocode → upsert → run matching pass.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

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
    scraper_class: type[BaseScraper],
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
        after: datetime | None = None
        if state and state.last_record_at and scraper_class.SUPPORTS_INCREMENTAL:
            # Look back a bit to catch records that arrived late
            after = state.last_record_at - timedelta(hours=2)
            logger.info(f"[{source}] Incremental scrape after {after.isoformat()}")
        else:
            logger.info(f"[{source}] Full scrape")

        highest_date: datetime | None = None

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


async def run_matching_pass(
    new_row_ids: list[str] | None = None,
    *,
    rematch: bool = False,
    rematch_window_days: int = 120,
) -> dict:
    """
    Run deduplication and lost→found matching.

    Modes:
    - Incremental (new_row_ids given, rematch=False): only check the freshly
      ingested records. For each new record we compare it against ALL existing
      candidates in BOTH directions:
        * a new LOST record is compared against existing FOUND records
          (lost→found reunification), and
        * a new FOUND record is compared against existing LOST records
          (found→lost reunification — the reverse direction, so newly arriving
          found reports can surface a match for an already-known lost pet),
      plus dedup in both directions.
    - Full re-match (rematch=True): scan recent active records
      (`get_matchable_records`, optionally bounded by `rematch_window_days`) so
      matches improve as more data arrives (e.g. coordinates filled in by
      geocoding). Idempotent — `save_match` refreshes scores in place.
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
        elif rematch:
            from datetime import date as _date

            since = None
            if rematch_window_days:
                since = _date.today() - timedelta(days=rematch_window_days)
            records_to_check = await repo.get_matchable_records(since_date=since)
        else:
            # Legacy default — only never-matched records. Prefer rematch=True.
            records_to_check = await repo.get_unmatched_records(limit=500)

        for record in records_to_check:
            # Candidates are the same regardless of which side is "new".
            candidates = await repo.find_match_candidates(
                _row_to_fingerprint(record),
                search_radius_miles=15.0,
                date_window_before_days=14,
                date_window_after_days=90,
            )

            # Deduplication (symmetric — direction doesn't matter)
            dedup_results = deduplicator.find_duplicates(record, candidates)
            for result in dedup_results:
                saved = await repo.save_match(result)
                if saved:
                    dedup_found += 1
                    logger.info(
                        f"DEDUP [{result.confidence}] score={result.score:.2f} "
                        f"signals={list(result.signals_fired.keys())}"
                    )

            # Lost→Found matching — run in BOTH directions so newly ingested
            # records of either type can surface a reunification:
            #   * record is LOST  → compare against FOUND/SIGHTING candidates
            #   * record is FOUND → compare against LOST candidates (reverse)
            if record.record_type == "lost":
                lf_results = matcher.find_matches(record, candidates)
            elif record.record_type in ("found", "sighting"):
                lf_results = matcher.find_reverse_matches(record, candidates)
            else:
                lf_results = []

            for result in lf_results:
                saved = await repo.save_match(result)
                if saved:
                    matches_found += 1
                    logger.info(
                        f"LOST→FOUND [{result.confidence}] score={result.score:.2f} "
                        f"signals={list(result.signals_fired.keys())}"
                    )
                    # Notify the owner of the lost pet (user-submitted) if prefs allow.
                    await _maybe_notify(session, record, result, candidates)

    logger.info(f"Matching pass: {dedup_found} dedup, {matches_found} lost→found")
    return {"dedup_found": dedup_found, "matches_found": matches_found}


def _row_to_fingerprint(row) -> PetRecord:
    """Convert a PetRow to a minimal PetRecord for candidate queries."""

    from ..models.pet_record import PetRecord
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
    import os

    from ..scrapers.base import ScraperConfig
    from ..scrapers.http.indy_lost_pet_alert import IndyLostPetAlertScraper

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


async def expire_stale_listings(max_age_days: int = 120) -> dict:
    """
    Source-agnostic fallback so resolved/found pets eventually leave the map.

    The per-source check_active() path (above) only covers IndyLostPetAlert.
    This expires any active listing whose event date is older than `max_age_days`
    and that has no live match — kept independent of a source's own verification.
    """
    async with get_session() as session:
        repo = PetRepository(session)
        count = await repo.deactivate_stale_by_age(max_age_days=max_age_days)
    logger.info(f"Age-based expiry: {count} records deactivated")
    return {"deactivated": count}


async def _maybe_notify(session, record, result, candidates) -> None:
    """If this new match involves a user-submitted lost pet, notify its owner."""
    from sqlalchemy import select

    from k9overwatch.db.models import PetRow as _PetRow
    from k9overwatch.notifications import MatchEvent, notify_new_match

    # Identify the other pet in the pair.
    other_id = result.pet_b_id if result.pet_a_id == str(record.id) else result.pet_b_id
    other = next((c for c in candidates if str(c.id) == other_id), None)
    if other is None:
        stmt = select(_PetRow).where(_PetRow.id == other_id)
        other = (await session.execute(stmt)).scalar_one_or_none()
    if other is None:
        return
    # `record` is the lost side in lost_found matching.
    await notify_new_match(session, MatchEvent(lost_pet=record, other_pet=other, match=result))


async def flush_digest_notifications() -> dict:
    """Scheduler entry point: send the per-day match digest emails."""
    from k9overwatch.notifications import flush_digest

    sent = await flush_digest()
    logger.info(f"Match digest: {sent} email(s) sent")
    return {"sent": sent}
