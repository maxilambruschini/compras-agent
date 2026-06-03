---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Gastos Bot
status: Awaiting next milestone
stopped_at: Phase 04 Plan 03 complete — all plans done, ready for verification
last_updated: "2026-06-03T02:54:05.025Z"
last_activity: 2026-06-03 — Milestone v2.0 completed and archived
progress:
  total_phases: 4
  completed_phases: 4
  total_plans: 12
  completed_plans: 12
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-27)

**Core value:** An employee sends a photo of an invoice over WhatsApp and the data lands correctly in the database — no manual entry, no lost receipts.
**v2.0 goal:** A conversational WhatsApp bot that lets restaurant managers capture cash expenses (gastos) and report twice-daily cash closings — so payments stop getting forgotten.
**Demo build:** No proactive scheduler — a manual trigger endpoint stands in for the twice-daily prompts.
**Current focus:** Phase 04 — admin-ui

## Current Position

Phase: Milestone v2.0 complete
Plan: —
Status: Awaiting next milestone
Last activity: 2026-06-03 — Milestone v2.0 completed and archived

## Performance Metrics

**Velocity (v1.0 reference):**

- Total plans completed (v1.0): 7
- Average plans per phase: 1.75
- v2.0 estimates: TBD after Phase 1 planning

**By Phase (v2.0):**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1. Data + Conversation Core | TBD | - | - |
| 2. WhatsApp Gastos Flow | TBD | - | - |
| 3. Prompt Trigger Endpoint | TBD | - | - |
| 4. Admin UI | TBD | - | - |
| 02 | 2 | - | - |

*Updated after each plan completion*

| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 01-data-conversation-core | P01 | 8m | 3 | 6 |
| Phase 01-data-conversation-core P02 | 15 minutes | 2 tasks | 5 files |
| Phase 01-data-conversation-core PP03 | 5m | 1 tasks | 2 files |
| Phase 01-data-conversation-core P04 | 35m | 3 tasks | 3 files |
| Phase 03-prompt-trigger-endpoint P03 | 10m | 2 tasks | 4 files |
| Phase 04-admin-ui PP02 | 15m | 2 tasks | 2 files |
| Phase 04-admin-ui PP03 | 25m | 3 tasks | 9 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Key decisions affecting v2.0 work:

- **Demo build: no APScheduler** — the proactive scheduler is out of scope for v2.0. A protected `POST /gastos/prompt` endpoint fires the prompt on demand. The real scheduler + Utility template are deferred to the production path (Future Requirements).
- **No Utility template required for demo** — within a live demo the recipient has just messaged the bot, so the 24h customer-service window is open; a free-form send works without a pre-approved template. Template submission is deferred.
- **Hybrid conversation engine** — GPT-4o extracts slots from free Spanish text; deterministic `match` + `StrEnum` state machine owns all transitions and the DB write gate. GPT never decides to save.
- **DB-backed idempotency** — `Conversation.last_message_id` (not the v1.0 in-memory `_processed_message_sids` set which is wiped on restart).
- **Per-sender row lock** — `SELECT ... FOR NO KEY UPDATE` in ConversationOrchestrator before any state read or write.
- **Confirmation step: deterministic string match only** — affirmative set: `{"sí", "si", "dale", "ok", "confirmo", "listo", "va", "yes", "bueno", "claro"}`. No LLM at the write gate.
- **Argentine number parsing** — `parse_ars_amount()` utility: strip dots (thousands sep), replace comma with dot (decimal sep). Never use Python `locale` (global mutable state, unsafe in async).
- **Trigger endpoint auth** — `POST /gastos/prompt` protected by bearer token (env var). Returns 401 on missing/invalid token, sends nothing.
- **Scheduler skips active non-idle conversations** — applies to trigger endpoint too: if sender has a non-idle conversation when the endpoint fires, skip the send (prevents clobbering active draft).
- **`FOR NO KEY UPDATE` (not `FOR UPDATE`)** — does not block FK-referencing child table inserts.
- **RLS deferred from Phase 1** — enabling RLS with zero policies causes Postgres default-deny for non-owner app role; single-company v1 has no per-row tenancy benefit; tracked for a hardening phase with explicit policies + app-role test.
- **CajaCierre created in Phase 1** — alongside conversations/gastos in one migration; no schema debt; reactive write is Phase 2.
- [Phase ?]: GastoSlots.monto is Optional[float] — GPT JSON number sidesteps Decimal trap
- [Phase ?]: parse_ars_amount() validates ARS format via regex before stripping separators
- [Phase ?]: react-router v7 unified package ('react-router'), not 'react-router-dom'
- [Phase ?]: Layout route wraps NavTabs + Outlet so navigation persists across all three views
- [Phase ?]: formatDate splits on '-' to avoid UTC timezone shift on date-only ISO strings

### Pending Todos

- [ ] Confirm `tzdata` package required on Alpine containers (add only if Alpine base image used)

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260513-kwb | Fix Phase 1 cleanup: uv, CR-01/02/03, WR-01/03/05, is_active server_default | 2026-05-13 | 88a784c | [260513-kwb](./quick/260513-kwb-fix-phase-1-cleanup-items-before-phase-2/) |

### Blockers/Concerns

None active.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Auth | Admin email/password login (Supabase Auth) | v3 | v1.0 init |
| Extraction | EXT-V2-01: AFIP QR code decoding | v3 | v1.0 init |
| Extraction | EXT-V2-02: CUIT mod-11 validation | v3 | v1.0 init |
| Gastos | Cross-check declared monto vs ticket total (>5% delta warning) | v2.x | v2.0 design |
| Gastos | Edit/delete gastos from admin UI | v2.x | v2.0 design |
| Gastos | Daily/weekly expense summaries | v3 | v2.0 design |
| Scheduler | Real twice-daily APScheduler (12:00/17:00 ART) | production path | v2.0 demo decision |
| Scheduler | Pre-approved Twilio Utility message template | production path | v2.0 demo decision |
| Scheduler | Weekend/holiday suppression of proactive prompts | production path | v2.0 demo decision |
| Scheduler | External cron (multi-worker support) | v3 | v2.0 design |

## Session Continuity

Last session: 2026-05-31T04:07:40.500Z
Stopped at: Phase 04 Plan 03 complete — all plans done, ready for verification
Resume: Run `/gsd:execute-phase 3` to continue with Plan 03 (Wave 2: CajaCierreService + AWAITING_CIERRE FSM handlers)

## Operator Next Steps

- Start the next milestone with /gsd-new-milestone
