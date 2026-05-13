---
phase: 01-foundation
plan: 02
type: execute
wave: 2
depends_on:
  - 01
files_modified:
  - backend/app/main.py
  - backend/app/routers/health.py
  - backend/Dockerfile
  - backend/tests/test_health.py
  - frontend/package.json
  - frontend/pnpm-lock.yaml
  - frontend/index.html
  - frontend/vite.config.ts
  - frontend/tsconfig.json
  - frontend/tsconfig.node.json
  - frontend/src/main.tsx
  - frontend/src/App.tsx
  - frontend/src/vite-env.d.ts
  - frontend/Dockerfile
  - frontend/.dockerignore
  - docker-compose.yml
  - .env
  - README.md
autonomous: false
requirements:
  - INF-01
  - INF-03
tags:
  - foundation
  - docker
  - fastapi
  - vite
  - walking-skeleton

must_haves:
  truths:
    - "`docker compose up` starts postgres, backend, and frontend containers without errors"
    - "Postgres healthcheck passes (pg_isready) before backend boots"
    - "`alembic upgrade head` runs inside the backend container before Uvicorn starts and creates all three tables"
    - "`curl http://localhost:8000/health` returns 200 with body containing `\"status\": \"ok\"`, `\"allowlist_count\": 0`, `\"db\": \"connected\"`"
    - "Vite dev server is reachable at http://localhost:5173 and renders the React scaffold"
    - "Backend container exits non-zero on startup if a required env var (e.g. OPENAI_API_KEY) is removed from .env (INF-03 end-to-end)"
  artifacts:
    - path: "backend/app/main.py"
      provides: "FastAPI app factory + lifespan + health router mount"
      contains: "def create_app"
    - path: "backend/app/routers/health.py"
      provides: "GET /health endpoint reading sender_allowlist count"
      contains: "@router.get(\"/health\")"
    - path: "backend/Dockerfile"
      provides: "Python 3.12-slim image with requirements installed"
      contains: "FROM python:3.12-slim"
    - path: "frontend/package.json"
      provides: "Vite + React + TS dev dependencies; scripts.dev = vite"
      contains: "\"vite\""
    - path: "frontend/Dockerfile"
      provides: "Node 22-alpine + pnpm + pnpm dev entrypoint"
      contains: "corepack enable"
    - path: "docker-compose.yml"
      provides: "postgres + backend + frontend services with healthcheck and entrypoint command"
      contains: "alembic upgrade head"
    - path: ".env"
      provides: "Local dev secrets (gitignored)"
      contains: "DATABASE_URL"
    - path: "backend/tests/test_health.py"
      provides: "Integration test for GET /health against test DB"
      contains: "/health"
  key_links:
    - from: "docker-compose.yml backend service"
      to: "backend/Dockerfile + alembic + uvicorn"
      via: "command: bash -c \"alembic upgrade head && uvicorn ...\""
      pattern: "alembic upgrade head && uvicorn"
    - from: "docker-compose.yml backend depends_on"
      to: "postgres healthcheck"
      via: "condition: service_healthy"
      pattern: "condition: service_healthy"
    - from: "backend/app/routers/health.py"
      to: "backend/app/db/session.get_db + SenderAllowlist"
      via: "Depends(get_db) + select(func.count()).select_from(SenderAllowlist)"
      pattern: "select\\(func\\.count\\(\\)\\)\\.select_from\\(SenderAllowlist\\)"
    - from: "frontend/Dockerfile node_modules"
      to: "docker-compose.yml anonymous volume"
      via: "volumes: - /app/node_modules"
      pattern: "/app/node_modules"
---

<objective>
Wire the Walking Skeleton: Docker Compose orchestrates Postgres + FastAPI backend + Vite/React frontend; Alembic runs `upgrade head` on container boot; FastAPI exposes `GET /health` that performs a real SQLAlchemy AsyncSession round-trip against the `sender_allowlist` table. This proves Phase-1 success criteria 1-5 end-to-end and unblocks Phase 2.

Purpose: Deliver the minimum complete vertical slice — `docker compose up` to `curl /health` returning `allowlist_count: 0` — establishing the deployment, routing, DB, and frontend scaffold that Phases 2-4 build on without renegotiation.

Output: Working `docker compose up`, a functional `GET /health` endpoint, a Vite-served React scaffold on `:5173`, and a human-verified end-to-end smoke that satisfies INF-01 and INF-03 in a real container environment.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@CLAUDE.md
@.planning/ROADMAP.md
@.planning/phases/01-foundation/01-CONTEXT.md
@.planning/phases/01-foundation/01-RESEARCH.md
@.planning/phases/01-foundation/01-PATTERNS.md
@.planning/phases/01-foundation/01-SKELETON.md
@.planning/phases/01-foundation/01-VALIDATION.md
@.planning/phases/01-foundation/01-01-SUMMARY.md

<interfaces>
<!-- Backbone files from Plan 01 that this plan consumes -->
backend/app/config.py:    get_settings() -> Settings
backend/app/db/session.py: async def get_db() -> AsyncGenerator[AsyncSession, None]
backend/app/db/engine.py: engine (AsyncEngine), AsyncSessionLocal
backend/app/db/models.py: Base, SenderAllowlist (table 'sender_allowlist')

<!-- New endpoint contract -->
GET /health  (handler in backend/app/routers/health.py)
  Response 200: {"status": "ok", "allowlist_count": <int>, "db": "connected"}
  Reads: SELECT count(*) FROM sender_allowlist
  Auth: none (open endpoint in Phase 1; UI-07 deferred to v2)

<!-- Docker port contract -->
postgres → host :5432, container :5432
backend  → host :8000, container :8000  (uvicorn --reload)
frontend → host :5173, container :5173  (pnpm dev --host 0.0.0.0)

<!-- Required env vars at runtime (loaded by pydantic-settings from .env / compose env_file) -->
DATABASE_URL, OPENAI_API_KEY, WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_VERIFY_TOKEN
POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB (compose-only, used by postgres service)
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: FastAPI app + /health router + integration test + .env</name>
  <files>
    backend/app/main.py,
    backend/app/routers/health.py,
    backend/tests/test_health.py,
    .env
  </files>
  <read_first>
    backend/app/config.py,
    backend/app/db/session.py,
    backend/app/db/engine.py,
    backend/app/db/models.py,
    backend/tests/conftest.py,
    .env.example,
    .planning/phases/01-foundation/01-RESEARCH.md,
    .planning/phases/01-foundation/01-PATTERNS.md
  </read_first>
  <action>
    Build the FastAPI application entry point and the walking-skeleton `/health` endpoint, then add an integration test that exercises it end-to-end against the aiosqlite test DB.

    1) `backend/app/routers/health.py` — implement per RESEARCH.md Code Examples §Walking Skeleton Health Endpoint. `APIRouter()` instance, exported as `router`. Single handler:
       ```
       @router.get("/health")
       async def health(db: AsyncSession = Depends(get_db)):
           result = await db.execute(select(func.count()).select_from(SenderAllowlist))
           count = result.scalar_one()
           return {"status": "ok", "allowlist_count": count, "db": "connected"}
       ```
       Imports: `from fastapi import APIRouter, Depends`, `from sqlalchemy import select, func`, `from sqlalchemy.ext.asyncio import AsyncSession`, `from app.db.session import get_db`, `from app.db.models import SenderAllowlist`. (The action describes the shape; do not paste this snippet verbatim — the canonical excerpt is in 01-PATTERNS.md.)

    2) `backend/app/main.py` — implement per RESEARCH.md Pattern 7. `@asynccontextmanager async def lifespan(app)` that calls `get_settings()` at startup (which raises ValidationError on missing env — INF-03 end-to-end), logs via structlog (`log.info("app.starting", log_level=settings.log_level)` — DO NOT log secrets), yields, and on shutdown calls `await engine.dispose()`. `def create_app() -> FastAPI` that constructs `FastAPI(title="Compras Agent API", lifespan=lifespan, debug=settings.debug)` and includes the health router. Module-level `app = create_app()`. Import the health router INSIDE `create_app` to avoid circular imports per 01-PATTERNS.md note.

    3) `backend/tests/test_health.py` — integration test using `httpx.AsyncClient` + ASGI transport (no live server needed). Override `app.dependency_overrides[get_db]` to yield the test `db_session` from conftest, so the request hits the in-memory aiosqlite DB. Tests:
       - `test_health_empty_allowlist`: GET /health → 200, body == `{"status": "ok", "allowlist_count": 0, "db": "connected"}`.
       - `test_health_with_seed`: insert one SenderAllowlist row in the fixture DB, GET /health → 200, `allowlist_count == 1`.
       Use `httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")`. Ensure conftest's `env_setup` fixture has set the required env vars before `app` is imported (otherwise `Settings()` blows up during import). The cleanest approach: lazily import `app` inside the test function body after env is set up.

    4) `.env` at repo root — copy from `.env.example` with dev-grade values:
       ```
       DATABASE_URL=postgresql+asyncpg://compras:compras@postgres:5432/compras
       POSTGRES_USER=compras
       POSTGRES_PASSWORD=compras
       POSTGRES_DB=compras
       OPENAI_API_KEY=sk-placeholder-replace-me
       WHATSAPP_TOKEN=placeholder
       WHATSAPP_PHONE_NUMBER_ID=placeholder
       WHATSAPP_VERIFY_TOKEN=placeholder
       DEBUG=true
       LOG_LEVEL=DEBUG
       CONFIDENCE_THRESHOLD=0.85
       ```
       The file is in `.gitignore` so it ships only to the local dev machine. Placeholder values are acceptable in Phase 1 because no real external calls are made — only `Settings()` validation runs.
  </action>
  <verify>
    <automated>cd backend && pytest tests/test_health.py -x -q</automated>
  </verify>
  <acceptance_criteria>
    - `grep -c "@router.get(\"/health\")" backend/app/routers/health.py` equals 1.
    - `grep -c "select(func.count()).select_from(SenderAllowlist)" backend/app/routers/health.py` equals 1.
    - `grep -c "lifespan=lifespan" backend/app/main.py` >= 1.
    - `grep -c "engine.dispose" backend/app/main.py` >= 1.
    - `grep -c "app = create_app()" backend/app/main.py` equals 1.
    - `grep "openai_api_key\|whatsapp_token\|database_url" backend/app/main.py` returns no matches (secrets never logged).
    - `pytest backend/tests/test_health.py -x -q` exits 0 with 2 tests passing.
    - `.env` file exists at repo root and contains `DATABASE_URL=postgresql+asyncpg://`.
    - `git check-ignore .env` exits 0 (file is gitignored — verifies .gitignore from Plan 01 is correct).
  </acceptance_criteria>
  <done>
    `/health` endpoint exists and is exercised by automated integration tests against the in-memory test DB. FastAPI app factory + lifespan pattern in place per RESEARCH.md Pattern 7. Local `.env` populated so containers will boot in Task 2.
  </done>
</task>

<task type="auto">
  <name>Task 2: Backend Dockerfile + Frontend Vite/React scaffold + Frontend Dockerfile + docker-compose.yml + README</name>
  <files>
    backend/Dockerfile,
    frontend/package.json,
    frontend/pnpm-lock.yaml,
    frontend/index.html,
    frontend/vite.config.ts,
    frontend/tsconfig.json,
    frontend/tsconfig.node.json,
    frontend/src/main.tsx,
    frontend/src/App.tsx,
    frontend/src/vite-env.d.ts,
    frontend/Dockerfile,
    frontend/.dockerignore,
    docker-compose.yml,
    README.md
  </files>
  <read_first>
    backend/requirements.txt,
    backend/app/main.py,
    .env,
    .env.example,
    .planning/phases/01-foundation/01-RESEARCH.md,
    .planning/phases/01-foundation/01-PATTERNS.md,
    .planning/phases/01-foundation/01-SKELETON.md
  </read_first>
  <action>
    Build the full Docker orchestration: backend image, frontend scaffold + image, and the compose file that wires them with Postgres. Honor every locked decision D-10/D-11/D-12 (pnpm-only, Vite, real scaffold) and every pitfall from RESEARCH.md (healthcheck, NullPool already in env.py, node_modules anonymous volume, entrypoint command).

    1) `backend/Dockerfile` — per RESEARCH.md Code Examples §Backend Dockerfile.
       - `FROM python:3.12-slim`
       - `WORKDIR /app`
       - `COPY requirements.txt .` → `RUN pip install --no-cache-dir -r requirements.txt`
       - `COPY . .`
       - Default `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]` (compose overrides this with the alembic+uvicorn bash command).

    2) Frontend scaffold via pnpm (D-10/D-11). From repo root: `pnpm create vite frontend --template react-ts` (non-interactive). This generates `package.json`, `vite.config.ts`, `tsconfig.json`, `tsconfig.node.json`, `index.html`, `src/main.tsx`, `src/App.tsx`, `src/vite-env.d.ts`, and other Vite defaults. Then `cd frontend && pnpm install` to generate `pnpm-lock.yaml`. Then:
       - Edit `frontend/vite.config.ts` to add `server: { host: true, port: 5173, proxy: { '/api': 'http://backend:8000', '/health': 'http://backend:8000' } }` so the dev server is reachable from outside the container and forwards `/health` to the backend (RESEARCH.md Open Question 2 — costs ~3 lines, removes CORS friction).
       - Edit `frontend/src/App.tsx` to render a minimal placeholder: `<h1>Compras Agent</h1><p>Phase 1 — Walking Skeleton</p>`. No styling work, no interactivity — D-10 says real scaffold, not real UI; Phase 4 builds the actual UI.

    3) `frontend/Dockerfile` — per RESEARCH.md Code Examples §Frontend Dockerfile (dev).
       - `FROM node:22-alpine`
       - `RUN corepack enable && corepack prepare pnpm@latest --activate` (D-11 — pnpm via corepack, no global install hacks).
       - `WORKDIR /app`
       - `COPY package.json pnpm-lock.yaml ./` → `RUN pnpm install`
       - `COPY . .`
       - `EXPOSE 5173`
       - `CMD ["pnpm", "dev", "--host", "0.0.0.0"]`

    4) `frontend/.dockerignore` — at minimum: `node_modules`, `dist`, `.git`. Prevents host artifacts polluting the image build context.

    5) `docker-compose.yml` at repo root — per RESEARCH.md Pattern 2. Services:
       - `postgres`: image `postgres:16-alpine`; environment `POSTGRES_USER/PASSWORD/DB` from compose `${VAR}` interpolation reading repo-root `.env`; named volume `postgres_data:/var/lib/postgresql/data`; `healthcheck: test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"], interval: 5s, timeout: 5s, retries: 5`; ports `5432:5432`.
       - `backend`: `build: ./backend`; `command: bash -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"` (D-05 — migrations before app, RESEARCH.md anti-pattern says do NOT use lifespan); ports `8000:8000`; `volumes: - ./backend:/app` for hot-reload; `depends_on: postgres: { condition: service_healthy }` (RESEARCH.md Pitfall 2); `env_file: .env`; `environment: DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}` so the in-container hostname is `postgres` (the service name) regardless of what `.env` says for host-side use.
       - `frontend`: `build: ./frontend`; `command: pnpm dev --host 0.0.0.0`; ports `5173:5173`; `volumes: - ./frontend/src:/app/src - ./frontend/public:/app/public - /app/node_modules` (RESEARCH.md Pitfall 5 — anonymous node_modules volume protects container packages).
       - Top-level `volumes: postgres_data:`.

    6) `README.md` at repo root — concise quickstart only. Sections:
       - **Compras Agent** (one-line description from CLAUDE.md).
       - **Prerequisites**: Docker 27+, Docker Compose v2.32+, pnpm 10+ (only for local non-container dev).
       - **Quickstart**: `cp .env.example .env`, edit values, `docker compose up`, then `curl http://localhost:8000/health` and visit `http://localhost:5173`.
       - **Architecture**: 3 services (postgres :5432, backend :8000, frontend :5173); migrations run automatically on backend container boot.
       - **Phase 1 scope link**: `.planning/phases/01-foundation/01-SKELETON.md`.

    Pitfall checklist (RESEARCH.md):
    - condition: service_healthy on postgres → present.
    - pg_isready healthcheck on postgres → present.
    - Anonymous /app/node_modules volume on frontend → present.
    - bash -c "alembic upgrade head && uvicorn ..." in backend command → present.
    - Backend command overrides the Dockerfile CMD (compose `command:` always wins).
    - DATABASE_URL in compose `environment:` uses `postgres` as host (the service name, not localhost).
  </action>
  <verify>
    <automated>docker compose config -q && docker compose build --quiet && docker compose up -d --wait && curl -fsS http://localhost:8000/health | grep -q '"status":"ok"' && curl -fsS http://localhost:8000/health | grep -q '"allowlist_count":0' && curl -fsS -o /dev/null -w "%{http_code}" http://localhost:5173 | grep -q "200" && docker compose down</automated>
  </verify>
  <acceptance_criteria>
    - `docker compose config -q` exits 0 (compose file is syntactically valid and resolves env vars from `.env`).
    - `docker compose build` exits 0 for both backend and frontend services.
    - `docker compose up -d --wait` exits 0 (all three services reach healthy state).
    - `grep -c "condition: service_healthy" docker-compose.yml` >= 1.
    - `grep -c "pg_isready" docker-compose.yml` >= 1.
    - `grep -c "alembic upgrade head && uvicorn" docker-compose.yml` >= 1.
    - `grep -c "/app/node_modules" docker-compose.yml` >= 1.
    - `grep -c "FROM python:3.12-slim" backend/Dockerfile` equals 1.
    - `grep -c "corepack enable" frontend/Dockerfile` >= 1.
    - `grep -c "pnpm" frontend/Dockerfile` >= 2 (corepack prepare + CMD).
    - `grep -c "\"vite\"" frontend/package.json` >= 1 (Vite scaffold succeeded).
    - `frontend/pnpm-lock.yaml` exists and is non-empty.
    - `frontend/src/App.tsx` contains the string `Compras Agent`.
    - With containers running: `curl -fsS http://localhost:8000/health` returns HTTP 200 and body containing `"status":"ok"`, `"allowlist_count":0`, `"db":"connected"`.
    - With containers running: `curl -fsS -o /dev/null -w "%{http_code}" http://localhost:5173` returns `200`.
    - `docker compose logs backend 2>&1 | grep -c "alembic"` >= 1 (migrations actually ran in container).
    - `docker compose logs backend 2>&1 | grep -ci "error\|exception\|traceback"` equals 0.
    - `docker compose exec -T postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c '\dt'` lists `invoices`, `invoice_line_items`, `sender_allowlist`.
  </acceptance_criteria>
  <done>
    `docker compose up` brings up Postgres + FastAPI backend + Vite frontend cleanly. Alembic migrations run inside the backend container before Uvicorn starts. `GET /health` returns `allowlist_count: 0`. Vite scaffold renders on `:5173`. All Phase-1 ROADMAP success criteria 1, 2, 3 verified end-to-end.
  </done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 3: Walking Skeleton end-to-end verification + INF-03 negative test</name>
  <what-built>
    A fully wired Walking Skeleton: Docker Compose orchestrates 3 services (Postgres 16, FastAPI/uvicorn on :8000, Vite/React on :5173). Alembic migrations run on container boot creating `invoices`, `invoice_line_items`, `sender_allowlist`. `GET /health` performs a real Postgres round-trip. A React scaffold loads in the browser.
  </what-built>
  <how-to-verify>
    1. From a clean state, run `docker compose down -v` (removes the postgres volume so we test first-boot from empty).
    2. Run `docker compose up` and watch logs. Expected: postgres reaches healthy → backend logs `alembic upgrade head` running, then `Uvicorn running on http://0.0.0.0:8000` → frontend logs `VITE v8.x.x ready`.
    3. In a browser, open http://localhost:8000/health. Expected JSON: `{"status":"ok","allowlist_count":0,"db":"connected"}`.
    4. In a browser, open http://localhost:5173. Expected: React page renders the text "Compras Agent" and "Phase 1 — Walking Skeleton".
    5. Insert one allowlist row to prove DB writes work end-to-end:
       `docker compose exec -T postgres psql -U compras -d compras -c "INSERT INTO sender_allowlist (phone_number, display_name) VALUES ('+5491100000000', 'Smoke test');"`
       Then re-curl `http://localhost:8000/health` — `allowlist_count` should now be `1`.
    6. **INF-03 negative test:** `docker compose down`, then comment out `OPENAI_API_KEY` in `.env`. Run `docker compose up backend`. Expected: backend container exits with non-zero code and stderr/logs contain a Pydantic `ValidationError` mentioning `openai_api_key`. Restore the `.env` line after.
    7. `docker compose down` to clean up.
  </how-to-verify>
  <resume-signal>Type "approved" if all 6 checks pass, or describe which check failed and what the actual behavior was.</resume-signal>
</task>

</tasks>

<threat_model>

## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| host → container | Docker Compose mounts source via volumes (`./backend:/app`, `./frontend/src:/app/src`); read/write trust is dev-machine scoped. |
| container ↔ container | postgres ↔ backend over the default compose network (`postgres` hostname); no TLS — acceptable for local dev only. |
| browser → backend (via Vite proxy) | Vite dev-server proxies `/health` and `/api` to backend; same trust boundary as direct backend access. |
| process env → containers | `.env` file is the secrets source (gitignored). Compose substitutes into env vars at container start. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-02-01 | Information Disclosure | `.env` committed by accident | mitigate | `.gitignore` from Plan 01 already lists `.env`; acceptance criterion in Task 1 runs `git check-ignore .env`. README also instructs `cp .env.example .env`. |
| T-02-02 | Information Disclosure | Backend container logs | mitigate | `app/main.py` logs only `log_level` at startup, never `database_url` / `openai_api_key` / `whatsapp_token`. Grep-based acceptance criterion in Plan 02 Task 1 enforces this. |
| T-02-03 | Spoofing | Webhook endpoints | accept | No webhook endpoints exist in Phase 1. INF-02 (HMAC verification) is Phase 3 scope. |
| T-02-04 | Denial of Service | Backend container fails to start on first boot due to Postgres-not-ready | mitigate | `condition: service_healthy` + `pg_isready` healthcheck (RESEARCH.md Pitfall 2). Acceptance criterion `docker compose up -d --wait` proves the chain works. |
| T-02-05 | Denial of Service | Alembic migration hangs in container | mitigate | Migrations run via shell entrypoint `bash -c "alembic upgrade head && uvicorn ..."` — NOT via FastAPI lifespan (alembic#1483 hang documented in RESEARCH.md anti-patterns). `pool.NullPool` already in env.py from Plan 01. |
| T-02-06 | Tampering | Vite dev-server proxy lets external requests reach backend | accept | Local-dev only. Vite dev port `:5173` is bound to host but listens on `localhost`; production deployment is out of Phase 1 scope. |
| T-02-07 | Information Disclosure | Postgres :5432 bound to host | accept | Local-dev convenience for `psql` debugging. Production would use Docker-internal network only; documented as out-of-scope deferral. |
| T-02-08 | Tampering | Volume-mounted source code in container | accept | Dev-only hot-reload — `./backend:/app` and `./frontend/src:/app/src` are dev conveniences. Production Dockerfile would `COPY` only, no volume mount. Documented in CLAUDE.md decision log. |

</threat_model>

<verification>
- `docker compose config -q` exits 0.
- `docker compose up -d --wait` exits 0; all services reach healthy.
- `curl -fsS http://localhost:8000/health` returns 200 with `"allowlist_count":0`.
- `curl -fsS -o /dev/null -w "%{http_code}" http://localhost:5173` returns `200`.
- `pytest backend/tests/ -v` (full suite) green — config, db, extraction_models, health.
- Human checkpoint (Task 3) confirms first-boot from empty volume works and INF-03 fails-fast when an env var is removed.
</verification>

<success_criteria>
- ROADMAP Phase 1 SC-1: `docker compose up` starts FastAPI, Postgres, frontend without errors. ✓
- ROADMAP Phase 1 SC-2: All tables (invoices, invoice_line_items, sender_allowlist) exist after migrations. ✓ (verified via `\dt`)
- ROADMAP Phase 1 SC-3: Allowlist table can be seeded with phone numbers. ✓ (Task 3 step 5)
- ROADMAP Phase 1 SC-4: `ExtractedInvoice` Pydantic model + enums importable and instantiable without errors. ✓ (Plan 01 tests)
- ROADMAP Phase 1 SC-5: App refuses to start with required env var missing. ✓ (Task 3 step 6 INF-03 negative test)
- INF-01 closed end-to-end: allowlist table created by Alembic migration, accessible via /health and direct psql.
- INF-03 closed end-to-end: Settings ValidationError aborts container startup when secret is missing.
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundation/01-02-SUMMARY.md` capturing: services wired, port mappings, env var contract, ROADMAP SC-1..5 status, INF-01 / INF-03 verification evidence, and any deviations from RESEARCH.md patterns or this plan's acceptance criteria.
</output>
