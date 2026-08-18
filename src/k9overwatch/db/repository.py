"""PetRepository — the single point where PetRecord objects touch persistent storage."""
from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..matching.breed_normalizer import normalize_breed
from ..models.pet_record import PetRecord
from .models import NotificationQueue, PetMatch, PetRow, SavedSearch, ScraperState


class PetRepository:
    """Data access layer for pet records."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Upsert ───────────────────────────────────────────────────────────────

    async def upsert(
        self, record: PetRecord, owner_id: str | None = None
    ) -> tuple[PetRow, bool]:
        """
        INSERT or UPDATE a pet record.
        Returns (row, created) where created=True means new record.

        owner_id links a record to the submitting user (source == "user").
        """
        # Check for existing row
        stmt = select(PetRow).where(
            and_(PetRow.source == record.source, PetRow.source_id == record.source_id)
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        now = datetime.now(UTC).replace(tzinfo=None)

        if existing is None:
            row = PetRow(
                source=record.source,
                source_id=record.source_id,
                source_url=record.source_url,
                record_type=str(record.record_type) if record.record_type else None,
                animal_type=str(record.animal_type) if record.animal_type else None,
                name=record.name,
                breed=record.breed,
                breed_secondary=record.breed_secondary,
                breed_normalized=normalize_breed(record.breed),
                color_primary=record.color_primary,
                color_secondary=record.color_secondary,
                gender=str(record.gender) if record.gender else None,
                age=record.age,
                size=str(record.size) if record.size else None,
                size_lbs=record.size_lbs,
                microchipped=record.microchipped,
                microchip_number=record.microchip_number,
                distinctive_features=record.distinctive_features,
                status=record.status,
                date_event=record.date_event,
                time_event=record.time_event,
                days_since_event=record.days_since_event,
                date_posted=record.date_posted,
                date_updated=record.date_updated,
                active=record.active,
                location_text=record.location_text,
                neighborhood=record.neighborhood,
                city=record.city,
                county=record.county,
                state=record.state,
                zip=record.zip,
                country=record.country,
                lat=record.lat,
                lon=record.lon,
                geocode_source=str(record.geocode_source) if record.geocode_source else None,
                geocode_confidence=str(record.geocode_confidence) if record.geocode_confidence else None,
                shelter_name=record.shelter_name,
                shelter_code=record.shelter_code,
                shelter_id=record.shelter_id,
                contact_phone=record.contact_phone,
                contact_email=record.contact_email,
                contact_name=record.contact_name,
                contact_method=record.contact_method,
                description=record.description,
                owner_message=record.owner_message,
                photos=record.photos,
                thumbnail_url=record.thumbnail_url,
                facebook_post_url=record.facebook_post_url,
                nextdoor_url=record.nextdoor_url,
                alert_number=record.alert_number,
                scraped_at=now,
                last_checked_at=now,
                raw=record.raw,
                owner_id=owner_id,
            )
            self.session.add(row)
            await self.session.flush()
            return row, True
        else:
            # Update mutable fields; preserve stable identity fields
            existing.source_url = record.source_url or existing.source_url
            existing.active = record.active
            existing.status = record.status or existing.status
            existing.breed_normalized = normalize_breed(record.breed) or existing.breed_normalized
            existing.date_updated = record.date_updated or existing.date_updated
            existing.days_since_event = record.days_since_event or existing.days_since_event
            existing.description = record.description or existing.description
            existing.photos = record.photos or existing.photos
            existing.thumbnail_url = record.thumbnail_url or existing.thumbnail_url
            existing.last_checked_at = now
            # Preserve ownership: only set owner_id on first creation, never clobber.
            if owner_id and not existing.owner_id:
                existing.owner_id = owner_id
            # Only update geo if we have new data
            if record.lat is not None:
                existing.lat = record.lat
                existing.lon = record.lon
                existing.geocode_source = str(record.geocode_source) if record.geocode_source else None
                existing.geocode_confidence = str(record.geocode_confidence) if record.geocode_confidence else None
            existing.raw = record.raw or existing.raw
            await self.session.flush()
            return existing, False

    async def mark_inactive(self, source: str, source_id: str) -> None:
        """Mark a specific record as no longer active on the source."""
        stmt = (
            update(PetRow)
            .where(and_(PetRow.source == source, PetRow.source_id == source_id))
            .values(active=False, last_checked_at=datetime.now(UTC).replace(tzinfo=None))
        )
        await self.session.execute(stmt)

    async def mark_inactive_bulk(self, source: str, seen_source_ids: set[str]) -> int:
        """
        Mark all records from `source` as inactive if their source_id is NOT
        in `seen_source_ids`. Returns count of records deactivated.
        Used by scrapers that do a full re-fetch (24petconnect).
        """
        stmt = (
            update(PetRow)
            .where(
                and_(
                    PetRow.source == source,
                    PetRow.active == True,
                    PetRow.source_id.not_in(seen_source_ids),
                )
            )
            .values(active=False, last_checked_at=datetime.now(UTC).replace(tzinfo=None))
        )
        result = await self.session.execute(stmt)
        return result.rowcount

    # ── Queries ───────────────────────────────────────────────────────────────

    async def get_by_key(self, source: str, source_id: str) -> PetRow | None:
        stmt = select(PetRow).where(
            and_(PetRow.source == source, PetRow.source_id == source_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_within_radius(
        self,
        lat: float,
        lon: float,
        miles: float,
        record_type: str | None = None,
        animal_type: str | None = None,
        active_only: bool = True,
        days: int | None = None,
    ) -> list[PetRow]:
        """
        Find records within `miles` of (lat, lon).
        Uses Haversine approximation in SQL for SQLite compatibility.
        For production PostGIS, replace with ST_DWithin.
        """
        # Bounding box pre-filter (fast)
        lat_delta = miles / 69.0
        lon_delta = miles / (69.0 * math.cos(math.radians(lat)))

        filters = [
            PetRow.lat.isnot(None),
            PetRow.lat.between(lat - lat_delta, lat + lat_delta),
            PetRow.lon.between(lon - lon_delta, lon + lon_delta),
        ]
        if active_only:
            filters.append(PetRow.active == True)
        if record_type:
            filters.append(PetRow.record_type == record_type)
        if animal_type:
            filters.append(PetRow.animal_type == animal_type)
        if days:
            cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
            filters.append(PetRow.date_event >= cutoff.date())

        stmt = select(PetRow).where(and_(*filters))
        result = await self.session.execute(stmt)
        candidates = result.scalars().all()

        # Haversine distance filter
        def haversine(r: PetRow) -> float:
            if r.lat is None or r.lon is None:
                return float("inf")
            R = 3958.8
            phi1, phi2 = math.radians(lat), math.radians(r.lat)
            d_phi = math.radians(r.lat - lat)
            d_lam = math.radians(r.lon - lon)
            a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
            return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return [r for r in candidates if haversine(r) <= miles]

    async def evaluate_saved_searches(
        self, new_rows: list[PetRow], *, confidence: str | None = None
    ) -> int:
        """Queue one durable alert for each enabled search matching a new row.

        ``confidence`` is optional because a plain listing has no match score. If
        supplied (for example by a matching pipeline), the search threshold is
        enforced before an alert is queued.
        """
        if not new_rows:
            return 0
        searches = list((await self.session.execute(
            select(SavedSearch).where(SavedSearch.enabled == True)
        )).scalars().all())
        users = {
            user.id: user
            for user in (await self.session.execute(select(User).where(
                User.id.in_({s.user_id for s in searches})
            ))).scalars().all()
        } if searches else {}
        rank = {"low": 0, "medium": 1, "high": 2}
        queued = 0
        now = datetime.now(UTC).replace(tzinfo=None)

        def distance(row, search) -> float:
            if row.lat is None or row.lon is None:
                return float("inf")
            phi1, phi2 = math.radians(search.latitude), math.radians(row.lat)
            d_phi = math.radians(row.lat - search.latitude)
            d_lam = math.radians(row.lon - search.longitude)
            a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
            return 3958.8 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        for search in searches:
            if confidence is not None and rank.get(confidence, 0) < rank.get(search.min_confidence, 1):
                continue
            user = users.get(search.user_id)
            if user is None:
                continue
            for row in new_rows:
                if row.record_type != search.record_type:
                    continue
                if search.animal_type and row.animal_type != search.animal_type:
                    continue
                if search.species:
                    wanted = normalize_breed(search.species) or search.species.strip().lower()
                    actual = row.breed_normalized or normalize_breed(row.breed)
                    if not actual or not (wanted == actual or wanted in actual or actual in wanted):
                        continue
                if search.days and (row.date_event is None or row.date_event < (date.today() - timedelta(days=search.days))):
                    continue
                if search.radius_miles is not None:
                    if search.latitude is None or search.longitude is None or distance(row, search) > search.radius_miles:
                        continue
                existing = await self.session.execute(select(NotificationQueue.id).where(
                    NotificationQueue.user_id == search.user_id,
                    NotificationQueue.saved_search_id == search.id,
                    NotificationQueue.pet_id == row.id,
                ))
                if existing.scalar_one_or_none() is not None:
                    continue
                self.session.add(NotificationQueue(
                    user_id=user.id,
                    saved_search_id=search.id,
                    pet_id=row.id,
                    subject=f"New {row.record_type} pet matches {search.name}",
                    body=(f"{row.name or 'A pet'} ({row.breed or 'unknown breed'}) "
                          f"matches your saved search '{search.name}'. "
                          f"View it at /pets/{row.id}"),
                    confidence=confidence,
                    status="pending",
                    created_at=now,
                ))
                queued += 1
        await self.session.flush()
        return queued

    async def claim_notification_queue(
        self, limit: int = 50, now: datetime | None = None
    ) -> list[NotificationQueue]:
        """Atomically claim eligible alerts for one delivery worker."""
        now = now or datetime.now(UTC).replace(tzinfo=None)
        eligible = select(NotificationQueue.id).where(
            NotificationQueue.status.in_(("pending", "failed")),
            or_(NotificationQueue.next_attempt_at.is_(None), NotificationQueue.next_attempt_at <= now),
            NotificationQueue.attempts < 5,
        ).order_by(NotificationQueue.created_at).limit(limit)
        claim = update(NotificationQueue).where(
            NotificationQueue.id.in_(eligible),
            NotificationQueue.status.in_(("pending", "failed")),
            or_(NotificationQueue.next_attempt_at.is_(None), NotificationQueue.next_attempt_at <= now),
            NotificationQueue.attempts < 5,
        ).values(
            status="processing",
            claimed_at=now,
            attempts=NotificationQueue.attempts + 1,
        ).returning(NotificationQueue.id)
        claimed_ids = list((await self.session.execute(claim)).scalars().all())
        if not claimed_ids:
            return []
        rows = list((await self.session.execute(
            select(NotificationQueue).where(NotificationQueue.id.in_(claimed_ids))
            .order_by(NotificationQueue.created_at)
        )).scalars().all())
        return rows

    async def mark_notification_failed(
        self, row: NotificationQueue, error: str, now: datetime | None = None
    ) -> None:
        """Record a delivery failure and schedule bounded exponential retry."""
        now = now or datetime.now(UTC).replace(tzinfo=None)
        row.status = "failed"
        row.last_error = error[:2000]
        row.claimed_at = None
        if row.attempts >= 5:
            row.next_attempt_at = None
        else:
            delay_seconds = min(3600, 60 * (2 ** (row.attempts - 1)))
            row.next_attempt_at = now + timedelta(seconds=delay_seconds)
        await self.session.flush()

    async def find_match_candidates(
        self,
        record: PetRecord,
        search_radius_miles: float = 15.0,
        date_window_before_days: int = 14,
        date_window_after_days: int = 90,
        max_record_age_days: int = 365,
    ) -> list[PetRow]:
        """
        Returns rows that are plausible match candidates for `record`:
        - Opposite or same record_type (for both dedup and lost→found)
        - Same animal_type
        - Within radius (if we have coordinates)
        - Within date window

        The window is asymmetric on purpose: LostFoundMatcher permits a found
        report up to MAX_DAYS_AFTER_LOST (90) days after the lost date and up to
        MAX_DAYS_BEFORE_LOST (3) days before, while dedup pairs are typically
        within ~2 weeks. Using a symmetric ±window smaller than 90 would silently
        exclude valid late found reports, so the after-window is kept wide and the
        matcher's own hard filters enforce the precise constraints.

        When `record.date_event` is missing, candidates are instead restricted to
        those scraped within the after-window, and everything is additionally
        capped at `max_record_age_days` since scrape time so we never silently
        match against arbitrarily old data.
        """
        filters = [PetRow.active == True]

        if record.animal_type:
            filters.append(PetRow.animal_type == str(record.animal_type))

        # Date window (asymmetric to match the matcher's allowed range)
        if record.date_event:
            lower = record.date_event - timedelta(days=date_window_before_days)
            upper = record.date_event + timedelta(days=date_window_after_days)
            filters.append(PetRow.date_event.between(lower, upper))
        else:
            # No event date — only consider candidates scraped recently
            scraped_cutoff = (
                datetime.now(UTC).replace(tzinfo=None) - timedelta(days=date_window_after_days)
            )
            filters.append(PetRow.scraped_at >= scraped_cutoff)

        # Hard cap: never match against records scraped longer ago than max_record_age_days,
        # regardless of how the event date is set.
        age_cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=max_record_age_days)
        filters.append(PetRow.scraped_at >= age_cutoff)

        # Exclude the record itself
        filters.append(
            or_(PetRow.source != record.source, PetRow.source_id != record.source_id)
        )

        stmt = select(PetRow).where(and_(*filters))
        result = await self.session.execute(stmt)
        candidates = result.scalars().all()

        # If we have coordinates, filter by radius
        if record.lat is not None and record.lon is not None:
            def haversine_to_record(r: PetRow) -> float:
                if r.lat is None or r.lon is None:
                    return float("inf")
                R = 3958.8
                phi1, phi2 = math.radians(record.lat), math.radians(r.lat)
                d_phi = math.radians(r.lat - record.lat)
                d_lam = math.radians(r.lon - record.lon)
                a = (math.sin(d_phi / 2) ** 2
                     + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2)
                return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

            # Keep candidates within radius OR candidates with no coordinates (zip-based match)
            candidates = [
                r for r in candidates
                if r.lat is None or haversine_to_record(r) <= search_radius_miles
            ]

        return candidates

    async def get_matchable_records(
        self, limit: int = 1000, since_date: date | None = None
    ) -> list[PetRow]:
        """
        Active records eligible for (re-)matching.

        Unlike `get_unmatched_records`, this does NOT exclude records that already
        participate in a match. Re-matching lets (a) new candidates surface for a
        pet that already had a match and (b) scores refresh as more data arrives
        (e.g. geocoding fills in coordinates → stronger geo signals).

        `since_date` bounds the pool to recent records so the periodic full pass
        stays roughly bounded instead of growing as O(records^2). 120 days covers
        the 90-day lost→found window plus margin.
        """
        filters = [PetRow.active == True]
        if since_date is not None:
            filters.append(PetRow.date_event >= since_date)
        stmt = (
            select(PetRow)
            .where(and_(*filters))
            .order_by(PetRow.date_event.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_records_missing_coordinates(self, limit: int = 100) -> list[PetRow]:
        """
        Active records with address text but no lat/lon yet.

        A record ends up here when geocoding failed at ingestion time (e.g. the
        provider was rate-limited or briefly down) — most commonly a user-submitted
        report, which is only geocoded once, at submit time. Backs the periodic
        `regeocode_pending_records` job so a transient provider failure doesn't
        permanently exclude a listing from the map and from matching.
        """
        filters = [
            PetRow.active == True,
            PetRow.lat.is_(None),
            or_(PetRow.location_text.isnot(None), PetRow.zip.isnot(None)),
        ]
        stmt = (
            select(PetRow)
            .where(and_(*filters))
            .order_by(PetRow.date_posted.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_unmatched_records(
        self, source: str | None = None, limit: int = 500
    ) -> list[PetRow]:
        """Deprecated: records with no match row yet.

        Kept for backward compatibility. Prefer `get_matchable_records` so pets
        that already have a match are still reconsidered when new data arrives.
        """
        matched_ids_stmt = select(PetMatch.pet_a_id).union(select(PetMatch.pet_b_id))
        filters = [PetRow.active == True, PetRow.id.not_in(matched_ids_stmt)]
        if source:
            filters.append(PetRow.source == source)
        stmt = select(PetRow).where(and_(*filters)).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ── Scraper state ─────────────────────────────────────────────────────────

    async def get_scraper_state(self, source: str) -> ScraperState | None:
        stmt = select(ScraperState).where(ScraperState.source == source)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_scraper_state(
        self,
        source: str,
        *,
        success: bool,
        records_fetched: int = 0,
        records_new: int = 0,
        last_record_at: datetime | None = None,
        error_message: str | None = None,
    ) -> None:
        stmt = select(ScraperState).where(ScraperState.source == source)
        result = await self.session.execute(stmt)
        state = result.scalar_one_or_none()

        now = datetime.now(UTC).replace(tzinfo=None)
        if state is None:
            state = ScraperState(source=source)
            self.session.add(state)

        state.last_run_at = now
        state.last_run_success = success
        state.records_fetched = records_fetched
        state.records_new = records_new
        state.error_message = error_message
        if success:
            state.consecutive_errors = 0
        else:
            state.consecutive_errors = (state.consecutive_errors or 0) + 1

        if last_record_at:
            state.last_record_at = last_record_at
        await self.session.flush()

    # ── Staleness ─────────────────────────────────────────────────────────────

    async def get_stale_records(
        self, source: str, older_than_hours: int = 48
    ) -> list[PetRow]:
        """
        Return active records from `source` that have not been re-checked by a
        scrape in the last `older_than_hours`. Used by the staleness job to
        verify (via check_active) whether a listing is still live.

        Falls back to scraped_at when last_checked_at is null.
        """
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=older_than_hours)
        filters = [
            PetRow.source == source,
            PetRow.active == True,
            or_(
                PetRow.last_checked_at.is_(None),
                PetRow.last_checked_at < cutoff,
            ),
        ]
        stmt = select(PetRow).where(and_(*filters)).order_by(PetRow.date_posted.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def deactivate_stale_by_age(
        self, max_age_days: int = 120, exclude_sources: list[str] | None = None
    ) -> int:
        """
        Mark long-expired listings inactive across ALL sources.

        The original staleness check only verified records against IndyLostPetAlert's
        live endpoint; the other four sources had no expiry path, so resolved/found
        pets stayed on the map forever. This is a safe, source-agnostic fallback: any
        active record whose event date is older than `max_age_days` (and which has no
        active match) is deactivated so the map and match pool stay fresh.

        `exclude_sources` lets a source opt out (e.g. if it has its own verification).
        """
        from .models import PetMatch

        cutoff = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=max_age_days)).date()
        filters = [PetRow.active == True, PetRow.date_event < cutoff]
        if exclude_sources:
            filters.append(PetRow.source.not_in(exclude_sources))
        stmt = select(PetRow).where(and_(*filters))
        rows = list((await self.session.execute(stmt)).scalars().all())
        if not rows:
            return 0

        # Don't expire a record that currently has a live (reviewed, un-rejected) match.
        active_match_ids = set()
        match_stmt = select(PetMatch).where(
            PetMatch.pet_a_id.in_([r.id for r in rows])
            | PetMatch.pet_b_id.in_([r.id for r in rows])
        )
        for m in (await self.session.execute(match_stmt)).scalars().all():
            if m.confirmed is not False:
                active_match_ids.add(m.pet_a_id)
                active_match_ids.add(m.pet_b_id)

        count = 0
        for r in rows:
            if r.id in active_match_ids:
                continue
            r.active = False
            r.last_checked_at = datetime.now(UTC).replace(tzinfo=None)
            count += 1
        await self.session.flush()
        return count

    async def save_match(self, match) -> bool:
        """
        Save (or update) a MatchResult.

        Idempotent by (pet_a_id, pet_b_id, match_type): if a row already exists
        for the pair, its score/confidence/signals are refreshed to the latest
        computed values so matches improve as more data arrives. This is what
        makes the periodic re-match pass safe to run repeatedly.

        A row that a human has explicitly REJECTED (`confirmed=False`) is
        preserved and not overwritten, so the pipeline respects human review.
        A human CONFIRMED row (`confirmed=True`) is refreshed but keeps its
        confirmed flag.

        Returns True if a new row was created, False if an existing row was
        updated (or left untouched because it was rejected).
        """

        existing = await self.session.execute(
            select(PetMatch).where(
                or_(
                    and_(PetMatch.pet_a_id == match.pet_a_id, PetMatch.pet_b_id == match.pet_b_id),
                    and_(PetMatch.pet_a_id == match.pet_b_id, PetMatch.pet_b_id == match.pet_a_id),
                )
            ).where(PetMatch.match_type == match.match_type)
        )
        row = existing.scalar_one_or_none()
        if row is None:
            row = PetMatch(
                pet_a_id=match.pet_a_id,
                pet_b_id=match.pet_b_id,
                match_type=match.match_type,
                score=match.score,
                confidence=match.confidence,
                signals_fired=match.signals_fired,
            )
            self.session.add(row)
            await self.session.flush()
            return True

        # Preserve a human rejection — never auto-overwrite a dismissed match.
        if row.confirmed is False:
            return False

        row.score = match.score
        row.confidence = match.confidence
        row.signals_fired = match.signals_fired
        await self.session.flush()
        return False

    async def get_matches_for_pet(self, pet_id: str) -> list[PetMatch]:
        stmt = select(PetMatch).where(
            or_(PetMatch.pet_a_id == pet_id, PetMatch.pet_b_id == pet_id)
        ).order_by(PetMatch.score.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_match_counts(self, pet_ids: list[str]) -> dict[str, int]:
        """Return {pet_id: number_of_matches} for the given pets, in one query."""
        if not pet_ids:
            return {}
        from sqlalchemy import func

        stmt = (
            select(
                PetMatch.pet_a_id,
                func.count().label("n"),
            )
            .where(PetMatch.pet_a_id.in_(pet_ids))
            .group_by(PetMatch.pet_a_id)
        )
        a_counts = {
            row.pet_a_id: row.n
            for row in (await self.session.execute(stmt)).all()
        }
        stmt_b = (
            select(PetMatch.pet_b_id, func.count().label("n"))
            .where(PetMatch.pet_b_id.in_(pet_ids))
            .group_by(PetMatch.pet_b_id)
        )
        b_counts = {
            row.pet_b_id: row.n
            for row in (await self.session.execute(stmt_b)).all()
        }
        return {
            pid: a_counts.get(pid, 0) + b_counts.get(pid, 0) for pid in pet_ids
        }

    # ── Active-listing age buckets ─────────────────────────────────────────────

    async def get_active_age_buckets(
        self, record_type: str | None = None
    ) -> dict[str, int]:
        """
        Count active records grouped by how long ago the event happened:
        'week' (≤7d), 'fortnight' (8–14d), 'month' (15–30d), 'older' (>30d).

        Robust to missing dates: effective age falls back
        date_event → days_since_event(+scrape age) → scrape age, so a listing
        with no parsed date still lands in a sensible bucket instead of vanishing.
        """
        filters = [PetRow.active == True]  # noqa: E712 — SQLAlchemy needs ==
        if record_type:
            filters.append(PetRow.record_type == record_type)
        stmt = select(
            PetRow.date_event, PetRow.days_since_event, PetRow.scraped_at
        ).where(and_(*filters))
        result = await self.session.execute(stmt)

        counts: dict[str, int] = dict.fromkeys(AGE_BUCKETS, 0)
        for date_event, days_since_event, scraped_at in result.all():
            counts[age_bucket(effective_age_days(date_event, days_since_event, scraped_at))] += 1
        return counts


# ── Age-bucket helpers (module-level: reused by API + tests) ────────────────────

AGE_BUCKETS = ("week", "fortnight", "month", "older")

# Human-friendly labels for the UI — plain language for non-technical users.
AGE_BUCKET_LABELS = {
    "week": "Within the last week",
    "fortnight": "1–2 weeks ago",
    "month": "2 weeks – 1 month ago",
    "older": "More than a month ago",
}


def effective_age_days(
    date_event: date | None,
    days_since_event: int | None,
    scraped_at: datetime | None,
) -> int:
    """Best-estimate age in days, tolerant of missing fields."""
    today = datetime.now(UTC).date()
    if date_event is not None:
        return max(0, (today - date_event).days)
    scrape_age = 0
    if scraped_at is not None:
        sd = scraped_at.date() if isinstance(scraped_at, datetime) else scraped_at
        scrape_age = max(0, (today - sd).days)
    if days_since_event is not None:
        return max(0, days_since_event) + scrape_age
    return scrape_age


def age_bucket(days: int) -> str:
    """Map an age in days to a bucket key."""
    if days <= 7:
        return "week"
    if days <= 14:
        return "fortnight"
    if days <= 30:
        return "month"
    return "older"


# ── User accounts & notification prefs ──────────────────────────────────────────

from .models import NotificationPrefs, User  # noqa: E402  (imported late to avoid cycle)


class UserRepository:
    """User accounts, registration, and notification preferences."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.strip().lower())
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, user_id: str) -> User | None:
        stmt = select(User).where(User.id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(self, email: str, password: str, display_name: str | None = None) -> User:
        from k9overwatch.web.auth import hash_password, new_unsubscribe_token

        user = User(
            email=email.strip().lower(),
            display_name=display_name or email.split("@")[0],
            password_hash=hash_password(password),
        )
        self.session.add(user)
        await self.session.flush()
        # Create default (low-spam) notification prefs alongside the user.
        self.session.add(
            NotificationPrefs(user_id=user.id, unsubscribe_token=new_unsubscribe_token())
        )
        await self.session.flush()
        return user

    async def get_prefs(self, user_id: str) -> NotificationPrefs | None:
        stmt = select(NotificationPrefs).where(NotificationPrefs.user_id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def save_prefs(self, user_id: str, **fields) -> NotificationPrefs:
        prefs = await self.get_prefs(user_id)
        if prefs is None:
            from k9overwatch.web.auth import new_unsubscribe_token

            prefs = NotificationPrefs(
                user_id=user_id, unsubscribe_token=new_unsubscribe_token()
            )
            self.session.add(prefs)
        for key, value in fields.items():
            if hasattr(prefs, key):
                setattr(prefs, key, value)
        await self.session.flush()
        return prefs
