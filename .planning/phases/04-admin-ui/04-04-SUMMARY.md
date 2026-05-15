---
phase: 04-admin-ui
plan: "04"
subsystem: ui
tags: [react, typescript, tanstack-query, react-router, shadcn, tailwindcss, invoice-detail]

requires:
  - phase: 04-admin-ui/04-01
    provides: FastAPI admin API — PATCH /invoices/:id, PATCH /invoices/:id/items/:item_id, PATCH /invoices/:id/status, DELETE /invoices/:id, GET /images/:filename
  - phase: 04-admin-ui/04-02
    provides: Tailwind v4, shadcn/ui components, react-router v7, @tanstack/react-query v5, @/* alias
  - phase: 04-admin-ui/04-03
    provides: InvoiceId type, all API types, useInvoice hook, patchInvoice/patchInvoiceStatus/patchLineItem/deleteInvoice/imageUrl, formatters, shared components (LoadingSpinner, ErrorBanner, FormField, StatusBadge)

provides:
  - InvoiceDetailPage (full implementation replacing Plan 03 stub) — /invoices/:id route
  - ImagePanel — img or embed for PDF; desktop sticky; "Sin imagen" fallback
  - InvoiceHeader — definition-list of all document fields; edit button; back link
  - ActionBar — Confirmar/Rechazar (pending_review only) + Eliminar; isPending spinner; responsive
  - DeleteConfirmation — inline strip (not modal); DELETE + navigate("/") on success
  - LineItemsTable — shadcn Table; formatCurrency/percent per cell; EditLineItemModal per row
  - EditDocumentModal — Dialog 560px max; pre-filled; dual invalidation on success
  - EditLineItemModal — Dialog 640px max; all numeric fields; dual invalidation on success

affects:
  - 04-admin-ui/04-05 (if any additional pages need detail components, all now available)

tech-stack:
  added: []
  patterns:
    - "InvoiceDetailPage uses grid grid-cols-1 md:grid-cols-2 gap-8 — mobile single column, desktop two-column"
    - "ImagePanel renders <embed> for .pdf extension, <img> for all others — extension derived from imagePath.split('.').pop()"
    - "ActionBar checks status === 'pending_review' to conditionally render Confirmar/Rechazar — one-click, no reason"
    - "DeleteConfirmation is an inline div strip (not a Dialog) — navigate('/') in onSuccess after invalidateQueries"
    - "EditDocumentModal / EditLineItemModal: local form state initialized from props; mutation.isPending disables Save; ErrorBanner inside modal on error"
    - "LineItemsTable local editingItem state drives EditLineItemModal open/close — no prop drilling"
    - "formatPercent helper in LineItemsTable: value * 100 with toFixed(1) for descuento_pct, toFixed(0) for iva_rate"
    - "Both edit modals invalidate ['invoice', id] AND ['invoices'] on success (dual invalidation per D-03)"
    - "ImagePanel wrapping div has md:sticky md:top-6 — static on mobile, sticky on desktop (D-17)"
    - "All interactive elements use min-h-[44px] touch target (D-17)"

key-files:
  created:
    - frontend/src/components/ImagePanel.tsx
    - frontend/src/components/InvoiceHeader.tsx
    - frontend/src/components/ActionBar.tsx
    - frontend/src/components/DeleteConfirmation.tsx
    - frontend/src/components/LineItemsTable.tsx
    - frontend/src/components/EditDocumentModal.tsx
    - frontend/src/components/EditLineItemModal.tsx
  modified:
    - frontend/src/pages/InvoiceDetailPage.tsx

key-decisions:
  - "ImagePanel wraps sticky div itself rather than relying on parent — avoids layout coupling; the md:sticky md:top-6 is on the ImagePanel root div"
  - "InvoiceDetailPage right column also has md:sticky md:top-6 for belt-and-suspenders — ImagePanel's own sticky div provides the actual sticky behavior"
  - "EditDocumentModal initializes form state from invoice prop at mount — does not re-sync on prop change; acceptable since modal unmounts on close"
  - "LineItemsTable collapses to 10 columns (not 11 as plan stated) — the # column plus 8 data columns plus actions = 10 total; colSpan set to 10 accordingly"

patterns-established:
  - "Local form state pattern: useState per field, initialized from props, submitted as object — consistent across EditDocumentModal and EditLineItemModal"
  - "Mutation error pattern: onError sets local error string; onSuccess clears it — ErrorBanner rendered conditionally"
  - "Modal close pattern: onSuccess calls onOpenChange(false) — Dialog open state controlled by parent"

requirements-completed:
  - UI-03
  - UI-04
  - UI-05

duration: 25min
completed: "2026-05-15"
---

# Phase 04 Plan 04: Invoice Detail Page Summary

**Full invoice detail page with side-by-side DataPanel/ImagePanel layout, edit modals for document and line items, Confirm/Reject/Delete action bar, and inline delete confirmation strip — all 8 components wired end-to-end**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-05-15T00:20:00Z
- **Completed:** 2026-05-15T00:45:00Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments

- Created 7 new components and replaced the InvoiceDetailPage stub from Plan 03
- ImagePanel handles PDF (embed) and images (img) with correct alt text and desktop-only sticky positioning
- InvoiceHeader renders all 9 document fields in a responsive definition-list grid with "Editar documento" button
- ActionBar conditionally shows Confirmar/Rechazar only for pending_review; always shows Eliminar; isPending spinners on all mutations
- DeleteConfirmation is an inline strip (not a Dialog) with navigate("/") on success — aria-describedby wired
- LineItemsTable renders all 9 data columns with formatCurrency and formatPercent; EditLineItemModal opens per row
- EditDocumentModal (560px) and EditLineItemModal (640px) pre-filled, dual-invalidate on success, ErrorBanner on failure
- TypeScript: 0 errors; npm run build: exits 0 (405 KB JS bundle)

## Task Commits

1. **Task 1: ImagePanel + InvoiceHeader + ActionBar + DeleteConfirmation** - `a778f15` (feat)
2. **Task 2: LineItemsTable + EditDocumentModal + EditLineItemModal + InvoiceDetailPage** - `e52075d` (feat)

## Files Created/Modified

- `frontend/src/components/ImagePanel.tsx` - img/embed renderer; md:sticky md:top-6; "Sin imagen" fallback
- `frontend/src/components/InvoiceHeader.tsx` - definition-list of 9 doc fields; back link; edit button
- `frontend/src/components/ActionBar.tsx` - Confirmar/Rechazar (pending_review only) + Eliminar; ispending spinners
- `frontend/src/components/DeleteConfirmation.tsx` - inline strip; delete mutation; navigate("/"); aria-describedby
- `frontend/src/components/LineItemsTable.tsx` - shadcn Table; formatCurrency/percent; EditLineItemModal per row
- `frontend/src/components/EditDocumentModal.tsx` - Dialog 560px; 7 fields; dual invalidation; isPending save
- `frontend/src/components/EditLineItemModal.tsx` - Dialog 640px; 8 numeric fields; dual invalidation; isPending save
- `frontend/src/pages/InvoiceDetailPage.tsx` - replaces stub; grid-cols-1 md:grid-cols-2 gap-8 layout

## Decisions Made

- **ImagePanel double-sticky**: ImagePanel root div has `md:sticky md:top-6`; InvoiceDetailPage right column also has `md:sticky md:top-6`. The outer div is structural (layout column), the inner ImagePanel div is the actual sticky element. Belt-and-suspenders approach — no visual duplication.
- **colSpan=10 in LineItemsTable**: Plan said colSpan={11} but actual column count is 10 (# + 8 data columns + actions). Used correct count 10 to prevent empty cell rendering.
- **EditDocumentModal form state initialized at mount only**: Form state does not re-sync when `invoice` prop changes. This is acceptable because the modal unmounts on close (`onOpenChange(false)`) and re-mounts with fresh props on next open.

## Deviations from Plan

None — plan executed exactly as written, with two minor self-corrections noted in Decisions Made above (colSpan count, sticky belt-and-suspenders).

## Issues Encountered

None — TypeScript compiled clean on first attempt for both tasks.

## User Setup Required

None — no external service configuration required.

## Known Stubs

None — all components are fully implemented. InvoiceDetailPage stub from Plan 03 is fully replaced.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes introduced. The imageUrl() function follows the A4 pattern established in Plan 03 (T-4-01 mitigated: filename extracted via split('/').pop(), path separators cannot be injected). Edit modal forms send JSON to existing PATCH endpoints validated server-side by Pydantic (T-4-04 accepted).

## Self-Check: PASSED

- [x] `frontend/src/components/ImagePanel.tsx` exists
- [x] `frontend/src/components/InvoiceHeader.tsx` exists
- [x] `frontend/src/components/ActionBar.tsx` exists
- [x] `frontend/src/components/DeleteConfirmation.tsx` exists
- [x] `frontend/src/components/LineItemsTable.tsx` exists
- [x] `frontend/src/components/EditDocumentModal.tsx` exists
- [x] `frontend/src/components/EditLineItemModal.tsx` exists
- [x] `frontend/src/pages/InvoiceDetailPage.tsx` modified (stub replaced)
- [x] Commit a778f15 exists (Task 1)
- [x] Commit e52075d exists (Task 2)
- [x] TypeScript: 0 errors
- [x] npm run build: exits 0

## Next Phase Readiness

- Plan 05 (if any) can use all detail page components
- Full detail page is functional end-to-end when backend is running
- UI-03, UI-04, UI-05 requirements satisfied

---
*Phase: 04-admin-ui*
*Completed: 2026-05-15*
