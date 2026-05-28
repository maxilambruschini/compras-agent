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
    # Import router inside factory — avoids circular import at module init time
    from app.routers.health import router as health_router

    app.include_router(health_router)

    # Debug-only extraction test endpoint (D-05) — not registered in production
    if settings.debug:
        from app.routers.extraction import router as extraction_router

        app.include_router(extraction_router, prefix="/extraction", tags=["extraction"])

    # T-01-04: agent_mode is read once here at app construction and only gates which router
    # mounts — there is no runtime flip path. Default "gastos" fails closed to the intended
    # demo agent. Misconfig (unknown value) results in neither router mounting, which is safe.
    if settings.agent_mode == "invoice":
        # v1.0 invoice extraction agent — WhatsApp webhook registered only in this mode
        from app.routers.whatsapp import router as whatsapp_router

        app.include_router(whatsapp_router, prefix="/whatsapp", tags=["whatsapp"])
    elif settings.agent_mode == "gastos":
        # v2.0 Gastos Bot — conversational expense capture via WhatsApp (D-09)
        from app.routers.gastos import router as gastos_router

        app.include_router(gastos_router, prefix="/gastos", tags=["gastos"])

    return app


app = create_app()
