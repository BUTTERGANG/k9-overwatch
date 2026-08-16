import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.models import PetMatch, PetRow
from k9overwatch.db.repository import PetRepository
from k9overwatch.web.dependencies import get_db
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

    return templates.TemplateResponse(
        request,
        "pets/detail.html",
        {"pet": pet, "match_count": match_count},
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
