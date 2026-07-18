from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

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

    # Load both pets for each match pair
    match_pairs = []
    for m in matches:
        pet_a_res = await db.execute(select(PetRow).where(PetRow.id == m.pet_a_id))
        pet_b_res = await db.execute(select(PetRow).where(PetRow.id == m.pet_b_id))
        pet_a = pet_a_res.scalar_one_or_none()
        pet_b = pet_b_res.scalar_one_or_none()
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
