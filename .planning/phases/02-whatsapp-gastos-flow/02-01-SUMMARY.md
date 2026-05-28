---
phase: 02-whatsapp-gastos-flow
plan: "01"
subsystem: conversation-fsm
tags: [fsm, vision, ticket-first, whatsapp, d-01, d-02, d-04, d-06]
dependency_graph:
  requires:
    - 01-04 (ConversationOrchestrator, DraftGasto, GastoSlots, parse_ars_amount)
    - 01-02 (SlotExtractionService, ExtractionFailedError)
  provides:
    - TicketVisionService (ticket_vision.py) — amount-only GPT-4o vision extractor
    - handle_message(ticket_image_path, ticket_amount) — media entry params for D-06
    - DEFLECTION_REPLY — fixed Spanish off-topic reply constant
    - Ticket-first FSM: idle→AWAITING_TICKET→(CONFIRM|AWAITING_MONTO)
  affects:
    - 02-02 (gastos router — consumes extended handle_message signature and TicketVisionService)
tech_stack:
  added: []
  patterns:
    - TicketAmount Pydantic model (Optional[float] + ConfigDict(use_enum_values=True))
    - check msg.refusal BEFORE msg.parsed (Pitfall 2 pattern from extraction.py)
    - Decimal(str(parsed.monto)) — never Decimal(float) for Argentine separator safety
    - async _handle_awaiting_ticket with 4 branches (sin-ticket, photo+amount, photo+unreadable, re-prompt)
    - DEFLECTION_REPLY module-level constant for off-topic idle (D-04)
key_files:
  created:
    - backend/app/services/ticket_vision.py
    - backend/tests/test_ticket_vision.py
  modified:
    - backend/app/services/conversation.py
    - backend/tests/test_conversation.py
decisions:
  - D-01 ticket-first: concepto-known idle → AWAITING_TICKET; sin ticket → AWAITING_MONTO
  - D-02 amount-only: TicketAmount(monto: Optional[float]) not ExtractedInvoice
  - D-04 deflection: no-slot idle → DEFLECTION_REPLY, stays IDLE
  - D-06 media entry: handle_message(ticket_image_path, ticket_amount) keyword params
metrics:
  duration: "6 minutes"
  completed: "2026-05-27"
  tasks_completed: 2
  files_changed: 4
---

# Phase 2 Plan 1: Ticket-First FSM + Amount-Only Vision Extractor Summary

**One-liner:** D-01 ticket-first FSM reorder + new TicketVisionService extracting amount via GPT-4o `.parse()` with Optional[float] schema, refusal-before-parsed guard, and Decimal(str()) conversion.

## What Was Built

### Task 1: TicketVisionService (`backend/app/services/ticket_vision.py`)

Amount-only GPT-4o vision extractor for payment ticket images. Mirrors `ExtractionService._call_gpt4o` pattern from `extraction.py`.

- `TicketAmount(BaseModel)`: single field `monto: Optional[float] = None` — null > hallucination; JSON number sidesteps Decimal("1.500") Argentine separator trap
- `TicketVisionService.extract_amount(image_bytes) -> Optional[Decimal]`: calls `chat.completions.parse(model="gpt-4o-2024-08-06", response_format=TicketAmount)`, checks `msg.refusal` BEFORE `msg.parsed` (Pitfall 2 / T-02-02), converts via `Decimal(str(parsed.monto))` — never `Decimal(float)`
- `SYSTEM_PROMPT`: Argentine Spanish amount-only prompt with number format rules
- Raises `ExtractionFailedError` on transport errors; API key never logged (T-02-01)
- No storage param — router owns image storage (D-06)
- 7 tests: success, decimal precision, unreadable (None), refusal, refusal+None-parsed, transport error, no-key-logged

### Task 2: Ticket-First FSM Rework (`backend/app/services/conversation.py`)

Reworked `ConversationOrchestrator` for D-01 ticket-first ordering and D-06 media entry. Non-negotiable entry sequence (ensure-row → lock → snapshot → idempotency → timeout → cancel → dispatch → commit → reply-outside-txn) preserved unchanged.

**Changes:**
1. `handle_message` gains `ticket_image_path: Optional[str] = None` and `ticket_amount: Optional[Decimal] = None` keyword params (D-06 media entry). Both default None — text-only Phase 1 calls still work unchanged.

2. `_handle_idle` reworked (D-01 ticket-first + D-04 deflection):
   - No slots extracted (concepto=None, monto=None) → `DEFLECTION_REPLY`, stay IDLE (D-04)
   - Concepto missing but gasto signal present → ask concepto, set AWAITING_MONTO
   - Concepto known → `AWAITING_TICKET` + ask for ticket photo (ticket-first; was AWAITING_MONTO in Phase 1)

3. `_handle_awaiting_ticket` reworked — now `async def` (previously sync `def`), 4 branches:
   - (a) `"sin ticket"` (case-insensitive) → `ticket_image_path=None`, state=AWAITING_MONTO, ask to type amount
   - (b) `ticket_image_path` + `ticket_amount` both set → `draft.monto = ticket_amount`, `draft.ticket_image_path = path`, state=CONFIRM, return `_confirm_summary(draft)` (D-01a/D-02)
   - (c) `ticket_image_path` set, `ticket_amount=None` (vision unreadable) → store path on draft, state=AWAITING_MONTO, ask to type amount (D-01b fallback)
   - (d) plain text without photo → re-prompt for photo or "sin ticket"

4. `DEFLECTION_REPLY` module-level constant (Argentine Spanish, concise, explains the bot's purpose, D-04)

5. Pure helpers (`is_confirmation`, `is_cancel`, `patch_draft`, `_load_draft`, `_save_draft`, `_confirm_summary`, `_handle_awaiting_monto`, `_handle_confirm`) unchanged.

**Tests updated:** 3 Phase 1 tests updated to reflect D-01 reorder; 5 new Phase 2 D-01/D-04 tests added. 25 total conversation tests + 1 lock-sql test all pass.

## Deviations from Plan

None — plan executed exactly as written.

The Phase 1 test `test_full_flow_awaiting_monto`, `test_state_persists`, and `test_sin_ticket` were updated as part of the D-01 reorder per Task 2 plan action ("adjust the existing idle→ticket ordering assertions to expect AWAITING_TICKET after concepto is known"). This is expected, not a deviation.

## Known Stubs

None. All behaviors are fully implemented and tested:
- `TicketVisionService.extract_amount` calls actual `chat.completions.parse`
- `_handle_awaiting_ticket` handles all 4 branches including media path
- `DEFLECTION_REPLY` is a real Spanish message, not a placeholder

## Threat Surface Scan

No new network endpoints introduced (Plan 01 is services-only — no router). All threat model mitigations satisfied:
- T-02-01: API key never logged — `log.error("ticket_vision.failed", error=str(exc))` logs exception message only, not settings
- T-02-02: `msg.refusal` checked before `msg.parsed`; `TicketAmount.monto: Optional[float]`; `None` returned on unreadable/refusal; `Decimal(str(...))` conversion
- T-02-03: Confirm gate unchanged — `is_confirmation()` deterministic match; vision never writes
- T-02-04: Image size guard enforced at router boundary (Plan 02) — orchestrator receives already-validated bytes/path (not in this plan's scope)
- T-02-SC: No new packages — `openai` and `pydantic` already pinned

## Self-Check

All created/modified files exist:

- `backend/app/services/ticket_vision.py` — ✓ created
- `backend/tests/test_ticket_vision.py` — ✓ created
- `backend/app/services/conversation.py` — ✓ modified
- `backend/tests/test_conversation.py` — ✓ modified

Commits:
- `f62c45a` — `feat(02-01): amount-only GPT-4o vision extractor (TicketVisionService)`
- `f871a1d` — `feat(02-01): rework FSM to ticket-first flow with media entry + deflection (D-01, D-02, D-04, D-06)`

Test results: `32 passed` (7 ticket_vision + 24 conversation + 1 lock_sql)

## Self-Check: PASSED
