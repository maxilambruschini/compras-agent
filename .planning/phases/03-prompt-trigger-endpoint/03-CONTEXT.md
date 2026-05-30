# Phase 3: Prompt Trigger Endpoint - Context

**Gathered:** 2026-05-30
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous)

<domain>
## Phase Boundary

Build the demo stand-in for the twice-daily proactive prompt **and** the caja-closing
flow it initiates. A protected `POST /gastos/prompt` endpoint, when called with a
manager's phone number, sends the prompt WhatsApp message (asking for pending payments,
cash-on-hand, and "¿hiciste otra compra hoy?"). The manager's replies are handled by the
**existing Phase 2 webhook router + ConversationOrchestrator** — no new inbound endpoint.
A new caja-closing branch in the FSM records `efectivo_en_caja` into a `CajaCierre` row
with an auto-derived `hora_cierre` (12:00 / 17:00) and `fecha`.

**In scope:**
- `POST /gastos/prompt` — bearer-token-protected trigger endpoint (demo scheduler stand-in).
- Prompt message send via the existing `WhatsAppProvider` (24h CS window assumed open).
- New caja-closing branch in `ConversationOrchestrator` (new `AWAITING_CIERRE` state +
  confirm), writing a `CajaCierre` row.
- `hora_cierre` auto-derivation from server time (ART), `fecha` = day recorded.
- Requirements: TRIG-01, TRIG-02, CAJA-01, CAJA-02.

**Out of scope (deferred / later):**
- Real time-based scheduler (APScheduler) + Twilio Utility template — production path.
- Weekend/holiday suppression. Batch/multi-recipient prompts.
- Admin UI for cierres (Phase 4).
</domain>

<decisions>
## Implementation Decisions

### Trigger Endpoint Contract
- **Request body:** JSON `{"phone_number": "+54..."}` — clean admin API, distinct from
  the Twilio form-encoded webhook.
- **Auth:** `Authorization: Bearer <token>` compared to env var `GASTOS_PROMPT_TOKEN`.
  Missing/invalid token → **HTTP 401, no message sent** (ROADMAP success criterion #2,
  TRIG-01 "protected endpoint"). User confirmed: keep the auth mechanism as specified
  (briefly considered removing it for the demo, then reversed — auth stays).
- **Active-conversation handling:** If the recipient has a non-idle conversation when the
  endpoint fires, **skip the send** and return **HTTP 200 + `{"status":"skipped",
  "reason":"active_conversation"}`** (matches the locked "scheduler skips active non-idle
  conversations" decision; prevents clobbering an in-progress draft).
- **Recipients:** Single phone number per call. Caller loops externally if multiple
  managers need prompting. (Batch is deferred.)
- Success send returns HTTP 200 (e.g. `{"status":"sent"}`).

### Prompt → Caja-Closing Conversation Flow
- **Entry state:** A successful prompt send sets the conversation to a **new
  `AWAITING_CIERRE` state**; a bare-amount reply in that state is interpreted as
  `efectivo_en_caja`.
- **Disambiguation:** In `AWAITING_CIERRE`, a **bare amount → caja closing**; a
  **recognized gasto intent** (e.g. "pagué X de Y") → hand off to the existing gasto
  capture flow (the prompt is a nudge, not a lock). Reuse the slot extraction / ARS
  number parsing already built.
- **Confirm gate:** Writing a `CajaCierre` requires an **explicit confirm step** — echo
  "Cierre HH:MM: $X ¿confirmás?" before the DB write. Matches the REQUIREMENTS
  "no automatic save without explicit confirmation" principle (same deterministic
  affirmative-set gate used for gastos). After write → state returns to IDLE.
- **`hora_cierre` cutoff:** Reply received **before 14:30 ART → "12:00"**; **14:30 or
  later → "17:00"**. Auto-derived, never asked.

### Caja Data Integrity & Edge Cases
- **Duplicates:** Insert a **new `CajaCierre` row each time** for the same
  `(fecha, hora_cierre)` — no unique constraint (demo simplicity). The UI shows the
  latest. (Upsert/reject deferred.)
- **Timezone:** Derive server time explicitly in **`America/Argentina/Buenos_Aires` (ART)**
  via `zoneinfo` for both `fecha` and the `hora_cierre` cutoff. (Confirms the pending
  `tzdata` todo — add `tzdata` if the container base image lacks the zone database.)
- **Gasto reply to prompt:** If the manager replies with a gasto instead of cash, route
  to the existing gasto flow; the caja closing is simply **not recorded that cycle**.
- **"¿hiciste otra compra hoy?"** is **purely conversational** — it nudges into existing
  gasto capture; no new record type or per-cycle tracking flag.

### Claude's Discretion
- Exact JSON response envelopes and status strings.
- Module placement of the trigger endpoint (new router vs extend `gastos.py`).
- Exact Spanish copy for the prompt message and the cierre confirm/echo strings.
- Internal FSM wiring for `AWAITING_CIERRE` (e.g. reuse of draft column vs a small
  dedicated draft field) — provided the confirm gate and disambiguation rules hold.
- Whether the cutoff constant (14:30) is hard-coded or a settings value.
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/app/routers/gastos.py` — Phase 2 webhook router (fast-200, allowlist gate,
  signature validation, `process_gasto_message` background dispatch). The trigger
  endpoint is a new POST handler; it does **not** receive webhooks — it *sends* a prompt
  and primes conversation state. Reuse `get_whatsapp_provider` factory + `_safe_send`.
- `backend/app/services/conversation.py` — `ConversationOrchestrator.handle_message(...)`.
  Current `ConvState`: IDLE / AWAITING_MONTO / AWAITING_TICKET / CONFIRM (string class at
  line 85). Add `AWAITING_CIERRE` (+ any cierre-confirm handling) and a dispatch branch in
  the `match conv.state` block (lines ~336-355). Owns the txn, `FOR NO KEY UPDATE` lock,
  `last_message_id` idempotency, timeout reset, and confirm gate — all reused.
- `backend/app/db/models.py` — `CajaCierre` (line 166) already exists:
  `fecha: date`, `hora_cierre: String(5)` ("12:00"|"17:00"), `efectivo_en_caja: Numeric(14,2)`,
  `ix_caja_cierres_fecha` index. **No migration needed** for the table itself.
  `Conversation.state String(30)` (line 128) easily holds "awaiting_cierre".
- `backend/app/config.py` — `Settings` (pydantic-settings). Add `GASTOS_PROMPT_TOKEN`
  (optional default "" or required) following the existing env-var pattern. ART cutoff
  could be a setting too.
- ARS parsing utility (`parse_ars_amount`, Phase 1) + affirmative-set confirm gate —
  reused verbatim for the cierre amount and confirm step.
- `backend/app/providers/base.py` `WhatsAppProvider.send_message(to, text)` — used to send
  the prompt.

### Established Patterns
- Bearer/secret comparison should be constant-time and never logged (T-02-W8 lineage).
- Deterministic confirm gate (no LLM at the write boundary).
- Optional Pydantic slot fields (null > hallucination).
- `FOR NO KEY UPDATE` is Postgres-only; tests mock/assert the lock.

### Integration Points
- `backend/app/main.py` `create_app()` — mount the trigger endpoint under the same
  `AGENT_MODE == "gastos"` seam as the gastos webhook router.
- Endpoint must set conversation state to `AWAITING_CIERRE` for the recipient (same
  per-sender row + lock the orchestrator uses) so the next inbound reply branches correctly.
</code_context>

<specifics>
## Specific Ideas

- The endpoint is the **demo stand-in for the twice-daily scheduler** — it lets a demo
  driver fire the 12:00 / 17:00 prompt on demand. Within a live demo the recipient has
  just messaged the bot, so the 24h customer-service window is open and a free-form send
  works without a pre-approved Utility template.
- One coherent prompt message covers all three asks (pending payments, cash-on-hand,
  "¿hiciste otra compra hoy?"); the reply branches by content, not by separate endpoints.
</specifics>

<deferred>
## Deferred Ideas

- Real APScheduler twice-daily scheduler + Twilio Utility template (production path).
- Weekend/holiday suppression of prompts.
- Batch / multi-recipient prompt in one request.
- Upsert/reject semantics for duplicate `(fecha, hora_cierre)` cierres.
- Cross-checking declared vs extracted amounts (REQUIREMENTS Future).
</deferred>

---

*Phase: 3-prompt-trigger-endpoint*
*Context gathered: 2026-05-30 (smart discuss, autonomous mode)*
