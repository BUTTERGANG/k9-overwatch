"""Tests for ContentReport admin review flow."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.models import ContentReport, ContactRequest, PetRow
from k9overwatch.db.repository import PetRepository, UserRepository
from k9overwatch.models.pet_record import PetRecord
from k9overwatch.web.auth import COOKIE_NAME, csrf_token_for, make_session_token


async def _login_as(client: AsyncClient, user_id: str) -> None:
    """Set the session cookie for a user id."""
    client.cookies.set(COOKIE_NAME, make_session_token(user_id))


async def test_admin_reports_page(client: AsyncClient, db_session: AsyncSession):
    """GET /admin/reports returns HTML with pending reports."""
    # Create a pending report
    reporter = await UserRepository(db_session).create("admin-reports-reporter@example.com", "password123")
    row, _ = await PetRepository(db_session).upsert(PetRecord(
        source="user", source_id="admin-reports-target", record_type="lost", animal_type="dog",
    ), owner_id="someone")
    await db_session.commit()

    db_session.add(ContentReport(
        reporter_id=reporter.id,
        target_type="report",
        target_id=row.id,
        reason="Test flag for admin view",
    ))
    await db_session.commit()

    resp = await client.get("/admin/reports", auth=("admin", "changeme"))
    assert resp.status_code == 200
    assert "Test flag for admin view" in resp.text


async def test_admin_reports_requires_auth(client: AsyncClient):
    """Admin pages should reject unauthenticated requests."""
    resp = await client.get("/admin/reports")
    assert resp.status_code == 401


async def test_dismiss_report(client: AsyncClient, db_session: AsyncSession):
    """POST /admin/reports/{id}/dismiss sets status to dismissed."""
    reporter = await UserRepository(db_session).create("dismiss-reporter@example.com", "password123")
    row, _ = await PetRepository(db_session).upsert(PetRecord(
        source="user", source_id="dismiss-target", record_type="lost", animal_type="dog",
    ), owner_id="someone")
    await db_session.commit()

    report = ContentReport(reporter_id=reporter.id, target_type="report", target_id=row.id, reason="Dismiss me")
    db_session.add(report)
    await db_session.commit()

    resp = await client.post(f"/admin/reports/{report.id}/dismiss", auth=("admin", "changeme"))
    assert resp.status_code in (302, 303)

    await db_session.refresh(report)
    assert report.status == "dismissed"
    assert report.reviewed_by == "admin"


async def test_action_report_mark_reviewed(client: AsyncClient, db_session: AsyncSession):
    """POST /admin/reports/{id}/action without deactivate just marks reviewed."""
    reporter = await UserRepository(db_session).create("action-reporter@example.com", "password123")
    row, _ = await PetRepository(db_session).upsert(PetRecord(
        source="user", source_id="action-target", record_type="lost", animal_type="dog",
    ), owner_id="someone")
    await db_session.commit()

    report = ContentReport(reporter_id=reporter.id, target_type="report", target_id=row.id, reason="Action me")
    db_session.add(report)
    await db_session.commit()

    resp = await client.post(
        f"/admin/reports/{report.id}/action",
        data={"deactivate": "false"},
        auth=("admin", "changeme"),
    )
    assert resp.status_code in (302, 303)

    await db_session.refresh(report)
    assert report.status == "reviewed"
    assert report.reviewed_by == "admin"

    # Pet should still be active
    await db_session.refresh(row)
    assert row.active is True


async def test_action_report_deactivate_pet(client: AsyncClient, db_session: AsyncSession):
    """POST /admin/reports/{id}/action with deactivate sets pet inactive."""
    reporter = await UserRepository(db_session).create("deactivate-reporter@example.com", "password123")
    row, _ = await PetRepository(db_session).upsert(PetRecord(
        source="user", source_id="deactivate-target", record_type="lost", animal_type="dog",
    ), owner_id="someone")
    await db_session.commit()

    report = ContentReport(reporter_id=reporter.id, target_type="report", target_id=row.id, reason="Deactivate me")
    db_session.add(report)
    await db_session.commit()

    resp = await client.post(
        f"/admin/reports/{report.id}/action",
        data={"deactivate": "true"},
        auth=("admin", "changeme"),
    )
    assert resp.status_code in (302, 303)

    await db_session.refresh(row)
    assert row.active is False
    assert row.owner_report_status == "closed"


async def test_action_report_deactivate_contact_request(client: AsyncClient, db_session: AsyncSession):
    """POST /admin/reports/{id}/action with deactivate closes the contact request."""
    from k9overwatch.db.models import ContactRequest

    owner = await UserRepository(db_session).create("action-contact-owner@example.com", "password123")
    requester = await UserRepository(db_session).create("action-contact-req@example.com", "password123")
    reporter = await UserRepository(db_session).create("action-contact-reporter@example.com", "password123")
    await db_session.commit()

    row, _ = await PetRepository(db_session).upsert(PetRecord(
        source="user", source_id="action-contact-target", record_type="lost", animal_type="dog",
    ), owner_id=owner.id)
    contact = ContactRequest(pet_id=row.id, requester_id=requester.id, recipient_id=owner.id, message="Test")
    db_session.add(contact)
    await db_session.commit()

    report = ContentReport(
        reporter_id=reporter.id,
        target_type="contact_request",
        target_id=contact.id,
        reason="Bad contact request",
    )
    db_session.add(report)
    await db_session.commit()

    resp = await client.post(
        f"/admin/reports/{report.id}/action",
        data={"deactivate": "true"},
        auth=("admin", "changeme"),
    )
    assert resp.status_code in (302, 303)

    await db_session.refresh(contact)
    assert contact.status == "closed"


async def test_flag_report_creates_content_report(client: AsyncClient, db_session: AsyncSession):
    """POST /reports/{id}/flag creates a ContentReport with target_type report."""
    reporter = await UserRepository(db_session).create("flag2-reporter@example.com", "password123")
    await db_session.commit()
    row, _ = await PetRepository(db_session).upsert(PetRecord(
        source="user", source_id="flag2-target", record_type="lost", animal_type="dog",
    ), owner_id="someone-else")
    await db_session.commit()

    resp = await client.post(
        f"/reports/{row.id}/flag",
        data={"reason": "Duplicate content", "csrf_token": csrf_token_for(reporter.id)},
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(reporter.id)}"},
    )
    assert resp.status_code in (302, 303)

    cr = (await db_session.execute(
        __import__("sqlalchemy").select(ContentReport).where(
            ContentReport.target_type == "report",
            ContentReport.target_id == row.id,
        )
    )).scalar_one()
    assert cr.reason == "Duplicate content"
    assert cr.status == "pending"


async def test_flag_contact_request_creates_content_report(client: AsyncClient, db_session: AsyncSession):
    """POST /contact-requests/{id}/flag creates a ContentReport."""
    from k9overwatch.db.models import ContactRequest

    owner = await UserRepository(db_session).create("flag3-owner@example.com", "password123")
    requester = await UserRepository(db_session).create("flag3-req@example.com", "password123")
    reporter = await UserRepository(db_session).create("flag3-reporter@example.com", "password123")
    await db_session.commit()

    row, _ = await PetRepository(db_session).upsert(PetRecord(
        source="user", source_id="flag3-target", record_type="lost", animal_type="dog",
    ), owner_id=owner.id)
    contact = ContactRequest(pet_id=row.id, requester_id=requester.id, recipient_id=owner.id, message="Flag test")
    db_session.add(contact)
    await db_session.commit()

    resp = await client.post(
        f"/contact-requests/{contact.id}/flag",
        data={"reason": "Spam", "csrf_token": csrf_token_for(reporter.id)},
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(reporter.id)}"},
    )
    assert resp.status_code in (302, 303)

    cr = (await db_session.execute(
        __import__("sqlalchemy").select(ContentReport).where(
            ContentReport.target_type == "contact_request",
            ContentReport.target_id == contact.id,
        )
    )).scalar_one()
    assert cr.reason == "Spam"
    assert cr.status == "pending"