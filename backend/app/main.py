"""FastAPI application factory with lifespan context manager.

Pattern: RESEARCH.md Pattern 7 + 01-PATTERNS.md
- lifespan validates config on startup (raises ValidationError if env var missing — INF-03)
- Routers imported INSIDE create_app() to avoid circular imports
- Engine disposed on shutdown via lazy factory (get_engine())
- Secrets are never logged
"""
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.config import get_settings

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: validate config — raises pydantic ValidationError if any required var is missing (INF-03)
    settings = get_settings()
    log.info("app.starting", log_level=settings.log_level)
    # NOTE: alembic upgrade head runs in Docker entrypoint BEFORE this lifespan.
    # Do NOT re-run migrations here — causes indefinite hang (alembic#1483).
    yield
    # Shutdown: dispose async engine only if it was actually created (WR-01)
    from app.db.engine import _engine as _db_engine

    if _db_engine is not None:
        await _db_engine.dispose()
    log.info("app.stopped")


def create_app() -> FastAPI:
    """Application factory — import routers here to avoid circular imports."""
    settings = get_settings()
    app = FastAPI(
        title="Compras Agent API",
        lifespan=lifespan,
        debug=settings.debug,
    )

    # CORS must be registered before any include_router call
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # Import router inside factory — avoids circular import at module init time
    from app.routers.health import router as health_router

    app.include_router(health_router)

    # Admin router — always registered, no debug gate (UI-01 through UI-05)
    from app.routers.admin import router as admin_router

    app.include_router(admin_router, tags=["admin"])

    return app


app = create_app()
