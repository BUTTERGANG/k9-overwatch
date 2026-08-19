"""Tests for threaded contact messages, blocking, and flagging."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.models import ContactMessage, ContactRequest
from k9overwatch.db.repository import PetRepository, UserRepository
from k9overwatch.models.pet_record import PetRecord
from k9overwatch.web.auth import COOKIE_NAME, csrf_token_for, make_session_token


async def test_reply_to_contact_request(client: AsyncClient, db_session: AsyncSession):
    owner = await UserRepository(db_session).create("reply-owner@example.com", "password123", "Owner")
    requester = await UserRepository(db_session).create("reply-requester@example.com", "password123", "Requester")
    await db_session.commit()
    row, _ = await PetRepository(db_session).upsert(PetRecord(
        source="user", source_id="reply-target", record_type="lost", animal_type="dog",
    ), owner_id=owner.id)
    contact = ContactRequest(pet_id=row.id, requester_id=requester.id, recipient_id=owner.id, message="I found this pet.")
    db_session.add(contact)
    await db_session.commit()

    resp = await client.post(
        f"/contact-requests/{contact.id}/reply",
        data={"message": "Great news! Can you describe the location?", "csrf_token": csrf_token_for(owner.id)},
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(owner.id)}"},
    )
    assert resp.status_code in (302, 303)

    msgs = (await db_session.execute(
        __import__("sqlalchemy").select(ContactMessage).where(ContactMessage.contact_id == contact.id)
    )).scalars().all()
    assert len(msgs) == 1
    assert msgs[0].message == "Great news! Can you describe the location?"
    assert msgs[0].sender_id == owner.id

    await db_session.refresh(contact)
    assert contact.status == "in_conversation"


async def test_reply_requires_participation(client: AsyncClient, db_session: AsyncSession):
    owner = await UserRepository(db_session).create("reply-participation-owner@example.com", "password123")
    requester = await UserRepository(db_session).create("reply-participation-req@example.com", "password123")
    outsider = await UserRepository(db_session).create("reply-outsider@example.com", "password123")
    await db_session.commit()
    row, _ = await PetRepository(db_session).upsert(PetRecord(
        source="user", source_id="reply-participation", record_type="lost", animal_type="dog",
    ), owner_id=owner.id)
    contact = ContactRequest(pet_id=row.id, requester_id=requester.id, recipient_id=owner.id, message="Hello")
    db_session.add(contact)
    await db_session.commit()

    resp = await client.post(
        f"/contact-requests/{contact.id}/reply",
        data={"message": "Hey there", "csrf_token": csrf_token_for(outsider.id)},
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(outsider.id)}"},
    )
    assert resp.status_code == 403


async def test_block_user_on_contact(client: AsyncClient, db_session: AsyncSession):
    owner = await UserRepository(db_session).create("block-owner@example.com", "password123")
    requester = await UserRepository(db_session).create("block-requester@example.com", "password123")
    await db_session.commit()
    row, _ = await PetRepository(db_session).upsert(PetRecord(
        source="user", source_id="block-target", record_type="lost", animal_type="dog",
    ), owner_id=owner.id)
    contact = ContactRequest(pet_id=row.id, requester_id=requester.id, recipient_id=owner.id, message="Please reply")
    db_session.add(contact)
    await db_session.commit()

    resp = await client.post(
        f"/contact-requests/{contact.id}/block",
        data={"csrf_token": csrf_token_for(owner.id)},
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(owner.id)}"},
    )
    assert resp.status_code in (302, 303)

    from k9overwatch.db.models import ContactBlock
    block = await db_session.get(ContactBlock, (owner.id, requester.id))
    assert block is not None
    await db_session.refresh(contact)
    assert contact.status == "closed"


async def test_messages_partial(client: AsyncClient, db_session: AsyncSession):
    owner = await UserRepository(db_session).create("msgs-owner@example.com", "password123")
    requester = await UserRepository(db_session).create("msgs-requester@example.com", "password123")
    await db_session.commit()
    row, _ = await PetRepository(db_session).upsert(PetRecord(
        source="user", source_id="msgs-target", record_type="lost", animal_type="dog",
    ), owner_id=owner.id)
    contact = ContactRequest(pet_id=row.id, requester_id=requester.id, recipient_id=owner.id, message="Initial")
    db_session.add(contact)
    await db_session.flush()
    db_session.add(ContactMessage(contact_id=contact.id, sender_id=requester.id, message="Are you there?"))
    db_session.add(ContactMessage(contact_id=contact.id, sender_id=owner.id, message="Yes, I'm here."))
    await db_session.commit()

    resp = await client.get(
        f"/contact-requests/{contact.id}/messages",
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(owner.id)}"},
    )
    assert resp.status_code == 200
    assert "Are you there?" in resp.text
    assert "I&#39;m here" in resp.text


async def test_messages_requires_participation(client: AsyncClient, db_session: AsyncSession):
    owner = await UserRepository(db_session).create("msgs-auth-owner@example.com", "password123")
    requester = await UserRepository(db_session).create("msgs-auth-req@example.com", "password123")
    outsider = await UserRepository(db_session).create("msgs-auth-outsider@example.com", "password123")
    await db_session.commit()
    row, _ = await PetRepository(db_session).upsert(PetRecord(
        source="user", source_id="msgs-auth", record_type="lost", animal_type="dog",
    ), owner_id=owner.id)
    contact = ContactRequest(pet_id=row.id, requester_id=requester.id, recipient_id=owner.id, message="Secret")
    db_session.add(contact)
    await db_session.commit()

    resp = await client.get(
        f"/contact-requests/{contact.id}/messages",
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(outsider.id)}"},
    )
    assert resp.status_code == 403


async def test_flag_report(client: AsyncClient, db_session: AsyncSession):
    from k9overwatch.db.models import ContentReport

    reporter = await UserRepository(db_session).create("flag-report@example.com", "password123")
    await db_session.commit()
    row, _ = await PetRepository(db_session).upsert(PetRecord(
        source="user", source_id="flag-target", record_type="lost", animal_type="dog",
    ), owner_id="someone-else")
    await db_session.commit()

    resp = await client.post(
        f"/reports/{row.id}/flag",
        data={"reason": "This is a duplicate report", "csrf_token": csrf_token_for(reporter.id)},
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(reporter.id)}"},
    )
    assert resp.status_code in (302, 303)

    report = (await db_session.execute(
        __import__("sqlalchemy").select(ContentReport).where(ContentReport.target_type == "report")
    )).scalars().first()
    assert report is not None
    assert report.target_id == row.id
    assert report.reason == "This is a duplicate report"
    assert report.reporter_id == reporter.id
    assert report.status == "pending"


async def test_flag_contact_request(client: AsyncClient, db_session: AsyncSession):
    from k9overwatch.db.models import ContentReport

    owner = await UserRepository(db_session).create("flag-contact-owner@example.com", "password123")
    requester = await UserRepository(db_session).create("flag-contact-req@example.com", "password123")
    reporter = await UserRepository(db_session).create("flag-contact-reporter@example.com", "password123")
    await db_session.commit()
    row, _ = await PetRepository(db_session).upsert(PetRecord(
        source="user", source_id="flag-contact-target", record_type="lost", animal_type="dog",
    ), owner_id=owner.id)
    contact = ContactRequest(pet_id=row.id, requester_id=requester.id, recipient_id=owner.id, message="Suspicious")
    db_session.add(contact)
    await db_session.commit()

    resp = await client.post(
        f"/contact-requests/{contact.id}/flag",
        data={"reason": "Inappropriate message", "csrf_token": csrf_token_for(reporter.id)},
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(reporter.id)}"},
    )
    assert resp.status_code in (302, 303)

    report = (await db_session.execute(
        __import__("sqlalchemy").select(ContentReport).where(ContentReport.target_type == "contact_request")
    )).scalars().first()
    assert report is not None
    assert report.target_id == contact.id
    assert report.reason == "Inappropriate message"


async def test_flag_report_requires_login(client: AsyncClient, db_session: AsyncSession):
    row, _ = await PetRepository(db_session).upsert(PetRecord(
        source="user", source_id="flag-auth", record_type="lost", animal_type="dog",
    ), owner_id="someone")
    await db_session.commit()

    resp = await client.post(f"/reports/{row.id}/flag", data={"reason": "bad"})
    assert resp.status_code in (302, 303)
    assert "/login" in str(resp.headers.get("location", ""))


async def test_block_prevents_reply(client: AsyncClient, db_session: AsyncSession):
    from k9overwatch.db.models import ContactBlock

    owner = await UserRepository(db_session).create("block-reply-owner@example.com", "password123")
    requester = await UserRepository(db_session).create("block-reply-req@example.com", "password123")
    await db_session.commit()
    row, _ = await PetRepository(db_session).upsert(PetRecord(
        source="user", source_id="block-reply", record_type="lost", animal_type="dog",
    ), owner_id=owner.id)
    contact = ContactRequest(pet_id=row.id, requester_id=requester.id, recipient_id=owner.id, message="Hey")
    db_session.add(contact)
    db_session.add(ContactBlock(blocker_id=owner.id, blocked_id=requester.id))
    await db_session.commit()

    resp = await client.post(
        f"/contact-requests/{contact.id}/reply",
        data={"message": "Blocked user tries to reply", "csrf_token": csrf_token_for(requester.id)},
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(requester.id)}"},
    )
    assert resp.status_code == 403
    assert "blocked" in resp.text