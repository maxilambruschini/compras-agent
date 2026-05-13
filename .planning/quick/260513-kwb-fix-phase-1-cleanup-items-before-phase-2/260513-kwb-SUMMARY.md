---
phase: quick-260513-kwb
plan: "01"
subsystem: backend
tags: [hardening, security, testing, docker, alembic]
dependency_graph:
  requires: []
  provides: [stable-foundation-for-phase-2]
  affects: [backend/app/db/engine.py, backend/app/main.py, backend/app/routers/health.py, backend/tests, backend/alembic, backend/Dockerfile, docker-compose.yml]
tech_stack:
  added: [threading.Lock (stdlib), uv (pip installer)]
  patterns: [double-checked locking, fail-fast guard, server_default migration]
key_files:
  created:
    - backend/alembic/versions/add_is_active_server_default.py
  modified:
    - backend/app/db/engine.py
    - backend/app/main.py
    - backend/app/routers/health.py
    - backend/alembic/env.py
    - backend/app/db/models.py
    - backend/tests/test_db.py
    - backend/tests/test_health.py
    - backend/Dockerfile
    - docker-compose.yml
decisions:
  - Use single _engine_lock for both get_engine() and get_async_session_local() — they always initialize together
  - Import _engine alias inside lifespan shutdown block rather than at module level — preserves lazy-init pattern
  - Use direct sqlalchemy import (text) rather than sa.text in models.py — consistent with existing import style
metrics:
  duration_seconds: 115
  completed_date: "2026-05-13"
  tasks_completed: 3
  files_modified: 9
  files_created: 1
---

# Phase quick-260513-kwb Plan 01: Fix Phase 1 Cleanup Items Before Phase 2 Summary

**One-liner:** Thread-safe engine singleton with double-checked locking, fail-fast alembic guard, server_default migration for is_active, uv-based Dockerfile install, and health endpoint stripped of information disclosure.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Harden engine singleton, fix lifespan, scrub health, asyncio markers, drop --reload | a06fefc | engine.py, main.py, health.py, test_db.py, docker-compose.yml |
| 2 | Alembic fail-fast guard, server_default migration, ORM sync, Dockerfile uv switch | 9b0110e | alembic/env.py, versions/add_is_active_server_default.py, models.py, Dockerfile |
| 3 | Run full test suite — update test_health.py, verify all 11 tests pass | 70337fb | tests/test_health.py |

## Changes Summary

### CR-01: Engine singleton race condition (engine.py)
Added `_engine_lock = threading.Lock()` at module level. Applied double-checked locking inside both `get_engine()` and `get_async_session_local()`. One lock covers both globals — they are always initialized together.

### WR-01: Lifespan engine disposal guard (main.py)
Replaced unconditional `get_engine().dispose()` with sentinel check: imports `_engine as _db_engine` inside the shutdown block, calls `dispose()` only if `_db_engine is not None`. Prevents creating an engine just to immediately dispose it during test teardown.

### CR-02: Health endpoint information disclosure (health.py, test_health.py)
Removed `allowlist_count` from the `/health` response. The DB connectivity query (`select(func.count()).select_from(SenderAllowlist)`) is retained — it still exercises the connection — but the count is no longer surfaced. Updated test assertions to match the new `{"status": "ok", "db": "connected"}` shape.

### WR-03: Missing @pytest.mark.asyncio decorators (test_db.py)
Added `@pytest.mark.asyncio` to `test_allowlist_crud` and `test_invoice_relationship`. Both were `async def` without the decorator, relying on implicit collection which is fragile across pytest-asyncio versions.

### WR-05: --reload flag in production docker-compose (docker-compose.yml)
Removed `--reload` from the backend `command`. The reloader subprocess with inotify scanning on the mounted volume is inappropriate for production images.

### CR-03: Alembic silent DATABASE_URL fallback (alembic/env.py)
Replaced `if database_url: config.set_main_option(...)` with a fail-fast `RuntimeError` when `DATABASE_URL` is absent. Silent fallback caused mysterious migration errors that were hard to diagnose.

### is_active server_default (alembic/versions/add_is_active_server_default.py + models.py)
New migration `9f9e9cf65e1e` (down_revision=`0cd640399c29`) adds `server_default=sa.text('true')` to `sender_allowlist.is_active` via `op.alter_column`. Updated `SenderAllowlist.is_active` in models.py to add `server_default=text('true')` keeping ORM and migration in sync. Raw SQL inserts that omit the column now default to `true` without requiring explicit value.

### Dockerfile uv switch
Replaced `pip install --no-cache-dir -r requirements.txt` with `pip install uv && uv pip install --system --no-cache -r requirements.txt`. The `--system` flag installs into the system Python — correct for single-environment Docker containers.

## Test Results

```
11 passed in 0.16s
```

All 11 tests collected and passed (9 original + 2 async tests now properly collected via @pytest.mark.asyncio).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_health.py assertions referenced removed response field**
- **Found during:** Task 3
- **Issue:** `test_health_empty_allowlist` asserted `body == {"status": "ok", "allowlist_count": 0, "db": "connected"}` and `test_health_with_seed` asserted `body["allowlist_count"] == 1`. Both would fail after the CR-02 health.py change.
- **Fix:** Updated assertions to match the new `{"status": "ok", "db": "connected"}` shape. Added negative assertion `"allowlist_count" not in body` to `test_health_with_seed`.
- **Files modified:** `backend/tests/test_health.py`
- **Commit:** 70337fb

The plan explicitly noted this might be needed in Task 3's action block ("A failing test_health.py test that checks for allowlist_count in the response must be updated").

## Known Stubs

None — all changes are concrete implementations with no placeholder values.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries introduced beyond what was explicitly planned.

## Self-Check: PASSED

Files verified:
- backend/app/db/engine.py — FOUND (has _engine_lock)
- backend/app/main.py — FOUND (has _db_engine is not None guard)
- backend/app/routers/health.py — FOUND (no allowlist_count)
- backend/alembic/env.py — FOUND (has raise RuntimeError)
- backend/alembic/versions/add_is_active_server_default.py — FOUND
- backend/app/db/models.py — FOUND (has server_default=text('true'))
- backend/tests/test_db.py — FOUND (has @pytest.mark.asyncio decorators)
- backend/tests/test_health.py — FOUND (updated assertions)
- backend/Dockerfile — FOUND (uv pip install)
- docker-compose.yml — FOUND (no --reload)

Commits verified:
- a06fefc — FOUND
- 9b0110e — FOUND
- 70337fb — FOUND
