from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from .enums import (
    AnimalType, Gender, GeocodeConfidence, GeocodeSource, RecordType, Size,
)


class PetRecord(BaseModel):
    """
    Canonical in-memory representation of a pet listing.
    All scrapers produce this; the DB layer consumes it.
    """

    # ── Identity ────────────────────────────────────────────────────────────
    source: str                         # e.g. "indylostpetalert"
    source_id: str                      # unique ID within the source
    source_url: Optional[str] = None    # link back to original listing
    record_type: RecordType

    # ── Animal characteristics ───────────────────────────────────────────────
    animal_type: Optional[AnimalType] = None
    name: Optional[str] = None
    breed: Optional[str] = None
    breed_secondary: Optional[str] = None
    color_primary: Optional[str] = None
    color_secondary: Optional[str] = None
    gender: Optional[Gender] = None
    age: Optional[str] = None
    size: Optional[Size] = None
    size_lbs: Optional[str] = None
    microchipped: Optional[bool] = None
    microchip_number: Optional[str] = None
    distinctive_features: Optional[str] = None

    # ── Status & timing ──────────────────────────────────────────────────────
    status: Optional[str] = None
    date_event: Optional[date] = None       # date lost/found/seen
    time_event: Optional[str] = None
    days_since_event: Optional[int] = None
    date_posted: Optional[datetime] = None  # when posted to source
    date_updated: Optional[datetime] = None
    active: bool = True

    # ── Location ─────────────────────────────────────────────────────────────
    location_text: Optional[str] = None     # raw address as given
    neighborhood: Optional[str] = None
    city: Optional[str] = None
    county: Optional[str] = None
    state: Optional[str] = None             # 2-letter code
    zip: Optional[str] = None
    country: str = "US"
    lat: Optional[float] = None
    lon: Optional[float] = None
    geocode_source: Optional[GeocodeSource] = None
    geocode_confidence: Optional[GeocodeConfidence] = None

    # ── Shelter ───────────────────────────────────────────────────────────────
    shelter_name: Optional[str] = None
    shelter_code: Optional[str] = None
    shelter_id: Optional[str] = None

    # ── Contact ───────────────────────────────────────────────────────────────
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    contact_name: Optional[str] = None
    contact_method: Optional[str] = None

    # ── Content ───────────────────────────────────────────────────────────────
    description: Optional[str] = None
    owner_message: Optional[str] = None
    photos: list[str] = Field(default_factory=list)
    thumbnail_url: Optional[str] = None

    # ── Social / cross-references ─────────────────────────────────────────────
    facebook_post_url: Optional[str] = None
    nextdoor_url: Optional[str] = None
    alert_number: Optional[str] = None

    # ── Audit ─────────────────────────────────────────────────────────────────
    scraped_at: datetime = Field(default_factory=datetime.utcnow)
    last_checked_at: datetime = Field(default_factory=datetime.utcnow)

    # ── Raw source payload (stored for re-parsing) ────────────────────────────
    raw: Optional[dict] = None

    model_config = {"use_enum_values": True}

    @property
    def unique_key(self) -> tuple[str, str]:
        return (self.source, self.source_id)

    def needs_geocoding(self) -> bool:
        """True if the record has address text but no coordinates yet."""
        return self.lat is None and bool(self.location_text or self.zip)

    def geocoding_address(self) -> Optional[str]:
        """Best address string to pass to a geocoder."""
        if self.location_text:
            parts = [self.location_text]
            if self.state and self.state not in self.location_text:
                parts.append(self.state)
            if self.country == "US" and "US" not in self.location_text:
                parts.append("USA")
            return ", ".join(parts)
        if self.zip:
            return self.zip
        return None

    def to_match_fingerprint(self) -> dict:
        """
        Compact dict of matching-relevant fields.
        Used by the matching engine to avoid full record comparisons.
        """
        return {
            "source": self.source,
            "source_id": self.source_id,
            "record_type": self.record_type,
            "animal_type": self.animal_type,
            "breed": self.breed,
            "breed_secondary": self.breed_secondary,
            "color_primary": self.color_primary,
            "color_secondary": self.color_secondary,
            "gender": self.gender,
            "size": self.size,
            "name": self.name,
            "date_event": self.date_event,
            "lat": self.lat,
            "lon": self.lon,
            "zip": self.zip,
            "city": self.city,
            "description": self.description,
            "microchip_number": self.microchip_number,
        }
