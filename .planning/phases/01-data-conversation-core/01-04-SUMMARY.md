---
phase: 01-data-conversation-core
plan: "04"
subsystem: backend/services
tags: [tdd, fsm, orchestrator, idempotency, row-locking, gastos-bot, conversation]
dependency_graph:
  requires:
    - 01-01 (Conversation/Gasto ORM models; CONVERSATION_TIMEOUT_HOURS config)
    - 01-02 (SlotExtractionService, GastoSlots, DraftGasto DTOs, parse_ars_amount)
    - 01-03 (GastoService.save_gasto)
  provides:
    - ConversationOrchestrator (backend/app/services/conversation.py)
    - ConvState constants (idle/awaiting_monto/awaiting_ticket/confirm)
    - AFFIRMATIVE set + is_confirmation() exact-token match
    - is_cancel() exact-token match
    - patch_draft() non-null slot merge helper
    - Full conversation test suite (backend/tests/test_conversation.py)
    - Compiled-SQL lock contract test (backend/tests/test_conversation_lock_sql.py)
  affects:
    - backend/app/services/conversation.py (new)
    - backend/tests/test_conversation.py (new)
    - backend/tests/test_conversation_lock_sql.py (new)
tech_stack:
  added: []
  patterns:
    - pg_insert(Conversation).on_conflict_do_nothing(index_elements=["sender_phone"]) — race-safe get-or-create before lock (T-04-RACE fix)
    - select(Conversation).with_for_update(key_share=True) — FOR NO KEY UPDATE row lock; compiled-SQL assertion proves mode (Task 0)
    - loaded_updated_at snapshot before any mutation — timeout ordering fix (review MEDIUM)
    - last_message_id idempotency check before any state read (Pitfall F)
    - async with session.begin() atomic commit; reply sent OUTSIDE transaction (Pitfall C)
    - is_confirmation() exact-token match — not prefix/startswith/contains (D-05)
    - patch_draft() non-null slot merge — never overwrites existing slots with null (D-07)
    - DraftGasto.model_validate_json wrapped in try/except → reset to idle on ValidationError (T-04-03)
    - failure_count in DraftGasto JSON — CONV-06 re-prompt threshold, no extra column
key_files:
  created:
    - path: backend/app/services/conversation.py
      purpose: ConversationOrchestrator — deterministic match-based FSM; wires SlotExtractionService + GastoService + WhatsAppProvider
    - path: backend/tests/test_conversation.py
      purpose: 19 tests covering CONV-01/02/03/04/06, GASTO-02/04/05/06, D-03/D-04/D-05/D-07 + idempotency-rollback + post-commit-send-failure + timeout-snapshot + exact-confirm-token
    - path: backend/tests/test_conversation_lock_sql.py
      purpose: Offline compiled-SQL assertion pinning FOR NO KEY UPDATE contract (no live DB needed)
  modified: []
decisions:
  - get-or-create via ON CONFLICT DO NOTHING before lock: closes T-04-RACE (two concurrent first messages from new sender no longer race on PK insert)
  - is_confirmation() exact-token match: strip+lower+rstrip(".!") ∈ AFFIRMATIVE — "sí" matches, "sí, pero cambiá el monto a 1500" does not
  - updated_at snapshot taken before last_message_id assignment: timeout check uses pre-mutation timestamp, not the onupdate-advanced one
  - DB failure → rollback including last_message_id: webhook is fully retryable (not silently lost)
  - Post-commit provider-send failure → at-most-once reply risk: committed DB state is NOT reversed; Phase-2 outbox is the future mitigation
  - True cross-session insert serialisation (T-04-RACE) deferred to Postgres integration test: tests/integration/test_conversation_concurrency_pg.py @pytest.mark.pg_integration (deferred to verify-phase)
metrics:
  duration: "~35 minutes"
  completed: "2026-05-27"
  tasks_completed: 3
  tasks_total: 3
  files_created: 3
  files_modified: 0
---

# Phase 01 Plan 04: ConversationOrchestrator (FSM, Lock, Idempotency, Confirm Gate) Summary

**One-liner:** ConversationOrchestrator deterministic match-based FSM with pg_insert ON CONFLICT DO NOTHING get-or-create, FOR NO KEY UPDATE row lock, pre-mutation updated_at snapshot, idempotency rollback, and exact-token confirm gate — all 20 tests green.

## What Was Built

### Task 0 — Compiled-SQL lock contract test

`backend/tests/test_conversation_lock_sql.py`: a single offline test that compiles `select(Conversation).with_for_update(key_share=True)` against `postgresql.dialect()` and asserts:
- The output contains `"FOR NO KEY UPDATE"` (correct lock mode)
- The output does NOT contain `"FOR KEY SHARE"` (guards weaker `read=True,key_share=True` regression)
- The output does NOT end with bare `"FOR UPDATE"` (guards against key_share=False regression)

Runs without a live DB — pure dialect compile. Fails loudly if a SQLAlchemy upgrade silently changes the emitted lock mode.

### Task 1 — ConversationOrchestrator scaffold (lock, idempotency, timeout, cancel)

**`backend/app/services/conversation.py`** — ConversationOrchestrator class:

**Non-negotiable entry sequence** (applied as per RESEARCH Pattern 5 + review cycle-2 HIGH fix):

1. **Ensure-row-exists (race-safe ON CONFLICT DO NOTHING):** `pg_insert(Conversation).values(sender_phone=clean_sender, state="idle").on_conflict_do_nothing(index_elements=["sender_phone"])` before the lock. Two concurrent FIRST messages from a new sender: the losing INSERT no-ops (not IntegrityError), both converge on the single row under `FOR NO KEY UPDATE`. Also valid SQLite ON CONFLICT syntax — unit-testable.

2. **Lock row:** `select(Conversation).with_for_update(key_share=True)` — compiles to `FOR NO KEY UPDATE` under postgresql dialect (verified by Task 0). SQLite ignores row locks; the unit test asserts the lock hint + compiled mode via spy.

3. **Snapshot `loaded_updated_at = conv.updated_at` BEFORE any field mutation.** All timeout logic uses this snapshot. If compared after `last_message_id = message_id`, `onupdate=func.now()` would advance `updated_at`, masking an expired conversation.

4. **Idempotency check** (before any state read): if `conv.last_message_id == message_id` → return no-op. Else: `conv.last_message_id = message_id`.

5. **Timeout check:** if `state != idle` and `now(utc) - loaded_updated_at > timedelta(hours=settings.conversation_timeout_hours)` → reset state=idle, draft=None, commit, send Spanish timeout notice OUTSIDE transaction.

6. **Global cancelar** (exact normalized token): reset state=idle, draft=None, commit, send "Registro cancelado." OUTSIDE transaction.

7. **State dispatch** (`_dispatch()`) — returns reply string.

8. `async with session.begin()` commits atomically at block exit (or rolls back on exception).

9. **Reply sent OUTSIDE transaction** (Pitfall C — no DB lock held during WhatsApp network call).

**Failure model documented in module docstring:**
- DB exception inside `session.begin()` → rollback INCLUDING `last_message_id = message_id` assignment → webhook retry sees prior ID → reprocessable.
- Post-commit `provider.send_message` failure → committed DB state is durable, reply may be lost → accepted at-most-once reply risk → Phase-2 outbox/retry is the future mitigation.

### Task 2 — State dispatch (slot fill, ticket, confirm gate, re-prompt)

**`_dispatch()`** with `match conv.state` over idle/awaiting_monto/awaiting_ticket/confirm:

- **idle:** call `slot_service.extract(text)` → `patch_draft()` (non-null slots only). Determine next missing slot in order concepto → monto → ticket (D-04). If both concepto+monto supplied → advance directly to `awaiting_ticket` (skip awaiting_monto, D-03).

- **awaiting_monto:** extract slots; fall back to `parse_ars_amount(text)` if GPT returns no monto. On success: set monto, reset `failure_count=0`, advance to `awaiting_ticket`. On failure: increment `failure_count`; on `>= 3` include concrete example ("Por ejemplo: 1500") + cancel offer (CONV-06).

- **awaiting_ticket:** `"sin ticket"` (case-insensitive) → `ticket_image_path=None`, advance to confirm, emit Spanish confirmation summary (GASTO-04).

- **confirm:** `is_confirmation(text)` (exact-token match, NO LLM) → `gasto_service.save_gasto(session, draft, conv.sender_phone)` → reset to idle (D-05). Non-affirmative: re-extract correction via `slot_service.extract(text)`, `patch_draft()`, re-confirm (D-07). GPT is NEVER invoked to decide the confirmation.

**Module-level helpers:**
- `is_confirmation(text)` — `text.strip().lower().rstrip(".!") in AFFIRMATIVE`. "sí" → True; "sí, pero cambiá el monto a 1500" → False.
- `is_cancel(text)` — same normalized match, token == "cancelar".
- `patch_draft(draft, slots)` — apply non-null only; `monto` → `Decimal(str(slots.monto))`.
- `_load_draft(conv)` — `DraftGasto.model_validate_json` with try/except → fresh draft on error (T-04-03 mitigation).
- `_save_draft(conv, draft)` — reassigns `conv.draft_gasto = draft.model_dump_json()` (string reassignment, not in-place mutation → onupdate fires, Pitfall E).

## TDD Gate Compliance

| Gate | Commit | Status |
|------|--------|--------|
| RED (test(01-04)) | 77c66e2 | PASS — all tests failed with ModuleNotFoundError |
| GREEN (feat(01-04)) | 2b4551e | PASS — 19 tests pass, full suite 133 passed |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Tests seeding Conversation rows with flush() then calling orchestrator session.begin() raised "A transaction is already begun on this Session"**

- **Found during:** Task 1 GREEN phase — first test run after implementation
- **Issue:** The test fixture's `db_session` uses SQLAlchemy autobegin. Seeds that call `db_session.add()` + `db_session.flush()` start an implicit transaction. The orchestrator then calls `async with session.begin()` on the already-begun session, which SQLAlchemy rejects.
- **Fix:** Changed all test seed patterns from `await db_session.flush()` to `await db_session.commit()` — matching the existing pattern in `test_invoice_service.py`. This is the correct pattern: commit the seed data so the orchestrator can start its own transaction.
- **Files modified:** `backend/tests/test_conversation.py`
- **Commit:** 2b4551e (fixed inline in GREEN commit)

No other deviations — implementation proceeded exactly as planned.

## Test Results

```
20 passed  (tests/test_conversation_lock_sql.py + tests/test_conversation.py)
133 passed, 1 skipped  (full suite — baseline was 113 passed, 1 skipped)
```

New tests added:
- `test_with_for_update_key_share_emits_for_no_key_update` (Task 0, offline compile)
- `test_row_lock_issued` (CONV-03 — spy + compiled SQL mode proof)
- `test_get_or_create_first_message` (T-04-RACE — ON CONFLICT DO NOTHING convergence)
- `test_idempotency` (CONV-02)
- `test_idempotency_rollback_on_db_failure` (review concern 4 — rollback of last_message_id)
- `test_provider_send_failure_after_commit` (at-most-once reply risk)
- `test_timeout_reset` (CONV-04)
- `test_timeout_uses_preload_snapshot` (review MEDIUM — pre-mutation snapshot)
- `test_cancelar` (GASTO-06)
- `test_cancelar_from_confirm` (GASTO-06 at confirm state)
- `test_full_flow_awaiting_monto` (GASTO-02)
- `test_full_flow_both_slots_skip_awaiting_monto` (D-03)
- `test_state_persists` (CONV-01)
- `test_sin_ticket` (GASTO-04)
- `test_confirm_saves_gasto` (GASTO-05, D-05)
- `test_confirm_requires_exact_token` (D-05/D-07 — "sí, pero cambiá el monto")
- `test_confirm_si_no_tiene_ticket_is_correction` (D-05 exact-token)
- `test_reprompt_counter` (CONV-06)
- `test_reprompt_counter_resets_on_success` (CONV-06)
- `test_reply_sent_after_commit` (Pitfall C)

## Known Stubs

None — `ConversationOrchestrator` is fully wired to `SlotExtractionService`, `GastoService`, and `WhatsAppProvider`. All tests use mocked collaborators with AsyncMock; production wiring is Phase 2 (webhook registration).

The `awaiting_ticket` state currently treats any non-"sin ticket" text the same as "sin ticket" (advances to confirm with `ticket_image_path=None`). This is correct per the plan: "Phase 1 accepts only the 'sin ticket' text path." Actual photo capture is Phase 2.

## Deferred Items

- **T-04-RACE Postgres integration test:** `tests/integration/test_conversation_concurrency_pg.py` with `@pytest.mark.pg_integration` — two concurrent first messages from one brand-new sender against a live Postgres should produce exactly one conversations row and one serialized turn. Deferred to verify-phase. The ON CONFLICT DO NOTHING path is unit-tested for error-free convergence on one row (SQLite).
- **Phase-2 outbox/retry:** post-commit `provider.send_message` failure is the accepted at-most-once reply risk. Documented in module docstring.

## Threat Flags

None — no new network endpoints, no new auth paths, no new file access patterns, no schema changes.

**T-04-01 (duplicate webhook):** mitigated — `last_message_id` idempotency check step 4, before any state read.
**T-04-02 (concurrent messages, existing row):** mitigated — `with_for_update(key_share=True)` → FOR NO KEY UPDATE; compiled-SQL assertion (Task 0) + spy assertion (test_row_lock_issued) prove the mode.
**T-04-RACE (concurrent first messages, new sender):** mitigated at get-or-create level — ON CONFLICT DO NOTHING materializes the row race-safely; cross-session proof deferred to Postgres integration test.
**T-04-03 (malformed draft JSON):** mitigated — `DraftGasto.model_validate_json` wrapped in try/except in `_load_draft()` → reset to fresh draft on ValidationError.
**T-04-04 (stale state replay):** mitigated — `updated_at` timeout reset; `last_message_id` DB-backed idempotency.
**T-04-05 (LLM-driven write):** mitigated — `is_confirmation()` is pure deterministic string match; `save_gasto` reachable only through this gate; `slot_service.extract` is NOT called on the affirmative path (asserted by `test_confirm_saves_gasto`).

## Self-Check: PASSED

| Item | Status |
|------|--------|
| backend/app/services/conversation.py | FOUND |
| backend/tests/test_conversation.py | FOUND |
| backend/tests/test_conversation_lock_sql.py | FOUND |
| .planning/phases/01-data-conversation-core/01-04-SUMMARY.md | FOUND |
| Commit 32acc3a (Task 0 lock SQL test) | FOUND |
| Commit 77c66e2 (RED test_conversation) | FOUND |
| Commit 2b4551e (GREEN ConversationOrchestrator) | FOUND |
| 20 tests pass (test_conversation_lock_sql + test_conversation) | PASSED |
| Full suite 133 passed 1 skipped | PASSED |
| on_conflict_do_nothing before with_for_update in conversation.py | PASSED |
| is_confirmation exact-token match (no startswith/contains) | PASSED |
| slot_service.extract NOT called on affirmative confirm path | PASSED |
| reply sent OUTSIDE session.begin() block | PASSED |
