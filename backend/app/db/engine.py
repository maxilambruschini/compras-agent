"""Async SQLAlchemy engine + session factory — lazy initialization.

CRITICAL (REVIEWS.md HIGH fix): get_settings() is called INSIDE get_engine(),
NOT at module import time. This allows pytest's session-scoped env_setup fixture
to patch env vars before any engine is created.

Module-level singletons start as None and are initialized on first call.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_engine: AsyncEngine | None = None
_session_local: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the singleton AsyncEngine, creating it on first call (lazy).

    Calls get_settings() inside the function — never at module import time —
    so pytest env_setup fixture can patch DATABASE_URL before the engine is built.
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.debug,
            pool_pre_ping=True,
        )
    return _engine


def get_async_session_local() -> async_sessionmaker[AsyncSession]:
    """Return the singleton async_sessionmaker, creating it on first call (lazy)."""
    global _session_local
    if _session_local is None:
        _session_local = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,  # Mandatory — prevents MissingGreenlet after commit
            class_=AsyncSession,
        )
    return _session_local


def reset_engine_for_tests() -> None:
    """Reset engine and session factory singletons.

    Useful in tests that need to swap DATABASE_URL mid-suite.
    """
    global _engine, _session_local
    if _engine is not None:
        # Note: caller is responsible for disposing the engine if needed
        _engine = None
    _session_local = None
