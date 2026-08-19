from __future__ import annotations

import base64
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from k9overwatch.web.dependencies import get_db
from k9overwatch.web.main import app


def _basic_auth_header(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_flush_digest_requires_admin_basic_auth(client: AsyncClient, monkeypatch):
    async def fake_flush_digest():
        return 0

    monkeypatch.setattr("k9overwatch.web.routers.accounts.flush_digest", fake_flush_digest)
    monkeypatch.setenv("ADMIN_USER", "testadmin")
    monkeypatch.setenv("ADMIN_PASSWORD", "testpass")

    unauthorized = await client.post("/admin/flush-digest")
    assert unauthorized.status_code == 401

    authorized = await client.post(
        "/admin/flush-digest",
        headers={"Authorization": _basic_auth_header("testadmin", "testpass")},
    )
    assert authorized.status_code == 200
    assert authorized.json() == {"sent": 0}
