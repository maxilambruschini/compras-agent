"""FastAPI dependency for per-request async database sessions."""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_async_session_local


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an AsyncSession for the current request.

    Calls get_async_session_local() inside the function (lazy) — never at import time.
    The async context manager handles session close on exit.
    """
    session_local = get_async_session_local()
    async with session_local() as session:
        yield session
