"""Normalizer: PetFBI GraphQL report dict → PetRecord."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

from ..models.enums import (
    AnimalType, Gender, GeocodeConfidence, GeocodeSource, RecordType,
)
from ..models.pet_record import PetRecord


def _parse_date(date_str: Optional[str]) -> Optional[date]:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(date_str[:10], fmt[:10]).date()
        except ValueError:
            continue
    return None


_SPECIES_MAP = {
    # Integer codes returned by the GraphQL API
    1: AnimalType.CAT,
    2: AnimalType.DOG,
    3: AnimalType.BIRD,
    4: AnimalType.RABBIT,
    # String labels (legacy / schema flexibility)
    "dog": AnimalType.DOG, "canine": AnimalType.DOG,
    "cat": AnimalType.CAT, "feline": AnimalType.CAT,
    "bird": AnimalType.BIRD, "avian": AnimalType.BIRD,
    "rabbit": AnimalType.RABBIT,
}

_REPORT_TYPE_MAP = {
    # Integer codes returned by the GraphQL API
    1: RecordType.LOST,
    2: RecordType.FOUND,
    3: RecordType.SIGHTING,
    # String labels
    "lost": RecordType.LOST,
    "found": RecordType.FOUND,
    "sighting": RecordType.SIGHTING,
}


def _normalize_animal_type(species) -> Optional[AnimalType]:
    if species is None:
        return None
    key = species if isinstance(species, int) else str(species).lower().strip()
    return _SPECIES_MAP.get(key, AnimalType.OTHER)


def _normalize_gender(gender: Optional[str]) -> Optional[Gender]:
    if not gender:
        return None
    g = str(gender).lower().strip()
    if g in ("male", "m", "1"):
        return Gender.MALE
    if g in ("female", "f", "2"):
        return Gender.FEMALE
    return Gender.UNKNOWN


def _normalize_record_type(report_type) -> RecordType:
    if report_type is None:
        return RecordType.LOST
    key = report_type if isinstance(report_type, int) else str(report_type).lower().strip()
    return _REPORT_TYPE_MAP.get(key, RecordType.LOST)


class PetFBINormalizer:
    """Convert a PetFBI GraphQL report dict to a PetRecord."""

    BASE_URL = "https://petfbi.org/report"

    def normalize(self, report: dict) -> PetRecord:
        report_id = str(report.get("report_id", ""))

        lat = report.get("geo_latitude")
        lon = report.get("geo_longitude")
        has_coords = lat is not None and lon is not None

        # Build description from available text fields
        desc_parts = []
        if report.get("comments"):
            desc_parts.append(report["comments"])
        if report.get("location_comments"):
            desc_parts.append(f"Location: {report['location_comments']}")
        if report.get("collar"):
            desc_parts.append(f"Collar: {report['collar']}")
        if report.get("markings"):
            desc_parts.append(f"Markings: {report['markings']}")
        description = " | ".join(desc_parts) if desc_parts else None

        # Photos: picture_file is a URL or relative path
        photo_url = report.get("picture_file")
        if photo_url and not photo_url.startswith("http"):
            photo_url = f"https://petfbi.org{photo_url}"

        return PetRecord(
            source="petfbi",
            source_id=report_id,
            source_url=f"{self.BASE_URL}/{report_id}" if report_id else None,
            record_type=_normalize_record_type(report.get("report_type")),
            animal_type=_normalize_animal_type(report.get("species")),
            name=report.get("animal_name"),
            breed=report.get("breedlabel1"),
            breed_secondary=report.get("breedlabel2"),
            color_primary=report.get("colorlabel1"),
            color_secondary=report.get("colorlabel2"),
            gender=_normalize_gender(report.get("gender")),
            age=report.get("age"),
            distinctive_features=report.get("markings"),
            status=str(report["status"]) if report.get("status") is not None else None,
            date_event=_parse_date(report.get("event_date")),
            date_updated=datetime.fromisoformat(report["last_updated"]) if report.get("last_updated") else None,
            location_text=report.get("location_comments"),
            country="US",
            lat=float(lat) if lat is not None else None,
            lon=float(lon) if lon is not None else None,
            geocode_source=GeocodeSource.PETFBI_NATIVE if has_coords else None,
            geocode_confidence=GeocodeConfidence.HIGH if has_coords else None,
            contact_email=report.get("public_email"),
            contact_name=report.get("contact_name"),
            description=description,
            photos=[photo_url] if photo_url else [],
            thumbnail_url=photo_url,
            raw=report,
        )
