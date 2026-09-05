"""Public Recently-Reunited gallery (roadmap §3).

GET /reunited lists pets the *owner* marked reunited (owner_report_status
== "reunited", source == "user"). Scraped records are never shown, even if
they carry a reunited-ish status. /api/stats gains a user_reunifications count.
"""
from __future__ import annotations

from datetime import date

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.models import PetRow


async def _add_pet(db: AsyncSession, **overrides) -> PetRow:
    defaults = dict(
        source="user", source_id="gal-1", record_type="lost",
        animal_type="dog", name="Rex", breed="Beagle Mix",
    )
    defaults.update(overrides)
    row = PetRow(**defaults)
    db.add(row)
    await db.commit()
    return row


async def test_reunited_gallery_renders_reunited_user_pets(client: AsyncClient, db_session: AsyncSession):
    pet = await _add_pet(
        db_session,
        owner_report_status="reunited", active=False,
        date_event=date(2026, 8, 1), thumbnail_url="https://example.com/rex.jpg",
    )
    resp = await client.get("/reunited")
    assert resp.status_code == 200
    assert "Recently Reunited" in resp.text
    assert "Rex" in resp.text
    assert "Beagle Mix" in resp.text
    assert f"/pets/{pet.id}" in resp.text
    assert "/img?url=" in resp.text  # photo proxied like elsewhere
    assert "August" in resp.text or "2026" in resp.text  # reunion-ish date shown


async def test_reunited_gallery_empty_state(client: AsyncClient, db_session: AsyncSession):
    resp = await client.get("/reunited")
    assert resp.status_code == 200
    assert "No reunions yet" in resp.text


async def test_reunited_gallery_excludes_scraped_and_open_records(client: AsyncClient, db_session: AsyncSession):
    # A scraped record that somehow carries a reunited owner status must NOT appear.
    scraped = await _add_pet(
        db_session, source="pawboost", source_id="scraped-9",
        owner_report_status="reunited", name="Secretive",
    )
    # Open user report should not appear either.
    await _add_pet(db_session, source_id="gal-open", owner_report_status="open", name="StillLost")
    resp = await client.get("/reunited")
    assert resp.status_code == 200
    assert "No reunions yet" in resp.text
    assert "Secretive" not in resp.text
    assert scraped.source_url is None or "scraped-9" not in resp.text
    assert "StillLost" not in resp.text


async def test_nav_links_to_reunited_page(client: AsyncClient, db_session: AsyncSession):
    resp = await client.get("/map")
    assert '/reunited"' in resp.text


async def test_api_stats_includes_user_reunifications(client: AsyncClient, db_session: AsyncSession):
    await _add_pet(db_session, owner_report_status="reunited", active=False)
    await _add_pet(db_session, source="petfbi", source_id="x",
                   owner_report_status="reunited", active=False)
    resp = await client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_reunifications"] == 1
