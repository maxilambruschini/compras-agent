---
phase: 04-admin-ui
plan: "03"
subsystem: ui
tags: [react, typescript, tanstack-query, react-router, shadcn, tailwindcss, invoice-list]

requires:
  - phase: 04-admin-ui/04-01
    provides: FastAPI admin API with GET /invoices, GET /invoices/:id, PATCH, DELETE endpoints + CORS
  - phase: 04-admin-ui/04-02
    provides: Tailwind v4, shadcn/ui 9 components, react-router v7, @tanstack/react-query v5, @/* alias

provides:
  - TypeScript contract layer (types/invoice.ts — InvoiceId branded type, all API response interfaces)
  - API client (lib/api.ts — fetchInvoices, fetchInvoice, patchInvoice, patchInvoiceStatus, patchLineItem, deleteInvoice, imageUrl)
  - Argentine locale formatters (lib/format.ts — formatCurrency es-AR, formatDate DD/MM/AAAA, formatCuit)
  - TanStack Query hooks (useInvoices, useInvoice)
  - Shared components: LoadingSpinner, ErrorBanner, FormField, StatusBadge
  - Invoice list components: FilterToolbar, InvoiceTable, Pagination
  - InvoiceListPage route component (/)
  - App.tsx with BrowserRouter + Routes + QueryClientProvider root
  - InvoiceDetailPage stub (placeholder, replaced by 04-04)

affects:
  - 04-admin-ui/04-04 (InvoiceDetailPage uses all types, hooks, formatters, and shared components from this plan)
  - 04-admin-ui/04-05 (any additional pages use same type/hook/formatter layer)

tech-stack:
  added: []
  patterns:
    - "InvoiceId branded type alias (string with UUID comment) — use on all invoice id fields, not plain string"
    - "fetchInvoices filters undefined params before URLSearchParams construction — no empty query params sent"
    - "imageUrl() extracts filename via split('/').pop() — assumes flat globally unique filenames in storage_path (A4 documented)"
    - "useInvoices queryKey includes params object — TanStack Query refetches on filter change automatically"
    - "InvoiceTable uses literal className check: invoice.status === 'pending_review' ? 'bg-amber-50' : '' — no dynamic concatenation"
    - "StatusBadge maps status string to shadcn Badge variant + custom className; aria-label on each badge"
    - "FilterToolbar passes undefined (not empty string) to onFilter — api.ts filters these out before URLSearchParams"
    - "App.tsx: QueryClientProvider > BrowserRouter > Routes (outer-to-inner order required for hooks to work in route components)"
    - "Import from 'react-router' not 'react-router-dom' — react-router v7 unified package"
    - "isPending (not isLoading) for TanStack Query v5 — isLoading was renamed in v5"

key-files:
  created:
    - frontend/src/types/invoice.ts
    - frontend/src/lib/api.ts
    - frontend/src/lib/format.ts
    - frontend/src/hooks/useInvoices.ts
    - frontend/src/hooks/useInvoice.ts
    - frontend/src/components/LoadingSpinner.tsx
    - frontend/src/components/ErrorBanner.tsx
    - frontend/src/components/FormField.tsx
    - frontend/src/components/StatusBadge.tsx
    - frontend/src/components/FilterToolbar.tsx
    - frontend/src/components/InvoiceTable.tsx
    - frontend/src/components/Pagination.tsx
    - frontend/src/pages/InvoiceListPage.tsx
    - frontend/src/pages/InvoiceDetailPage.tsx
  modified:
    - frontend/src/App.tsx
    - frontend/tsconfig.json

key-decisions:
  - "InvoiceId is a type alias (not opaque type) for string — provides intent clarity without needing casting at runtime boundaries"
  - "InvoiceTable drops the 'Total' column — total_amount is absent from InvoiceListItem (list response); added 'Creado' (created_at) instead"
  - "InvoiceListPage shows only loading spinner OR error OR table — not a combination, matching standard list page UX"
  - "tsconfig.json root-level ignoreDeprecations:'6.0' added — TypeScript 6.0 deprecated baseUrl but shadcn requires it in root tsconfig"

patterns-established:
  - "All API functions in lib/api.ts use the shared request<T>() wrapper — consistent error handling across all endpoints"
  - "Formatters return '—' (em dash) for null/undefined/empty — consistent null display across all table cells and fields"
  - "Components import types from '../types/invoice' (relative) or '@/components/ui/*' (@/ alias) — two-tier import pattern"

requirements-completed:
  - UI-01
  - UI-02
  - UI-06

duration: 18min
completed: "2026-05-14"
---

# Phase 04 Plan 03: Invoice List Page Summary

**TypeScript API contract layer + TanStack Query hooks + 7 shared components + InvoiceListPage with filterable paginated table + App.tsx router — list page functional end-to-end when backend is running**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-05-14T23:59:00Z
- **Completed:** 2026-05-15T00:17:00Z
- **Tasks:** 2
- **Files modified:** 16

## Accomplishments

- Created complete TypeScript contract layer: InvoiceId branded type alias, 7 interfaces matching backend Pydantic schemas exactly
- Built API client with 7 exported functions (fetchInvoices, fetchInvoice, patchInvoice, patchInvoiceStatus, patchLineItem, deleteInvoice, imageUrl) + A4 filename assumption documented per REVIEWS.md
- Implemented Argentine locale formatters: formatCurrency (es-AR locale), formatDate (DD/MM/AAAA), formatCuit
- Created useInvoices and useInvoice TanStack Query v5 hooks with correct queryKeys
- Built 7 shared/list components: LoadingSpinner, ErrorBanner, FormField, StatusBadge (Spanish labels + aria-label), FilterToolbar (responsive flex layout), InvoiceTable (pending_review amber highlight, hidden md:table-cell columns), Pagination
- Wired App.tsx with QueryClientProvider > BrowserRouter > Routes for / and /invoices/:id
- TypeScript: 0 errors; npm run build: exits 0 (379 KB JS bundle)

## Task Commits

1. **Task 1: Types + API client + formatters + TanStack Query hooks** - `f0e9580` (feat)
2. **Task 2: Shared components + InvoiceListPage + App router wiring** - `f765dfd` (feat)

## Files Created/Modified

- `frontend/src/types/invoice.ts` - InvoiceId, LineItemResponse, InvoiceListItem, InvoiceDetailResponse, InvoiceListResponse, InvoiceListParams, InvoiceDocumentPatch, LineItemPatch
- `frontend/src/lib/api.ts` - fetch wrapper + 7 exported API functions; imageUrl with A4 JSDoc note
- `frontend/src/lib/format.ts` - formatCurrency (es-AR), formatDate (DD/MM/AAAA), formatCuit
- `frontend/src/hooks/useInvoices.ts` - useQuery with queryKey ["invoices", params]
- `frontend/src/hooks/useInvoice.ts` - useQuery with enabled: !!id guard
- `frontend/src/components/LoadingSpinner.tsx` - animate-spin Tailwind div
- `frontend/src/components/ErrorBanner.tsx` - shadcn Alert variant=destructive
- `frontend/src/components/FormField.tsx` - Label + children wrapper, space-y-2
- `frontend/src/components/StatusBadge.tsx` - shadcn Badge, Spanish labels, aria-label, pending_review amber custom class
- `frontend/src/components/FilterToolbar.tsx` - flex flex-col md:flex-row; Estado/Proveedor/Desde/Hasta/Buscar/Filtrar/Limpiar
- `frontend/src/components/InvoiceTable.tsx` - shadcn Table; bg-amber-50 literal on pending_review; hidden md:table-cell on Tipo/Número/Fecha
- `frontend/src/components/Pagination.tsx` - Anterior/Siguiente outline buttons; Página {n} de {total}; min-h-[44px]
- `frontend/src/pages/InvoiceListPage.tsx` - useInvoices hook; isPending/error/data states; FilterToolbar+InvoiceTable+Pagination
- `frontend/src/pages/InvoiceDetailPage.tsx` - intentional stub; replaced by Plan 04
- `frontend/src/App.tsx` - QueryClientProvider > BrowserRouter > Routes (react-router v7)
- `frontend/tsconfig.json` - added ignoreDeprecations "6.0" (TypeScript 6 baseUrl deprecation)

## Decisions Made

- **Dropped "Total" column from InvoiceTable** — `total_amount` field is absent from `InvoiceListItem` (GET /invoices list response only returns InvoiceListItem shape). Added "Creado" (created_at) column instead, which is available and useful for sorting context.
- **tsconfig.json ignoreDeprecations** — TypeScript 6.0 deprecated `baseUrl` but shadcn@2 requires it in root `tsconfig.json` for alias detection; added `"ignoreDeprecations": "6.0"` to suppress the error.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] tsconfig.json missing ignoreDeprecations for TypeScript 6.0 baseUrl deprecation**
- **Found during:** Task 1 (TypeScript compile check)
- **Issue:** `./node_modules/.bin/tsc --noEmit` produced `error TS5101: Option 'baseUrl' is deprecated` — the root `tsconfig.json` needed `"ignoreDeprecations": "6.0"` (already present in `tsconfig.app.json` from Plan 02, but missing from root)
- **Fix:** Added `"ignoreDeprecations": "6.0"` to `compilerOptions` in `frontend/tsconfig.json`
- **Files modified:** `frontend/tsconfig.json`
- **Verification:** TypeScript compiles 0 errors
- **Committed in:** f0e9580 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Necessary fix — tsconfig.json root-level was missing the same ignoreDeprecations that tsconfig.app.json already had from Plan 02. No scope creep.

## Issues Encountered

None beyond the tsconfig.json deviation above.

## Known Stubs

| Stub | File | Line | Reason |
|------|------|------|--------|
| `InvoiceDetailPage` placeholder | `frontend/src/pages/InvoiceDetailPage.tsx` | 3 | Intentional — plan explicitly calls for this stub to allow App.tsx to compile; Plan 04 (04-04) replaces it with the full detail page |

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes introduced. API client is browser-side fetch only; SQL injection mitigated server-side (T-4-02 accepted at frontend per plan threat model). Error messages in ErrorBanner accepted per T-4-frontend-01 (v1 demo, localhost only).

## Self-Check: PASSED

- [x] `frontend/src/types/invoice.ts` exists
- [x] `frontend/src/lib/api.ts` exists
- [x] `frontend/src/lib/format.ts` exists
- [x] `frontend/src/hooks/useInvoices.ts` exists
- [x] `frontend/src/hooks/useInvoice.ts` exists
- [x] `frontend/src/components/LoadingSpinner.tsx` exists
- [x] `frontend/src/components/ErrorBanner.tsx` exists
- [x] `frontend/src/components/FormField.tsx` exists
- [x] `frontend/src/components/StatusBadge.tsx` exists
- [x] `frontend/src/components/FilterToolbar.tsx` exists
- [x] `frontend/src/components/InvoiceTable.tsx` exists
- [x] `frontend/src/components/Pagination.tsx` exists
- [x] `frontend/src/pages/InvoiceListPage.tsx` exists
- [x] `frontend/src/pages/InvoiceDetailPage.tsx` exists
- [x] `frontend/src/App.tsx` modified
- [x] Commit f0e9580 exists (Task 1)
- [x] Commit f765dfd exists (Task 2)
- [x] TypeScript: 0 errors
- [x] npm run build: exits 0

## Next Phase Readiness

- Plan 04 (InvoiceDetailPage) can begin: all types, API functions, hooks, and shared components are ready
- `useInvoice(id)` hook is exported and typed with `enabled: !!id` guard
- `patchInvoice`, `patchInvoiceStatus`, `patchLineItem`, `deleteInvoice` exported and typed
- `imageUrl(imagePath)` extracts filename for `/images/{filename}` serving
- `formatCurrency`, `formatDate`, `formatCuit` ready for use in detail field display
- `FormField`, `ErrorBanner`, `LoadingSpinner`, `StatusBadge` ready for modal and detail use

---
*Phase: 04-admin-ui*
*Completed: 2026-05-14*
