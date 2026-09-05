from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.models import PetMatch, PetRow
from k9overwatch.web.dependencies import get_db, verify_admin
from k9overwatch.web.templates_config import templates

router = APIRouter()


@router.get("/matches")
async def matches_page(
    request: Request,
    match_type: str = Query(default="lost_found"),
    confidence: list[str] = Query(default=["high", "medium"]),
    pet: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    """
    Match review list. `pet=<id>` deep-links to the matches involving one pet —
    used by the map report cards' potential-match badges.
    """
    PAGE_SIZE = 20
    stmt = select(PetMatch).where(
        PetMatch.match_type == match_type,
        PetMatch.confidence.in_(confidence),
    )
    if pet:
        stmt = stmt.where(or_(PetMatch.pet_a_id == pet, PetMatch.pet_b_id == pet))
    stmt = stmt.order_by(desc(PetMatch.score)).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)

    result = await db.execute(stmt)
    matches = result.scalars().all()

    # Bulk-fetch all referenced pet rows in a single query
    pet_ids = set()
    for m in matches:
        pet_ids.add(m.pet_a_id)
        pet_ids.add(m.pet_b_id)
    pets_by_id: dict = {}
    if pet_ids:
        pets_result = await db.execute(select(PetRow).where(PetRow.id.in_(list(pet_ids))))
        for row in pets_result.scalars().all():
            pets_by_id[row.id] = row

    match_pairs = []
    for m in matches:
        pet_a = pets_by_id.get(m.pet_a_id)
        pet_b = pets_by_id.get(m.pet_b_id)
        if pet_a and pet_b:
            match_pairs.append({"match": m, "pet_a": pet_a, "pet_b": pet_b})

    return templates.TemplateResponse(
        request,
        "matches/list.html",
        {
            "match_pairs": match_pairs,
            "active_tab": match_type,
            "confidence": confidence,
            "page": page,
        },
    )


@router.post("/api/matches/{match_id}/review", dependencies=[Depends(verify_admin)])
async def review_match(
    request: Request,
    match_id: str,
    confirmed: bool,
    db: AsyncSession = Depends(get_db),
):
    """Mark a match as reviewed. Returns an HTML badge fragment for HTMX outerHTML swap."""
    result = await db.execute(select(PetMatch).where(PetMatch.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    match.reviewed = True
    match.confirmed = confirmed
    # Record the decision-time signal snapshot (C10) so future re-weighting has
    # labeled data even if a later re-match pass updates score/signals_fired.
    match.decision_snapshot = {
        "confirmed": confirmed,
        "score": match.score,
        "signals_fired": dict(match.signals_fired or {}),
        "decided_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
    }
    await db.commit()
    return templates.TemplateResponse(
        request,
        "matches/_review_badge.html",
        {"match_id": match_id, "confirmed": confirmed},
    )
