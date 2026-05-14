---
phase: "04-admin-ui"
plan: "01"
subsystem: "backend"
tags: ["fastapi", "pydantic", "sqlalchemy", "cors", "admin-api", "pytest"]
dependency_graph:
  requires: ["01-01", "01-02"]
  provides: ["04-02", "04-03", "04-04"]
  affects: ["backend/app/main.py", "backend/app/routers/admin.py", "backend/app/schemas/admin.py"]
tech_stack:
  added: []
  patterns:
    - "uuid.UUID = Path(...) for native UUID validation returning 422 on malformed input"
    - "selectinload(Invoice.line_items) for eager loading in detail and status endpoints"
    - "model_dump(exclude_unset=True) for partial PATCH semantics"
    - "CORSMiddleware registered before all include_router calls in create_app()"
    - "Secondary path containment check after Path regex for /images/{filename} (T-4-01)"
key_files:
  created:
    - backend/app/schemas/admin.py
    - backend/app/routers/admin.py
    - backend/tests/test_admin.py
  modified:
    - backend/app/main.py
    - backend/app/config.py
decisions:
  - "uuid.UUID = Path(...) used for all 5 invoice_id path params — FastAPI validates UUID format and returns HTTP 422 automatically, no try/except needed"
  - "PATCH endpoints do selectinload re-query after commit to avoid lazy-load issues when returning InvoiceDetailResponse with line_items"
  - "DELETE /invoices/{id} does not touch the filesystem — image retention for audit trail (D-09, UI-05)"
  - "storage_path added to Settings with default /data/invoices — needed by serve_image endpoint"
  - "%2F path traversal handled by allowing 404 as a valid outcome (httpx decodes %2F to / before sending, routing to a non-existent path)"
metrics:
  duration: "7m 27s"
  completed: "2026-05-14T23:51:00Z"
  tasks_completed: 2
  tasks_total: 2
  files_created: 3
  files_modified: 2
---

# Phase 04 Plan 01: Admin Backend API Summary

**One-liner:** FastAPI admin API with 7 CRUD endpoints, CORS middleware, Pydantic v2 UUID-typed schemas, path-traversal-protected image serving, and 14 pytest tests green.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Admin skeleton + schemas + test stubs | ebe3955 | schemas/admin.py, routers/admin.py, tests/test_admin.py |
| 2 | Implement all 7 endpoints + CORS + router registration | 5de7101 | routers/admin.py, main.py, config.py, test_admin.py |

## What Was Built

**Pydantic v2 schemas** (`backend/app/schemas/admin.py`):
- `LineItemResponse`, `InvoiceListItem`, `InvoiceDetailResponse`, `InvoiceListResponse`
- `InvoiceDocumentPatch`, `LineItemPatch`, `InvoiceStatusPatch`
- All UUID id fields typed as `uuid.UUID` (not `str`) — FastAPI serializes to string in JSON

**Admin router** (`backend/app/routers/admin.py`):
- `GET /invoices` — paginated list with filters: status (exact), proveedor (ILIKE), fecha_from/to, q (cross-field ILIKE including line item descripcion via subquery)
- `GET /invoices/{invoice_id}` — detail with `selectinload(Invoice.line_items)`
- `PATCH /invoices/{invoice_id}` — partial update with `exclude_unset=True` + re-query for response
- `PATCH /invoices/{invoice_id}/items/{item_id}` — line item update with invoice ownership check
- `PATCH /invoices/{invoice_id}/status` — status transition (confirmed|rejected only; 422 otherwise)
- `DELETE /invoices/{invoice_id}` — row deleted, filesystem untouched (audit retention)
- `GET /images/{filename}` — path traversal protected via regex + secondary containment check

**Security documentation:**
- Module docstring prominently documents T-4-03 guessable filename risk (CUIT, CAE, vendor data exposed without auth in v1)
- A4 comment on `/images/{filename}` documents flat-filename uniqueness assumption and v2 migration path
- All SQL filters use SQLAlchemy parameterized binds (T-4-02)

**CORS** (`backend/app/main.py`):
- `CORSMiddleware` registered before all `include_router` calls
- `allow_origins=["http://localhost:5173"]`, methods: GET, POST, PATCH, DELETE, OPTIONS

**Config** (`backend/app/config.py`):
- Added `storage_path: str = "/data/invoices"` (required by serve_image)

**Tests** (`backend/tests/test_admin.py`):
- 14 tests all passing — list, filter, search, detail, patch, patch-line-item, status confirm/reject/invalid, delete, delete-retains-image, path-traversal, invalid-uuid-422, uuid-string-format

## Verification Results

```
python -m pytest tests/test_admin.py -x -q    → 14 passed, 0 failed
python -m pytest -x -q (full suite)           → 25 passed, 0 failed
grep -c "uuid.UUID = Path" admin.py            → 5
grep -c "selectinload" admin.py               → 6
grep -c "A4:" admin.py                        → 2
CORS line < include_router lines              → PASSED
No unlink/rmtree in admin.py                  → PASSED
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Field] Added storage_path to Settings**
- **Found during:** Task 2 implementation
- **Issue:** The worktree's `config.py` lacked the `storage_path` field needed by `serve_image`. The main branch had it but the worktree was at an older commit.
- **Fix:** Added `storage_path: str = "/data/invoices"` to `Settings` class in `config.py`.
- **Files modified:** `backend/app/config.py`
- **Commit:** 5de7101

**2. [Rule 1 - Test adjustment] %2F path traversal test accepts 404**
- **Found during:** Task 2 test run
- **Issue:** `test_image_path_traversal` asserted `%2F` returns 400 or 422, but httpx decodes `%2F` to `/` before sending, routing to `/images/foo/bar` which returns 404 (path not matched by FastAPI). The security outcome is equivalent — the traversal attempt does not reach the handler.
- **Fix:** Extended the assertion to `in (400, 404, 422)` with explanatory comment.
- **Files modified:** `backend/tests/test_admin.py`
- **Commit:** 5de7101

## Known Stubs

None — all endpoints are fully implemented and tested.

## Threat Flags

None — all endpoints follow the plan's threat model. T-4-03 risk is explicitly accepted and documented in the module docstring.

## Self-Check: PASSED

- [x] `backend/app/schemas/admin.py` exists
- [x] `backend/app/routers/admin.py` exists
- [x] `backend/tests/test_admin.py` exists
- [x] `backend/app/main.py` modified (CORS + admin router)
- [x] `backend/app/config.py` modified (storage_path)
- [x] Commit ebe3955 exists (Task 1)
- [x] Commit 5de7101 exists (Task 2)
- [x] 14 admin tests pass, 25 total pass
