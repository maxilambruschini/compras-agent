# Phase 4: Admin UI — Research

**Researched:** 2026-05-14
**Domain:** React 19 + Tailwind CSS v4 + shadcn/ui + FastAPI admin router
**Confidence:** HIGH (all critical claims verified via npm registry, official docs, or direct codebase inspection)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Two separate modals — "Edit document" for header fields, "Edit" per line item row. Both pre-filled.
- **D-02:** PUT semantics: `PATCH /invoices/{id}` for document fields; `PATCH /invoices/{id}/items/{item_id}` for line items.
- **D-03:** On save success, TanStack Query invalidates the detail query; page re-renders with updated values.
- **D-04:** Detail page shows prominent Confirm and Reject buttons when status is `pending_review`.
- **D-05:** One-click actions — no reason or note required.
- **D-06:** Confirm → `confirmed`; Reject → `rejected`. API: `PATCH /invoices/{id}/status` with `{"status": "confirmed" | "rejected"}`.
- **D-07:** Confirm/Reject buttons NOT on list view — manager must open detail page.
- **D-08:** Side-by-side layout: data fields left, original invoice image right.
- **D-09:** Backend exposes `GET /images/{filename}` to stream from local filesystem. Frontend constructs URL from `invoice.image_path`.
- **D-10:** React Router v7. Routes: `/` → invoice list, `/invoices/:id` → invoice detail.
- **D-11:** TanStack Query v5. `useQuery` for reads, `useMutation` + invalidation for writes.
- **D-12:** Both React Router v7 and TanStack Query v5 must be installed in this phase.
- **D-13:** New `backend/app/routers/admin.py`. Endpoints: `GET /invoices`, `GET /invoices/{id}`, `PATCH /invoices/{id}`, `PATCH /invoices/{id}/items/{item_id}`, `PATCH /invoices/{id}/status`, `DELETE /invoices/{id}`, `GET /images/{filename}`.
- **D-14:** `pending_review` rows highlighted with amber background in list.
- **D-15:** Tailwind CSS v4 via `npm install tailwindcss @tailwindcss/vite`. CSS-first config — no `tailwind.config.js`. Use `@import "tailwindcss"` in `index.css`.
- **D-16:** shadcn/ui — `npx shadcn@latest init` (default style, CSS variables enabled). Components: `Button`, `Dialog`, `Badge`, `Input`, `Label`, `Select`, `Table`, `Alert`, `Separator`. No bulk install.
- **D-17:** Fully responsive. Mobile-first. Tailwind breakpoints: `sm` (640px), `md` (768px), `lg` (1024px). List table collapses to 3 columns on mobile; detail grid becomes single column; modals go full-width; ActionBar buttons go full-width on mobile.

### Claude's Discretion

- Exact component file structure and folder layout
- Pagination implementation detail (offset-based chosen as simpler for v1)
- Whether to add optimistic update on Confirm/Reject or just re-fetch after success
- Internal structuring of TanStack Query hooks (e.g., `useInvoices`, `useInvoice`)

### Deferred Ideas (OUT OF SCOPE)

- Authentication (UI-07) — deferred to v2
- CSV export (EXP-01, EXP-02) — v2
- Allowlist management UI — no v1 requirement
- Optional reject reason / audit note — v2 enhancement
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| UI-01 | Paginated invoice list filterable by proveedor, fecha range, and status | `GET /invoices` with query params; TanStack Query `useQuery`; offset pagination |
| UI-02 | Search invoices by proveedor name, product description, or document number | `GET /invoices?q=` search param; ILIKE query on backend |
| UI-03 | Click invoice → document header fields + all line items + original image on one screen | Detail route `/invoices/:id`; `GET /invoices/{id}` eager-loads line_items; `GET /images/{filename}` |
| UI-04 | Edit any extracted field (document or line item) to correct AI errors | `PATCH /invoices/{id}` and `PATCH /invoices/{id}/items/{item_id}`; two modal pattern; invalidation |
| UI-05 | Delete invoice record; retain original file on disk | `DELETE /invoices/{id}` removes DB row only; `image_path` column retains file reference; no filesystem deletion |
| UI-06 | Pending review invoices visually distinguished in list | `bg-amber-50` on `pending_review` rows; `StatusBadge` with amber variant |
</phase_requirements>

---

## Summary

Phase 4 builds the entire React admin UI from a bare skeleton (`App.tsx` with 8 lines). The frontend currently has React 19 + Vite 8 + TypeScript but no router, no data-fetching layer, and no styling framework. This phase installs and configures Tailwind CSS v4, shadcn/ui, React Router v7, and TanStack Query v5, then builds all pages and components from scratch.

The backend is complete (FastAPI 0.136.1 + SQLAlchemy async + Postgres). The admin router is entirely new: `backend/app/routers/admin.py` with 7 endpoints, registered in `create_app()`. CORS middleware is absent from the codebase and must be added before any frontend-to-backend call will work. The Vite proxy (`/api → localhost:8000`) already exists but does not cover `/invoices` or `/images` routes yet — either the proxy must be extended or CORS added (CORS is the correct solution since image requests from `<img src>` tags bypass the Vite proxy entirely).

The key planning complexity is the correct sequencing of toolchain setup (Tailwind → shadcn → shadcn component add) before component development can begin, and the CSS custom property co-existence between the existing `index.css` tokens and Tailwind v4's own variable system.

**Primary recommendation:** Wave 0 installs toolchain and adds CORS + admin router skeleton; Wave 1 builds backend endpoints; Wave 2 builds frontend pages and components; Wave 3 wires data layer and integration tests.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Invoice list + filtering + pagination | API / Backend | Frontend (render) | Query logic (ILIKE, status filter, date range, offset) belongs server-side; frontend is display only |
| Full-text search (`q` param) | API / Backend | — | PostgreSQL ILIKE on proveedor + descripcion + numero_documento; not client-side |
| Invoice detail (header + line items) | API / Backend | Frontend (render) | Eager-load via SQLAlchemy relationship; one round-trip |
| Image serving | API / Backend | — | `GET /images/{filename}` streams file from local filesystem using `settings.storage_path`; browser `<img src>` hits this directly |
| Edit (document + line item) | API / Backend | Frontend (modal) | Business logic (update ORM, commit) is server-side; frontend owns modal UX and form validation |
| Status workflow (confirm/reject) | API / Backend | Frontend (conditional render) | Status state lives in DB; frontend only shows buttons conditionally based on `invoice.status` |
| Delete | API / Backend | Frontend (navigate) | DB row deletion is server-side; frontend navigates to `/` on success |
| Client-side routing | Browser / Client | — | React Router v7 BrowserRouter; `/` and `/invoices/:id` |
| Server state + cache | Browser / Client | — | TanStack Query v5 QueryClient; all data fetching and mutation state |
| Responsive layout | Browser / Client | — | Tailwind breakpoints `md:` prefix; mobile-first |
| CORS | API / Backend | — | CORSMiddleware in FastAPI `create_app()`; required because `<img src>` bypasses Vite proxy |

---

## Standard Stack

### Core (must install this phase)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| tailwindcss | 4.3.0 | Utility-first CSS | v4 — locked by D-15 |
| @tailwindcss/vite | 4.3.0 | Vite plugin for Tailwind v4 | Required for v4; replaces PostCSS approach |
| shadcn (CLI) | 4.7.0 | Component scaffolding CLI | `npx shadcn@latest` — locked by D-16 |
| lucide-react | 1.16.0 | Icons (shadcn peer dep) | Installed automatically by shadcn; use sparingly |
| react-router | 7.15.1 | Client-side routing | Package name is `react-router` (v7 merged `react-router-dom`) — locked by D-10/D-12 |
| @tanstack/react-query | 5.100.10 | Server state management | v5 — locked by D-11/D-12 |

[VERIFIED: npm registry — checked 2026-05-14]

### Supporting (backend)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| fastapi.middleware.cors.CORSMiddleware | (bundled in FastAPI 0.136.1) | CORS headers for frontend→backend calls | Required since `<img src>` bypasses Vite proxy |
| fastapi.responses.FileResponse | (bundled) | Stream local filesystem files | `/images/{filename}` endpoint |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| native `fetch` API | axios | fetch is sufficient; no extra dep; axios adds 45kb; for this scale fetch wins |
| TanStack Query | SWR | TQ has better mutation/invalidation ergonomics for multi-resource invalidation (already in CLAUDE.md) |
| BrowserRouter (declarative) | createBrowserRouter (data API) | Declarative is simpler for 2 routes; no loaders/actions needed |

**Installation commands:**
```bash
# Frontend (run from frontend/)
npm install tailwindcss @tailwindcss/vite
npm install react-router @tanstack/react-query
npx shadcn@latest init
npx shadcn@latest add button dialog badge input label select table alert separator
```

---

## Architecture Patterns

### System Architecture Diagram

```
Browser
  │
  ├─ React Router v7 (BrowserRouter)
  │    ├─ / → InvoiceListPage
  │    │       ├─ FilterToolbar  ──────────────────────────┐
  │    │       ├─ InvoiceTable                             │
  │    │       └─ Pagination                               │ GET /invoices?page=&status=&proveedor=&q=
  │    │                                                   │
  │    └─ /invoices/:id → InvoiceDetailPage               ├─ GET /invoices/:id
  │            ├─ DataPanel                               │
  │            │    ├─ InvoiceHeader                      ├─ PATCH /invoices/:id
  │            │    ├─ ActionBar ─────────── PATCH /invoices/:id/status
  │            │    └─ LineItemsTable ────── PATCH /invoices/:id/items/:item_id
  │            └─ ImagePanel  ─────────────── GET /images/:filename (direct, not via TQ)
  │
  │  TanStack Query v5 (QueryClientProvider at root)
  │    queryKeys: ["invoices"] | ["invoice", id]
  │    mutations → invalidate queryKeys on success
  │
  └─ Vite dev server (:5173)
       proxy: /api → :8000  (extend to cover /invoices, /images)
       OR rely on CORS (required for <img src> anyway)

FastAPI (:8000)
  ├─ CORSMiddleware (allow_origins=["http://localhost:5173"])
  ├─ GET  /health
  ├─ POST /whatsapp/...
  └─ Admin Router (backend/app/routers/admin.py)
       ├─ GET  /invoices              → InvoiceListResponse
       ├─ GET  /invoices/{id}         → InvoiceDetailResponse (+ line_items)
       ├─ PATCH /invoices/{id}        → InvoiceDetailResponse
       ├─ PATCH /invoices/{id}/items/{item_id}  → LineItemResponse
       ├─ PATCH /invoices/{id}/status → InvoiceDetailResponse
       ├─ DELETE /invoices/{id}       → 204 No Content
       └─ GET  /images/{filename}     → FileResponse (streams from storage_path)

Postgres (Docker :5432)
  ├─ invoices (UUID PK, status, image_path, ...)
  └─ invoice_line_items (int PK, invoice_id FK, ...)
```

### Recommended Project Structure
```
frontend/src/
├── api/
│   └── client.ts           # fetch wrapper, BASE_URL, error handling
├── components/
│   ├── ui/                 # shadcn generated components (do not edit)
│   ├── InvoiceTable.tsx
│   ├── StatusBadge.tsx
│   ├── FilterToolbar.tsx
│   ├── Pagination.tsx
│   ├── InvoiceHeader.tsx
│   ├── ActionBar.tsx
│   ├── LineItemsTable.tsx
│   ├── ImagePanel.tsx
│   ├── EditDocumentModal.tsx
│   ├── EditLineItemModal.tsx
│   ├── DeleteConfirmation.tsx
│   ├── FormField.tsx
│   ├── ErrorBanner.tsx
│   └── LoadingSpinner.tsx
├── hooks/
│   ├── useInvoices.ts      # useQuery wrapper for list
│   └── useInvoice.ts       # useQuery wrapper for detail
├── pages/
│   ├── InvoiceListPage.tsx
│   └── InvoiceDetailPage.tsx
├── types/
│   └── invoice.ts          # TypeScript interfaces matching API response shapes
├── App.tsx                 # BrowserRouter + Routes + QueryClientProvider
├── main.tsx                # createRoot (unchanged)
└── index.css               # @import "tailwindcss" + existing custom props + new tokens
```

### Pattern 1: Tailwind v4 + @tailwindcss/vite Setup

**What:** CSS-first configuration; no `tailwind.config.js`. The Vite plugin replaces the PostCSS plugin.
**When to use:** All new Vite projects with Tailwind v4.

`vite.config.ts` change:
```typescript
// Source: https://ui.shadcn.com/docs/installation/vite (verified 2026-05-14)
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

const apiTarget = process.env.VITE_API_URL || 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),  // required by shadcn
    },
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': apiTarget,
      '/health': apiTarget,
      '/invoices': apiTarget,
      '/images': apiTarget,
    },
  },
})
```

`index.css` — replace ALL existing Tailwind directives with import, keep custom props:
```css
/* Source: tailwindcss.com/docs/upgrade-guide (verified 2026-05-14) */
@import "tailwindcss";

:root {
  /* --- existing tokens (keep) --- */
  --text: #6b6375;
  --text-h: #08060d;
  --bg: #fff;
  --border: #e5e4e7;
  --code-bg: #f4f3ec;
  --sans: system-ui, 'Segoe UI', Roboto, sans-serif;
  --heading: system-ui, 'Segoe UI', Roboto, sans-serif;
  --mono: ui-monospace, Consolas, monospace;

  /* --- new admin tokens (D-15, UI-SPEC) --- */
  --accent-admin: #2563eb;
  --accent-admin-bg: rgba(37, 99, 235, 0.08);
  --destructive: #dc2626;
  --destructive-hover: #b91c1c;
  --pending-bg: #fef3c7;
  --pending-badge: #d97706;
  --surface-secondary: #f8f7fa;

  font: 14px/1.5 var(--sans);
  color: var(--text);
  background: var(--bg);
}
```

**CSS custom property conflict analysis:** Tailwind v4 generates variables like `--color-red-500`, `--shadow-xl`, `--breakpoint-xl`. The existing tokens use names like `--text`, `--bg`, `--border`. These DO NOT conflict — Tailwind v4 uses structured namespaced prefixes (`--color-*`, `--shadow-*`, `--breakpoint-*`). The existing short-name tokens are safe alongside Tailwind v4. [VERIFIED: tailwindcss.com/docs/upgrade-guide]

**`#root` CSS conflict:** The existing `index.css` sets `#root { width: 1126px; text-align: center; }` — this is a walking skeleton style that must be replaced. The admin UI needs full-width layout.

### Pattern 2: shadcn/ui Init with Tailwind v4

**What:** `npx shadcn@latest init` detects Tailwind v4 automatically and writes CSS variables into `index.css` using `@theme inline` syntax.
**When to use:** Once and only once, after Tailwind v4 is installed.

```bash
# Source: https://ui.shadcn.com/docs/installation/vite (verified 2026-05-14)
npx shadcn@latest init
# prompts: style=default, CSS variables=yes
# shadcn 4.7.0 handles v4 automatically — no manual config needed
```

shadcn writes to `index.css` under `@theme inline { ... }` for its color tokens. These use `--background`, `--foreground`, `--primary`, etc. — again no conflict with existing `--text`, `--bg` tokens (different names).

shadcn also requires the `@/*` path alias in `tsconfig.app.json`:
```json
{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"]
    }
  }
}
```

Add components one at a time (required by D-16 / UI-SPEC registry safety rule):
```bash
npx shadcn@latest add button
npx shadcn@latest add dialog
npx shadcn@latest add badge
npx shadcn@latest add input
npx shadcn@latest add label
npx shadcn@latest add select
npx shadcn@latest add table
npx shadcn@latest add alert
npx shadcn@latest add separator
```

Each `add` command writes to `src/components/ui/`. These files are generated source — commit them, do not `.gitignore` them.

**Known shadcn v4 breaking change:** shadcn v4 removed `React.forwardRef` from all components. Components use direct prop-passing. Also: `tailwindcss-animate` is deprecated; shadcn init now installs `tw-animate-css` instead. [VERIFIED: ui.shadcn.com/docs/tailwind-v4]

### Pattern 3: React Router v7 Setup (Declarative Mode)

**What:** For this project's 2-route structure, declarative `BrowserRouter` mode is correct. No need for `createBrowserRouter` (data API mode) — no loaders or server-side actions.
**Package name:** `react-router` (v7 merged `react-router-dom`; import from `"react-router"`)

```tsx
// Source: Context7 /remix-run/react-router (verified 2026-05-14)
// App.tsx — replaces current skeleton
import { BrowserRouter, Routes, Route } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import InvoiceListPage from "./pages/InvoiceListPage";
import InvoiceDetailPage from "./pages/InvoiceDetailPage";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<InvoiceListPage />} />
          <Route path="/invoices/:id" element={<InvoiceDetailPage />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
```

Navigation hooks:
```tsx
import { useParams, useNavigate, Link } from "react-router";

// In InvoiceDetailPage:
const { id } = useParams<{ id: string }>();

// After delete:
const navigate = useNavigate();
navigate("/");
```

**main.tsx** remains unchanged — `createRoot` wrapping `<App />` is already correct.

### Pattern 4: TanStack Query v5 — useQuery / useMutation

**What:** `QueryClientProvider` at root (inside App.tsx), `useQuery` for reads, `useMutation` with `onSuccess` invalidation for writes.

```tsx
// Source: Context7 /tanstack/query (verified 2026-05-14)

// hooks/useInvoices.ts
import { useQuery } from "@tanstack/react-query";
import { fetchInvoices } from "../api/client";

export function useInvoices(params: InvoiceListParams) {
  return useQuery({
    queryKey: ["invoices", params],
    queryFn: () => fetchInvoices(params),
  });
}

// hooks/useInvoice.ts
export function useInvoice(id: string) {
  return useQuery({
    queryKey: ["invoice", id],
    queryFn: () => fetchInvoice(id),
  });
}

// In EditDocumentModal — mutation with dual invalidation (D-03):
import { useMutation, useQueryClient } from "@tanstack/react-query";

const queryClient = useQueryClient();
const mutation = useMutation({
  mutationFn: (data: InvoiceDocumentPatch) => patchInvoice(id, data),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ["invoice", id] });
    queryClient.invalidateQueries({ queryKey: ["invoices"] });
  },
});
```

**Status mutation (Confirm/Reject — D-06):**
```tsx
const statusMutation = useMutation({
  mutationFn: (status: "confirmed" | "rejected") =>
    patchInvoiceStatus(id, status),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ["invoice", id] });
    queryClient.invalidateQueries({ queryKey: ["invoices"] });
  },
});
```

**Delete mutation (UI-05):**
```tsx
const deleteMutation = useMutation({
  mutationFn: () => deleteInvoice(id),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ["invoices"] });
    navigate("/");
  },
});
```

**Loading/pending state** — `mutation.isPending` replaces `mutation.isLoading` in TQ v5:
```tsx
<Button disabled={mutation.isPending}>
  {mutation.isPending ? <LoadingSpinner /> : "Guardar cambios"}
</Button>
```

### Pattern 5: FastAPI Admin Router

**What:** New router registered in `create_app()`. Follows exact same pattern as `health.py` and `extraction.py` — `async def` + `AsyncSession = Depends(get_db)`.

```python
# backend/app/routers/admin.py
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.config import Settings, get_settings
import pathlib

router = APIRouter()

@router.get("/invoices")
async def list_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    proveedor: str | None = Query(None),
    fecha_from: str | None = Query(None),
    fecha_to: str | None = Query(None),
    q: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    ...

@router.get("/images/{filename}")
async def serve_image(
    filename: str = Path(...),
    settings: Settings = Depends(get_settings),
):
    file_path = pathlib.Path(settings.storage_path) / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(file_path))
```

Registration in `main.py` `create_app()`:
```python
from app.routers.admin import router as admin_router
app.include_router(admin_router, tags=["admin"])
```

**Note on prefixes:** The endpoints are `/invoices` and `/images` at top level — no `/admin` prefix. The Vite proxy and CORS both need to cover these paths.

### Pattern 6: CORS Configuration

**What:** `CORSMiddleware` must be added to `create_app()` before any routes. This is the only way to make `<img src="http://localhost:8000/images/...">` work from the browser — Vite proxy does not intercept `<img src>` tags.

```python
# Source: fastapi.tiangolo.com/tutorial/cors/ (verified 2026-05-14)
# In create_app(), before app.include_router():
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
```

For production: `allow_origins` should come from an environment variable (e.g., `settings.cors_origins`). For v1 demo: hardcoded localhost is acceptable. `allow_credentials` is left `False` since there is no auth in v1.

**CORS must be added before `app.include_router()` calls** — Starlette middleware is applied in reverse registration order, and CORS must fire before any route handler.

### Pattern 7: Frontend API Client

**What:** Thin fetch wrapper in `api/client.ts`. Uses native `fetch`. Base URL is empty string (goes through Vite proxy in dev) or `VITE_API_URL` for production.

```typescript
// frontend/src/api/client.ts
const BASE_URL = import.meta.env.VITE_API_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const fetchInvoices = (params: InvoiceListParams) =>
  request<InvoiceListResponse>(`/invoices?${new URLSearchParams(params as any)}`);

export const fetchInvoice = (id: string) =>
  request<InvoiceDetailResponse>(`/invoices/${id}`);

export const patchInvoice = (id: string, data: Partial<InvoiceDocumentPatch>) =>
  request<InvoiceDetailResponse>(`/invoices/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const patchInvoiceStatus = (id: string, status: "confirmed" | "rejected") =>
  request<InvoiceDetailResponse>(`/invoices/${id}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });

export const patchLineItem = (id: string, itemId: number, data: Partial<LineItemPatch>) =>
  request<LineItemResponse>(`/invoices/${id}/items/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const deleteInvoice = (id: string) =>
  request<void>(`/invoices/${id}`, { method: "DELETE" });

// Image URL — direct, not through TanStack Query
export const imageUrl = (filename: string) =>
  `${BASE_URL}/images/${filename}`;
```

**Image URL note:** The image URL is constructed directly (not fetched through TanStack Query) because `<img src>` handles its own loading. The CORS middleware enables the browser to load it cross-origin.

### Pattern 8: Image Serving — Path Safety

**What:** The `/images/{filename}` endpoint must prevent path traversal attacks. [CITED: OWASP path traversal]

```python
@router.get("/images/{filename}")
async def serve_image(
    filename: str = Path(..., pattern=r"^[^/\\]+$"),  # no path separators
    settings: Settings = Depends(get_settings),
):
    # Resolve and verify the path stays within storage_path
    storage_root = pathlib.Path(settings.storage_path).resolve()
    file_path = (storage_root / filename).resolve()
    if not str(file_path).startswith(str(storage_root)):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(file_path))
```

`FileResponse` auto-detects MIME type from extension and sets `Content-Length`, `Last-Modified`, and `ETag` headers. Suitable for JPEG, PNG, and PDF. [VERIFIED: fastapi.tiangolo.com/advanced/custom-response/]

### Anti-Patterns to Avoid

- **Vite proxy for images:** `<img src="/images/...">` in JSX goes directly to the origin server, NOT through Vite's proxy. CORS is mandatory for this to work cross-origin. Do not try to solve this with the proxy alone.
- **`react-router-dom` import:** In React Router v7, the package is `react-router`; there is no separate `react-router-dom`. Importing from `react-router-dom` will fail.
- **`mutation.isLoading` in TQ v5:** Renamed to `mutation.isPending`. Using the old name causes a silent `undefined` bug.
- **Tailwind v4 `@tailwind base/components/utilities` directives:** These were removed in v4. Replace with `@import "tailwindcss"`.
- **`tailwindcss.config.js`:** Not needed in v4. Do not create it. shadcn's CSS variables go directly into `index.css`.
- **Hardcoded `image_path` as URL:** `image_path` in the DB is a local filesystem path (e.g., `/data/invoices/abc.jpg`). Extract only the filename component: `image_path.split('/').pop()` or use `path.basename()` equivalent in TypeScript.
- **`async def` without `await` in admin router:** All DB queries must use `await session.execute(...)`. Never call sync SQLAlchemy methods on an `AsyncSession`.
- **Eager-loading line items:** `session.get(Invoice, id)` does NOT load the relationship. Must use `selectinload` or `joinedload`:
  ```python
  from sqlalchemy.orm import selectinload
  result = await session.execute(
      select(Invoice).where(Invoice.id == id).options(selectinload(Invoice.line_items))
  )
  ```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Focus trap in modals | Custom focus management | shadcn `Dialog` | Dialog uses Radix UI under the hood — correct focus trap + Escape key + aria-modal |
| Form field label association | Custom `htmlFor` wiring | shadcn `Label` + `FormField` | Radix `Label` handles association properly |
| Status badge variants | CSS `if/else` rendering | shadcn `Badge` with `variant` prop | Consistent styling tokens, accessible `aria-label` |
| Table structure | `<div>` grid tables | shadcn `Table` primitives | Semantic `<table>` elements required for screen reader row navigation |
| HTTP error parsing | Try/catch around JSON | `api/client.ts` wrapper | Centralises error handling; components only see Error objects |
| Query invalidation across multiple keys | Manual `refetch()` calls | `queryClient.invalidateQueries()` | Invalidates all matching keys including paginated variants |
| Image path resolution | String manipulation | `pathlib.Path(settings.storage_path) / filename` | Platform-safe path joining; `.resolve()` for traversal prevention |

**Key insight:** The shadcn primitives handle all accessibility concerns for modals, labels, and tables. The only custom components needed are data/layout ones (InvoiceTable row behavior, ImagePanel, FilterToolbar, Pagination, DeleteConfirmation strip).

---

## Common Pitfalls

### Pitfall 1: `#root` CSS Conflicts with Admin Layout
**What goes wrong:** The existing `index.css` constrains `#root` to `width: 1126px; text-align: center; display: flex; flex-direction: column`. These conflict with the full-width admin table layout and the split detail grid.
**Why it happens:** Walking skeleton CSS was scaffold-only.
**How to avoid:** Wave 0 task must replace the `#root` block with `min-height: 100svh; box-sizing: border-box;` only. The admin layout uses Tailwind classes for width/flex control.
**Warning signs:** Invoice table appears centred or constrained to 1126px on desktop.

### Pitfall 2: `image_path` is a Filesystem Path, Not a URL Segment
**What goes wrong:** Storing `invoice.image_path` (e.g., `/data/invoices/2024-01-abc.jpg`) directly as an `<img src>` value — this is a local filesystem path, not a URL.
**Why it happens:** The column name says "path" and stores a path.
**How to avoid:** The frontend must extract only the filename: `const filename = imagePath.split('/').pop()` then construct `imageUrl(filename)`. The backend `GET /images/{filename}` endpoint resolves the full path from `settings.storage_path`.
**Warning signs:** Images return 404 or browser shows a file:// URL error.

### Pitfall 3: shadcn Init Overwrites `index.css`
**What goes wrong:** `npx shadcn@latest init` can add `@import "tailwindcss"` at the top of `index.css`, potentially duplicating it if Tailwind was already added manually.
**Why it happens:** shadcn init writes its own CSS setup assuming a clean file.
**How to avoid:** Add Tailwind (`@import "tailwindcss"`) AND run `npx shadcn@latest init` in the same Wave 0 task, in order. The executor should let shadcn write the file, then manually add back the custom property tokens from the original `index.css` and the new admin tokens.
**Warning signs:** Duplicate `@import "tailwindcss"` in `index.css`; CSS variable declarations appear twice.

### Pitfall 4: SQLAlchemy Async Relationship Loading
**What goes wrong:** `GET /invoices/{id}` returns the invoice but `line_items` is an empty list or raises `MissingGreenlet` error.
**Why it happens:** SQLAlchemy async sessions do NOT lazy-load relationships. `invoice.line_items` accessed outside a coroutine raises an error.
**How to avoid:** Always use `selectinload(Invoice.line_items)` in the query options for the detail endpoint.
**Warning signs:** `MissingGreenlet` or `greenlet_spawn has not been called` in logs; `line_items: []` in response even when items exist in DB.

### Pitfall 5: CORS Order in `create_app()`
**What goes wrong:** CORS headers missing on API responses despite CORSMiddleware being added.
**Why it happens:** `app.add_middleware()` in Starlette applies middleware in reverse order. If CORS is added after routing, it fires after the route handler — too late.
**How to avoid:** Call `app.add_middleware(CORSMiddleware, ...)` as the FIRST statement after `app = FastAPI(...)`, before all `app.include_router()` calls.
**Warning signs:** Browser console shows `No 'Access-Control-Allow-Origin' header`.

### Pitfall 6: `pending_review` Amber Highlight Tailwind Class
**What goes wrong:** Using arbitrary CSS `background-color: var(--pending-bg)` on `<tr>` elements instead of a Tailwind class — class is stripped by Tailwind v4's content scanning in production build.
**Why it happens:** Tailwind v4 scans JSX for class names to include. Dynamic classes constructed via string concatenation (e.g., `"bg-" + color`) are not detected.
**How to avoid:** Use the literal Tailwind class `bg-amber-50` (maps to `#fffbeb`, close to `#fef3c7`) in JSX. For dark mode, add `dark:bg-amber-950`. This matches UI-SPEC's `bg-amber-50` specification exactly.
**Warning signs:** Table rows appear white in production build even though they're amber in dev.

### Pitfall 7: No CORS on Image Endpoint
**What goes wrong:** `<img src="http://localhost:8000/images/foo.jpg">` is blocked by browser CORS policy.
**Why it happens:** The Vite dev proxy only rewrites fetch/XHR calls initiated by JavaScript — not native `<img src>` requests.
**How to avoid:** CORS middleware (Pitfall 5) handles this. The image endpoint is a regular FastAPI route and will return proper CORS headers once CORSMiddleware is in place.
**Warning signs:** Browser shows "blocked by CORS policy" on image requests; images never load.

---

## Existing Backend Patterns — Admin Router MUST Follow

### Session injection pattern (from `health.py`)
```python
# REQUIRED: always use Depends(get_db)
async def my_endpoint(db: AsyncSession = Depends(get_db)):
    ...
```

### Settings injection pattern (from `extraction.py`)
```python
# For endpoints that need storage_path:
async def serve_image(
    filename: str,
    settings: Settings = Depends(get_settings),
):
    ...
```

### Router registration in `main.py` (from existing pattern)
```python
# Inside create_app(), import inside the function body (avoids circular imports):
from app.routers.admin import router as admin_router
app.include_router(admin_router, tags=["admin"])
```

### No service class needed for admin queries
`InvoiceService` has `find_duplicate`, `find_existing_for_race`, and `save_invoice` — none are directly reusable for admin list/detail queries. The admin router can write SQLAlchemy queries inline (they are simple SELECTs + UPDATEs + DELETEs). No new service class needed.

### `Invoice.id` is a UUID
```python
import uuid
invoice_id = uuid.UUID(id_str)  # convert path param string before querying
result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
```

### `InvoiceLineItem.id` is an integer
```python
item = await db.get(InvoiceLineItem, item_id_int)  # simple primary key lookup
```

### Full ORM field inventory for response schemas

**Invoice (invoices table):**
- `id` — UUID
- `tipo_comprobante` — Optional[str] (max 50)
- `numero_documento` — Optional[str] (max 100)
- `proveedor` — Optional[str] (max 255)
- `fecha` — Optional[date]
- `cuit_proveedor` — Optional[str] (max 13)
- `cae` — Optional[str] (max 20)
- `fecha_vencimiento_cae` — Optional[date]
- `confidence_score` — Optional[Decimal] (4,3)
- `status` — str (NOT NULL; values: `auto_saved`, `pending_review`, `confirmed`, `rejected`)
- `whatsapp_message_id` — Optional[str]
- `sender_phone` — Optional[str]
- `image_path` — Optional[str] (local filesystem path)
- `raw_extraction` — Optional[str] (JSON dump, not exposed to frontend)
- `created_at` — datetime (timezone-aware)
- `updated_at` — datetime (timezone-aware)

**InvoiceLineItem (invoice_line_items table):**
- `id` — int (PK)
- `invoice_id` — UUID (FK)
- `descripcion` — Optional[str]
- `codigo_sku` — Optional[str] (max 100)
- `bultos` — Optional[Decimal] (12,4)
- `unidades_por_bulto` — Optional[Decimal] (12,4)
- `precio_unitario_sin_iva` — Optional[Decimal] (14,4)
- `descuento_pct` — Optional[Decimal] (6,4)
- `iva_rate` — Optional[Decimal] (6,4)
- `percepciones_iibb` — Optional[Decimal] (14,4)

**Editable fields (PATCH /invoices/{id}):**
tipo_comprobante, numero_documento, proveedor, fecha, cuit_proveedor, cae, fecha_vencimiento_cae

**Editable fields (PATCH /invoices/{id}/items/{item_id}):**
descripcion, codigo_sku, bultos, unidades_por_bulto, precio_unitario_sin_iva, descuento_pct, iva_rate, percepciones_iibb

**NOT editable:** id, confidence_score, whatsapp_message_id, sender_phone, image_path, raw_extraction, created_at, updated_at

---

## Code Examples

### Full-text search query (UI-02)
```python
# Source: SQLAlchemy 2.0 docs + codebase pattern
from sqlalchemy import or_, func

if q:
    search = f"%{q.lower()}%"
    stmt = stmt.where(
        or_(
            func.lower(Invoice.proveedor).like(search),
            func.lower(Invoice.numero_documento).like(search),
            # For descripcion (line items), need a subquery or join
        )
    )
```

Note: searching `descripcion` (line items) requires a join to `invoice_line_items`. For v1, searching proveedor + numero_documento in the invoices table covers UI-02's core cases. A join for product description can be added if needed.

### Pagination query
```python
# Offset-based (Claude's Discretion decision)
offset = (page - 1) * page_size
stmt = select(Invoice).offset(offset).limit(page_size).order_by(Invoice.created_at.desc())
result = await db.execute(stmt)
invoices = result.scalars().all()

# Total count (for "Página X de Y"):
count_stmt = select(func.count()).select_from(Invoice)  # apply same filters
total = (await db.execute(count_stmt)).scalar_one()
```

### StatusBadge variant mapping
```tsx
// Source: UI-SPEC.md component inventory
const variantMap: Record<string, string> = {
  auto_saved: "secondary",
  pending_review: "outline",  // overridden with amber custom class
  confirmed: "default",
  rejected: "destructive",
};

const labelMap: Record<string, string> = {
  auto_saved: "Guardado",
  pending_review: "Revisar",
  confirmed: "Confirmado",
  rejected: "Rechazado",
};
```

### Argentine currency formatter
```typescript
// Format as "$ 1.234,56" — Argentine locale
const formatCurrency = (value: number | string | null) => {
  if (value === null || value === undefined) return "—";
  return "$ " + Number(value).toLocaleString("es-AR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
};

// Format date as DD/MM/AAAA
const formatDate = (iso: string | null) => {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
};
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `@tailwind base/components/utilities` in CSS | `@import "tailwindcss"` | Tailwind v4 (2025) | One line replaces three; no PostCSS config |
| `tailwind.config.js` | No config file; CSS-first via `@theme` | Tailwind v4 (2025) | Cleaner setup; shadcn writes tokens directly to CSS |
| `react-router-dom` package | `react-router` (merged) | React Router v7 (2024) | Same import paths, just different package name |
| `mutation.isLoading` | `mutation.isPending` | TanStack Query v5 | Silent bug if old name used — returns `undefined` |
| `React.forwardRef` in shadcn components | Direct prop forwarding | shadcn March 2025 | Components are simpler; no ref forwarding needed for standard use |
| `tailwindcss-animate` | `tw-animate-css` | shadcn March 2025 | `tailwindcss-animate` deprecated; shadcn init installs the replacement |
| `query.isLoading` | `query.isPending` | TanStack Query v5 | Note: for queries, also check `query.isFetching` for background refetches |

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (already installed) |
| Config file | `backend/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `cd backend && python -m pytest tests/test_admin.py -x -q` |
| Full suite command | `cd backend && python -m pytest -x -q` |

Frontend testing: No test framework installed. For this phase, backend API endpoint tests (httpx ASGI) are the automated gate; frontend is verified manually.

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| UI-01 | `GET /invoices` returns paginated list with filter params | unit (ASGI) | `pytest tests/test_admin.py::test_list_invoices -x` | ❌ Wave 0 |
| UI-01 | Status filter returns only matching rows | unit (ASGI) | `pytest tests/test_admin.py::test_list_invoices_filter_status -x` | ❌ Wave 0 |
| UI-02 | `GET /invoices?q=` matches proveedor | unit (ASGI) | `pytest tests/test_admin.py::test_list_invoices_search -x` | ❌ Wave 0 |
| UI-03 | `GET /invoices/{id}` includes line_items array | unit (ASGI) | `pytest tests/test_admin.py::test_get_invoice_detail -x` | ❌ Wave 0 |
| UI-04 | `PATCH /invoices/{id}` updates editable fields | unit (ASGI) | `pytest tests/test_admin.py::test_patch_invoice -x` | ❌ Wave 0 |
| UI-04 | `PATCH /invoices/{id}/items/{item_id}` updates line item | unit (ASGI) | `pytest tests/test_admin.py::test_patch_line_item -x` | ❌ Wave 0 |
| UI-04 | `PATCH /invoices/{id}/status` sets confirmed/rejected | unit (ASGI) | `pytest tests/test_admin.py::test_patch_status -x` | ❌ Wave 0 |
| UI-05 | `DELETE /invoices/{id}` removes DB row, returns 204 | unit (ASGI) | `pytest tests/test_admin.py::test_delete_invoice -x` | ❌ Wave 0 |
| UI-05 | Delete does NOT remove file from filesystem | unit | `pytest tests/test_admin.py::test_delete_retains_image -x` | ❌ Wave 0 |
| UI-06 | `GET /invoices` returns `pending_review` rows (visual tested manually) | manual | — | — |

### Sampling Rate
- **Per task commit:** `cd backend && python -m pytest tests/test_admin.py -x -q`
- **Per wave merge:** `cd backend && python -m pytest -x -q`
- **Phase gate:** Full backend suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `backend/tests/test_admin.py` — admin router endpoint tests (all UI-01 through UI-05)
- [ ] `backend/app/routers/admin.py` — skeleton (no-op endpoints) to allow test collection

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No (auth deferred UI-07) | — |
| V3 Session Management | No (no auth) | — |
| V4 Access Control | Partial | No auth in v1; image endpoint protected by filename-only pattern (path traversal) |
| V5 Input Validation | Yes | FastAPI Query/Path type annotations; Pydantic response models; PATCH body validated via Pydantic schema |
| V6 Cryptography | No | No cryptographic operations in this phase |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal via `/images/{filename}` | Tampering | Restrict `filename` to no path separators via `Path(pattern=r"^[^/\\]+$")`; resolve and verify path stays within `storage_path` |
| SQL injection via search/filter params | Tampering | SQLAlchemy parameterized queries — never string-concatenate SQL; use `.where()` with bound params |
| Unrestricted data exposure (no auth) | Information Disclosure | Accepted for v1 demo per locked decision (UI-07 deferred); document in code comments |
| CSRF (no auth, no cookies) | Tampering | N/A — no session cookies; all requests are stateless |
| Oversized PATCH payload | Denial of Service | FastAPI body size limit (default 1MB); Pydantic schema rejects unknown fields |

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js / npm | Frontend build | ✓ | (npm 10+ assumed — Vite 8 requires Node 18+) | — |
| Vite 8 | Frontend | ✓ | 8.0.12 (in package.json) | — |
| Python 3.12 | Backend | ✓ | (from prior phases) | — |
| PostgreSQL (Docker) | Admin queries | ✓ | (running from Phase 1) | — |
| `settings.storage_path` | Image serving | ✓ | defaults to `/data/invoices` | — |

[ASSUMED: Node.js and Docker are available — confirmed indirectly by prior phases completing successfully. Not re-probed in this session.]

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Node.js 18+ is installed and available in shell | Environment Availability | `npm install` fails; executor must install Node first |
| A2 | Docker Postgres from Phase 1 is accessible for integration testing | Environment Availability | Admin endpoint tests may need a separate test DB (aiosqlite in-memory used for unit tests — same as existing conftest.py pattern) |
| A3 | `settings.storage_path` default `/data/invoices` is the same path used by StorageBackend in Phase 2 | Image serving | Images not found if path differs; executor should verify against Phase 2 implementation |

---

## Open Questions

1. **Admin router prefix: `/` vs `/api/`?**
   - What we know: Existing routers use prefixes: `/whatsapp`, `/extraction`. The Vite proxy routes `/api` to backend. Current CONTEXT.md D-13 shows endpoints as `/invoices` and `/images` (no `/api` prefix).
   - What's unclear: Should the admin router use an `/api` prefix so the Vite proxy can catch all non-image fetch calls, or keep top-level routes + CORS?
   - Recommendation: Keep top-level routes (`/invoices`, `/images`) and use CORS. This is consistent with `/health` being top-level. Adding an `/api` prefix would break the image `<img src>` pattern (browsers don't auto-add prefixes) and require frontend changes to all fetch calls. CORS solves both cases cleanly.

2. **Search across line item `descripcion` (UI-02)**
   - What we know: UI-02 requires searching by "product description" — which lives in `invoice_line_items.descripcion`, not in the `invoices` table.
   - What's unclear: Does the `q` search need to join `invoice_line_items` and return the parent invoice?
   - Recommendation: For v1, implement `q` search on `invoices.proveedor` + `invoices.numero_documento`. Add a subquery join for `descripcion` only if the product explicitly requires it. The requirement says "by proveedor name, product description, or document number" — a JOIN subquery is straightforward but adds complexity. Planner should decide and note in PLAN.

---

## Sources

### Primary (HIGH confidence)
- npm registry (`npm view`) — tailwindcss 4.3.0, @tailwindcss/vite 4.3.0, react-router 7.15.1, @tanstack/react-query 5.100.10, shadcn 4.7.0, lucide-react 1.16.0 [VERIFIED: 2026-05-14]
- Context7 `/remix-run/react-router` — BrowserRouter setup, useParams, useNavigate [VERIFIED]
- Context7 `/tanstack/query` — QueryClient, useQuery, useMutation, invalidateQueries [VERIFIED]
- fastapi.tiangolo.com/tutorial/cors/ — CORSMiddleware parameters [VERIFIED]
- fastapi.tiangolo.com/advanced/custom-response/ — FileResponse API [VERIFIED]
- ui.shadcn.com/docs/installation/vite — shadcn init with Tailwind v4, path alias [VERIFIED]
- ui.shadcn.com/docs/tailwind-v4 — shadcn v4 breaking changes (forwardRef removal, tailwindcss-animate deprecation) [VERIFIED]
- tailwindcss.com/docs/upgrade-guide — v4 CSS variable system, `@import` syntax, conflict analysis [VERIFIED]

### Secondary (MEDIUM confidence)
- Codebase inspection — `health.py`, `extraction.py`, `invoice.py`, `main.py`, `models.py`, `config.py`, `index.css`, `package.json`, `vite.config.ts` [VERIFIED via Read tool]

### Tertiary (LOW confidence)
- None in this research.

---

## Metadata

**Confidence breakdown:**
- Standard stack versions: HIGH — verified via npm registry
- Tailwind v4 setup: HIGH — verified via official docs
- shadcn/ui v4 compatibility: HIGH — verified via official shadcn docs
- React Router v7 patterns: HIGH — verified via Context7
- TanStack Query v5 patterns: HIGH — verified via Context7
- FastAPI CORS + FileResponse: HIGH — verified via official FastAPI docs
- Existing backend patterns: HIGH — verified via direct codebase inspection
- CSS custom property conflict analysis: HIGH — verified via official Tailwind upgrade guide

**Research date:** 2026-05-14
**Valid until:** 2026-06-14 (30 days — stable libraries; shadcn/ui moves faster, re-verify if > 2 weeks)
