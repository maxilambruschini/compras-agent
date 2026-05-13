# Phase 1: Foundation - Pattern Map

**Mapped:** 2026-05-13
**Files analyzed:** 11 new files (greenfield — no existing codebase analogs)
**Analogs found:** 0 / 11 internal (all patterns sourced from RESEARCH.md canonical excerpts and official documentation)

---

## File Classification

| New File | Role | Data Flow | Closest Analog | Match Quality |
|----------|------|-----------|----------------|---------------|
| `backend/app/main.py` | config/factory | request-response | RESEARCH.md Pattern 7 | canonical excerpt |
| `backend/app/config.py` | config | request-response | RESEARCH.md Pattern 4 | canonical excerpt |
| `backend/app/db/engine.py` | config | request-response | RESEARCH.md Pattern 3 | canonical excerpt |
| `backend/app/db/models.py` | model | CRUD | RESEARCH.md Pattern 5 | canonical excerpt |
| `backend/app/db/session.py` | middleware/utility | request-response | RESEARCH.md Pattern 3 | canonical excerpt |
| `backend/app/models/extraction.py` | model | transform | RESEARCH.md Pattern 6 | canonical excerpt |
| `backend/app/routers/health.py` | controller/route | request-response | RESEARCH.md Code Examples | canonical excerpt |
| `backend/alembic/env.py` | config | batch | RESEARCH.md Pattern 1 | canonical excerpt |
| `docker-compose.yml` | config | event-driven | RESEARCH.md Pattern 2 | canonical excerpt |
| `backend/Dockerfile` | config | — | RESEARCH.md Code Examples | canonical excerpt |
| `frontend/Dockerfile` | config | — | RESEARCH.md Code Examples | canonical excerpt |

---

## Pattern Assignments

### `backend/app/main.py` (config/factory, request-response)

**Source:** RESEARCH.md Pattern 7 (lines 571–609)
**Role:** FastAPI app factory + lifespan context manager

**Imports pattern:**
```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config import get_settings
import structlog
```

**Core pattern — lifespan + app factory:**
```python
log = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: validate config (raises on missing env vars)
    settings = get_settings()
    log.info("app.starting", env=settings.log_level)
    # NOTE: alembic upgrade head runs in Docker entrypoint BEFORE this lifespan
    # Do NOT re-run migrations here — leads to alembic#1483 hang
    yield
    # Shutdown: dispose async engine
    from app.db.engine import engine
    await engine.dispose()
    log.info("app.stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Compras Agent API",
        lifespan=lifespan,
        debug=settings.debug,
    )
    from app.routers.health import router as health_router
    app.include_router(health_router)
    return app


app = create_app()
```

**Critical constraints:**
- Import routers inside `create_app()` to avoid circular imports at module init time
- Never call `alembic upgrade head` in lifespan — use Docker entrypoint command instead (see RESEARCH.md anti-patterns, alembic#1483)
- `@app.on_event("startup")` is deprecated since FastAPI 0.93 — always use `lifespan=` parameter

---

### `backend/app/config.py` (config, request-response)

**Source:** RESEARCH.md Pattern 4 (lines 383–418)
**Role:** pydantic-settings BaseSettings — fail-fast env var validation (INF-03)

**Imports pattern:**
```python
from functools import lru_cache
from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict
```

**Core pattern — required fields (no default = required):**
```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Required — no default — app refuses to start if missing (INF-03)
    database_url: str           # postgresql+asyncpg://user:pass@host:5432/db
    openai_api_key: str
    whatsapp_token: str
    whatsapp_phone_number_id: str
    whatsapp_verify_token: str

    # Optional with defaults
    debug: bool = False
    log_level: str = "INFO"
    confidence_threshold: float = 0.85


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

**Critical constraints:**
- `from pydantic_settings import BaseSettings` — NOT `from pydantic import BaseSettings` (moved in Pydantic v2)
- Fields typed as `str` with no `= "default"` are REQUIRED; missing var raises `ValidationError` at import time
- `@lru_cache` on `get_settings()` ensures Settings is constructed once; use `get_settings.cache_clear()` in tests
- Never log `settings.database_url` — information disclosure risk

---

### `backend/app/db/engine.py` (config, CRUD)

**Source:** RESEARCH.md Pattern 3 (lines 330–349)
**Role:** Async engine + session factory — created once at module level

**Imports pattern:**
```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config import get_settings
```

**Core pattern:**
```python
settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,         # logs SQL in development
    pool_pre_ping=True,          # detect stale connections
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,      # prevent lazy-load errors after commit (MissingGreenlet)
    class_=AsyncSession,
)
```

**Critical constraints:**
- `expire_on_commit=False` is MANDATORY — default `True` causes `MissingGreenlet` after `await session.commit()` (RESEARCH.md Pitfall 3)
- Use `create_async_engine` not `create_engine` — sync engine cannot be used with asyncpg driver
- Use `async_sessionmaker` not `sessionmaker` — async-specific factory
- `pool_pre_ping=True` detects stale connections without extra infrastructure

---

### `backend/app/db/session.py` (utility/middleware, request-response)

**Source:** RESEARCH.md Pattern 3 (lines 352–364)
**Role:** FastAPI `Depends(get_db)` session dependency — per-request lifecycle

**Imports pattern:**
```python
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.engine import AsyncSessionLocal
```

**Core pattern:**
```python
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
```

**Usage in routes:**
```python
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db

@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    ...
```

**Critical constraints:**
- `async with AsyncSessionLocal() as session` handles `__aenter__`/`__aexit__` — the `finally: await session.close()` is a belt-and-suspenders guard
- Never open sessions outside this dependency in route handlers — leaks sessions on exceptions

---

### `backend/app/db/models.py` (model, CRUD)

**Source:** RESEARCH.md Pattern 5 (lines 422–511)
**Role:** SQLAlchemy ORM models — source of truth for Postgres schema and Alembic autogenerate

**Imports pattern:**
```python
from __future__ import annotations
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    ForeignKey, String, Text, Numeric, Date, DateTime,
    Boolean, Integer, func, Index
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
```

**Core pattern — DeclarativeBase (SQLAlchemy 2.0 style):**
```python
class Base(DeclarativeBase):
    pass


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tipo_comprobante: Mapped[Optional[str]] = mapped_column(String(50))
    numero_documento: Mapped[Optional[str]] = mapped_column(String(100))
    proveedor: Mapped[Optional[str]] = mapped_column(String(255))
    fecha: Mapped[Optional[date]] = mapped_column(Date)
    cuit_proveedor: Mapped[Optional[str]] = mapped_column(String(13))
    cae: Mapped[Optional[str]] = mapped_column(String(20))
    fecha_vencimiento_cae: Mapped[Optional[date]] = mapped_column(Date)
    confidence_score: Mapped[Optional[float]] = mapped_column(Numeric(4, 3))
    status: Mapped[str] = mapped_column(String(30), default="pending_review")
    whatsapp_message_id: Mapped[Optional[str]] = mapped_column(String(100))
    sender_phone: Mapped[Optional[str]] = mapped_column(String(30))
    image_path: Mapped[Optional[str]] = mapped_column(Text)
    raw_extraction: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    line_items: Mapped[List["InvoiceLineItem"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_invoices_numero_documento_proveedor", "numero_documento", "proveedor"),
        Index("ix_invoices_status", "status"),
        Index("ix_invoices_created_at", "created_at"),
    )


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE")
    )
    descripcion: Mapped[Optional[str]] = mapped_column(Text)
    codigo_sku: Mapped[Optional[str]] = mapped_column(String(100))
    bultos: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4))
    unidades_por_bulto: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4))
    precio_unitario_sin_iva: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4))
    descuento_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4))
    iva_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4))
    percepciones_iibb: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4))

    invoice: Mapped["Invoice"] = relationship(back_populates="line_items")


class SenderAllowlist(Base):
    __tablename__ = "sender_allowlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

**Critical constraints:**
- Use `class Base(DeclarativeBase): pass` NOT `Base = declarative_base()` — 2.0 style; `declarative_base()` is legacy
- Use `Mapped[Optional[str]]` + `mapped_column()` NOT `Column(String, nullable=True)` — enables full IDE type inference
- `from __future__ import annotations` required for forward references in `Mapped["InvoiceLineItem"]`
- This `Base` must be imported in `alembic/env.py` for autogenerate to see all tables (RESEARCH.md Pitfall 1)

---

### `backend/app/models/extraction.py` (model, transform)

**Source:** RESEARCH.md Pattern 6 (lines 513–568)
**Role:** Pydantic output contract for GPT-4o structured extraction — consumed by Phase 2 ExtractionService

**Imports pattern:**
```python
from __future__ import annotations
from decimal import Decimal
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict
```

**Core pattern — str Enum + all-Optional fields:**
```python
class TipoComprobante(str, Enum):
    """Argentine invoice document types. str Enum stores readable labels in Postgres."""
    FACTURA_A = "FACTURA_A"
    FACTURA_B = "FACTURA_B"
    FACTURA_C = "FACTURA_C"
    REMITO = "REMITO"
    LISTA_INFORMAL = "LISTA_INFORMAL"
    UNKNOWN = "UNKNOWN"    # Required fallback — GPT-4o may see unknown types


class LineItem(BaseModel):
    """Extracted line item — all fields Optional per EXT-06 (null > hallucination)."""
    model_config = ConfigDict(use_enum_values=True)

    descripcion: Optional[str] = None
    codigo_sku: Optional[str] = None
    bultos: Optional[Decimal] = None
    unidades_por_bulto: Optional[Decimal] = None
    precio_unitario_sin_iva: Optional[Decimal] = None
    descuento_pct: Optional[Decimal] = None
    iva_rate: Optional[Decimal] = None
    percepciones_iibb: Optional[Decimal] = None


class ExtractedInvoice(BaseModel):
    """Top-level extraction output contract for GPT-4o response parsing."""
    model_config = ConfigDict(use_enum_values=True)

    tipo_comprobante: Optional[TipoComprobante] = None
    numero_documento: Optional[str] = None
    proveedor: Optional[str] = None
    fecha: Optional[str] = None          # ISO 8601 string; parse to date in service layer
    cuit_proveedor: Optional[str] = None
    cae: Optional[str] = None
    fecha_vencimiento_cae: Optional[str] = None
    line_items: List[LineItem] = []
    # confidence_score is computed in Phase 2 ExtractionService, not by GPT-4o
```

**Critical constraints:**
- `TipoComprobante(str, Enum)` — MUST inherit from both `str` AND `Enum` for OpenAI Structured Outputs JSON Schema generation to work in Phase 2
- Every field MUST have `= None` explicitly — `Optional[str]` in Pydantic v2 does NOT imply a default (RESEARCH.md Pitfall 4)
- `use_enum_values=True` in `ConfigDict` ensures Pydantic serializes enum as string value, not enum object
- `UNKNOWN` enum value is required by D-08 — GPT-4o fallback for unrecognized document types

---

### `backend/app/routers/health.py` (controller/route, request-response)

**Source:** RESEARCH.md Code Examples — Walking Skeleton Health Endpoint (lines 690–710)
**Role:** GET /health — walking skeleton proof that FastAPI → AsyncSession → Postgres round-trip works

**Imports pattern:**
```python
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.db.models import SenderAllowlist
```

**Core pattern:**
```python
router = APIRouter()


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    """Walking skeleton: proves FastAPI -> AsyncSession -> Postgres round-trip works."""
    result = await db.execute(
        select(func.count()).select_from(SenderAllowlist)
    )
    count = result.scalar_one()
    return {"status": "ok", "allowlist_count": count, "db": "connected"}
```

**Critical constraints:**
- Always `async def` for route handlers — sync handlers block the event loop
- Use `select(func.count()).select_from(Model)` pattern for COUNT queries (SQLAlchemy 2.0 style)
- `result.scalar_one()` not `result.scalar()` — raises if no rows returned (zero is valid, None is a bug)
- Register in `create_app()` via `app.include_router(health_router)` in `main.py`

---

### `backend/alembic/env.py` (config, batch)

**Source:** RESEARCH.md Pattern 1 (lines 207–266) + Code Examples Alembic URL Override (lines 714–720)
**Role:** Alembic migration runner — CRITICAL async configuration, most common footgun in this stack

**Imports pattern:**
```python
import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# CRITICAL: Import ALL ORM models so autogenerate can see Base.metadata
from app.db.models import Base  # noqa: F401
```

**Core pattern — async migration wrapper:**
```python
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override alembic.ini URL with environment variable at runtime (Pitfall 6)
database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # MANDATORY: prevents connection pool interference
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())  # MANDATORY: wraps async in sync entry point


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

**Critical constraints (triple-check these):**
- `pool.NullPool` is MANDATORY — without it, async connection pools from the app engine interfere with migration scripts, causing silent hangs
- `asyncio.run(run_async_migrations())` is MANDATORY — omitting it causes `run_migrations_online()` to silently do nothing
- `from app.db.models import Base  # noqa: F401` MUST be present — without this import, `Base.metadata` is empty, autogenerate generates empty migrations (RESEARCH.md Pitfall 1)
- `config.set_main_option("sqlalchemy.url", database_url)` MUST override `alembic.ini` URL with env var (RESEARCH.md Pitfall 6)
- Source: https://alembic.sqlalchemy.org/en/latest/cookbook.html (async section)

---

### `docker-compose.yml` (config, event-driven)

**Source:** RESEARCH.md Pattern 2 (lines 277–322)
**Role:** Multi-service orchestration — Postgres, backend, frontend with correct startup ordering

**Core pattern:**
```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 5
    ports:
      - "5432:5432"

  backend:
    build: ./backend
    command: bash -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
    ports:
      - "8000:8000"
    volumes:
      - ./backend:/app    # hot-reload in dev; remove in production
    depends_on:
      postgres:
        condition: service_healthy   # CRITICAL: wait for pg_isready, not just container started
    env_file: .env
    environment:
      - DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}

  frontend:
    build: ./frontend
    command: pnpm dev --host 0.0.0.0
    ports:
      - "5173:5173"
    volumes:
      - ./frontend/src:/app/src
      - ./frontend/public:/app/public
      - /app/node_modules             # anonymous volume — prevents host node_modules overwrite

volumes:
  postgres_data:
```

**Critical constraints:**
- `condition: service_healthy` REQUIRES the `healthcheck` block on postgres — without healthcheck the condition is invalid (RESEARCH.md Pitfall 2)
- `bash -c "alembic upgrade head && uvicorn ..."` runs migrations before app start — canonical Docker entrypoint pattern
- `/app/node_modules` anonymous volume in frontend prevents host `node_modules` from shadowing container-installed packages (RESEARCH.md Pitfall 5)
- `env_file: .env` loads all vars from `.env`; the `environment:` block overrides `DATABASE_URL` with Docker's internal hostname (`postgres` service name, not `localhost`)

---

### `backend/Dockerfile` (config)

**Source:** RESEARCH.md Code Examples — Backend Dockerfile (lines 724–737)
**Role:** Backend container image — Python 3.12-slim base, pip install, copy source

**Core pattern:**
```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# CMD is overridden by docker-compose.yml command:
# bash -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Critical constraints:**
- `COPY requirements.txt .` + `RUN pip install` BEFORE `COPY . .` — Docker layer caching: deps layer only rebuilds when requirements.txt changes
- `CMD` is the fallback; `docker-compose.yml` overrides it with the migration + uvicorn chain
- `python:3.12-slim` — matches pinned Python 3.12 runtime from CLAUDE.md

---

### `frontend/Dockerfile` (config)

**Source:** RESEARCH.md Code Examples — Frontend Dockerfile (lines 740–755)
**Role:** Frontend dev container — node:22-alpine + corepack pnpm + Vite dev server

**Core pattern:**
```dockerfile
FROM node:22-alpine

RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app

COPY package.json pnpm-lock.yaml ./
RUN pnpm install

COPY . .

EXPOSE 5173
CMD ["pnpm", "dev", "--host", "0.0.0.0"]
```

**Critical constraints:**
- `corepack enable && corepack prepare pnpm@latest --activate` — installs pnpm via Node.js corepack; do NOT use `npm install -g pnpm` in Alpine (permissions issues)
- `COPY package.json pnpm-lock.yaml ./` + `RUN pnpm install` BEFORE `COPY . .` — layer cache optimization
- `CMD` is overridden by docker-compose `command: pnpm dev --host 0.0.0.0`
- The `node_modules` anonymous volume in `docker-compose.yml` prevents the host mount from overwriting the container-installed packages

---

## Shared Patterns

### Async Route Handler Pattern
**Apply to:** All files in `backend/app/routers/`
**Rule:** Every route handler MUST be `async def`. Sync handlers block the uvicorn event loop.
```python
@router.get("/path")
async def handler(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Model))
    ...
```

### SQLAlchemy 2.0 Query Style
**Apply to:** All files that query the DB (`routers/`, future `services/`)
**Rule:** Use `select()` + `await db.execute()` — NOT the legacy `db.query(Model)` ORM style.
```python
from sqlalchemy import select, func

# Correct (2.0 style):
result = await db.execute(select(SenderAllowlist).where(SenderAllowlist.is_active == True))
rows = result.scalars().all()

# Wrong (legacy, sync-only):
# db.query(SenderAllowlist).filter(...).all()
```

### Settings Access Pattern
**Apply to:** Any file that needs configuration values
**Rule:** Always call `get_settings()` — never instantiate `Settings()` directly.
```python
from app.config import get_settings

settings = get_settings()  # cached via @lru_cache
```

### Pydantic Optional Field Pattern
**Apply to:** `backend/app/models/extraction.py` and any future Pydantic models
**Rule:** In Pydantic v2, `Optional[T]` does NOT imply `default=None`. Always write `= None` explicitly.
```python
# Correct:
field_name: Optional[str] = None

# Wrong — still required in Pydantic v2:
# field_name: Optional[str]
```

### Structlog Pattern
**Apply to:** `main.py` and any module with significant logic
**Rule:** Use `structlog.get_logger()` at module level; pass context as keyword args.
```python
import structlog
log = structlog.get_logger()

log.info("event.name", key="value", other_key=123)
```

---

## No Analog Found

This is a greenfield project. No internal codebase analogs exist for any file. All patterns above are sourced from RESEARCH.md, which compiled them from official documentation (SQLAlchemy 2.0 async docs, Alembic cookbook, FastAPI settings guide, Pydantic v2 docs).

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| All 11 files | various | various | Greenfield project — no prior source files exist |

Planner MUST use the pattern excerpts above rather than searching the codebase.

---

## Test File Patterns

### `backend/tests/conftest.py` (test fixture, CRUD)

**Pattern — async test engine with SQLite+aiosqlite for isolation:**
```python
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.db.models import Base
from app.db.session import get_db
from app.main import create_app
from httpx import AsyncClient, ASGITransport

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest_asyncio.fixture
async def async_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest_asyncio.fixture
async def async_session(async_engine):
    AsyncSessionLocal = async_sessionmaker(
        async_engine, expire_on_commit=False, class_=AsyncSession
    )
    async with AsyncSessionLocal() as session:
        yield session

@pytest_asyncio.fixture
async def client(async_session):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: async_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
```

**Critical constraints:**
- `asyncio_mode = "auto"` must be set in `backend/pyproject.toml` under `[tool.pytest.ini_options]`
- Use `sqlite+aiosqlite:///:memory:` for unit/integration tests — no Postgres required in CI
- `app.dependency_overrides[get_db]` swaps the real DB session with the test session — standard FastAPI testing pattern

---

## Metadata

**Analog search scope:** No internal search conducted — greenfield project
**Files scanned:** 0 internal (2 planning docs read: 01-CONTEXT.md, 01-RESEARCH.md)
**Pattern sources:** RESEARCH.md (7 named patterns + 2 Dockerfile excerpts + 1 health endpoint + 1 conftest sketch)
**Pattern extraction date:** 2026-05-13
**Valid until:** 2026-06-13 (matches RESEARCH.md validity window)
