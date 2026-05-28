# Phase 2: WhatsApp Gastos Flow - Context

**Gathered:** 2026-05-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire the live `/gastos/webhook` Twilio router and drive the **reactive multi-turn
gasto capture** end-to-end: an allowlisted manager texts a free-form Spanish intent,
the bot asks for a ticket photo, GPT-4o vision reads the amount off the ticket (or
the manager types it after "sin ticket"), the manager confirms, and a `Gasto` row +
ticket image land in the DB. Covers GASTO-03 plus the WhatsApp/transport side of the
gasto flow already engineered in Phase 1 (states, idempotency, lock, timeout, confirm
gate, slot extraction).

**In scope:**
- The `/gastos/webhook` FastAPI router (mirrors v1.0 `/whatsapp/webhook`): Twilio
  signature validation → allowlist gate → return HTTP 200 fast → run the orchestrator
  in a background task.
- Mount the gastos router under the `AGENT_MODE == "gastos"` seam in `app/main.py`
  (the seam was pre-built in Phase 1 D-09 as a commented-out branch).
- **Ticket-photo capture (GASTO-03)** at the `awaiting_ticket` step: download via
  `LocalStorageBackend`, store the image, run GPT-4o vision to extract the **amount**,
  link the image path to the gasto.
- **Flow reorder** of the Phase 1 orchestrator so the ticket step is the amount source
  (see D-01).
- Fixed Spanish deflection reply for off-topic / unrecognized idle messages (D-04).

**Out of scope (moved or later):**
- **Caja-closing flow (CAJA-01, CAJA-02) → moved to Phase 3** (decision 2026-05-27).
  It is initiated by the Phase 3 prompt-trigger, so it is built there alongside its
  entry point. `CajaCierre` model already exists (Phase 1); `hora_cierre` rule is
  captured in D-03 below for Phase 3 to use.
- Prompt-trigger endpoint (Phase 3). Admin UI (Phase 4).
- Cross-checking declared amount vs ticket total (deferred — REQUIREMENTS Future).
</domain>

<decisions>
## Implementation Decisions

### Gasto flow order (reorders Phase 1 FSM)
- **D-01:** **Ticket-first.** Flow is: `idle` (intent supplies `concepto`; ask concepto
  if absent) → **`awaiting_ticket`** → if a photo is sent, GPT-4o vision extracts the
  `monto` and the image is stored; if the manager replies "sin ticket", the bot asks
  for the amount (→ `awaiting_monto`) → `confirm` → write `Gasto` → `idle`. This
  **changes the Phase 1 sequence** (which asked `monto` before the ticket). The
  planner must rework `ConvState` / orchestrator dispatch in `services/conversation.py`
  to put the ticket step ahead of the amount step.
- **D-01a (edge — planner to resolve):** If the opening intent already states an amount
  *and* the manager later sends a ticket, vision re-reads the amount from the ticket;
  the `confirm` summary shows the resolved amount so the manager can correct it
  freeform (Phase 1 D-07 correction path). If no ticket is sent, use the stated/typed
  amount without re-asking.
- **D-01b:** If vision cannot read an amount from the ticket, fall back to asking the
  manager to type it (re-prompt), reusing the Phase 1 re-prompt/3-strikes behavior.

### Ticket vision extraction
- **D-02:** Ticket vision uses **gpt-4o** (vision), and extracts **only the amount
  spent** — not the full Argentine invoice schema. The image is always stored when
  provided. (Slot/text extraction stays on gpt-4o-mini per Phase 1 D-06.) The exact
  extraction approach — a lightweight amount-only prompt vs. reusing
  `services/extraction.py`'s `ExtractedInvoice` and pulling the total — is planner
  discretion; "amount only" is the requirement.

### Caja-closing (deferred to Phase 3 — captured here so it isn't lost)
- **D-03 [informational]:** (Phase 3 — not a Phase 2 deliverable.) `hora_cierre` is **auto-derived from server time** (a cutoff selects
  "12:00" vs "17:00"), not asked. The exact cutoff is planner discretion when Phase 3
  builds the caja flow. `fecha` = the day the closing is recorded.

### Off-topic / unrecognized messages
- **D-04:** An idle message that is neither a gasto intent nor recognizable gets a
  **fixed Spanish deflection reply** describing what the bot does; conversation state
  stays `idle`. No GPT free-chat. Exact copy is planner discretion (concise, Argentine
  Spanish).

### Transport / webhook (carried from v1.0 pattern — not re-discussed)
- **D-05:** The webhook validates the Twilio signature, gates on `SenderAllowlist`,
  returns HTTP 200 **before** any DB/GPT work, then runs the orchestrator in a
  background task (v1.0 `asyncio.create_task` + strong-ref-set pattern). DB-backed
  idempotency lives in the orchestrator (Phase 1 `last_message_id`); whether to also
  keep a router-level in-memory dedupe is planner discretion.
- **D-06:** Media reaches the orchestrator by extending its entry path —
  `handle_message` currently takes text only. The planner decides whether the router
  downloads media and passes a path/bytes into an extended orchestrator method, or the
  orchestrator gains media params. The `WhatsAppProvider.send_message(to, text)` /
  `download_media(url)` interface is fixed.

### Claude's Discretion
- Exact `ConvState` names after the reorder; module layout of the reworked orchestrator.
- Router-level dedupe vs orchestrator-only idempotency.
- Ticket amount-extraction prompt/schema (amount-only is the only hard requirement).
- All Spanish copy strings (ticket request, deflection, ticket-unreadable fallback).
- `hora_cierre` cutoff time (Phase 3).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design & requirements
- `docs/plans/2026-05-27-gastos-bot-design.md` — approved design (reuse-vs-recreate
  map, hybrid engine, conversation flow). NOTE the demo-build amendment at top
  (scheduler → trigger endpoint) and that this Phase 2 reorders the flow per D-01.
- `.planning/REQUIREMENTS.md` — v2.0 requirements + traceability (CAJA-01/02 now Phase 3).
- `.planning/ROADMAP.md` §"Phase 2: WhatsApp Gastos Flow" — goal + 6 success criteria.
- `.planning/phases/01-data-conversation-core/01-CONTEXT.md` — Phase 1 decisions
  (D-01..D-09) this phase builds on, especially the FSM, confirm gate, timeout, and
  the AGENT_MODE seam (D-09).

### Research
- `.planning/research/SUMMARY.md` — synthesized findings; cross-cutting constraints.
- `.planning/research/ARCHITECTURE.md` — state machine + concurrency/idempotency
  (ignore the APScheduler snippets — scheduler dropped for the demo).
- `.planning/research/PITFALLS.md` — DB idempotency, `FOR NO KEY UPDATE` row lock,
  timeout reset, Argentine number parsing.

### Code to mirror
- `backend/app/routers/whatsapp.py` — the v1.0 webhook to mirror for `/gastos/webhook`:
  signature validation, allowlist gate, 200-before-work, `asyncio.create_task` +
  `_background_tasks` strong-ref set, magic-byte image guard, provider factory.
- `backend/app/services/extraction.py` — the GPT-4o vision `.parse()` pattern reused
  for ticket amount extraction (D-02).
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/app/routers/whatsapp.py` — full v1.0 reactive webhook: signature
  validation, `SenderAllowlist` gate, `get_whatsapp_provider` factory, fast-200 +
  background task, `_validate_image_bytes` magic-byte guard, `_safe_send`. The gastos
  router is a structural clone that dispatches into the orchestrator instead of the
  invoice pipeline.
- `backend/app/services/conversation.py` — `ConversationOrchestrator.handle_message(
  session_factory, sender, text, message_id)`. Owns transaction, lock
  (`FOR NO KEY UPDATE`), idempotency (`last_message_id`), timeout reset, confirm gate,
  reply-send outside the txn. **Must be reworked for D-01 ticket-first order and D-06
  media path.** Current `ConvState`: IDLE / AWAITING_MONTO / AWAITING_TICKET / CONFIRM.
- `backend/app/services/extraction.py` — `ExtractionService` (GPT-4o vision +
  Pydantic `.parse()`); reuse for ticket amount extraction (D-02).
- `backend/app/services/storage.py` `LocalStorageBackend` — stores the ticket image as
  it stores invoice images.
- `backend/app/providers/base.py` `WhatsAppProvider` Protocol + `twilio.py` impl —
  `send_message`, `download_media`, `validate_signature` reused untouched.
- `backend/app/db/models.py` — `Gasto`, `Conversation`, `CajaCierre`, `SenderAllowlist`
  all exist from Phase 1. `Gasto` already has an optional ticket reference field.

### Established Patterns
- Fast-200 then background task (`asyncio.create_task` + module-level strong-ref set)
  so Twilio's 5s timeout is never hit before DB/GPT work.
- Provider accessed only via the `WhatsAppProvider` Protocol; tests override the
  provider factory through `app.dependency_overrides`.
- Slot/draft Pydantic fields are `Optional` (null > hallucination) — applies to the
  ticket amount extraction too.
- `SELECT ... FOR NO KEY UPDATE` is Postgres-only — tests mock/assert the lock call
  (aiosqlite has no such semantics).

### Integration Points
- `backend/app/main.py` `create_app()` — uncomment/implement the `AGENT_MODE == "gastos"`
  branch (currently a comment placeholder, D-09) to mount the gastos router.
- `ConversationOrchestrator` entry path — extended to carry media (D-06) and reordered
  for ticket-first (D-01).
</code_context>

<specifics>
## Specific Ideas

- The whole point of vision-on-ticket: the manager just photographs the ticket and the
  bot reads the amount off it — typing the amount is the fallback for "sin ticket".
  Vision is deliberately scoped to the amount only (no full invoice extraction) to keep
  cost/latency low and the flow focused.
- One deployment = one agent (`AGENT_MODE=gastos` is the milestone default); flipping to
  `invoice` resurrects the shipped v1.0 demo unchanged.
</specifics>

<deferred>
## Deferred Ideas

- **Caja-closing reactive entry** — explicitly deferred to Phase 3 (built with its
  prompt-trigger initiator). `hora_cierre` rule captured in D-03.
- Cross-check declared/extracted amount vs ticket total (REQUIREMENTS Future).
- Multi-attachment ticket handling (v1.0 processes only the first media item).

None of these expand Phase 2 scope — captured so they aren't lost.
</deferred>

---

*Phase: 2-whatsapp-gastos-flow*
*Context gathered: 2026-05-27*
