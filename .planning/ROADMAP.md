# Roadmap: Compras Agent

## Overview

**v1.0 MVP** shipped 2026-05-27: WhatsApp invoice capture, GPT-4o extraction, Postgres persistence, React admin UI. Archived to `.planning/milestones/v1.0/`.

**v2.0 Gastos Bot** (current): A conversational WhatsApp bot for Argentine restaurant managers to capture cash expenses (gastos) and report twice-daily cash closings (cierres de caja). Demo build — the proactive scheduler is replaced by a manual trigger endpoint. Four phases, starting at Phase 1.

## Milestones

### v1.0 MVP (Shipped: 2026-05-27)

- [x] Phase 1: Foundation — Docker Compose + Postgres schema + Pydantic models (completed 2026-05-13)
- [x] Phase 2: Extraction Pipeline — GPT-4o vision extraction, confidence scoring, StorageBackend (completed 2026-05-14)
- [x] Phase 3: WhatsApp Pipeline — End-to-end webhook receive → extract → store → reply (completed 2026-05-14)
- [x] Phase 4: Admin UI — React invoice list, detail, edit, delete, search, filter (completed 2026-05-27)

### v2.0 Gastos Bot (Current)

**Phase Numbering:** Reset to 1 for this milestone.

- [x] **Phase 1: Data + Conversation Core** - DB models, Alembic migration, ConversationOrchestrator, SlotExtractionService, GastoService — unit-testable with no WhatsApp or scheduler (completed 2026-05-27)
- [x] **Phase 2: WhatsApp Gastos Flow** - /gastos webhook router, reactive multi-turn capture end-to-end via Twilio (completed 2026-05-28)
- [ ] **Phase 3: Prompt Trigger Endpoint** - Protected POST /gastos/prompt endpoint that sends the prompt message to a given manager on demand (demo stand-in for the scheduler)
- [ ] **Phase 4: Admin UI** - Gastos list/detail and Cierres list views cloned from v1.0 invoice pattern

## Phase Details

### Phase 1: Data + Conversation Core
**Goal**: The conversation engine, data models, and gasto persistence layer exist and are fully unit-tested — no WhatsApp connection required
**Depends on**: Nothing (first phase of v2.0)
**Requirements**: CONV-01, CONV-02, CONV-03, CONV-04, CONV-05, CONV-06, GASTO-01, GASTO-02, GASTO-04, GASTO-05, GASTO-06
**Success Criteria** (what must be TRUE):
  1. A unit test can drive the ConversationOrchestrator through every state transition (idle → awaiting_monto → awaiting_ticket → confirm → idle) using a mocked WhatsApp provider and mocked slot extractor — all transitions pass without touching WhatsApp or the network
  2. A duplicate webhook message ID (matching `Conversation.last_message_id`) causes the orchestrator to exit without advancing state or writing any record — confirmed by test with a mocked DB session
  3. Two concurrent orchestrator calls for the same sender are serialized by `SELECT ... FOR NO KEY UPDATE`; neither call reads stale state or produces a duplicate DB write — confirmed by test
  4. A conversation row older than `CONVERSATION_TIMEOUT_HOURS` auto-resets to idle on the next inbound message, and the manager receives a Spanish-language timeout notice — confirmed by test
  5. Argentine number strings "1.500" and "1.234,56" are parsed to Decimal("1500") and Decimal("1234.56") respectively by `parse_ars_amount()` — confirmed by unit test; Python's `Decimal("1.500")` trap documented and blocked
  6. An unparseable reply re-prompts the current step; after 3 consecutive failures the bot sends a concrete example and offers to cancel — confirmed by test; GPT is never invoked on the confirmation step (deterministic string match only)
**Plans**: 4 plans
- [x] 01-01-PLAN.md — Data foundation: Gasto/Conversation/CajaCierre models, migration, config (AGENT_MODE, timeout), main.py seam
- [x] 01-02-PLAN.md — Slot extraction: GastoSlots/DraftGasto DTOs, parse_ars_amount(), SlotExtractionService (gpt-4o-mini)
- [x] 01-03-PLAN.md — GastoService persistence (mirrors InvoiceService)
- [x] 01-04-PLAN.md — ConversationOrchestrator: match-based FSM, lock, idempotency, timeout, re-prompt, confirm gate

### Phase 2: WhatsApp Gastos Flow
**Goal**: An allowlisted manager can send a free-form Spanish expense intent on WhatsApp and the bot drives the full multi-turn capture — intent → ticket photo (amount read by GPT vision) or "sin ticket" (amount asked) → confirmation → saved gasto record — end-to-end via Twilio
**Depends on**: Phase 1
**Requirements**: GASTO-03
**Note**: Caja-closing flow (CAJA-01, CAJA-02) moved to Phase 3 — it is initiated by the Phase 3 prompt-trigger, so it is built there alongside its entry point (decision 2026-05-27).
**Success Criteria** (what must be TRUE):
  1. Sending "Pago de queso en supermercado" from an allowlisted Twilio number triggers an immediate acknowledgement and the bot asks for a ticket photo; the gasto is saved in the DB after the manager replies "sí" at confirm — verifiable end-to-end on the Twilio sandbox
  2. Sending a ticket photo at the `awaiting_ticket` step stores the image via LocalStorageBackend, runs GPT-4o vision to extract the amount spent (`monto`), and links the image to the gasto record; replying "sin ticket" skips storage and the bot asks the manager to type the amount instead
  3. Sending from a non-allowlisted number returns a Spanish rejection message and creates no DB record
  4. A replayed webhook (identical Twilio `MessageSid`) does not advance state or create a duplicate record — confirmed against the live Twilio sandbox
  5. The `/gastos/webhook` router returns HTTP 200 before any DB or GPT work begins (Twilio timeout safety) — verified with a timing test or log inspection
  6. An idle message that is neither a gasto intent nor recognizable returns a fixed Spanish deflection reply and leaves conversation state at idle — confirmed by test
**Plans**: 2 plans
- [x] 02-01-PLAN.md — FSM rework to ticket-first + amount-only GPT-4o vision extractor + media entry path + off-topic deflection
- [x] 02-02-PLAN.md — /gastos/webhook Twilio router (signature → allowlist → fast-200 → background orchestrator with ticket download/store/vision) + AGENT_MODE mount

### Phase 3: Prompt Trigger Endpoint
**Goal**: A caller can POST to a protected endpoint with a manager's phone number and that manager immediately receives the prompt message on WhatsApp — the conversation engine then handles all follow-up replies via the existing Phase 2 webhook router, including recording the cash-on-hand caja closing
**Depends on**: Phase 2
**Requirements**: TRIG-01, TRIG-02, CAJA-01, CAJA-02
**Success Criteria** (what must be TRUE):
  1. `POST /gastos/prompt` with a valid bearer token and a manager phone number returns HTTP 200 and the manager receives a WhatsApp message asking for pending payments, cash-on-hand, and "¿hiciste otra compra hoy?" — verifiable in the Twilio sandbox within a live demo session (24h customer-service window is open because the recipient has already messaged the bot)
  2. `POST /gastos/prompt` with a missing or invalid token returns HTTP 401 — no message is sent
  3. After receiving the triggered prompt, the manager can reply conversationally and the existing orchestrator handles the full capture / caja-closing branch without any additional endpoint — confirmed end-to-end in the sandbox
  4. A manager who replies with a cash-on-hand amount in the caja-closing flow has a `CajaCierre` row written with the correct `hora_cierre` (12:00 or 17:00, auto-derived from server time) and `fecha` — verifiable in the DB
**Plans**: 3 plans (3 waves — TDD RED→GREEN)
- [x] 03-01-PLAN.md — Wave 0 RED: test_prompt_trigger.py + test_conversation_cierre.py + conftest GASTOS_PROMPT_TOKEN + cierre.py skeleton + config token field
- [ ] 03-02-PLAN.md — Wave 1: POST /gastos/prompt bearer-auth trigger endpoint (constant-time, fail-closed, row-lock, send-after-commit) + main.py mount (TRIG-01, TRIG-02 send)
- [ ] 03-03-PLAN.md — Wave 2: CajaCierreService.save_cierre (ART hora_cierre/fecha) + AWAITING_CIERRE/AWAITING_CIERRE_CONFIRM FSM branch + gasto handoff (CAJA-01, CAJA-02, TRIG-02 reply)

### Phase 4: Admin UI
**Goal**: A manager or accountant can open the web UI and view all captured gastos and caja closings — read-only lists showing only committed records, not in-progress conversation drafts
**Depends on**: Phase 3
**Requirements**: UI-01, UI-02
**Success Criteria** (what must be TRUE):
  1. The Gastos page lists all rows from the `gastos` table (confirmed status only — no `conversations.draft_gasto` rows appear), with columns for fecha, concepto, lugar, monto, and ticket indicator; rows are filterable by date range and searchable by concepto or lugar
  2. Clicking a gasto row shows the full detail: all fields, the ticket image (if present), and the ticket extraction JSON (if present)
  3. The Cierres page lists all `caja_cierres` rows with fecha, hora_cierre (12:00 / 17:00), and efectivo_en_caja; no editing controls are shown (read-only)
**Plans**: TBD
**UI hint**: yes

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Data + Conversation Core | 4/4 | Complete   | 2026-05-27 |
| 2. WhatsApp Gastos Flow | 2/2 | Complete   | 2026-05-28 |
| 3. Prompt Trigger Endpoint | 1/3 | In Progress|  |
| 4. Admin UI | 0/TBD | Not started | - |
