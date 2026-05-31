# Phase 4: Admin UI - Context

**Gathered:** 2026-05-31
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous)

<domain>
## Phase Boundary

Deliver the read-only web UI for managers/accountants to view captured gastos and caja
closings. This is a **full-stack** phase: the frontend is currently a bare Vite+React
"Walking Skeleton" (only App.tsx/main.tsx, deps = react/react-dom) and there are **no
backend read endpoints** yet (backend exposes only /health, the two webhooks, and
/gastos/prompt). So Phase 4 builds: (1) FastAPI read endpoints for gastos + cierres,
(2) the React pages that consume them, (3) the dev wiring (Vite proxy + FastAPI CORS).

**In scope:**
- Backend read API: `GET /gastos` (list, filterable/searchable), `GET /gastos/{id}` (detail),
  `GET /gastos/{id}/ticket` (streams the stored ticket image), `GET /cierres` (list).
  Committed records only — never expose `conversations.draft_gasto`.
- Frontend: Gastos list page (with filter/search), Gasto detail page (incl. ticket image),
  Cierres list page (read-only). Routing + data fetching + API client.
- Dev wiring: Vite dev proxy `/api → backend:8000`, FastAPI CORS middleware (none exists today).
- Requirements: UI-01, UI-02.

**Out of scope (deferred / not built):**
- Editing or deleting gastos/cierres (REQUIREMENTS Future — read-only for v2.0).
- Admin authentication / login (PROJECT.md locked decision: deferred for demo).
- Pagination, real-time updates, daily/weekly summaries.
- Adding `lugar` or a ticket-extraction-JSON column to the schema (see Decisions — these
  ROADMAP-SC fields were never persisted; SC is being corrected to match the real schema).
</domain>

<decisions>
## Implementation Decisions

### Backend Read API
- **New read router** (e.g. `backend/app/routers/admin.py` or `read.py` — planner's choice):
  `GET /gastos`, `GET /gastos/{id}`, `GET /gastos/{id}/ticket`, `GET /cierres`.
  Mounted under the `AGENT_MODE=='gastos'` seam alongside the other gastos routes.
- **Committed records only** — query the `gastos` / `caja_cierres` tables directly; never
  surface `conversations.draft_gasto` (in-progress drafts).
- **Server-side filtering/search:** `GET /gastos?from=<date>&to=<date>&q=<text>` — date range
  on `fecha` + case-insensitive substring search on `concepto`. `q` matches concepto
  (there is no separate `lugar` column — see Data Display).
- **No pagination** — return all matching rows, newest first (`created_at` desc). Volume is
  <20/day (PROJECT.md), so unbounded return is fine for the demo.
- **Ticket image:** `GET /gastos/{id}/ticket` streams the file from `LocalStorageBackend`
  using the gasto's `ticket_image_path`; 404 when the gasto has no ticket. (Not a static mount,
  not base64 — keeps access going through FastAPI, consistent with the StorageBackend abstraction.)
- Pydantic response models for gasto list/detail and cierre list (Decimal serialized as string
  or number — planner's choice, but must not lose precision).

### Frontend Stack & Wiring
- **Add libraries:** `react-router-dom` (routing: Gastos list ↔ detail ↔ Cierres),
  `@tanstack/react-query` (server-state: useQuery for reads, automatic staleness), and a small
  typed `fetch` API client module. Matches the CLAUDE.md recommended stack.
- **Dev wiring:** Vite dev proxy maps `/api` → the backend (`http://backend:8000` in Docker /
  `localhost:8000` locally); API base configurable via `VITE_API_URL`. **Add CORS middleware
  to FastAPI** (`fastapi.middleware.cors.CORSMiddleware`) — none exists today; allow the
  frontend dev origin.
- **No auth** — open admin UI (PROJECT.md locked decision; login deferred to v3).
- **Data freshness:** manual refresh + react-query default staleness/refetch. No polling
  (real-time is out of scope per PROJECT.md).

### Data Display & Schema Reality
- **Schema mismatch resolved — show real fields only.** The ROADMAP SC mentioned a `lugar`
  column and a "ticket extraction JSON"; **neither is persisted** (the `Gasto` model is
  `fecha, concepto, monto, ticket_image_path, sender_phone, created_at`; Phase 2 vision
  extracted the amount only, not a stored JSON). The UI shows the actual fields:
  - **Gastos list columns:** fecha, concepto, monto, ticket indicator (has-image yes/no), sender_phone.
  - **Gasto detail:** all of the above + the ticket image (if `ticket_image_path` present).
    No "ticket extraction JSON" panel (none exists).
  - `lugar`/proveedor is part of the free-text `concepto` — no separate column.
  **ROADMAP Phase 4 success criteria must be updated** to match (drop `lugar` column and
  ticket-JSON references). Track as a plan task.
- **Cierres page columns:** fecha, hora_cierre ("12:00"/"17:00"), efectivo_en_caja, sender_phone.
  **Strictly read-only** — no edit/delete controls rendered.
- **Default order:** newest first (`created_at` desc) on both lists.
- **States:** standard minimal — loading spinner, "no records" empty state, inline error message.

### Claude's Discretion
- Read-router filename/module layout; exact Pydantic response model field names.
- API client module shape; react-query key structure; route paths.
- Decimal serialization format (string vs number) — must preserve precision.
- All visual/layout/interaction/styling detail → defer to the UI-SPEC (UI design contract).
- Whether ticket-indicator is an icon, badge, or text.
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets / Current State
- `frontend/` — Vite + React 19 + TS scaffold. `src/App.tsx` is a placeholder ("Phase 1 —
  Walking Skeleton"); `src/main.tsx` mounts it. Deps: only react + react-dom. pnpm lockfile.
  Scripts: dev (vite), build (tsc -b && vite build), lint, preview. **No router, no
  react-query, no API client, no `.env`, no vite proxy yet.**
- `backend/app/db/models.py` — `Gasto` (fecha, concepto, monto Numeric(14,2),
  ticket_image_path Optional, sender_phone, created_at) and `CajaCierre` (fecha, hora_cierre
  String(5), efectivo_en_caja Numeric(14,2), sender_phone, created_at) both exist with
  `ix_gastos_fecha` / `ix_caja_cierres_fecha` indexes. No `lugar`, no extraction-JSON column.
- `backend/app/services/storage.py` `LocalStorageBackend` — used to retrieve the stored ticket
  image file for the `GET /gastos/{id}/ticket` stream.
- `backend/app/services/gasto.py` `GastoService`, `backend/app/db/session.py` `get_db`
  (async session DI) — reuse for the read endpoints' DB access.
- `backend/app/main.py` `create_app()` — the `AGENT_MODE=='gastos'` seam mounts gastos +
  prompt routers; the new read router mounts here too. **No CORS middleware present — add it.**
- `backend/app/routers/health.py` — simple `@router.get` pattern to mirror for read endpoints.

### Established Patterns
- FastAPI async route handlers with `Depends(get_db)` async session.
- Pydantic v2 models for request/response.
- Decimal for money (Numeric(14,2)) — never float; preserve precision across the API boundary.
- Backend runs in Docker (compose); frontend dev server at :5173, backend at :8000.

### Integration Points
- Frontend → backend over HTTP: Vite dev proxy `/api` + CORS on FastAPI.
- Read endpoints query `gastos` / `caja_cierres`, excluding `conversations` drafts.
- Ticket image path stored on `Gasto.ticket_image_path` → streamed via `LocalStorageBackend`.
</code_context>

<specifics>
## Specific Ideas

- The UI is the accountant/manager's window into what the WhatsApp bot captured — it must show
  only **committed** records (what actually landed in the DB), never in-progress conversation
  drafts. That confirmed-only boundary is the core correctness property of this phase.
- Read-only by design: this phase intentionally has no write path. Edits/deletes are a future
  milestone; surfacing edit controls now would imply a capability that isn't built.
</specifics>

<deferred>
## Deferred Ideas

- Edit/delete gastos and cierres from the UI (REQUIREMENTS Future / v2.x).
- Admin authentication (email/password) — deferred to v3.
- Pagination, daily/weekly expense summaries, real-time updates.
- Adding `lugar` and a ticket-extraction-JSON column (schema change) — not pursued; the UI
  reflects the real schema instead.
- Cross-checking declared vs extracted ticket amounts (REQUIREMENTS Future).
</deferred>

---

*Phase: 4-admin-ui*
*Context gathered: 2026-05-31 (smart discuss, autonomous mode)*
