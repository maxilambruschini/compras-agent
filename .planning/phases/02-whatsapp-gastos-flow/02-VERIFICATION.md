---
phase: 02-whatsapp-gastos-flow
verified: 2026-05-27T23:22:00-03:00
status: human_needed
score: 10/10 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Send 'Pago de queso en supermercado' from an allowlisted Twilio sandbox number"
    expected: "Bot replies asking for ticket photo or 'sin ticket'; after replying 'sí' at confirm, a gasto row exists in the DB with correct concepto, monto, and ticket_image_path"
    why_human: "End-to-end Twilio sandbox flow — requires live credentials, a running server, and a real WhatsApp session; cannot be grepped or unit-tested"
  - test: "Send a ticket photo from the allowlisted number when state is awaiting_ticket"
    expected: "Image is stored under storage_path, linked on the gasto row; vision-read monto appears in the confirm summary; replying 'sí' writes the gasto with ticket_image_path set"
    why_human: "Requires real image bytes, live GPT-4o vision call, and DB inspection post-confirm"
  - test: "Send a replayed MessageSid (identical Twilio MessageSid) to /gastos/webhook"
    expected: "HTTP 200 returned; no second DB state advance; DB last_message_id unchanged from first delivery"
    why_human: "Twilio sandbox replay is the stated verification method in ROADMAP SC-4; unit test covers in-memory fast-path but the DB last_message_id source-of-truth path needs live exercise"
---

# Phase 2: WhatsApp Gastos Flow — Verification Report

**Phase Goal:** An allowlisted manager can send a free-form Spanish expense intent on WhatsApp and the bot drives the full multi-turn capture — intent → ticket photo (amount read by GPT vision) or "sin ticket" (amount asked) → confirmation → saved gasto record — end-to-end via Twilio
**Verified:** 2026-05-27T23:22:00-03:00
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | After concepto is known, bot asks for ticket photo BEFORE asking for amount (D-01) | VERIFIED | `conversation.py:402-409` — `conv.state = ConvState.AWAITING_TICKET` + reply asks for photo when `draft.concepto` is set; `_handle_idle` never routes to AWAITING_MONTO when concepto is present |
| 2 | A ticket photo's amount is read by GPT-4o vision and becomes the gasto monto (D-02) | VERIFIED | `ticket_vision.py:114-132` — `chat.completions.parse(response_format=TicketAmount)` with `gpt-4o-2024-08-06`; `gastos.py:262` — `ticket_amount = await vision.extract_amount(image_bytes)` fed into orchestrator |
| 3 | Replying 'sin ticket' skips storage and routes to awaiting_monto where bot asks for amount (D-01, GASTO-04) | VERIFIED | `conversation.py:491-495` — `text.strip().lower() == "sin ticket"` → `ticket_image_path = None`, `conv.state = AWAITING_MONTO`; no storage call in this branch |
| 4 | When vision cannot read amount, bot falls back to asking manager to type it (D-01b) | VERIFIED | `conversation.py:506-513` — branch (c): `ticket_image_path is not None and ticket_amount is None` → stores path, sets `AWAITING_MONTO`, asks manager to type amount |
| 5 | Off-topic idle message yields fixed Spanish deflection reply and leaves state at idle (D-04) | VERIFIED | `conversation.py:387-390` — `slots.concepto is None and slots.monto is None` → `return DEFLECTION_REPLY` without state change or draft save; constant defined at line 108 |
| 6 | Confirm summary shows resolved amount so manager can correct it freeform (D-01a) | VERIFIED | `conversation.py:550-561` — `_confirm_summary` builds bullet list with `draft.monto`; branch (b) at line 498 sets `draft.monto = ticket_amount` before calling `_confirm_summary` |
| 7 | Allowlisted sender's intent triggers fast-200 and orchestrator dispatch; gasto saves after confirm (SC-1) | VERIFIED | `gastos.py:351-366` — `asyncio.create_task(process_gasto_message(...))` then `return Response(status_code=200)` immediately; orchestrator save via `GastoService.save_gasto` in `conversation.py:537` |
| 8 | Non-allowlisted sender gets Spanish rejection and no DB record (SC-3) | VERIFIED | `gastos.py:340-344` — `scalar_one_or_none() is None` → `send_message(NON_ALLOWLISTED_REPLY)` + `return Response(200)` with no orchestrator call |
| 9 | Replayed webhook (identical MessageSid) does not advance state or create duplicate (SC-4) | VERIFIED | `gastos.py:325-328` — `_processed_message_sids` in-memory fast-path; orchestrator `last_message_id` DB gate at `conversation.py:238-240` is source of truth |
| 10 | /gastos/webhook returns HTTP 200 before any DB or GPT work begins (SC-5) | VERIFIED | `gastos.py:352-366` — `asyncio.create_task` schedules background work, `Response(status_code=200)` returned immediately; no `await` of the task before return |

**Score:** 10/10 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/services/ticket_vision.py` | Amount-only GPT-4o vision extractor | VERIFIED | 157 lines; `TicketAmount(monto: Optional[float])` + `TicketVisionService.extract_amount`; `response_format=TicketAmount` at line 132; `Decimal(str(...))` at line 154 |
| `backend/app/services/conversation.py` | Ticket-first FSM with media entry | VERIFIED | `ticket_amount` in `handle_message` signature (line 178), `_dispatch` (line 304), `_handle_awaiting_ticket` (line 474); `DEFLECTION_REPLY` at line 108; `AWAITING_TICKET` at line 88 |
| `backend/app/routers/gastos.py` | Twilio webhook router with fast-200 | VERIFIED | `/gastos/webhook` POST handler; `process_gasto_message` background fn; `_validate_image_bytes`, `extract_amount`, `handle_message` all present and wired |
| `backend/app/main.py` | AGENT_MODE=='gastos' router mount | VERIFIED | Real (uncommented) `elif settings.agent_mode == "gastos":` branch at line 62; `include_router(gastos_router, prefix="/gastos")` at line 66 |
| `backend/tests/test_ticket_vision.py` | 7 tests for vision service | VERIFIED | 7 test functions covering success, decimal precision, unreadable (None), refusal, refusal+None-parsed, transport error, no-key-logged |
| `backend/tests/test_conversation.py` | FSM tests including ticket-first behaviors | VERIFIED | 24 test functions; includes `test_idle_concepto_known_advances_to_awaiting_ticket`, `test_idle_off_topic_deflection_stays_idle`, `test_awaiting_ticket_sin_ticket_advances_to_awaiting_monto`, `test_awaiting_ticket_with_media_path_and_amount_advances_to_confirm`, `test_awaiting_ticket_with_media_path_vision_unreadable_advances_to_awaiting_monto` |
| `backend/tests/test_gastos_webhook.py` | 8 webhook integration tests | VERIFIED | Covers invalid sig, non-allowlisted, text-only dispatch, duplicate MessageSid, fast-200 assertion, media download+store+vision dispatch, bad magic bytes, sin-ticket text-only |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `conversation.py handle_message` | `DraftGasto.ticket_image_path / DraftGasto.monto` | media params set draft fields before CONFIRM | WIRED | `ticket_image_path` set at line 499; `ticket_amount` assigned to `draft.monto` at line 500; both saved via `_save_draft` before state → CONFIRM |
| `ticket_vision.py` | `openai chat.completions.parse` | amount-only vision call | WIRED | `await self._client.chat.completions.parse(model="gpt-4o-2024-08-06", ..., response_format=TicketAmount)` at line 114; `msg.refusal` checked at line 145 before `msg.parsed` at line 149 |
| `gastos.py` | `ConversationOrchestrator.handle_message` | background task feeds sender/text/message_id + ticket_image_path + ticket_amount | WIRED | `process_gasto_message` calls `orchestrator.handle_message(..., ticket_image_path=ticket_path, ticket_amount=ticket_amount)` at line 268 |
| `gastos.py` | `TicketVisionService.extract_amount + LocalStorageBackend.save` | download → magic-byte guard → store → vision → feed orchestrator | WIRED | Full pipeline at lines 226-275; `storage.save(image_bytes, filename)` at line 254; `vision.extract_amount(image_bytes)` at line 262; `ExtractionFailedError` caught at line 263 |
| `main.py` | `app.routers.gastos.router` | include_router under AGENT_MODE=='gastos' | WIRED | `elif settings.agent_mode == "gastos":` at line 62; `app.include_router(gastos_router, prefix="/gastos")` at line 66 |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|--------------------|--------|
| `conversation.py _handle_awaiting_ticket` | `ticket_amount` / `ticket_image_path` | `gastos.py process_gasto_message` → `TicketVisionService.extract_amount` + `LocalStorageBackend.save` | Yes — real OpenAI call + filesystem write | FLOWING |
| `conversation.py _confirm_summary` | `draft.monto` | assigned from `ticket_amount` (vision result) in branch (b) at line 500 | Yes — Decimal from `str(parsed.monto)` | FLOWING |
| `gastos.py process_gasto_message` | `ticket_path` / `ticket_amount` | `storage.save(image_bytes, ...)` + `vision.extract_amount(image_bytes)` | Yes — LocalStorageBackend returns real path; vision returns `Optional[Decimal]` | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `response_format=TicketAmount` present | `grep -n "response_format=TicketAmount" backend/app/services/ticket_vision.py` | line 132 match | PASS |
| `Decimal(str(...))` not `Decimal(float)` | `grep -n "Decimal(str(" backend/app/services/ticket_vision.py` | line 154 match | PASS |
| `msg.refusal` before `msg.parsed` in source order | `grep -n "msg.refusal" ticket_vision.py` (line 145) vs `msg.parsed` (line 149) | refusal at 145, parsed at 149 | PASS |
| `async def _handle_awaiting_ticket` | `grep -c "async def _handle_awaiting_ticket" conversation.py` | count = 1 | PASS |
| No hard media gate (NumMedia == 0 reject) | `grep -c "int(NumMedia) == 0" gastos.py` | count = 0 | PASS |
| AGENT_MODE gastos branch real (uncommented) | `grep -n 'agent_mode == "gastos"' main.py` | line 62, real elif | PASS |
| `asyncio.create_task` + strong-ref pattern | `grep -n "asyncio.create_task\|_background_tasks\|add_done_callback" gastos.py` | all three present at lines 352, 362, 363 | PASS |
| No debt markers in modified files | `grep -rn "TBD\|FIXME\|XXX" ticket_vision.py conversation.py gastos.py main.py` | no output | PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| GASTO-03 | 02-01-PLAN.md, 02-02-PLAN.md | Bot requests a photo of the ticket and stores it linked to the gasto record | SATISFIED | `gastos.py:249-265` — `LocalStorageBackend.save(image_bytes, f"{message_sid}/{message_sid}{ext}")` stores ticket; `ticket_path` passed to `orchestrator.handle_message(ticket_image_path=ticket_path)` which sets `draft.ticket_image_path` before `GastoService.save_gasto` writes the record |

**Note on REQUIREMENTS.md traceability:** GASTO-03 is listed as "Pending" in REQUIREMENTS.md traceability table (line 89). This is a pre-implementation status marker — the actual code satisfies the requirement. The traceability table should be updated to "Complete" as a follow-up housekeeping step, but it is not a gap in the implementation.

---

### Anti-Patterns Found

None. No `TBD`, `FIXME`, `XXX`, `HACK`, `PLACEHOLDER`, or unimplemented stubs found in any of the four files modified by this phase. `_handle_awaiting_ticket` branch (d) (re-prompt) is a real reply string, not a placeholder. `DEFLECTION_REPLY` is substantive Argentine Spanish content.

---

### Human Verification Required

#### 1. End-to-end gasto capture via Twilio sandbox

**Test:** From an allowlisted Twilio sandbox number, send "Pago de queso en supermercado". Then send a ticket photo (or "sin ticket"). Then send "sí" at the confirm summary.
**Expected:** Bot replies at each step with correct prompts; after "sí", a gasto row exists in Postgres with `concepto`, `monto`, `ticket_image_path` (or NULL for sin-ticket), and no conversation row in `draft_gasto`.
**Why human:** Requires live Twilio credentials, a running FastAPI server, and real WhatsApp messaging. No unit test can substitute for the actual transport round-trip (ROADMAP SC-1 and SC-2 both call this out explicitly as "verifiable end-to-end on the Twilio sandbox").

#### 2. Ticket photo vision path — image stored and linked to gasto

**Test:** From the allowlisted number at `awaiting_ticket` state, send a real receipt photo.
**Expected:** The image is stored under `STORAGE_PATH/{MessageSid}/{MessageSid}.jpg`; the confirm summary shows the vision-extracted monto; after confirmation the gasto row has `ticket_image_path` populated.
**Why human:** Requires a real JPEG, live GPT-4o vision API call, and DB inspection post-confirm. The unit test mocks the vision call; the real OCR accuracy on an Argentine ticket is only verifiable live.

#### 3. Replayed MessageSid against live Twilio (SC-4 full path)

**Test:** Using the Twilio sandbox retry mechanism or by re-POSTing the same webhook payload with the same MessageSid.
**Expected:** HTTP 200, no second state transition, `conversations.last_message_id` unchanged.
**Why human:** The in-memory `_processed_message_sids` fast-path is unit-tested, but the DB `last_message_id` source-of-truth path (handles process-restart replay) requires a live Twilio re-delivery to exercise the full contract stated in ROADMAP SC-4.

---

### Gaps Summary

No automated gaps found. All 10 must-have truths are VERIFIED against the actual codebase. No missing artifacts, no stubs, no broken wiring, no debt markers.

Status is `human_needed` because ROADMAP success criteria 1, 2, and 4 explicitly require Twilio sandbox verification — they cannot be satisfied by grep or unit tests alone. The three human items above are the remaining verification steps before the phase can be marked fully PASSED.

---

_Verified: 2026-05-27T23:22:00-03:00_
_Verifier: Claude (gsd-verifier)_
