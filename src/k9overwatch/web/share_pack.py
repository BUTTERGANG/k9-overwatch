"""
Share-pack generator for Facebook group posting.

Given a PetRow, produce a plain-text + HTML "share pack" optimized for
pasting into local lost/found Facebook groups. Design rules:

  * Emoji header per record type so posts stand out in a busy group feed.
  * Location is cross-streets / neighborhood level from ``location_text``
    (and city/state). RAW COORDINATES ARE NEVER INCLUDED — the detail page
    has the approximate map, and FB posts get screenshotted far and wide.
  * Contact goes through the detail page's secure form, never a personal
    phone/email pasted into a public group.
  * Missing fields are simply omitted (no "Unknown: Unknown" noise).
"""
from __future__ import annotations

import html
import os

from k9overwatch.db.models import PetRow

_HEADERS = {
    ("lost", "dog"): "🐾 LOST DOG",
    ("lost", "cat"): "🐾 LOST CAT",
    ("lost", "other"): "🐾 LOST PET",
    ("found", "dog"): "🏠 FOUND DOG",
    ("found", "cat"): "🏠 FOUND CAT",
    ("found", "other"): "🏠 FOUND PET",
    ("sighting", "dog"): "👀 SIGHTING",
    ("sighting", "cat"): "👀 SIGHTING",
    ("sighting", "other"): "👀 SIGHTING",
}


def detail_url(pet: PetRow, base_url: str | None = None) -> str:
    base = (base_url or os.getenv("APP_BASE_URL", "")).rstrip("/")
    return f"{base}/pets/{pet.id}"


def _header(pet: PetRow) -> str:
    return _HEADERS.get((pet.record_type or "", pet.animal_type or ""),
                        _HEADERS.get((pet.record_type or "", "other"), "🐾 PET ALERT"))


def _location_line(pet: PetRow) -> str | None:
    parts = [pet.location_text, pet.city]
    line = ", ".join(str(p).strip() for p in parts if p)
    if pet.state and pet.state not in line:
        line = f"{line}, {pet.state}" if line else pet.state
    return line or None


def _date_line(pet: PetRow) -> str | None:
    if pet.date_event:
        return pet.date_event.strftime("%B %-d, %Y")
    return None


def _lines(pet: PetRow, base_url: str | None) -> list[str]:
    url = detail_url(pet, base_url)
    lines: list[str] = [_header(pet)]
    if pet.name:
        lines.append(f"Name: {pet.name}")
    if pet.breed:
        lines.append(f"Breed: {pet.breed}")
    if pet.color_primary:
        color = pet.color_primary
        if pet.color_secondary:
            color += f" / {pet.color_secondary}"
        lines.append(f"Color: {color}")
    if pet.gender:
        lines.append(f"Gender: {pet.gender.capitalize()}")
    if pet.size:
        lines.append(f"Size: {pet.size}")
    if pet.distinctive_features:
        lines.append(f"Distinguishing marks: {pet.distinctive_features}")
    location = _location_line(pet)
    if location:
        lines.append(f"Location: {location}")
    date_line = _date_line(pet)
    if date_line:
        lines.append(f"Date: {date_line}")
    lines.append(f"More details: {url}")
    lines.append("More details / contact via secure form at the link above — please don't share personal contact info in comments.")
    return lines


def build_share_pack(pet: PetRow, base_url: str | None = None) -> dict[str, str]:
    """Return ``{"text": ..., "html": ...}`` share pack for a pet."""
    lines = _lines(pet, base_url)
    text = "\n".join(lines)
    html_lines = "\n".join(f"<p>{html.escape(line)}</p>" for line in lines)
    return {"text": text, "html": f"<div>{html_lines}</div>"}
