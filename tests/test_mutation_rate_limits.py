"""Rate limiting on unauthenticated-abusable mutation endpoints (roadmap D13).

Flags are limited to 10/hour; replies/status/block get a moderate 30/hour
window. The limiter is keyed by client IP + route name, so a single test client
hammering an endpoint should see HTTP 429 once the window budget is spent.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.models import ContactRequest
from k9overwatch.db.repository import PetRepository, UserRepository
from k9overwatch.models.pet_record import PetRecord
from k9overwatch.web.auth import COOKIE_NAME, csrf_token_for, make_session_token


async def _make_user(db: AsyncSession, email: str):
    user = await UserRepository(db).create(email, "password123")
    await db.commit()
    return user


def _auth_headers(user_id: str) -> dict[str, str]:
    return {"Cookie": f"{COOKIE_NAME}={make_session_token(user_id)}"}


@pytest.mark.parametrize(
    ("path_factory", "data"),
    [
        pytest.param(
            lambda ids: f"/reports/{ids['pet'].id}/flag",
            {"reason": "spam spam spam"},
            id="report-flag",
        ),
        pytest.param(
            lambda ids: f"/contact-requests/{ids['contact'].id}/flag",
            {"reason": "harassment"},
            id="contact-flag",
        ),
    ],
)
async def test_flag_endpoints_rate_limited_at_10_per_hour(
    client: AsyncClient,
    db_session: AsyncSession,
    path_factory,
    data,
):
    reporter = await _make_user(db_session, "ratelimit-reporter@example.com")
    owner = await _make_user(db_session, "ratelimit-owner@example.com")
    requester = await _make_user(db_session, "ratelimit-requester@example.com")
    row, _ = await PetRepository(db_session).upsert(PetRecord(
        source="user", source_id="rl-target", record_type="lost", animal_type="dog",
    ), owner_id=owner.id)
    contact = ContactRequest(
        pet_id=row.id, requester_id=requester.id, recipient_id=owner.id, message="hi",
    )
    db_session.add(contact)
    await db_session.commit()
    ids = {"pet": row, "contact": contact}
    token = csrf_token_for(reporter.id)
    headers = _auth_headers(reporter.id)
    path = path_factory(ids)

    statuses = []
    for _ in range(11):
        resp = await client.post(
            path,
            data={**data, "csrf_token": token},
            headers=headers,
        )
        statuses.append(resp.status_code)
    assert 429 in statuses, f"expected a 429 among {statuses}"
    # Once limited, stays limited.
    assert (await client.post(path, data={**data, "csrf_token": token}, headers=headers)).status_code == 429


@pytest.mark.parametrize(
    ("path_suffix", "data"),
    [
        pytest.param("reply", {"message": "still interested?"}, id="contact-reply"),
        pytest.param("status", {"status": "in_conversation"}, id="contact-status"),
        pytest.param("block", {}, id="contact-block"),
    ],
)
async def test_contact_mutation_endpoints_rate_limited(
    client: AsyncClient,
    db_session: AsyncSession,
    path_suffix: str,
    data: dict,
):
    owner = await _make_user(db_session, "rl-contact-owner@example.com")
    requester = await _make_user(db_session, "rl-contact-requester@example.com")
    row, _ = await PetRepository(db_session).upsert(PetRecord(
        source="user", source_id="rl-contact-target", record_type="lost", animal_type="dog",
    ), owner_id=owner.id)
    contact = ContactRequest(
        pet_id=row.id, requester_id=requester.id, recipient_id=owner.id, message="hi",
    )
    db_session.add(contact)
    await db_session.commit()

    token = csrf_token_for(requester.id)
    headers = _auth_headers(requester.id)

    statuses = []
    for _ in range(35):
        resp = await client.post(
            f"/contact-requests/{contact.id}/{path_suffix}",
            data={**data, "csrf_token": token},
            headers=headers,
        )
        statuses.append(resp.status_code)
        if resp.status_code == 429:
            break
    assert 429 in statuses, f"expected a 429 among {statuses}"
