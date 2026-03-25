"""Normalizer: LostMyDoggie card dict → PetRecord."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from ..models.enums import AnimalType, Gender, RecordType
from ..models.pet_record import PetRecord


def _parse_date(date_str: str) -> Optional[object]:
    """Parse 'YYYY-MM-DD' or 'MM/DD/YYYY' date strings."""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


class LostMyDoggieNormalizer:
    def normalize(
        self,
        data: dict,
        animal_type_str: str,
        record_type_str: str,
    ) -> Optional[PetRecord]:
        pet_id = data.get("pet_id")
        if not pet_id:
            return None

        animal_type = AnimalType.DOG if animal_type_str == "dog" else AnimalType.CAT
        record_type = RecordType.LOST if record_type_str == "lost" else RecordType.FOUND

        # status_line: "Lost \xa0Male Dog" or "Found \xa0Female Cat"
        status_line = data.get("status_line", "")
        gender = None
        sl_lower = status_line.lower()
        if "female" in sl_lower:
            gender = Gender.FEMALE
        elif "male" in sl_lower:
            gender = Gender.MALE

        # location: "INDIANAPOLIS, IN\n46254"
        location_raw = data.get("location_raw", "")
        location_parts = location_raw.split("\n")
        location_text = location_parts[0].strip() if location_parts else None
        zip_code = location_parts[1].strip() if len(location_parts) > 1 else None

        # details list: [breed, "Color1, Color2", "Lost: YYYY-MM-DD"]
        details = data.get("details", [])
        breed = details[0] if len(details) > 0 else None
        color_raw = details[1] if len(details) > 1 else None
        color_primary = None
        color_secondary = None
        if color_raw:
            colors = [c.strip() for c in color_raw.split(",")]
            color_primary = colors[0] if colors else None
            color_secondary = colors[1] if len(colors) > 1 else None

        date_event = None
        if len(details) > 2:
            m = re.search(r"(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})", details[2])
            if m:
                date_event = _parse_date(m.group(1))

        full_photo_url = data.get("full_photo_url")
        thumbnail_url = data.get("thumbnail_url")

        return PetRecord(
            source="lostmydoggie",
            source_id=pet_id,
            source_url=data.get("detail_url"),
            record_type=record_type,
            animal_type=animal_type,
            name=data.get("name"),
            breed=breed,
            color_primary=color_primary,
            color_secondary=color_secondary,
            gender=gender,
            date_event=date_event,
            location_text=location_text,
            zip=zip_code,
            country="US",
            photos=[full_photo_url] if full_photo_url else [],
            thumbnail_url=thumbnail_url,
            raw=data,
        )
