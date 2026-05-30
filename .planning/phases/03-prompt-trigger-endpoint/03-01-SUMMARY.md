---
phase: 03-prompt-trigger-endpoint
plan: "01"
subsystem: backend/tests
tags: [tdd, red-phase, wave-0, cierre, prompt-trigger]
dependency_graph:
  requires: []
  provides:
    - backend/app/services/cierre.py (skeleton with _derive_hora_cierre, _today_art)
    - backend/tests/test_prompt_trigger.py (RED: TRIG-01, TRIG-02)
    - backend/tests/test_conversation_cierre.py (RED: CAJA-01, CAJA-02)
  affects:
    - backend/tests/conftest.py (GASTOS_PROMPT_TOKEN env var added)
    - backend/app/config.py (gastos_prompt_token field added)
tech_stack:
  added: []
  patterns:
    - Wave 0 TDD RED: test files collect cleanly before implementation exists
    - Deferred imports inside test bodies (not at module top) to avoid collection ImportError
    - zoneinfo.ZoneInfo + module-level datetime reference for patchable ART time helpers
    - Pure function helpers fully implemented in skeleton; service method raises NotImplementedError
key_files:
  created:
    - backend/app/services/cierre.py
    - backend/tests/test_prompt_trigger.py
    - backend/tests/test_conversation_cierre.py
  modified:
    - backend/app/config.py
    - backend/tests/conftest.py
decisions:
  - "gastos_prompt_token uses empty-string default (not required field) so existing tests instantiate Settings without the env var"
  - "cierre.py uses module-level datetime reference (not datetime.datetime) so tests can patch app.services.cierre.datetime"
  - "All imports of ConvState.AWAITING_CIERRE and DraftCierre deferred to test bodies to maintain collection safety in Wave 0"
  - "hora_cierre pure time helpers fully implemented (no NotImplementedError); only save_cierre is stubbed"
metrics:
  duration: "4m 23s"
  completed: "2026-05-30"
  tasks_completed: 3
  files_modified: 5
---

# Phase 3 Plan 01: Wave 0 RED Setup Summary

**One-liner:** TDD Wave 0 RED scaffold — bearer token config field, conftest wiring, CajaCierreService skeleton with ART time helpers, and 16 failing tests asserting TRIG-01/TRIG-02/CAJA-01/CAJA-02 behavior.

## What Was Built

### Task 1: Settings field + conftest wiring + cierre.py skeleton

- Added `gastos_prompt_token: str = ""` to `Settings` in `backend/app/config.py` (line 51), following the same empty-string-default pattern as `twilio_from_number`. Inline comment documents the fail-closed enforcement contract.
- Added `mp.setenv("GASTOS_PROMPT_TOKEN", "test-prompt-token")` to the `env_setup` session fixture in `backend/tests/conftest.py` (immediately after the `AGENT_MODE` setenv, per Pitfall 6 from research).
- Created `backend/app/services/cierre.py` with:
  - Module-level `_ART = ZoneInfo("America/Argentina/Buenos_Aires")` and `_CUTOFF = time(14, 30)`
  - Fully implemented `_derive_hora_cierre() -> str` (returns "12:00" if before 14:30 ART, "17:00" otherwise)
  - Fully implemented `_today_art()` (returns `datetime.now(_ART).date()`)
  - `class CajaCierreService` with `__init__` (structlog logger) and `save_cierre` stub raising `NotImplementedError`
  - Module-level `datetime` reference (not `from datetime import datetime`) so `patch("app.services.cierre.datetime")` works in tests

### Task 2: test_prompt_trigger.py (TRIG-01, TRIG-02)

8 tests covering every TRIG-01/TRIG-02 requirement:

| Test | Requirement | Expected state |
|------|-------------|----------------|
| `test_valid_token_sends` | TRIG-01 auth | RED (404 — endpoint missing) |
| `test_missing_token_401` | TRIG-01 auth | RED (404) |
| `test_wrong_token_401` | TRIG-01 auth | RED (404) |
| `test_empty_configured_token_denies` | T-03-A2 (fail-closed) | RED (404) |
| `test_active_conversation_skipped` | TRIG-01 skip | RED (404) |
| `test_state_set_to_awaiting_cierre` | TRIG-01 state | RED (AttributeError on AWAITING_CIERRE) |
| `test_prompt_text_sent` | TRIG-02 | RED (404) |
| `test_row_lock_issued` | TRIG-01 lock | RED (404) |

All imports of `app.routers.prompt` are deferred inside fixture/test bodies so collection succeeds before Plan 02 creates the router.

### Task 3: test_conversation_cierre.py (CAJA-01, CAJA-02)

8 tests covering every CAJA-01/CAJA-02 requirement:

| Test | Requirement | Expected state |
|------|-------------|----------------|
| `test_bare_amount_advances_to_confirm` | CAJA-01 FSM | RED (AttributeError on AWAITING_CIERRE) |
| `test_gasto_intent_handoff` | CAJA-01 FSM | RED (AttributeError) |
| `test_confirm_saves_cierre` | CAJA-01 FSM | RED (AttributeError) |
| `test_confirm_requires_exact_token` | CAJA-01 gate | RED (AttributeError) |
| `test_hora_cierre_morning` | CAJA-02 hora | **PASSES** (pure fn implemented) |
| `test_hora_cierre_afternoon` | CAJA-02 hora | **PASSES** (pure fn implemented) |
| `test_fecha_art_not_utc` | CAJA-02 fecha | RED (NotImplementedError) |
| `test_duplicate_cierres_allowed` | CAJA-02 dup | RED (NotImplementedError) |

The `test_hora_cierre_morning` and `test_hora_cierre_afternoon` tests pass immediately because `_derive_hora_cierre` is a fully-implemented pure function in the Wave 0 skeleton — this is intentional per the plan spec.

## Deviations from Plan

None. Plan executed exactly as written.

## Known Stubs

- `CajaCierreService.save_cierre` — raises `NotImplementedError("save_cierre: Plan 03 implementation pending")`. Full implementation in Plan 03 (Wave 2). Tests asserting save_cierre behavior (`test_confirm_saves_cierre`, `test_fecha_art_not_utc`, `test_duplicate_cierres_allowed`) are RED pending Plan 03.

## Threat Flags

None. This plan only adds test files, a config field, and a skeleton service. No new network endpoints, auth paths, file access patterns, or schema changes.

## Self-Check: PASSED

- `backend/app/config.py` — gastos_prompt_token field: FOUND
- `backend/tests/conftest.py` — GASTOS_PROMPT_TOKEN setenv: FOUND
- `backend/app/services/cierre.py` — created, imports cleanly: FOUND
- `backend/tests/test_prompt_trigger.py` — 8 tests collected: FOUND
- `backend/tests/test_conversation_cierre.py` — 8 tests collected: FOUND
- Commit `7e65c27` (Task 1): FOUND
- Commit `411fd85` (Task 2): FOUND
- Commit `c4280cd` (Task 3): FOUND
- 16 Phase 3 tests collect with 0 collection errors: VERIFIED
- Full suite (170 tests) collects with 0 collection errors: VERIFIED
