# Feature Research

**Domain:** Conversational WhatsApp expense-capture bot (gastos + cierres de caja) — Argentine restaurant, Spanish UX
**Researched:** 2026-05-27
**Confidence:** HIGH — based on approved design doc (`docs/plans/2026-05-27-gastos-bot-design.md`) and v1.0 codebase reuse map

> This file covers **v2.0 net-new features only**. Existing v1.0 capabilities (one-shot invoice photo capture, GPT-4o extraction, admin invoice UI, sender allowlist, storage, dedup) are treated as available infrastructure — not re-researched here.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features the manager expects from day one. Missing any = bot feels broken or untrustworthy.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **DB-backed conversation state per sender** | Managers reply hours later from a different session; in-memory state is wiped on restart, losing partial gastos | HIGH | New `conversations` table: `sender_phone (unique), state (enum), draft_gasto (JSONB), updated_at`. Must survive Uvicorn restarts. No analog in v1.0 — entirely new. |
| **Free-text intent parsing (Spanish)** | Managers type naturally ("Pago de queso en el Coto") not structured commands | MEDIUM | `slot_extraction.py` — GPT-4o parses free Spanish text into `{concepto, lugar, monto}` slots. Reuses openai client + Pydantic Structured Outputs from v1.0 `extraction.py`. New Pydantic slot schema required. |
| **Slot-filling follow-up questions** | Bot must ask for what it doesn't have (monto, proveedor) rather than failing silently | MEDIUM | Deterministic state machine in `conversation.py`; transitions are code-owned, not LLM decisions. States: `idle → awaiting_monto → awaiting_ticket → confirm → idle`. |
| **Re-prompt on unparseable reply** | Manager typos or sends ambiguous text; bot must stay on the current slot and re-ask clearly | LOW | Orchestrator: if GPT slot extraction returns all-null slots for the expected field, re-send the current question unchanged. Cap at 3 retries then send a concrete example ("Escribí el monto en números, ej: 1500"). No state transition on failure. |
| **Ticket photo step ("Mandame una foto del ticket")** | Physical receipt is the audit record; manager expects to be asked | MEDIUM | State `awaiting_ticket`: bot prompts; inbound media → `storage.py` download + `extraction.py` run on ticket. "sin ticket" text → skip, `ticket_image_path = null`. Reuses `WhatsAppProvider.download_media` + `LocalStorageBackend` untouched. |
| **"sin ticket" / skip path** | Not every cash purchase yields a retrievable ticket (kiosk, informal supplier) | LOW | Keyword match on "sin ticket", "no tengo", "sin comprobante" (case-insensitive) in `awaiting_ticket` state. Sets `ticket_image_path = null`, advances to `confirm`. |
| **Confirmation step before save** | Manager must see what will be written and approve; prevents garbage data landing silently | MEDIUM | State `confirm`: bot sends formatted summary using WhatsApp bold ("*queso* · Coto · *$1.500* · ticket ✓. ¿Confirmás? (sí / no / corregir)"). `sí` variants → write `Gasto` row → idle. |
| **Mid-flow correction at confirmation** | Manager realizes amount is wrong at the confirmation step | MEDIUM | "corregir" or "el monto está mal" at `confirm` → GPT identifies which slot to fix → state rewinds to the relevant `awaiting_X` state. Corrections loop back; code enforces re-confirmation before any write. |
| **"cancelar" global command** | Manager changes their mind; must exit cleanly without a dangling draft | LOW | Global keyword intercept ("cancelar", "cancel", "salir") checked before state machine logic at every inbound message. Clears `draft_gasto`, sets state to `idle`, sends "Cancelado. Escribime cuando quieras registrar un gasto." |
| **Sender allowlist gate** | Only registered managers should trigger the gastos flow | LOW | Reuses existing `SenderAllowlist` check from v1.0 verbatim. Same DB table, same CRUD — zero new code. |
| **Structured `Gasto` record persisted to DB** | The whole point — replaces the handwritten GASTOS sheet | MEDIUM | New `gastos` table: `id, fecha, concepto, lugar, salida (monto pagado), entrada (nullable), ticket_image_path, ticket_extraction (JSONB, nullable), sender_phone, status, created_at`. New `gasto.py` service mirrors `invoice.py` structure. |
| **Twice-daily proactive prompts (12:00 / 17:00)** | Managers forget to report; the bot must initiate — this is the primary adoption driver | HIGH | APScheduler in-process (`scheduler.py`). Jobs fire outbound messages via existing `WhatsAppProvider.send_message` — no new provider method needed. Config: `SCHEDULER_CAJA_TIMES`, TZ `America/Argentina/Buenos_Aires`. New dependency: `apscheduler`. |
| **Caja closing flow (efectivo en caja)** | Twice-daily cierre is the primary reconciliation event; must be captured at each scheduler prompt | MEDIUM | Scheduler fires → state `awaiting_caja_efectivo` → manager replies amount → writes `CajaCierre` row → bot follows up "¿Hiciste otra compra hoy?" → branches into gasto flow or back to `idle`. New `caja_cierres` table. |
| **Idempotency on WhatsApp webhook retries** | Meta Cloud API retries delivery if it doesn't receive 200 within ~20 seconds; duplicate processing creates double gastos or double cierres | MEDIUM | Guard on `wamid` (Meta's message ID) checked before entering the orchestrator. At low volume a small DB table or in-process LRU cache (bounded size) is sufficient. Write only happens after confirmation — no mid-flow duplication risk since state is persisted. |
| **Session timeout / stale conversation expiry** | Manager starts a gasto, gets interrupted, comes back next day; stale draft must not silently persist | LOW | On each inbound message, compare `conversations.updated_at` to now. If delta > threshold (default 4 hours, configurable as `CONVERSATION_TIMEOUT_HOURS`), send "Tu última consulta quedó sin terminar. ¿Querés retomar (sí) o empezar de nuevo (no)?" before continuing. |
| **WhatsApp routing: text vs. media discrimination** | Same webhook receives both message types; the orchestrator needs to know what arrived before routing | LOW | `gastos_whatsapp.py` router inspects `message.type` before calling orchestrator. Media in `idle` state is not a gasto trigger (gastos always start with text intent); media in `awaiting_ticket` → process as ticket. Prevents wrong-state media handling. Separate webhook path from v1.0 invoice handler. |

---

### Differentiators (Competitive Advantage)

Features that go beyond a basic slot-filling bot and make this genuinely useful vs. the handwritten sheet.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Cross-check declared monto vs. ticket total** | Catches transcription errors before the record is saved; replaces manual reconciliation by accountants | MEDIUM | After `extraction.py` runs on the ticket image, compare `ticket_extraction.total` to `draft_gasto.monto`. If delta > configurable threshold (e.g., 5%), bot warns: "El ticket dice $1.480, vos pusiste $1.500. ¿Cuál es correcto?" Manager resolves before confirmation. Directly reuses existing `ExtractedInvoice.total` field — no new extraction logic. Dependency: ticket photo step must be complete. |
| **"¿Hiciste otra compra hoy?" post-cierre nudge** | The moment after a cierre is the highest-signal moment to surface forgotten gastos; the prompt captures them before they fall through | LOW | After writing `CajaCierre`, bot sends one follow-up. "sí" → branch into gasto flow (orchestrator transitions from `idle`). "no" / no response within window → back to `idle`. Low complexity because state machine already handles both paths. |
| **Raw ticket extraction stored as JSONB for audit** | Accountants can verify what the AI saw on the ticket; supports dispute resolution without hunting for the original image | LOW | `gastos.ticket_extraction` JSONB column populated from `ExtractedInvoice.model_dump()`. No additional cost — extraction already runs for the cross-check. Zero new code beyond writing the column. |
| **Admin UI: gastos list + detail + edit views** | Accountants need to review, search, and correct captured gastos — same workflow as invoices | MEDIUM | Clone invoice list/detail/edit React pages into `/gastos` routes. Reuses TanStack Query patterns, existing filter bar component, edit form components verbatim. New backend endpoints: `GET /gastos`, `GET /gastos/{id}`, `PATCH /gastos/{id}`. |
| **Admin UI: cierres de caja list** | Managers and accountants need the cash-on-hand history for daily reconciliation | LOW | Read-only table: fecha, hora_cierre, efectivo_en_caja, sender_phone. Cierres are immutable once submitted — no edit needed. `GET /caja-cierres`. Minor frontend addition. |

---

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Free-form LLM agent with tool-calling for save** | Seems elegant — one model decides everything, no state machine code to maintain | LLM can call save with missing or hallucinated fields; skips required questions non-deterministically; flow becomes untestable and unauditable. OpenAI function-calling does not guarantee required fields are present before the tool is called. | Hybrid: GPT for intent/slot parsing (pure extraction); code owns all state transitions and the write gate. GPT never decides to save. |
| **Open-ended chit-chat / general assistant** | Managers might ask unrelated questions; feels friendlier | Out-of-scope messages grow conversation context, confuse state machine, create liability. This is a closed transactional tool — not an assistant. | Any message not parseable as gasto intent, slot reply, or known command in the current state → respond "Solo puedo ayudarte a registrar gastos o el cierre de caja. ¿Querés registrar un gasto?" Return to `idle`. |
| **In-memory message dedup set in production** | Simple — v1.0 already uses `_processed_message_sids` | Lost on any restart. At low volume this was tolerable for invoices, but a caja cierre written twice corrupts reconciliation figures irreversibly. | DB-backed `processed_message_ids` table (wamid + processed_at). Bounded by volume (< 20/day means < 40 rows/day). Negligible cost. |
| **Automatic save without confirmation step** | Fewer messages exchanged, faster UX | One typo or misparse silently writes garbage. Managers have no recourse without an edit flow inside the bot. Accountants lose trust in the dataset. | Always require explicit "sí" confirmation. Keep confirmation message concise and scannable using WhatsApp `*bold*` formatting. |
| **Real-time admin UI updates (WebSocket/SSE)** | Dashboard feels live | Adds WebSocket server, connection management, and reconnect logic for a workflow running at < 20 gastos/day. Complexity is not justified by value at this volume. | TanStack Query refetch-on-focus / manual refresh. Already the pattern from v1.0 admin UI. |
| **Per-slot infinite retry loop** | Seems like good UX to persist until the slot is filled | Can trap the manager in an infinite loop if they are confused or trying to use the wrong command. | Max 3 re-prompts per slot, then send a concrete example and offer to cancel ("Escribí 'cancelar' si querés salir"). Always honor "cancelar" globally before any retry logic. |
| **External cron + protected public endpoint for scheduler** | Separates scheduler from app process; survives independent restarts | Requires authenticated public URL, external scheduler service, secret management — all new infra for 2 jobs/day. Not justified. | APScheduler in-process. A missed prompt at restart is not catastrophic at this cadence. Document the upgrade path for v3 if deployment becomes multi-instance. |
| **Collecting manager FIRMA (signature) via WhatsApp** | The handwritten GASTOS sheet has a FIRMA column | WhatsApp does not support electronic signatures; asking for a signature field produces arbitrary text that has no legal value | `sender_phone` from the allowlist serves as the authenticated identity. The phone is the signature. |

---

## Feature Dependencies

```
[DB-backed conversation state]
    └── required by --> [Slot-filling follow-up questions]
    └── required by --> [Mid-flow correction]
    └── required by --> [Session timeout / expiry]
    └── required by --> [Cancelar command]
    └── required by --> [Caja closing flow]
    └── required by --> [Idempotency guard]

[Free-text intent parsing (Spanish)]
    └── required by --> [Slot-filling follow-up questions]

[Slot-filling follow-up questions]
    └── required by --> [Confirmation step before save]
                            └── required by --> [Structured Gasto record persisted]

[Ticket photo step]
    └── requires --> [v1.0 storage.py]         (reuse — untouched)
    └── requires --> [v1.0 extraction.py]       (reuse — untouched)
    └── required by --> [Cross-check monto vs. ticket total]

[Cross-check monto vs. ticket total]
    └── enhances --> [Confirmation step before save]

[Twice-daily proactive prompts]
    └── required by --> [Caja closing flow]
    └── requires --> [APScheduler in-process]
    └── requires --> [v1.0 WhatsAppProvider.send_message]  (reuse — untouched)

[Caja closing flow]
    └── triggers --> ["¿Hiciste otra compra hoy?" nudge]
                         └── branches into --> [Slot-filling follow-up questions]

[WhatsApp routing: text vs. media discrimination]
    └── required by --> [Ticket photo step]
    └── required by --> [Free-text intent parsing]

[Sender allowlist gate]
    └── requires --> [v1.0 SenderAllowlist table]  (reuse — untouched)
```

### Dependency Notes

- **DB-backed conversation state is the foundational dependency.** Every multi-turn feature requires it. Must be built and unit-tested in isolation (no WhatsApp needed) before any reactive flow is wired. This maps to Phase 1 of the v2.0 build sequence.
- **extraction.py and storage.py are reused untouched.** The ticket photo step gets its complexity almost for free — the only new code is calling those services from the `awaiting_ticket` state handler and writing the result to `gastos.ticket_extraction`.
- **Cross-check enhances confirmation, does not gate it.** If extraction fails on a ticket (illegible image, network timeout), skip the cross-check and proceed to confirmation without the delta warning. Never block the save on extraction failure.
- **Proactive scheduler and reactive webhook are independent entry points** that both funnel into the same orchestrator and state machine. The scheduler sets initial state to `awaiting_caja_efectivo`; the webhook continues the conversation. This means the scheduler can be built and tested after the core reactive flow is stable.
- **Idempotency guard wraps the orchestrator entry point**, not the write. Place it in `gastos_whatsapp.py` before any state is read or written. The confirmation step already prevents mid-flow double-writes; the guard stops double-entry into the flow itself.

---

## MVP Definition

### Launch With (v2.0)

Minimum needed to replace the handwritten GASTOS sheet and validate manager adoption.

- [ ] **DB-backed conversation state** — foundational; nothing persists without it
- [ ] **Free-text intent parsing (Spanish)** — managers must be able to start naturally
- [ ] **Slot-filling follow-up questions** — bot collects monto (and optionally lugar) when missing
- [ ] **Ticket photo step with "sin ticket" skip** — physical receipt captured or explicitly waived
- [ ] **Confirmation step before save** — data integrity; manager trust
- [ ] **"cancelar" global command** — non-negotiable exit path
- [ ] **Re-prompt on unparseable reply** — no silent failures allowed
- [ ] **Mid-flow correction at confirmation** — monto errors happen; fix without restart
- [ ] **Session timeout / expiry** — stale drafts from yesterday must not silently persist
- [ ] **Structured Gasto record + DB persistence** — the actual replacement for the GASTOS sheet
- [ ] **Twice-daily proactive prompts (12:00 / 17:00)** — without reminders, managers revert to forgetting
- [ ] **Caja closing flow** — cierre de caja is the primary daily reconciliation event
- [ ] **Idempotency on webhook retries** — duplicate cierres corrupt reconciliation figures
- [ ] **Sender allowlist gate** — security; zero new code (v1.0 reuse)
- [ ] **WhatsApp text vs. media routing** — infrastructure prerequisite for all flows
- [ ] **Admin UI: gastos list + detail + edit** — accountants need visibility on day one
- [ ] **Admin UI: cierres list** — reconciliation requires a view of the closing history

### Add After Validation (v2.x)

- [ ] **Cross-check declared monto vs. ticket total** — high value once adoption is confirmed; adds a GPT call per ticket so validate volume before enabling
- [ ] **"¿Hiciste otra compra hoy?" post-cierre nudge** — add when managers are comfortable with the cierre flow; requires cierre flow to be stable first
- [ ] **Raw ticket extraction stored as JSONB** — can be backfilled; low effort but not blocking launch

### Future Consideration (v3+)

- [ ] **Weekly/monthly gasto summaries via WhatsApp** — defer until there are 2+ weeks of records to summarize meaningfully
- [ ] **Supabase Auth for admin UI** — deferred from v1.0, still deferred; add when app is exposed beyond localhost demo
- [ ] **External scheduler (cron → protected endpoint)** — upgrade from APScheduler only if deployment becomes multi-instance or restart reliability becomes a problem

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| DB-backed conversation state | HIGH | HIGH | P1 |
| Free-text intent parsing (Spanish) | HIGH | MEDIUM | P1 |
| Slot-filling follow-up questions | HIGH | MEDIUM | P1 |
| Ticket photo step | HIGH | LOW (reuses extraction.py) | P1 |
| Confirmation step before save | HIGH | MEDIUM | P1 |
| Cancelar command | HIGH | LOW | P1 |
| Re-prompt on unparseable reply | HIGH | LOW | P1 |
| Mid-flow correction | MEDIUM | MEDIUM | P1 |
| Session timeout / expiry | MEDIUM | LOW | P1 |
| Structured Gasto record persistence | HIGH | MEDIUM | P1 |
| Twice-daily proactive prompts | HIGH | HIGH | P1 |
| Caja closing flow | HIGH | MEDIUM | P1 |
| Idempotency on webhook retries | HIGH | LOW | P1 |
| WhatsApp text vs. media routing | HIGH | LOW | P1 |
| Sender allowlist gate | HIGH | LOW (v1.0 reuse) | P1 |
| Admin UI: gastos list + detail + edit | HIGH | MEDIUM (clone invoice UI) | P1 |
| Admin UI: cierres list | MEDIUM | LOW | P1 |
| Cross-check monto vs. ticket total | HIGH | MEDIUM | P2 |
| "¿Hiciste otra compra hoy?" nudge | MEDIUM | LOW | P2 |
| Raw ticket extraction as JSONB | LOW | LOW | P2 |
| Supabase Auth for admin UI | MEDIUM | MEDIUM | P3 |
| Weekly/monthly WhatsApp summaries | MEDIUM | MEDIUM | P3 |
| External scheduler | LOW | HIGH | P3 |

**Priority key:**
- P1: Must have for v2.0 launch
- P2: Add post-validation (v2.x patch)
- P3: Defer to v3+

---

## Competitor Feature Analysis

No direct competitors — this is a bespoke internal tool replacing a handwritten sheet. Reference patterns from analogous domains:

| Feature | Generic slot-filling bots (e.g., food ordering) | Expense apps (Fyle, Expensify) | Our Approach |
|---------|-----------------------------------------------|-------------------------------|--------------|
| Conversation initiation | User-initiated only | App push notification | Both: reactive (manager texts intent) + proactive (12:00/17:00 APScheduler) |
| Confirmation before save | Varies — often none | Mobile UI confirmation screen | Always — explicit "¿Confirmás?" before any write |
| Free-text language | Usually English or structured commands | Form fields, not conversational | Spanish free-text → GPT slot extraction → deterministic state machine |
| Receipt capture | Not common in transactional bots | Mobile photo upload in-app | WhatsApp media message → reuse v1.0 extraction pipeline |
| Amount verification | None | OCR cross-check in premium tiers | Cross-check declared amount vs. ticket total via existing GPT extraction (P2) |
| Audit trail | None | Full audit log | Ticket image + raw extraction JSON stored alongside every gasto |
| FIRMA / identity | N/A | User account | `sender_phone` from allowlist is the authenticated identity; no separate signature needed |

---

## Sources

- Approved design document: `docs/plans/2026-05-27-gastos-bot-design.md` (HIGH confidence — first-party approved design)
- v1.0 codebase reuse map from design doc (HIGH confidence — verified against four shipped phases)
- Hybrid LLM + deterministic state machine pattern: design doc rationale section; standard industry approach for transactional WhatsApp bots where write correctness is required
- APScheduler in-process for low-frequency jobs in FastAPI: established pattern, documented in APScheduler 3.x/4.x; sufficient at 2 jobs/day
- Argentine GASTOS sheet columns (FECHA, OBSERVACION, ENTRADA, SALIDA, FIRMA): from design doc / client context

---

*Feature research for: v2.0 Gastos Bot — conversational WhatsApp expense capture + cierres de caja (Argentine restaurant)*
*Researched: 2026-05-27*
