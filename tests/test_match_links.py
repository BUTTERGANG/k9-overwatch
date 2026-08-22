"""Tests for match badges + direct match links on synchronized map report cards.

The map list cards and popups already show a potential-match badge; this pins
the "direct link" behavior: the badge must deep-link to /matches?pet=<id> so a
user lands on THAT pet's matches, and GET /matches must accept a `pet` filter.
"""
import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.models import PetMatch
from k9overwatch.db.repository import PetRepository

from .conftest import make_petfbi_record


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    from k9overwatch.web.dependencies import get_db
    from k9overwatch.web.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _seed_two_matches(db_session):
    repo = PetRepository(db_session)
    rex, _ = await repo.upsert(make_petfbi_record(source_id="link-a", name="Rex"))
    fido, _ = await repo.upsert(make_petfbi_record(source_id="link-b", name="Fido"))
    buddy, _ = await repo.upsert(make_petfbi_record(source_id="link-c", name="Buddy"))
    shep, _ = await repo.upsert(make_petfbi_record(source_id="link-d", name="Shep"))
    db_session.add_all(
        [
            PetMatch(
                pet_a_id=rex.id, pet_b_id=fido.id,
                match_type="lost_found", score=0.92, confidence="high",
            ),
            PetMatch(
                pet_a_id=buddy.id, pet_b_id=shep.id,
                match_type="lost_found", score=0.88, confidence="high",
            ),
        ]
    )
    await db_session.commit()
    return rex


class TestMatchesPetFilter:
    @pytest.mark.asyncio
    async def test_pet_filter_shows_only_that_pets_matches(self, client, db_session):
        rex = await _seed_two_matches(db_session)

        response = await client.get(f"/matches?pet={rex.id}")

        assert response.status_code == 200
        assert "Rex" in response.text
        assert "Fido" in response.text
        assert "Buddy" not in response.text
        assert "Shep" not in response.text

    @pytest.mark.asyncio
    async def test_no_filter_shows_all_matches(self, client, db_session):
        await _seed_two_matches(db_session)

        response = await client.get("/matches")

        assert response.status_code == 200
        for name in ("Rex", "Fido", "Buddy", "Shep"):
            assert name in response.text

    @pytest.mark.asyncio
    async def test_unknown_pet_yields_empty_list(self, client, db_session):
        await _seed_two_matches(db_session)

        response = await client.get(f"/matches?pet={uuid.uuid4()}")

        assert response.status_code == 200
        assert "Rex" not in response.text


class TestMapCardsDirectMatchLinks:
    @pytest.mark.asyncio
    async def test_map_list_badges_deep_link_to_per_pet_matches(self):
        import pathlib

        js = (
            pathlib.Path(__file__).resolve().parent.parent
            / "src" / "k9overwatch" / "web" / "static" / "js" / "map.js"
        ).read_text()
        # Both the synchronized report card and the marker popup badge must
        # link to the per-pet filtered matches page, not the unfiltered one.
        assert 'href="/matches?pet=' in js
        assert js.count('href="/matches?pet=') >= 2
