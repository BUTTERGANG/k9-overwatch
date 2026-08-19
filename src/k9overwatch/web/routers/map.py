from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.models import PetRow
from k9overwatch.db.repository import (
    AGE_BUCKET_LABELS,
    AGE_BUCKETS,
    PetRepository,
    age_bucket,
    effective_age_days,
)
from k9overwatch.web.dependencies import get_db
from k9overwatch.web.schemas.pet import GeoJSONCollection, GeoJSONFeature, PetSummary
from k9overwatch.web.templates_config import templates

router = APIRouter()

# Animal types that are NOT explicitly "dog" or "cat" — these all map to the
# "Other" checkbox in the map UI so users don't need to know internal enum values.
_OTHER_ANIMAL_TYPES = {"bird", "rabbit", "other"}

@router.get("/map")
async def map_page(request: Request):
    return templates.TemplateResponse(request, "map.html", {})


@router.get("/api/map/buckets")
async def get_active_buckets(
    record_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Active-listing counts by recency, with plain-language labels for the UI."""
    repo = PetRepository(db)
    counts = await repo.get_active_age_buckets(record_type=record_type)
    return {
        "buckets": [
            {"key": k, "label": AGE_BUCKET_LABELS[k], "count": counts[k]}
            for k in AGE_BUCKETS
        ],
        "total": sum(counts.values()),
    }

@router.get("/api/map/geojson", response_model=GeoJSONCollection)
async def get_map_geojson(
    sw_lat: float = Query(ge=-90, le=90),
    sw_lng: float = Query(ge=-180, le=180),
    ne_lat: float = Query(ge=-90, le=90),
    ne_lng: float = Query(ge=-180, le=180),
    record_type: list[str] = Query(default=["lost", "found", "sighting", "adoptable"]),
    animal_type: list[str] = Query(default=[]),
    days: int = Query(default=90, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    if sw_lat > ne_lat:
        raise HTTPException(status_code=422, detail="Invalid latitude bounds")

    longitude_filter = (
        PetRow.lon.between(sw_lng, ne_lng)
        if sw_lng <= ne_lng
        else or_(PetRow.lon >= sw_lng, PetRow.lon <= ne_lng)
    )
    stmt = select(PetRow).where(
        PetRow.active == True,
        PetRow.lat >= sw_lat,
        PetRow.lat <= ne_lat,
        longitude_filter,
    )

    if record_type:
        stmt = stmt.where(PetRow.record_type.in_(record_type))

    if animal_type:
        # "other" is a catch-all for every animal that isn't explicitly dog or cat.
        # Expand it to include bird, rabbit, and records with no animal_type set so
        # that sources storing those values still appear when "Other" is checked.
        if "other" in animal_type:
            exact = [t for t in animal_type if t not in _OTHER_ANIMAL_TYPES]
            other_types = list(_OTHER_ANIMAL_TYPES)
            stmt = stmt.where(
                or_(
                    PetRow.animal_type.in_(exact + other_types),
                    PetRow.animal_type == None,  # noqa: E711 — SQLAlchemy IS NULL
                )
            )
        else:
            stmt = stmt.where(PetRow.animal_type.in_(animal_type))

    if days:
        # Include records whose effective age is within `days`. Records with no
        # parsed date_event are kept (they fall back to scrape age) so a listing
        # is never hidden just because its date didn't parse — matching bucket logic.
        cutoff = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)).date()
        stmt = stmt.where(
            or_(PetRow.date_event >= cutoff, PetRow.date_event.is_(None))
        )

    # Limit payload size, but count the full matching set so the client can
    # tell users when the viewport contains more records than returned.
    count_stmt = stmt.with_only_columns(func.count(PetRow.id)).order_by(None)
    total = int((await db.execute(count_stmt)).scalar_one())
    stmt = stmt.order_by(PetRow.date_event.desc()).limit(500)

    result = await db.execute(stmt)
    pets = result.scalars().all()

    features = []
    # One bulk query for match counts (instead of N per-pin lookups).
    match_counts = await PetRepository(db).get_match_counts([str(p.id) for p in pets])
    for pet in pets:
        if pet.lat is None or pet.lon is None:
            continue

        summary = PetSummary(
            id=str(pet.id),
            source=pet.source,
            record_type=pet.record_type,
            animal_type=pet.animal_type,
            name=pet.name,
            breed=pet.breed,
            color_primary=pet.color_primary,
            gender=pet.gender,
            date_event=pet.date_event,
            location_text=pet.location_text,
            city=pet.city,
            state=pet.state,
            zip=pet.zip,
            lat=pet.lat,
            lon=pet.lon,
            thumbnail_url=pet.thumbnail_url,
            active=pet.active,
            match_count=match_counts.get(str(pet.id), 0),
            age_bucket=age_bucket(
                effective_age_days(pet.date_event, pet.days_since_event, pet.scraped_at)
            ),
            geocode_source=pet.geocode_source,
            geocode_confidence=pet.geocode_confidence,
        )

        feature = GeoJSONFeature(
            geometry={"type": "Point", "coordinates": [pet.lon, pet.lat]},
            properties=summary
        )
        features.append(feature)

    returned = len(features)
    return GeoJSONCollection(
        features=features,
        total=total,
        returned=returned,
        truncated=total > returned,
    )
