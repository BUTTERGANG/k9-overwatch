import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.models import ContactRequest, PetMatch, PetRow, User
from k9overwatch.db.repository import PetRepository
from k9overwatch.web.dependencies import get_current_user_id, get_db
from k9overwatch.web.templates_config import templates

router = APIRouter()

PAGE_SIZE = 24

async def search_pets(
    db: AsyncSession,
    record_type: list[str],
    animal_type: list[str],
    days: int,
    page: int,
    query: str | None = None,
) -> tuple[Sequence[PetRow], int]:
    stmt = select(PetRow).where(PetRow.active == True)
    
    if record_type:
        stmt = stmt.where(PetRow.record_type.in_(record_type))
    if animal_type:
        stmt = stmt.where(PetRow.animal_type.in_(animal_type))

    if query:
        # Search each word independently so "blue collar" finds listings that
        # contain both terms anywhere in the user-facing description fields.
        search_columns = (
            PetRow.name,
            PetRow.breed,
            PetRow.color_primary,
            PetRow.color_secondary,
            PetRow.description,
            PetRow.distinctive_features,
            PetRow.location_text,
            PetRow.city,
            PetRow.state,
        )
        for term in query.split():
            pattern = f"%{term}%"
            stmt = stmt.where(or_(*(column.ilike(pattern) for column in search_columns)))

    cutoff_date = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
    # Keep listings with an unparsed event date visible; source data frequently
    # omits or mangles dates.
    stmt = stmt.where(or_(PetRow.date_event >= cutoff_date.date(), PetRow.date_event.is_(None)))
    
    # Get total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()
    
    # Get paginated results
    stmt = stmt.order_by(desc(PetRow.date_event))
    stmt = stmt.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    
    result = await db.execute(stmt)
    pets = result.scalars().all()
    
    return pets, total

@router.get("/reunited")
async def reunited_gallery(request: Request, db: AsyncSession = Depends(get_db)):
    """Public 'Recently Reunited' gallery: only owner-marked user-submitted reports."""
    stmt = (
        select(PetRow)
        .where(
            PetRow.source == "user",
            PetRow.owner_report_status == "reunited",
        )
        .order_by(PetRow.date_event.desc().nullslast(), PetRow.scraped_at.desc())
        .limit(100)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return templates.TemplateResponse(
        request, "reunited.html",
        {"pets": rows},
    )


@router.get("/pets")
async def pets_page(
    request: Request,
    record_type: list[str] = Query(default=["lost", "found", "sighting", "adoptable"]),
    animal_type: list[str] = Query(default=[]),
    days: int = Query(default=30, ge=1, le=365),
    page: int = Query(default=1, ge=1),
    q: str | None = Query(default=None, max_length=200),
    db: AsyncSession = Depends(get_db)
):
    pets, total = await search_pets(db, record_type, animal_type, days, page, q)
    total_pages = math.ceil(total / PAGE_SIZE) if total > 0 else 1
    match_counts = await PetRepository(db).get_match_counts([pet.id for pet in pets])

    return templates.TemplateResponse(
        request,
        "pets/list.html",
        {
            "pets": pets,
            "match_counts": match_counts,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "filters": {
                "record_type": record_type,
                "animal_type": animal_type,
                "days": days,
                "q": q or ""
            }
        }
    )

@router.get("/pets/results")
async def pets_results(
    request: Request,
    record_type: list[str] = Query(default=["lost", "found", "sighting", "adoptable"]),
    animal_type: list[str] = Query(default=[]),
    days: int = Query(default=30, ge=1, le=365),
    page: int = Query(default=1, ge=1),
    q: str | None = Query(default=None, max_length=200),
    db: AsyncSession = Depends(get_db)
):
    pets, total = await search_pets(db, record_type, animal_type, days, page, q)
    total_pages = math.ceil(total / PAGE_SIZE) if total > 0 else 1
    match_counts = await PetRepository(db).get_match_counts([pet.id for pet in pets])

    return templates.TemplateResponse(
        request,
        "pets/_results.html",
        {
            "pets": pets,
            "match_counts": match_counts,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "filters": {
                "record_type": record_type,
                "animal_type": animal_type,
                "days": days,
                "q": q or ""
            }
        }
    )


@router.get("/pets/{pet_id}/share-pack")
async def pet_share_pack(
    pet_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """JSON share pack ({text, html}) for pasting into Facebook groups.

    Public (scraped) reports are already public on their detail pages.
    User-submitted reports are owner-only.
    """
    from k9overwatch.web.share_pack import build_share_pack

    pet = (await db.execute(select(PetRow).where(PetRow.id == pet_id))).scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found")
    if pet.source == "user":
        user_id = await get_current_user_id(request)
        if not user_id or user_id != pet.owner_id:
            raise HTTPException(status_code=403, detail="Only the report owner can export a share pack.")
    return build_share_pack(pet)


@router.get("/pets/{pet_id}")
async def pet_detail(
    pet_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PetRow).where(PetRow.id == pet_id))
    pet = result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found")

    match_count_result = await db.execute(
        select(func.count()).where(
            or_(PetMatch.pet_a_id == pet_id, PetMatch.pet_b_id == pet_id)
        )
    )
    match_count = match_count_result.scalar_one()
    current_user_id = await get_current_user_id(request)

    return templates.TemplateResponse(
        request,
        "pets/detail.html",
        {
            "pet": pet,
            "match_count": match_count,
            "current_user_id": current_user_id,
            "contact_sent": request.query_params.get("contact_sent") == "1",
            "tip_sent": request.query_params.get("tip_sent") == "1",
            "located_from_photo": request.query_params.get("located_from_photo") == "1",
        },
    )


@router.post("/pets/{pet_id}/contact")
async def contact_pet_owner(
    pet_id: str,
    request: Request,
    message: str = Form(..., min_length=1, max_length=2000),
    db: AsyncSession = Depends(get_db),
):
    """Create a privacy-preserving contact request without revealing email addresses."""
    user_id = await get_current_user_id(request)
    if not user_id:
        return RedirectResponse(url=f"/login?next=/pets/{pet_id}", status_code=303)
    pet = (await db.execute(select(PetRow).where(PetRow.id == pet_id))).scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found")
    message = message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    if not pet.owner_id:
        raise HTTPException(status_code=400, detail="This report does not have an owner contact channel.")
    if pet.owner_id == user_id:
        raise HTTPException(status_code=400, detail="You cannot contact yourself about your own report.")
    owner = (await db.execute(select(User).where(User.id == pet.owner_id, User.is_active == True))).scalar_one_or_none()
    if owner is None:
        raise HTTPException(status_code=400, detail="This report owner is unavailable.")
    existing = (await db.execute(select(ContactRequest).where(
        ContactRequest.pet_id == pet_id,
        ContactRequest.requester_id == user_id,
        ContactRequest.recipient_id == pet.owner_id,
        ContactRequest.status.in_(["open", "in_conversation"]),
    ))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="You already have an open contact request for this report.")
    contact = ContactRequest(
        pet_id=pet_id,
        requester_id=user_id,
        recipient_id=pet.owner_id,
        message=message,
    )
    db.add(contact)
    await db.flush()
    from k9overwatch.notifications import notify_contact_request
    await notify_contact_request(db, contact, pet)
    await db.commit()
    return RedirectResponse(url=f"/pets/{pet_id}?contact_sent=1", status_code=303)


@router.post("/pets/{pet_id}/tip")
async def submit_scraped_tip(
    pet_id: str,
    request: Request,
    message: str = Form(..., min_length=1, max_length=2000),
    db: AsyncSession = Depends(get_db),
):
    """Submit a tip for a scraped pet listing that has no owner contact info."""
    user_id = await get_current_user_id(request)
    if not user_id:
        return RedirectResponse(url=f"/login?next=/pets/{pet_id}", status_code=303)
    pet = (await db.execute(select(PetRow).where(PetRow.id == pet_id))).scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found")
    message = message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    if pet.owner_id:
        raise HTTPException(status_code=400, detail="This pet already has an owner contact channel. Use the contact form instead.")
    # Fetch the user's email to include in the tip for admin follow-up.
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=400, detail="Your account was not found.")
    # Check for existing tip from this user on this pet to prevent duplicates.
    existing = (await db.execute(select(ContactRequest).where(
        ContactRequest.pet_id == pet_id,
        ContactRequest.requester_id == user_id,
        ContactRequest.recipient_id == "__scraped_tip__",
        ContactRequest.status.in_(["open", "in_conversation"]),
    ))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="You already submitted a tip for this listing.")
    contact = ContactRequest(
        pet_id=pet_id,
        requester_id=user_id,
        recipient_id="__scraped_tip__",
        message=f"[Tip submitted by {user.email}]\n\n{message}",
    )
    db.add(contact)
    await db.commit()
    return RedirectResponse(url=f"/pets/{pet_id}?tip_sent=1", status_code=303)


@router.get("/pets/{pet_id}/matches")
async def pet_matches_partial(
    pet_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """HTMX partial — returns just the match cards for one pet."""
    match_stmt = select(PetMatch).where(
        or_(PetMatch.pet_a_id == pet_id, PetMatch.pet_b_id == pet_id)
    ).order_by(desc(PetMatch.score))
    match_result = await db.execute(match_stmt)
    matches = match_result.scalars().all()

    # Bulk-fetch all referenced "other" pet rows in a single query
    other_ids = [m.pet_b_id if m.pet_a_id == pet_id else m.pet_a_id for m in matches]
    others_by_id: dict = {}
    if other_ids:
        others_result = await db.execute(select(PetRow).where(PetRow.id.in_(other_ids)))
        for row in others_result.scalars().all():
            others_by_id[row.id] = row

    match_pairs = []
    for m in matches:
        other_id = m.pet_b_id if m.pet_a_id == pet_id else m.pet_a_id
        other = others_by_id.get(other_id)
        if other:
            match_pairs.append({"match": m, "other": other})

    return templates.TemplateResponse(
        request,
        "pets/matches_partial.html",
        {"match_pairs": match_pairs},
    )


@router.post("/pets/{pet_id}/reactivate")
async def reactivate_pet(
    pet_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Owner reactivates their own report (was previously closed/reunited)."""
    user_id = await get_current_user_id(request)
    if not user_id:
        return RedirectResponse(url=f"/login?next=/pets/{pet_id}", status_code=303)
    pet = (await db.execute(select(PetRow).where(PetRow.id == pet_id))).scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found")
    if pet.owner_id != user_id:
        raise HTTPException(status_code=403, detail="You are not the owner of this report.")
    if pet.source != "user":
        raise HTTPException(status_code=400, detail="Only user-submitted reports can be reactivated.")
    pet.active = True
    pet.owner_report_status = "open"
    await db.commit()
    return RedirectResponse(url=f"/pets/{pet_id}", status_code=303)


@router.post("/pets/{pet_id}/reunited")
async def mark_reunited(
    pet_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Owner marks their pet as reunited. Deactivates the pet and any matched counterpart."""
    user_id = await get_current_user_id(request)
    if not user_id:
        return RedirectResponse(url=f"/login?next=/pets/{pet_id}", status_code=303)
    pet = (await db.execute(select(PetRow).where(PetRow.id == pet_id))).scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found")
    if pet.owner_id != user_id:
        raise HTTPException(status_code=403, detail="You are not the owner of this report.")
    if pet.source != "user":
        raise HTTPException(status_code=400, detail="Only user-submitted reports can be marked reunited.")
    pet.active = False
    pet.owner_report_status = "reunited"

    # Deactivate the matched counterpart if the match is lost_found type.
    match_result = await db.execute(
        select(PetMatch).where(
            or_(PetMatch.pet_a_id == pet_id, PetMatch.pet_b_id == pet_id),
            PetMatch.match_type == "lost_found",
        )
    )
    for match in match_result.scalars().all():
        counterpart_id = match.pet_b_id if match.pet_a_id == pet_id else match.pet_a_id
        counterpart = await db.get(PetRow, counterpart_id)
        if counterpart is not None and counterpart.active:
            counterpart.active = False
    await db.commit()
    return RedirectResponse(url=f"/pets/{pet_id}", status_code=303)
