"""SQLAlchemy ORM models."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class PetRow(Base):
    """ORM model mapping to the pets table."""
    __tablename__ = "pets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Identity
    source = Column(Text, nullable=False, index=True)
    source_id = Column(Text, nullable=False)
    source_url = Column(Text)
    record_type = Column(Text, nullable=False, index=True)

    # Animal
    animal_type = Column(Text, index=True)
    name = Column(Text)
    breed = Column(Text)
    breed_secondary = Column(Text)
    breed_normalized = Column(Text, index=True)      # canonical breed after normalization
    color_primary = Column(Text)
    color_secondary = Column(Text)
    gender = Column(Text)
    age = Column(Text)
    size = Column(Text)
    size_lbs = Column(Text)  # stored as text in DB; cast to float in application code
    microchipped = Column(Boolean)
    microchip_number = Column(Text)
    distinctive_features = Column(Text)

    # Status & timing
    status = Column(Text)
    date_event = Column(Date, index=True)
    time_event = Column(Text)
    days_since_event = Column(Integer)
    date_posted = Column(DateTime, index=True)
    date_updated = Column(DateTime)
    active = Column(Boolean, default=True, nullable=False, index=True)

    # Location
    location_text = Column(Text)
    neighborhood = Column(Text)
    city = Column(Text)
    county = Column(Text)
    state = Column(String(2), index=True)
    zip = Column(String(10), index=True)
    country = Column(String(2), default="US")
    lat = Column(Float)
    lon = Column(Float)
    geocode_source = Column(Text)
    geocode_confidence = Column(Text)

    # Ownership: links a record to the user who submitted it (source == "user")
    owner_id = Column(String(36), index=True)
    owner_report_status = Column(Text, index=True)
    stale_notified_at = Column(DateTime, default=None)

    # Shelter
    shelter_name = Column(Text)
    shelter_code = Column(Text)
    shelter_id = Column(Text)

    # Contact
    contact_phone = Column(Text)
    contact_email = Column(Text)
    contact_name = Column(Text)
    contact_method = Column(Text)

    # Content
    description = Column(Text)
    owner_message = Column(Text)
    photos = Column(JSON)           # list[str]
    thumbnail_url = Column(Text)

    # Social
    facebook_post_url = Column(Text)
    nextdoor_url = Column(Text)
    alert_number = Column(Text)

    # Audit
    scraped_at = Column(DateTime, default=_now)
    last_checked_at = Column(DateTime, default=_now)
    stale_notified_at = Column(DateTime, nullable=True)  # set when auto-stale warning sent to owner

    # Raw payload
    raw = Column(JSON)

    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_source_record"),
        Index("ix_pets_active_date_event", "active", "date_event"),
        Index("ix_pets_active_type_date", "active", "animal_type", "date_event"),
        Index("ix_pets_active_lat_lon", "active", "lat", "lon"),
        Index("ix_pets_active_date_lat_lon", "active", "date_event", "lat", "lon"),
    )

    def __repr__(self) -> str:
        return f"<PetRow {self.source}/{self.source_id} {self.record_type} {self.animal_type}>"


class PetMatch(Base):
    """Records of likely duplicate or lost→found matches between pets."""
    __tablename__ = "pet_matches"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Both sides of the match (references pets.id, no FK constraint for portability)
    pet_a_id = Column(String(36), nullable=False, index=True)
    pet_b_id = Column(String(36), nullable=False, index=True)

    match_type = Column(Text, nullable=False)       # "dedup" | "lost_found"
    score = Column(Float, nullable=False)           # 0.0–1.0
    confidence = Column(Text, nullable=False)       # "low" | "medium" | "high"
    signals_fired = Column(JSON)                    # dict of signal_name → weight

    created_at = Column(DateTime, default=_now)
    reviewed = Column(Boolean, default=False)       # human-reviewed?
    confirmed = Column(Boolean)                     # human confirmed/rejected?

    __table_args__ = (
        UniqueConstraint("pet_a_id", "pet_b_id", "match_type", name="uq_match_pair"),
        Index("ix_matches_pet_a_type", "pet_a_id", "match_type"),
        Index("ix_matches_pet_b_type", "pet_b_id", "match_type"),
    )


class ScraperState(Base):
    """Tracks the last successful run and high-water mark per scraper source."""
    __tablename__ = "scraper_state"

    source = Column(Text, primary_key=True)
    last_run_at = Column(DateTime)
    last_run_success = Column(Boolean, default=False)
    last_record_at = Column(DateTime)   # highest date_posted seen in last run
    records_fetched = Column(Integer, default=0)
    records_new = Column(Integer, default=0)
    error_message = Column(Text)
    consecutive_errors = Column(Integer, default=0)


class GeocodeCache(Base):
    """Cache of geocoded addresses to avoid redundant API calls."""
    __tablename__ = "geocode_cache"

    address_key = Column(Text, primary_key=True)    # normalized address string
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    geocode_source = Column(Text)
    geocode_confidence = Column(Text)
    cached_at = Column(DateTime, default=_now)
    hit_count = Column(Integer, default=1)


class AccountToken(Base):
    """Hashed, expiring, single-use account action token."""
    __tablename__ = "account_tokens"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), nullable=False, index=True)
    purpose = Column(String(40), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    used_at = Column(DateTime)
    created_at = Column(DateTime, default=_now, nullable=False)

    __table_args__ = (Index("ix_account_tokens_lookup", "user_id", "purpose", "used_at"),)


class EmailQueue(Base):
    """Provider-independent outbound email queue for local/dev delivery adapters."""
    __tablename__ = "email_queue"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), nullable=False, index=True)
    recipient = Column(Text, nullable=False)
    kind = Column(String(40), nullable=False)
    subject = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    sent_at = Column(DateTime)


class User(Base):
    """A person with an account (submits reports, receives match alerts)."""
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(Text, nullable=False, unique=True, index=True)
    display_name = Column(Text)
    # Scrypt-hashed password (modern, no external dep): "scrypt$<params>$<salt>$<hash>"
    password_hash = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_now)
    is_active = Column(Boolean, default=True, nullable=False)
    email_verified = Column(Boolean, default=False, nullable=False)


class NotificationPrefs(Base):
    """Per-user alert preferences. Defaults are low-spam: email digest only."""
    __tablename__ = "notification_prefs"

    user_id = Column(String(36), primary_key=True)

    # Channel + frequency. "off" = no alerts at all.
    # "digest" sends at most one email per day (coalesced). "instant" sends per match.
    email_enabled = Column(Boolean, default=True, nullable=False)
    frequency = Column(Text, default="digest", nullable=False)  # off | digest | instant

    # Only alert on matches at/above this confidence (never "low" by default => no false hope)
    min_confidence = Column(Text, default="medium", nullable=False)  # low | medium | high

    # Also alert when someone submits a FOUND/SIGHTING that may match this user's LOST pet
    notify_on_found_match = Column(Boolean, default=True, nullable=False)

    # Unsubscribe token (opaque) so email footers can disable without login
    unsubscribe_token = Column(Text, nullable=False, unique=True)

    updated_at = Column(DateTime, default=_now)


class SavedSearch(Base):
    """A user's persisted listing criteria for future alerts and quick reuse."""
    __tablename__ = "saved_searches"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    record_type = Column(Text, nullable=False, default="lost")
    animal_type = Column(Text)
    species = Column(Text)
    latitude = Column(Float)
    longitude = Column(Float)
    radius_miles = Column(Integer)
    days = Column(Integer, nullable=False, default=30)
    min_confidence = Column(Text, nullable=False, default="medium")
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    __table_args__ = (Index("ix_saved_searches_user_enabled", "user_id", "enabled"),)


class NotificationQueue(Base):
    """Durable, provider-independent outbound notification queue.

    Serves saved-search alerts, lost↔found match alerts, contact-relay
    notifications, and the coalesced daily digest. Each row is atomically
    claimed by a delivery worker and retried with bounded exponential backoff
    (see claim_notification_queue / mark_notification_failed), so a transient
    mail-provider failure never silently drops the alert.
    """

    __tablename__ = "notification_queue"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), nullable=False, index=True)

    # One of: saved_search | match | contact | digest.
    kind = Column(String(24), nullable=False, default="saved_search", index=True)

    # Saved-search specific (NULL for other kinds).
    saved_search_id = Column(String(36), nullable=True, index=True)
    pet_id = Column(String(36), nullable=True, index=True)

    # Opaque dedupe key so repeated matching passes never re-queue the same
    # alert for the same user + event.
    dedupe_key = Column(String(160), nullable=True, index=True)

    subject = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    confidence = Column(Text)
    status = Column(Text, nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=_now, nullable=False)
    claimed_at = Column(DateTime)
    sent_at = Column(DateTime)
    next_attempt_at = Column(DateTime, index=True)
    last_error = Column(Text)

    __table_args__ = (
        Index("ix_notification_queue_status_created", "status", "created_at"),
    )


class ContactRequest(Base):
    """Private, authenticated relay between a report owner and another user."""
    __tablename__ = "contact_requests"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    pet_id = Column(String(36), nullable=False, index=True)
    requester_id = Column(String(36), nullable=False, index=True)
    recipient_id = Column(String(36), nullable=False, index=True)
    message = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="open")
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    __table_args__ = (
        Index("ix_contact_requests_pair_pet_status", "pet_id", "requester_id", "recipient_id", "status"),
    )


class ContactMessage(Base):
    """Threaded messages inside a contact relay conversation."""
    __tablename__ = "contact_messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    contact_id = Column(String(36), nullable=False, index=True)
    sender_id = Column(String(36), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_now, nullable=False)

    __table_args__ = (
        Index("ix_contact_messages_contact_created", "contact_id", "created_at"),
    )


class ContactBlock(Base):
    """Users can block others to stop contact relay abuse."""
    __tablename__ = "contact_blocks"

    blocker_id = Column(String(36), primary_key=True)
    blocked_id = Column(String(36), primary_key=True)
    created_at = Column(DateTime, default=_now, nullable=False)


class ContentReport(Base):
    """User-flagged content (reports, contact requests) for admin review."""
    __tablename__ = "content_reports"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    reporter_id = Column(String(36), nullable=False, index=True)
    target_type = Column(String(40), nullable=False, index=True)  # "report" | "contact_request"
    target_id = Column(String(36), nullable=False, index=True)
    reason = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)  # pending | reviewed | dismissed
    created_at = Column(DateTime, default=_now, nullable=False)
    reviewed_at = Column(DateTime)
    reviewed_by = Column(String(36))
