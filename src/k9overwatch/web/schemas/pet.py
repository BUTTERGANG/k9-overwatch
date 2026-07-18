from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class PetSummary(BaseModel):
    id: str
    source: str
    record_type: str
    animal_type: str | None = None
    name: str | None = None
    breed: str | None = None
    color_primary: str | None = None
    gender: str | None = None
    date_event: date | None = None
    location_text: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    lat: float | None = None
    lon: float | None = None
    thumbnail_url: str | None = None
    active: bool
    match_count: int = 0
    age_bucket: str | None = None   # week | fortnight | month | older

class PetDetail(PetSummary):
    breed_secondary: str | None = None
    color_secondary: str | None = None
    age: str | None = None
    size: str | None = None
    distinctive_features: str | None = None
    description: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    contact_name: str | None = None
    photos: list[str] = []
    source_url: str | None = None
    date_posted: datetime | None = None
    shelter_name: str | None = None

class GeoJSONFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict
    properties: PetSummary

class GeoJSONCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[GeoJSONFeature]
    total: int
