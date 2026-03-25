"""Normalizer: PawBoost card data dict → PetRecord."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

from ..models.enums import AnimalType, Gender, RecordType
from ..models.pet_record import PetRecord


def _parse_date_text(text: Optional[str]) -> Optional[date]:
    if not text:
        return None
    for fmt in ("%B %d, %Y", "%B %d %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_city_state_zip(location_str: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse 'City, ST 12345' into (city, state, zip)."""
    if not location_str:
        return None, None, None
    m = re.match(r"^(.+?),\s*([A-Z]{2})\s+(\d{5})?", location_str.strip())
    if m:
        return m.group(1).strip(), m.group(2), m.group(3)
    return location_str, None, None


class PawBoostNormalizer:
    def normalize(self, raw: dict, record_type_str: str) -> PetRecord:
        details = raw.get("details", [])

        # Parse species and gender from details list
        animal_type = None
        gender = None
        _species_map = {
            "dog": AnimalType.DOG, "cat": AnimalType.CAT,
            "bird": AnimalType.BIRD, "rabbit": AnimalType.RABBIT,
            "other": AnimalType.OTHER,
        }
        for detail in details:
            d_lower = detail.lower()
            if d_lower in _species_map:
                animal_type = _species_map[d_lower]
            elif d_lower == "male":
                gender = Gender.MALE
            elif d_lower == "female":
                gender = Gender.FEMALE

        city, state, zip_code = _parse_city_state_zip(raw.get("location_city"))

        # Override ZIP from detail URL slug if available
        if raw.get("zip_code"):
            zip_code = raw["zip_code"]

        record_type = RecordType.LOST if record_type_str == "lost" else RecordType.FOUND

        date_event = _parse_date_text(raw.get("date_lost_text"))

        # Full photo URL (without -thumb suffix)
        photos = []
        if raw.get("full_photo_url"):
            photos.append(raw["full_photo_url"])
        elif raw.get("thumbnail_url"):
            photos.append(raw["thumbnail_url"])

        return PetRecord(
            source="pawboost",
            source_id=str(raw.get("pet_id", "")),
            source_url=raw.get("detail_url"),
            record_type=record_type,
            animal_type=animal_type,
            name=raw.get("name"),
            gender=gender,
            date_event=date_event,
            location_text=raw.get("location_text"),
            city=city,
            state=state,
            zip=zip_code,
            country="US",
            description=raw.get("description"),
            owner_message=raw.get("owner_message"),
            photos=photos,
            thumbnail_url=raw.get("thumbnail_url"),
            facebook_post_url=raw.get("facebook_post_url"),
            nextdoor_url=raw.get("nextdoor_url"),
            alert_number=raw.get("pet_id"),
            raw=raw,
        )
