---
phase: 04-admin-ui
plan: 01
subsystem: backend/tests
tags: [tdd, red-phase, admin-api, wave-0]
dependency_graph:
  requires: []
  provides: [backend/tests/test_admin.py]
  affects: [04-02-PLAN.md]
tech_stack:
  added: []
  patterns: [ASGITransport fixture, dependency_overrides, pytest-asyncio]
key_files:
  created:
    - backend/tests/test_admin.py
  modified: []
decisions:
  - "Deferred all app-code imports to fixture/test bodies so --collect-only succeeds before Plan 04-02 exists"
  - "Helper functions _make_gasto/_make_cierre centralize row construction with explicit created_at for order assertions"
  - "Both tasks (gastos/ticket/draft/Decimal + cierres/CORS) written in one file — no fixture duplication"
metrics:
  duration: 8m
  completed: 2026-05-31
  tasks_completed: 2
  files_created: 1
---

# Phase 04 Plan 01: RED Test Suite for Admin Read Endpoints — Summary

**One-liner:** 12 RED pytest tests locking the contract for four GET endpoints (gastos list/detail/ticket, cierres) with committed-only, Decimal-as-string, and CORS security gates — all fail 404 until Plan 04-02 implements `admin.py`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Write gastos-list + detail + ticket + drafts + Decimal RED tests | cdd2e6c | backend/tests/test_admin.py |
| 2 | Write cierres-list + CORS-header RED tests | cdd2e6c | backend/tests/test_admin.py (appended) |

## Verification Results

### Collection
```
python -m pytest tests/test_admin.py --collect-only -q
12 tests collected in 0.06s  ← ZERO errors
```

### RED State Confirmed
```
python -m pytest tests/test_admin.py -x -q
FAILED tests/test_admin.py::test_list_gastos_empty - assert 404 == 200
1 failed in 0.43s  ← endpoints not mounted yet (correct)
```

### Full Suite — No Regression
```
python -m pytest tests/ --collect-only -q
184 tests collected in 0.28s  ← was 172 before; 12 new tests added
```

## Tests Written

| Test Node ID | Requirement | Security Gate |
|---|---|---|
| `test_list_gastos_empty` | UI-01 | — |
| `test_list_gastos_newest_first` | UI-01 | — |
| `test_list_gastos_date_filter` | UI-01 | — |
| `test_list_gastos_search` | UI-01 | T-04-02 (SQLi-safe ILIKE surface) |
| `test_get_gasto` | UI-01 | — |
| `test_get_gasto_not_found` | UI-01 | input validation |
| `test_get_ticket_no_path` | UI-01 | T-04-04 (404-on-no-ticket locked) |
| `test_drafts_not_exposed` | UI-01 | T-04-01 (committed-only boundary) |
| `test_decimal_serialization` | UI-01 | Decimal precision gate |
| `test_list_cierres_empty` | UI-02 | — |
| `test_list_cierres` | UI-02 | Decimal precision gate (cierres) |
| `test_cors_header` | UI-01/02 | T-04-03 (CORS allow_origins) |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — this plan creates tests only; no production code was written.

## Threat Flags

None — test file only. No new network endpoints, auth paths, or schema changes introduced.

## Self-Check: PASSED

- [x] `backend/tests/test_admin.py` exists (411 lines)
- [x] Commit `cdd2e6c` verified in git log
- [x] All 12 named tests present per 04-VALIDATION.md
- [x] Collection clean (0 errors)
- [x] RED state confirmed (all tests fail with 404)
- [x] No full-suite collection regression (184 collected)
