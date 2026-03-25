import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, case, select, func, text
from datetime import datetime, timezone

from k9overwatch.db.models import PetRow, PetMatch, ScraperState
from k9overwatch.web.dependencies import get_db
from k9overwatch.web.templates_config import templates

router = APIRouter()

_basic_security = HTTPBasic()


def verify_admin(credentials: HTTPBasicCredentials = Depends(_basic_security)) -> None:
    """Verify HTTP Basic credentials against ADMIN_USER / ADMIN_PASSWORD env vars."""
    expected_user = os.getenv("ADMIN_USER", "admin")
    expected_password = os.getenv("ADMIN_PASSWORD", "changeme")
    user_ok = secrets.compare_digest(credentials.username.encode(), expected_user.encode())
    pass_ok = secrets.compare_digest(credentials.password.encode(), expected_password.encode())
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


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
            func.count(case((PetMatch.match_type == "lost_found", 1))).label("reunification_matches"),
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
        "generated_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
    }
