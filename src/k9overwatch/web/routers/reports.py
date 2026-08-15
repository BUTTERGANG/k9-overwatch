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
from k9overwatch.geocoding.geocoder import GeocodingService
from k9overwatch.geocoding.providers.nominatim import NominatimProvider
from k9overwatch.models.pet_record import PetRecord
from k9overwatch.web.dependencies import get_current_user_id, get_db
from k9overwatch.web.templates_config import templates

router = APIRouter()

UPLOAD_DIR = os.path.join("data", "uploads")
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PHOTOS = 3


def _save_uploads(files: list[UploadFile]) -> list[str]:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    paths: list[str] = []
    for f in files:
        if not f or not f.filename:
            continue
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ALLOWED_EXT:
            continue
        name = f"{uuid.uuid4().hex}{ext}"
        dest = os.path.join(UPLOAD_DIR, name)
        with open(dest, "wb") as out:
            out.write(f.file.read())
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


@router.post("/report")
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

    # Geocode the free-text location so the pin lands on the map.
    if location_text:
        geocoder = GeocodingService(db, [NominatimProvider()])
        record = await geocoder.geocode(record)

    repo = PetRepository(db)
    row, _created = await repo.upsert(record, owner_id=user_id)
    await db.commit()

    # Run matching immediately so a brand-new lost report surfaces a found match now.
    from k9overwatch.scheduler.jobs import run_matching_pass

    await run_matching_pass(new_row_ids=[row.id])

    return RedirectResponse(url=f"/pets/{row.id}", status_code=302)
