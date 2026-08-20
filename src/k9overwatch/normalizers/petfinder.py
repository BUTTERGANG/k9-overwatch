"""Normalizer: Petfinder API v2 animal dict → PetRecord."""
from __future__ import annotations

from datetime import datetime

from ..models.enums import (
    AnimalType,
    Gender,
    RecordType,
    Size,
)
from ..models.pet_record import PetRecord

_ANIMAL_TYPE_MAP: dict[str, AnimalType] = {
    "dog": AnimalType.DOG,
    "cat": AnimalType.CAT,
    "bird": AnimalType.BIRD,
    "rabbit": AnimalType.RABBIT,
    "horse": AnimalType.OTHER,
    "pig": AnimalType.OTHER,
    "smallfurry": AnimalType.OTHER,
    "barnyard": AnimalType.OTHER,
    "scalesfinsother": AnimalType.OTHER,
    "reptile": AnimalType.OTHER,
}

_GENDER_MAP: dict[str, Gender] = {
    "male": Gender.MALE,
    "female": Gender.FEMALE,
    "unknown": Gender.UNKNOWN,
}

_SIZE_MAP: dict[str, Size] = {
    "small": Size.SMALL,
    "medium": Size.MEDIUM,
    "large": Size.LARGE,
    "xlarge": Size.XLARGE,
}

_STATUS_TO_RECORD_TYPE: dict[str, RecordType] = {
    "adoptable": RecordType.ADOPTABLE,
    "adopted": RecordType.ADOPTABLE,
    "lost": RecordType.LOST,
    "found": RecordType.FOUND,
}


def _normalize_animal_type(raw: str | None) -> AnimalType | None:
    if not raw:
        return None
    return _ANIMAL_TYPE_MAP.get(raw.lower().strip(), AnimalType.OTHER)


def _normalize_gender(raw: str | None) -> Gender | None:
    if not raw:
        return None
    return _GENDER_MAP.get(raw.lower().strip())


def _normalize_size(raw: str | None) -> Size | None:
    if not raw:
        return None
    return _SIZE_MAP.get(raw.lower().strip())


def _normalize_record_type(status: str | None, animal_type: str | None) -> RecordType:
    """Petfinder primarily returns adoptable animals, but status can be lost/found."""
    if status:
        result = _STATUS_TO_RECORD_TYPE.get(status.lower().strip())
        if result:
            return result
    return RecordType.ADOPTABLE


def _parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


class PetfinderNormalizer:
    """Convert a Petfinder animal dict to a PetRecord."""

    BASE_URL = "https://www.petfinder.com/animal"

    def normalize(self, animal: dict) -> PetRecord:
        animal_id = str(animal.get("id", ""))
        animal_type_str = animal.get("type")
        status = animal.get("status", "adoptable")

        # Photos
        photos_raw = animal.get("photos") or []
        photo_urls = [p.get("full", "") for p in photos_raw if p.get("full")]
        thumbnail = None
        if photos_raw:
            thumbnail = photos_raw[0].get("small") or photos_raw[0].get("full")

        # Contact
        contact = animal.get("contact") or {}
        breeds = animal.get("breeds") or {}
        colors = animal.get("colors") or {}

        # Location parsing — Petfinder returns "City, ST" or "City, ST ZIP"
        location_text = animal.get("location") or None
        city = None
        state = None
        zip_code = None
        if location_text:
            parts = [p.strip() for p in location_text.split(",")]
            city = parts[0] if len(parts) > 0 else None
            if len(parts) >= 2:
                rest = parts[1]
                # Could be "IN" or "IN 46201"
                rest_parts = rest.split(None, 1)
                state = rest_parts[0] if rest_parts else None
                zip_code = rest_parts[1] if len(rest_parts) > 1 else None

        return PetRecord(
            source="petfinder",
            source_id=animal_id,
            source_url=f"{self.BASE_URL}/{animal_id}" if animal_id else None,
            record_type=_normalize_record_type(status, animal_type_str),
            animal_type=_normalize_animal_type(animal_type_str),
            name=animal.get("name"),
            breed=breeds.get("primary"),
            breed_secondary=breeds.get("secondary"),
            color_primary=colors.get("primary"),
            color_secondary=colors.get("secondary"),
            gender=_normalize_gender(animal.get("gender")),
            size=_normalize_size(animal.get("size")),
            age=animal.get("age"),
            status=status,
            description=animal.get("description"),
            date_posted=_parse_datetime(animal.get("published_at")),
            date_updated=_parse_datetime(animal.get("status_changed_at")),
            location_text=location_text,
            city=city,
            state=state,
            zip=zip_code,
            country="US",
            contact_email=contact.get("email"),
            contact_phone=contact.get("phone"),
            photos=photo_urls,
            thumbnail_url=thumbnail,
            raw=animal,
        )