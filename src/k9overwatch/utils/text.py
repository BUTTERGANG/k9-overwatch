"""Text utility functions shared across scrapers and normalizers."""
from __future__ import annotations

import re
from html import unescape
from typing import Optional


def strip_html(html: str) -> str:
    """Strip all HTML tags and normalize whitespace. Converts common entities."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    # Normalize typographic quotes to ASCII
    text = (
        text.replace("\u2019", "'")
            .replace("\u2018", "'")
            .replace("\u201c", '"')
            .replace("\u201d", '"')
            .replace("\xa0", " ")  # non-breaking space
    )
    return re.sub(r"\s+", " ", text).strip()


def extract(pattern: str, text: str, group: int = 1) -> Optional[str]:
    """Return the first capturing group of a pattern match, or None."""
    m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    return m.group(group).strip() if m else None


def normalize_phone(phone: Optional[str]) -> Optional[str]:
    """Strip formatting from a phone number, return digits only (10 or 11)."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return digits
    return None


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")


def truncate(text: Optional[str], max_length: int = 500) -> Optional[str]:
    """Truncate text to max_length characters, appending '…' if cut."""
    if not text:
        return text
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"


def parse_city_state(location: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """
    Parse 'City, ST' or 'City, State' into (city, state_code).
    Returns (None, None) if pattern does not match.
    """
    if not location:
        return None, None
    m = re.match(r"^(.+?),\s*([A-Za-z]{2,})\s*$", location.strip())
    if not m:
        return None, None
    city = m.group(1).strip().title()
    state = m.group(2).strip().upper()
    # Normalize state name to 2-letter code for common cases
    STATE_ABBR = {
        "INDIANA": "IN", "ILLINOIS": "IL", "OHIO": "OH", "MICHIGAN": "MI",
        "KENTUCKY": "KY", "MISSOURI": "MO", "WISCONSIN": "WI", "MINNESOTA": "MN",
    }
    state = STATE_ABBR.get(state, state)
    return city, state[:2]
