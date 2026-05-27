# Gastos Bot — Design (Milestone v2.0)

**Date:** 2026-05-27
**Status:** Approved design, ready for roadmap
**Builds on:** Milestone v1.0 (invoice-capture system, 4 phases shipped)

> **Demo-build amendment (2026-05-27):** This is a demo, not production. The
> time-based **proactive scheduler (APScheduler) described below is dropped** and
> replaced by a **manual prompt-trigger endpoint** (`POST /gastos/prompt`) that fires
> the prompt on demand during a demo. Because the recipient has just messaged the bot,
> the WhatsApp 24h customer-service window is open, so **no Utility message template is
> needed**. The real scheduler + template are the deferred production path. See
> `.planning/REQUIREMENTS.md` (TRIG-01/02) and `.planning/ROADMAP.md` Phase 3, which
> are the authoritative source for planning. Sections B and "Build sequence" below are
> retained for production context only.

## Problem

Restaurant managers pay cash for ad-hoc merchandise (milk, ice, vegetables, etc.)
out of the register and currently record those payments by hand on a "GASTOS" sheet.
They forget to record them. The cash-on-hand never reconciles.

## Goal

A conversational WhatsApp bot that:

1. **Proactively** prompts each manager twice a day (12:00 and 17:00) to record
   pending payments and report cash left in the register (for the cierres).
2. **Captures payments conversationally**: manager texts an intent
   ("Pago de queso en supermercado") → bot asks the follow-ups it needs → asks for
   a photo of the ticket → saves a structured *gasto* record + a reference to the
   ticket image.

This is a distinct behavior from v1.0's invoice capture, which was one-shot and
purely reactive (photo in → extract → done). v2.0 adds **multi-turn conversation
state** and **proactive scheduled outreach**.

## Scope

- Single-company / single-restaurant deployment (consistent with v1.0).
- Spanish (Argentina) UX.
- Cash expenses (gastos) + twice-daily cash closings (cierres de caja).

Out of scope for v2.0: multi-restaurant, accounting integrations, tax logic.

## Reuse vs. Recreate map

### Reuse almost as-is

- **Docker / Compose / Postgres / Alembic** — add migrations for new tables only.
- **`app/main.py` app factory** — register one new router; start/stop the scheduler.
- **`app/providers/` (WhatsAppProvider + Twilio/Meta)** — `send_message`,
  `download_media`, `validate_signature` carry over untouched. The same
  `send_message` now also serves proactive outbound — no new method needed.
- **`app/services/storage.py`** — stores the ticket photo as it stores invoice
  images today.
- **`app/config.py` settings pattern** and **`SenderAllowlist`** model + allowlist gate.
- **`app/services/extraction.py`** — the GPT-4o vision mechanism is reusable. The
  ticket photo (a Factura B) maps cleanly onto the existing `ExtractedInvoice`
  schema (total, proveedor, fecha, CAE, items). High reuse — called on the ticket step.
- **Frontend admin shell** (React/Vite list→detail→edit) — clone invoice views into
  Gastos views.

### Recreate / build new

1. **Conversation state** — DB-backed session per sender (multi-turn; manager may
   reply hours later). The in-memory `_processed_message_sids` set won't do.
2. **Conversation orchestrator service** — decides next question / when to persist.
3. **New webhook routing** — today's handler is hardwired "media → extract → save";
   the gastos flow needs text-vs-media routing into the orchestrator.
4. **New DB models** — `Gasto`, `CajaCierre`, `Conversation`.
5. **Scheduler** — twice-daily proactive prompts. New; v1.0 was purely reactive.
6. **New admin UI views** for gastos + caja closings.

## Architecture choices

### A. Conversation engine — Hybrid (LLM intent + code control)

GPT parses free Spanish text into intent + slots; a deterministic state machine
drives required questions and the save. Code decides when to persist — GPT never
"decides" to save. Chosen over a pure LLM function-calling agent (can skip required
fields / save prematurely) and a pure scripted machine (brittle on free-form input).

### B. Scheduler — APScheduler in-process

Twice-daily jobs (12:00, 17:00) fire outbound WhatsApp prompts to each active
manager, inside the existing Uvicorn process — zero new infra. A missed prompt
isn't catastrophic at ~2 jobs/day. (Upgrade path: external cron → protected endpoint.)

### C. Conversation state — DB-backed (required)

A `conversations` row per sender holds current state + the partial gasto being
assembled. Must survive restarts and hours-long reply gaps.

These lock together: the hybrid engine reads/writes the DB-backed state; the
scheduler kicks off conversations the same engine then drives.

## Conversation flow (state machine)

Each inbound message loads the sender's `Conversation` row, runs the orchestrator,
updates state.

```
idle
 │  manager texts free-form intent ("Pago de queso en supermercado")
 │  → GPT extracts slots: {concepto: "queso", lugar: "supermercado", monto: null}
 ▼
awaiting_monto        bot: "¿Cuánto pagaste?"        → fills monto
 ▼
awaiting_ticket       bot: "Mandame una foto del ticket (o escribí 'sin ticket')"
 │   ├─ photo  → extraction.py on the Factura B → stores image + cross-checks total
 │   └─ "sin ticket" → skip
 ▼
confirm               bot: "Registro: queso · supermercado · $X · {ticket✓}. ¿Confirmás?"
 │   ├─ sí → write Gasto row, state → idle, "✅ Registrado"
 │   └─ corrections → loop back to the relevant slot
 ▼
idle
```

Scheduler-initiated flows reuse the same machine:

- **12:00 & 17:00** → `awaiting_caja_count`: "¿Cuánto efectivo queda en caja?" →
  writes `CajaCierre`, then asks "¿Hiciste otra compra hoy?" → branches into the
  gasto flow or back to `idle`.

GPT does slot-extraction on free text only; **code** owns transitions and the write.
Any unparseable reply → bot re-asks the current slot (no silent failures).

## Data model (new tables)

**`gastos`** — mirrors the handwritten GASTOS sheet:
`id, fecha, concepto (observación), lugar/proveedor, salida (monto pagado),
entrada (nullable), ticket_image_path (nullable), ticket_extraction (JSON, nullable),
sender_phone, status, created_at`

**`caja_cierres`** — the twice-daily closings:
`id, fecha, hora_cierre (12:00/17:00), efectivo_en_caja, sender_phone, created_at`

**`conversations`** — per-sender state:
`sender_phone (unique), state, draft_gasto (JSON — partial slots), updated_at`

Reused unchanged: `sender_allowlist`. The ticket photo flows through the existing
`LocalStorageBackend` + `extraction.py`; `ticket_extraction` stores its JSON for
audit and to cross-check the declared `salida` against the ticket total.

## Build sequence

### Files touched vs. net-new

**Modify (surgical):**
- `app/main.py` — register `gastos` router; start/stop APScheduler in lifespan.
- `app/db/models.py` — add `Gasto`, `CajaCierre`, `Conversation`.
- `requirements.txt` — add `apscheduler`.
- `app/config.py` — scheduler times + timezone (`America/Argentina/Buenos_Aires`).

**Net-new backend:**
- `app/routers/gastos_whatsapp.py` — webhook entry routing text vs. media into the
  orchestrator (separate webhook path preferred over branching the existing one).
- `app/services/conversation.py` — orchestrator (load state → next action → persist).
- `app/services/slot_extraction.py` — GPT free-text → `{concepto, lugar, monto}`.
- `app/services/gasto.py` — persistence (like `invoice.py`).
- `app/services/scheduler.py` — APScheduler jobs firing the 12:00/17:00 prompts.
- Alembic migration for the three tables.

**Reused untouched:** `providers/`, `services/storage.py`, `services/extraction.py`,
`SenderAllowlist`, settings pattern.

**Frontend:** clone invoice list/detail into Gastos + a Cierres view.

### Phase breakdown (v2.0 roadmap)

1. **Data + conversation core** — models, migration, `Conversation` state,
   orchestrator, slot extraction. Unit-testable with no WhatsApp.
2. **WhatsApp gastos flow** — webhook routing + ticket photo through `extraction.py`;
   full reactive capture working end-to-end.
3. **Proactive scheduler** — APScheduler 12:00/17:00 prompts + caja closing flow.
4. **Admin UI** — Gastos + Cierres views.
