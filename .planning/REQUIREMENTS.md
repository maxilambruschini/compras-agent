# Requirements: Compras Agent — Milestone v2.0 Gastos Bot

**Milestone:** v2.0 Gastos Bot
**Defined:** 2026-05-27
**Provider:** Twilio (WhatsApp). Utility message template submitted via Twilio Content API.

Conversational WhatsApp bot for a restaurant manager to record cash expenses
(gastos) paid out of the register and report twice-daily cash closings (cierres de
caja). Hybrid engine: GPT-4o extracts intent/slots from free Spanish text; a
deterministic state machine owns transitions and the DB write. Builds on the shipped
v1.0 invoice system (reuses WhatsAppProvider, ExtractionService, LocalStorageBackend,
SenderAllowlist, FastAPI/Postgres stack).

See `docs/plans/2026-05-27-gastos-bot-design.md` and `.planning/research/SUMMARY.md`.

## v2.0 Requirements

### Gasto Capture (GASTO)

- [ ] **GASTO-01**: Manager records a cash expense by texting a free-form intent in Spanish (e.g. "Pago de queso en supermercado")
- [ ] **GASTO-02**: Bot collects the required gasto fields (concepto, lugar/proveedor, monto) through follow-up questions when not provided up front
- [ ] **GASTO-03**: Bot requests a photo of the ticket and stores it linked to the gasto record
- [ ] **GASTO-04**: Manager can skip the ticket ("sin ticket") and still save the gasto
- [ ] **GASTO-05**: Bot shows a summary and requires explicit confirmation before writing the gasto
- [ ] **GASTO-06**: Manager can correct a field or cancel the gasto before it is saved

### Conversation Engine (CONV)

- [ ] **CONV-01**: Conversation state is persisted per sender in the database and survives process restarts
- [ ] **CONV-02**: Duplicate WhatsApp webhook deliveries do not advance state or create duplicate records (DB-backed idempotency)
- [ ] **CONV-03**: Concurrent messages from the same sender are serialized so state cannot be corrupted (per-sender row lock)
- [ ] **CONV-04**: A stale/abandoned conversation auto-resets to idle on the next message after a timeout
- [ ] **CONV-05**: Argentine number formats are parsed correctly ("1.500" = $1.500, "1.234,56" = $1234.56)
- [ ] **CONV-06**: Unparseable or off-topic replies re-prompt the current step instead of failing silently

### Caja Closing (CAJA)

- [ ] **CAJA-01**: Manager reports cash-on-hand (efectivo en caja) for a twice-daily closing
- [ ] **CAJA-02**: Each closing is recorded with the date and which closing (12:00 / 17:00) it corresponds to

### Proactive Scheduler (SCHED)

- [ ] **SCHED-01**: Each active manager is prompted twice daily (12:00 and 17:00 America/Argentina/Buenos_Aires)
- [ ] **SCHED-02**: Proactive prompts are delivered via a pre-approved Twilio Utility message template (24h-window compliant)
- [ ] **SCHED-03**: The scheduled prompt asks for pending payments, cash-on-hand, and "¿hiciste otra compra hoy?", branching into the capture/closing flow
- [ ] **SCHED-04**: Scheduler survives restarts without double-firing or silently skipping (misfire grace + coalesce)

### Admin UI (UI)

- [ ] **UI-01**: Manager/accountant can list and view captured gastos in the web UI
- [ ] **UI-02**: Manager/accountant can list and view caja closings in the web UI

## Future Requirements (deferred)

- [ ] Cross-check declared monto against extracted ticket total, warn on mismatch (adds a GPT call per ticket; validate adoption first — no schema change needed, JSON column reserved)
- [ ] Edit/delete gastos from the admin UI
- [ ] Daily/weekly expense summaries
- [ ] Weekend/holiday suppression of proactive prompts
- [ ] Admin authentication (email/password) — deferred from v1.0

## Out of Scope

- Open-ended chit-chat / general assistant behavior — this is a closed transactional tool; off-topic messages get a fixed deflection
- Free-form LLM tool-calling that can persist records on its own — write path stays deterministic (GPT extracts, code saves)
- Automatic save without explicit confirmation — one misparse would write garbage permanently
- Multi-restaurant / multi-tenant — single-restaurant deployment
- Multi-worker scheduler (Gunicorn `--workers >1`) — v2.0 runs single-worker; revisit with APScheduler 4.x + shared jobstore or external cron if scaled

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| (filled by roadmap) | | |
