"""Normalizer: IndyHumane Shelterluv HTML card → PetRecord."""
from __future__ import annotations

import re
from datetime import date, datetime

from bs4 import Tag

from ..models.enums import AnimalType, Gender, RecordType, Size
from ..models.pet_record import PetRecord


GENDER_MAP: dict[str, Gender] = {
    "female": Gender.FEMALE,
    "male": Gender.MALE,
}


def _parse_gender(text: str | None) -> tuple[Gender | None, bool | None]:
    """Parse 'Female/Spayed' → (FEMALE, True) or 'Male/Neutered' → (MALE, True)."""
    if not text:
        return None, None
    parts = text.split("/")
    gender = GENDER_MAP.get(parts[0].strip().lower())
    altered = None
    if len(parts) > 1:
        altered_str = parts[1].strip().lower()
        altered = altered_str in ("spayed", "neutered")
    return gender, altered


class IndyHumaneNormalizer:
    """Convert a BeautifulSoup Tag (sla-card from IndyHumane) to a PetRecord."""

    SOURCE_NAME = "indyhumane"
    SHELTER_NAME = "IndyHumane"

    def normalize(self, card: Tag, animal_type: AnimalType) -> PetRecord | None:
        # Shelterluv ID from the adopt-me link
        link_el = card.find("a", class_="sla-card__btn")
        if not link_el:
            return None
        href = str(link_el.get("href", ""))
        m = re.search(r"id=(\d+)", href)
        if not m:
            return None
        shelterluv_id = m.group(1)

        # Name
        name_el = card.find("p", class_="sla-card__name")
        name = name_el.get_text(strip=True) if name_el else None

        # Meta fields: two <p class="sla-card__meta"> elements
        meta_els = card.find_all("p", class_="sla-card__meta")
        sex_text = meta_els[0].get_text(strip=True) if len(meta_els) > 0 else None
        age_text = meta_els[1].get_text(strip=True) if len(meta_els) > 1 else None

        gender, altered = _parse_gender(sex_text)

        # Photo
        img = card.find("img")
        photo_url = None
        if img and img.get("src"):
            photo_url = str(img["src"])

        if not name:
            name = f"IndyHumane pet {shelterluv_id}"

        return PetRecord(
            source=self.SOURCE_NAME,
            source_id=shelterluv_id,
            source_url=f"https://indyhumane.org/adopt/adopt-me/?id={shelterluv_id}",
            record_type=RecordType.ADOPTABLE,
            animal_type=animal_type,
            name=name,
            gender=gender,
            age=age_text or None,
            shelter_name=self.SHELTER_NAME,
            photos=[photo_url] if photo_url else [],
            thumbnail_url=photo_url,
        )