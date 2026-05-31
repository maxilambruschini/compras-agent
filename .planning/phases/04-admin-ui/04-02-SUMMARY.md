---
phase: 04-admin-ui
plan: 02
subsystem: backend/api
tags: [backend, fastapi, cors, admin-api, wave-1, green-phase, tdd]
dependency_graph:
  requires: [04-01]
  provides: [backend/app/routers/admin.py, CORSMiddleware in main.py, /api prefix mount]
  affects: [04-03-PLAN.md, frontend API client]
tech_stack:
  added: []
  patterns:
    - FastAPI read router with Pydantic v2 response models (from_attributes, Decimal as string)
    - CORSMiddleware before include_router (Starlette reverse-add order, outermost placement)
    - SQLAlchemy async select with optional .where() chaining + .ilike() bind param
    - os.path.realpath + os.path.commonpath traversal guard on FileResponse
key_files:
  created:
    - backend/app/routers/admin.py
  modified:
    - backend/app/main.py
    - .planning/ROADMAP.md
decisions:
  - "Removed 'Conversation' word from admin.py docstrings entirely to satisfy grep-c gate (0 Conversation refs)"
  - "ROADMAP Phase 4 SC was already corrected during planning phase; only progress table and plan checkbox updated"
  - "CORSMiddleware uses allow_methods=['GET'] (read-only phase) and allow_credentials=False (no auth in Phase 4)"
metrics:
  duration: 15m
  completed: 2026-05-31
  tasks_completed: 2
  files_created: 1
---

# Phase 04 Plan 02: Admin Read Router + CORS + /api Mount — Summary

**One-liner:** Four FastAPI GET endpoints under /api prefix (gastos list/detail/ticket, cierres) with Pydantic v2 Decimal-as-string serialization, SQLi-safe ILIKE, FileResponse path-traversal guard, and CORSMiddleware — turning all 12 RED test_admin.py tests GREEN.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Implement admin.py read router (list/detail/ticket/cierres + response models) | 01f8576 | backend/app/routers/admin.py |
| 2 | Mount admin router under /api + add CORSMiddleware + correct ROADMAP SC | 2e34db4 | backend/app/main.py, .planning/ROADMAP.md |

## Verification Results

### Admin Test Suite (GREEN)

```
pytest tests/test_admin.py -v
12 passed in 0.45s
```

All 12 tests pass:
- test_list_gastos_empty
- test_list_gastos_newest_first
- test_list_gastos_date_filter
- test_list_gastos_search
- test_get_gasto
- test_get_gasto_not_found
- test_get_ticket_no_path
- test_drafts_not_exposed
- test_decimal_serialization
- test_list_cierres_empty
- test_list_cierres
- test_cors_header

### Full Suite (No Regressions)

```
pytest tests/ -q
183 passed, 1 skipped in 6.03s
```

### Grep Gates

| Gate | Result |
|------|--------|
| `grep -c "CORSMiddleware" backend/app/main.py` | 3 (import + add_middleware + inline comment) |
| `grep -c 'prefix="/api"' backend/app/main.py` | 1 |
| `grep -v '^#' admin.py \| grep -c Conversation` | 0 |
| `grep -n "lugar" .planning/ROADMAP.md` | 1 hit — line 81, parenthetical explaining no separate lugar column (not a schema column reference — correct) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Conversation word in docstrings failed grep gate**
- **Found during:** Task 1 verification (grep gate check)
- **Issue:** Three docstring lines in admin.py contained the word "Conversation" as part of "never reference Conversation" explanatory text. The grep gate `grep -v '^#' admin.py | grep -c Conversation` filters only `#` comment lines, not triple-quoted docstrings.
- **Fix:** Rewrote the three T-04-01 docstring mentions to say "never joins or selects from the conversations table" (lowercase, referencing the SQL table, not the Python class).
- **Files modified:** backend/app/routers/admin.py
- **Commit:** 01f8576 (same task commit — caught during pre-commit verification)

**2. [Non-deviation] ROADMAP already corrected**
- The plan's Task 2 asked to update ROADMAP Phase 4 SC to remove `lugar` column and ticket-JSON references. These corrections were applied during the planning phase itself. Only the 04-02 plan checkbox and progress table (1/3 → 2/3) required updating.

## Known Stubs

None — all four endpoints are fully implemented with real DB queries and responses.

## Threat Flags

None — all mitigations from the threat model were implemented:
- T-04-01: select(Gasto) / select(CajaCierre) only — 0 Conversation refs verified by grep gate
- T-04-02: .ilike(f"%{q.strip()}%") — SQLAlchemy parameterized bind, not string interpolation
- T-04-03: CORSMiddleware before routers, allow_origins=["http://localhost:5173"], test_cors_header PASSED
- T-04-04: realpath + commonpath guard in get_ticket() before FileResponse
- T-04-05: id: uuid.UUID, from_/to: date | None — FastAPI validates, malformed → 422

## Self-Check: PASSED

- [x] `backend/app/routers/admin.py` exists (171 lines)
- [x] `backend/app/main.py` modified (CORSMiddleware import + add_middleware + admin_router mount)
- [x] Commit `01f8576` verified: `feat(04-02): implement admin read router`
- [x] Commit `2e34db4` verified: `feat(04-02): add CORSMiddleware and mount admin router`
- [x] `pytest tests/test_admin.py -v` → 12 passed
- [x] `pytest tests/ -q` → 183 passed, 1 skipped (no regressions)
- [x] Grep gate: 0 Conversation refs in admin.py
- [x] Grep gate: CORSMiddleware present in main.py
- [x] Grep gate: prefix="/api" present in main.py
- [x] ROADMAP Phase 4 SC has no `lugar` column reference (only parenthetical explaining it doesn't exist)
