"""Admin direct content hardening: edit/deactivate owner reports (roadmap A2)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.models import PetRow
from k9overwatch.db.repository import PetRepository
from k9overwatch.models.enums import AnimalType, RecordType
from k9overwatch.models.pet_record import PetRecord


async def _owner_report(db_session: AsyncSession) -> PetRow:
    row, _ = await PetRepository(db_session).upsert(PetRecord(
        source="user", source_id="hardening-1",
        record_type=RecordType.LOST, animal_type=AnimalType.DOG,
        name="Rex", description="friendly pup", contact_email="owner@example.com",
    ), owner_id="someone")
    await db_session.commit()
    return row


async def test_admin_deactivate_owner_report(client: AsyncClient, db_session: AsyncSession):
    """POST /admin/pets/{id}/deactivate hides the report and closes its lifecycle."""
    row = await _owner_report(db_session)

    resp = await client.post(f"/admin/pets/{row.id}/deactivate", auth=("admin", "changeme"))
    assert resp.status_code in (302, 303)

    await db_session.refresh(row)
    assert row.active is False
    assert row.owner_report_status == "closed"


async def test_admin_edit_owner_report(client: AsyncClient, db_session: AsyncSession):
    """POST /admin/pets/{id}/edit updates only the supplied fields."""
    row = await _owner_report(db_session)

    resp = await client.post(
        f"/admin/pets/{row.id}/edit",
        data={"description": "edited by moderator", "name": "Rex Jr."},
        auth=("admin", "changeme"),
    )
    assert resp.status_code in (302, 303)

    await db_session.refresh(row)
    assert row.description == "edited by moderator"
    assert row.name == "Rex Jr."
    # Unsupplied fields untouched.
    assert row.contact_email == "owner@example.com"
    # Report stays active after a plain content edit.
    assert row.active is True


async def test_admin_endpoints_require_auth(client: AsyncClient, db_session: AsyncSession):
    row = await _owner_report(db_session)
    assert (await client.post(f"/admin/pets/{row.id}/deactivate")).status_code == 401
    assert (await client.post(f"/admin/pets/{row.id}/edit", data={"name": "x"})).status_code == 401


async def test_admin_deactivate_unknown_pet_404(client: AsyncClient):
    resp = await client.post("/admin/pets/nonexistent/deactivate", auth=("admin", "changeme"))
    assert resp.status_code == 404


@pytest.mark.parametrize("path", ["/admin/pets/{id}/deactivate"])
async def test_csrf_rejected_without_token(client: AsyncClient, db_session: AsyncSession, path):
    """Cookie-authenticated POSTs without CSRF token are rejected by middleware."""
    from k9overwatch.web.auth import COOKIE_NAME, make_session_token

    row = await _owner_report(db_session)
    client.cookies.set(COOKIE_NAME, make_session_token("someuser"))
    resp = await client.post(path.format(id=row.id))
    assert resp.status_code == 403
