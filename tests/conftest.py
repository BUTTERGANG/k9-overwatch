"""Shared pytest fixtures for K9-Overwatch tests."""
from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from k9overwatch.db.models import Base
from k9overwatch.models.enums import AnimalType, Gender, RecordType
from k9overwatch.models.pet_record import PetRecord


# ── Event loop ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    """Single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── In-memory DB ──────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Fresh in-memory SQLite session per test. Tables created and dropped."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ── PetRecord factories ───────────────────────────────────────────────────────

def make_indy_record(**overrides) -> PetRecord:
    """Sample IndyLostPetAlert PetRecord (lost dog)."""
    defaults = dict(
        source="indylostpetalert",
        source_id="12345",
        source_url="https://indylostpetalert.com/?p=12345",
        record_type=RecordType.LOST,
        animal_type=AnimalType.DOG,
        name="Buddy",
        breed="Labrador Mix",
        color_primary="Black",
        color_secondary="White",
        gender=Gender.MALE,
        date_event=date(2026, 3, 20),
        location_text="4521 N. Keystone Ave, Indianapolis, Marion County",
        city="Indianapolis",
        county="Marion County",
        state="IN",
        zip="46205",
        country="US",
        contact_phone="317-555-0199",
        description="Black lab mix, very friendly, responds to Buddy.",
        alert_number="96891",
    )
    defaults.update(overrides)
    return PetRecord(**defaults)


def make_petconnect24_record(**overrides) -> PetRecord:
    """Sample 24petconnect PetRecord (found cat)."""
    defaults = dict(
        source="24petconnect",
        source_id="654321",
        source_url="https://24petconnect.com/LostFound/Details/INDY01/654321",
        record_type=RecordType.FOUND,
        animal_type=AnimalType.CAT,
        name="Luna",
        breed="Domestic Shorthair",
        color_primary="Grey",
        gender=Gender.FEMALE,
        date_event=date(2026, 3, 18),
        location_text="Broad Ripple Park, Indianapolis IN",
        shelter_name="Indianapolis Animal Care Services",
        shelter_code="INDY01",
        photos=["https://24petconnect.com/image/abc123"],
    )
    defaults.update(overrides)
    return PetRecord(**defaults)


def make_pawboost_record(**overrides) -> PetRecord:
    """Sample PawBoost PetRecord (lost dog)."""
    defaults = dict(
        source="pawboost",
        source_id="PB-7890",
        source_url="https://www.pawboost.com/landing/pet/abc123/lost-max-indianapolis-in-46220",
        record_type=RecordType.LOST,
        animal_type=AnimalType.DOG,
        name="Max",
        gender=Gender.MALE,
        date_event=date(2026, 3, 19),
        location_text="Indianapolis, IN",
        city="Indianapolis",
        state="IN",
        zip="46220",
        country="US",
        description="Golden Retriever, friendly, wearing blue collar.",
        thumbnail_url="https://img-cdn.pawboost.com/thumb/123.jpg",
        photos=["https://img-cdn.pawboost.com/full/123.jpg"],
    )
    defaults.update(overrides)
    return PetRecord(**defaults)


def make_petfbi_record(**overrides) -> PetRecord:
    """Sample PetFBI PetRecord with native coordinates (lost dog)."""
    defaults = dict(
        source="petfbi",
        source_id="987654",
        source_url="https://petfbi.org/report/987654",
        record_type=RecordType.LOST,
        animal_type=AnimalType.DOG,
        name="Rex",
        breed="Golden Retriever",
        color_primary="Golden",
        gender=Gender.MALE,
        age="3 years",
        date_event=date(2026, 3, 15),
        lat=39.8689,
        lon=-86.1397,
        geocode_source="petfbi_native",
        geocode_confidence="high",
        contact_email="owner@example.com",
        contact_name="John Smith",
        description="Very friendly, responds to Rex. | Collar: Red collar",
        photos=["https://petfbi.org/wp-content/uploads/rex.jpg"],
    )
    defaults.update(overrides)
    return PetRecord(**defaults)


def make_lostmydoggie_record(**overrides) -> PetRecord:
    """Sample LostMyDoggie PetRecord (lost dog)."""
    defaults = dict(
        source="lostmydoggie",
        source_id="473213",
        source_url="https://www.lostmydoggie.com/details.cfm?petid=473213",
        record_type=RecordType.LOST,
        animal_type=AnimalType.DOG,
        name="Draco",
        breed="Siberian Husky",
        color_primary="White",
        color_secondary="Brown",
        gender=Gender.MALE,
        date_event=date(2025, 12, 5),
        location_text="INDIANAPOLIS, IN",
        zip="46254",
        country="US",
        photos=["https://www.lostmydoggie.com/pet_images/473213.jpg"],
        thumbnail_url="https://www.lostmydoggie.com/pet_images/thumbs/473213.jpg",
    )
    defaults.update(overrides)
    return PetRecord(**defaults)
