"""Integration tests for GET /health endpoint.

Uses httpx.AsyncClient + ASGI transport against the in-memory aiosqlite test DB.
The session-scoped autouse env_setup fixture in conftest.py patches env vars before
collection, so `from app.main import app` is safe at module-level import.
"""
import pytest
import pytest_asyncio
import httpx

from app.db.models import SenderAllowlist
from app.db.session import get_db


@pytest_asyncio.fixture
async def client(db_session):
    """Function-scoped ASGI test client wired to the test DB session."""
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_empty_allowlist(client):
    """GET /health with no rows in sender_allowlist returns allowlist_count: 0."""
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "allowlist_count": 0, "db": "connected"}


@pytest.mark.asyncio
async def test_health_with_seed(client, db_session):
    """GET /health after seeding one allowlist row returns allowlist_count: 1."""
    db_session.add(SenderAllowlist(phone_number="+5491100000000"))
    await db_session.commit()

    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["allowlist_count"] == 1
    assert body["status"] == "ok"
    assert body["db"] == "connected"
