---
phase: 03-prompt-trigger-endpoint
plan: "03"
subsystem: backend/app/services
tags: [fsm, caja-cierre, conversation, tdd-green, wave-2, decimal-safe, art-timezone]
dependency_graph:
  requires:
    - 03-01 (cierre.py skeleton, RED tests)
    - 03-02 (ConvState.AWAITING_CIERRE + AWAITING_CIERRE_CONFIRM constants)
  provides:
    - backend/app/services/cierre.py (CajaCierreService.save_cierre fully implemented)
    - backend/app/models/conversation.py (DraftCierre model)
    - backend/app/services/conversation.py (AWAITING_CIERRE/AWAITING_CIERRE_CONFIRM dispatch arms + _handle_awaiting_cierre + _handle_cierre_confirm)
  affects:
    - backend/tests/test_conversation_cierre.py (8 tests now GREEN)
tech_stack:
  added: []
  patterns:
    - parse_ars_amount called BEFORE GPT slot extraction in disambiguation handler (no API cost on bare-amount path)
    - Deterministic is_confirmation gate at DB write boundary — GPT never invoked at confirm step
    - DraftCierre stored in shared draft_gasto TEXT column as JSON (column reuse — FSM is always in gasto path OR cierre path, never both)
    - conv.draft_gasto always reassigned (never mutated in-place) to trigger SQLAlchemy change-tracking (Pitfall E)
    - session.flush() not commit() in save_cierre — caller (orchestrator) owns transaction
    - Local import of CajaCierreService and _derive_hora_cierre inside handler methods to avoid potential circular imports
key_files:
  created: []
  modified:
    - backend/app/services/cierre.py
    - backend/app/models/conversation.py
    - backend/app/services/conversation.py
    - backend/tests/test_conversation_cierre.py
decisions:
  - "DraftCierre placed in app/models/conversation.py alongside DraftGasto for consistency; imported into conversation.py"
  - "Test bug fixed: all 4 FSM tests used db_session.flush() before handle_message; this leaves SQLAlchemy autobegin transaction open so session.begin() inside orchestrator raises InvalidRequestError; changed to db_session.commit() to match test_conversation.py established pattern"
  - "No cancel handling added in cierre handlers — global cancel at handle_message Step 6 covers all states including AWAITING_CIERRE and AWAITING_CIERRE_CONFIRM"
  - "CajaCierreService instantiated inline (CajaCierreService()) inside _handle_cierre_confirm — stateless service, no dependency injection needed (mirrors GastoService pattern)"
metrics:
  duration: "~10 minutes"
  completed: "2026-05-30"
  tasks_completed: 2
  files_modified: 4
---

# Phase 3 Plan 03: CajaCierreService.save_cierre + AWAITING_CIERRE FSM Handlers Summary

**One-liner:** Decimal-safe save_cierre with ART hora_cierre/fecha, DraftCierre model, and AWAITING_CIERRE disambiguation (bare amount → confirm; gasto intent → handoff) + deterministic confirm gate — all 8 cierre tests GREEN, full suite clean.

## What Was Built

### Task 1: CajaCierreService.save_cierre

Replaced the `NotImplementedError` stub with a complete implementation in `backend/app/services/cierre.py`:

- `clean_phone = sender_phone.removeprefix("whatsapp:").strip()` — strip prefix, mirrors GastoService
- `hora_cierre = _derive_hora_cierre()` — "12:00" before 14:30 ART, "17:00" at/after (existing pure function)
- `fecha = _today_art()` — ART date via `datetime.now(_ART).date()`, NOT UTC
- `CajaCierre(fecha=fecha, hora_cierre=hora_cierre, efectivo_en_caja=efectivo_en_caja, sender_phone=clean_phone)` — Decimal passed straight to `Numeric(14,2)`, no `float()` conversion
- `session.add(cierre)` + `await session.flush()` — caller owns transaction (no commit)
- `self._log.info("cierre.saved", id=str(cierre.id), hora_cierre=hora_cierre, monto=str(efectivo_en_caja))` — structlog audit trail

Verified: `grep -c "float("` returns 0; `session.flush` present; `session.commit` absent.

### Task 2: DraftCierre + AWAITING_CIERRE FSM Handlers

**app/models/conversation.py** — added `DraftCierre(BaseModel)`:
```python
class DraftCierre(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    cierre_monto: Optional[Decimal] = None
```

**app/services/conversation.py** — three changes:

1. Import: `from app.models.conversation import DraftCierre, DraftGasto, GastoSlots`

2. Dispatch arms (after `ConvState.CONFIRM`, before default):
   ```python
   case ConvState.AWAITING_CIERRE:
       reply = await self._handle_awaiting_cierre(session, conv, text)
   case ConvState.AWAITING_CIERRE_CONFIRM:
       reply = await self._handle_cierre_confirm(session, conv, text)
   ```

3. Handler methods `_handle_awaiting_cierre` and `_handle_cierre_confirm`:
   - `_handle_awaiting_cierre`: parse_ars_amount first → DraftCierre JSON reassign + AWAITING_CIERRE_CONFIRM + confirm echo; else GPT slots, if gasto intent → reset draft_gasto=None + state=IDLE then delegate to _handle_idle; else re-prompt
   - `_handle_cierre_confirm`: load DraftCierre (try/except → warn), is_confirmation gate → save_cierre + IDLE; else re-echo confirm

**tests/test_conversation_cierre.py** (Rule 1 bug fix): all 4 FSM test seeds changed from `await db_session.flush()` to `await db_session.commit()` — matches `test_conversation.py` established pattern; flush leaves an open autobegin transaction that blocks `async with session.begin()` in the orchestrator.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_conversation_cierre.py used flush() instead of commit() before handle_message calls**
- **Found during:** Task 2 — test_bare_amount_advances_to_confirm failing with `InvalidRequestError: A transaction is already begun on this Session`
- **Issue:** 4 FSM tests seeded conversation rows with `await db_session.flush()` then immediately called `orch.handle_message()`. SQLAlchemy autobegin starts a transaction on flush. The orchestrator's `async with session.begin()` then raises because a transaction is already active.
- **Fix:** Changed all 4 occurrences to `await db_session.commit()` (matching `test_conversation.py` lines 252, 302, 413, 478 etc. which all use `commit()` before orchestrator calls).
- **Files modified:** backend/tests/test_conversation_cierre.py
- **Commit:** 32a2326 (included with Task 2 changes)

## Known Stubs

None. All Plan 03 deliverables are fully implemented. CajaCierreService.save_cierre is no longer a stub. The AWAITING_CIERRE/AWAITING_CIERRE_CONFIRM FSM arms are fully functional.

## Threat Flags

None. No new network endpoints, auth paths, file access patterns, or schema changes beyond what the plan's threat model covered.

All threat mitigations from the plan implemented:
- T-03-W1: is_confirmation gate before save_cierre — confirmed by test_confirm_requires_exact_token
- T-03-W2: conv.draft_gasto=None before _handle_idle gasto handoff (Pitfall 4)
- T-03-W3: Decimal passed straight to Numeric(14,2) — no float() conversion
- T-03-W4: Always reassign conv.draft_gasto (never mutate in-place — Pitfall E)
- T-03-W5: structlog "cierre.saved" with id/hora/monto + sender_phone stored on row

## Self-Check: PASSED

- backend/app/services/cierre.py — save_cierre implemented: FOUND
- backend/app/models/conversation.py — DraftCierre class: FOUND
- backend/app/services/conversation.py — AWAITING_CIERRE dispatch arm: FOUND
- backend/app/services/conversation.py — AWAITING_CIERRE_CONFIRM dispatch arm: FOUND
- backend/app/services/conversation.py — _handle_awaiting_cierre method: FOUND
- backend/app/services/conversation.py — _handle_cierre_confirm method: FOUND
- Commit 871c6d2 (Task 1 — save_cierre): FOUND
- Commit 32a2326 (Task 2 — FSM + DraftCierre): FOUND
- 8 test_conversation_cierre.py tests GREEN: VERIFIED (8 passed)
- test_conversation.py green (no regression): VERIFIED (32 passed)
- Full suite green: VERIFIED (169 passed, 1 skipped)
- grep -c "float(" cierre.py = 0: VERIFIED
- grep "session.flush" cierre.py present: VERIFIED
- grep -c "session.commit" cierre.py = 0: VERIFIED
- grep -c "AWAITING_CIERRE_CONFIRM" conversation.py >= 3: VERIFIED (3)
- No is_cancel/cancel handling in _handle_awaiting_cierre or _handle_cierre_confirm: VERIFIED
- parse_ars_amount called before _slot_service.extract in _handle_awaiting_cierre: VERIFIED
