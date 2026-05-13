# Walking Skeleton — Compras Agent

**Phase:** 1
**Generated:** 2026-05-13

## Capability Proven End-to-End

A developer runs `docker compose up` and `curl http://localhost:8000/health` returns `{"status": "ok", "allowlist_count": 0, "db": "connected"}` — proving FastAPI → SQLAlchemy AsyncSession → Postgres round-trip works and Alembic migrations created the `sender_allowlist` table on container boot.

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Backend framework | FastAPI 0.136.1 + Uvicorn 0.38.0 (async) | Native Pydantic v2; required by pywa (Phase 3) and OpenAI structured outputs (Phase 2) |
| Data layer | Postgres 16 + SQLAlchemy 2.0.49 (asyncpg 0.31.0) | Per CLAUDE.md stack lock; AsyncSession across all routes (D-06) |
| Migrations | Alembic 1.18.4 with async `env.py` (`asyncio.run` + `run_sync`) | D-04, D-05; runs in Docker entrypoint (`alembic upgrade head &&`) before Uvicorn — avoids alembic#1483 hang |
| Settings/Secrets | pydantic-settings 2.14.1 BaseSettings, required fields (no defaults) | INF-03 fail-fast; `.env` for dev, env vars in prod |
| Frontend framework | React 19 + Vite 8 + TypeScript 5 + pnpm 10 | D-10, D-11, D-12; full scaffold in Phase 1, real screens in Phase 4 |
| Deployment | `docker compose up` — Postgres + backend + frontend containers, hot-reload volumes | Per ROADMAP; single command starts everything |
| Directory layout | `backend/app/{config,db,models,routers,services}/` + `frontend/src/`; sibling repos at root | D-01, D-02 |
| Migration trigger | Docker compose `command: bash -c "alembic upgrade head && uvicorn ..."` | D-05 |
| Postgres readiness | `pg_isready` healthcheck + `depends_on: condition: service_healthy` | RESEARCH.md Pitfall 2 |
| Logging | structlog 25.5.0 JSON output | RESEARCH.md — production-ready from day one |

## Stack Touched in Phase 1

- [x] Project scaffold — `backend/` (Python 3.12, FastAPI, SQLAlchemy, Alembic, pytest), `frontend/` (Vite + React + TS via pnpm)
- [x] Routing — `GET /health` in `backend/app/routers/health.py`
- [x] Database — real READ from `sender_allowlist` (count query in /health). Schema created by Alembic migration on container boot. Write path proven via `pytest` allowlist CRUD test against a test DB.
- [x] UI — Vite dev server boots on `:5173` and renders the React scaffold; functional buttons/forms wired to API are Phase 4 work.
- [x] Deployment — `docker compose up` (local dev) is the documented full-stack run command. No remote deployment in Phase 1.

## Out of Scope (Deferred to Later Slices)

- AI extraction logic (GPT-4o vision, prompt design, ExtractionService) → Phase 2
- WhatsApp webhook receipt, HMAC verification, pywa handlers → Phase 3
- Authentication (UI-07) → v2 (deferred per ROADMAP)
- Admin UI screens (invoice list, detail, edit, delete) → Phase 4
- File storage backend implementation (StorageBackend abstraction concretes) → Phase 2
- Background task queue / Celery — using FastAPI BackgroundTasks (Phase 3)
- Multi-tenancy, AFIP QR decoding, CUIT mod-11 validation, Twilio gateway → v2
- Document-level totals, supplier master table → v2 / out of scope

## Subsequent Slice Plan

Each later phase adds one vertical slice on top of this skeleton without altering its architectural decisions:

- **Phase 2:** Developer passes an invoice image to `ExtractionService.extract(image_bytes)` and receives a validated `ExtractedInvoice` with confidence score. StorageBackend stores the original file. No WhatsApp involved.
- **Phase 3:** Allowlisted phone number sends an invoice photo on WhatsApp → webhook receives it (HMAC validated) → background task downloads + extracts + stores → reply sent. End-to-end WhatsApp → DB.
- **Phase 4:** Manager opens the React UI, sees paginated invoices, filters by proveedor/fecha/status, opens detail, edits fields, deletes records. Reads/writes via FastAPI routes added in this phase.
