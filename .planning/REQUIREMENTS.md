# Requirements: Compras Agent — Milestone v2.0 Gastos Bot

**Milestone:** v2.0 Gastos Bot
**Defined:** 2026-05-27
**Provider:** Twilio (WhatsApp). Demo build — no Utility template required (trigger fires within 24h customer-service window).

Conversational WhatsApp bot for a restaurant manager to record cash expenses
(gastos) paid out of the register and report twice-daily cash closings (cierres de
caja). Hybrid engine: GPT-4o extracts intent/slots from free Spanish text; a
deterministic state machine owns transitions and the DB write. Builds on the shipped
v1.0 invoice system (reuses WhatsAppProvider, ExtractionService, LocalStorageBackend,
SenderAllowlist, FastAPI/Postgres stack).

See `docs/plans/2026-05-27-gastos-bot-design.md` and `.planning/research/SUMMARY.md`.

## v2.0 Requirements

### Gasto Capture (GASTO)

- [x] **GASTO-01**: Manager records a cash expense by texting a free-form intent in Spanish (e.g. "Pago de queso en supermercado")
- [ ] **GASTO-02**: Bot collects the required gasto fields (concepto, lugar/proveedor, monto) through follow-up questions when not provided up front
- [ ] **GASTO-03**: Bot requests a photo of the ticket and stores it linked to the gasto record
- [ ] **GASTO-04**: Manager can skip the ticket ("sin ticket") and still save the gasto
- [ ] **GASTO-05**: Bot shows a summary and requires explicit confirmation before writing the gasto
- [ ] **GASTO-06**: Manager can correct a field or cancel the gasto before it is saved

### Conversation Engine (CONV)

- [x] **CONV-01**: Conversation state is persisted per sender in the database and survives process restarts
- [ ] **CONV-02**: Duplicate WhatsApp webhook deliveries do not advance state or create duplicate records (DB-backed idempotency)
- [ ] **CONV-03**: Concurrent messages from the same sender are serialized so state cannot be corrupted (per-sender row lock)
- [ ] **CONV-04**: A stale/abandoned conversation auto-resets to idle on the next message after a timeout
- [x] **CONV-05**: Argentine number formats are parsed correctly ("1.500" = $1.500, "1.234,56" = $1234.56)
- [ ] **CONV-06**: Unparseable or off-topic replies re-prompt the current step instead of failing silently

### Caja Closing (CAJA)

- [ ] **CAJA-01**: Manager reports cash-on-hand (efectivo en caja) for a twice-daily closing
- [ ] **CAJA-02**: Each closing is recorded with the date and which closing (12:00 / 17:00) it corresponds to

### Prompt Trigger (TRIG)

> Demo build: a real time-based scheduler is out of scope. A manual trigger endpoint
> stands in for the twice-daily prompt so the prompt flow can be fired on demand
> during a demo. Within a live demo the recipient has just messaged the bot, so the
> 24h customer-service window is open and a free-form send works without a template.

- [ ] **TRIG-01**: A protected endpoint, when called, sends the prompt message to a given manager via WhatsApp (demo stand-in for the scheduler)
- [ ] **TRIG-02**: The triggered prompt asks for pending payments, cash-on-hand, and "¿hiciste otra compra hoy?", and branches into the capture / caja-closing flow

### Admin UI (UI)

- [ ] **UI-01**: Manager/accountant can list and view captured gastos in the web UI
- [ ] **UI-02**: Manager/accountant can list and view caja closings in the web UI

## Future Requirements (deferred)

- [ ] Cross-check declared monto against extracted ticket total, warn on mismatch (adds a GPT call per ticket; validate adoption first — no schema change needed, JSON column reserved)
- [ ] Edit/delete gastos from the admin UI
- [ ] Daily/weekly expense summaries
- [ ] Real time-based scheduler (twice-daily 12:00/17:00 prompts) via APScheduler — production path; demo uses the manual trigger endpoint instead
- [ ] Pre-approved Twilio Utility message template for proactive sends outside the 24h window — required only for the real production scheduler above
- [ ] Weekend/holiday suppression of proactive prompts
- [ ] Admin authentication (email/password) — deferred from v1.0

## Out of Scope

- Open-ended chit-chat / general assistant behavior — this is a closed transactional tool; off-topic messages get a fixed deflection
- Free-form LLM tool-calling that can persist records on its own — write path stays deterministic (GPT extracts, code saves)
- Automatic save without explicit confirmation — one misparse would write garbage permanently
- Multi-restaurant / multi-tenant — single-restaurant deployment
- Time-based proactive scheduler — this is a demo build; replaced by a manual trigger endpoint (see TRIG). The real scheduler + Utility template are deferred to the production path.

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| CONV-01 | Phase 1 | Complete |
| CONV-02 | Phase 1 | Pending |
| CONV-03 | Phase 1 | Pending |
| CONV-04 | Phase 1 | Pending |
| CONV-05 | Phase 1 | Complete |
| CONV-06 | Phase 1 | Pending |
| GASTO-01 | Phase 1 | Complete |
| GASTO-02 | Phase 1 | Pending |
| GASTO-04 | Phase 1 | Pending |
| GASTO-05 | Phase 1 | Pending |
| GASTO-06 | Phase 1 | Pending |
| GASTO-03 | Phase 2 | Pending |
| CAJA-01 | Phase 2 | Pending |
| CAJA-02 | Phase 2 | Pending |
| TRIG-01 | Phase 3 | Pending |
| TRIG-02 | Phase 3 | Pending |
| UI-01 | Phase 4 | Pending |
| UI-02 | Phase 4 | Pending |
