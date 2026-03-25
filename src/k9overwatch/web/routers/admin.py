from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from datetime import datetime

from k9overwatch.db.models import PetRow, PetMatch, ScraperState
from k9overwatch.web.dependencies import get_db
from k9overwatch.web.templates_config import templates

router = APIRouter()


@router.get("/admin")
async def admin_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    stats = await _get_stats(db)
    return templates.TemplateResponse("admin/dashboard.html", {"request": request, "stats": stats})


@router.get("/api/admin/stats")
async def admin_stats_json(db: AsyncSession = Depends(get_db)):
    return await _get_stats(db)


async def _get_stats(db: AsyncSession) -> dict:
    # Scraper states
    scraper_result = await db.execute(select(ScraperState))
    scrapers = scraper_result.scalars().all()

    # Total pet counts
    total_pets = (await db.execute(select(func.count()).select_from(PetRow))).scalar_one()
    active_pets = (await db.execute(select(func.count()).select_from(PetRow).where(PetRow.active == True))).scalar_one()

    # Counts by record type
    lost_count = (await db.execute(select(func.count()).select_from(PetRow).where(PetRow.record_type == "lost"))).scalar_one()
    found_count = (await db.execute(select(func.count()).select_from(PetRow).where(PetRow.record_type == "found"))).scalar_one()

    # Ungeocodeable
    no_geo = (await db.execute(select(func.count()).select_from(PetRow).where(PetRow.lat == None))).scalar_one()

    # Match counts
    total_matches = (await db.execute(select(func.count()).select_from(PetMatch))).scalar_one()
    reunification_matches = (await db.execute(select(func.count()).select_from(PetMatch).where(PetMatch.match_type == "lost_found"))).scalar_one()

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
        "total_pets": total_pets,
        "active_pets": active_pets,
        "lost_count": lost_count,
        "found_count": found_count,
        "no_geocode": no_geo,
        "total_matches": total_matches,
        "reunification_matches": reunification_matches,
        "generated_at": datetime.utcnow().isoformat(),
    }
