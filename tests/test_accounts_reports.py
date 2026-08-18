"""
Tests for the new account, report, contact, and maintenance features.

Uses httpx ASGITransport against the real app with get_db overridden to an
in-memory session, and signed-cookie auth simulated via the app's own helpers.
"""
from __future__ import annotations

import base64
import io

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.repository import PetRepository, UserRepository
from k9overwatch.web.auth import COOKIE_NAME, csrf_token_for, make_session_token
from k9overwatch.web.main import app
from k9overwatch.web.routers import reports

# Small real JPEG fixture: unlike a filename or client MIME header, these bytes
# can be decoded and validated by the upload pipeline.
VALID_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAH/AP/EABQQAQAAAAAAAAAAAAAAAAAAACD/2gAIAQEAAT8Af//EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQIBAT8Af//EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQMBAT8Af//Z"
)


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



async def test_register_login_logout_flow(client, db_session):
    # Register
    resp = await client.post(
        "/register",
        data={"email": "owner@example.com", "password": "supersecret", "display_name": "Sam", "csrf_token": csrf_token_for("anonymous")},
    )
    assert resp.status_code in (302, 303), resp.status_code
    # User + default prefs created
    users = UserRepository(db_session)
    user = await users.get_by_email("owner@example.com")
    assert user is not None
    prefs = await users.get_prefs(user.id)
    assert prefs is not None and prefs.frequency == "digest" and prefs.min_confidence == "medium"

    # Log in with right password
    resp = await client.post("/login", data={"email": "owner@example.com", "password": "supersecret", "csrf_token": csrf_token_for("anonymous")})
    assert resp.status_code in (302, 303)
    cookie = resp.cookies.get(COOKIE_NAME)
    assert cookie

    # Authenticated page shows account nav. AsyncClient persists the Set-Cookie
    # response, so no per-request cookies mapping is needed here.
    resp = await client.get("/account")
    assert resp.status_code == 200
    assert "My account" in resp.text

    # Wrong password rejected
    resp = await client.post("/login", data={"email": "owner@example.com", "password": "wrong", "csrf_token": csrf_token_for("anonymous")})
    assert resp.status_code == 401


async def test_flush_digest_requires_admin_authentication(client):
    response = await client.post("/admin/flush-digest")

    assert response.status_code == 401


async def test_report_requires_login(client, db_session):
    resp = await client.get("/report")
    assert resp.status_code in (302, 303)
    assert "/login" in str(resp.headers.get("location", ""))


def test_save_upload_rejects_content_that_only_claims_to_be_jpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "UPLOAD_DIR", str(tmp_path))

    upload = reports.UploadFile(
        filename="not-an-image.jpg", file=io.BytesIO(b"not a jpeg"), headers={"content-type": "image/jpeg"}
    )

    assert reports._save_uploads([upload]) == []
    assert list(tmp_path.iterdir()) == []


def test_save_upload_rejects_jpeg_markers_without_jpeg_structure(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "UPLOAD_DIR", str(tmp_path))

    upload = reports.UploadFile(
        filename="fake.jpg", file=io.BytesIO(b"\xff\xd8\xff\xe0\x00\x02\xff\xd9")
    )

    assert reports._save_uploads([upload]) == []
    assert list(tmp_path.iterdir()) == []


def test_save_upload_rejects_oversize_input_before_decode(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "UPLOAD_DIR", str(tmp_path))

    upload = reports.UploadFile(
        filename="too-large.jpg", file=io.BytesIO(b"x" * (reports.MAX_UPLOAD_BYTES + 1))
    )

    assert reports._save_uploads([upload]) == []
    assert list(tmp_path.iterdir()) == []


def test_save_upload_normalizes_valid_jpeg_to_safe_generated_file(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "UPLOAD_DIR", str(tmp_path))

    upload = reports.UploadFile(
        filename="../../unsafe-name.jpg", file=io.BytesIO(VALID_JPEG), headers={"content-type": "image/jpeg"}
    )

    paths = reports._save_uploads([upload])

    assert len(paths) == 1
    saved_name = paths[0].removeprefix("/uploads/")
    assert saved_name.endswith(".jpg")
    assert saved_name != "unsafe-name.jpg"
    assert (tmp_path / saved_name).is_file()


async def test_submit_report_creates_user_row_and_geocodes(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "UPLOAD_DIR", str(tmp_path))
    users = UserRepository(db_session)
    user = await users.create("reporter@example.com", "password123")
    await db_session.commit()

    files = [("files", ("dog.jpg", io.BytesIO(VALID_JPEG), "image/jpeg"))]
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
            "csrf_token": csrf_token_for(user.id),
        },
        files=files,
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(user.id)}"},
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
    assert row.photos and len(row.photos) == 1
    saved_name = row.photos[0].removeprefix("/uploads/")
    assert (tmp_path / saved_name).is_file()
    # geocoded from location_text
    assert row.lat is not None and row.lon is not None


async def test_contact_request_requires_login(client, db_session):
    repo = PetRepository(db_session)
    row, _ = await repo.upsert(__import__("k9overwatch.models.pet_record", fromlist=["PetRecord"]).PetRecord(
        source="user", source_id="contact-target", record_type="lost", animal_type="dog",
    ), owner_id="owner-id")
    await db_session.commit()

    resp = await client.post(f"/pets/{row.id}/contact", data={"message": "I may have found your dog."})

    assert resp.status_code in (302, 303)
    assert "/login" in str(resp.headers.get("location", ""))


async def test_contact_request_creates_private_handoff(client, db_session):
    users = UserRepository(db_session)
    owner = await users.create("owner@example.com", "password123", "Owner")
    requester = await users.create("finder@example.com", "password123", "Finder")
    await db_session.commit()
    repo = PetRepository(db_session)
    row, _ = await repo.upsert(__import__("k9overwatch.models.pet_record", fromlist=["PetRecord"]).PetRecord(
        source="user", source_id="contact-target-2", record_type="lost", animal_type="dog", name="Buddy",
    ), owner_id=owner.id)
    await db_session.commit()

    resp = await client.post(
        f"/pets/{row.id}/contact",
        data={"message": "I may have found Buddy near the park.", "csrf_token": csrf_token_for(requester.id)},
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(requester.id)}"},
    )

    assert resp.status_code in (302, 303)
    assert f"/pets/{row.id}" in str(resp.headers.get("location", ""))
    from k9overwatch.db.models import ContactRequest
    request_row = await db_session.get(ContactRequest, (await db_session.execute(
        __import__("sqlalchemy", fromlist=["select"]).select(ContactRequest)
    )).scalars().first().id)
    assert request_row.requester_id == requester.id
    assert request_row.recipient_id == owner.id
    assert request_row.message == "I may have found Buddy near the park."
    assert request_row.status == "open"


async def test_contact_request_rejects_duplicate_open_request(client, db_session):
    owner = await UserRepository(db_session).create("duplicate-owner@example.com", "password123")
    requester = await UserRepository(db_session).create("duplicate-requester@example.com", "password123")
    await db_session.commit()
    row, _ = await PetRepository(db_session).upsert(__import__("k9overwatch.models.pet_record", fromlist=["PetRecord"]).PetRecord(
        source="user", source_id="duplicate-target", record_type="lost", animal_type="dog",
    ), owner_id=owner.id)
    await db_session.commit()
    headers = {"Cookie": f"{COOKIE_NAME}={make_session_token(requester.id)}"}
    first = await client.post(f"/pets/{row.id}/contact", data={"message": "First message", "csrf_token": csrf_token_for(requester.id)}, headers=headers)
    second = await client.post(f"/pets/{row.id}/contact", data={"message": "Second message", "csrf_token": csrf_token_for(requester.id)}, headers=headers)

    assert first.status_code in (302, 303)
    assert second.status_code == 409
    assert "already have an open contact request" in second.text


async def test_contact_request_cannot_target_own_report(client, db_session):
    user = await UserRepository(db_session).create("self@example.com", "password123")
    await db_session.commit()
    row, _ = await PetRepository(db_session).upsert(__import__("k9overwatch.models.pet_record", fromlist=["PetRecord"]).PetRecord(
        source="user", source_id="own-target", record_type="lost", animal_type="dog",
    ), owner_id=user.id)
    await db_session.commit()

    resp = await client.post(
        f"/pets/{row.id}/contact",
        data={"message": "My own report.", "csrf_token": csrf_token_for(user.id)},
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(user.id)}"},
    )

    assert resp.status_code == 400
    assert "your own report" in resp.text


async def test_contact_request_participants_can_update_status(client, db_session):
    from k9overwatch.db.models import ContactRequest
    owner = await UserRepository(db_session).create("status-owner@example.com", "password123")
    requester = await UserRepository(db_session).create("status-requester@example.com", "password123")
    outsider = await UserRepository(db_session).create("status-outsider@example.com", "password123")
    await db_session.commit()
    row, _ = await PetRepository(db_session).upsert(__import__("k9overwatch.models.pet_record", fromlist=["PetRecord"]).PetRecord(
        source="user", source_id="status-target", record_type="lost", animal_type="dog",
    ), owner_id=owner.id)
    contact = ContactRequest(
        pet_id=row.id, requester_id=requester.id, recipient_id=owner.id, message="I found this pet."
    )
    db_session.add(contact)
    await db_session.commit()

    denied = await client.post(
        f"/contact-requests/{contact.id}/status", data={"status": "in_conversation", "csrf_token": csrf_token_for(outsider.id)},
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(outsider.id)}"},
    )
    allowed = await client.post(
        f"/contact-requests/{contact.id}/status", data={"status": "in_conversation", "csrf_token": csrf_token_for(owner.id)},
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(owner.id)}"},
    )

    assert denied.status_code == 403
    assert allowed.status_code in (302, 303)
    await db_session.refresh(contact)
    assert contact.status == "in_conversation"


async def test_pet_detail_exposes_private_contact_form(client, db_session):
    owner = await UserRepository(db_session).create("form-owner@example.com", "password123")
    await db_session.commit()
    row, _ = await PetRepository(db_session).upsert(__import__("k9overwatch.models.pet_record", fromlist=["PetRecord"]).PetRecord(
        source="user", source_id="form-target", record_type="lost", animal_type="dog",
    ), owner_id=owner.id)
    await db_session.commit()
    viewer = await UserRepository(db_session).create("form-viewer@example.com", "password123")
    await db_session.commit()

    resp = await client.get(f"/pets/{row.id}", headers={"Cookie": f"{COOKIE_NAME}={make_session_token(viewer.id)}"})

    assert resp.status_code == 200
    assert f'action="/pets/{row.id}/contact"' in resp.text
    assert "Contact the report owner securely" in resp.text


async def test_account_shows_outgoing_contact_requests(client, db_session):
    from k9overwatch.db.models import ContactRequest
    owner = await UserRepository(db_session).create("outgoing-owner@example.com", "password123", "Owner")
    requester = await UserRepository(db_session).create("outgoing-requester@example.com", "password123", "Requester")
    await db_session.commit()
    row, _ = await PetRepository(db_session).upsert(__import__("k9overwatch.models.pet_record", fromlist=["PetRecord"]).PetRecord(
        source="user", source_id="outgoing-target", record_type="lost", animal_type="dog", name="Scout",
    ), owner_id=owner.id)
    db_session.add(ContactRequest(
        pet_id=row.id, requester_id=requester.id, recipient_id=owner.id, message="I saw Scout near the trail."
    ))
    await db_session.commit()

    resp = await client.get("/account", headers={"Cookie": f"{COOKIE_NAME}={make_session_token(requester.id)}"})

    assert resp.status_code == 200
    assert "Your contact requests" in resp.text
    assert "I saw Scout near the trail." in resp.text


async def test_account_shows_contact_requests(client, db_session):
    from k9overwatch.db.models import ContactRequest
    owner = await UserRepository(db_session).create("inbox-owner@example.com", "password123")
    requester = await UserRepository(db_session).create("inbox-requester@example.com", "password123")
    await db_session.commit()
    row, _ = await PetRepository(db_session).upsert(__import__("k9overwatch.models.pet_record", fromlist=["PetRecord"]).PetRecord(
        source="user", source_id="inbox-target", record_type="lost", animal_type="dog", name="Scout",
    ), owner_id=owner.id)
    db_session.add(ContactRequest(
        pet_id=row.id, requester_id=requester.id, recipient_id=owner.id, message="I saw Scout near the trail."
    ))
    await db_session.commit()

    resp = await client.get("/account", headers={"Cookie": f"{COOKIE_NAME}={make_session_token(owner.id)}"})

    assert resp.status_code == 200
    assert "Contact requests" in resp.text
    assert "I saw Scout near the trail." in resp.text


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
    resp = await client.get(
        f"/pets/{row.id}",
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(user.id)}"},
    )
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


async def test_report_owner_can_mark_report_reunited(client, db_session):
    from k9overwatch.models.pet_record import PetRecord

    owner = await UserRepository(db_session).create("reunited@example.com", "password123")
    await db_session.commit()
    row, _ = await PetRepository(db_session).upsert(
        PetRecord(source="user", source_id="reunited-report", record_type="lost", animal_type="dog"),
        owner_id=owner.id,
    )
    row.owner_report_status = "open"
    await db_session.commit()
    response = await client.post(
        f"/reports/{row.id}/status",
        data={"status": "reunited", "csrf_token": csrf_token_for(owner.id)},
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(owner.id)}"},
    )
    assert response.status_code in (302, 303)
    await db_session.refresh(row)
    assert row.owner_report_status == "reunited"
    assert row.active is False


async def test_report_status_cannot_be_changed_by_another_user(client, db_session):
    from k9overwatch.models.pet_record import PetRecord

    owner = await UserRepository(db_session).create("status-owner-2@example.com", "password123")
    outsider = await UserRepository(db_session).create("status-outsider-2@example.com", "password123")
    await db_session.commit()
    row, _ = await PetRepository(db_session).upsert(
        PetRecord(source="user", source_id="private-status-report", record_type="lost", animal_type="dog"),
        owner_id=owner.id,
    )
    await db_session.commit()
    response = await client.post(
        f"/reports/{row.id}/status",
        data={"status": "closed", "csrf_token": csrf_token_for(outsider.id)},
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(outsider.id)}"},
    )
    assert response.status_code == 404
