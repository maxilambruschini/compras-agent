# Phase 1: Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-13
**Phase:** 1-Foundation
**Areas discussed:** Project layout, DB migrations approach, Pydantic model design, Stub frontend

---

## Project Layout

| Option | Description | Selected |
|--------|-------------|----------|
| backend/ + frontend/ | Two top-level sibling dirs. Standard separation, easy Docker-ize. | ✓ |
| app/ monolith dir | Single app/ containing both. Messier Docker build contexts. | |
| Flat root | Python at root alongside frontend src/. Gets messy fast. | |

**User's choice:** `backend/ + frontend/`
**Notes:** User confirmed migrations would be handled by Alembic when asked about migration directory placement ("Doesn't alembic handle those decisions?"). Internal Python package structure delegated to Claude.

| Option | Description | Selected |
|--------|-------------|----------|
| backend/app/ package | Standard FastAPI layout — app/models/, app/routers/, app/services/, app/db/ | ✓ (Claude) |
| backend/src/ package | Extra import layer, less common in FastAPI projects. | |
| You decide | Claude picks conventional layout. | ✓ |

**User's choice:** Delegated to Claude

---

## DB Migrations Approach

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-run on container startup | `alembic upgrade head` before Uvicorn. Always current after `docker compose up`. | ✓ |
| Manual via docker exec | Developer runs explicitly. More control, not automatic. | |
| Separate init container | Cleanest but complex for a demo build. | |

**User's choice:** Auto-run on container startup

| Option | Description | Selected |
|--------|-------------|----------|
| SQLAlchemy ORM models | `app/db/models.py`, autogenerate migrations. Standard FastAPI + Postgres. | ✓ |
| SQLAlchemy Core | Table() objects. Less common in FastAPI. | |
| Raw SQL only | No autogenerate, no ORM. | |

**User's choice:** SQLAlchemy ORM models

| Option | Description | Selected |
|--------|-------------|----------|
| ORM for both schema and queries | AsyncSession in FastAPI routes. Type-safe, consistent. | ✓ |
| ORM for schema only, raw SQL for queries | Two patterns to maintain. | |
| You decide | Claude picks standard approach. | |

**User's choice:** ORM for both schema and queries

---

## Pydantic Model Design

| Option | Description | Selected |
|--------|-------------|----------|
| Nested: header + List[LineItem] | ExtractedInvoice + line_items: List[LineItem]. Mirrors REQUIREMENTS.md EXT-01/02 vs EXT-03/04 split. | ✓ |
| Flat single model | All fields at one level. Awkward for multi-item invoices. | |
| Separate models per doc type | FacturaExtracted, RemitoExtracted, etc. Complicates generic pipeline. | |

**User's choice:** Nested header + List[LineItem]

| Option | Description | Selected |
|--------|-------------|----------|
| Python str Enum | `TipoComprobante(str, Enum)` with readable labels. Postgres stores readable values. | ✓ |
| Plain string field | No enforcement. Risk of inconsistent values. | |
| Integer AFIP codes | Requires post-processing mapping; GPT-4o doesn't output codes naturally. | |

**User's choice:** Python str Enum

| Option | Description | Selected |
|--------|-------------|----------|
| Separate files: extraction.py vs db/models.py | Clean separation of GPT-4o contracts vs DB contracts. | ✓ |
| Same file app/models.py | Mixes two concerns, grows messy. | |
| You decide | Claude picks the layout. | |

**User's choice:** Separate files

---

## Stub Frontend

| Option | Description | Selected |
|--------|-------------|----------|
| Nginx static HTML placeholder | Tiny, starts instantly, no Node.js needed. | |
| Vite + React scaffold | Real frontend structure, heavier, requires Node.js. | ✓ |
| No frontend in Phase 1 | Skip entirely, add in Phase 4. | |

**User's choice:** Vite + React scaffold
**Notes:** User specified **pnpm** explicitly: "We need to make sure we use pnpm rather than using regular npm since it's much better."

| Option | Description | Selected |
|--------|-------------|----------|
| Vite dev server (`pnpm dev`) | Hot-reload, port 5173, volume-mounted source. | ✓ |
| Build + serve static | Every change needs rebuild. Slow iteration. | |
| You decide | Claude picks dev-friendly approach. | |

**User's choice:** Vite dev server with `pnpm dev`

---

## Claude's Discretion

- Internal Python package subdir structure within `backend/app/` (user said "you decide") — Claude will use conventional FastAPI layout: `app/models/`, `app/routers/`, `app/services/`, `app/db/`.

## Deferred Ideas

- Frontend tech stack details (component library, routing, state management) — deferred to Phase 4 per earlier agreement.
