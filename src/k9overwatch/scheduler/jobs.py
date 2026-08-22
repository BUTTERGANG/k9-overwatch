"""
Job functions for each scraper source.
Each job: scrape → geocode → upsert → run matching pass.
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta

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
    saved_alerts = 0
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
        # Track every source_id returned by this scrape run for staleness sweep
        seen_source_ids: set[str] = set()

        try:
            async for record in scraper.scrape(after=after):
                records_fetched += 1
                seen_source_ids.add(record.source_id)
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

                        # ── Cross-source dedup check ─────────────────────
                        # For newly created records, check if the same pet
                        # exists from another source and link them.
                        duplicates = await repo.find_cross_source_duplicates(record, row)
                        for dup_row, dup_score in duplicates:
                            linked = await repo.link_duplicates(row, dup_row, dup_score)
                            if linked:
                                logger.info(
                                    f"CROSS-SOURCE DEDUP [{source}/{record.source_id}] "
                                    f"→ [{dup_row.source}/{dup_row.source_id}] "
                                    f"score={dup_score:.2f}"
                                )

                except Exception as exc:
                    errors += 1
                    logger.error(f"[{source}] Error processing record {record.source_id}: {exc}")

        except Exception as exc:
            logger.error(f"[{source}] Scraper failed: {exc}")
            await repo.update_scraper_state(
                source, success=False, error_message=str(exc)
            )
            # Re-fetch state to check consecutive errors and fire webhook if needed
            state = await repo.get_scraper_state(source)
            if state and state.consecutive_errors >= 3:
                from ..utils.alerts import send_scraper_alert
                await send_scraper_alert(
                    source=source,
                    consecutive_errors=state.consecutive_errors,
                    error_message=str(exc),
                )
            raise

        # Staleness sweep: for full scrapes (no date filter), any record from this
        # source that was NOT returned by the scraper is gone from the source site.
        # This catches deactivated/reunited listings for browser-based scrapers that
        # don't expose a single-record lookup endpoint.
        records_deactivated = 0
        if after is None and seen_source_ids:
            records_deactivated = await repo.mark_inactive_bulk(source, seen_source_ids)
            if records_deactivated:
                logger.info(
                    f"[{source}] Staleness sweep: {records_deactivated} records deactivated"
                )

        # Update scraper state
        await repo.update_scraper_state(
            source,
            success=True,
            records_fetched=records_fetched,
            records_new=records_new,
            last_record_at=highest_date,
        )
        saved_alerts = await repo.evaluate_saved_searches(new_rows)

        logger.info(
            f"[{source}] Done: {records_fetched} fetched, {records_new} new, "
            f"{errors} errors, {records_deactivated} deactivated"
        )

    # Run matching on newly ingested records
    if run_matching and new_rows:
        await run_matching_pass(new_row_ids=[row.id for row in new_rows])

    return {
        "source": source,
        "records_fetched": records_fetched,
        "records_new": records_new,
        "errors": errors,
        "saved_alerts": saved_alerts,
    }


async def run_saved_search_alerts(new_row_ids: list[str]) -> int:
    """Evaluate enabled saved searches for a set of newly ingested rows."""
    from sqlalchemy import select

    from ..db.models import PetRow

    async with get_session() as session:
        rows = list((await session.execute(
            select(PetRow).where(PetRow.id.in_(new_row_ids))
        )).scalars().all())
        return await PetRepository(session).evaluate_saved_searches(rows)


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
                max_record_age_days=365,
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


def build_staleness_scrapers(config) -> dict:
    """
    One scraper instance per source that supports per-record liveness checks.

    Every source now implements check_active(): the HTTP sources re-fetch
    their record endpoints, the browser scrapers load the listing page in a
    throwaway stealth browser (see BrowserBaseScraper.check_active).
    """
    from ..scrapers.browser.lostmydoggie import LostMyDoggieScraper
    from ..scrapers.browser.pawboost import PawBoostScraper
    from ..scrapers.browser.petfbi import PetFBIScraper
    from ..scrapers.http.indy_lost_pet_alert import IndyLostPetAlertScraper
    from ..scrapers.http.petconnect24 import PetConnect24Scraper

    return {
        IndyLostPetAlertScraper.SOURCE_NAME: IndyLostPetAlertScraper(config),
        PetConnect24Scraper.SOURCE_NAME: PetConnect24Scraper(config),
        PawBoostScraper.SOURCE_NAME: PawBoostScraper(config),
        PetFBIScraper.SOURCE_NAME: PetFBIScraper(config),
        LostMyDoggieScraper.SOURCE_NAME: LostMyDoggieScraper(config),
    }


async def check_stale_records(stale_hours: int = 48) -> dict:
    """
    For every source, verify records that haven't been seen recently via the
    source's own check_active() and mark them inactive if they're gone.
    Checks fail open — a scraper error never deactivates a record; the
    source-agnostic expire_stale_listings job remains the backstop.
    """
    import os

    from ..scrapers.base import ScraperConfig

    config = ScraperConfig(
        search_lat=float(os.getenv("SEARCH_LAT", "39.7684")),
        search_lon=float(os.getenv("SEARCH_LON", "-86.1581")),
    )
    scrapers = build_staleness_scrapers(config)
    per_source: dict[str, int] = {}
    total_deactivated = 0

    async with get_session() as session:
        repo = PetRepository(session)
        for source, scraper in scrapers.items():
            deactivated = 0
            for row in await repo.get_stale_records(source, older_than_hours=stale_hours):
                is_active = await scraper.check_active(row.source_id, source_url=row.source_url)
                if not is_active:
                    await repo.mark_inactive(source, row.source_id)
                    deactivated += 1
            per_source[source] = deactivated
            total_deactivated += deactivated

    logger.info(f"Staleness check: {total_deactivated} records deactivated {per_source}")
    return {"deactivated": total_deactivated, "per_source": per_source}


async def regeocode_pending_records(limit: int = 100) -> dict:
    """
    Retry geocoding for active records that still have no lat/lon.

    Scraped records self-heal: a failed geocode is retried on the source's next
    full scrape (`needs_geocoding()` stays true until lat is set). User-submitted
    reports have no such retry — `reports.submit_report` geocodes once, so a
    transient Nominatim failure (rate limit, timeout) leaves the report
    permanently off the map and unmatchable. This is the source-agnostic backstop.
    """
    regeocoded_ids: list[str] = []

    async with get_session() as session:
        repo = PetRepository(session)
        geocoder = _make_geocoder_from_env(session)
        rows = await repo.get_records_missing_coordinates(limit=limit)

        for row in rows:
            record = PetRecord(
                source=row.source,
                source_id=row.source_id,
                record_type=row.record_type,
                animal_type=row.animal_type,
                location_text=row.location_text,
                city=row.city,
                state=row.state,
                zip=row.zip,
                country=row.country or "US",
            )
            result_record = await geocoder.geocode(record)
            if result_record.lat is not None:
                row.lat = result_record.lat
                row.lon = result_record.lon
                row.geocode_source = result_record.geocode_source
                row.geocode_confidence = result_record.geocode_confidence
                regeocoded_ids.append(row.id)

        await session.commit()

    logger.info(f"Re-geocode sweep: {len(regeocoded_ids)}/{len(rows)} filled in")

    # Newly-coordinated records can now surface geo-matches — run them through
    # matching immediately rather than waiting for the next full rematch pass.
    if regeocoded_ids:
        await run_matching_pass(new_row_ids=regeocoded_ids)

    return {"checked": limit, "regeocoded": len(regeocoded_ids)}


async def expire_stale_listings(max_age_days: int = 120, stale_notify_hours: int = 48) -> dict:
    """
    Source-agnostic fallback so resolved/found pets eventually leave the map.

    The per-source check_active() path (above) only covers IndyLostPetAlert.
    This expires any active listing whose event date is older than `max_age_days`
    and that has no live match — kept independent of a source's own verification.

    For user-submitted reports, a two-pass approach is used:
    1. First pass: set `stale_notified_at` to mark that an alert was sent.
    2. Second pass (already notified, still stale): deactivate the report.
    Non-user reports are deactivated immediately as before.
    """
    from datetime import timedelta

    from sqlalchemy import or_, select

    from ..db.models import PetMatch, PetRow

    cutoff = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=max_age_days)).date()
    notified_cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=stale_notify_hours)

    async with get_session() as session:
        repo = PetRepository(session)
        count = 0

        # ── Non-user records: deactivate immediately as before. ──────────────
        stmt = select(PetRow).where(
            PetRow.active == True,
            PetRow.date_event < cutoff,
            PetRow.source != "user",
        )
        rows = list((await session.execute(stmt)).scalars().all())
        if rows:
            # Don't expire records with a live (unrejected) match.
            active_match_ids = set()
            match_stmt = select(PetMatch).where(
                PetMatch.pet_a_id.in_([r.id for r in rows])
                | PetMatch.pet_b_id.in_([r.id for r in rows])
            )
            for m in (await session.execute(match_stmt)).scalars().all():
                if m.confirmed is not False:
                    active_match_ids.add(m.pet_a_id)
                    active_match_ids.add(m.pet_b_id)

            for r in rows:
                if r.id in active_match_ids:
                    continue
                r.active = False
                r.last_checked_at = datetime.now(UTC).replace(tzinfo=None)
                count += 1

        # ── User-submitted records: two-pass approach. ───────────────────────
        user_stmt = select(PetRow).where(
            PetRow.active == True,
            PetRow.date_event < cutoff,
            PetRow.source == "user",
        )
        user_rows = list((await session.execute(user_stmt)).scalars().all())
        if user_rows:
            # Build active-match set for user rows too
            active_user_match_ids = set()
            user_match_stmt = select(PetMatch).where(
                PetMatch.pet_a_id.in_([r.id for r in user_rows])
                | PetMatch.pet_b_id.in_([r.id for r in user_rows])
            )
            for m in (await session.execute(user_match_stmt)).scalars().all():
                if m.confirmed is not False:
                    active_user_match_ids.add(m.pet_a_id)
                    active_user_match_ids.add(m.pet_b_id)

            for r in user_rows:
                if r.id in active_user_match_ids:
                    continue
                if r.stale_notified_at is None:
                    # First pass: flag as notified but don't deactivate yet.
                    r.stale_notified_at = datetime.now(UTC).replace(tzinfo=None)
                elif r.stale_notified_at < notified_cutoff:
                    # Second pass: enough time has passed since notification.
                    r.active = False
                    r.last_checked_at = datetime.now(UTC).replace(tzinfo=None)
                    count += 1

        await session.flush()
    logger.info(f"Age-based expiry: {count} records deactivated")
    return {"deactivated": count}


async def _maybe_notify(session, record, result, candidates) -> None:
    """If this new match involves a user-submitted lost pet, notify its owner."""
    from sqlalchemy import select

    from k9overwatch.db.models import PetRow as _PetRow
    from k9overwatch.notifications import MatchEvent, notify_new_match

    # Identify the other pet in the pair, regardless of match orientation.
    current_is_a = result.pet_a_id == str(record.id)
    other_id = result.pet_b_id if current_is_a else result.pet_a_id
    other = next((c for c in candidates if str(c.id) == other_id), None)
    if other is None:
        stmt = select(_PetRow).where(_PetRow.id == other_id)
        other = (await session.execute(stmt)).scalar_one_or_none()
    if other is None:
        return
    # Matching runs in both directions. Always notify the LOST side's owner,
    # rather than assuming the newly ingested record is the lost record.
    if record.record_type == "lost":
        lost_pet, other_pet = record, other
    elif other.record_type == "lost":
        lost_pet, other_pet = other, record
    else:
        return
    await notify_new_match(
        session, MatchEvent(lost_pet=lost_pet, other_pet=other_pet, match=result)
    )


async def flush_digest_notifications() -> dict:
    """Scheduler entry point: send the per-day match digest emails."""
    from k9overwatch.notifications import flush_digest

    sent = await flush_digest()
    logger.info(f"Match digest: {sent} email(s) sent")
    return {"sent": sent}


async def flush_saved_search_notifications() -> dict:
    """Scheduler entry point for durable saved-search notification delivery."""
    from k9overwatch.notifications import flush_notification_queue

    async with get_session() as session:
        sent = await flush_notification_queue(session)
    logger.info(f"Saved-search notifications: {sent} email(s) sent")
    return {"sent": sent}
