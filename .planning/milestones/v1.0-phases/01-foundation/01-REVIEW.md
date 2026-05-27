---
phase: 01-foundation
reviewed: 2026-05-13T17:32:00Z
depth: standard
files_reviewed: 19
files_reviewed_list:
  - backend/app/config.py
  - backend/app/db/engine.py
  - backend/app/db/models.py
  - backend/app/db/session.py
  - backend/app/main.py
  - backend/app/models/extraction.py
  - backend/app/routers/health.py
  - backend/alembic/env.py
  - backend/alembic/versions/0cd640399c29_initial_schema.py
  - backend/tests/conftest.py
  - backend/tests/test_config.py
  - backend/tests/test_db.py
  - backend/tests/test_extraction_models.py
  - backend/tests/test_health.py
  - backend/requirements.txt
  - backend/requirements-dev.txt
  - backend/pyproject.toml
  - docker-compose.yml
  - frontend/vite.config.ts
findings:
  critical: 3
  warning: 5
  info: 3
  total: 11
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-05-13T17:32:00Z
**Depth:** standard
**Files Reviewed:** 19
**Status:** issues_found

## Summary

Phase 1 establishes the foundation layer: settings, async SQLAlchemy engine/session, ORM models, a walking-skeleton health endpoint, Alembic migrations, and a test suite. The overall architecture is sound and follows documented patterns. However, three blockers are present: the engine singleton is not thread/task safe under concurrent startup (race condition on the global), the `/health` endpoint is publicly accessible with no authentication or rate limiting, and the Alembic `env.py` silently falls back to the `alembic.ini` URL when `DATABASE_URL` is unset rather than failing loudly — meaning migrations could run against the wrong database. Five warnings cover engine disposal safety, a missing `updated_at` trigger in the migration, SQLite/Postgres behavioral divergence in tests, missing `pytest.mark.asyncio` decorators on async test functions in `test_db.py`, and `--reload` in the production Docker command.

---

## Critical Issues

### CR-01: Race Condition in Engine Singleton Initialization

**File:** `backend/app/db/engine.py:19-33`

**Issue:** `get_engine()` and `get_async_session_local()` use a module-level global with an `if _engine is None` check but provide no lock. Under concurrent async startup (multiple coroutines, or a thread pool hitting the function simultaneously before the first call completes), two callers can both observe `_engine is None`, both call `create_async_engine`, and one of the two engines is immediately orphaned — leaking its connection pool permanently with no path to disposal. In FastAPI's lifespan, `get_engine()` is also called in the shutdown handler, which would dispose whichever singleton was last written, leaving the leaked pool open.

**Fix:**
```python
import asyncio
import threading

_engine_lock = threading.Lock()

def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:  # double-checked locking
                settings = get_settings()
                _engine = create_async_engine(
                    settings.database_url,
                    echo=settings.debug,
                    pool_pre_ping=True,
                )
    return _engine
```
Apply the same pattern to `get_async_session_local()`. Alternatively, initialize both eagerly inside the FastAPI `lifespan` startup block where single-threaded execution is guaranteed.

---

### CR-02: `/health` Endpoint Exposes Database State Without Authentication

**File:** `backend/app/routers/health.py:12-19`

**Issue:** `GET /health` returns `allowlist_count` — the exact number of whitelisted sender phone numbers in the database — with no authentication, no rate limiting, and no IP restriction. This is not a liveness probe returning `{"status": "ok"}`; it is a data-bearing query result served publicly. An attacker can poll this endpoint to detect when new phone numbers are enrolled without any credentials. The endpoint also hits the database on every call, making it a free denial-of-service vector against the connection pool.

**Fix:** Split the endpoint into two:
1. A truly public liveness probe that returns `{"status": "ok"}` with no DB query.
2. An authenticated readiness probe (behind a header token or internal-only route) that includes `allowlist_count`.

At minimum, remove `allowlist_count` from the unauthenticated response:
```python
@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    await db.execute(select(func.count()).select_from(SenderAllowlist))
    return {"status": "ok", "db": "connected"}
```

---

### CR-03: Alembic `env.py` Silently Falls Back to `alembic.ini` URL When `DATABASE_URL` Is Unset

**File:** `backend/alembic/env.py:29-31`

**Issue:** The `DATABASE_URL` override is guarded by `if database_url:`. If `DATABASE_URL` is absent from the environment, Alembic silently uses whatever URL is in `alembic.ini`. If `alembic.ini` contains a placeholder or a development URL, migrations will run against the wrong database without any error. For a system that includes an Argentine compliance requirement and audit trail, a silent migration against the wrong target is a data-integrity risk (running `upgrade head` on the wrong Postgres instance could corrupt or wipe production data).

**Fix:** Fail loudly when the URL is missing rather than falling back:
```python
database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL environment variable is required to run migrations. "
        "Set it before invoking alembic."
    )
config.set_main_option("sqlalchemy.url", database_url)
```
The offline mode path (`run_migrations_offline`) also reads `config.get_main_option("sqlalchemy.url")` which would then correctly receive the validated value.

---

## Warnings

### WR-01: Engine Disposal in Lifespan Silently Skips If Engine Was Never Created

**File:** `backend/app/main.py:28-31`

**Issue:** The shutdown block calls `get_engine()` unconditionally. If startup failed after `get_settings()` but before the engine was initialized (e.g., a downstream import error), `get_engine()` will now create a brand-new engine at shutdown time and immediately dispose it — wasting a connection pool initialization only to tear it down. More importantly, if the real engine was never created, calling `get_engine()` in shutdown creates a new one; this is not harmful but is a logic error that masks whether a real engine was running.

**Fix:** Check the module-level sentinel before disposal:
```python
from app.db.engine import _engine as _db_engine
if _db_engine is not None:
    await _db_engine.dispose()
```
Or expose a `dispose_engine()` helper in `engine.py` that is a no-op when `_engine is None`.

---

### WR-02: `updated_at` Column Has No Database-Level Trigger in Migration

**File:** `backend/alembic/versions/0cd640399c29_initial_schema.py:38-40`

**Issue:** The `invoices.updated_at` column is created with `server_default=sa.text('now()')` but has no `ON UPDATE` trigger in the migration SQL. The SQLAlchemy ORM model specifies `onupdate=func.now()`, which SQLAlchemy honors when updates go through the ORM session. However, direct SQL updates (e.g., from Alembic data migrations, admin scripts, or a future service that bypasses the ORM) will not update `updated_at`. This means the audit timestamp will be stale for any non-ORM write path, silently producing incorrect audit records — a compliance concern given Argentine invoice retention requirements.

**Fix:** Add a Postgres trigger in the migration's `upgrade()`:
```python
op.execute("""
    CREATE OR REPLACE FUNCTION update_updated_at_column()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.updated_at = NOW();
        RETURN NEW;
    END;
    $$ language 'plpgsql';

    CREATE TRIGGER invoices_updated_at
        BEFORE UPDATE ON invoices
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
""")
```
And drop it in `downgrade()`.

---

### WR-03: Async Test Functions in `test_db.py` Missing `@pytest.mark.asyncio`

**File:** `backend/tests/test_db.py:23,40`

**Issue:** `test_allowlist_crud` and `test_invoice_relationship` are `async def` functions but lack `@pytest.mark.asyncio` decorators. `pyproject.toml` sets `asyncio_mode = "auto"`, which causes pytest-asyncio to auto-collect async tests — but this behavior changed across pytest-asyncio versions: in some releases `auto` mode only applies within modules that opt in, and the mode was deprecated in favor of explicit marking in newer 0.23+ versions. The test suite currently passes, but pinning `pytest-asyncio` without a version in `requirements-dev.txt` means a future `pip install` could bring in a version where these tests silently become no-ops (passing vacuously without actually running) instead of failing.

**Fix:** Add `@pytest.mark.asyncio` to both functions, and pin `pytest-asyncio` to a specific version in `requirements-dev.txt`:
```
pytest-asyncio==0.23.8
```

---

### WR-04: SQLite Test Backend Diverges from Postgres on UUID and Numeric Behavior

**File:** `backend/tests/conftest.py:16,48-54`

**Issue:** Tests use `sqlite+aiosqlite:///:memory:` with `sqlalchemy.Uuid` mapped columns. SQLite stores UUIDs as `BLOB` or `VARCHAR` depending on dialect negotiation, while Postgres uses a native `uuid` type. The `Numeric(4,3)` precision for `confidence_score` is also dialect-dependent: SQLite silently accepts out-of-range values (e.g., `1.500` for a `Numeric(4,3)` field whose max is `9.999`) that Postgres would reject with a constraint violation. Tests that insert `confidence_score` values without checking boundary enforcement will pass on SQLite and fail in production.

**Fix:** Either add a `CHECK` constraint in the ORM model to enforce `confidence_score` bounds at the application layer (independent of dialect), or add a test that explicitly verifies an out-of-range `confidence_score` raises an error — using the real Postgres container via `docker compose` in a separate integration test suite.

---

### WR-05: `--reload` Flag in Production Docker Command

**File:** `docker-compose.yml:20`

**Issue:** The backend command is `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`. The `--reload` flag is a development-only feature that watches the filesystem for changes and restarts the process. In production this has two problems: (1) it forks a reloader subprocess that monitors `./backend:/app` (the volume mount), making the container consume extra CPU scanning inotify events, and (2) any accidental file write inside the container (log rotation, temp files) can trigger an unexpected restart mid-request, dropping in-flight invoice processing.

**Fix:** Remove `--reload` from the production command. Use a separate `docker-compose.override.yml` for local development that adds `--reload` back:
```yaml
# docker-compose.yml (production)
command: bash -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"

# docker-compose.override.yml (local dev only)
command: bash -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
```

---

## Info

### IN-01: `reset_engine_for_tests()` Leaks the Old Engine If Not Disposed by Caller

**File:** `backend/app/db/engine.py:48-57`

**Issue:** `reset_engine_for_tests()` sets `_engine = None` without disposing it, delegating disposal to "the caller." No caller in the test suite currently calls `await engine.dispose()` before `reset_engine_for_tests()`. If the function is ever called during a test run where an engine was created (not the current test flow, but possible if integration tests are added), the old engine's connection pool will leak for the session. The comment says "caller is responsible" but no test enforces this contract.

**Fix:** Expose a coroutine version that disposes before clearing, and remove the footgun:
```python
async def reset_engine_for_tests() -> None:
    global _engine, _session_local
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    _session_local = None
```

---

### IN-02: `confidence_score` Precision `Numeric(4, 3)` Cannot Represent Score of `1.0`

**File:** `backend/app/db/models.py:49`, `backend/alembic/versions/0cd640399c29_initial_schema.py:33`

**Issue:** `Numeric(4, 3)` allows a maximum of 4 total digits with 3 after the decimal, meaning the maximum storable value is `9.999`. For a confidence score bounded `[0, 1]`, this is fine — `1.000` fits. However, `Numeric(4, 3)` is typically described as "precision 4, scale 3" which in Postgres means values like `1.000` (1 integer digit + 3 decimal digits = 4 total) are the maximum. This is correct but non-obvious, and leaves zero headroom for any future score that exceeds `1.0` (e.g., a raw logit or a percentage). The name `confidence_score` implies a `[0, 1]` range; document this constraint or use `Numeric(5, 4)` for a little more headroom.

**Fix:** Add a comment in the model, or add a `CHECK` constraint:
```python
confidence_score: Mapped[Optional[Decimal]] = mapped_column(
    Numeric(4, 3),
    # Range [0.000, 1.000] — 4 total digits, 3 decimal places
)
```

---

### IN-03: `pywa` Dependency Absent From `requirements.txt`

**File:** `backend/requirements.txt`

**Issue:** The project's `CLAUDE.md` specifies `pywa==3.9.0` as a required dependency for WhatsApp Cloud API integration. It is absent from `requirements.txt`. While Phase 1 does not yet implement WhatsApp handling, `requirements.txt` is the file Docker builds from, and omitting `pywa` means any Phase 2 implementation that imports `pywa` will fail at container startup with an `ImportError`. Adding it now avoids a broken Docker build the moment the first WhatsApp handler is written.

**Fix:**
```
# requirements.txt
pywa==3.9.0
```

---

_Reviewed: 2026-05-13T17:32:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
