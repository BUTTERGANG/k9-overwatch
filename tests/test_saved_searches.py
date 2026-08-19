from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from k9overwatch.db import connection as db_conn
from k9overwatch.db.models import SavedSearch
from k9overwatch.db.repository import UserRepository
from k9overwatch.web import dependencies as deps
from k9overwatch.web.auth import COOKIE_NAME, csrf_token_for, make_session_token
from k9overwatch.web.main import app


@pytest.fixture
async def client(db_session):

    engine = db_session.bind
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    saved_engine, saved_factory = db_conn._engine, db_conn._session_factory
    db_conn._engine, db_conn._session_factory = engine, factory

    async def override():
        async with factory() as session:
            yield session

    app.dependency_overrides[deps.get_db] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()
    db_conn._engine, db_conn._session_factory = saved_engine, saved_factory


async def test_authenticated_user_can_create_and_view_saved_search(client, db_session):
    user = await UserRepository(db_session).create("saved@example.com", "password123")
    await db_session.commit()
    headers = {"Cookie": f"{COOKIE_NAME}={make_session_token(user.id)}"}

    response = await client.post(
        "/account/saved-searches",
        data={
            "name": "Indy dogs",
            "record_type": "lost",
            "animal_type": "dog",
            "species": "Labrador",
            "latitude": "39.7684",
            "longitude": "-86.1581",
            "radius_miles": "25",
            "days": "30",
            "min_confidence": "high",
            "csrf_token": csrf_token_for(user.id),
        },
        headers=headers,
    )

    assert response.status_code in (302, 303)
    saved = (await db_session.execute(select(SavedSearch))).scalar_one()
    assert saved.user_id == user.id
    assert saved.name == "Indy dogs"
    assert saved.species == "Labrador"
    assert saved.radius_miles == 25
    assert saved.min_confidence == "high"

    page = await client.get("/account", headers=headers)
    assert page.status_code == 200
    assert "Indy dogs" in page.text
    assert "/account/saved-searches/" + saved.id in page.text


async def test_saved_search_update_and_delete_are_owned_by_authenticated_user(client, db_session):
    user = await UserRepository(db_session).create("owner@example.com", "password123")
    outsider = await UserRepository(db_session).create("outsider@example.com", "password123")
    saved = SavedSearch(user_id=user.id, name="Original", record_type="found", days=14)
    db_session.add(saved)
    await db_session.commit()

    owner_headers = {"Cookie": f"{COOKIE_NAME}={make_session_token(user.id)}"}
    outsider_headers = {"Cookie": f"{COOKIE_NAME}={make_session_token(outsider.id)}"}
    denied = await client.post(
        f"/account/saved-searches/{saved.id}",
        data={"name": "Hacked", "record_type": "lost", "days": "7", "csrf_token": csrf_token_for(outsider.id)},
        headers=outsider_headers,
    )
    assert denied.status_code == 404

    updated = await client.post(
        f"/account/saved-searches/{saved.id}",
        data={"name": "Updated", "record_type": "lost", "animal_type": "cat", "days": "7", "csrf_token": csrf_token_for(user.id)},
        headers=owner_headers,
    )
    assert updated.status_code in (302, 303)
    await db_session.refresh(saved)
    assert saved.name == "Updated"
    assert saved.record_type == "lost"
    assert saved.animal_type == "cat"
    assert saved.days == 7

    deleted = await client.post(f"/account/saved-searches/{saved.id}/delete", data={"csrf_token": csrf_token_for(user.id)}, headers=owner_headers)
    assert deleted.status_code in (302, 303)
    assert (await db_session.execute(select(SavedSearch).where(SavedSearch.id == saved.id))).scalar_one_or_none() is None


async def test_saved_searches_require_login(client):
    response = await client.post("/account/saved-searches", data={"name": "Nope"})
    assert response.status_code in (302, 303)
    assert "/login" in response.headers["location"]


async def test_saved_search_schema_is_registered():
    assert SavedSearch.__tablename__ == "saved_searches"
    assert {"user_id", "record_type", "animal_type", "species", "latitude", "longitude", "radius_miles", "days", "min_confidence"}.issubset(SavedSearch.__table__.columns.keys())


async def test_saved_search_input_is_clamped_to_safe_ranges(client, db_session):
    user = await UserRepository(db_session).create("limits@example.com", "password123")
    await db_session.commit()
    headers = {"Cookie": f"{COOKIE_NAME}={make_session_token(user.id)}"}
    response = await client.post(
        "/account/saved-searches",
        data={"name": "Limits", "days": "9999", "radius_miles": "9999", "latitude": "95", "longitude": "-200", "csrf_token": csrf_token_for(user.id)},
        headers=headers,
    )
    assert response.status_code == 400
    assert (await db_session.execute(select(SavedSearch))).scalar_one_or_none() is None