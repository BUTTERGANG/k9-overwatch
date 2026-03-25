from collections.abc import Sequence

from fastapi import APIRouter, Request, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, or_
from datetime import datetime, timedelta
import math

from k9overwatch.db.models import PetRow, PetMatch
from k9overwatch.web.dependencies import get_db
from k9overwatch.web.templates_config import templates

router = APIRouter()

PAGE_SIZE = 24

async def search_pets(
    db: AsyncSession,
    record_type: list[str],
    animal_type: list[str],
    days: int,
    page: int
) -> tuple[Sequence[PetRow], int]:
    stmt = select(PetRow).where(PetRow.active == True)
    
    if record_type:
        stmt = stmt.where(PetRow.record_type.in_(record_type))
    if animal_type:
        stmt = stmt.where(PetRow.animal_type.in_(animal_type))
        
    cutoff_date = datetime.now() - timedelta(days=days)
    stmt = stmt.where(PetRow.date_event >= cutoff_date.date())
    
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

@router.get("/pets")
async def pets_page(
    request: Request,
    record_type: list[str] = Query(default=["lost", "found", "sighting", "adoptable"]),
    animal_type: list[str] = Query(default=[]),
    days: int = Query(default=30),
    page: int = Query(default=1),
    db: AsyncSession = Depends(get_db)
):
    pets, total = await search_pets(db, record_type, animal_type, days, page)
    total_pages = math.ceil(total / PAGE_SIZE) if total > 0 else 1
    
    return templates.TemplateResponse(
        "pets/list.html",
        {
            "request": request,
            "pets": pets,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "is_partial": False,
            "filters": {
                "record_type": record_type,
                "animal_type": animal_type,
                "days": days
            }
        }
    )

@router.get("/pets/results")
async def pets_results(
    request: Request,
    record_type: list[str] = Query(default=["lost", "found", "sighting", "adoptable"]),
    animal_type: list[str] = Query(default=[]),
    days: int = Query(default=30),
    page: int = Query(default=1),
    db: AsyncSession = Depends(get_db)
):
    pets, total = await search_pets(db, record_type, animal_type, days, page)
    total_pages = math.ceil(total / PAGE_SIZE) if total > 0 else 1
    
    return templates.TemplateResponse(
        "pets/list.html",
        {
            "request": request,
            "pets": pets,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "is_partial": True,
            "filters": {
                "record_type": record_type,
                "animal_type": animal_type,
                "days": days
            }
        }
    )


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

    return templates.TemplateResponse(
        "pets/detail.html",
        {"request": request, "pet": pet},
    )


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

    match_pairs = []
    for m in matches:
        other_id = m.pet_b_id if m.pet_a_id == pet_id else m.pet_a_id
        other_result = await db.execute(select(PetRow).where(PetRow.id == other_id))
        other = other_result.scalar_one_or_none()
        if other:
            match_pairs.append({"match": m, "other": other})

    return templates.TemplateResponse(
        "pets/matches_partial.html",
        {"request": request, "match_pairs": match_pairs},
    )
