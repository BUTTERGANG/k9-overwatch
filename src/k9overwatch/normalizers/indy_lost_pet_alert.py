"""Normalizer: IndyLostPetAlert WordPress post → PetRecord."""
from __future__ import annotations

import re
from datetime import date, datetime
from html import unescape

from ..models.enums import AnimalType, Gender, RecordType, Size
from ..models.pet_record import PetRecord

# ── Category ID maps ──────────────────────────────────────────────────────────

RECORD_TYPE_MAP: dict[int, RecordType] = {
    19: RecordType.LOST,
    20: RecordType.FOUND,
    21: RecordType.SIGHTING,
}

ANIMAL_TYPE_MAP: dict[int, AnimalType] = {
    # Dog categories
    24: AnimalType.DOG,   # lost dog
    27: AnimalType.DOG,   # found dog
    33: AnimalType.DOG,   # dog sighting
    # Cat categories
    25: AnimalType.CAT,
    28: AnimalType.CAT,
    34: AnimalType.CAT,
    # Bird
    166: AnimalType.BIRD,
    172: AnimalType.BIRD,
    # Other
    26: AnimalType.OTHER,
    29: AnimalType.OTHER,
    35: AnimalType.OTHER,
    174: AnimalType.OTHER,  # ferret
}

# Size slug → normalized Size
SIZE_SLUG_MAP: dict[str, Size] = {
    "x-small-lost-dog": Size.XSMALL,
    "x-small-dog-found-pet": Size.XSMALL,
    "xsmall-under-10-lbs": Size.XSMALL,
    "small": Size.SMALL,
    "small-dog-found-pet": Size.SMALL,
    "small-under-25-lbs": Size.SMALL,
    "medium": Size.MEDIUM,
    "medium-dog-found-pet": Size.MEDIUM,
    "large": Size.LARGE,
    "large-dog-found-pet": Size.LARGE,
    "x-large": Size.XLARGE,
    "x-large-dog-found-pet": Size.XLARGE,
    "xx-large-dog": Size.XXLARGE,
    "xx-large-dog-found-pet": Size.XXLARGE,
    "small-cat": Size.XSMALL,
    "small-cat-found-pet": Size.XSMALL,
    "medium-cat": Size.SMALL,
    "medium-cat-found-pet": Size.SMALL,
    "large-cat": Size.MEDIUM,
    "large-cat-found-pet": Size.MEDIUM,
    "x-large-cat": Size.LARGE,
}

# Size text in content → normalized Size
SIZE_TEXT_MAP: dict[str, Size] = {
    "x-small": Size.XSMALL, "xsmall": Size.XSMALL, "under 10": Size.XSMALL,
    "small": Size.SMALL, "10-25": Size.SMALL,
    "medium": Size.MEDIUM, "25-50": Size.MEDIUM,
    "large": Size.LARGE, "50-75": Size.LARGE,
    "x-large": Size.XLARGE, "xlarge": Size.XLARGE, "75-90": Size.XLARGE,
    "xx-large": Size.XXLARGE, "xxlarge": Size.XXLARGE, "90+": Size.XXLARGE,
}

# Color tag ID → canonical name
COLOR_TAG_MAP: dict[int, str] = {
    223: "Black", 224: "Brown", 234: "White", 228: "Grey", 232: "Tan",
    233: "Tri-Color", 237: "Tabby", 226: "Brindle", 241: "Orange",
    231: "Spotted", 230: "Red", 236: "Calico", 227: "Golden",
    229: "Merle", 248: "Tortoise", 235: "Yellow", 239: "Blue", 240: "Green",
}


def _strip_html(html: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    # Normalize curly/typographic quotes to ASCII equivalents
    text = text.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract(pattern: str, text: str, group: int = 1) -> str | None:
    """Return the first match of pattern in text, or None."""
    m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(group).strip()
    return None


def _parse_date(date_str: str | None) -> date | None:
    if not date_str:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


class IndyNormalizer:
    """Convert an IndyLostPetAlert WordPress post dict to a PetRecord."""

    def normalize(self, post: dict) -> PetRecord:
        categories: list[int] = post.get("categories", [])
        tags: list[int] = post.get("tags", [])
        title: str = post["title"]["rendered"]
        raw_html: str = post["content"]["rendered"]
        text = _strip_html(raw_html)

        record_type = self._parse_record_type(categories)
        animal_type = self._parse_animal_type(categories)
        size, size_lbs = self._parse_size(categories, text)
        color_primary, color_secondary = self._parse_colors(tags, text)
        date_event = self._parse_date_event(text, record_type)
        location_text, city, county = self._parse_location(text)

        # Alert number from title
        alert_match = re.search(r"Alert\s*#(\d+)", title, re.IGNORECASE)
        alert_number = alert_match.group(1) if alert_match else None

        # Description = everything after the structured fields
        description = self._extract_description(text)

        photo_url = post.get("jetpack_featured_media_url")
        photos = [photo_url] if photo_url else []

        return PetRecord(
            source="indylostpetalert",
            source_id=str(post["id"]),
            source_url=post.get("link"),
            record_type=record_type or RecordType.LOST,
            animal_type=animal_type,
            name=_extract(r"Pet's\s+Name\s*:\s*([^\n]+?)(?=\s+Pet\s|\s+Color|\s+Date|\s+Approx|\s+Gender)", text),
            breed=_extract(r"Breed\s*:\s*([^\n]+?)(?=\s+\w+\s*:)", text),
            color_primary=color_primary,
            color_secondary=color_secondary,
            gender=self._parse_gender(text),
            size=size,
            size_lbs=size_lbs,
            status=str(record_type) if record_type else None,
            date_event=date_event,
            time_event=_extract(r"Approximate\s+Time\s+Pet\s+(?:Went\s+Missing|Was\s+Found|Was\s+Seen)\s*:\s*([\d:apm ]+)", text),
            date_posted=datetime.fromisoformat(post["date"]) if post.get("date") else None,
            date_updated=datetime.fromisoformat(post["modified"]) if post.get("modified") else None,
            location_text=location_text,
            city=city,
            county=county,
            state="IN",
            country="US",
            contact_phone=_extract(r"Phone\s*:\s*([\d\s\-\(\)\.+]+?)(?=\s+\w+\s*:|\s*$)", text),
            description=description,
            photos=photos,
            thumbnail_url=photo_url,
            alert_number=alert_number,
            raw=post,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _parse_record_type(self, categories: list[int]) -> RecordType | None:
        for cat_id in (19, 20, 21):
            if cat_id in categories:
                return RECORD_TYPE_MAP[cat_id]
        return None

    def _parse_animal_type(self, categories: list[int]) -> AnimalType | None:
        for cat_id in categories:
            if cat_id in ANIMAL_TYPE_MAP:
                return ANIMAL_TYPE_MAP[cat_id]
        return None

    def _parse_size(self, categories: list[int], text: str) -> tuple[Size | None, str | None]:
        # First try category slug
        # (We'd need category objects with slugs; for now use text parsing)
        size_match = _extract(
            r"(?:Pet\s+Size|Size\s+of\s+Pet)\s*:\s*(.+?)(?=Color\s+of\s+Pet|$)",
            text
        )
        if size_match:
            size_text = size_match.lower()
            for key, val in SIZE_TEXT_MAP.items():
                if key in size_text:
                    return val, size_match.strip()
        return None, None

    def _parse_colors(self, tags: list[int], text: str) -> tuple[str | None, str | None]:
        colors = [COLOR_TAG_MAP[t] for t in tags if t in COLOR_TAG_MAP]
        color_from_text = _extract(r"Color\s+of\s+Pet\s*:\s*(.+?)(?=Date\s+Pet|$)", text)
        if not colors and color_from_text:
            color_parts = [c.strip() for c in re.split(r"[,/&]", color_from_text)]
            colors = [c for c in color_parts if c]
        return (colors[0] if colors else None), (colors[1] if len(colors) > 1 else None)

    def _parse_gender(self, text: str) -> Gender | None:
        g = _extract(r"Gender\s*:\s*(\w+)", text)
        if not g:
            return None
        g_lower = g.lower()
        if "male" in g_lower and "fe" not in g_lower:
            return Gender.MALE
        if "female" in g_lower or "fem" in g_lower:
            return Gender.FEMALE
        return Gender.UNKNOWN

    def _parse_date_event(self, text: str, record_type: RecordType | None) -> date | None:
        patterns = [
            r"Date\s+Pet\s+Went\s+Missing\s*:\s*([\d/]+)",
            r"Date\s+Pet\s+Was\s+Found\s*:\s*([\d/]+)",
            r"Date\s+Pet\s+Was\s+Seen\s*:\s*([\d/]+)",
        ]
        for pat in patterns:
            val = _extract(pat, text)
            if val:
                return _parse_date(val)
        return None

    def _parse_location(self, text: str) -> tuple[str | None, str | None, str | None]:
        loc = _extract(r"Location\s+Information\s*:\s*(.+?)(?=Contact\s+Information|$)", text)
        if not loc:
            return None, None, None

        # Split on commas: [street, neighborhood, city, county]
        parts = [p.strip() for p in loc.split(",")]
        city = None
        county = None
        for part in reversed(parts):
            part_lower = part.lower()
            if "county" in part_lower:
                county = part
            elif city is None and county is not None:
                city = part

        return loc, city, county

    def _extract_description(self, text: str) -> str | None:
        """Extract free-text description after the structured fields section."""
        # The description follows the last labeled field (usually Gender:)
        m = re.search(r"Gender\s*:\s*\w+\s*(.+)", text, re.IGNORECASE | re.DOTALL)
        if m:
            desc = m.group(1).strip()
            if len(desc) > 10:
                return desc
        return None
