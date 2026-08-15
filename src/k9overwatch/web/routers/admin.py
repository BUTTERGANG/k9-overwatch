from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.models import PetMatch, PetRow, ScraperState
from k9overwatch.web.dependencies import get_db, verify_admin
from k9overwatch.web.templates_config import templates

router = APIRouter()


@router.get("/admin", dependencies=[Depends(verify_admin)])
async def admin_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    stats = await _get_stats(db)
    return templates.TemplateResponse(request, "admin/dashboard.html", {"stats": stats})


@router.get("/api/admin/stats", dependencies=[Depends(verify_admin)])
async def admin_stats_json(db: AsyncSession = Depends(get_db)):
    return await _get_stats(db)


@router.get("/admin/stats-partial", dependencies=[Depends(verify_admin)])
async def admin_stats_partial(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    stats = await _get_stats(db)
    return templates.TemplateResponse(request, "admin/stats_partial.html", {"stats": stats})


async def _get_stats(db: AsyncSession) -> dict:
    # Scraper states
    scraper_result = await db.execute(select(ScraperState))
    scrapers = scraper_result.scalars().all()

    # All PetRow counts in a single query via conditional aggregation
    pet_stats_result = await db.execute(
        select(
            func.count().label("total_pets"),
            func.count(case((PetRow.active == True, 1))).label("active_pets"),
            func.count(case((PetRow.record_type == "lost", 1))).label("lost_count"),
            func.count(case((PetRow.record_type == "found", 1))).label("found_count"),
            func.count(case((PetRow.lat.is_(None), 1))).label("no_geocode"),
        ).select_from(PetRow)
    )
    pet_row = pet_stats_result.one()

    # All PetMatch counts in a single query
    match_stats_result = await db.execute(
        select(
            func.count().label("total_matches"),
            func.count(case((PetMatch.match_type == "lost_found", 1)))
                .label("reunification_matches"),
        ).select_from(PetMatch)
    )
    match_row = match_stats_result.one()

    return {
        "scrapers": [
            {
                "source": s.source,
                "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
                "last_run_success": s.last_run_success,
                "records_fetched": s.records_fetched,
                "records_new": s.records_new,
                "error_message": s.error_message,
            }
            for s in scrapers
        ],
        "total_pets": pet_row.total_pets,
        "active_pets": pet_row.active_pets,
        "lost_count": pet_row.lost_count,
        "found_count": pet_row.found_count,
        "no_geocode": pet_row.no_geocode,
        "total_matches": match_row.total_matches,
        "reunification_matches": match_row.reunification_matches,
        "generated_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
    }
