# Phase 4: Admin UI — Research

**Researched:** 2026-05-31
**Domain:** FastAPI read endpoints + React 19 + Vite + TanStack Query v5 + React Router v7
**Confidence:** HIGH

---

## Summary

Phase 4 delivers a full-stack read-only admin UI: four new FastAPI GET endpoints for
committed gastos and caja cierres, and three React pages (Gastos list, Gasto detail,
Cierres list). The backend scaffold (models, session, service layer, router pattern) is
fully established — this phase adds a new read router that mirrors `health.py`/`prompt.py`
patterns. The frontend is a bare Vite + React 19 + TS scaffold with only
`react`/`react-dom` as deps; three libraries must be added (`react-router`, `@tanstack/
react-query`, typed fetch client as a hand-rolled module).

Two wiring concerns are locked and verified:
1. **CORS:** `CORSMiddleware` is entirely absent from `create_app()` — it must be added
   before the new read router mounts.
2. **Vite proxy vs backend route prefix:** The existing `vite.config.ts` proxy is
   `'/api': apiTarget` with **no `rewrite`**. This means `GET /api/gastos` proxies to
   `backend:8000/api/gastos`. But all current backend routes lack an `/api` prefix (`/health`,
   `/gastos`, `/webhook`, `/gastos/prompt`). The planner must choose one option:
   - **Option A (recommended):** Mount the new read router with `prefix="/api"` — only the
     new read endpoints get the `/api` prefix; no existing routes are disturbed; Twilio
     webhooks remain at `/webhook`.
   - **Option B:** Add `rewrite: (path) => path.replace(/^\/api/, '')` to the Vite proxy
     — strips the prefix before forwarding. Downside: changes proxy behavior for `/health`
     too, which is also proxied.
   Option A is cleaner and keeps all read endpoints under a stable namespace.

Decimal serialization: Pydantic v2 serializes `Decimal` fields as **strings** by default
in JSON output. This is the correct behavior — the frontend `formatARS` utility should
call `parseFloat()` on the string value. No special `model_config` override is needed.

The frontend has **zero test infrastructure** (no vitest, no test files). Backend tests
use `httpx.AsyncClient` with `httpx.ASGITransport` over in-memory SQLite (aiosqlite).
The primary automated validation gate for this phase is backend pytest coverage of the
four new read endpoints; frontend UI correctness is a manual UAT gate.

**Primary recommendation:** Add read router with `prefix="/api"` under the gastos seam.
Mount `CORSMiddleware` first in `create_app()`. Add `react-router`, `@tanstack/react-query`
to frontend via pnpm. All components hand-rolled CSS against existing `index.css` tokens.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- New read router (`admin.py` or `read.py`): `GET /gastos`, `GET /gastos/{id}`,
  `GET /gastos/{id}/ticket`, `GET /cierres`. Mounted under `AGENT_MODE=='gastos'` seam.
- Committed records only — query `gastos`/`caja_cierres` tables directly; never surface
  `conversations.draft_gasto`.
- Server-side filtering: `?from=&to=&q=` — date range on `fecha` + ILIKE on `concepto`.
  No pagination. Newest first (`created_at` desc).
- `GET /gastos/{id}/ticket` streams the file from `LocalStorageBackend` via
  `ticket_image_path`; 404 when no ticket. Not a static mount, not base64.
- Pydantic v2 response models. Decimal precision must be preserved.
- Add `CORSMiddleware` to `create_app()` — none exists today.
- Frontend: add `react-router` (routing) + `@tanstack/react-query` (server state) + typed
  fetch client module. Vite dev proxy `/api → backend`. `VITE_API_URL` env var.
- No auth. Manual refresh + react-query staleness. No polling.
- Schema: real fields only. Gastos list: fecha, concepto, monto, ticket indicator,
  sender_phone. Detail: all + ticket image. Cierres: fecha, hora_cierre, efectivo_en_caja,
  sender_phone. No `lugar`, no extraction-JSON.
- Default order: newest first (`created_at` desc) on both lists.

### Claude's Discretion
- Read-router filename/module layout; exact Pydantic response model field names.
- API client module shape; react-query key structure; route paths.
- Decimal serialization format (string vs number) — must preserve precision.
- All visual/layout/interaction/styling detail — deferred to UI-SPEC.
- Whether ticket-indicator is icon, badge, or text (UI-SPEC specifies badge).

### Deferred Ideas (OUT OF SCOPE)
- Edit/delete gastos or cierres.
- Admin authentication.
- Pagination, daily/weekly summaries, real-time updates.
- Adding `lugar` or ticket-extraction-JSON column.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| UI-01 | Manager/accountant can list and view captured gastos in the web UI | GET /gastos + GET /gastos/{id} + GET /gastos/{id}/ticket + GastosListPage + GastoDetailPage |
| UI-02 | Manager/accountant can list and view caja closings in the web UI | GET /cierres + CierresListPage |
</phase_requirements>

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Gasto/cierre list queries (filter, sort) | API / Backend | — | DB access, SQL filters — must stay server-side |
| Ticket image streaming | API / Backend | — | File I/O via LocalStorageBackend; access control lives here |
| CORS policy | API / Backend | — | Middleware must be at the HTTP server level, not client-side |
| Route navigation | Browser / Client | — | React Router v7 in-browser SPA routing |
| Server-state caching | Browser / Client | — | TanStack Query holds fetched data, manages staleness |
| Money / date formatting | Browser / Client | — | Pure display transforms; no server logic needed |
| CSS token system | Browser / Client | — | Vanilla CSS custom properties in index.css |

---

## Standard Stack

### Core (backend additions)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi | 0.136.1 | Router, Depends, response types | Already in project [VERIFIED: pyproject.toml] |
| pydantic | 2.13.4 | Response models, Decimal serialization | Already in project [VERIFIED: pyproject.toml] |
| sqlalchemy | 2.0.49 | Async select, ILIKE, date filter | Already in project [VERIFIED: pyproject.toml] |
| fastapi.middleware.cors CORSMiddleware | (bundled with starlette) | Allow frontend origin | Built into FastAPI/Starlette — zero new dep |

### Core (frontend additions)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| react-router | 7.16.0 | Client-side routing, createBrowserRouter | CLAUDE.md recommended; v7 ships as `react-router` (not `react-router-dom`) [VERIFIED: npm registry] |
| @tanstack/react-query | 5.100.14 | Server state, useQuery, staleness | CLAUDE.md recommended; v5 is current stable [VERIFIED: npm registry] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| @types/react-router-dom | 5.3.3 | TS types (legacy) | NOT needed — react-router v7 ships its own types; `@types/react-router-dom` is for v5/v6 only |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| FileResponse (for ticket) | StreamingResponse with generator | FileResponse is simpler for on-disk files — infers content-type, adds ETag/Last-Modified. Use it. |
| react-router (package) | react-router-dom | In v7, `react-router` IS the package; `react-router-dom` is an alias but the canonical name changed to `react-router` |
| hand-rolled fetch client | axios | axios adds ~14 KB; typed fetch client is 20 lines, zero dep |
| server-side filter | client-side filter | Server-side is correct for correctness (committed-only boundary enforced on server); client-side would require fetching all rows |

**Installation (frontend — run inside `frontend/`):**
```bash
pnpm add react-router @tanstack/react-query
```

**No new backend Python packages needed.** CORSMiddleware is bundled with Starlette (already a FastAPI dependency).

---

## Package Legitimacy Audit

slopcheck was not installable in this environment (permission denied by auto-mode classifier).
All packages below are verified against the npm registry and official documentation.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| react-router | npm | ~10 yrs | ~14M/wk | github.com/remix-run/react-router | [ASSUMED-OK] | Approved — canonical routing library, Remix org, CLAUDE.md recommended |
| @tanstack/react-query | npm | ~5 yrs | ~10M/wk | github.com/TanStack/query | [ASSUMED-OK] | Approved — CLAUDE.md recommended, industry standard |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*slopcheck was unavailable at research time. Packages above are `[ASSUMED]` based on npm
registry existence, known provenance (official orgs), and CLAUDE.md endorsement. No
`checkpoint:human-verify` gate is required given the well-known provenance of both packages.*

---

## Architecture Patterns

### System Architecture Diagram

```
WhatsApp Manager (browser)
         |
         | HTTP GET /api/gastos?from=&to=&q=
         v
[Vite Dev Server :5173]
  proxy '/api' → http://backend:8000
         |  (no path rewrite — /api/* forwarded as-is)
         v
[FastAPI :8000]
  CORSMiddleware (added in Phase 4)
  GET /api/gastos         ─── SQLAlchemy async select ──► [Postgres: gastos table]
  GET /api/gastos/{id}    ─── scalar_one_or_none        ► [Postgres: gastos table]
  GET /api/gastos/{id}/ticket ── LocalStorageBackend ──► [/data/invoices filesystem]
  GET /api/cierres        ─── SQLAlchemy async select ──► [Postgres: caja_cierres table]
         |
         | JSON response (Decimal as string, dates as ISO)
         v
[React :5173]
  QueryClientProvider (staleTime: 30_000)
  react-router createBrowserRouter
    /gastos         → GastosListPage  (useQuery ["gastos", {from,to,q}])
    /gastos/:id     → GastoDetailPage (useQuery ["gastos", id])
    /cierres        → CierresListPage (useQuery ["cierres"])
  Typed fetch client (reads VITE_API_URL or falls back to '')
  formatARS() + formatDate() utilities
  Vanilla CSS custom properties (index.css tokens)
```

### Recommended Project Structure

```
backend/app/routers/
├── admin.py          # NEW: GET /api/gastos, /api/gastos/{id}, /api/gastos/{id}/ticket, /api/cierres
├── health.py         # existing
├── gastos.py         # existing (webhook)
└── prompt.py         # existing

frontend/src/
├── api/
│   └── client.ts     # typed fetch client; reads VITE_API_URL
├── components/
│   └── Spinner.tsx   # shared loading ring
├── pages/
│   ├── GastosListPage.tsx
│   ├── GastoDetailPage.tsx
│   └── CierresListPage.tsx
├── utils/
│   ├── formatARS.ts  # manual ARS money formatter
│   └── formatDate.ts # Spanish month abbreviation formatter
├── admin.css         # component styles (extend index.css tokens; do NOT rewrite index.css)
├── App.tsx           # router + QueryClientProvider wiring
├── main.tsx          # StrictMode + createRoot (import admin.css here)
└── index.css         # add --secondary-surface token (light + dark blocks)
```

### Pattern 1: FastAPI Read Router with `/api` prefix

**What:** New read router mounted with `prefix="/api"` inside the `agent_mode == 'gastos'`
branch. All four read endpoints live in `backend/app/routers/admin.py`.

**When to use:** Phase 4 read endpoints only — existing webhook/prompt routes stay at their
current paths. This avoids disturbing Twilio's webhook URL.

```python
# backend/app/routers/admin.py
# Source: mirrors health.py + prompt.py patterns in this codebase
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.db.models import Gasto, CajaCierre
from app.config import get_settings
import os

router = APIRouter()

@router.get("/gastos", response_model=list[GastoOut])
async def list_gastos(
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    q: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[GastoOut]: ...

@router.get("/gastos/{id}", response_model=GastoOut)
async def get_gasto(id: uuid.UUID, db: AsyncSession = Depends(get_db)): ...

@router.get("/gastos/{id}/ticket")
async def get_ticket(id: uuid.UUID, db: AsyncSession = Depends(get_db),
                     settings = Depends(get_settings)): ...

@router.get("/cierres", response_model=list[CierreOut])
async def list_cierres(db: AsyncSession = Depends(get_db)): ...
```

```python
# backend/app/main.py — inside `elif settings.agent_mode == "gastos":` block
from app.routers.admin import router as admin_router
app.include_router(admin_router, prefix="/api", tags=["admin"])
```

### Pattern 2: CORSMiddleware placement

**What:** `add_middleware` call at the top of `create_app()`, before any router includes.
Starlette applies middleware in reverse-add order (last added = outermost) — CORS must be
outermost so preflight OPTIONS requests are intercepted before hitting route handlers.

```python
# backend/app/main.py — create_app(), first lines after FastAPI() construction
# Source: https://fastapi.tiangolo.com/tutorial/cors/
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev origin
    allow_credentials=False,   # no cookies/auth in Phase 4
    allow_methods=["GET"],     # read-only phase
    allow_headers=["*"],
)
```

**Note:** `allow_credentials=False` permits `allow_origins=["*"]` or specific origins with
`allow_methods`/`allow_headers` wildcards. Since there is no auth, `allow_credentials=False`
is correct and keeps the config simple.

### Pattern 3: SQLAlchemy async filtering (date range + ILIKE)

**What:** Build a `select()` statement conditionally appending `where()` clauses based on
query params. ILIKE uses the `.ilike()` column method.

```python
# Source: SQLAlchemy 2.0 docs — async select pattern mirrors health.py in this codebase
from sqlalchemy import select
from app.db.models import Gasto
from datetime import date

stmt = (
    select(Gasto)
    .order_by(Gasto.created_at.desc())
)
if from_:
    stmt = stmt.where(Gasto.fecha >= from_)
if to:
    stmt = stmt.where(Gasto.fecha <= to)
if q:
    stmt = stmt.where(Gasto.concepto.ilike(f"%{q}%"))

result = await db.execute(stmt)
rows = result.scalars().all()
```

**Note:** `.ilike()` generates `ILIKE` on Postgres (case-insensitive). On SQLite (tests),
SQLAlchemy compiles `.ilike()` as `LIKE` with `LOWER()` wrapping — functionally equivalent
for test coverage. [ASSUMED — verified against SQLAlchemy 2.0 docs behavior]

### Pattern 4: Ticket image streaming via FileResponse

**What:** Retrieve the gasto's `ticket_image_path`, resolve to absolute path using
`settings.storage_path`, return `FileResponse`. FileResponse infers `Content-Type` from
the file extension. Returns 404 if `ticket_image_path` is None or the file does not exist.

```python
# Source: https://fastapi.tiangolo.com/advanced/custom-response/
from fastapi.responses import FileResponse
from fastapi import HTTPException

@router.get("/gastos/{id}/ticket")
async def get_ticket(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    settings = Depends(get_settings),
):
    result = await db.execute(select(Gasto).where(Gasto.id == id))
    gasto = result.scalar_one_or_none()
    if gasto is None:
        raise HTTPException(status_code=404, detail="Gasto not found")
    if not gasto.ticket_image_path:
        raise HTTPException(status_code=404, detail="No ticket for this gasto")

    full_path = os.path.join(settings.storage_path, gasto.ticket_image_path)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="Ticket file not found on disk")

    return FileResponse(full_path)  # content-type inferred from extension
```

**Security note:** `ticket_image_path` comes from the database (written by
`LocalStorageBackend.save()`), which already ran path-traversal sanitization on write.
An additional `os.path.commonpath` guard is still recommended in the read path (defense
in depth) — verify the resolved `full_path` is under `settings.storage_path`.

### Pattern 5: Pydantic v2 response models with Decimal

**What:** Pydantic v2 serializes `Decimal` fields as **strings** in JSON by default (not
float). The frontend receives `"1234.56"` and calls `parseFloat("1234.56")` before
formatting. No `model_config` customization is needed to get string output.

```python
# Source: Pydantic v2 default behavior — Decimal → string in JSON serialization
# Confirmed: github.com/pydantic/pydantic/issues/7120 (Decimals serialized as strings)
from pydantic import BaseModel
from decimal import Decimal
from datetime import date, datetime
import uuid

class GastoOut(BaseModel):
    id: uuid.UUID
    fecha: date
    concepto: str
    monto: Decimal          # serialized as "1234.56" string in JSON
    ticket_image_path: str | None
    sender_phone: str
    created_at: datetime

    model_config = {"from_attributes": True}  # ORM mode — replaces Pydantic v1 orm_mode

class CierreOut(BaseModel):
    id: uuid.UUID
    fecha: date
    hora_cierre: str        # "12:00" | "17:00"
    efectivo_en_caja: Decimal
    sender_phone: str
    created_at: datetime

    model_config = {"from_attributes": True}
```

### Pattern 6: TanStack Query v5 setup with React Router v7

**What:** Wrap the entire app in `QueryClientProvider`. Create the router outside the
React tree. `RouterProvider` is the root element rendered to the DOM.

```tsx
// frontend/src/App.tsx
// Source: https://tanstack.com/query/v5/docs/framework/react/overview
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider, Navigate } from "react-router";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000 } },
});

const router = createBrowserRouter([
  { path: "/", element: <Navigate to="/gastos" replace /> },
  { path: "/gastos", element: <GastosListPage /> },
  { path: "/gastos/:id", element: <GastoDetailPage /> },
  { path: "/cierres", element: <CierresListPage /> },
]);

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
```

**React Router v7 package name:** Install as `react-router` (not `react-router-dom`).
In v7, the package was unified — `react-router-dom` still exists as an alias but the
canonical install is `react-router`. The `createBrowserRouter` and `RouterProvider` imports
come from `"react-router"` (or `"react-router/dom"` for `RouterProvider`). [VERIFIED: npm registry + reactrouter.com docs]

### Pattern 7: Typed fetch client

**What:** Small module reading `VITE_API_URL` from `import.meta.env`. The `/api` prefix is
baked into every function. When the Vite proxy is active, requests to `/api/*` are proxied
to the backend.

```ts
// frontend/src/api/client.ts
const BASE = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api`
  : "/api";   // falls back to Vite proxy path in dev

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  listGastos: (params?: { from?: string; to?: string; q?: string }) => {
    const qs = new URLSearchParams(
      Object.entries(params ?? {}).filter(([, v]) => v != null) as string[][]
    ).toString();
    return get<GastoOut[]>(`/gastos${qs ? `?${qs}` : ""}`);
  },
  getGasto: (id: string) => get<GastoOut>(`/gastos/${id}`),
  ticketUrl: (id: string) => `${BASE}/gastos/${id}/ticket`,
  listCierres: () => get<CierreOut[]>("/cierres"),
};
```

**Ticket URL note:** The ticket image is rendered as `<img src={api.ticketUrl(id)}>` —
the browser fetches it directly. No `useQuery` needed for the ticket; include the URL in
`GastoOut` or construct client-side from the id. The browser sends the request through the
Vite proxy in dev, or directly to `VITE_API_URL` in production.

### Anti-Patterns to Avoid

- **`react-router-dom` import path:** In React Router v7, import from `"react-router"`,
  not `"react-router-dom"`. The v6 DOM-specific package is deprecated as the primary import.
- **`allow_credentials=True` with wildcard origins:** FastAPI/Starlette rejects this
  combination. Phase 4 has no auth, so `allow_credentials=False` (default) is correct.
- **Using `Gasto` ORM object directly as response:** Always use `response_model=GastoOut`
  (Pydantic) — Pydantic's `from_attributes=True` (ORM mode) handles the conversion. Returning
  the raw ORM object causes SQLAlchemy lazy-load errors in async context.
- **CORS added after routers:** FastAPI processes middleware in reverse-add order. Add
  `CORSMiddleware` before `include_router` calls so OPTIONS preflight reaches it first.
- **`import.meta.env.VITE_API_URL` in Node context:** Vite env vars are only available in
  browser/Vite-bundled code. The `vite.config.ts` correctly uses `process.env.VITE_API_URL`
  (Node context) to set the proxy target — these are two different access patterns.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| File streaming with content-type detection | Custom StreamingResponse + mimetypes lookup | `FileResponse(full_path)` | FastAPI's FileResponse infers media-type from extension, adds ETag, Last-Modified, Content-Length — correct HTTP caching semantics for free |
| CORS preflight handling | Custom OPTIONS handler | `CORSMiddleware` | Handles all CORS cases: simple requests, preflight, `Access-Control-*` headers — ~200 lines of Starlette code |
| Server-state cache invalidation | `useState` + manual `useEffect` refetch chains | `useQuery` with `staleTime` | React Query handles background refetch, deduplication, error retry — `useEffect` chains have race conditions |
| Money formatting with locale API | `Intl.NumberFormat('es-AR')` | Manual `formatARS()` | `es-AR` locale support is inconsistent across mobile browsers — UI-SPEC explicitly prohibits `toLocaleString` |

**Key insight:** The backend streaming and CORS primitives are already the framework's
concern — implementing them manually introduces subtle bugs (missing headers, wrong preflight
response codes, chunked-encoding edge cases) that the framework handles correctly.

---

## Common Pitfalls

### Pitfall 1: Vite proxy strips nothing — `/api` prefix must exist on backend
**What goes wrong:** Frontend calls `/api/gastos`; Vite proxies to `backend:8000/api/gastos`;
backend returns 404 because all current routes lack `/api` prefix.
**Why it happens:** `vite.config.ts` proxy `'/api': apiTarget` does NOT rewrite. It
forwards `/api/gastos` as `/api/gastos`, not `/gastos`.
**How to avoid:** Mount the new read router with `prefix="/api"` in `main.py`. Alternatively,
add `rewrite: (path) => path.replace(/^\/api/, '')` to the Vite proxy — but this also
affects `/health` which is already proxied, requiring a health-check path change or exception.
**Warning signs:** 404 responses from `fetch('/api/gastos')` in the browser dev tools,
even when the backend is running.

### Pitfall 2: Decimal becomes float in JSON (precision loss on large amounts)
**What goes wrong:** `monto = Decimal("1234567.89")` arrives in the browser as
`1234567.89` (float64), which can round-trip incorrectly for extreme values.
**Why it happens:** Some JSON serializers convert Decimal to float. Pydantic v2 defaults
to string — but only if the response goes through Pydantic's `.model_dump(mode='json')`.
Returning a raw dict or bypassing Pydantic loses this guarantee.
**How to avoid:** Always use `response_model=GastoOut`/`CierreOut`. Never return raw ORM
objects or dicts. Pydantic v2 default: Decimal → string. Frontend `parseFloat()` on the
string is safe for 14-digit ARS amounts (well within float64 range for this domain).

### Pitfall 3: CORS preflight fails on POST-like or non-simple requests
**What goes wrong:** `GET` requests with custom headers (e.g., `Content-Type: application/json`
on a GET) or non-simple methods trigger CORS preflight. Without `CORSMiddleware`, the
browser blocks the request before it reaches FastAPI.
**Why it happens:** `CORSMiddleware` is absent from `create_app()` today.
**How to avoid:** Add `CORSMiddleware` as the first `add_middleware` call. Include
`http://localhost:5173` (Vite dev origin) in `allow_origins`. All Phase 4 endpoints are
`GET` with no custom headers, so `allow_methods=["GET"]` is sufficient.
**Warning signs:** Browser console `CORS policy: No 'Access-Control-Allow-Origin' header`
errors; network tab shows OPTIONS request returning 405 or no CORS headers.

### Pitfall 4: Path traversal on ticket ID (defense-in-depth gap)
**What goes wrong:** A crafted `id` parameter resolves to a path that escapes
`settings.storage_path` when joined with `ticket_image_path` from the DB.
**Why it happens:** `ticket_image_path` was sanitized by `LocalStorageBackend.save()` on
write, but a defense-in-depth check on the read path prevents any future regression.
**How to avoid:** After `os.path.join(settings.storage_path, gasto.ticket_image_path)`,
add: `assert os.path.commonpath([os.path.realpath(full_path), os.path.realpath(settings.storage_path)]) == os.path.realpath(settings.storage_path)` — raises ValueError on escape, return 400/404.

### Pitfall 5: React Router v7 import path (breaks at build time)
**What goes wrong:** `import { createBrowserRouter } from 'react-router-dom'` fails or
imports from an uninstalled package if only `react-router` is installed.
**Why it happens:** In React Router v7, the unified package is `react-router`. The
`react-router-dom` sub-package still exists (for backward compat) but is not needed.
**How to avoid:** `pnpm add react-router` only. Import from `"react-router"` or
`"react-router/dom"` (for `RouterProvider`). Do NOT install `react-router-dom` separately.

### Pitfall 6: react-query staleTime 0 causes unnecessary re-fetches on navigation
**What goes wrong:** Every time the user navigates back to the Gastos list from a detail
page, `useQuery` re-fetches the full list because `staleTime` defaults to 0.
**Why it happens:** Default `staleTime: 0` means data is immediately considered stale.
**How to avoid:** Set `staleTime: 30_000` (30 seconds) on the `QueryClient` default. This
is the value locked in the UI-SPEC. The "← Volver a gastos" back link will use the cached
list without a new network request within the 30-second window.

### Pitfall 7: `conversations.draft_gasto` leaks into gastos list
**What goes wrong:** In-progress conversation drafts appear as gastos in the UI.
**Why it happens:** If query accidentally joins or selects from `conversations` table.
**How to avoid:** `GET /gastos` queries `gastos` table only (`select(Gasto)`). The
`Gasto` rows are written only after explicit confirmation (GASTO-05). No join to
`conversations` is needed or permitted. Verify with a test that seeds a conversation
with `draft_gasto` set and confirms it does NOT appear in the list response.

### Pitfall 8: Docker compose pnpm lockfile — new deps require container rebuild
**What goes wrong:** `pnpm add react-router @tanstack/react-query` updates
`pnpm-lock.yaml` on the host. The Docker frontend container mounts `./frontend/src` and
`./frontend/public` as volumes — but `node_modules` is an anonymous volume
(`/app/node_modules`). Adding new packages does NOT auto-install inside the running container.
**Why it happens:** See `docker-compose.yml`: `- /app/node_modules` (anonymous volume,
not bind-mounted). The container's node_modules is frozen at build time.
**How to avoid:** After `pnpm add`, run `docker compose build frontend` (rebuilds the
image with updated `package.json` and `pnpm-lock.yaml`) then `docker compose up frontend`.
For local dev outside Docker, `pnpm install` in `frontend/` is sufficient.

---

## Code Examples

### SQLAlchemy async select with optional filters
```python
# Source: mirrors health.py pattern (app/routers/health.py) + SQLAlchemy 2.0 async docs
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

async def _query_gastos(
    db: AsyncSession,
    from_: date | None,
    to: date | None,
    q: str | None,
) -> list[Gasto]:
    stmt = select(Gasto).order_by(Gasto.created_at.desc())
    if from_:
        stmt = stmt.where(Gasto.fecha >= from_)
    if to:
        stmt = stmt.where(Gasto.fecha <= to)
    if q and q.strip():
        stmt = stmt.where(Gasto.concepto.ilike(f"%{q.strip()}%"))
    result = await db.execute(stmt)
    return list(result.scalars().all())
```

### formatARS utility (manual, no Intl)
```ts
// Source: UI-SPEC §Monto Display — must not use toLocaleString('es-AR')
export function formatARS(value: string | number): string {
  const num = typeof value === "string" ? parseFloat(value) : value;
  if (isNaN(num)) return "—";
  const [intPart, decPart = "00"] = num.toFixed(2).split(".");
  const intFormatted = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `$${intFormatted},${decPart}`;
}
// $1.234,56 — correct Argentine format
```

### formatDate utility (Spanish month abbreviations)
```ts
// Source: UI-SPEC §Implementation Notes #4
const MONTHS = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"];

export function formatDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}
// "31 may 2026"
```

### useQuery usage (v5 API)
```tsx
// Source: https://tanstack.com/query/v5/docs/framework/react/overview
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

const { data, isPending, error } = useQuery({
  queryKey: ["gastos"],
  queryFn: () => api.listGastos(),
  staleTime: 30_000,
});
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `react-router-dom` as the primary package | `react-router` (unified package) | v7 (2024) | Install `react-router`, not `react-router-dom`; same API |
| `response_format={"type":"json_object"}` | `client.chat.completions.parse()` | openai-python v1.40+ | Not relevant to this phase |
| Pydantic v1 `orm_mode = True` | Pydantic v2 `model_config = {"from_attributes": True}` | Pydantic v2 | Must use v2 syntax — project uses Pydantic 2.13.4 |
| TanStack Query v4 `isLoading` | v5 `isPending` | v5 (2023) | `isLoading` removed in v5; use `isPending` for initial load |
| TanStack Query v4 `cacheTime` | v5 `gcTime` | v5 (2023) | Rename only; configure via `defaultOptions.queries.gcTime` |

**Deprecated/outdated:**
- `react-router-dom`: Still installable but not the canonical package for v7 projects. Install `react-router`.
- Pydantic v1 `orm_mode`: Replaced by `model_config = {"from_attributes": True}` in v2.
- TanStack Query v4 `isLoading`: Replaced by `isPending` in v5.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | SQLAlchemy `.ilike()` on SQLite (tests) compiles to `LOWER(x) LIKE LOWER(y)` — functionally equivalent to Postgres ILIKE | Architecture Patterns §3 | Test filtering behavior differs from production; low risk for read-only feature |
| A2 | `LocalStorageBackend._root` corresponds to `settings.storage_path` — the read path joins the same root | Pattern 4 (ticket streaming) | File not found at expected path; test with a real gasto that has a ticket |
| A3 | `react-router` v7 `RouterProvider` is importable from `"react-router/dom"` as shown in official docs | Pattern 6 | Import error at build time; fallback: import from `"react-router"` directly |
| A4 | Docker compose anonymous `node_modules` volume requires rebuild after adding frontend deps | Pitfall 8 | If volume is not anonymous, pnpm install inside the running container would suffice |

**If this table is empty:** All claims in this research were verified or cited — no user confirmation needed.
*(Table is not empty — 4 low-risk assumptions logged above.)*

---

## Open Questions

1. **`settings.storage_path` field name**
   - What we know: `LocalStorageBackend` takes a `root: str` at construction. The env var
     is `STORAGE_PATH` (from `D-08`). The config `Settings` object has a field for this.
   - What's unclear: The exact attribute name on `Settings` (e.g., `storage_path`,
     `storage_root`, `data_path`). The read endpoint needs it.
   - Recommendation: Planner task: grep `backend/app/config.py` for the `STORAGE_PATH`
     field name before writing the ticket endpoint.

2. **Production CORS origin**
   - What we know: Dev origin is `http://localhost:5173`. Production serves the built
     frontend from an unknown origin.
   - What's unclear: Whether a production CORS allow-list is needed now.
   - Recommendation: For the demo, `allow_origins=["http://localhost:5173", "http://localhost:3000"]`
     is sufficient. Add `CORS_ORIGINS` env var to `Settings` if production deploy is planned.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker + compose | Frontend + backend dev stack | ✓ | (compose v2, per docker-compose.yml) | — |
| pnpm | Frontend dep management | ✓ (inferred from pnpm-lock.yaml in project) | unknown | npm install |
| Python 3.12 | Backend read endpoints | ✓ | 3.12 (pyproject.toml) | — |
| Postgres (Docker) | DB queries | ✓ | postgres:16-alpine (docker-compose.yml) | aiosqlite (tests) |
| aiosqlite | Backend tests (in-memory SQLite) | ✓ | (dev dependency in pyproject.toml) | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none.

---

## Validation Architecture

> `workflow.nyquist_validation: true` in `.planning/config.json` — section is required.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (asyncio_mode = "auto") |
| Config file | `backend/pyproject.toml` → `[tool.pytest.ini_options]` |
| Quick run command | `cd backend && pytest tests/test_admin.py -x -q` |
| Full suite command | `cd backend && pytest -x -q` |

### Frontend Test Infrastructure

There is **no frontend test infrastructure** — no vitest, no jest config, no test files,
no `@testing-library` package. The `frontend/package.json` has no test script. Adding
vitest is out of scope for this phase (adds toolchain overhead with minimal benefit for a
demo build). Frontend correctness is validated manually (UAT).

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| UI-01 | GET /api/gastos returns committed gastos list (newest first) | unit | `pytest tests/test_admin.py::test_list_gastos_empty -x` | ❌ Wave 0 |
| UI-01 | GET /api/gastos filters by date range (?from=&to=) | unit | `pytest tests/test_admin.py::test_list_gastos_date_filter -x` | ❌ Wave 0 |
| UI-01 | GET /api/gastos filters by concepto (?q=) ILIKE | unit | `pytest tests/test_admin.py::test_list_gastos_search -x` | ❌ Wave 0 |
| UI-01 | GET /api/gastos/{id} returns single gasto | unit | `pytest tests/test_admin.py::test_get_gasto -x` | ❌ Wave 0 |
| UI-01 | GET /api/gastos/{id} returns 404 for unknown id | unit | `pytest tests/test_admin.py::test_get_gasto_not_found -x` | ❌ Wave 0 |
| UI-01 | GET /api/gastos/{id}/ticket returns 404 when no ticket_image_path | unit | `pytest tests/test_admin.py::test_get_ticket_no_path -x` | ❌ Wave 0 |
| UI-01 | drafts (conversations.draft_gasto) never appear in gastos list | unit | `pytest tests/test_admin.py::test_drafts_not_exposed -x` | ❌ Wave 0 |
| UI-01 | Decimal monto preserved as string in JSON response | unit | `pytest tests/test_admin.py::test_decimal_serialization -x` | ❌ Wave 0 |
| UI-02 | GET /api/cierres returns committed cierres list (newest first) | unit | `pytest tests/test_admin.py::test_list_cierres -x` | ❌ Wave 0 |
| UI-01/02 | CORS header present on read endpoint responses (allow_origins check) | unit | `pytest tests/test_admin.py::test_cors_header -x` | ❌ Wave 0 |
| UI-01 | Frontend GastosListPage renders table — manual | manual | Browser: navigate to http://localhost:5173/gastos | — |
| UI-01 | GastoDetailPage shows ticket image — manual | manual | Browser: click row with ticket, verify image loads | — |
| UI-01 | Filter bar sends correct query params — manual | manual | Browser: enter dates/text, verify list updates | — |
| UI-02 | CierresListPage renders cierres — manual | manual | Browser: click "Cierres de Caja" tab | — |

### Test Fixture Pattern

New tests follow the established `conftest.py` pattern exactly:
- Use `db_session` (in-memory SQLite, aiosqlite) fixture from `conftest.py`
- Use `httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://testserver")`
- Seed `Gasto` / `CajaCierre` rows directly via `db_session.add()` + `db_session.flush()`
- Override `get_db` dependency with `async def override_get_db(): yield db_session`

### Sampling Rate
- **Per task commit:** `pytest tests/test_admin.py -x -q`
- **Per wave merge:** `pytest -x -q` (full suite — no regressions)
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `backend/tests/test_admin.py` — covers all UI-01, UI-02 requirements above
- [ ] No new conftest fixtures needed (existing `db_session` + `env_setup` are sufficient)

---

## Security Domain

> `security_enforcement` not set in config → treated as enabled.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth in Phase 4 (deferred to v3) |
| V3 Session Management | no | No sessions; open read-only endpoints |
| V4 Access Control | partial | Committed-records-only boundary enforced server-side (never query `conversations`) |
| V5 Input Validation | yes | UUID path params validated by FastAPI/Pydantic; query params typed (`date`, `str`) |
| V6 Cryptography | no | No crypto in read endpoints |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal on ticket file | Tampering / Info Disclosure | `LocalStorageBackend` sanitizes on write; add `commonpath` check on read |
| Draft gasto exposure | Info Disclosure | Query `gastos` table only; never join `conversations` |
| CORS misconfiguration | Elevation of Privilege | Explicit `allow_origins` list; `allow_credentials=False` |
| SQLi via `q` param | Tampering | SQLAlchemy parameterized queries; `.ilike()` uses bind parameter, not string interpolation |

---

## Sources

### Primary (HIGH confidence)
- FastAPI official docs — custom responses: https://fastapi.tiangolo.com/advanced/custom-response/
- FastAPI official docs — CORS: https://fastapi.tiangolo.com/tutorial/cors/
- TanStack Query v5 — overview: https://tanstack.com/query/v5/docs/framework/react/overview
- React Router v7 — data mode installation: https://reactrouter.com/start/data/installation
- `backend/pyproject.toml` — package versions (VERIFIED in codebase)
- `backend/app/db/models.py` — Gasto, CajaCierre exact schema (VERIFIED in codebase)
- `backend/app/main.py` — create_app pattern, AGENT_MODE seam (VERIFIED in codebase)
- `frontend/vite.config.ts` — proxy config, no rewrite (VERIFIED in codebase)
- `frontend/package.json` — current deps (VERIFIED in codebase)
- `frontend/src/index.css` — existing token system (VERIFIED in codebase)
- npm registry — `@tanstack/react-query` 5.100.14 (VERIFIED: npm view)
- npm registry — `react-router` 7.16.0 / `react-router-dom` 7.16.0 (VERIFIED: npm view)

### Secondary (MEDIUM confidence)
- Pydantic v2 Decimal → string serialization: github.com/pydantic/pydantic/issues/7120
- Vite proxy configuration (no rewrite): https://vite.dev/config/server-options

### Tertiary (LOW confidence)
- SQLAlchemy ILIKE on SQLite behavior (ASSUMED — not directly verified against SQLAlchemy source)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages verified on npm/pyproject.toml, versions confirmed
- Architecture: HIGH — patterns derived directly from existing codebase files
- Pitfalls: HIGH — most pitfalls derived from direct code inspection (vite.config.ts proxy,
  missing CORS, docker-compose node_modules mount), not training data alone
- Validation: HIGH — existing test pattern copied exactly from test_prompt_trigger.py

**Research date:** 2026-05-31
**Valid until:** 2026-06-30 (stable stack; react-router/react-query APIs stable in major version)
