"""Feature: share-pack generator for Facebook group posting.

A share pack is plain text (+ HTML) optimized for pasting into Facebook
groups. It must include the key fields and the detail-page URL, and must
NEVER include raw coordinates.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.models import PetRow, User
from k9overwatch.web.auth import COOKIE_NAME, make_session_token
from k9overwatch.web.share_pack import build_share_pack


def _pet(**overrides) -> PetRow:
    pet = PetRow(
        source="petfbi",
        source_id="abc-123",
        record_type="lost",
        animal_type="dog",
        name="Rex",
        breed="German Shepherd",
        color_primary="Black and tan",
        gender="male",
        size="Large",
        distinctive_features="White patch on chest, limps on left front leg",
        location_text="Near 5th & Meridian, Indianapolis",
        city="Indianapolis",
        state="IN",
        lat=39.7684,
        lon=-86.1581,
        active=True,
    )
    pet.id = "pet-1"
    for key, value in overrides.items():
        setattr(pet, key, value)
    return pet


def test_pack_includes_key_fields_and_detail_url():
    pack = build_share_pack(_pet(), base_url="https://k9.example.com")
    assert "🐾 LOST DOG" in pack["text"]
    assert "Rex" in pack["text"]
    assert "German Shepherd" in pack["text"]
    assert "Black and tan" in pack["text"]
    assert "male" in pack["text"].lower()
    assert "Large" in pack["text"]
    assert "White patch on chest" in pack["text"]
    assert "5th & Meridian" in pack["text"]
    assert "https://k9.example.com/pets/pet-1" in pack["text"]
    # Secure-contact line points at the detail page, not raw contact info
    assert "secure form" in pack["text"] or "secure" in pack["text"].lower()
    assert pack["html"]


@pytest.mark.parametrize(
    "record_type, animal_type, expected",
    [
        ("lost", "dog", "🐾 LOST DOG"),
        ("found", "cat", "🏠 FOUND CAT"),
        ("sighting", "dog", "👀 SIGHTING"),
    ],
)
def test_pack_headers(record_type, animal_type, expected):
    pack = build_share_pack(_pet(record_type=record_type, animal_type=animal_type), base_url="https://k9.example.com")
    assert expected in pack["text"]


def test_pack_excludes_raw_coordinates():
    pack = build_share_pack(_pet(), base_url="https://k9.example.com")
    assert "39.7684" not in pack["text"]
    assert "-86.1581" not in pack["text"]
    assert "39.7684" not in pack["html"]


def test_pack_omits_missing_fields_gracefully():
    pet = _pet(name=None, breed=None, color_primary=None, gender=None, size=None,
               distinctive_features=None, location_text=None, city=None, state=None)
    pack = build_share_pack(pet, base_url="https://k9.example.com")
    assert "🐾 LOST DOG" in pack["text"]
    assert "Unknown" not in pack["text"].split("\n")[0]


# ── Endpoint behavior ────────────────────────────────────────────────────────

async def _seed_user(db_session: AsyncSession, email: str = "owner@example.com") -> User:
    from k9overwatch.db.repository import UserRepository
    user = await UserRepository(db_session).create(email=email, password="supersecret", display_name="Owner")
    await db_session.commit()
    return user


async def test_share_pack_endpoint_public_report_allowed(client: AsyncClient, db_session):
    db_session.add(_pet())
    await db_session.commit()
    resp = await client.get("/pets/pet-1/share-pack")
    assert resp.status_code == 200
    data = resp.json()
    assert "Rex" in data["text"]
    assert "39.7684" not in data["text"]


async def test_share_pack_owner_only_for_user_reports(client: AsyncClient, db_session):
    user = await _seed_user(db_session)
    db_session.add(_pet(source="user", owner_id=user.id))
    await db_session.commit()

    # Anonymous → forbidden
    resp = await client.get("/pets/pet-1/share-pack")
    assert resp.status_code == 403

    # Owner → allowed
    resp = await client.get(
        "/pets/pet-1/share-pack",
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(user.id)}"},
    )
    assert resp.status_code == 200
