from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.models import PetMatch, PetRow, ScraperState
from k9overwatch.web.dependencies import get_db, verify_admin
from k9overwatch.web.templates_config import templates

router = APIRouter()

# Keep dashboard health aligned with the scheduler's production intervals.
SCRAPER_INTERVAL_MINUTES = {
    "indylostpetalert": 15,
    "24petconnect": 30,
    "pawboost": 35,
    "petfbi": 40,
    "lostmydoggie": 45,
}


def scraper_health(state: ScraperState, *, now: datetime | None = None) -> str:
    """Return a small, API/template-friendly health status for one scraper."""
    if not state.last_run_at:
        return "pending"
    if not state.last_run_success:
        return "error"
    now = now or datetime.now(UTC).replace(tzinfo=None)
    interval = SCRAPER_INTERVAL_MINUTES.get(state.source, 60)
    age_minutes = (now - state.last_run_at).total_seconds() / 60
    # Allow one missed interval plus a small scheduler/browser grace period.
    if age_minutes > interval + 15:
        return "stale"
    return "healthy"


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
                "health": scraper_health(s),
                "consecutive_errors": s.consecutive_errors or 0,
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


# ── Admin: Content Reports ────────────────────────────────────────────


@router.get("/admin/reports", dependencies=[Depends(verify_admin)])
async def admin_reports_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """List pending ContentReports with dismiss/action buttons."""
    from k9overwatch.db.models import ContentReport

    stmt = select(ContentReport).where(ContentReport.status == "pending").order_by(ContentReport.created_at.desc())
    reports = list((await db.execute(stmt)).scalars().all())
    return templates.TemplateResponse(request, "admin/reports.html", {"reports": reports})


@router.post("/admin/reports/{report_id}/dismiss", dependencies=[Depends(verify_admin)])
async def dismiss_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Set a ContentReport status to dismissed."""
    from k9overwatch.db.models import ContentReport

    report = await db.get(ContentReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    report.status = "dismissed"
    report.reviewed_at = datetime.now(UTC).replace(tzinfo=None)
    report.reviewed_by = "admin"
    await db.commit()
    return RedirectResponse(url="/admin/reports", status_code=303)


@router.post("/admin/reports/{report_id}/action", dependencies=[Depends(verify_admin)])
async def action_report(
    report_id: str,
    request: Request,
    deactivate: str = Form(default="false"),
    db: AsyncSession = Depends(get_db),
):
    """Review a ContentReport; optionally deactivate the target."""
    from k9overwatch.db.models import ContentReport, ContactRequest, PetRow

    report = await db.get(ContentReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    do_deactivate = deactivate.lower() in ("true", "1", "yes", "on")

    if do_deactivate and report.target_type == "report":
        pet = await db.get(PetRow, report.target_id)
        if pet is not None:
            pet.active = False
            pet.owner_report_status = "closed"
    elif do_deactivate and report.target_type == "contact_request":
        contact = await db.get(ContactRequest, report.target_id)
        if contact is not None:
            contact.status = "closed"

    report.status = "reviewed"
    report.reviewed_at = datetime.now(UTC).replace(tzinfo=None)
    report.reviewed_by = "admin"
    await db.commit()
    return RedirectResponse(url="/admin/reports", status_code=303)
