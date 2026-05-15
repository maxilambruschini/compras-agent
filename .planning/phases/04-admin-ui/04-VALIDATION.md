---
phase: 4
slug: admin-ui
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-14
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio (already installed) |
| **Config file** | `backend/pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `cd backend && python -m pytest tests/test_admin.py -x -q` |
| **Full suite command** | `cd backend && python -m pytest -x -q` |
| **Estimated runtime** | ~10 seconds (backend unit tests) |

Frontend testing: No test framework installed. Backend API endpoint tests (httpx ASGI) are the automated gate; frontend is verified manually per UI-SPEC interaction contracts.

---

## Sampling Rate

- **After every task commit:** Run `cd backend && python -m pytest tests/test_admin.py -x -q`
- **After every plan wave:** Run `cd backend && python -m pytest -x -q`
- **Before `/gsd-verify-work`:** Full backend suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 4-01-01 | 01 | 1 | UI-01 | T-4-01 / — | Paginated list returns only DB rows, no path injection | unit (ASGI) | `pytest tests/test_admin.py::test_list_invoices -x` | ❌ W0 | ⬜ pending |
| 4-01-02 | 01 | 1 | UI-01 | — | Status filter returns only matching rows | unit (ASGI) | `pytest tests/test_admin.py::test_list_invoices_filter_status -x` | ❌ W0 | ⬜ pending |
| 4-01-03 | 01 | 1 | UI-02 | — | Search `?q=` matches proveedor name | unit (ASGI) | `pytest tests/test_admin.py::test_list_invoices_search -x` | ❌ W0 | ⬜ pending |
| 4-01-04 | 01 | 1 | UI-03 | — | Detail endpoint includes line_items array (selectinload) | unit (ASGI) | `pytest tests/test_admin.py::test_get_invoice_detail -x` | ❌ W0 | ⬜ pending |
| 4-02-01 | 02 | 1 | UI-04 | — | PATCH /invoices/{id} updates editable fields | unit (ASGI) | `pytest tests/test_admin.py::test_patch_invoice -x` | ❌ W0 | ⬜ pending |
| 4-02-02 | 02 | 1 | UI-04 | — | PATCH /invoices/{id}/items/{item_id} updates line item | unit (ASGI) | `pytest tests/test_admin.py::test_patch_line_item -x` | ❌ W0 | ⬜ pending |
| 4-02-03 | 02 | 1 | UI-04 | — | PATCH /invoices/{id}/status sets confirmed/rejected | unit (ASGI) | `pytest tests/test_admin.py::test_patch_status -x` | ❌ W0 | ⬜ pending |
| 4-02-04 | 02 | 1 | UI-05 | T-4-02 | DELETE removes DB row, returns 204 | unit (ASGI) | `pytest tests/test_admin.py::test_delete_invoice -x` | ❌ W0 | ⬜ pending |
| 4-02-05 | 02 | 1 | UI-05 | T-4-02 | Delete does NOT remove file from filesystem | unit | `pytest tests/test_admin.py::test_delete_retains_image -x` | ❌ W0 | ⬜ pending |
| 4-03-01 | 03 | 2 | UI-06 | — | pending_review rows visually highlighted (manual) | manual | — | — | ⬜ pending |
| 4-03-02 | 03 | 2 | UI-01 | T-4-03 | /images/{filename} rejects path separators | unit (ASGI) | `pytest tests/test_admin.py::test_image_path_traversal -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/app/routers/admin.py` — skeleton (no-op endpoints) to allow test collection without import errors
- [ ] `backend/tests/test_admin.py` — admin router endpoint test stubs for all UI-01 through UI-05 + path traversal check
- [ ] `backend/tests/conftest.py` — verify existing async session fixtures cover admin tests (same pattern as test_whatsapp_handler.py)

*All tests must be importable (no syntax errors) before Wave 0 is marked complete. Tests may be `pytest.mark.skip` until the implementation exists.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| pending_review rows highlighted amber in list | UI-06 | Visual styling — no frontend test framework installed | Open browser at localhost:5173, verify rows with status=pending_review show amber background (#fef3c7) and amber badge |
| Side-by-side layout on desktop | UI-03 | CSS layout — manual visual check | Open invoice detail at ≥1024px width; confirm DataPanel left, ImagePanel right, image sticky |
| Responsive collapse on mobile | D-17 | CSS media queries — manual | Open at <768px width; confirm single-column stacked layout, FilterToolbar stacked vertically |
| Edit modal pre-fill | UI-04 | Browser interaction | Click "Editar documento"; confirm all fields are pre-filled with current invoice values |
| Confirm/Reject disappear after action | D-04, D-07 | Browser interaction | Confirm a pending_review invoice; verify buttons disappear from ActionBar |
| Delete confirmation inline strip | UI-05 | Browser interaction | Click "Eliminar factura"; verify inline strip appears below ActionBar (no modal); confirm navigation to list after delete |

---

## Security Threat Model

| Threat ID | Pattern | STRIDE | Mitigation |
|-----------|---------|--------|------------|
| T-4-01 | Path traversal via `/images/{filename}` | Tampering | Restrict `filename` to no path separators: `Path(pattern=r"^[^/\\]+$")`; resolve and verify path stays within `settings.storage_path` |
| T-4-02 | SQL injection via search/filter params | Tampering | SQLAlchemy parameterized queries — `.where()` with bound params, never string-concatenated SQL |
| T-4-03 | Unrestricted data exposure (no auth) | Information Disclosure | Accepted for v1 demo — UI-07 deferred per locked decision; document in admin.py module docstring |
| T-4-04 | Oversized PATCH payload | Denial of Service | FastAPI default 1MB body limit; Pydantic schema rejects unknown fields |

*Note: CSRF is N/A (no session cookies — all requests are stateless in v1).*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
