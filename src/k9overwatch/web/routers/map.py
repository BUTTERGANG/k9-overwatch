from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
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
    sw_lat: float, sw_lng: float, ne_lat: float, ne_lng: float,
    record_type: list[str] = Query(default=["lost", "found", "sighting", "adoptable"]),
    animal_type: list[str] = Query(default=[]),
    days: int = Query(default=90),
    db: AsyncSession = Depends(get_db),
):
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
        stmt = stmt.where(PetRow.animal_type.in_(animal_type))
        
    from datetime import datetime, timedelta
    if days:
        cutoff = datetime.now() - timedelta(days=days)
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
            match_count=0,  # Could query matching table for this later
            age_bucket=age_bucket(
                effective_age_days(pet.date_event, pet.days_since_event, pet.scraped_at)
            ),
        )
        
        feature = GeoJSONFeature(
            geometry={"type": "Point", "coordinates": [pet.lon, pet.lat]},
            properties=summary
        )
        features.append(feature)
        
    return GeoJSONCollection(features=features, total=len(features))
