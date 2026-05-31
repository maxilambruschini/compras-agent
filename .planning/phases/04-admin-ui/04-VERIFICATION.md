---
phase: 04-admin-ui
verified: 2026-05-31
status: human_needed
score: 8/8 automatable must-haves verified
verifier: orchestrator (direct — gsd-verifier agent truncated before writing; evidence gathered and assessed inline)
---

# Phase 04: Admin UI — Verification

**Goal:** A manager or accountant can open the web UI and view all captured gastos and
caja closings — read-only lists showing only committed records, not in-progress
conversation drafts.

**Requirements:** UI-01 (list/view gastos), UI-02 (list/view cierres) — both covered by Plans 04-01/02/03.

## Automated Evidence (all PASS)

| # | Must-have | Evidence | Status |
|---|-----------|----------|--------|
| 1 | `GET /api/gastos` lists committed gastos, newest-first | `test_admin.py::test_list_gastos_newest_first`, `test_list_gastos_empty` | ✅ |
| 2 | Drafts never exposed (committed-only boundary) | `test_drafts_not_exposed` PASS; `admin.py` selects `Gasto`/`CajaCierre` only — the 3 `conversations` references are docstrings documenting the boundary, not queries | ✅ |
| 3 | Date-range + concepto search filtering | `test_list_gastos_date_filter`, `test_list_gastos_search`, `test_list_gastos_search_percent_literal` (literal `%` after WR-01 fix) | ✅ |
| 4 | `GET /api/gastos/{id}` detail + 404 | `test_get_gasto`, `test_get_gasto_not_found` | ✅ |
| 5 | `GET /api/gastos/{id}/ticket` streams image / 404 when absent + path-traversal guard | `test_get_ticket_no_path`; `realpath`+`commonpath` guard reviewed | ✅ |
| 6 | `GET /api/cierres` lists caja_cierres | `test_list_cierres`, `test_list_cierres_empty` | ✅ |
| 7 | Decimal monto/efectivo serialized as string (precision preserved) | `test_decimal_serialization` | ✅ |
| 8 | CORS configured; frontend builds + lints; 3 read-only pages exist | `test_cors_header`; `pnpm build` exit 0; `pnpm lint` exit 0; no mutation/edit/delete controls in pages (grep) | ✅ |

**Test runs:** `test_admin.py` 13/13 pass · full backend suite **184 passed, 1 skipped** · `frontend pnpm build` exit 0 · `frontend pnpm lint` exit 0.

**Schema:** No drift; no migration (read-only over existing tables).
**Code review:** `04-REVIEW.md` status `resolved` (WR-01/WR-02/IN-01 fixed; WR-03 no-auth accepted per locked PROJECT.md/CONTEXT decision; IN-02 deferred).

## Human Verification Required (browser — no frontend test runner by design)

These require a running stack (`docker compose up`; or `cd backend && uvicorn ...` + `cd frontend && pnpm dev`). **Docker users must `docker compose build frontend` first** to pick up the new deps (react-router, @tanstack/react-query) — the node_modules volume is anonymous.

1. **Gastos list renders** — open `http://localhost:5173/gastos`; the table shows fecha, concepto, monto (formatted `$1.234,56`), ticket indicator, sender_phone; newest first.
2. **Filter + search** — enter a date range and a concepto search term; the list updates (query params hit the backend; react-query refetches).
3. **Gasto detail + ticket image** — click a gasto row with a ticket; the detail page shows all fields and the ticket image inline; opens full-size in a new tab (now `noopener,noreferrer`).
4. **Cierres list (read-only)** — click the "Cierres de Caja" tab; the list shows fecha, hora_cierre, efectivo_en_caja, sender_phone; confirm NO edit/delete controls are present.
5. **States** — verify spinner on load, "no records" empty state, and an inline error when the backend is down.

## Verdict

All automatable must-haves (8/8) pass: the backend read API fully satisfies UI-01/UI-02
contracts (list, filter, search, detail, ticket, cierres, Decimal precision, CORS, the
committed-only boundary), and the frontend builds and lints clean with three read-only
pages. The remaining items are live browser-rendering checks that no automated test in
this project can exercise — classified as **human_needed**, not gaps.
