---
slug: ui-polish
created: 2026-05-15
status: in-progress
---

# Quick Task: UI Polish + Image Loading Fix

## Objective
Fix the broken invoice image display and improve overall UI quality across the list page, detail page, and edit modal.

## Tasks

### Task 1 — Fix image serving (backend + docker)
- Add `/invoices/{id}/image` endpoint to admin.py (looks up image_path from DB, serves file)
- Add `invoice_storage` named volume to docker-compose.yml mounted at `/data/invoices` in backend
- Update `imageUrl()` in api.ts to call `/api/invoices/{id}/image`

### Task 2 — List page UI
- Add proper header bar with background, border-bottom, and "Compras Agent" subtitle
- Add "Desde" / "Hasta" labels above date inputs in FilterToolbar
- Map `tipo_comprobante` enum values to Spanish labels in InvoiceTable (LISTA_INFORMAL → Lista informal, FACTURA_A → Factura A, etc.)
- Add hover state to table rows

### Task 3 — Detail page + modal UI
- Replace "Encabezado" h2 with supplier name as the page title in InvoiceHeader
- Change `tipo_comprobante` in EditDocumentModal from free text input to select with enum options
- Format numeric values in LineItemsTable (strip trailing zeros from 3.0000 → 3, 0.0000 → —)

## Files
- backend/app/routers/admin.py
- docker-compose.yml
- frontend/src/lib/api.ts
- frontend/src/components/FilterToolbar.tsx
- frontend/src/components/InvoiceTable.tsx
- frontend/src/components/InvoiceHeader.tsx
- frontend/src/components/EditDocumentModal.tsx
- frontend/src/components/LineItemsTable.tsx
- frontend/src/pages/InvoiceListPage.tsx
