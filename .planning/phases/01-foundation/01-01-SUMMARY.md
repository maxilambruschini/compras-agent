---
phase: 01-foundation
plan: "01"
subsystem: backend-data-contract
tags:
  - foundation
  - sqlalchemy
  - alembic
  - pydantic
  - python
dependency_graph:
  requires: []
  provides:
    - backend/app/config.py (Settings, get_settings)
    - backend/app/db/models.py (Base, Invoice, InvoiceLineItem, SenderAllowlist)
    - backend/app/db/engine.py (get_engine, get_async_session_local)
    - backend/app/db/session.py (get_db)
    - backend/app/models/extraction.py (TipoComprobante, LineItem, ExtractedInvoice)
    - backend/alembic/versions/0cd640399c29_initial_schema.py (Postgres DDL migration)
  affects:
    - Plan 02 (docker-compose + FastAPI wiring depends on these contracts)
    - Plan 03 (WhatsApp webhook writes to Invoice + InvoiceLineItem)
    - Plan 04 (frontend reads from same schema via API)
tech_stack:
  added:
    - fastapi==0.136.1
    - uvicorn==0.38.0
    - pydantic==2.13.4
    - pydantic-settings==2.14.1
    - sqlalchemy==2.0.49
    - asyncpg==0.31.0
    - alembic==1.18.4
    - structlog==25.5.0
    - python-dotenv==1.2.2
    - openai==2.36.0
    - pytest (dev)
    - pytest-asyncio (dev)
    - aiosqlite (dev)
    - httpx (dev)
  patterns:
    - pydantic-settings BaseSettings with required fields (no defaults) for fail-fast env validation
    - SQLAlchemy 2.0 DeclarativeBase + Mapped + mapped_column typed style
    - dialect-agnostic sqlalchemy.Uuid for UUID columns (works on asyncpg + aiosqlite)
    - Lazy async engine factory (get_settings() called inside function, not at module import)
    - Alembic async env.py with asyncio.run + pool.NullPool + DATABASE_URL env override
    - Session-scoped autouse pytest fixture for env var patching + lru_cache clear
key_files:
  created:
    - backend/requirements.txt
    - backend/requirements-dev.txt
    - backend/pyproject.toml
    - backend/app/__init__.py
    - backend/app/config.py
    - backend/app/db/__init__.py
    - backend/app/db/models.py
    - backend/app/db/engine.py
    - backend/app/db/session.py
    - backend/app/models/__init__.py
    - backend/app/models/extraction.py
    - backend/app/routers/__init__.py
    - backend/app/services/__init__.py
    - backend/alembic.ini
    - backend/alembic/env.py
    - backend/alembic/script.py.mako
    - backend/alembic/versions/.gitkeep
    - backend/alembic/versions/0cd640399c29_initial_schema.py
    - backend/tests/__init__.py
    - backend/tests/conftest.py
    - backend/tests/test_config.py
    - backend/tests/test_extraction_models.py
    - backend/tests/test_db.py
    - .env.example
    - .gitignore
  modified: []
decisions:
  - "Used sqlalchemy.Uuid (dialect-agnostic) instead of sqlalchemy.dialects.postgresql.UUID — enables aiosqlite tests without special handling (REVIEWS.md MEDIUM fix)"
  - "Lazy engine factory pattern in engine.py — get_settings() called inside get_engine(), not at module import, so pytest env_setup fixture patches env vars before any engine is created (REVIEWS.md HIGH fix)"
  - "Session-scoped autouse env_setup fixture in conftest.py uses pytest.MonkeyPatch() directly (not function-scoped monkeypatch) to allow session scope + get_settings.cache_clear() (REVIEWS.md HIGH fix)"
  - "Minimal models.py stub in Task 1 (Base + SenderAllowlist only) allows conftest.py to import without ModuleNotFoundError during Task 1 collection; Task 2 replaces stub with full schema (REVIEWS.md HIGH fix)"
  - "Alembic autogenerate run against real Postgres 16 container (not SQLite) to produce correct DDL types: sa.Uuid, sa.Numeric, sa.DateTime(timezone=True) (REVIEWS.md MEDIUM fix)"
  - "requirements-dev.txt separated from requirements.txt to keep production image lean (REVIEWS.md LOW suggestion)"
metrics:
  duration: "~70 minutes"
  completed_date: "2026-05-13"
  tasks_completed: 2
  tests_passing: 9
  files_created: 25
---

# Phase 1 Plan 01: Data Contract Summary

Establishes the data contract for Compras Agent: Pydantic settings with fail-fast validation, SQLAlchemy ORM schema, Pydantic extraction models, Alembic async migration scaffold, and a passing Wave 0 pytest suite covering INF-01 (sender allowlist CRUD) and INF-03 (env var fail-fast).

## What Was Built

### Task 1: Backend skeleton, Settings, extraction models, models stub, Wave 0 tests (commit dde087e)

Backend Python package skeleton at `backend/app/` per D-02 layout. Pinned production dependencies in `requirements.txt` and test-only deps in `requirements-dev.txt` (keeps Docker image lean). `pyproject.toml` with `asyncio_mode = "auto"`.

`app/config.py`: `Settings(BaseSettings)` with 5 required fields and no defaults — `ValidationError` is raised on startup if any is absent (INF-03). `@lru_cache get_settings()` ensures single instantiation.

`app/models/extraction.py`: `TipoComprobante(str, Enum)` with `FACTURA_A/B/C`, `REMITO`, `LISTA_INFORMAL`, `UNKNOWN` per D-08. `LineItem` and `ExtractedInvoice` Pydantic models — every field `Optional[T] = None` per EXT-06 requirement. `use_enum_values=True` on both models for OpenAI Structured Outputs Phase 2 compatibility.

`app/db/models.py` (stub): minimal `Base` + `SenderAllowlist` so conftest.py can `from app.db.models import Base` without `ModuleNotFoundError` during Task 1 pytest collection (REVIEWS.md HIGH fix).

`tests/conftest.py`: session-scoped autouse `env_setup` fixture patches all 5 required env vars and calls `get_settings.cache_clear()` so the lazy engine factory sees correct values on first call.

5 tests passing: `test_missing_env_raises`, `test_settings_load`, `test_all_optional`, `test_unknown_enum`, `test_line_item_optional`.

### Task 2: Full ORM schema, lazy engine, session, Alembic, Postgres DDL migration (commit 81ed8f9)

`app/db/models.py` (full): `Invoice`, `InvoiceLineItem`, `SenderAllowlist` using SQLAlchemy 2.0 typed mapping. **Uses `sqlalchemy.Uuid` (dialect-agnostic)** not `sqlalchemy.dialects.postgresql.UUID` — this is the critical fix enabling aiosqlite test backend without `InterfaceError` on UUID binding. `Invoice` has all AFIP document header columns, processing metadata, timestamps with `server_default=func.now()`, and a `line_items` relationship with `cascade="all, delete-orphan"`. Three indexes on `invoices`. `SenderAllowlist` satisfies INF-01.

`app/db/engine.py`: **lazy singleton pattern** — `_engine = None` at module level, initialized on first `get_engine()` call inside the function. `get_settings()` is called inside the function, never at module import time. This allows pytest's session-scoped `env_setup` fixture to set `DATABASE_URL` before any engine is created (REVIEWS.md HIGH fix). `expire_on_commit=False` mandatory to prevent `MissingGreenlet` errors.

`app/db/session.py`: `get_db()` async generator using lazy `get_async_session_local()`.

`alembic/env.py`: fully async — `asyncio.run()` wrapping, `pool.NullPool`, `from app.db.models import Base` import before `target_metadata`, `os.environ.get("DATABASE_URL")` override. All RESEARCH.md Pattern 1 critical requirements applied.

`alembic/versions/0cd640399c29_initial_schema.py`: migration generated against a real Postgres 16 Alpine container (not SQLite). Uses `sa.Uuid()`, `sa.Numeric(precision=..., scale=...)`, `sa.DateTime(timezone=True)` — correct Postgres DDL, not SQLite CHAR/REAL fallbacks. Creates all 3 tables with correct foreign keys, unique constraints, and indexes.

4 new tests: `test_allowlist_table_exists`, `test_allowlist_crud`, `test_invoice_relationship`, `test_all_three_tables_in_metadata`. 9 total tests passing.

## Deviations from Plan

### Auto-fixed Issues

None — all REVIEWS.md concerns were pre-addressed in the plan's action items:
- **REVIEWS.md HIGH: conftest import ordering** — Addressed by shipping models stub in Task 1
- **REVIEWS.md HIGH: module-level get_settings() in engine.py** — Addressed by lazy factory pattern
- **REVIEWS.md MEDIUM: postgresql.UUID incompatible with aiosqlite** — Addressed by using sqlalchemy.Uuid
- **REVIEWS.md MEDIUM: Alembic autogenerate against SQLite** — Addressed by using throwaway Postgres container
- **REVIEWS.md LOW: requirements-dev.txt split** — Addressed with separate dev requirements file

### Grep Criterion Note

The acceptance criterion `grep -c "from sqlalchemy import.*Uuid"` returns 0 for a multi-line import block. The import is correctly written as a parenthesized multi-line `from sqlalchemy import (... Uuid ...)` — `Uuid` appears 4 times in the file (import + 3 usages). No `from sqlalchemy.dialects.postgresql import UUID` exists. The criterion is a false negative for multi-line imports; the code is correct.

## Known Stubs

None — all contracts are fully implemented. The Task 1 `models.py` stub was replaced in Task 2 with the full schema.

## Threat Flags

No new security surface beyond the plan's threat model. All T-01-xx threats addressed:
- T-01-01: Settings required fields + `.env` in `.gitignore` + `.env.example` with placeholders only
- T-01-02: No secret-bearing log statements in any file
- T-01-03: All DB operations use ORM parameterized queries
- T-01-04: `pool.NullPool` in `env.py` prevents migration hang
- T-01-07: Session-scoped autouse env_setup + cache_clear ensures lazy engine sees correct URL

## Self-Check: PASSED

All 15 required files found. Both task commits (dde087e, 81ed8f9) verified in git log. 9 tests passing.
