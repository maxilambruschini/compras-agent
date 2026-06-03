---
phase: 03-prompt-trigger-endpoint
plan: "02"
subsystem: backend/app/routers, backend/app/services, backend/app/main
tags: [bearer-auth, prompt-trigger, conversation-state, row-lock, wave-1, green-phase]
dependency_graph:
  requires:
    - 03-01 (ConvState stubs, test_prompt_trigger.py RED tests, conftest token, config field)
    - 02-02 (gastos.py: get_whatsapp_provider, _safe_send to reuse)
  provides:
    - backend/app/routers/prompt.py (POST /gastos/prompt endpoint, verify_token, PromptRequest/PromptResponse, PROMPT_TEXT)
    - backend/app/services/conversation.py (ConvState.AWAITING_CIERRE + AWAITING_CIERRE_CONFIRM constants)
    - backend/app/main.py (prompt_router mounted under agent_mode=='gastos')
  affects:
    - backend/tests/test_prompt_trigger.py (8 tests now GREEN)
tech_stack:
  added: []
  patterns:
    - HTTPBearer(auto_error=False) + secrets.compare_digest constant-time bearer auth dependency
    - Fail-closed empty-token guard (deny all when settings.gastos_prompt_token == "")
    - begin_nested() (SAVEPOINT) + explicit commit() to handle shared-session test fixtures
    - pg_insert ON CONFLICT DO NOTHING + SELECT FOR NO KEY UPDATE row lock mirrored from conversation.py
    - _safe_send called strictly AFTER transaction commits (Pitfall C send-after-commit ordering)
key_files:
  created:
    - backend/app/routers/prompt.py
  modified:
    - backend/app/services/conversation.py
    - backend/app/main.py
decisions:
  - "Use begin_nested() (SAVEPOINT) + explicit commit() instead of async with db.begin(): — the test fixtures share db_session across seed operations and the endpoint call; explicit begin() raises InvalidRequestError when autobegin has already started a transaction; begin_nested() works in both test (shared session) and production (fresh session per request)"
  - "ConvState.AWAITING_CIERRE and AWAITING_CIERRE_CONFIRM added as constants only — no FSM dispatch arms or handler methods (those land in Plan 03)"
  - "_safe_send imported from app.routers.gastos directly (not duplicated); get_whatsapp_provider likewise reused from gastos"
  - "auth.invalid_token logged with reason field but no credential value (T-03-A3)"
metrics:
  duration: "~15 minutes"
  completed: "2026-05-30"
  tasks_completed: 2
  files_modified: 3
---

# Phase 3 Plan 02: POST /gastos/prompt Trigger Endpoint Summary

**One-liner:** Bearer-token-protected POST /gastos/prompt endpoint with constant-time auth, fail-closed empty-token guard, per-sender FOR NO KEY UPDATE row lock, send-after-commit ordering, and AWAITING_CIERRE/AWAITING_CIERRE_CONFIRM ConvState constants.

## What Was Built

### Task 1: ConvState constants + routers/prompt.py

**conversation.py change:** Two constants added to the `ConvState` class:
- `AWAITING_CIERRE = "awaiting_cierre"` (fits String(30); used by trigger endpoint and upcoming FSM handlers)
- `AWAITING_CIERRE_CONFIRM = "awaiting_cierre_confirm"` (fits String(30); used by cierre confirm handler in Plan 03)

No dispatch arms, no handler methods, no DraftCierre — all FSM logic lands in Plan 03.

**prompt.py created** with:
- `_bearer_scheme = HTTPBearer(auto_error=False)` — missing header yields `credentials=None` (not 403)
- `verify_token` dependency with three-layer check: (1) fail-closed on empty configured token, (2) credentials/scheme check, (3) `secrets.compare_digest` (constant-time, never `==`)
- `PromptRequest(phone_number: str)` and `PromptResponse(status: str, reason: str | None = None)` Pydantic models
- `PROMPT_TEXT` — Spanish message containing "efectivo" and "otra compra" substrings (required by test_prompt_text_sent)
- `trigger_prompt` handler using `db.begin_nested()` + `db.commit()` transaction pattern, pg_insert ON CONFLICT DO NOTHING ensure-row, SELECT FOR NO KEY UPDATE lock, skip non-idle, set AWAITING_CIERRE, commit, then `_safe_send` strictly outside the transaction

**Deviation (Rule 1 — Bug):** The plan specified `async with db.begin():` but this raises `InvalidRequestError: A transaction is already begun on this Session` in the test context where `db_session` is shared between the seed step (`db_session.flush()`) and the endpoint call. Changed to `async with db.begin_nested():` (SAVEPOINT) + `await db.commit()`. Semantics are equivalent in production (fresh session from `get_db`) and correct in both contexts. The plan's spec for send-after-commit ordering and row-lock behavior is preserved unchanged.

### Task 2: Mount prompt router in main.py

Added inside the existing `elif settings.agent_mode == "gastos":` block:
```python
from app.routers.prompt import router as prompt_router
app.include_router(prompt_router, tags=["gastos"])
```

Route `/gastos/prompt` is only present when AGENT_MODE=gastos. The invoice branch is unchanged.

## Verification Results

```
pytest tests/test_prompt_trigger.py -q
8 passed in 0.37s

pytest tests/test_gastos_webhook.py tests/test_conversation.py -q
32 passed in 1.96s

pytest tests/ --ignore=tests/test_conversation_cierre.py -q
161 passed, 1 skipped in 5.64s
```

Route presence confirmed:
```
AGENT_MODE=gastos DATABASE_URL=... OPENAI_API_KEY=test python -c "
from app.main import create_app; app=create_app();
assert '/gastos/prompt' in [r.path for r in app.routes]
print('mounted OK')"
# Output: mounted OK
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] begin_nested() instead of begin() for transaction handling**
- **Found during:** Task 1 — test_active_conversation_skipped failing with `InvalidRequestError: A transaction is already begun on this Session`
- **Issue:** Test fixture seeds a row via `db_session.flush()` before calling the endpoint. SQLAlchemy autobegin starts a transaction on flush. The handler then calls `async with db.begin():` on the same session — fails because a transaction is already active.
- **Fix:** Changed `async with db.begin():` to `async with db.begin_nested():` (SAVEPOINT) + `await db.commit()` after the block. Both in-transaction (test) and fresh-session (production) contexts work correctly.
- **Files modified:** backend/app/routers/prompt.py
- **Commit:** bc89bbe

## Known Stubs

None. All TRIG-01 and TRIG-02 send-half behaviors are fully implemented and tested.

`ConvState.AWAITING_CIERRE` is referenced by the endpoint and its tests; the FSM handlers that consume this state (AWAITING_CIERRE dispatch arm, `_handle_awaiting_cierre`, `_handle_cierre_confirm`) land in Plan 03. This is intentional per the wave structure.

## Threat Flags

No new threat surfaces beyond what was in the plan's threat model. All mitigations implemented:

| Threat ID | Mitigation | Status |
|-----------|-----------|--------|
| T-03-A1 | secrets.compare_digest in verify_token | Implemented — line 82 of prompt.py |
| T-03-A2 | Fail-closed: `if not configured: raise 401` before compare | Implemented — lines 72-76 |
| T-03-A3 | Token value never logged; log "auth.invalid_token" with reason only | Implemented |
| T-03-R1 | pg_insert ON CONFLICT DO NOTHING + SELECT FOR NO KEY UPDATE | Implemented — lines 153-169 |
| T-03-R2 | _safe_send after commit (line 177 vs block ending at ~170) | Implemented |
| T-03-V1 | Pydantic PromptRequest validates phone_number as str | Implemented |

## Self-Check: PASSED

- backend/app/routers/prompt.py — created, 180+ lines: FOUND
- backend/app/services/conversation.py — AWAITING_CIERRE constant: FOUND
- backend/app/services/conversation.py — AWAITING_CIERRE_CONFIRM constant: FOUND
- backend/app/main.py — prompt_router import and include_router: FOUND
- Commit ea8dfc8 (Task 1 — constants + prompt.py): FOUND
- Commit bc89bbe (Task 1 fix — begin_nested): FOUND
- Commit d8f2d3e (Task 2 — main.py mount): FOUND
- 8 test_prompt_trigger.py tests GREEN: VERIFIED
- No regressions in test_gastos_webhook.py or test_conversation.py: VERIFIED (40 passed)
- Full suite (ignoring test_conversation_cierre.py RED tests): 161 passed, 1 skipped: VERIFIED
