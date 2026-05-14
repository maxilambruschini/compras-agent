"""pytest configuration and fixtures for the backend test suite.

- env_setup: session-scoped autouse fixture that patches required env vars before
  any test collection begins, then clears the get_settings() lru_cache so the first
  call inside any test sees the patched values. (REVIEWS.md HIGH fix: lazy engine)
- async_engine: function-scoped async SQLite+aiosqlite in-memory engine with
  Base.metadata.create_all on entry and drop_all on exit.
- db_session: function-scoped AsyncSession yielded from the test engine.
"""
import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base

# Capture real API key before env_setup patches it — used by integration tests.
_REAL_OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")


@pytest.fixture(scope="session")
def real_openai_api_key() -> str:
    """Return the OPENAI_API_KEY that was set BEFORE env_setup patched the environment.

    Integration tests must use this fixture rather than os.environ['OPENAI_API_KEY']
    to avoid receiving the test-stub value injected by env_setup.
    """
    return _REAL_OPENAI_API_KEY

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session", autouse=True)
def env_setup():
    """Patch required env vars for the entire test session.

    Uses pytest.MonkeyPatch directly (not the function-scoped monkeypatch fixture)
    so it can live at session scope. Clears the get_settings lru_cache after patching
    so engine.py's lazy factory sees the correct DATABASE_URL on first call.
    """
    mp = pytest.MonkeyPatch()
    mp.setenv("DATABASE_URL", TEST_DATABASE_URL)
    mp.setenv("OPENAI_API_KEY", "test-openai-key")
    mp.setenv("WHATSAPP_TOKEN", "test-whatsapp-token")
    mp.setenv("WHATSAPP_PHONE_NUMBER_ID", "test-phone-number-id")
    mp.setenv("WHATSAPP_VERIFY_TOKEN", "test-verify-token")
    # Phase 3: WhatsApp provider credentials
    mp.setenv("WHATSAPP_PROVIDER", "twilio")
    mp.setenv("TWILIO_ACCOUNT_SID", "test-twilio-sid")
    mp.setenv("TWILIO_AUTH_TOKEN", "test-twilio-token")
    mp.setenv("TWILIO_FROM_NUMBER", "whatsapp:+14155238886")
    # NOTE: WEBHOOK_BASE_URL is NOT set at session scope; individual tests that need it
    # must patch it via monkeypatch and call get_settings.cache_clear() before/after.

    # Clear the lru_cache so any previously cached Settings (from other imports) is evicted
    from app.config import get_settings

    get_settings.cache_clear()

    yield

    mp.undo()
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def async_engine():
    """Per-test in-memory SQLite engine with full schema created."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(async_engine):
    """Per-test AsyncSession bound to the in-memory test engine."""
    session_factory = async_sessionmaker(
        async_engine, expire_on_commit=False, class_=AsyncSession
    )
    async with session_factory() as session:
        yield session
