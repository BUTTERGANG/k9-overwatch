"""Normalizer: 24petconnect HTML card → PetRecord."""
from __future__ import annotations

import re

from bs4 import Tag

from ..models.enums import AnimalType, Gender, RecordType, Size
from ..models.pet_record import PetRecord

# Maps search_type string → RecordType
SEARCH_TYPE_MAP = {
    "LOST": RecordType.LOST,
    "FOUND": RecordType.FOUND,
    "ADOPT": RecordType.ADOPTABLE,
}

ANIMAL_TYPE_MAP = {
    "dog": AnimalType.DOG,
    "dogs": AnimalType.DOG,
    "cat": AnimalType.CAT,
    "cats": AnimalType.CAT,
    "bird": AnimalType.BIRD,
    "rabbit": AnimalType.RABBIT,
    "other": AnimalType.OTHER,
}

# Breed name fragments → animal type (for lost/found cards that lack "Animal type" span)
_CAT_BREED_FRAGMENTS = {
    "shorthair", "longhair", "mediumhair", "domestic sh", "domestic lh",
    "siamese", "persian", "maine coon", "ragdoll", "bengal", "abyssinian",
    "bombay", "burmese", "sphynx", "himalayan", "tabby", "calico", "tortoiseshell",
}
_DOG_BREED_FRAGMENTS = {
    "terrier", "retriever", "shepherd", "labrador", "poodle", "bulldog",
    "pit bull", "pittbull", "rottweiler", "beagle", "spaniel", "dachshund",
    "chihuahua", "husky", "malamute", "collie", "corgi", "pomeranian",
    "maltese", "shih tzu", "boxer", "doberman", "great dane", "dalmatian",
    "pointer", "setter", "hound", "schnauzer", "akita", "samoyed",
    "weimaraner", "vizsla", "plott", "coonhound", "bloodhound",
    "griffon", "basenji", "affenpinscher", "bichon", "bolognese",
    "mastiff", "pinscher", "spitz", "chow", "dingo",
    "papillon", "pekinese", "pekingese", "whippet", "greyhound",
}


def _infer_animal_type_from_breed(breed: str | None) -> AnimalType | None:
    """Infer animal type from breed name when the API doesn't provide one."""
    if not breed:
        return None
    b = breed.lower()
    if any(f in b for f in _CAT_BREED_FRAGMENTS):
        return AnimalType.CAT
    if "rabbit" in b or "bunny" in b:
        return AnimalType.RABBIT
    if "bird" in b or "parrot" in b or "cockatiel" in b or "parakeet" in b:
        return AnimalType.BIRD
    if any(f in b for f in _DOG_BREED_FRAGMENTS):
        return AnimalType.DOG
    return None

SIZE_MAP = {
    "x-small (10 lbs & under)": Size.XSMALL,
    "small (10-25 lbs)": Size.SMALL,
    "medium (25-50 lbs)": Size.MEDIUM,
    "large (50-75 lbs)": Size.LARGE,
    "x-large (75-90 lbs)": Size.XLARGE,
    "xx-large (90+ lbs)": Size.XXLARGE,
}


def _field(card: Tag, label: str) -> str | None:
    """Extract a labeled field value from a 24petconnect listing card.
    Cards contain spans like: <span>Name : Chase</span>
    """
    pattern = re.compile(rf"{re.escape(label)}\s*:\s*(.+)", re.IGNORECASE)
    for span in card.find_all("span"):
        text = span.get_text(strip=True)
        m = pattern.search(text)
        if m:
            return m.group(1).strip()
    return None


def _extract_onclick(card: Tag) -> tuple[str | None, str | None]:
    """Extract ShelterCode and AnimalId from the onclick handler.
    The onclick is on the card div itself, not a descendant.
    """
    # Check the card element itself first, then descendants
    onclick_str = card.get("onclick", "") or ""
    if not onclick_str:
        el = card.find(onclick=True)
        onclick_str = el.get("onclick", "") if el else ""
    m = re.search(r"Details\('([^']+)',\s*'?(\d+)'?\)", onclick_str)
    if m:
        return m.group(1), m.group(2)
    # Fallback: extract from div id="Result_XXXXXX"
    div_id = card.get("id", "")
    id_match = re.match(r"Result_(\d+)", div_id)
    if id_match:
        return None, id_match.group(1)
    return None, None


def _parse_gender(value: str | None) -> Gender | None:
    if not value:
        return None
    v = value.upper().strip()
    if v in ("M", "MALE"):
        return Gender.MALE
    if v in ("F", "FEMALE"):
        return Gender.FEMALE
    return Gender.UNKNOWN


class PetConnect24Normalizer:
    """Convert a BeautifulSoup Tag (gridResult card) to a PetRecord."""

    def normalize(self, card: Tag, search_type: str) -> PetRecord:
        shelter_code, animal_id = _extract_onclick(card)
        record_type = SEARCH_TYPE_MAP.get(search_type, RecordType.LOST)

        # Build source URL
        source_url = None
        if shelter_code and animal_id:
            source_url = f"https://24petconnect.com/LostFound/Details/{shelter_code}/{animal_id}"

        # Animal type from "Animal type : Dog" span (adoptable records)
        # Lost/found cards lack this field; infer from breed instead
        animal_type_str = _field(card, "Animal type")
        breed_str = _field(card, "Breed")
        animal_type = None
        if animal_type_str:
            animal_type = ANIMAL_TYPE_MAP.get(animal_type_str.lower())
        if animal_type is None:
            animal_type = _infer_animal_type_from_breed(breed_str)

        # Extract photo URL
        img = card.find("img")
        photo_url = None
        if img and img.get("src"):
            src = img["src"]
            if "/image/" in src:
                photo_url = f"https://24petconnect.com{src}" if src.startswith("/") else src

        # Days since event
        days_str = _field(card, "Days Since Lost") or _field(card, "Days Since Found")
        days_since = None
        if days_str:
            try:
                days_since = int(re.search(r"\d+", days_str).group())
            except (AttributeError, ValueError):
                pass

        # Size
        size_str = _field(card, "Size")
        size = None
        if size_str:
            size = SIZE_MAP.get(size_str.lower())

        return PetRecord(
            source="24petconnect",
            source_id=animal_id or "",
            source_url=source_url,
            record_type=record_type,
            animal_type=animal_type,
            name=_field(card, "Name"),
            breed=_field(card, "Breed"),
            gender=_parse_gender(_field(card, "Gender")),
            age=_field(card, "Age"),
            size=size,
            status=_field(card, "Status"),
            days_since_event=days_since,
            location_text=_field(card, "Location Lost") or _field(card, "Location Found"),
            shelter_name=_field(card, "Located at"),
            shelter_code=shelter_code,
            photos=[photo_url] if photo_url else [],
            thumbnail_url=photo_url,
            raw={"html": str(card), "search_type": search_type},
        )
