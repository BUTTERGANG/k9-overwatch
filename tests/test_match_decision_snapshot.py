"""Decision-time signal snapshot on match review (roadmap C10 groundwork)."""

from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.models import PetMatch


async def _make_match(db_session: AsyncSession) -> PetMatch:
    m = PetMatch(
        pet_a_id="a", pet_b_id="b", match_type="lost_found",
        score=0.62, confidence="medium",
        signals_fired={"zip_match": 0.20, "breed_exact": 0.15},
    )
    db_session.add(m)
    await db_session.commit()
    return m


async def test_review_stores_decision_snapshot(client: httpx.AsyncClient, db_session: AsyncSession):
    """Reviewing a match records score/signals as they were at decision time."""
    m = await _make_match(db_session)

    resp = await client.post(
        f"/api/matches/{m.id}/review",
        params={"confirmed": "true"},
        auth=("admin", "changeme"),
    )
    assert resp.status_code == 200

    await db_session.refresh(m)
    snap = m.decision_snapshot
    assert snap is not None
    assert snap["confirmed"] is True
    assert snap["score"] == 0.62
    assert snap["signals_fired"] == {"zip_match": 0.20, "breed_exact": 0.15}
    assert "decided_at" in snap


async def test_snapshot_survives_rematch_signal_updates(client: httpx.AsyncClient, db_session: AsyncSession):
    """Later changes to signals_fired don't rewrite the decision-time snapshot."""
    m = await _make_match(db_session)
    await client.post(
        f"/api/matches/{m.id}/review",
        params={"confirmed": "false"},
        auth=("admin", "changeme"),
    )
    await db_session.refresh(m)
    original = dict(m.decision_snapshot)

    # Simulate a re-match pass mutating the live signals.
    m.signals_fired = {"zip_match": 0.99}
    m.score = 0.99
    await db_session.commit()
    await db_session.refresh(m)

    assert m.decision_snapshot == original
