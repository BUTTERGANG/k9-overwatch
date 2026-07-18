"""
Tests for the new account, report, contact, and maintenance features.

Uses httpx ASGITransport against the real app with get_db overridden to an
in-memory session, and signed-cookie auth simulated via the app's own helpers.
"""
from __future__ import annotations

import io

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.repository import PetRepository, UserRepository
from k9overwatch.web.auth import COOKIE_NAME, make_session_token
from k9overwatch.web.main import app


@pytest.fixture
async def client(db_session):
    """HTTP client whose DB is the test's in-memory session.

    The app's middleware + routers resolve the DB through the module-level
    engine/factory, so we point those globals at the test engine. This keeps
    auth (middleware) and request handlers on the same in-memory database.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from k9overwatch.db import connection as db_conn

    # db_session is an open AsyncSession; reuse its engine for app-wide access.
    engine = db_session.bind
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    saved_engine = db_conn._engine
    saved_factory = db_conn._session_factory
    db_conn._engine = engine
    db_conn._session_factory = factory

    async def _override():
        async with factory() as s:
            yield s

    import k9overwatch.web.dependencies as deps

    app.dependency_overrides[deps.get_db] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    db_conn._engine = saved_engine
    db_conn._session_factory = saved_factory


def _login_headers(user_id: str) -> dict:
    return {COOKIE_NAME: make_session_token(user_id)}


async def test_register_login_logout_flow(client, db_session):
    # Register
    resp = await client.post(
        "/register",
        data={"email": "owner@example.com", "password": "supersecret", "display_name": "Sam"},
    )
    assert resp.status_code in (302, 303), resp.status_code
    # User + default prefs created
    users = UserRepository(db_session)
    user = await users.get_by_email("owner@example.com")
    assert user is not None
    prefs = await users.get_prefs(user.id)
    assert prefs is not None and prefs.frequency == "digest" and prefs.min_confidence == "medium"

    # Log in with right password
    resp = await client.post("/login", data={"email": "owner@example.com", "password": "supersecret"})
    assert resp.status_code in (302, 303)
    cookie = resp.cookies.get(COOKIE_NAME)
    assert cookie

    # Authenticated page shows account nav
    resp = await client.get("/account", cookies={COOKIE_NAME: cookie})
    assert resp.status_code == 200
    assert "My account" in resp.text

    # Wrong password rejected
    resp = await client.post("/login", data={"email": "owner@example.com", "password": "wrong"})
    assert resp.status_code == 401


async def test_report_requires_login(client, db_session):
    resp = await client.get("/report")
    assert resp.status_code in (302, 303)
    assert "/login" in str(resp.headers.get("location", ""))


async def test_submit_report_creates_user_row_and_geocodes(client, db_session):
    users = UserRepository(db_session)
    user = await users.create("reporter@example.com", "password123")
    await db_session.commit()

    files = [("files", ("dog.jpg", io.BytesIO(b"\xff\xd8\xff\xe0fakejpg"), "image/jpeg"))]
    resp = await client.post(
        "/report",
        data={
            "record_type": "lost",
            "animal_type": "dog",
            "name": "Rex",
            "breed": "Lab",
            "color_primary": "Black",
            "location_text": "Indianapolis, IN",
            "contact_name": "Pat",
            "contact_email": "pat@example.com",
        },
        files=files,
        cookies=_login_headers(user.id),
    )
    assert resp.status_code in (302, 303), resp.text

    repo = PetRepository(db_session)
    rows = await repo.get_matchable_records()
    user_rows = [r for r in rows if r.source == "user"]
    assert user_rows, "submitted report should persist as source=user"
    row = user_rows[0]
    assert row.owner_id == user.id
    assert row.name == "Rex"
    assert row.contact_email == "pat@example.com"
    # geocoded from location_text
    assert row.lat is not None and row.lon is not None


async def test_contact_info_gated_behind_login(client, db_session):
    repo = PetRepository(db_session)
    row, _ = await repo.upsert(__import__("k9overwatch.models.pet_record", fromlist=["PetRecord"]).PetRecord(
        source="user", source_id="u1", record_type="lost", animal_type="dog",
        contact_email="secret@example.com",
    ), owner_id="someone")
    await db_session.commit()

    # Anonymous: contact hidden, prompt to log in
    resp = await client.get(f"/pets/{row.id}")
    assert resp.status_code == 200
    assert "secret@example.com" not in resp.text
    assert "Log in to view" in resp.text

    # Logged in: contact revealed
    users = UserRepository(db_session)
    user = await users.create("viewer@example.com", "password123")
    await db_session.commit()
    resp = await client.get(f"/pets/{row.id}", cookies=_login_headers(user.id))
    assert "secret@example.com" in resp.text


async def test_geojson_includes_match_count(client, db_session):
    repo = PetRepository(db_session)
    a, _ = await repo.upsert(__import__("k9overwatch.models.pet_record", fromlist=["PetRecord"]).PetRecord(
        source="seed", source_id="mca", record_type="lost", animal_type="dog",
        lat=39.77, lon=-86.15, date_event=__import__("datetime").date.today(),
    ))
    b, _ = await repo.upsert(__import__("k9overwatch.models.pet_record", fromlist=["PetRecord"]).PetRecord(
        source="seed", source_id="mcb", record_type="found", animal_type="dog",
        lat=39.78, lon=-86.14, date_event=__import__("datetime").date.today(),
    ))
    await db_session.flush()
    await repo.save_match(__import__("k9overwatch.matching.signals", fromlist=["MatchResult"]).MatchResult.from_signals(
        str(a.id), str(b.id), "lost_found", {"zip_match": 0.2}
    ))
    await db_session.commit()

    resp = await client.get("/api/map/geojson", params={
        "sw_lat": 39.0, "sw_lng": -87.0, "ne_lat": 40.5, "ne_lng": -85.0, "days": 90,
    })
    assert resp.status_code == 200
    counts = {f["properties"]["id"]: f["properties"]["match_count"] for f in resp.json()["features"]}
    assert counts.get(str(a.id)) == 1


async def test_image_proxy_blocks_bad_schemes(client):
    resp = await client.get("/img", params={"url": "file:///etc/passwd"})
    assert resp.status_code == 400
    resp = await client.get("/img", params={"url": "javascript:alert(1)"})
    assert resp.status_code == 400


async def test_expire_stale_by_age(client, db_session):
    from datetime import date, timedelta

    repo = PetRepository(db_session)
    old, _ = await repo.upsert(__import__("k9overwatch.models.pet_record", fromlist=["PetRecord"]).PetRecord(
        source="seed", source_id="old1", record_type="lost", animal_type="dog",
        lat=39.77, lon=-86.15, date_event=date.today() - timedelta(days=200),
    ))
    fresh, _ = await repo.upsert(__import__("k9overwatch.models.pet_record", fromlist=["PetRecord"]).PetRecord(
        source="seed", source_id="new1", record_type="lost", animal_type="dog",
        lat=39.77, lon=-86.15, date_event=date.today(),
    ))
    await db_session.commit()

    count = await repo.deactivate_stale_by_age(max_age_days=120)
    assert count == 1
    await db_session.refresh(old)
    await db_session.refresh(fresh)
    assert old.active is False
    assert fresh.active is True
