"""
FastAPI route tests for K9-Overwatch.

Uses an in-memory SQLite database injected via FastAPI's dependency_overrides,
consistent with the db_session fixture approach in conftest.py.
"""
from __future__ import annotations

import base64
from collections.abc import AsyncGenerator
from datetime import date, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from k9overwatch.db.models import Base
from k9overwatch.web.dependencies import get_db
from k9overwatch.web.main import app

from .conftest import make_petfbi_record

# ── Per-test in-memory DB override ──────────────────────────────────────────

@pytest_asyncio.fixture
async def web_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Fresh in-memory SQLite session for web route tests.
    Tables are created before the test and dropped after.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def client(web_db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    AsyncClient bound to the FastAPI app with the DB dependency overridden
    to use the test-scoped in-memory SQLite session.
    """
    async def _override_get_db():
        yield web_db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ── Helper ───────────────────────────────────────────────────────────────────

def _basic_auth_header(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


# ── Health check ─────────────────────────────────────────────────────────────

class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_returns_200_when_db_up(self, client: AsyncClient):
        response = await client.get("/api/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["db"] == "ok"


# ── Pets list ─────────────────────────────────────────────────────────────────

class TestPetsPage:
    @pytest.mark.asyncio
    async def test_pets_page_returns_200(self, client: AsyncClient):
        response = await client.get("/pets")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        # Template renders something pet-related
        assert "pets" in response.text.lower() or "lost" in response.text.lower()

    @pytest.mark.asyncio
    async def test_pets_page_invalid_page_zero_returns_422(self, client: AsyncClient):
        response = await client.get("/pets?page=0")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_pets_page_days_exceeds_max_returns_422(self, client: AsyncClient):
        response = await client.get("/pets?days=999")
        assert response.status_code == 422


# ── Pet detail ────────────────────────────────────────────────────────────────

class TestPetDetail:
    @pytest.mark.asyncio
    async def test_pet_detail_nonexistent_returns_404(self, client: AsyncClient):
        import uuid
        fake_id = str(uuid.uuid4())
        response = await client.get(f"/pets/{fake_id}")
        assert response.status_code == 404


# ── Map GeoJSON ───────────────────────────────────────────────────────────────

class TestMapPage:
    @pytest.mark.asyncio
    async def test_map_page_has_actionable_empty_state_and_report_cta(self, client: AsyncClient):
        response = await client.get("/map")
        assert response.status_code == 200
        assert 'id="map-empty-state"' in response.text
        assert 'href="/pets"' in response.text
        assert 'href="/report"' in response.text
        assert 'id="clear-map-filters-btn"' in response.text

    @pytest.mark.asyncio
    async def test_map_page_has_filter_summary_and_clear_all_control(self, client: AsyncClient):
        response = await client.get("/map")
        assert response.status_code == 200
        assert 'id="map-filter-summary"' in response.text
        assert 'id="clear-all-map-filters-btn"' in response.text
        assert 'aria-live="polite"' in response.text


class TestMapGeoJSON:
    @pytest.mark.asyncio
    async def test_geojson_returns_feature_collection(self, client: AsyncClient):
        response = await client.get(
            "/api/map/geojson",
            params={"sw_lat": 39.0, "sw_lng": -87.0, "ne_lat": 40.5, "ne_lng": -85.5},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["type"] == "FeatureCollection"
        assert "features" in body

    @pytest.mark.asyncio
    async def test_geojson_inverted_bbox_returns_422(self, client: AsyncClient):
        # sw_lat > ne_lat — inverted bounding box
        response = await client.get(
            "/api/map/geojson",
            params={"sw_lat": 40, "ne_lat": 39, "sw_lng": -87, "ne_lng": -86},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_geojson_includes_seeded_pet_with_coords(
        self, client: AsyncClient, web_db_session: AsyncSession
    ):
        """A pet with coordinates should appear in the GeoJSON response."""
        from k9overwatch.db.repository import PetRepository
        repo = PetRepository(web_db_session)
        record = make_petfbi_record(date_event=date.today() - timedelta(days=10))  # has lat=39.8689, lon=-86.1397
        await repo.upsert(record)
        await web_db_session.commit()

        response = await client.get(
            "/api/map/geojson",
            params={"sw_lat": 39.0, "sw_lng": -87.0, "ne_lat": 40.5, "ne_lng": -85.5},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        assert len(body["features"]) >= 1


# ── Admin routes ──────────────────────────────────────────────────────────────

class TestAdminRoutes:
    @pytest.mark.asyncio
    async def test_admin_without_auth_returns_401(self, client: AsyncClient):
        response = await client.get("/admin")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_with_correct_credentials_returns_200(
        self, client: AsyncClient, monkeypatch
    ):
        monkeypatch.setenv("ADMIN_USER", "testadmin")
        monkeypatch.setenv("ADMIN_PASSWORD", "testpass")
        response = await client.get(
            "/admin",
            headers={"Authorization": _basic_auth_header("testadmin", "testpass")},
        )
        assert response.status_code == 200
