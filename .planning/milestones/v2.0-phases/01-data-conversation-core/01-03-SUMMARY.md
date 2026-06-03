---
phase: 01-data-conversation-core
plan: "03"
subsystem: backend/services
tags: [tdd, gasto-service, persistence, gastos-bot, stateless-service]
dependency_graph:
  requires:
    - 01-01 (Gasto ORM model)
    - 01-02 (DraftGasto DTO)
  provides:
    - GastoService (backend/app/services/gasto.py)
    - save_gasto persistence tests (backend/tests/test_gasto_service.py)
  affects:
    - backend/app/services/gasto.py (new)
    - backend/tests/test_gasto_service.py (new)
tech_stack:
  added: []
  patterns:
    - Stateless service pattern (mirrors InvoiceService — __init__ sets _log only)
    - session-first method signature: save_gasto(self, session, draft, sender_phone)
    - session.flush() (not commit) to populate id — orchestrator owns transaction
    - str.removeprefix("whatsapp:") — strips at most one leading prefix (not .replace/.strip)
    - structlog gasto.saved with id + monto for audit trail (T-03-02)
key_files:
  created:
    - path: backend/app/services/gasto.py
      purpose: GastoService with save_gasto — write side of GASTO-05 confirmation gate
    - path: backend/tests/test_gasto_service.py
      purpose: 8 TDD tests for save_gasto against aiosqlite db_session fixture
  modified: []
decisions:
  - GastoService does not commit — orchestrator owns the transaction (RESEARCH Pattern 7); flush() populates id so the caller can reference it before committing
  - removeprefix("whatsapp:") over .replace() or .strip() — strips at most one leading occurrence; .replace would strip an embedded "whatsapp:" occurrence; .strip would strip individual characters from both ends
metrics:
  duration: "~5 minutes"
  completed: "2026-05-27"
  tasks_completed: 1
  tasks_total: 1
  files_created: 2
  files_modified: 0
---

# Phase 01 Plan 03: GastoService Persistence Layer Summary

**One-liner:** Stateless GastoService.save_gasto mirrors InvoiceService — session.flush() (not commit) writes a Gasto row with fecha=today, stripped sender_phone via removeprefix, and full GASTO-05 confirmation-gate contract.

## What Was Built

### Task 1 — GastoService.save_gasto (TDD)

**`backend/app/services/gasto.py`** — GastoService:

- Constructor: `__init__(self) -> None` sets `self._log = structlog.get_logger()` — stateless, mirrors InvoiceService. No session held.
- `async def save_gasto(self, session: AsyncSession, draft: DraftGasto, sender_phone: str) -> Gasto`:
  - Builds `Gasto(fecha=date.today(), concepto=draft.concepto, monto=draft.monto, ticket_image_path=draft.ticket_image_path, sender_phone=clean_phone)`.
  - `clean_phone = sender_phone.removeprefix("whatsapp:").strip()` — strips exactly one leading `"whatsapp:"` occurrence. `removeprefix` is the correct primitive: `.replace("whatsapp:", "")` would strip an embedded occurrence; `.strip("whatsapp:")` would strip those individual characters from both ends.
  - `session.add(gasto)` then `await session.flush()` — populates `gasto.id` without committing. The orchestrator (Plan 04) owns the transaction and calls `session.commit()` after confirmation.
  - Logs `gasto.saved` with `id=str(gasto.id)` and `monto=str(draft.monto)` — audit trail per T-03-02.

**`backend/tests/test_gasto_service.py`** — 8 tests using the `db_session` aiosqlite fixture:

1. `test_save_gasto_inserts_one_row` — exactly one gastos row inserted
2. `test_save_gasto_fields` — fecha=today, concepto, monto, ticket_image_path all correct
3. `test_save_gasto_strips_whatsapp_prefix` — `"whatsapp:+549..."` → `"+549..."`
4. `test_save_gasto_strips_only_one_whatsapp_prefix` — `"whatsapp:whatsapp:+549..."` → `"whatsapp:+549..."` (proves removeprefix vs replace distinction)
5. `test_save_gasto_no_prefix_unchanged` — `"+549..."` → `"+549..."` (idempotent on no-match)
6. `test_save_gasto_returns_id_before_caller_commits` — id populated by flush; row visible within same session before caller commits
7. `test_save_gasto_ticket_image_path_none` — `ticket_image_path=None` yields None in DB (GASTO-04)
8. `test_gasto_service_is_stateless` — `vars(svc)` contains only `_log`

## Deviations from Plan

None — plan executed exactly as written.

TDD gate compliance:
- RED gate: `test(01-03)` commit `695477a` — 7 failing behavior tests (import error; GastoService not yet implemented)
- GREEN gate: `feat(01-03)` commit `64d11f5` — all 8 tests pass (note: stateless test added during implementation as it required no RED failure path — it passes trivially once the class exists; documented as a non-behavior test)

## Test Results

```
8 passed  (tests/test_gasto_service.py)
113 passed, 1 skipped  (full suite — baseline was 105 passed, 1 skipped)
```

Acceptance criteria verified:
- `gasto.py` contains `removeprefix("whatsapp:")` — PASS
- `gasto.py` does NOT contain `.replace("whatsapp:"` — PASS
- `gasto.py` does NOT contain `session.commit` — PASS
- `gasto.id` is non-None after `save_gasto` returns (flushed) — PASS
- `ticket_image_path=None` → DB row has `None` — PASS
- `GastoService` holds no session state — PASS

## Known Stubs

None — this plan creates pure service/persistence code. No UI rendering, no data wiring.

## Threat Flags

None — no new network endpoints, no auth paths, no file access patterns, no new schema changes beyond what the plan's threat model covers.

**T-03-01 (Tampering, monto):** mitigated — `save_gasto` is invoked only after the orchestrator's deterministic confirm gate (Plan 04); monto carried as Decimal from DraftGasto; no implicit save path exists.
**T-03-02 (Repudiation, audit):** mitigated — structlog `gasto.saved` logged with `id` + `monto` on every write.

## Self-Check: PASSED

| Item | Status |
|------|--------|
| backend/app/services/gasto.py | FOUND |
| backend/tests/test_gasto_service.py | FOUND |
| .planning/phases/01-data-conversation-core/01-03-SUMMARY.md | FOUND |
| Commit 695477a (RED test_gasto_service) | FOUND |
| Commit 64d11f5 (GREEN GastoService) | FOUND |
| 8 tests pass (test_gasto_service) | PASSED |
| Full suite 113 passed 1 skipped | PASSED |
| removeprefix("whatsapp:") in gasto.py | PASSED |
| No session.commit in gasto.py | PASSED |
