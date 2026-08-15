"""PetRepository — the single point where PetRecord objects touch persistent storage."""
from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, exists, not_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..matching.breed_normalizer import normalize_breed
from ..models.pet_record import PetRecord
from .models import PetMatch, PetRow, ScraperState, User, UserSession


class PetRepository:
    """Data access layer for pet records."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Upsert ───────────────────────────────────────────────────────────────

    async def upsert(self, record: PetRecord) -> tuple[PetRow, bool]:
        """
        INSERT or UPDATE a pet record.
        Returns (row, created) where created=True means new record.
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
                geocode_source=(
                    str(record.geocode_source) if record.geocode_source else None
                ),
                geocode_confidence=(
                    str(record.geocode_confidence) if record.geocode_confidence else None
                ),
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
            # Only update geo if we have new data
            if record.lat is not None:
                existing.lat = record.lat
                existing.lon = record.lon
                existing.geocode_source = (
                    str(record.geocode_source) if record.geocode_source else None
                )
                existing.geocode_confidence = (
                    str(record.geocode_confidence) if record.geocode_confidence else None
                )
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
            a = (
                math.sin(d_phi / 2) ** 2
                + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
            )
            return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return [r for r in candidates if haversine(r) <= miles]

    async def find_match_candidates(
        self,
        record: PetRecord,
        search_radius_miles: float = 15.0,
        date_window_days: int = 60,
        max_record_age_days: int = 365,
    ) -> list[PetRow]:
        """
        Returns rows that are plausible match candidates for `record`:
        - Opposite or same record_type (for both dedup and lost→found)
        - Same animal_type
        - Within radius (if we have coordinates)
        - Within date window (event-relative, or wall-clock fallback when date_event is None)
        - Scraped within max_record_age_days (hard cap to prevent cross-year matches)
        """
        filters = [PetRow.active == True]

        if record.animal_type:
            filters.append(PetRow.animal_type == str(record.animal_type))

        # Date window: event-relative when available, wall-clock fallback otherwise.
        # When date_event is None we still restrict to recently-scraped records so
        # we never silently match against arbitrarily old data.
        if record.date_event:
            lower = record.date_event - timedelta(days=date_window_days)
            upper = record.date_event + timedelta(days=date_window_days)
            filters.append(PetRow.date_event.between(lower, upper))
        else:
            # No event date — only consider candidates scraped recently
            scraped_cutoff = (
                datetime.now(UTC).replace(tzinfo=None) - timedelta(days=date_window_days)
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

    async def get_stale_records(
        self, source: str, *, older_than_hours: int = 48
    ) -> list[PetRow]:
        """
        Return active records from `source` whose `last_checked_at` is older
        than `older_than_hours` hours (or NULL). Used by the staleness checker
        to verify that records still exist on the source website.
        """
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=older_than_hours)
        stmt = select(PetRow).where(
            and_(
                PetRow.source == source,
                PetRow.active == True,
                or_(
                    PetRow.last_checked_at.is_(None),
                    PetRow.last_checked_at < cutoff,
                ),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_unmatched_records(
        self, source: str | None = None, limit: int = 500
    ) -> list[PetRow]:
        """Records not yet present in pet_matches — candidates for a matching pass."""
        # Use NOT EXISTS correlated subquery — faster than NOT IN for large tables
        # because NOT IN materializes the entire subquery result.
        matched_subq = (
            select(PetMatch.pet_a_id)
            .where(PetMatch.pet_a_id == PetRow.id)
            .union(
                select(PetMatch.pet_b_id).where(PetMatch.pet_b_id == PetRow.id)
            )
        )
        filters = [PetRow.active == True, not_(exists(matched_subq))]
        if source:
            filters.append(PetRow.source == source)
        stmt = select(PetRow).where(and_(*filters)).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

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

    # ── Match storage ─────────────────────────────────────────────────────────

    async def save_match(self, match) -> bool:
        """
        Save a MatchResult. Returns True if a new record was created.
        If a match already exists and the new score is higher (and not yet
        human-reviewed), updates the score, confidence, and signals in place.
        """
        result = await self.session.execute(
            select(PetMatch).where(
                or_(
                    and_(PetMatch.pet_a_id == match.pet_a_id, PetMatch.pet_b_id == match.pet_b_id),
                    and_(PetMatch.pet_a_id == match.pet_b_id, PetMatch.pet_b_id == match.pet_a_id),
                )
            ).where(PetMatch.match_type == match.match_type)
        )
        existing = result.scalar_one_or_none()
        if existing:
            if not existing.reviewed and match.score > existing.score:
                existing.score = match.score
                existing.confidence = match.confidence
                existing.signals_fired = match.signals_fired
                await self.session.flush()
            return False
        row = PetMatch(
            pet_a_id=match.pet_a_id,
            pet_b_id=match.pet_b_id,
            match_type=match.match_type,
            score=match.score,
            confidence=match.confidence,
            signals_fired=match.signals_fired,
        )
        self.session.add(row)
        # Increment the denormalized match_count on both pets so the map
        # endpoint can skip the expensive UNION ALL subquery.
        await self.session.execute(
            update(PetRow)
            .where(PetRow.id.in_([match.pet_a_id, match.pet_b_id]))
            .values(match_count=PetRow.match_count + 1)
        )
        await self.session.flush()
        return True

    async def get_matches_for_pet(self, pet_id: str) -> list[PetMatch]:
        stmt = select(PetMatch).where(
            or_(PetMatch.pet_a_id == pet_id, PetMatch.pet_b_id == pet_id)
        ).order_by(PetMatch.score.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()


class UserRepository:
    """Data access layer for user accounts and sessions."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_user(
        self,
        *,
        email: str,
        display_name: str,
        password_hash: str | None = None,
    ) -> User:
        user = User(email=email, display_name=display_name, password_hash=password_hash)
        self.session.add(user)
        await self.session.flush()
        return user

    async def get_user_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: str) -> User | None:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def create_session(
        self,
        *,
        user_id: str,
        expires_at: datetime,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> UserSession:
        session = UserSession(
            user_id=user_id,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.session.add(session)
        await self.session.flush()
        return session

    async def get_session(self, session_id: str) -> UserSession | None:
        """Return a valid (not revoked, not expired) session."""
        result = await self.session.execute(
            select(UserSession).where(
                UserSession.id == session_id,
                UserSession.revoked == False,
                UserSession.expires_at > datetime.now(UTC).replace(tzinfo=None),
            )
        )
        return result.scalar_one_or_none()

    async def revoke_session(self, session_id: str) -> None:
        await self.session.execute(
            update(UserSession).where(UserSession.id == session_id).values(revoked=True)
        )

    async def update_last_login(self, user_id: str) -> None:
        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(last_login_at=datetime.now(UTC).replace(tzinfo=None))
        )
