from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.models import PetRow
from k9overwatch.web.dependencies import get_db
from k9overwatch.web.schemas.pet import GeoJSONCollection, GeoJSONFeature, PetSummary
from k9overwatch.web.templates_config import templates

router = APIRouter()

# Animal types that are NOT explicitly "dog" or "cat" — these all map to the
# "Other" checkbox in the map UI so users don't need to know internal enum values.
_OTHER_ANIMAL_TYPES = {"bird", "rabbit", "other"}

@router.get("/map")
async def map_page(request: Request):
    return templates.TemplateResponse(request, "map.html")

@router.get("/api/map/geojson", response_model=GeoJSONCollection)
async def get_map_geojson(
    sw_lat: float, sw_lng: float, ne_lat: float, ne_lng: float,
    record_type: list[str] = Query(default=["lost", "found", "sighting", "adoptable"]),
    animal_type: list[str] = Query(default=[]),
    days: int = Query(default=90, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    if sw_lat > ne_lat or sw_lng > ne_lng:
        raise HTTPException(status_code=422, detail="Invalid bounding box")

    stmt = select(PetRow).where(
        PetRow.active == True,
        PetRow.lat >= sw_lat,
        PetRow.lat <= ne_lat,
        PetRow.lon >= sw_lng,
        PetRow.lon <= ne_lng,
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
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
        stmt = stmt.where(PetRow.date_event >= cutoff.date())

    # limit to roughly 500 features so browser doesn't choke
    stmt = stmt.order_by(PetRow.date_event.desc()).limit(500)
    
    result = await db.execute(stmt)
    pets = result.scalars().all()

    features = []
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
            match_count=pet.match_count or 0,
        )

        feature = GeoJSONFeature(
            geometry={"type": "Point", "coordinates": [pet.lon, pet.lat]},
            properties=summary
        )
        features.append(feature)

    return GeoJSONCollection(features=features, total=len(features))
