---
phase: 01-data-conversation-core
verified: 2026-05-27T00:00:00Z
status: passed
score: 6/6 must-haves verified
overrides_applied: 0
deferred:
  - truth: "Two concurrent FIRST messages from a brand-new sender are serialized by SELECT ... FOR NO KEY UPDATE at the cross-session Postgres level"
    addressed_in: "verify-phase (Postgres integration test)"
    evidence: "VALIDATION.md documents tests/integration/test_conversation_concurrency_pg.py @pytest.mark.pg_integration as deferred; unit test test_get_or_create_first_message covers error-free convergence on SQLite; compiled-SQL contract test proves the lock mode is correct"
---

# Phase 1: Data + Conversation Core — Verification Report

**Phase Goal:** The conversation engine, data models, and gasto persistence layer exist and are fully unit-tested — no WhatsApp connection required
**Verified:** 2026-05-27
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A unit test can drive the ConversationOrchestrator through every state transition (idle → awaiting_monto → awaiting_ticket → confirm → idle) using a mocked provider and mocked slot extractor — all transitions pass without touching WhatsApp or the network | VERIFIED | 19 tests in test_conversation.py cover every transition; test_full_flow_awaiting_monto, test_full_flow_both_slots_skip_awaiting_monto, test_sin_ticket, test_confirm_saves_gasto all pass |
| 2 | A duplicate webhook message ID (matching Conversation.last_message_id) causes the orchestrator to exit without advancing state or writing any record | VERIFIED | test_idempotency passes; also test_idempotency_rollback_on_db_failure proves last_message_id reverts on DB-side failure |
| 3 | Two concurrent orchestrator calls for the same sender are serialized by SELECT ... FOR NO KEY UPDATE; neither call reads stale state or produces a duplicate DB write | VERIFIED (unit) / DEFERRED (cross-session) | test_row_lock_issued captures the SELECT and compiles against postgresql.dialect() asserting "FOR NO KEY UPDATE"; test_conversation_lock_sql.py pins the SQLAlchemy key_share=True → FOR NO KEY UPDATE contract offline; test_get_or_create_first_message proves ON CONFLICT DO NOTHING closes the new-sender race on SQLite; true cross-session proof is the documented deferred Postgres integration test |
| 4 | A conversation row older than CONVERSATION_TIMEOUT_HOURS auto-resets to idle on the next inbound message, and the manager receives a Spanish-language timeout notice | VERIFIED | test_timeout_reset and test_timeout_uses_preload_snapshot both pass; Spanish timeout notice verified in test_timeout_reset |
| 5 | Argentine number strings "1.500" and "1.234,56" are parsed to Decimal("1500") and Decimal("1234.56") respectively by parse_ars_amount() — Python's Decimal("1.500") trap documented and blocked | VERIFIED | test_parse_ars_amount_dot_thousands_sep and test_parse_ars_amount_dot_thousands_comma_decimal pass; trap documented in amounts.py docstring and ARS_PATTERN regex blocks the naive path |
| 6 | An unparseable reply re-prompts the current step; after 3 consecutive failures the bot sends a concrete example and offers to cancel — GPT is never invoked on the confirmation step (deterministic string match only) | VERIFIED | test_reprompt_counter passes (failure_count reaches 3, last reply contains "ejemplo"/"cancelar"); test_confirm_saves_gasto asserts slot_service.extract NOT called on affirmative; test_confirm_requires_exact_token and test_confirm_si_no_tiene_ticket_is_correction both pass |

**Score:** 6/6 truths verified (criterion 3 has one deferred component; see Deferred Items below)

---

### Deferred Items

Items not yet fully met but explicitly addressed in later milestone phases or in the verify-phase Postgres integration test.

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | True cross-session insert serialization: two concurrent FIRST messages from a brand-new sender on a live Postgres produce exactly one conversations row and one serialized turn | verify-phase (Postgres integration test) | VALIDATION.md deferred row: tests/integration/test_conversation_concurrency_pg.py @pytest.mark.pg_integration; SQLite unit tests prove error-free convergence; compiled-SQL test proves lock mode correctness |

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/db/models.py` | Gasto, Conversation, CajaCierre ORM models | VERIFIED | All three classes present; Conversation has sender_phone PK, state, draft_gasto, last_message_id, updated_at with onupdate; Gasto has D-01 minimal field set (no lugar/proveedor/entrada/category); CajaCierre has fecha, hora_cierre, efectivo_en_caja |
| `backend/alembic/versions/c3d4e5f6a7b8_add_gastos_tables.py` | Single migration creating all three tables, down_revision b1c2d3e4f5a6 | VERIFIED | down_revision = 'b1c2d3e4f5a6'; Alembic head is single (c3d4e5f6a7b8); upgrade() creates conversations/gastos/caja_cierres + 4 indexes; downgrade() drops in reverse; RLS deferred comment present; no ENABLE ROW LEVEL SECURITY statement |
| `backend/app/config.py` | agent_mode + conversation_timeout_hours settings | VERIFIED | agent_mode: str = "gastos"; conversation_timeout_hours: int = 4; both in optional-with-defaults block |
| `backend/app/main.py` | Invoice webhook registered only when agent_mode == "invoice" | VERIFIED | if settings.agent_mode == "invoice": block wraps whatsapp_router include; gastos Phase 2 seam comment present |
| `backend/app/models/conversation.py` | GastoSlots + DraftGasto all-Optional DTOs | VERIFIED | GastoSlots.monto Optional[float]; DraftGasto.monto Optional[Decimal]; failure_count int=0; no lugar/proveedor/entrada/category; ConfigDict(use_enum_values=True) |
| `backend/app/services/amounts.py` | parse_ars_amount() pure utility | VERIFIED | Module-level pure function; ARS regex validates format before stripping separators; Decimal("1.500") trap documented; no locale module; returns None on all bad input |
| `backend/app/services/slot_extraction.py` | SlotExtractionService using gpt-4o-mini .parse() | VERIFIED | model="gpt-4o-mini"; response_format=GastoSlots; refusal checked before parsed; SlotExtractionError hierarchy; structlog with text preview |
| `backend/app/services/gasto.py` | GastoService persistence (mirrors InvoiceService) | VERIFIED | Stateless; save_gasto uses removeprefix("whatsapp:"); session.flush() (no session.commit()); fecha=date.today() |
| `backend/app/services/conversation.py` | ConversationOrchestrator deterministic match-based FSM | VERIFIED | ON CONFLICT DO NOTHING at line 195 before with_for_update at line 206; loaded_updated_at snapshot taken before any field mutation; is_confirmation() exact-token match; patch_draft() non-null only; reply sent outside session.begin() block; failure model documented in module docstring |
| `backend/tests/test_conversation.py` | Full FSM test suite (19 tests) | VERIFIED | 19 tests covering CONV-01/02/03/04/06, GASTO-02/04/05/06, all pass |
| `backend/tests/test_conversation_lock_sql.py` | Offline compiled-SQL lock contract | VERIFIED | Asserts "FOR NO KEY UPDATE" present, "FOR KEY SHARE" absent, bare "FOR UPDATE" absent at end |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `backend/app/main.py` | `settings.agent_mode` | conditional router registration | VERIFIED | `if settings.agent_mode == "invoice":` at line 57; invoice router only registers in invoice mode |
| `backend/app/services/conversation.py` | Conversation row | `pg_insert(Conversation).on_conflict_do_nothing(index_elements=["sender_phone"])` BEFORE `with_for_update(key_share=True)` | VERIFIED | on_conflict_do_nothing at line 195; with_for_update at line 206; correct ordering confirmed |
| `backend/app/services/conversation.py` | `GastoService.save_gasto` | called only at confirm + affirmative match | VERIFIED | `_handle_confirm` calls save_gasto only inside `if is_confirmation(text):` branch; test_confirm_saves_gasto asserts slot_service.extract NOT called on affirmative |
| `backend/app/services/slot_extraction.py` | `GastoSlots` | `response_format=GastoSlots` in client.chat.completions.parse() | VERIFIED | response_format=GastoSlots at line 113; test_extract_calls_parse_with_gpt4o_mini_and_gasto_slots_format asserts this |

---

### Data-Flow Trace (Level 4)

Not applicable — Phase 1 delivers unit-testable server-side logic (FSM, services, DTOs). No page or component rendering dynamic data from a live API. All data flows are verified through direct unit tests against aiosqlite.

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| parse_ars_amount("1.500") == Decimal("1500") | pytest tests/test_amounts.py::test_parse_ars_amount_dot_thousands_sep | PASSED | PASS |
| parse_ars_amount("1.234,56") == Decimal("1234.56") | pytest tests/test_amounts.py::test_parse_ars_amount_dot_thousands_comma_decimal | PASSED | PASS |
| Full conversation suite (19 tests) | pytest tests/test_conversation.py | 19 passed | PASS |
| Compiled-SQL lock contract | pytest tests/test_conversation_lock_sql.py | 1 passed | PASS |
| Full backend suite | python -m pytest -q | 133 passed, 1 skipped | PASS |

---

### Probe Execution

No probe scripts declared for this phase (no scripts/tests/probe-*.sh discovered). Phase 1 is a pure unit-test phase — no running server required.

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| CONV-01 | 01-01 | Conversation state persisted per sender, survives restarts | SATISFIED | Conversation ORM with sender_phone PK; test_conversation_round_trip + test_state_persists pass |
| CONV-02 | 01-04 | Duplicate webhook IDs do not advance state or create duplicates | SATISFIED | test_idempotency + test_idempotency_rollback_on_db_failure pass |
| CONV-03 | 01-04 | Concurrent messages serialized by row lock | SATISFIED (unit) | test_row_lock_issued + test_conversation_lock_sql.py + test_get_or_create_first_message pass; cross-session proof deferred |
| CONV-04 | 01-04 | Stale conversation auto-resets to idle after timeout | SATISFIED | test_timeout_reset + test_timeout_uses_preload_snapshot pass |
| CONV-05 | 01-02 | Argentine number formats parsed correctly | SATISFIED | All 11 test_amounts tests pass including the two ROADMAP criterion-5 exact assertions |
| CONV-06 | 01-04 | Unparseable replies re-prompt; 3 failures → example + cancel | SATISFIED | test_reprompt_counter + test_reprompt_counter_resets_on_success pass |
| GASTO-01 | 01-02 | Free-form Spanish intent → structured slots | SATISFIED | test_extract_returns_parsed_slots_on_success passes; mocked gpt-4o-mini .parse() pattern verified |
| GASTO-02 | 01-04 | Bot collects missing fields via follow-up questions | SATISFIED | test_full_flow_awaiting_monto + test_full_flow_both_slots_skip_awaiting_monto pass |
| GASTO-04 | 01-04 | Manager can skip ticket ("sin ticket") and still save | SATISFIED | test_sin_ticket passes; ticket_image_path=None on DraftGasto preserved through save |
| GASTO-05 | 01-03 + 01-04 | Summary + explicit confirmation before writing gasto | SATISFIED | test_confirm_saves_gasto passes; save_gasto only reachable through is_confirmation() exact-token gate |
| GASTO-06 | 01-04 | Manager can correct a field or cancel before save | SATISFIED | test_cancelar + test_cancelar_from_confirm + test_confirm_requires_exact_token + test_confirm_si_no_tiene_ticket_is_correction all pass |

All 11 Phase 1 requirements satisfied. GASTO-03, CAJA-01, CAJA-02, TRIG-01, TRIG-02, UI-01, UI-02 are correctly assigned to later phases.

---

### Anti-Patterns Found

No blockers found.

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `backend/app/services/conversation.py` | 360-376 | Duplicated `conv.state = ConvState.AWAITING_MONTO` assignment (set once at 360, overwritten at 375 in the "concepto missing" branch) | INFO | Dead first assignment; no behavioral impact — second assignment is correct. Not a stub, not a debt marker. |

No TBD/FIXME/XXX markers found in any phase-modified source files. No unresolved debt markers.

The `awaiting_ticket` state advances to `confirm` for ANY non-"sin ticket" text (not just "sin ticket"). This is correct per the plan: "Phase 1 accepts only the 'sin ticket' text path — actual photo capture is Phase 2." Documented in the SUMMARY.md Known Stubs section as intentional scope deferral, not a bug.

---

### Human Verification Required

None. Phase 1 is declared fully unit-testable with no WhatsApp or network connection (VALIDATION.md Manual-Only Verifications: "none expected"). All 6 ROADMAP success criteria have automated test coverage confirming them.

---

## Gaps Summary

No gaps. All 6 ROADMAP success criteria are verified against actual codebase evidence. The one deferred item (cross-session Postgres concurrency proof) is explicitly planned and documented in VALIDATION.md as a Postgres integration test artifact; it does not block the Phase 1 goal, which is unit-testability.

---

_Verified: 2026-05-27_
_Verifier: Claude (gsd-verifier)_
