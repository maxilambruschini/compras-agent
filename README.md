# Compras Agent

A WhatsApp-to-database invoice capture system for Argentine companies. Employees photograph invoices and send them via WhatsApp; an AI agent extracts structured data and stores it in Postgres. Managers review and manage captured invoices via a React web UI.

## Prerequisites

- Docker 27+
- Docker Compose v2.32+
- pnpm 10+ (only for local non-container development)

## Quickstart

```bash
cp .env.example .env
# Edit .env — replace OPENAI_API_KEY and WhatsApp credentials with real values
docker compose up
```

Then:
- API health check: `curl http://localhost:8000/health`
- Frontend: open http://localhost:5173

## Architecture

Three services managed by Docker Compose:

| Service | Port | Description |
|---------|------|-------------|
| postgres | :5432 | Postgres 16 — invoice records, line items, sender allowlist |
| backend | :8000 | FastAPI + Uvicorn — extraction API, webhook receiver |
| frontend | :5173 | Vite + React — admin review UI |

Alembic migrations run automatically on backend container boot (`alembic upgrade head` in entrypoint).

## Phase 1 scope

See `.planning/phases/01-foundation/01-SKELETON.md` for Phase 1 scope and decisions.
