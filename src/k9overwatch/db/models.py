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

    # Matching performance cache — incremented by save_match()
    match_count = Column(Integer, default=0, nullable=False, server_default="0")

    # User-submitted listing fields
    user_id = Column(String(36))          # FK → users.id (no constraint for portability)
    user_submitted = Column(Boolean, default=False)
    moderation_status = Column(Text, default="approved")  # pending|approved|rejected|flagged
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime)
    resolved_reason = Column(Text)         # reunited|found_deceased|other|cancelled

    # Audit
    scraped_at = Column(DateTime, default=_now)
    last_checked_at = Column(DateTime, default=_now)

    # Raw payload
    raw = Column(JSON)

    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_source_record"),
        Index("ix_pets_active_date_event", "active", "date_event"),
        Index("ix_pets_active_type_date", "active", "animal_type", "date_event"),
        Index("ix_pets_active_lat_lon", "active", "lat", "lon"),
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


class User(Base):
    """Registered user accounts."""
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(Text, nullable=False, unique=True)
    email_verified = Column(Boolean, default=False)
    password_hash = Column(Text)              # None for OAuth-only accounts
    display_name = Column(Text, nullable=False)
    phone = Column(Text)
    phone_verified = Column(Boolean, default=False)

    # Role & status
    role = Column(Text, default="user")       # "user" | "moderator" | "admin"
    active = Column(Boolean, default=True)
    banned = Column(Boolean, default=False)
    ban_reason = Column(Text)

    # Profile
    city = Column(Text)
    state = Column(String(2))
    zip = Column(String(10))

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=_now)
    last_login_at = Column(DateTime)
    updated_at = Column(DateTime)

    __table_args__ = (
        Index("ix_users_email", "email"),
    )

    def __repr__(self) -> str:
        return f"<User {self.email} role={self.role}>"


class UserSession(Base):
    """Server-side session tokens for authenticated users."""
    __tablename__ = "user_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), nullable=False, index=True)  # → users.id
    ip_address = Column(Text)
    user_agent = Column(Text)
    created_at = Column(DateTime, nullable=False, default=_now)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False)
