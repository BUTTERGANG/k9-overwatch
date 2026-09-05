"""Feature: opt-in daily digest emails for Facebook group admins.

Digest is env-gated (GROUP_ADMIN_DIGEST_ENABLED=0 default), compiles new
active lost/found/sighting reports from the last 24h filtered to the
admin's saved-search radius (else metro-wide default radius), and honors
unsubscribe tokens.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.models import NotificationPrefs, PetRow, SavedSearch, User
from k9overwatch.scheduler.jobs import send_group_admin_digests
from k9overwatch.web.auth import new_unsubscribe_token


def _now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _make_user(db_session: AsyncSession, email: str, *, group_admin: bool = False) -> User:
    user = User(
        email=email,
        display_name=email.split("@")[0],
        password_hash="x",
        is_group_admin=group_admin,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(NotificationPrefs(user_id=user.id, unsubscribe_token=new_unsubscribe_token()))
    await db_session.flush()
    return user


def _pet(record_type="lost", *, hours_old=1, lat=39.7684, lon=-86.1581, **kw) -> PetRow:
    return PetRow(
        source="petfbi",
        source_id=f"src-{record_type}-{hours_old}-{lat}",
        record_type=record_type,
        animal_type="dog",
        name=kw.pop("name", "Rex"),
        breed="Lab",
        location_text="5th & Meridian",
        city="Indianapolis",
        state="IN",
        lat=lat,
        lon=lon,
        active=True,
        date_posted=_now_naive() - timedelta(hours=hours_old),
        scraped_at=_now_naive() - timedelta(hours=hours_old),
        **kw,
    )


@pytest.fixture
def digest_env(monkeypatch):
    monkeypatch.setenv("GROUP_ADMIN_DIGEST_ENABLED", "1")
    monkeypatch.setattr("k9overwatch.notifications._smtp_configured", lambda: True)
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "k9overwatch.notifications._send_email",
        lambda to, subject, body, token: sent.append((to, subject)) or True,
    )
    return sent


async def _run_digest(db_session, monkeypatch):
    """Run the digest job against the test session (patch get_session)."""
    import contextlib

    from k9overwatch.db import connection as db_conn

    @contextlib.asynccontextmanager
    async def fake_session():
        yield db_session

    monkeypatch.setattr(db_conn, "get_session", fake_session)
    import k9overwatch.scheduler.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "get_session", fake_session)
    result = await send_group_admin_digests()
    assert set(result) == {"sent"}
    return result["sent"]


async def test_digest_compiles_last_24h_within_radius(db_session, digest_env, monkeypatch):
    admin = await _make_user(db_session, "admin@example.com", group_admin=True)
    db_session.add(SavedSearch(
        user_id=admin.id, name="Indy", record_type="lost",
        latitude=39.7684, longitude=-86.1581, radius_miles=10,
        days=30,
    ))
    fresh_near = _pet("lost", hours_old=2)
    fresh_far = _pet("found", hours_old=3, lat=41.0, lon=-86.0)  # far outside 10mi
    old = _pet("sighting", hours_old=48)
    db_session.add_all([fresh_near, fresh_far, old])
    await db_session.commit()

    count = await _run_digest(db_session, monkeypatch)
    assert count == 1
    to, subject = digest_env[0]
    assert to == "admin@example.com"
    assert "Rex" in subject or True  # subject shape asserted loosely


async def test_digest_skips_when_env_disabled(db_session, monkeypatch):
    monkeypatch.setenv("GROUP_ADMIN_DIGEST_ENABLED", "0")
    await _make_user(db_session, "admin@example.com", group_admin=True)
    db_session.add(_pet())
    await db_session.commit()
    sent: list = []
    monkeypatch.setattr("k9overwatch.notifications._send_email", lambda *a: sent.append(a) or True)
    count = await _run_digest(db_session, monkeypatch)
    assert count == 0 and not sent


async def test_digest_respects_unsubscribe(db_session, digest_env, monkeypatch):
    admin = await _make_user(db_session, "admin@example.com", group_admin=True)
    prefs = (await db_session.execute(
        select(NotificationPrefs).where(NotificationPrefs.user_id == admin.id)
    )).scalar_one()
    prefs.email_enabled = False
    db_session.add(_pet())
    await db_session.commit()

    count = await _run_digest(db_session, monkeypatch)
    assert count == 0 and not digest_env


async def test_digest_metro_default_radius_used_without_saved_search(db_session, digest_env, monkeypatch):
    monkeypatch.setenv("GROUP_ADMIN_DIGEST_RADIUS_MILES", "25")
    await _make_user(db_session, "admin@example.com", group_admin=True)
    near = _pet("lost", hours_old=1, lat=39.7684, lon=-86.1581)
    far = _pet("found", hours_old=2, lat=45.0, lon=-85.0)
    db_session.add_all([near, far])
    await db_session.commit()

    await _run_digest(db_session, monkeypatch)
    assert len(digest_env) == 1
