"""Feature: one-tap inbound "report via link" prefill tokens.

A signed ephemeral token (?prefill=...) carries minimal prefill JSON
{record_type, animal_type, color_primary, location_hint} into the report
form. Valid + unexpired → fields prefilled (still editable). Tampered or
expired → form renders empty, silently.
"""
from __future__ import annotations

import time

from httpx import AsyncClient

from k9overwatch.web.report_prefill import make_prefill_token, parse_prefill_token

PAYLOAD = {
    "record_type": "found",
    "animal_type": "cat",
    "color_primary": "Orange tabby",
    "location_hint": "Mass Ave & College",
}


def test_token_roundtrip():
    token = make_prefill_token(PAYLOAD)
    parsed = parse_prefill_token(token)
    assert parsed == PAYLOAD


def test_tampered_token_rejected():
    token = make_prefill_token(PAYLOAD)
    body = token.rsplit(".", 1)[0]
    forged = body[:-4] + ("AAAA" if body[-4:] != "AAAA" else "BBBB") + "." + token.rsplit(".", 1)[1]
    assert parse_prefill_token(forged) is None
    assert parse_prefill_token("garbage") is None
    assert parse_prefill_token("") is None


def test_expired_token_rejected(monkeypatch):
    monkeypatch.setenv("PREFILL_TOKEN_TTL_DAYS", "7")
    token = make_prefill_token(PAYLOAD)
    # Travel 8 days into the future.
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 8 * 24 * 3600)
    assert parse_prefill_token(token) is None


async def test_valid_token_prefills_form(client: AsyncClient, db_session):
    from k9overwatch.db.repository import UserRepository
    from k9overwatch.web.auth import COOKIE_NAME, make_session_token

    user = await UserRepository(db_session).create(email="prefill@example.com", password="pw")
    await db_session.commit()
    token = make_prefill_token(PAYLOAD)
    resp = await client.get(
        f"/report?prefill={token}",
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(user.id)}"},
    )
    assert resp.status_code == 200
    text = resp.text
    assert 'value="Orange tabby"' in text
    assert "Mass Ave &amp; College" in text or "Mass Ave & College" in text


async def test_tampered_token_renders_empty_form(client: AsyncClient, db_session):
    from k9overwatch.db.repository import UserRepository
    from k9overwatch.web.auth import COOKIE_NAME, make_session_token

    user = await UserRepository(db_session).create(email="p2@example.com", password="pw")
    await db_session.commit()
    token = make_prefill_token(PAYLOAD)[:-6] + "aaaaaa"
    resp = await client.get(
        f"/report?prefill={token}",
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(user.id)}"},
    )
    assert resp.status_code == 200
    assert 'value="Orange tabby"' not in resp.text


async def test_expired_token_renders_empty_form(client: AsyncClient, db_session, monkeypatch):
    from k9overwatch.db.repository import UserRepository
    from k9overwatch.web.auth import COOKIE_NAME, make_session_token

    user = await UserRepository(db_session).create(email="p3@example.com", password="pw")
    await db_session.commit()
    token = make_prefill_token(PAYLOAD)
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 30 * 24 * 3600)
    resp = await client.get(
        f"/report?prefill={token}",
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(user.id)}"},
    )
    assert resp.status_code == 200
    assert 'value="Orange tabby"' not in resp.text
