# Phase 4: Admin UI - Context

**Gathered:** 2026-05-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 4 builds the React admin web UI that lets a manager or accountant view all captured invoices, search and filter them, inspect the original image alongside extracted data, correct AI extraction errors, and delete records.

Deliverables:
- React Router v7 routes: `/` (invoice list) and `/invoices/:id` (invoice detail)
- Invoice list page with pagination, filtering (proveedor, date range, status), and full-text search
- Invoice detail page with split layout: data fields (left) and original invoice image (right)
- Edit modal for document-level fields (proveedor, fecha, tipo_comprobante, CUIT, CAE, etc.)
- Edit modal per line-item row (descripcion, SKU, bultos, precio, IVA rate, etc.)
- Confirm / Reject buttons on detail page for `pending_review` invoices (one-click, no reason)
- Delete action on detail page (removes DB record, retains image file)
- Visual highlighting of `pending_review` rows in the list
- New FastAPI admin router: list, detail, PATCH document, PATCH line item, DELETE, PATCH status, GET image
- TanStack Query v5 for all data fetching and mutation invalidation

**This phase does NOT include:** authentication (deferred to v2), allowlist management UI, WhatsApp gateway configuration, extraction pipeline changes, or CSV export.

</domain>

<decisions>
## Implementation Decisions

### Editing Interaction

- **D-01:** Editing uses **two separate modals** — one for document-level fields, one per line item. The detail page has an "Edit document" button for the invoice header and an "Edit" button on each line-item row. Both open a modal form pre-filled with the current values.
- **D-02:** Saving from either modal calls a **PUT endpoint** (full replacement of the editable fields). API: `PATCH /invoices/{id}` for document fields; `PATCH /invoices/{id}/items/{item_id}` for line items.
- **D-03:** After a successful save, TanStack Query invalidates the detail query so the page re-renders with the updated values.

### Status Workflow

- **D-04:** The detail page shows **prominent Confirm and Reject buttons** when the invoice status is `pending_review`. These are the primary call-to-action for the review workflow.
- **D-05:** Both actions are **one-click** — no reason or note required. This minimizes friction for high-volume review.
- **D-06:** Confirm → sets status to `confirmed`; Reject → sets status to `rejected`. API: `PATCH /invoices/{id}/status` with `{"status": "confirmed" | "rejected"}`.
- **D-07:** Confirm and Reject buttons are NOT shown on the list view — manager must open the detail page to act. This forces the manager to see the image and data before deciding.

### Invoice Image Display

- **D-08:** The detail page uses a **side-by-side layout**: data fields (document header + line items table) on the left, the original invoice image on the right. This is the primary UX — the manager can cross-check extracted data against the source document without scrolling.
- **D-09:** The backend exposes a **dedicated `/images/{filename}` endpoint** that reads the file from the local filesystem and streams it as a response. The frontend constructs the image URL from `invoice.image_path`. This endpoint is intentionally simple for v1 but provides a hook for access control in v2 (auth middleware can be added without frontend changes).

### Frontend Routing and State Management

- **D-10:** Use **React Router v7** for client-side navigation. Routes: `/` → invoice list, `/invoices/:id` → invoice detail. Browser back button works; individual invoices are bookmarkable.
- **D-11:** Use **TanStack Query v5** for all server state. `useQuery` for list and detail reads; `useMutation` + invalidation for edits, status changes, and deletes. No hand-rolled `useEffect` data fetching.
- **D-12:** Both React Router v7 and TanStack Query v5 must be installed as part of this phase (not yet in `package.json`).

### API Layer (new FastAPI router)

- **D-13:** A new `backend/app/routers/admin.py` router handles all UI API calls. Endpoints:
  - `GET /invoices` — paginated list with filter params (proveedor, fecha_from, fecha_to, status, q for search)
  - `GET /invoices/{id}` — full detail including line items
  - `PATCH /invoices/{id}` — update document-level fields
  - `PATCH /invoices/{id}/items/{item_id}` — update a single line item
  - `PATCH /invoices/{id}/status` — set status (confirm/reject)
  - `DELETE /invoices/{id}` — remove DB record (image file is retained)
  - `GET /images/{filename}` — stream image file from local filesystem

### Visual Design for Status

- **D-14:** `pending_review` rows in the list are visually distinguished — highlighted background or a colored badge on the status column. Exact color TBD by planner (e.g., amber/yellow for "needs attention").

### Claude's Discretion

- Exact component file structure and folder layout (the planner follows existing `frontend/src/` conventions — currently just App.tsx)
- Which UI component library or CSS approach to use (no library is installed; planner may choose Tailwind, a headless component lib, or plain CSS — keep it minimal for v1)
- Pagination implementation detail (offset-based vs cursor-based; offset is simpler for v1)
- Whether to add an optimistic update on Confirm/Reject or just re-fetch after success
- Internal structuring of TanStack Query hooks (e.g., `useInvoices`, `useInvoice` — standard conventions)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Data Model
- `backend/app/db/models.py` — Invoice + InvoiceLineItem + SenderAllowlist ORM models; all column names and types (planner must use exact field names for API schemas)

### Existing Backend Patterns
- `backend/app/routers/health.py` — router pattern to follow for new admin router
- `backend/app/routers/extraction.py` — example of route with dependency injection
- `backend/app/services/invoice.py` — InvoiceService; planner should check if existing service methods can be reused for admin queries

### Frontend Scaffold
- `frontend/src/App.tsx` — current skeleton; all new code builds from here
- `frontend/package.json` — current dependencies; React Router v7 and TanStack Query v5 must be added

### Requirements
- `.planning/REQUIREMENTS.md` §Admin UI (UI-01 through UI-06) — all 6 UI requirements for this phase
- `.planning/ROADMAP.md` §Phase 4 — success criteria (6 items) that define done

### Project Decisions
- `.planning/PROJECT.md` §Key Decisions — "No auth for demo" (UI-07 deferred), "Local Docker stack instead of Supabase" (no supabase-js on frontend; all data via FastAPI REST), "StorageBackend abstraction" (image_path stored in DB)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- No reusable frontend components yet — App.tsx is a bare skeleton. Phase 4 builds all UI from scratch.
- `backend/app/services/invoice.py` — may contain query helpers reusable for the admin list/detail endpoints; planner should audit before writing new queries.

### Established Patterns
- Backend routers use `async def` with `AsyncSession = Depends(get_db)` for DB access — admin router must follow the same pattern.
- Environment wiring via Pydantic Settings (`backend/app/config.py`) — no new env vars expected for the UI, but image storage root path may need to be configurable.
- Frontend: React 19 + Vite 8 + TypeScript, no JSX pragma needed (configured in tsconfig). All new components are `.tsx`.

### Integration Points
- `create_app()` in `backend/app/main.py` — new admin router must be registered here (same pattern as whatsapp and extraction routers)
- Docker Compose: frontend runs at `:5173`, backend at `:8000`. CORS is already configured (verify) or must be added for frontend→backend calls.
- `image_path` column in Invoice stores the local filesystem path. The `/images/{filename}` endpoint must resolve this path against the same storage root used by StorageBackend.

</code_context>

<specifics>
## Specific Ideas

- The detail page's **split layout** (data left, image right) is the key UX — the manager should be able to see the original document and the extracted data simultaneously while reviewing and correcting.
- **Edit modals are pre-filled** from the current field values. The "Edit document" modal covers all document-level fields; the "Edit line item" modal covers all line-item fields for that row.
- **Confirm / Reject buttons are only visible when status is `pending_review`** — they disappear once the invoice has been actioned.
- Image is served by a dedicated backend endpoint rather than a static mount, to preserve a hook for future access control.

</specifics>

<deferred>
## Deferred Ideas

- **Authentication (UI-07)** — deferred to v2. Already logged in STATE.md and PROJECT.md.
- **CSV export** — mentioned in v2 requirements (EXP-01, EXP-02). Not in scope for Phase 4.
- **Allowlist management UI** — no requirement for v1; managers add numbers directly to the DB or via a future admin panel.
- **Optimistic reject reason / audit note** — one-click with no reason is v1; if the team wants an optional note on Reject, that's a v2 enhancement.

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 4-Admin UI*
*Context gathered: 2026-05-14*
