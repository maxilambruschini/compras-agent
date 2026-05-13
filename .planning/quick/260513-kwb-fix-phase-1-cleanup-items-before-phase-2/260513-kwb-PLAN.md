---
phase: quick-260513-kwb
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/db/engine.py
  - backend/app/routers/health.py
  - backend/alembic/env.py
  - backend/app/main.py
  - backend/tests/test_db.py
  - backend/Dockerfile
  - docker-compose.yml
  - backend/app/db/models.py
  - backend/alembic/versions/add_is_active_server_default.py
autonomous: true
requirements: [CR-01, CR-02, CR-03, WR-01, WR-03, WR-05, is_active-server_default, uv-switch]

must_haves:
  truths:
    - "Engine singleton is race-condition safe under concurrent initialization"
    - "GET /health returns only {status, db} — no allowlist_count"
    - "Alembic raises RuntimeError when DATABASE_URL env var is absent"
    - "Lifespan shutdown only disposes engine if it was actually created"
    - "All async test functions in test_db.py carry @pytest.mark.asyncio"
    - "docker-compose.yml backend command has no --reload flag"
    - "sender_allowlist.is_active column has server_default='true' in the database"
    - "Dockerfile installs dependencies via uv, not pip"
    - "All 9 existing tests continue to pass after changes"
  artifacts:
    - path: "backend/app/db/engine.py"
      provides: "Thread-safe engine singleton with double-checked locking"
      contains: "_engine_lock"
    - path: "backend/app/routers/health.py"
      provides: "Liveness probe without allowlist_count"
    - path: "backend/alembic/env.py"
      provides: "Fail-fast DATABASE_URL guard"
      contains: "raise RuntimeError"
    - path: "backend/alembic/versions/add_is_active_server_default.py"
      provides: "Migration adding server_default to is_active column"
      contains: "server_default"
    - path: "backend/Dockerfile"
      provides: "uv-based dependency installation"
      contains: "uv pip install"
  key_links:
    - from: "backend/app/main.py lifespan shutdown"
      to: "backend/app/db/engine._engine"
      via: "import _engine as _db_engine; guard with is not None"
---

<objective>
Close all Phase 1 review findings scoped to this task: switch pip to uv in the Dockerfile,
harden the engine singleton (CR-01), scrub allowlist_count from the public /health (CR-02),
add a fail-fast guard in alembic/env.py (CR-03), guard lifespan engine disposal (WR-01),
add missing @pytest.mark.asyncio decorators (WR-03), drop --reload from docker-compose.yml
(WR-05), and ship a new Alembic migration that adds server_default='true' to
sender_allowlist.is_active.

Purpose: Eliminate every critical and in-scope warning from the Phase 1 review before Phase 2
work begins. Phase 2 will depend on a stable foundation — race conditions and silent Alembic
misconfiguration must be fixed now.
Output: 9 source file edits + 1 new Alembic migration, all tests green.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/01-foundation/01-REVIEW.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Harden engine singleton, fix lifespan disposal, add asyncio decorators, drop --reload, fix CR-02 health endpoint</name>
  <files>
    backend/app/db/engine.py
    backend/app/main.py
    backend/app/routers/health.py
    backend/tests/test_db.py
    docker-compose.yml
  </files>
  <action>
Fix five issues across five files.

backend/app/db/engine.py (CR-01):
Add a module-level `threading.Lock` named `_engine_lock`. Apply double-checked locking inside
`get_engine()` and `get_async_session_local()`. The import for `threading` goes at the top of
the file alongside existing imports.

Pattern for get_engine():
```
_engine_lock = threading.Lock()

def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                settings = get_settings()
                _engine = create_async_engine(...)
    return _engine
```
Apply identical double-checked locking to `get_async_session_local()` using the same
`_engine_lock` (one lock covers both globals — they are always initialized together).

backend/app/main.py (WR-01):
Replace the unconditional `get_engine()` call in the lifespan shutdown block with a sentinel
check. Import `_engine` under an alias at the point of use (inside the shutdown block, after
`yield`), not at module level, to preserve the lazy-import pattern already established.

Replace:
```python
from app.db.engine import get_engine
engine = get_engine()
await engine.dispose()
```
With:
```python
from app.db.engine import _engine as _db_engine
if _db_engine is not None:
    await _db_engine.dispose()
```

backend/app/routers/health.py (CR-02):
Remove `allowlist_count` from the response. Keep the DB query (proves connectivity) but return
only `{"status": "ok", "db": "connected"}`. Remove the `count` variable assignment. The
`select(func.count()).select_from(SenderAllowlist)` query and `await db.execute(...)` stay — we
still want the connection exercise. Remove the `count = result.scalar_one()` line and the key
from the return dict.

backend/tests/test_db.py (WR-03):
Add `@pytest.mark.asyncio` to `test_allowlist_crud` (line 23) and `test_invoice_relationship`
(line 40). Both are `async def` without the decorator. Add `import pytest` if it is not already
present at the top of the file (check: it is not in the current imports — add it).

docker-compose.yml (WR-05):
Change the backend `command` from:
  `bash -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"`
to:
  `bash -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"`
Remove only `--reload`. Leave the rest of docker-compose.yml untouched.
  </action>
  <verify>
    <automated>cd /Users/maximolambruschini/NewCombin/compras_agent/backend && python -c "from app.db.engine import _engine_lock; print('lock ok')"</automated>
  </verify>
  <done>
    engine.py has `_engine_lock = threading.Lock()` and double-checked locking in both
    get_engine() and get_async_session_local(); main.py lifespan disposal is guarded by
    `if _db_engine is not None`; health.py returns only {status, db}; test_db.py has
    @pytest.mark.asyncio on both async test functions; docker-compose.yml command has no
    --reload.
  </done>
</task>

<task type="auto">
  <name>Task 2: Fix CR-03 alembic env.py fail-fast guard + add server_default migration + switch Dockerfile to uv</name>
  <files>
    backend/alembic/env.py
    backend/alembic/versions/add_is_active_server_default.py
    backend/app/db/models.py
    backend/Dockerfile
  </files>
  <action>
Fix three issues across four files.

backend/alembic/env.py (CR-03):
Replace the silent fallback guard with a fail-fast RuntimeError. Current code (lines 29-31):
```python
database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)
```
Replace with:
```python
database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL environment variable is required to run migrations. "
        "Set it before invoking alembic."
    )
config.set_main_option("sqlalchemy.url", database_url)
```
All other content in env.py stays exactly as-is. The critical pattern comments must not be
removed.

backend/alembic/versions/add_is_active_server_default.py (new file — is_active server_default):
Create a new migration file. The revision ID must be a fresh 12-char hex string — generate one
with `python -c "import uuid; print(uuid.uuid4().hex[:12])"` and substitute it into the file.
The down_revision must reference `'0cd640399c29'` (the current head).

The migration adds `server_default=sa.text('true')` to the `sender_allowlist.is_active` column,
which was created in the initial schema without a server_default. The column is `Boolean NOT NULL`
and already has an ORM-level `default=True`, but lacks a database-level server_default — meaning
raw SQL inserts (admin scripts, fixtures) must supply the value explicitly.

upgrade():
```python
op.alter_column(
    'sender_allowlist',
    'is_active',
    server_default=sa.text('true'),
    existing_type=sa.Boolean(),
    existing_nullable=False,
)
```

downgrade():
```python
op.alter_column(
    'sender_allowlist',
    'is_active',
    server_default=None,
    existing_type=sa.Boolean(),
    existing_nullable=False,
)
```

Also update the ORM model to match (backend/app/db/models.py): add
`server_default=sa.text('true')` to the `is_active` mapped_column so ORM and migration stay in
sync. The column definition becomes:
```python
is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa.text('true'))
```
This requires adding `sa` import — use `import sqlalchemy as sa` at the top of models.py, or
since `sqlalchemy` objects are already imported directly, add `from sqlalchemy import text` and
use `text('true')` instead of `sa.text('true')`. Either form is correct; prefer the direct-import
form (`from sqlalchemy import text`) since models.py already uses direct sqlalchemy imports.

backend/Dockerfile (uv switch):
Install `uv` and use it for the pip install step. Replace the existing RUN line:
```
RUN pip install --no-cache-dir -r requirements.txt
```
With:
```
RUN pip install uv && uv pip install --system --no-cache -r requirements.txt
```
This installs uv via pip once (base image has pip), then delegates the actual package
installation to uv. The `--system` flag installs into the system Python (correct for Docker
single-environment containers). No other Dockerfile lines change.
  </action>
  <verify>
    <automated>cd /Users/maximolambruschini/NewCombin/compras_agent/backend && python -c "import os; os.environ.pop('DATABASE_URL', None); import sys; sys.path.insert(0, '.'); from unittest.mock import patch; print('env.py guard will be tested via pytest')"</automated>
  </verify>
  <done>
    alembic/env.py raises RuntimeError when DATABASE_URL is unset; new migration file exists
    with correct revision chain (down_revision='0cd640399c29') and ALTER COLUMN for
    server_default; models.py SenderAllowlist.is_active has server_default=text('true');
    Dockerfile installs uv then uses `uv pip install --system` to install requirements.txt.
  </done>
</task>

<task type="auto">
  <name>Task 3: Run full test suite and verify all 9 tests pass</name>
  <files></files>
  <action>
Run the test suite to confirm all existing tests still pass after the changes in Tasks 1 and 2.
No production code changes in this task — tests only.

Execute:
  cd /Users/maximolambruschini/NewCombin/compras_agent/backend && pytest tests/ -x -q

Expected: 9 tests collected, 9 passed, 0 errors, 0 warnings that indicate broken behavior.

If any test fails:
- A failing test_health.py test that checks for allowlist_count in the response must be updated
  to match the new response shape `{"status": "ok", "db": "connected"}` — the health router no
  longer returns allowlist_count (CR-02 fix). Check backend/tests/test_health.py and update the
  assertion to match the new response.
- Any other failure: diagnose root cause and fix before proceeding.

After tests pass, create the summary file at
`.planning/quick/260513-kwb-fix-phase-1-cleanup-items-before-phase-2/260513-kwb-SUMMARY.md`.
  </action>
  <verify>
    <automated>cd /Users/maximolambruschini/NewCombin/compras_agent/backend && pytest tests/ -x -q 2>&1 | tail -5</automated>
  </verify>
  <done>
    pytest exits 0, all tests pass. Summary file written.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| ENV → alembic | DATABASE_URL sourced from process environment; must be validated before use |
| Concurrent startup → engine | Multiple coroutines or threads can race on singleton init |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-kwb-01 | Information Disclosure | GET /health (allowlist_count) | mitigate | Remove allowlist_count from unauthenticated response — implemented in CR-02 fix |
| T-kwb-02 | Denial of Service | GET /health DB query | accept | Query runs against connection pool; at <20 invoices/day, pool saturation from /health is not a realistic threat in v1 |
| T-kwb-03 | Tampering | Alembic silent DB fallback | mitigate | Fail-fast RuntimeError when DATABASE_URL absent — implemented in CR-03 fix |
| T-kwb-04 | Denial of Service | --reload in production | mitigate | Removed from docker-compose.yml; reloader subprocess + inotify scan on volume mount eliminated |
</threat_model>

<verification>
All changes verified by Task 3 pytest run:
- `pytest tests/ -x -q` exits 0
- 9 tests collected and passed
- `_engine_lock` importable from app.db.engine
- health.py response shape confirmed by test_health.py assertions
</verification>

<success_criteria>
- engine.py has threading.Lock + double-checked locking in get_engine() and get_async_session_local()
- health.py GET /health returns {"status": "ok", "db": "connected"} with no allowlist_count
- alembic/env.py raises RuntimeError("DATABASE_URL environment variable is required...") when env var is absent
- main.py lifespan shutdown block checks `_db_engine is not None` before calling dispose()
- test_db.py test_allowlist_crud and test_invoice_relationship have @pytest.mark.asyncio
- docker-compose.yml backend command has no --reload flag
- new Alembic migration file exists with down_revision='0cd640399c29' and op.alter_column for server_default='true' on is_active
- models.py SenderAllowlist.is_active has server_default=text('true')
- Dockerfile uses `uv pip install --system` for requirements.txt installation
- pytest tests/ exits 0 with all 9 tests passing
</success_criteria>

<output>
After completion, create `.planning/quick/260513-kwb-fix-phase-1-cleanup-items-before-phase-2/260513-kwb-SUMMARY.md`
using the summary template.
</output>
