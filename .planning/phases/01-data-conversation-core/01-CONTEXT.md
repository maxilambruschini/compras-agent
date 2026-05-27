# Phase 1: Data + Conversation Core - Context

**Gathered:** 2026-05-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver the conversation engine, data models, and gasto persistence layer for the
Gastos Bot — fully unit-testable with NO WhatsApp connection and NO scheduler.
Covers CONV-01..06 and the persistence/orchestration side of GASTO-01, 02, 04, 05, 06.

In scope: SQLAlchemy models (Gasto, Conversation; CajaCierre may land here or Phase 2
per planner), Alembic migration, the deterministic ConversationOrchestrator state
machine, the SlotExtractionService (GPT text→slots), GastoService persistence,
`parse_ars_amount()`, DB-backed idempotency + per-sender row locking + timeout reset,
and the config/env additions (AGENT_MODE, CONVERSATION_TIMEOUT_HOURS).

Out of scope (later phases): the Twilio webhook wiring and ticket-photo capture
(Phase 2), the prompt-trigger endpoint (Phase 3), admin UI (Phase 4).
</domain>

<decisions>
## Implementation Decisions

### Gasto data shape
- **D-01:** Minimal field set. A gasto holds: `concepto` (freeform observación, e.g. "queso en supermercado"), `monto` (the salida / money paid out, Decimal), `fecha` (auto = today, not asked), and an optional ticket reference (image path, populated in Phase 2). No separate lugar/proveedor field, no entrada, no category in v2.0.
- **D-02:** `fecha` defaults to the day the gasto is recorded. Backdating ("ayer compré…") is NOT supported in v2.0 (deferred).

### Conversation flow
- **D-03:** Ask only the slots still missing after parsing the opening intent — one question per turn. If the manager's first message already supplies a slot (e.g. "queso en supermercado $1500" gives concepto + monto), the bot does not re-ask it.
- **D-04:** State sequence: `idle` → (extract slots from intent) → `awaiting_monto` (only if monto missing) → `awaiting_ticket` → `confirm` → write Gasto → `idle`. Concepto comes from the intent; if absent, the bot asks for it before monto. Order of follow-ups: concepto (if needed) → monto → ticket → confirm.
- **D-05:** Confirmation step uses a deterministic string match (sí/dale/ok/confirmo …), never an LLM call — money is written only on explicit confirmation. (Reaffirms ROADMAP success criterion 6.)

### Slot extraction model
- **D-06:** SlotExtractionService uses **gpt-4o-mini** (cheaper/faster; short-text slot parsing is within its range). Vision/ticket extraction in Phase 2 still uses gpt-4o. Mirror the existing `client.chat.completions.parse()` + Pydantic pattern from `services/extraction.py`, with an Optional-fields `DraftGasto`/`GastoSlots` schema (null > hallucination).

### Correction & cancellation
- **D-07:** At the confirm step the manager corrects a field by re-stating it freeform ("no, fueron 1500", "era en la verdulería"); the SlotExtractionService re-parses the message and patches the matching slot(s) on the draft, then re-confirms. `cancelar` aborts the draft and returns to `idle`.

### Timeout
- **D-08:** `CONVERSATION_TIMEOUT_HOURS = 4`. A conversation row whose `updated_at` is older than the threshold auto-resets to `idle` on the next inbound message; the manager gets a short Spanish notice that the previous draft expired. (Uses existing `updated_at`; no extra column needed.)

### Agent selection (demo isolation)
- **D-09:** A single env var **`AGENT_MODE`** with values `invoice` | `gastos` selects which demo agent is live. The app registers ONLY the selected agent's WhatsApp webhook/router; the other is fully disabled (not just hidden). Default value for this milestone is `gastos`. The config setting + the conditional router registration in `app/main.py` are introduced here in Phase 1 (config layer); the gastos webhook itself is wired in Phase 2. The existing invoice webhook registration becomes conditional on `AGENT_MODE == "invoice"`.

### Claude's Discretion
- Exact ORM column types/lengths, table/index names, Alembic migration structure.
- Whether CajaCierre model is created here or in Phase 2 (it has no reactive flow until Phase 2) — planner decides.
- Internal module layout of the orchestrator (single `conversation.py` `match` statement vs. helpers) — research recommended a simple `match`-based orchestrator.
- Exact Spanish copy strings (re-prompts, timeout notice, confirmation) — keep concise, Argentine Spanish.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design & requirements
- `docs/plans/2026-05-27-gastos-bot-design.md` — approved design: reuse-vs-recreate map, hybrid engine choice, data model, conversation flow. NOTE the demo-build amendment at top (scheduler → trigger endpoint).
- `.planning/REQUIREMENTS.md` — v2.0 requirements (GASTO/CONV/CAJA/TRIG/UI) + traceability.
- `.planning/ROADMAP.md` §"Phase 1: Data + Conversation Core" — goal + 6 success criteria that pre-lock the technical mechanics.

### Research
- `.planning/research/SUMMARY.md` — synthesized findings; cross-cutting constraints.
- `.planning/research/ARCHITECTURE.md` — state machine + concurrency/idempotency integration (NOTE: contains APScheduler 4.x snippets that are now irrelevant — scheduler dropped for the demo).
- `.planning/research/PITFALLS.md` — DB idempotency, FOR NO KEY UPDATE row lock, conversation timeout, Argentine number parsing (`Decimal("1.500")` trap).
- `.planning/research/STACK.md` — confirms no new deps needed for Phase 1 (apscheduler dropped; slot extraction reuses existing OpenAI client).
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/app/services/extraction.py` — the `client.chat.completions.parse()` + Pydantic `.parsed`/`.refusal` pattern to mirror for SlotExtractionService. Also the service constructor/DI shape.
- `backend/app/services/invoice.py` (`InvoiceService`: find_duplicate / save_invoice) — persistence pattern to mirror for `GastoService`.
- `backend/app/db/models.py` — ORM conventions: `DeclarativeBase`, `Mapped`/`mapped_column`, dialect-agnostic `sqlalchemy.Uuid`, server-default timestamps with `onupdate` (gives the `updated_at` the timeout logic relies on), Optional columns. `SenderAllowlist` reused as-is.
- `backend/app/config.py` — Pydantic Settings pattern; add `AGENT_MODE` and `CONVERSATION_TIMEOUT_HOURS` here (fail-fast validation like existing env vars).

### Established Patterns
- All extraction/draft Pydantic fields are `Optional` with `default=None` (null > hallucination) — apply to the slot schema.
- Async SQLAlchemy sessions; tests run on aiosqlite, prod on asyncpg — keep models dialect-agnostic (no `postgresql.UUID`). NOTE: `SELECT ... FOR NO KEY UPDATE` is Postgres-only — tests must mock/assert the locking call rather than rely on SQLite semantics.
- Lazy engine/settings factories so pytest can patch env before construction.

### Integration Points
- `backend/app/main.py` `create_app()` — router registration becomes conditional on `AGENT_MODE`. This is the seam for demo isolation (D-09).
- `backend/app/providers/base.py` `WhatsAppProvider` — not used in Phase 1 (orchestrator takes a mocked provider in tests), but the orchestrator's send interface should match `send_message(to, text)` for Phase 2 wiring.
</code_context>

<specifics>
## Specific Ideas

- The handwritten "GASTOS" sheet (OBSERVACION / ENTRADA / SALIDA / FIRMA) is the mental model for the data, but v2.0 deliberately captures only the minimal subset (concepto + salida). The freeform `concepto` mirrors the sheet's OBSERVACION column, which itself mixes item and place.
- Demo intent: one deployment = one agent. `AGENT_MODE=gastos` is the milestone default; flipping to `invoice` resurrects the shipped v1.0 demo unchanged.
</specifics>

<deferred>
## Deferred Ideas

- Capture `entrada` (money in) alongside salida — future, if reconciliation is needed.
- Separate `lugar`/`proveedor` field distinct from concepto — future, enables structured queries.
- Expense `category` field.
- Backdating `fecha` ("ayer compré…").
- Structured field-picker correction UX (reply a number) — chose freeform re-extract instead.
- Cross-check declared monto vs. extracted ticket total (already in REQUIREMENTS Future).

None of these expand Phase 1 scope — captured so they aren't lost.
</deferred>

---

*Phase: 1-data-conversation-core*
*Context gathered: 2026-05-27*
