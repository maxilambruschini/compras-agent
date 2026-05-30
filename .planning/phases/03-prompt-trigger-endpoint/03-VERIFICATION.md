---
phase: 03-prompt-trigger-endpoint
verified: 2026-05-30T11:45:00-03:00
status: human_needed
score: 7/8 must-haves verified (1 requires live Twilio sandbox — human item)
overrides_applied: 0
human_verification:
  - test: "POST /gastos/prompt with a valid bearer token against the live Twilio sandbox — send to a real WhatsApp number"
    expected: "Manager receives the WhatsApp message containing 'efectivo', 'otra compra', and the three asks. HTTP 200 {\"status\":\"sent\"} returned to caller."
    why_human: "No live Twilio credentials or open customer-service window in CI. The code path is fully verified by tests; only the end-to-end delivery over the Twilio network requires human execution."
---

# Phase 3: Prompt Trigger Endpoint Verification Report

**Phase Goal:** A caller can POST to a protected endpoint with a manager's phone number and that manager immediately receives the prompt message on WhatsApp — the conversation engine then handles all follow-up replies via the existing Phase 2 webhook router, including recording the cash-on-hand caja closing.
**Verified:** 2026-05-30T11:45:00-03:00
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | POST /gastos/prompt with valid bearer token + phone returns 200 and sends the prompt via WhatsApp provider | ✓ VERIFIED | test_valid_token_sends passes; prompt.py lines 137-204; PROMPT_TEXT sent via _safe_send after commit |
| 2 | POST /gastos/prompt with missing or invalid token returns 401, no message sent | ✓ VERIFIED | test_missing_token_401, test_wrong_token_401, test_empty_configured_token_denies all pass; verify_token uses secrets.compare_digest, fail-closed on empty token |
| 3 | GASTOS_PROMPT_TOKEN="" causes every request to return 401 (fail-closed) | ✓ VERIFIED | verify_token checks `if not configured` before compare_digest; test_empty_configured_token_denies covers both non-empty and empty credential edge cases |
| 4 | Non-idle recipient yields 200 {"status":"skipped","reason":"active_conversation"}, no send, state unchanged | ✓ VERIFIED | test_active_conversation_skipped passes; prompt.py lines 185-187; state re-read after refresh matches original |
| 5 | Successful send sets AWAITING_CIERRE under FOR NO KEY UPDATE row lock; send happens after DB commit | ✓ VERIFIED | test_state_set_to_awaiting_cierre and test_row_lock_issued pass; prompt.py uses begin_nested() + db.commit() before _safe_send; with_for_update(key_share=True) compiles to FOR NO KEY UPDATE |
| 6 | Manager reply in AWAITING_CIERRE/AWAITING_CIERRE_CONFIRM routes through existing orchestrator FSM into cierre or gasto flow | ✓ VERIFIED | conversation.py dispatch arms at lines 355-359; _handle_awaiting_cierre and _handle_cierre_confirm implemented; all cierre FSM tests pass |
| 7 | CajaCierre row written with hora_cierre auto-derived in ART (12:00/17:00) and fecha as ART date | ✓ VERIFIED | test_hora_cierre_morning, test_hora_cierre_afternoon, test_fecha_art_not_utc, test_duplicate_cierres_allowed all pass; cierre.py _derive_hora_cierre/_today_art use ZoneInfo("America/Argentina/Buenos_Aires"); no float() conversion |
| 8 | Live Twilio sandbox end-to-end: manager actually receives the WhatsApp message | ? HUMAN NEEDED | Cannot verify without live Twilio credentials and open 24h CS window — code path confirmed by all automated tests |

**Score:** 7/8 truths verified (1 human item)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/routers/prompt.py` | POST /gastos/prompt + verify_token + PROMPT_TEXT (min 60 lines) | ✓ VERIFIED | 205 lines; verify_token with compare_digest, fail-closed; PROMPT_TEXT contains "efectivo" and "otra compra"; router defined |
| `backend/app/main.py` | prompt_router mounted under agent_mode=='gastos' | ✓ VERIFIED | Lines 65+68: `from app.routers.prompt import router as prompt_router`; `app.include_router(prompt_router, tags=["gastos"])`; confirmed absent under invoice mode |
| `backend/app/services/conversation.py` | AWAITING_CIERRE + AWAITING_CIERRE_CONFIRM constants + FSM dispatch arms + _handle_awaiting_cierre + _handle_cierre_confirm + DraftCierre | ✓ VERIFIED | Constants at lines 91-92; dispatch arms lines 355-359; handlers lines 586-699; DraftCierre in app/models/conversation.py (re-exported via conversation.py import) |
| `backend/app/services/cierre.py` | CajaCierreService.save_cierre fully implemented (Decimal-safe, ART time, flush) | ✓ VERIFIED | Lines 80-120; no float(); session.add + await session.flush(); _derive_hora_cierre/_today_art implemented with ZoneInfo |
| `backend/app/config.py` | gastos_prompt_token field with empty-string default | ✓ VERIFIED | Line 51: `gastos_prompt_token: str = ""`; comment documents fail-closed enforcement |
| `backend/tests/test_prompt_trigger.py` | 8 canonical test IDs for TRIG-01/TRIG-02 | ✓ VERIFIED | All 8 collected and pass: test_valid_token_sends, test_missing_token_401, test_wrong_token_401, test_empty_configured_token_denies, test_active_conversation_skipped, test_state_set_to_awaiting_cierre, test_prompt_text_sent, test_row_lock_issued |
| `backend/tests/test_conversation_cierre.py` | 8 canonical test IDs for CAJA-01/CAJA-02 (plan spec) + 2 additional CR-01 tests | ✓ VERIFIED | 10 tests collected and pass; includes all required: test_bare_amount_advances_to_confirm, test_gasto_intent_handoff, test_confirm_saves_cierre, test_confirm_requires_exact_token, test_hora_cierre_morning, test_hora_cierre_afternoon, test_fecha_art_not_utc, test_duplicate_cierres_allowed |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `prompt.py` | `settings.gastos_prompt_token` | `secrets.compare_digest` constant-time + fail-closed on empty | ✓ WIRED | Line 84: `secrets.compare_digest(credentials.credentials, configured)`; line 71: `if not configured` guard before compare |
| `prompt.py` | `Conversation row` | `pg_insert ON CONFLICT DO NOTHING` + `select.with_for_update(key_share=True)` | ✓ WIRED | Lines 169-181; begin_nested() owns the lock; test_row_lock_issued confirms FOR NO KEY UPDATE in compiled SQL |
| `main.py` | `app.routers.prompt.router` | `include_router` under `agent_mode=='gastos'` | ✓ WIRED | Lines 65+68; route present in create_app() output; absent under invoice mode |
| `conversation.py` | `parse_ars_amount` | `_handle_awaiting_cierre` tries parse BEFORE GPT slot extraction | ✓ WIRED | Lines 605-617; parse_ars_amount called first, slot_service.extract only on None result |
| `conversation.py` | `CajaCierreService.save_cierre` | `_handle_cierre_confirm` after `is_confirmation(text)` gate | ✓ WIRED | Line 681: `await CajaCierreService().save_cierre(session, cierre_draft.cierre_monto, conv.sender_phone)`; GPT never invoked at gate |
| `cierre.py` | `CajaCierre row` | `session.add + session.flush` (caller owns commit) | ✓ WIRED | Lines 111-112; no session.commit in cierre.py; flush populates id |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|--------------------|--------|
| `cierre.py save_cierre` | `efectivo_en_caja` | `parse_ars_amount(text)` via orchestrator | Yes — Decimal from real text parse, stored as Numeric(14,2) | ✓ FLOWING |
| `cierre.py save_cierre` | `hora_cierre` | `_derive_hora_cierre()` using `datetime.now(ZoneInfo("America/Argentina/Buenos_Aires"))` | Yes — real ART clock | ✓ FLOWING |
| `cierre.py save_cierre` | `fecha` | `_today_art()` using `datetime.now(_ART).date()` | Yes — ART date, not UTC | ✓ FLOWING |
| `prompt.py trigger_prompt` | `conv.state` | DB select + in-handler mutation to AWAITING_CIERRE | Yes — persisted to Conversation row | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Phase 3 test suite (18 tests) | `pytest tests/test_prompt_trigger.py tests/test_conversation_cierre.py -q` | 18 passed, 0 failed | ✓ PASS |
| Full test suite (no regressions) | `pytest tests/ -q` | 171 passed, 1 skipped | ✓ PASS |
| /gastos/prompt mounted under gastos mode | `create_app()` route table check | route present | ✓ PASS |
| /gastos/prompt absent under invoice mode | `create_app()` with AGENT_MODE=invoice | route absent | ✓ PASS |
| PROMPT_TEXT substrings | Python assert "efectivo" and "otra compra" in PROMPT_TEXT.lower() | both present | ✓ PASS |
| ConvState constants | Python assert AWAITING_CIERRE=="awaiting_cierre", AWAITING_CIERRE_CONFIRM=="awaiting_cierre_confirm" | both correct | ✓ PASS |
| No float() in cierre.py | grep -c "float(" backend/app/services/cierre.py | 0 | ✓ PASS |
| session.flush (not commit) in cierre.py | grep "session.flush\|session.commit" | only flush found | ✓ PASS |
| secrets.compare_digest (not ==) | grep compare_digest prompt.py | found at line 84 | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| TRIG-01 | 03-01, 03-02 | Protected endpoint sends prompt message to manager via WhatsApp | ✓ SATISFIED | prompt.py POST /gastos/prompt; verify_token with fail-closed auth; 8 prompt tests green |
| TRIG-02 | 03-01, 03-02, 03-03 | Triggered prompt asks for pending payments, cash-on-hand, "¿hiciste otra compra hoy?"; branches into capture/caja-closing flow | ✓ SATISFIED | PROMPT_TEXT contains all three asks; FSM AWAITING_CIERRE dispatch handles reply routing |
| CAJA-01 | 03-01, 03-03 | Manager reports cash-on-hand for twice-daily closing | ✓ SATISFIED | _handle_awaiting_cierre + _handle_cierre_confirm + CajaCierreService.save_cierre; confirm gate is deterministic (no GPT); test_confirm_saves_cierre green |
| CAJA-02 | 03-01, 03-03 | Each closing recorded with date and which closing (12:00/17:00) it corresponds to | ✓ SATISFIED | _derive_hora_cierre() returns "12:00"/"17:00" based on ART time; _today_art() uses ZoneInfo; test_hora_cierre_morning, test_hora_cierre_afternoon, test_fecha_art_not_utc, test_duplicate_cierres_allowed all green |

All 4 required requirement IDs (TRIG-01, TRIG-02, CAJA-01, CAJA-02) are satisfied. REQUIREMENTS.md traceability table marks all four as Complete for Phase 3.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None found | — | — | — | — |

No TBD, FIXME, XXX, or unresolved debt markers found in any Phase 3 modified file. No stub patterns (return null/return []) found in production paths. No hardcoded empty data flowing to render paths.

### Human Verification Required

#### 1. Live Twilio Sandbox End-to-End Send

**Test:** With a running backend (real DATABASE_URL + TWILIO_* credentials), call `POST /gastos/prompt` with a valid GASTOS_PROMPT_TOKEN and a manager's WhatsApp number that has recently messaged the bot (to have an open 24h CS window).

**Expected:** HTTP 200 `{"status":"sent"}` returned; the target WhatsApp number receives a message containing:
- "efectivo" (cash-on-hand mention)
- "otra compra" (purchase nudge)
- Three asks: pending payments, efectivo amount, otra compra hoy

The manager can then reply with a bare amount (e.g. "1500") and the existing webhook router handles the cierre confirmation flow through to a CajaCierre row in the database.

**Why human:** No live Twilio credentials or active 24h customer-service window available in CI. The code path (auth, state set, PROMPT_TEXT content, whatsapp: prefix on send, FSM reply handling) is fully verified by 18 automated tests. Only the actual Twilio network delivery and WhatsApp UI rendering require human execution.

---

## Gaps Summary

No automatable gaps found. All automated success criteria pass. The single outstanding item is the live Twilio sandbox round-trip, which is classified as a human verification item per the verification instructions (no live Twilio in CI).

**TRIG-01 (auth, skip, state, lock):** Fully verified by 8 passing unit tests.
**TRIG-02 (prompt text, FSM branching):** PROMPT_TEXT contains all required substrings; FSM AWAITING_CIERRE dispatch and save_cierre wiring verified by 10 passing tests.
**CAJA-01 (caja closing record):** CajaCierre row written after deterministic is_confirmation() gate; GPT never invoked at the write boundary — verified by tests.
**CAJA-02 (hora_cierre, fecha in ART):** _derive_hora_cierre() and _today_art() tested with clock patches at boundary conditions (11:00 ART, 14:30 ART boundary, 23:00 ART vs 02:00 UTC cross-day); no float() conversion in Decimal path.

---

_Verified: 2026-05-30T11:45:00-03:00_
_Verifier: Claude (gsd-verifier)_
