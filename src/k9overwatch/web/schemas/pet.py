from typing import Optional, Literal
from datetime import date, datetime
from pydantic import BaseModel

class PetSummary(BaseModel):
    id: str
    source: str
    record_type: str
    animal_type: Optional[str] = None
    name: Optional[str] = None
    breed: Optional[str] = None
    color_primary: Optional[str] = None
    gender: Optional[str] = None
    date_event: Optional[date] = None
    location_text: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    thumbnail_url: Optional[str] = None
    active: bool
    match_count: int = 0

class PetDetail(PetSummary):
    breed_secondary: Optional[str] = None
    color_secondary: Optional[str] = None
    age: Optional[str] = None
    size: Optional[str] = None
    distinctive_features: Optional[str] = None
    description: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    contact_name: Optional[str] = None
    photos: list[str] = []
    source_url: Optional[str] = None
    date_posted: Optional[datetime] = None
    shelter_name: Optional[str] = None

class GeoJSONFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict
    properties: PetSummary

class GeoJSONCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[GeoJSONFeature]
    total: int
