# Project Research Summary

**Project:** Compras Agent — v2.0 Gastos Bot
**Domain:** Conversational WhatsApp expense-capture bot with proactive scheduling (Argentine restaurant, Spanish UX)
**Researched:** 2026-05-27
**Confidence:** HIGH

---

## CRITICAL CONSTRAINT — READ BEFORE PLANNING PHASES

> **WhatsApp proactive messages require a pre-approved "Utility" template. Free-form messages sent outside the 24-hour customer-service window are silently rejected (Meta error 131026 / Twilio error 63016). Template approval takes up to 24 hours. The scheduler phase (Phase 3) cannot go to production without an approved template.**
>
> **Action required: Template submission is a Phase 2 exit criterion, not a Phase 3 task. The roadmap must enforce this order.**

---

## Executive Summary

Milestone v2.0 adds two net-new behaviors to the shipped v1.0 invoice-capture system: (1) proactive twice-daily WhatsApp prompts that trigger a caja-closing flow, and (2) a multi-turn conversational expense-capture flow initiated by managers texting free-form Spanish intent. The v1.0 stack (FastAPI + pywa + GPT-4o + Postgres + React/Vite) is fully reused. The only new backend dependency is APScheduler 3.11.2. No new infra. No new WhatsApp provider logic.

The recommended architecture is a hybrid engine: GPT-4o handles free-text slot extraction (concepto, lugar, monto from informal Spanish), while a deterministic Python state machine (`match` + `StrEnum`) owns all state transitions and the DB write gate. GPT never "decides" to save — code enforces required fields and the mandatory confirmation step. Conversation state is DB-backed (one `conversations` row per sender), making it restart-safe and suitable for multi-hour reply gaps. The `conversations` row is protected by `SELECT ... FOR NO KEY UPDATE` at the start of every orchestrator call to prevent concurrent webhook deliveries from racing on the same sender's state.

The highest-risk element of v2.0 is the Meta/Twilio messaging policy constraint on proactive outbound. Every 12:00 prompt will land outside the 24-hour customer-service window on typical days — the API will silently reject free-form text. A pre-approved Utility-category message template must be submitted to Meta early enough that approval completes before Phase 3 implementation begins. Secondary risks are: Argentine number format parsing ("1.500" meaning 1,500 ARS), APScheduler version choice (3.x vs 4.x APIs differ substantially — lock to 3.11.2), and confirmation-step ambiguity (deterministic string match required — no LLM on the step where money is written).

---

## Key Findings

### Recommended Stack

The v1.0 stack is unchanged. Only one new backend dependency is added for v2.0: `apscheduler==3.11.2`. The version question is resolved: APScheduler 3.11.2 is the correct choice. APScheduler 4.x (currently `4.0.0a6`) is explicitly marked not production-safe by its maintainer and may change APIs without a migration path. APScheduler 3.11+ supports `zoneinfo` natively — do not install `pytz` alongside it. On Alpine containers add the `tzdata` package; on Debian/Ubuntu it is already present.

The conversation engine is hand-rolled (`match` + `StrEnum` in ~100 lines). No state machine library, no LangGraph, no Rasa. LangGraph break-even is roughly two cooperative agents or three independent branching paths — this bot has one agent and linear state progression.

**Core technologies (v2.0 additions only — full v1.0 list in STACK.md):**
- `apscheduler==3.11.2`: In-process cron scheduler — `AsyncIOScheduler` + `CronTrigger` in FastAPI `lifespan`. Single new dep, zero new infra, appropriate for 2 static jobs/day at single-worker Uvicorn.
- Hand-rolled `match` + `StrEnum`: Conversation state machine — 5 states, 2 linear flows. No library adds value at this scale.
- `openai` (existing, v2.36.0): Slot extraction via `.parse()` with a new `GastoSlots` Pydantic model alongside the existing invoice schema.
- `tzdata` (conditional): IANA timezone database — add only on Alpine containers.

**APScheduler version decision — MUST BE LOCKED BEFORE PHASE 3:**
STACK.md recommends 3.11.2. ARCHITECTURE.md examples show 4.x patterns (`AsyncScheduler`, `add_schedule`, `async with`) inconsistently. These are incompatible APIs. Resolve to 3.11.2 before Phase 3 planning and audit ARCHITECTURE.md snippets for 4.x usage before treating them as implementation reference.

### Expected Features

All v2.0 features are P1 for launch. Deferred items are v2.x patches or v3+. Full prioritization matrix in FEATURES.md.

**Must have — v2.0 launch (all P1):**
- DB-backed conversation state per sender — foundational; every multi-turn feature depends on it; unit-test before WhatsApp wiring
- Free-text intent parsing in Spanish — `SlotExtractionService` using GPT-4o `.parse()` into `GastoSlots{concepto, lugar, monto: Optional[Decimal]}`
- Slot-filling follow-up questions — orchestrator re-prompts for missing monto
- Ticket photo step with "sin ticket" skip — reuses v1.0 `extraction.py` and `storage.py` untouched
- Mandatory confirmation step before save — explicit "sí" required; deterministic string match only, no LLM
- "cancelar" global command — checked before any state logic on every inbound message
- Re-prompt on unparseable reply (max 3 retries, then concrete example + offer to cancel)
- Mid-flow correction at confirmation — rewinds to the relevant `awaiting_X` state
- Session timeout / auto-reset — check `conversations.updated_at` delta; default 4h; configurable as `CONVERSATION_TIMEOUT_HOURS`
- Structured `Gasto` record persisted to DB — replaces handwritten GASTOS sheet
- Twice-daily proactive prompts (12:00 / 17:00 ART) — primary adoption driver; requires pre-approved Utility template
- Caja closing flow (`awaiting_caja_count` state triggered by scheduler)
- DB-backed idempotency on webhook retries — `Conversation.last_message_id` column; NOT the v1.0 in-memory set (never acceptable for gastos flow)
- Sender allowlist gate — zero new code (v1.0 reuse)
- WhatsApp text vs. media routing — separate `/gastos/webhook` router; state-aware dispatch inside orchestrator
- Admin UI: gastos list + detail + edit — clone invoice views
- Admin UI: cierres de caja list — read-only

**Should have — v2.x patches (post-validation):**
- Cross-check declared monto vs. ticket total (>5% delta → warning before confirmation)
- "¿Hiciste otra compra hoy?" post-cierre nudge
- Raw ticket extraction stored as JSONB for audit (backfillable)

**Defer — v3+:**
- Weekly/monthly WhatsApp summaries
- Supabase Auth for admin UI
- External scheduler (only if deployment becomes multi-instance)

### Architecture Approach

The system adds a second webhook router (`/gastos/webhook`) alongside the existing `/whatsapp/webhook`. Both share the same `WhatsAppProvider` abstraction and `validate_signature` pattern. The gastos router dispatches text and media messages to a `ConversationOrchestrator`, which loads the sender's `conversations` row under a per-sender row lock, runs one state transition, writes back, then sends the WhatsApp reply outside the transaction to avoid holding the lock during network I/O. The scheduler runs as `AsyncIOScheduler` inside the FastAPI `lifespan` context manager and upserts `conversations` rows via plain INSERT ... ON CONFLICT DO UPDATE (no FOR UPDATE — scheduler sets state, does not read-modify-write slots).

**Major components (net-new for v2.0):**
1. `app/routers/gastos_whatsapp.py` — webhook entry: signature validation, allowlist gate, text/media dispatch, `asyncio.create_task` to orchestrator
2. `app/services/conversation.py` (ConversationOrchestrator) — loads conversation row under `SELECT ... FOR NO KEY UPDATE`, dispatches to state handlers, owns all transitions and the write gate
3. `app/services/slot_extraction.py` (SlotExtractionService) — GPT-4o `.parse()` on free Spanish text → `GastoSlots{concepto, lugar, monto: Optional[Decimal]}`
4. `app/services/gasto.py` (GastoService) — `save_gasto()`, `save_caja_cierre()`, query methods for admin API
5. `app/services/scheduler.py` — APScheduler job: queries active allowlist, sends proactive Utility template prompts, upserts Conversation rows
6. `app/routers/gastos_admin.py` — `GET /gastos`, `GET /gastos/{id}`, `PATCH /gastos/{id}`, `GET /caja-cierres`
7. Alembic migration — `gastos`, `caja_cierres`, `conversations` tables (all with `ENABLE ROW LEVEL SECURITY`)
8. Frontend: `GastosPage.tsx`, `CierresPage.tsx` — clone invoice list pattern

**DB-backed idempotency (replaces in-memory set permanently):**
`Conversation.last_message_id` checked as the first operation inside the row lock before any state is read. The v1.0 `_processed_message_sids` in-memory set is wiped on restart; a duplicate caja cierre corrupts reconciliation figures irrecoverably.

**Per-sender row lock pattern (SELECT ... FOR NO KEY UPDATE):**
Opens async session, locks the `conversations` row for the sender, checks `last_message_id` for idempotency, runs the state machine, commits, then sends the WhatsApp reply after the transaction. Two concurrent deliveries of the same message: first acquires lock, processes, commits; second acquires lock, sees matching `last_message_id`, exits. No double transition.

### Critical Pitfalls

Full pitfall list (32 entries) in PITFALLS.md. Top 5 for phase planning:

1. **Proactive messages require pre-approved Utility template — BLOCKS PHASE 3 (P19).** Free-form outbound text is silently rejected by Meta (error 131026) and Twilio (error 63016) outside the 24-hour customer-service window. Template approval takes up to 24 hours. Submit the Utility template no later than end of Phase 2. Make "template approved" a Phase 2 exit criterion. Never fall back to free-form `body` for outbound-initiated messages.

2. **Argentine number format parsing causes silent amount corruption (P26).** Managers type "1.500" meaning $1,500 ARS; Python's `Decimal("1.500")` returns 1.5. GPT Structured Outputs with `monto: Optional[float]` is the primary defense (GPT outputs JSON numbers, not locale strings). Any fallback parser must apply `parse_ars_amount()`: strip dots (thousands separator), replace commas with dots (decimal separator). Never use Python's `locale` module — global mutable state unsafe in async servers.

3. **In-memory idempotency never acceptable for gastos (P20).** The v1.0 `_processed_message_sids` set is wiped on restart. Duplicate delivery after restart can write a second caja cierre — a corruption with no visible error. Use `Conversation.last_message_id` (DB-persisted, checked under the row lock) from Phase 1.

4. **Confirmation step must use deterministic string match — no LLM (P31).** This is the gate between draft and DB write. Use fixed affirmative set: `{"sí", "si", "dale", "ok", "confirmo", "listo", "va", "yes", "bueno", "claro"}`. Any reply not in this set is treated as a correction/denial and re-prompted.

5. **Concurrent webhook deliveries race on the `conversations` row (P21).** WhatsApp delivers with at-least-once semantics. Without a row lock, two concurrent deliveries load the same state and both write back. Use `SELECT ... FOR NO KEY UPDATE` at the start of every orchestrator call. Send the WhatsApp reply after the transaction commits.

**Additional items to carry forward into phase planning:**
- Session timeout: check `updated_at` delta on every inbound message; reset to idle with user-facing message on expiry
- APScheduler: `misfire_grace_time=600`, `coalesce=True`, `replace_existing=True` on all cron jobs
- Scheduler must be single-worker (`--workers 1`) for v2.0; document this constraint with the upgrade path
- `SCHEDULER_TIMEZONE = "America/Argentina/Buenos_Aires"` as typed config constant; log `next_run_time` at startup
- If sender has active non-idle conversation when scheduler fires: skip the proactive prompt for that sender (prevents upsert from clobbering an active draft)

---

## Implications for Roadmap

The approved design doc defines four phases. Research confirms this ordering and adds critical enforcement constraints.

### Phase 1: Data + Conversation Core

**Rationale:** Every v2.0 feature is gated on DB-backed conversation state. The orchestrator, slot extractor, and gasto service are fully unit-testable without WhatsApp or APScheduler. Building and testing in isolation catches the highest-risk logic before any platform dependency is introduced.

**Delivers:** Three new DB tables with migrations, ConversationOrchestrator, SlotExtractionService, GastoService, full unit test coverage of all state transitions with mocked provider and mocked extraction.

**Addresses:** DB-backed conversation state, free-text intent parsing, slot-filling follow-ups, re-prompt on parse failure, cancelar command, session timeout/expiry, mid-flow correction, structured Gasto persistence.

**Must implement in Phase 1:**
- `Conversation.last_message_id` column (DB idempotency — replaces in-memory set)
- `SELECT ... FOR NO KEY UPDATE` in orchestrator
- `monto: Optional[Decimal]` in `GastoSlots` + `parse_ars_amount()` utility
- All `DraftGasto` fields `Optional` with defaults
- `ENABLE ROW LEVEL SECURITY` in migration for all three new tables

**Avoids:** P20 (in-memory idempotency), P21 (concurrent race), P25 (monto hallucination), P26 (Argentine number parsing), P31 (LLM on confirmation), P32 (rigid draft schema)

### Phase 2: WhatsApp Gastos Flow

**Rationale:** With the orchestrator tested in isolation, wire it to the WhatsApp webhook. This phase validates the full reactive flow end-to-end. This is also where the Utility template must be submitted — approval takes up to 24 hours and Phase 3 cannot begin without it.

**Delivers:** Full reactive gastos capture end-to-end (text intent → monto → ticket photo → confirm → save), separate `/gastos/webhook` router, ticket photo reusing v1.0 `extraction.py`/`storage.py` untouched, status event filter.

**Addresses:** WhatsApp text vs. media routing, ticket photo step with "sin ticket" skip, confirmation step, sender allowlist gate, idempotency on webhook retries.

**Must implement in Phase 2:**
- Separate `gastos_whatsapp.py` router (do not branch existing `/whatsapp/webhook`)
- State-aware message type validation in orchestrator
- Status event filter
- Webhook 200 response before any DB or GPT work
- **WhatsApp Utility template submitted to Meta/Twilio before Phase 2 closes**

**Phase 2 exit criterion:** Template submitted AND approval confirmed before Phase 3 planning begins.

**Avoids:** P1 (media URL expiry), P4 (webhook timeout), P7 (status event flood), P19 (by submitting template early), P29 (image/text branching)

### Phase 3: Proactive Scheduler

**Rationale:** The scheduler depends on the WhatsApp send path (Phase 2) and the conversation state machine (Phase 1). It cannot go to production without the approved Utility template from Phase 2. Building it last means the template approval window is fully consumed during Phase 2 development.

**Delivers:** APScheduler 3.11.2 wired into FastAPI `lifespan`, twice-daily Utility template prompts, caja closing flow, scheduler health check on `GET /health`.

**Addresses:** Twice-daily proactive prompts, caja closing flow, optional "¿Hiciste otra compra hoy?" nudge.

**Must implement in Phase 3:**
- Pin `apscheduler==3.11.2` (NOT 4.x alpha) — resolve before Phase 3 planning
- `SCHEDULER_TIMEZONE = "America/Argentina/Buenos_Aires"` typed config constant
- `misfire_grace_time=600`, `coalesce=True`, `replace_existing=True`
- Single-worker constraint documented with upgrade path
- Job error listener + structlog `event="scheduler.job_failed"`
- Startup log: `next_run_time` in Buenos Aires local time for both jobs
- Utility template path only — no free-form `body` fallback
- Skip proactive prompt for senders with active non-idle conversation

**Avoids:** P19 (enforced by Phase 2 exit criterion), P23 (missed fires), P24 (double fires from multi-worker), P27 (timezone misconfiguration), P28 (silent scheduler death), P30 (prompts on closed days)

**Research flag:** APScheduler version (3.x vs 4.x) must be locked to 3.11.2 before this phase is planned. ARCHITECTURE.md code samples use 4.x API — audit and replace before use.

### Phase 4: Admin UI

**Rationale:** Frontend views are independent of backend behavior and can be built after the three backend phases are stable. Cloning the invoice list/detail/edit pattern makes this low-risk.

**Delivers:** `GastosPage.tsx` (list + detail + edit), `CierresPage.tsx` (read-only), backend endpoints for gastos and cierres.

**Addresses:** Admin UI gastos list + detail + edit, admin UI cierres list.

**Uses:** Existing TanStack Query v5 patterns, React Router 7.x, existing filter bar and edit form components — minimal new logic.

**Note:** Admin UI must show only committed `gastos` rows, not `conversations.draft_gasto` (unconfirmed financial data).

### Phase Ordering Rationale

- Phase 1 before Phase 2: Orchestrator must be unit-tested in isolation; WhatsApp retry behavior makes state machine bugs difficult to reproduce
- Phase 2 before Phase 3: Utility template approval window (up to 24h) must be consumed during Phase 2 development — Phase 3 cannot start without an approved template
- Phase 3 before Phase 4: Admin UI views records created by Phase 3's flows; testing against empty tables is unproductive
- Template submission is a Phase 2 exit criterion, not a Phase 3 task — this is the single most important scheduling constraint in v2.0

### Research Flags

**Phase 3 — one decision must be locked before planning begins:**
- APScheduler version: STACK.md says 3.11.2; ARCHITECTURE.md code uses 4.x patterns. Lock to 3.11.2 and audit ARCHITECTURE.md before implementation.

**All phases — standard patterns (skip additional research):**
- Phase 1: SQLAlchemy ORM `with_for_update()`, Alembic migrations — well-documented, established in v1.0
- Phase 2: pywa webhook routing, FastAPI router registration, `asyncio.create_task` — established v1.0 patterns
- Phase 4: TanStack Query v5, React Router 7 list/detail/edit — clone invoice views

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified against PyPI 2026-05-27. APScheduler 3.11.2 confirmed stable. One internal inconsistency (ARCHITECTURE.md used 4.x examples) — must resolve before Phase 3. |
| Features | HIGH | Derived from approved first-party design doc. Full dependency graph verified. No ambiguity on MVP scope. |
| Architecture | HIGH | Derived from live codebase inspection + approved design doc. Component map, data flow, and anti-patterns are concrete. |
| Pitfalls | HIGH | WhatsApp template policy verified against official Meta/Twilio docs. Concurrency patterns verified against PostgreSQL official docs. APScheduler behavior verified against official docs and GitHub issues. |

**Overall confidence: HIGH**

### Gaps to Address

- **APScheduler version inconsistency:** STACK.md recommends 3.11.2; ARCHITECTURE.md code samples use APScheduler 4.x API (`AsyncScheduler`, `add_schedule`, `ConflictPolicy`). Resolve to 3.11.2 before Phase 3 planning. Rewrite ARCHITECTURE.md snippets that use 4.x API before treating them as implementation reference.

- **Utility template submission details:** The template body is known ("Hola {{1}}, es hora del cierre del mediodía. ¿Cuánto efectivo queda en caja?") but the exact Meta/Twilio submission format, Content SID workflow, and variable binding must be confirmed when Phase 2 begins. Not blocking Phase 1 development, but must be resolved before Phase 2 closes.

- **Scheduler-interrupts-active-conversation:** If the scheduler fires at 17:00 while a manager is mid-gasto (non-idle state), the upsert to `awaiting_caja_count` would clobber the active draft. Recommended mitigation: skip the proactive prompt for senders with non-idle conversation state. This logic must be fully specified in Phase 3 planning.

- **`FOR NO KEY UPDATE` vs `FOR UPDATE`:** Both appear in the research files. `FOR NO KEY UPDATE` is preferred (does not block foreign-key-referencing inserts from child tables). Confirm and apply consistently in Phase 1.

---

## Sources

### Primary (HIGH confidence)

- `docs/plans/2026-05-27-gastos-bot-design.md` — approved design, v2.0 scope, reuse map, phase breakdown
- `.planning/research/STACK.md` — verified against PyPI registries 2026-05-27
- `.planning/research/FEATURES.md` — derived from approved design doc + v1.0 codebase reuse map
- `.planning/research/ARCHITECTURE.md` — derived from live codebase inspection + approved design doc
- `.planning/research/PITFALLS.md` — WhatsApp policy verified against official Meta/Twilio docs; PostgreSQL concurrency verified against official docs
- APScheduler 3.x user guide: https://apscheduler.readthedocs.io/en/3.x/userguide.html
- Meta WhatsApp error 131026: https://developers.facebook.com/documentation/business-messaging/whatsapp/reference/errors#131026
- Twilio error 63016: https://www.twilio.com/docs/api/errors/63016

### Secondary (MEDIUM confidence)

- APScheduler 4.x production guidance — PyPI pre-release warning + maintainer GitHub discussions
- LangGraph break-even — community consensus across multiple sources
- APScheduler + Gunicorn multi-worker: GitHub Discussion #1088

### Tertiary (LOW confidence)

- Meta Utility template approval timing (up to 24h) — documented typical range, not guaranteed SLA
- Argentine number format normalization — confirmed by multiple blog sources; GPT JSON output as primary defense is highest-confidence path

---

*Research completed: 2026-05-27*
*Ready for roadmap: yes*
