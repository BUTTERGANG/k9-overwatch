from fastapi import APIRouter, Request, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from k9overwatch.db.models import PetMatch, PetRow
from k9overwatch.web.dependencies import get_db
from k9overwatch.web.templates_config import templates

router = APIRouter()


@router.get("/matches")
async def matches_page(
    request: Request,
    match_type: str = Query(default="lost_found"),
    confidence: list[str] = Query(default=["high", "medium"]),
    page: int = Query(default=1),
    db: AsyncSession = Depends(get_db),
):
    PAGE_SIZE = 20
    stmt = select(PetMatch).where(
        PetMatch.match_type == match_type,
        PetMatch.confidence.in_(confidence),
    ).order_by(desc(PetMatch.score)).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)

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
