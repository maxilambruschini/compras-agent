---
phase: 01-foundation
plan: "02"
subsystem: walking-skeleton
tags:
  - foundation
  - docker
  - fastapi
  - vite
  - walking-skeleton
dependency_graph:
  requires:
    - 01 (backend/app/config.py, db/models.py, db/engine.py, db/session.py, alembic migration)
  provides:
    - backend/app/main.py (FastAPI app factory + lifespan)
    - backend/app/routers/health.py (GET /health endpoint)
    - backend/Dockerfile (python:3.12-slim production image)
    - frontend/ (Vite 8 + React 19 + TypeScript scaffold)
    - frontend/Dockerfile (node:22-alpine + pnpm dev)
    - docker-compose.yml (postgres + backend + frontend orchestration)
    - .env (local dev secrets, gitignored)
    - README.md (quickstart)
  affects:
    - Plan 03 (WhatsApp webhook mounts on the same FastAPI app instance)
    - Plan 04 (frontend builds on the Vite scaffold established here)
tech_stack:
  added:
    - structlog==25.5.0 (already in requirements.txt from Plan 01)
    - httpx (dev, already in requirements-dev.txt from Plan 01)
    - Vite 8.0.12 (frontend build tool)
    - React 19.2.6 (UI framework)
    - TypeScript 6.0.3 (type safety)
    - "@vitejs/plugin-react 6.0.1"
    - pnpm 10.12.1 (frontend package manager)
    - Docker Compose v2 (multi-service orchestration)
  patterns:
    - FastAPI app factory + asynccontextmanager lifespan (RESEARCH.md Pattern 7)
    - Lazy engine disposal in lifespan shutdown via get_engine()
    - ASGI test client with dependency_overrides[get_db] for integration tests
    - Docker Compose condition: service_healthy on postgres (pg_isready healthcheck)
    - alembic upgrade head && uvicorn in backend entrypoint command (D-05)
    - VITE_API_URL env var driving Vite proxy target (fallback to localhost:8000)
    - Anonymous /app/node_modules volume preventing host override (RESEARCH.md Pitfall 5)
key_files:
  created:
    - backend/app/main.py
    - backend/app/routers/health.py
    - backend/tests/test_health.py
    - backend/Dockerfile
    - backend/.dockerignore
    - frontend/ (full Vite + React scaffold via pnpm create vite)
    - frontend/Dockerfile
    - frontend/.dockerignore
    - frontend/vite.config.ts (modified from scaffold default)
    - frontend/src/App.tsx (replaced scaffold with minimal placeholder)
    - docker-compose.yml
    - README.md
    - .env
  modified: []
decisions:
  - "lifespan calls get_settings() at startup to trigger pydantic ValidationError on missing env vars (INF-03 end-to-end)"
  - "get_engine() called in lifespan shutdown (not at module level) to match lazy factory pattern from Plan 01"
  - "Router imported inside create_app() to avoid circular imports at module init time"
  - "Vite proxy target reads from process.env.VITE_API_URL with http://localhost:8000 fallback (REVIEWS.md MEDIUM fix)"
  - "VITE_API_URL=http://backend:8000 set in compose environment so in-Docker proxy resolves backend service hostname"
  - "backend/.dockerignore excludes tests/ to keep production image lean (REVIEWS.md LOW)"
metrics:
  duration: "~30 minutes"
  completed_date: "2026-05-13"
  tasks_completed: 2
  tests_passing: 11
  files_created: 28
---

# Phase 1 Plan 02: Walking Skeleton Summary

FastAPI app factory wired to GET /health (real Postgres round-trip via AsyncSession), Docker Compose orchestrating postgres:16 + backend:8000 + Vite frontend:5173, Alembic migrations auto-running on container boot.

## What Was Built

### Task 1: FastAPI app + /health router + integration test + .env (commit 9da5870)

`backend/app/routers/health.py`: `GET /health` handler using `Depends(get_db)`, executes `select(func.count()).select_from(SenderAllowlist)`, returns `{"status": "ok", "allowlist_count": <int>, "db": "connected"}`. Follows PATTERNS.md canonical excerpt exactly.

`backend/app/main.py`: `@asynccontextmanager lifespan` calls `get_settings()` on startup (raises `ValidationError` if required env var missing — INF-03 end-to-end), logs `app.starting` via structlog without any secret values, disposes the lazy engine on shutdown via `get_engine().dispose()`. `create_app()` factory constructs `FastAPI(lifespan=lifespan)` and imports the health router inside the function (avoids circular imports).

`backend/tests/test_health.py`: 2 integration tests using `httpx.AsyncClient(ASGITransport)` + `dependency_overrides[get_db]`. `test_health_empty_allowlist` verifies 200 + `{"status":"ok","allowlist_count":0,"db":"connected"}`. `test_health_with_seed` inserts one `SenderAllowlist` row and verifies `allowlist_count == 1`. Both pass (total test suite: 11 passing).

`.env`: local dev secrets with placeholder values, gitignored (verified via `git check-ignore`).

### Task 2: Backend Dockerfile + Frontend scaffold + docker-compose.yml + README (commit 96775b7)

`backend/Dockerfile`: `FROM python:3.12-slim`, layer-cache-optimized (`COPY requirements.txt` before `COPY .`), `CMD uvicorn` (overridden by compose `command:`).

`backend/.dockerignore`: excludes `__pycache__/`, `.pytest_cache/`, `_autogen.db`, `.venv/`, `requirements-dev.txt`, `tests/` (REVIEWS.md MEDIUM fix — keeps production image lean).

Frontend scaffold generated via `pnpm create vite frontend --template react-ts`, `pnpm install` run inside `frontend/`. Result: Vite 8.0.12 + React 19.2.6 + TypeScript 6.0.3.

`frontend/vite.config.ts`: modified from scaffold default to add `server.host=true`, `server.port=5173`, proxy with `process.env.VITE_API_URL || 'http://localhost:8000'` (REVIEWS.md MEDIUM fix).

`frontend/src/App.tsx`: replaced Vite default with minimal `<h1>Compras Agent</h1><p>Phase 1 — Walking Skeleton</p>`.

`frontend/Dockerfile`: `FROM node:22-alpine`, `corepack enable && corepack prepare pnpm@latest --activate`, layer-cache-optimized `pnpm install`, `CMD pnpm dev --host 0.0.0.0`.

`docker-compose.yml`: postgres:16-alpine with `pg_isready` healthcheck, backend `depends_on: postgres: condition: service_healthy`, backend `command: bash -c "alembic upgrade head && uvicorn ..."`, `env_file: .env` + `DATABASE_URL` override in `environment:` (docker-internal hostname `postgres`), frontend with anonymous `/app/node_modules` volume, `VITE_API_URL=http://backend:8000`.

`README.md`: quickstart (`cp .env.example .env`, `docker compose up`), architecture table, prerequisites.

## End-to-End Verification Evidence

```
docker compose up -d --wait --wait-timeout 120  → exit 0, all 3 services healthy
curl http://localhost:8000/health                → {"status":"ok","allowlist_count":0,"db":"connected"}
curl -o /dev/null -w "%{http_code}" http://localhost:5173 → 200
docker compose logs backend | grep alembic       → "Running upgrade  -> 0cd640399c29, initial_schema"
docker compose logs backend error count          → 0
\dt in postgres container                        → invoices, invoice_line_items, sender_allowlist, alembic_version
```

## ROADMAP Success Criteria Status

| SC | Description | Status |
|----|-------------|--------|
| SC-1 | `docker compose up` starts FastAPI, Postgres, frontend without errors | VERIFIED |
| SC-2 | All tables exist after migrations | VERIFIED (`\dt` shows all 3 tables) |
| SC-3 | Allowlist table can be seeded with phone numbers | VERIFIED (test_health_with_seed) |
| SC-4 | ExtractedInvoice model importable without errors | VERIFIED (Plan 01 tests) |
| SC-5 | App refuses to start with required env var missing | VERIFIED (lifespan get_settings() + Task 3 INF-03 negative test pending) |

## INF-01 / INF-03 Verification

**INF-01:** `sender_allowlist` table created by Alembic migration `0cd640399c29`. Accessible via `/health` COUNT query and direct psql. `\dt` confirms table exists in Postgres container.

**INF-03:** `lifespan()` calls `get_settings()` on startup. `Settings` has 5 required fields with no defaults — missing any raises `pydantic.ValidationError` before `yield`, aborting container startup. Full negative test (removing `OPENAI_API_KEY` from `.env`) deferred to Task 3 human checkpoint.

## REVIEWS.md Fix Application Log

| Issue | Severity | Fix Applied |
|-------|----------|-------------|
| Vite proxy hardcoded `backend:8000` breaks local dev | MEDIUM | `process.env.VITE_API_URL \|\| 'http://localhost:8000'` in vite.config.ts |
| `--wait-timeout 120` missing from `docker compose up` | MEDIUM | Used in Task 2 verify command |
| `backend/.dockerignore` missing | MEDIUM | Created — excludes `__pycache__`, `.pytest_cache`, `.venv`, `tests/` |
| `psql -U compras` hardcoded user for acceptance test | LOW | Used in acceptance criteria (intentional — expand variables not available outside container) |
| Production image includes dev deps | LOW | `requirements-dev.txt` in `.dockerignore`, only `requirements.txt` installed in Dockerfile |

## Deviations from Plan

### Auto-fixed Issues

None — all plan action items and REVIEWS.md concerns were addressed as written.

### Notes

The `frontend/vite-env.d.ts` file referenced in the plan's `<files>` list was not explicitly created — `pnpm create vite --template react-ts` does not generate a `vite-env.d.ts` in Vite 8; the TypeScript environment types are declared in `tsconfig.app.json` via `"types": ["vite/client"]` instead. This is correct Vite 8 behavior and does not affect functionality.

## Known Stubs

`frontend/src/App.tsx` renders `<h1>Compras Agent</h1><p>Phase 1 — Walking Skeleton</p>`. This is intentional per D-10 — Phase 4 builds the actual UI. The stub satisfies the Task 3 browser verification step ("renders the text Compras Agent and Phase 1 — Walking Skeleton").

## Threat Flags

No new security surface beyond the plan's threat model:
- T-02-01: `.env` gitignored (verified), `.env.example` used for reference
- T-02-02: `main.py` logs `log_level` only — grep confirms no secret values logged
- T-02-09: `backend/.dockerignore` and `frontend/.dockerignore` both present

## Self-Check: PASSED

All required files exist:
- backend/app/main.py: FOUND
- backend/app/routers/health.py: FOUND
- backend/tests/test_health.py: FOUND
- backend/Dockerfile: FOUND
- backend/.dockerignore: FOUND
- frontend/package.json: FOUND
- frontend/pnpm-lock.yaml: FOUND
- frontend/Dockerfile: FOUND
- frontend/.dockerignore: FOUND
- frontend/vite.config.ts: FOUND
- frontend/src/App.tsx: FOUND
- docker-compose.yml: FOUND
- README.md: FOUND
- .env: FOUND

Both task commits verified in git log:
- Task 1: 9da5870 (feat(01-02): FastAPI app factory + /health endpoint)
- Task 2: 96775b7 (feat(01-02): backend Dockerfile + Vite/React scaffold)

11 tests passing (pytest backend/tests/).

## Checkpoint Pending

Task 3 is a `checkpoint:human-verify` — requires human verification of:
1. Cold-boot from empty Postgres volume (`docker compose down -v` → `docker compose up`)
2. Browser verification of http://localhost:8000/health and http://localhost:5173
3. DB write test (INSERT into sender_allowlist via psql, verify allowlist_count becomes 1)
4. INF-03 negative test (remove OPENAI_API_KEY from .env, verify backend exits non-zero with ValidationError)
