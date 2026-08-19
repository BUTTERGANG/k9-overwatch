"""
Owner-submitted lost/found reports.

Lets a logged-in person post a report about an animal they lost or found,
including photo uploads stored locally under data/uploads/. Creates a PetRow
with source="user" so it flows through the same map/matching pipeline as scraped
records. Submitted reports are geocoded from the entered location before save.
"""
from __future__ import annotations

import os
import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.repository import PetRepository
from k9overwatch.models.pet_record import PetRecord
from k9overwatch.web.dependencies import get_current_user_id, get_db
from k9overwatch.web.rate_limit import rate_limit
from k9overwatch.web.templates_config import templates

router = APIRouter()

UPLOAD_DIR = os.path.join("data", "uploads")
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PHOTOS = 3
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def _has_image_signature(content: bytes, ext: str) -> bool:
    """Check the image container signature, rather than trusting the filename/MIME."""
    if ext in {".jpg", ".jpeg"}:
        return _looks_like_jpeg(content)
    if ext == ".png":
        return content.startswith(b"\x89PNG\r\n\x1a\n") and content[12:16] == b"IHDR"
    if ext == ".webp":
        return len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    return False


def _looks_like_jpeg(content: bytes) -> bool:
    """Validate JPEG markers without decoding pixel data."""
    if len(content) < 4 or not content.startswith(b"\xff\xd8") or not content.endswith(b"\xff\xd9"):
        return False
    pos = 2
    has_frame = False
    while pos < len(content) - 2:
        if content[pos] != 0xFF:
            return False
        while pos < len(content) and content[pos] == 0xFF:
            pos += 1
        if pos >= len(content):
            return False
        marker = content[pos]
        pos += 1
        if marker == 0xDA:
            if pos + 2 > len(content) - 2:
                return False
            segment_length = int.from_bytes(content[pos : pos + 2], "big")
            if segment_length < 2 or pos + segment_length > len(content) - 2:
                return False
            return has_frame and content[pos + segment_length :].endswith(b"\xff\xd9")
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            return False
        if pos + 2 > len(content):
            return False
        segment_length = int.from_bytes(content[pos : pos + 2], "big")
        if segment_length < 2 or pos + segment_length > len(content):
            return False
        if marker in {
            0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
            0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
        }:
            has_frame = True
        pos += segment_length
    return False


def _save_uploads(files: list[UploadFile]) -> list[str]:
    """Save at most ``MAX_PHOTOS`` bounded, signature-checked image uploads."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    paths: list[str] = []
    for f in files:
        if not f or not f.filename:
            continue
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ALLOWED_EXT:
            continue
        f.file.seek(0)
        content = f.file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES or not _has_image_signature(content, ext):
            continue
        name = f"{uuid.uuid4().hex}{ext}"
        dest = os.path.join(UPLOAD_DIR, name)
        with open(dest, "wb") as out:
            out.write(content)
        paths.append(f"/uploads/{name}")
        if len(paths) >= MAX_PHOTOS:
            break
    return paths


@router.get("/report")
async def report_page(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await get_current_user_id(request)
    if not user_id:
        return RedirectResponse(url="/login?next=/report", status_code=302)
    return templates.TemplateResponse(request, "accounts/report.html", {})


@router.post("/report", dependencies=[Depends(rate_limit("report", limit=10))])
async def submit_report(
    request: Request,
    record_type: str = Form(...),
    animal_type: str = Form("dog"),
    name: str = Form(default=""),
    breed: str = Form(default=""),
    color_primary: str = Form(default=""),
    gender: str = Form(default=""),
    distinctive_features: str = Form(default=""),
    description: str = Form(default=""),
    location_text: str = Form(default=""),
    contact_name: str = Form(default=""),
    contact_email: str = Form(default=""),
    contact_phone: str = Form(default=""),
    contact_method: str = Form(default=""),
    date_lost: str = Form(default=""),
    files: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
):
    user_id = await get_current_user_id(request)
    if not user_id:
        return RedirectResponse(url="/login?next=/report", status_code=302)
    if record_type not in ("lost", "found", "sighting"):
        return templates.TemplateResponse(
            request, "accounts/report.html",
            {"error": "Choose whether this is a lost, found, or sighted animal."}, status_code=400
        )

    photos = _save_uploads(files)
    thumbnail = photos[0] if photos else None

    # Build a normalized PetRecord then persist as a user-sourced row.
    record = PetRecord(
        source="user",
        source_id=f"user-{user_id}-{uuid.uuid4().hex[:8]}",
        record_type=record_type,  # type: ignore[arg-type]
        animal_type=animal_type,  # type: ignore[arg-type]
        name=name or None,
        breed=breed or None,
        color_primary=color_primary or None,
        gender=gender or None,  # type: ignore[arg-type]
        distinctive_features=distinctive_features or None,
        description=description or None,
        location_text=location_text or None,
        city=None,
        state="IN",
        contact_name=contact_name or None,
        contact_email=contact_email or None,
        contact_phone=contact_phone or None,
        contact_method=contact_method or None,
        photos=photos,
        thumbnail_url=thumbnail,
        date_event=date.fromisoformat(date_lost) if date_lost else None,
    )

    # Geocode the free-text location so the pin lands on the map. Uses the same
    # env-configured provider cascade as the scraper jobs (GEOCODE_PROVIDER).
    # If the provider fails here (rate limit, timeout), the source-agnostic
    # `regeocode_pending_records` job retries it later — see scheduler/jobs.py.
    if location_text:
        from k9overwatch.scheduler.jobs import _make_geocoder_from_env

        geocoder = _make_geocoder_from_env(db)
        record = await geocoder.geocode(record)

    repo = PetRepository(db)
    row, _created = await repo.upsert(record, owner_id=user_id)
    row.owner_report_status = "open"
    await db.commit()

    # Run matching immediately so a brand-new lost report surfaces a found match now.
    from k9overwatch.scheduler.jobs import run_matching_pass

    await run_matching_pass(new_row_ids=[row.id])

    return RedirectResponse(url=f"/pets/{row.id}", status_code=302)
