from __future__ import annotations

from datetime import UTC, date, datetime

from pydantic import BaseModel, Field

from .enums import (
    AnimalType,
    Gender,
    GeocodeConfidence,
    GeocodeSource,
    RecordType,
    Size,
)


class PetRecord(BaseModel):
    """
    Canonical in-memory representation of a pet listing.
    All scrapers produce this; the DB layer consumes it.
    """

    # ── Identity ────────────────────────────────────────────────────────────
    source: str                         # e.g. "indylostpetalert"
    source_id: str                      # unique ID within the source
    source_url: str | None = None    # link back to original listing
    record_type: RecordType

    # ── Animal characteristics ───────────────────────────────────────────────
    animal_type: AnimalType | None = None
    name: str | None = None
    breed: str | None = None
    breed_secondary: str | None = None
    color_primary: str | None = None
    color_secondary: str | None = None
    gender: Gender | None = None
    age: str | None = None
    size: Size | None = None
    size_lbs: str | None = None
    microchipped: bool | None = None
    microchip_number: str | None = None
    distinctive_features: str | None = None

    # ── Status & timing ──────────────────────────────────────────────────────
    status: str | None = None
    date_event: date | None = None       # date lost/found/seen
    time_event: str | None = None
    days_since_event: int | None = None
    date_posted: datetime | None = None  # when posted to source
    date_updated: datetime | None = None
    active: bool = True

    # ── Location ─────────────────────────────────────────────────────────────
    location_text: str | None = None     # raw address as given
    neighborhood: str | None = None
    city: str | None = None
    county: str | None = None
    state: str | None = None             # 2-letter code
    zip: str | None = None
    country: str = "US"
    lat: float | None = None
    lon: float | None = None
    geocode_source: GeocodeSource | None = None
    geocode_confidence: GeocodeConfidence | None = None

    # ── Shelter ───────────────────────────────────────────────────────────────
    shelter_name: str | None = None
    shelter_code: str | None = None
    shelter_id: str | None = None

    # ── Contact ───────────────────────────────────────────────────────────────
    contact_phone: str | None = None
    contact_email: str | None = None
    contact_name: str | None = None
    contact_method: str | None = None

    # ── Content ───────────────────────────────────────────────────────────────
    description: str | None = None
    owner_message: str | None = None
    photos: list[str] = Field(default_factory=list)
    thumbnail_url: str | None = None

    # ── Social / cross-references ─────────────────────────────────────────────
    facebook_post_url: str | None = None
    nextdoor_url: str | None = None
    alert_number: str | None = None

    # ── Audit ─────────────────────────────────────────────────────────────────
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # ── Raw source payload (stored for re-parsing) ────────────────────────────
    raw: dict | None = None

    model_config = {"use_enum_values": True}

    @property
    def unique_key(self) -> tuple[str, str]:
        return (self.source, self.source_id)

    def needs_geocoding(self) -> bool:
        """True if the record has address text but no coordinates yet."""
        return self.lat is None and bool(self.location_text or self.zip)

    def geocoding_address(self) -> str | None:
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
