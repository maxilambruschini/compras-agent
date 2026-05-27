# Architecture Patterns

**Domain:** WhatsApp-to-database invoice capture + conversational expense bot (Argentine AFIP)
**Researched:** 2026-05-27 (updated from 2026-05-12 v1.0 baseline)
**Confidence:** HIGH — derived from actual codebase inspection + approved design doc

---

## System Overview

```
WhatsApp Provider (Twilio / Meta Cloud API)
         │
         │ POST /whatsapp/webhook       POST /gastos/webhook
         │ (existing — media only)      (new — text + media)
         ▼                              ▼
┌────────────────────────────────────────────────────────────────┐
│  FastAPI Application (create_app + lifespan)                   │
│                                                                │
│  Existing Router              New Router                       │
│  ┌──────────────────┐        ┌──────────────────────────────┐  │
│  │ /whatsapp/webhook│        │ /gastos/webhook              │  │
│  │ (media → extract │        │ text-vs-media dispatch       │  │
│  │  → invoice save) │        │ → ConversationOrchestrator   │  │
│  └──────────────────┘        └──────────────────┬───────────┘  │
│           │                                     │              │
│           ▼                                     ▼              │
│  ┌──────────────────┐        ┌──────────────────────────────┐  │
│  │  ExtractionService│       │  ConversationOrchestrator    │  │
│  │  (GPT-4o vision) │◀───────│  load Conversation row       │  │
│  │  LocalStorageBack│        │  → state dispatch            │  │
│  └──────────────────┘        │  → SlotExtractionService     │  │
│                              │  → ExtractionService (ticket)│  │
│                              │  → GastoService (persist)    │  │
│                              │  → WhatsAppProvider (reply)  │  │
│                              └──────────────────────────────┘  │
│                                                                │
│  Scheduler (APScheduler, in-process)                           │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 12:00 + 17:00 jobs                                      │   │
│  │ → query active SenderAllowlist rows                     │   │
│  │ → send proactive prompt via WhatsAppProvider            │   │
│  │ → upsert Conversation row to awaiting_caja_count state  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                │
│  Admin API (existing /api/invoices + new /api/gastos,          │
│             /api/cierres)                                      │
└────────────────────────────────────────────────────────────────┘
         │ async SQLAlchemy ORM (asyncpg)
         ▼
┌────────────────────────────────────────────────────────────────┐
│  Postgres (Docker)                                             │
│  ├── invoices / invoice_line_items  (v1.0 unchanged)          │
│  ├── sender_allowlist               (v1.0 unchanged)          │
│  ├── conversations   (NEW — per-sender state + draft slots)   │
│  ├── gastos          (NEW — committed expense records)        │
│  └── caja_cierres    (NEW — twice-daily cash closings)        │
└────────────────────────────────────────────────────────────────┘
         ▲ React/Vite Admin UI (existing + new Gastos/Cierres views)
```

---

## (a) Webhook Routing — Separate Path vs Branch

**Decision: Separate router at `/gastos/webhook`, registered alongside the existing `/whatsapp/webhook`.**

Rationale derived from reading `backend/app/routers/whatsapp.py`:

The existing handler has a hardwired media gate (step 5 — returns D-11 and exits if `NumMedia == 0`). Branching the gastos conversation flow into it would require removing that gate for allowlisted gastos senders while preserving it for invoice senders — two different behavioral contracts in one function. That adds fragile conditional logic to a security-sensitive handler.

The cleaner split:

```
POST /whatsapp/webhook   → existing handler, unchanged
                           media-only, invoice pipeline
                           uses WHATSAPP_PROVIDER env var
                           idempotency: _processed_message_sids (in-memory, acceptable)

POST /gastos/webhook     → new handler in app/routers/gastos_whatsapp.py
                           accepts text AND media
                           routes into ConversationOrchestrator
                           idempotency: Conversation.last_message_id column (DB-backed)
```

Both routers share the same `get_whatsapp_provider` dependency factory (already in `whatsapp.py`) and the same `validate_signature` call pattern. The gastos router imports `get_whatsapp_provider` from `app.routers.whatsapp` — no duplication of the factory.

**Registration in `app/main.py`:**

```python
from app.routers.gastos_whatsapp import router as gastos_wa_router
app.include_router(gastos_wa_router, prefix="/gastos", tags=["gastos"])
```

**Text-vs-media dispatch inside `/gastos/webhook`:**

```
POST /gastos/webhook receives form fields (same Twilio/Meta shape):
  NumMedia, MediaUrl0, MediaContentType0, Body, From, MessageSid

Dispatch logic (inside the handler, before background task):
  if NumMedia > 0 and MediaUrl0 is not None:
      → route as "media" message to orchestrator
  else:
      → route as "text" message to orchestrator (Body field)

Both branches call:
  asyncio.create_task(
      orchestrator.handle_message(
          sender=From,
          message_type="media"|"text",
          body=Body,          # text branch
          media_url=MediaUrl0, # media branch
          media_content_type=MediaContentType0,
          message_id=MessageSid,
      )
  )
```

The orchestrator, not the router, decides what to do with media vs text given the current conversation state (e.g., media in `awaiting_ticket` state triggers extraction; media in `idle` state triggers a "please send text first" reply).

---

## (b) Conversation State Machine

### States and Transitions

```
idle
 │  inbound text (intent detected by SlotExtractionService)
 │  slots: {concepto, lugar, monto} — partial OK at this step
 ▼
awaiting_monto          if monto was missing from initial text
 │  inbound text → SlotExtractionService extracts monto
 ▼
awaiting_ticket
 │  ├─ inbound media → ExtractionService (GPT-4o on Factura B)
 │   │  stores image via LocalStorageBackend
 │   │  cross-checks ticket total vs draft monto
 │   └─ inbound text "sin ticket" → skip photo step
 ▼
confirm                 bot sends summary, awaits sí/no/correction
 │  ├─ "sí" → GastoService.save() → state = idle → "✅ Registrado"
 │  └─ correction text → SlotExtractionService re-extracts
 │     → update draft_gasto → re-enter confirm (or back to awaiting_X)
 ▼
idle

--- Scheduler-initiated branch ---
idle  (or any non-terminal state — scheduler interrupts politely)
 │  APScheduler fires 12:00 / 17:00 job
 │  → send proactive prompt via WhatsAppProvider.send_message()
 │  → upsert Conversation row: state = awaiting_caja_count
 ▼
awaiting_caja_count     bot: "¿Cuánto efectivo queda en caja?"
 │  inbound text → SlotExtractionService extracts monto
 │  → GastoService.save_caja_cierre()
 ▼
awaiting_more_gastos    bot: "¿Hiciste alguna compra hoy?"
 │  ├─ sí / intent detected → state = awaiting_monto (enter gasto flow)
 │  └─ no → state = idle
 ▼
idle
```

### Where Draft Slots Live

The `conversations` table row is the single source of truth for in-progress state. The `draft_gasto` column is a JSON object holding partial slot values:

```json
{
  "concepto": "queso",
  "lugar": "supermercado",
  "monto": null,
  "ticket_image_path": null,
  "ticket_extraction": null
}
```

`draft_gasto` is written after every turn. When the orchestrator moves to `idle` and calls `GastoService.save()`, it reads from `draft_gasto`, writes the `gastos` row, then nulls out `draft_gasto`.

### ORM Model: `conversations` table

```python
class Conversation(Base):
    __tablename__ = "conversations"

    sender_phone: Mapped[str] = mapped_column(String(30), primary_key=True)
    # Current state name — matches the state machine string literals
    state: Mapped[str] = mapped_column(String(50), nullable=False, default="idle")
    # Partial gasto being assembled (JSON). Null when state == idle.
    draft_gasto: Mapped[Optional[str]] = mapped_column(Text)  # JSON dump
    # Last processed MessageSid — DB-backed idempotency gate (replaces in-memory set)
    last_message_id: Mapped[Optional[str]] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

### Concurrency and Locking on the Per-Sender Row

WhatsApp Cloud API can deliver duplicate webhook POSTs for the same message (retry on 200 not received fast enough). The existing handler uses an in-memory `_processed_message_sids` set. For multi-turn state, this is insufficient because:

1. The set is cleared on restart.
2. Two concurrent deliveries of the same message could both load `state=awaiting_monto`, both run `SlotExtractionService`, and both attempt to advance state — producing a double transition.

**Solution: `SELECT ... FOR UPDATE` on the `Conversation` row.**

The `ConversationOrchestrator.handle_message()` opens an async DB session and immediately issues a row-level lock:

```python
async with session.begin():
    result = await session.execute(
        select(Conversation)
        .where(Conversation.sender_phone == sender)
        .with_for_update()          # row-level lock; second concurrent call blocks
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        conv = Conversation(sender_phone=sender, state="idle")
        session.add(conv)
        await session.flush()       # assigns the row before proceeding

    # DB-backed idempotency gate (replaces _processed_message_sids)
    if conv.last_message_id == message_id:
        return                      # already processed — release lock and exit

    conv.last_message_id = message_id
    # ... run state machine logic ...
    # ... commit releases the lock ...
```

This guarantees serialized processing per sender. Two parallel deliveries: the first acquires the lock, processes, commits, releases. The second acquires the lock, sees `last_message_id` matches, exits. No double transition.

The `SELECT ... FOR UPDATE` lock scope is per row (`sender_phone`), so two different senders never block each other — the low-volume constraint (< 20/day) means lock contention is not a concern.

**Important:** The orchestrator must open its own session via `get_async_session_local()` (same pattern as `process_invoice` in the existing handler) because it runs inside `asyncio.create_task`, outside FastAPI's request lifecycle dependency injection.

---

## (c) Scheduler Integration with FastAPI Lifespan

### APScheduler Wiring

APScheduler's `AsyncScheduler` (from `apscheduler` 4.x) integrates cleanly with FastAPI's `asynccontextmanager` lifespan. The scheduler is started on startup and stopped on shutdown in `app/main.py`:

```python
from contextlib import asynccontextmanager
from apscheduler import AsyncScheduler
from apscheduler.triggers.cron import CronTrigger

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    log.info("app.starting", log_level=settings.log_level)

    # Start scheduler
    from app.services.scheduler import send_proactive_prompts
    scheduler = AsyncScheduler()
    async with scheduler:
        scheduler.add_schedule(
            send_proactive_prompts,
            CronTrigger(hour=12, minute=0, timezone="America/Argentina/Buenos_Aires"),
            id="prompt_noon",
        )
        scheduler.add_schedule(
            send_proactive_prompts,
            CronTrigger(hour=17, minute=0, timezone="America/Argentina/Buenos_Aires"),
            id="prompt_evening",
        )
        await scheduler.start_in_background()
        yield
        # Shutdown: scheduler context manager handles cleanup
        await scheduler.stop()

    # Dispose DB engine (existing pattern)
    from app.db.engine import _engine as _db_engine
    if _db_engine is not None:
        await _db_engine.dispose()
    log.info("app.stopped")
```

Note: APScheduler 3.x uses `BackgroundScheduler` (sync) or `AsyncIOScheduler`. APScheduler 4.x uses `AsyncScheduler` with `async with`. Confirm the installed major version in `requirements.txt` before wiring — the API differs substantially. The design doc says "add `apscheduler`" without pinning; pin to `apscheduler>=4.0` for the async-native API.

### What the Job Function Does

`app/services/scheduler.py` — `send_proactive_prompts()`:

```
1. Open async DB session via get_async_session_local()
2. SELECT phone_number FROM sender_allowlist WHERE is_active = true
   (reuses existing SenderAllowlist model — no new query needed)
3. For each active sender:
   a. Send proactive WhatsApp message via WhatsAppProvider.send_message()
      (constructs provider via settings — same factory as get_whatsapp_provider)
   b. Upsert Conversation row: state = awaiting_caja_count, draft_gasto = null
      INSERT ... ON CONFLICT (sender_phone) DO UPDATE SET state=..., updated_at=...
      This is safe because the scheduler does not hold a FOR UPDATE lock —
      it is only setting state, not reading-then-writing draft slots.
4. Log completion; swallow per-sender errors so one failed send doesn't abort the batch.
```

The scheduler job constructs its own `WhatsAppProvider` instance directly from settings (no FastAPI `Depends()`), mirroring the pattern in `process_invoice` that constructs `ExtractionService` inside the background task.

### Missed Fire Behavior

At twice daily, a missed prompt (process restart at exactly 12:00) is not catastrophic — the manager simply doesn't get that proactive ping. No recovery mechanism needed for v2.0. The `misfire_grace_time` APScheduler setting can be set to 5 minutes so the job fires if the process comes back up within 5 minutes of the scheduled time.

### What Happens on Restart with Active Conversations

The `Conversation` row in Postgres survives restarts. A manager mid-conversation at `awaiting_monto` who sends a reply after a restart will load their `Conversation` row, find `state=awaiting_monto`, and the orchestrator will continue correctly. The only loss is the in-memory `_background_tasks` set (tasks killed mid-flight), but those are covered by the DB-backed `last_message_id` idempotency gate.

---

## (d) Ticket Photo Step — Reusing ExtractionService + LocalStorageBackend

The existing `ExtractionService` and `LocalStorageBackend` are called from the `process_invoice` background task today. For the gastos ticket step, the same services are called from inside `ConversationOrchestrator.handle_message()` when `state == awaiting_ticket` and message type is `media`.

**Reuse path (no changes to ExtractionService or LocalStorageBackend):**

```python
# Inside ConversationOrchestrator, awaiting_ticket + media branch:

from app.services.extraction import ExtractionService, ExtractionResult
from app.services.storage import LocalStorageBackend
from openai import AsyncOpenAI

settings = get_settings()
extraction_service = ExtractionService(
    openai_client=AsyncOpenAI(api_key=settings.openai_api_key),
    storage=LocalStorageBackend(root=settings.storage_path),
    settings=settings,
)

# Download media bytes via provider (same as process_invoice does)
image_bytes = await provider.download_media(media_url)

# Reuse magic-byte validation from whatsapp.py
if not _validate_image_bytes(image_bytes):
    await provider.send_message(sender, "❌ No pude leer la imagen del ticket.")
    return  # stay in awaiting_ticket state, let manager retry

filename = f"ticket_{message_id}.jpg"
result: ExtractionResult = await extraction_service.extract(image_bytes, filename)

# result.invoice.total → cross-check against draft_gasto["monto"]
# result.invoice → store as JSON in draft_gasto["ticket_extraction"]
# The image path written by LocalStorageBackend is in result (or derivable from filename)
```

**Cross-check logic:** If `abs(ticket_total - declared_monto) / declared_monto > 0.05` (5% tolerance), the bot flags the discrepancy and asks the manager to confirm or correct. This is new logic in the orchestrator — not in `ExtractionService`.

**What the Gasto row stores:**

```
ticket_image_path    → the path LocalStorageBackend wrote (same as Invoice.image_path pattern)
ticket_extraction    → JSON dump of ExtractedInvoice (for audit; same as Invoice.raw_extraction)
```

The `ExtractedInvoice` Pydantic schema maps cleanly to a Factura B (the ticket type managers photograph), so no schema changes to `ExtractionService` are needed.

---

## (e) New vs Modified Components and Build Order

### Component Map

| Status | File | Change |
|--------|------|--------|
| **Modify** | `backend/app/main.py` | Add scheduler start/stop to `lifespan`; register `gastos_whatsapp` router |
| **Modify** | `backend/app/db/models.py` | Add `Gasto`, `CajaCierre`, `Conversation` ORM classes |
| **Modify** | `backend/app/config.py` | Add `scheduler_timezone`, optional `scheduler_noon_hour`/`scheduler_evening_hour` settings |
| **Modify** | `backend/requirements.txt` | Add `apscheduler>=4.0` |
| **New** | `backend/app/routers/gastos_whatsapp.py` | Webhook handler for gastos: signature validation, allowlist gate, text/media dispatch, asyncio.create_task |
| **New** | `backend/app/services/conversation.py` | `ConversationOrchestrator` — loads state, dispatches to sub-handlers, owns state transitions |
| **New** | `backend/app/services/slot_extraction.py` | `SlotExtractionService` — GPT-4o call on free Spanish text → `{concepto, lugar, monto}` Pydantic model |
| **New** | `backend/app/services/gasto.py` | `GastoService` — `save_gasto()`, `save_caja_cierre()`, query methods for admin API |
| **New** | `backend/app/services/scheduler.py` | APScheduler job function + WhatsAppProvider construction |
| **New** | `backend/app/routers/gastos_admin.py` | Admin CRUD for `/api/gastos` and `/api/cierres` |
| **New** | `backend/migrations/versions/xxxx_add_gastos_tables.py` | Alembic migration for `gastos`, `caja_cierres`, `conversations` |
| **New** | `frontend/src/pages/GastosPage.tsx` | Admin list view for gastos |
| **New** | `frontend/src/pages/CierresPage.tsx` | Admin list view for caja closings |
| **Untouched** | `backend/app/routers/whatsapp.py` | No changes — invoice pipeline unchanged |
| **Untouched** | `backend/app/providers/` | No changes — `WhatsAppProvider` Protocol already supports `send_message` for outbound |
| **Untouched** | `backend/app/services/extraction.py` | No changes — called as-is from orchestrator |
| **Untouched** | `backend/app/services/storage.py` | No changes — `LocalStorageBackend` called as-is |
| **Untouched** | `backend/app/services/invoice.py` | No changes |
| **Untouched** | `backend/app/db/engine.py` | No changes — `get_async_session_local()` reused in orchestrator and scheduler |

### Build Order (Dependency-Respecting)

```
Phase 1 — Data + conversation core
  Step 1: Add Gasto, CajaCierre, Conversation to models.py
  Step 2: Write and run Alembic migration
  Step 3: Write SlotExtractionService (GPT-4o text → slots, unit-testable alone)
  Step 4: Write GastoService (persistence, testable with SQLite via existing test pattern)
  Step 5: Write ConversationOrchestrator (depends on SlotExtractionService + GastoService)
          Test all state transitions with mocked provider and mocked extraction
          → No WhatsApp, no scheduler needed yet. Full unit test coverage possible.

Phase 2 — WhatsApp gastos flow
  Step 6: Write gastos_whatsapp.py router
          Wire: signature validation (copy pattern from existing router),
          allowlist gate (reuse SenderAllowlist query),
          text/media dispatch, asyncio.create_task(orchestrator.handle_message)
  Step 7: Register router in main.py (prefix="/gastos")
  Step 8: Integration test: full reactive gasto capture end-to-end
          (text intent → monto question → ticket photo → confirm → save)
          → Depends on Phase 1 complete

Phase 3 — Proactive scheduler
  Step 9:  Write scheduler.py job function
  Step 10: Wire APScheduler into lifespan in main.py
  Step 11: Test: mock the clock, verify proactive prompt is sent to active senders
           and Conversation row is upserted to awaiting_caja_count
  Step 12: Test caja closing flow end-to-end (scheduler → caja → optional gasto → idle)
           → Depends on Phase 2 (WhatsApp send) + Phase 1 (Conversation row)

Phase 4 — Admin UI
  Step 13: Write gastos_admin.py router (list + detail endpoints)
  Step 14: Add /api/gastos and /api/cierres to React routing + list pages
           → Clone invoice list pattern; minimal new logic
```

---

## Architectural Patterns

### Pattern 1: Row-Level Lock for Per-Sender Serialization

**What:** `SELECT ... FOR UPDATE` on the `Conversation` row at the start of every orchestrator call.
**When to use:** Any time a webhook handler must read-modify-write a single DB row and duplicate delivery is possible.
**Trade-offs:** Simple, no external dependencies. Requires that the entire orchestrator logic runs within a single transaction. At <20 messages/day, no contention risk.

### Pattern 2: Services Constructed Inside Background Tasks

**What:** `ExtractionService`, `WhatsAppProvider`, and DB sessions are instantiated inside `asyncio.create_task` closures, not injected via FastAPI `Depends()`.
**When to use:** Always, for background tasks. FastAPI's dependency injection lifecycle ends when the request returns — background tasks run after that and cannot use request-scoped dependencies.
**Trade-offs:** Slightly more verbose (no DI magic). Consistent with existing `process_invoice` pattern. Easy to test by passing mock instances directly.

### Pattern 3: Hybrid State Machine (GPT Slots + Code Transitions)

**What:** `SlotExtractionService` extracts intent and slot values from free Spanish text. `ConversationOrchestrator` owns all state transitions and persistence decisions. GPT never "decides" to save.
**When to use:** Any conversational flow where required fields must be collected reliably and business rules (e.g., "always require monto before saving") must be enforced.
**Trade-offs:** More code than pure LLM agent. Much more reliable and testable — every transition is a deterministic code path.

### Pattern 4: Protocol-Based Provider Abstraction for Outbound

**What:** `WhatsAppProvider.send_message()` is the only method the scheduler and orchestrator use for outbound. The same Protocol works for Twilio and Meta — no conditional branching in business logic.
**When to use:** Already established in v1.0. Scheduler and orchestrator must import from `app.providers.base` and construct via the same factory, not import `TwilioProvider` directly.

---

## Data Flow

### Reactive Gasto Capture (Happy Path)

```
Manager texts "Pago de queso 800 pesos en super"
    ↓
POST /gastos/webhook (Twilio/Meta)
    ↓
gastos_whatsapp.py: signature validation → allowlist check → dispatch
    ↓
asyncio.create_task(orchestrator.handle_message(type="text", body=...))
    ↓
ConversationOrchestrator:
  SELECT conversations WHERE sender_phone = X FOR UPDATE
  state == "idle" → call SlotExtractionService("Pago de queso 800 pesos en super")
  → {concepto: "queso", lugar: "super", monto: 800}
  all slots filled → state = "awaiting_ticket", save draft_gasto
  send: "Mandame una foto del ticket (o escribí 'sin ticket')"
    ↓
Manager sends photo
    ↓
POST /gastos/webhook
    ↓
orchestrator: state == "awaiting_ticket" + media
  → download_media → validate_image_bytes
  → ExtractionService.extract(image_bytes, filename)  ← reused unchanged
  → cross-check ticket total vs draft_gasto.monto
  → state = "confirm", update draft_gasto with ticket_image_path
  send: "Registro: queso · super · $800 · ticket✓. ¿Confirmás?"
    ↓
Manager texts "sí"
    ↓
POST /gastos/webhook
    ↓
orchestrator: state == "confirm"
  → SlotExtractionService detects confirmation intent
  → GastoService.save_gasto(draft_gasto) → INSERT gastos row
  → state = "idle", draft_gasto = null
  send: "✅ Registrado"
```

### Proactive Scheduler Flow

```
APScheduler fires (12:00 ART)
    ↓
scheduler.send_proactive_prompts()
  → SELECT phone_number FROM sender_allowlist WHERE is_active
  → For each sender:
       WhatsAppProvider.send_message(sender, "¿Cuánto efectivo queda en caja?")
       INSERT INTO conversations (sender_phone, state) VALUES (X, "awaiting_caja_count")
       ON CONFLICT (sender_phone) DO UPDATE SET state = "awaiting_caja_count", updated_at = now()
    ↓
Manager replies with amount
    ↓
POST /gastos/webhook (normal reactive path)
    ↓
orchestrator: state == "awaiting_caja_count"
  → SlotExtractionService extracts monto
  → GastoService.save_caja_cierre(sender, hora="12:00", efectivo=monto)
  → state = "awaiting_more_gastos"
  send: "¿Hiciste alguna compra hoy?"
```

---

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| WhatsApp (Twilio/Meta) | `WhatsAppProvider.send_message()` — same Protocol for inbound and outbound | Scheduler constructs provider from settings directly (no DI) |
| OpenAI GPT-4o | `ExtractionService` (image→slots) + new `SlotExtractionService` (text→slots) | Two separate callers; same openai client pattern |
| APScheduler | `AsyncScheduler` wired into FastAPI `lifespan` context manager | Pin to 4.x for async-native API; 3.x has different interface |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `gastos_whatsapp.py` → `ConversationOrchestrator` | `asyncio.create_task(orchestrator.handle_message(...))` | Same pattern as existing `process_invoice` background task |
| `ConversationOrchestrator` → `SlotExtractionService` | Direct async call | SlotExtractionService is stateless; construct once per orchestrator call |
| `ConversationOrchestrator` → `ExtractionService` | Direct async call (ticket photo step only) | Reused unchanged — same interface as invoice pipeline |
| `ConversationOrchestrator` → `GastoService` | Direct async call, shares the session held open by orchestrator | GastoService receives the already-locked session |
| `scheduler.py` → `WhatsAppProvider` | Direct construction from settings (no DI) | Must import provider factory pattern from `whatsapp.py`, not duplicate it |
| `scheduler.py` → `Conversation` table | `get_async_session_local()` | Upsert only — no FOR UPDATE needed (scheduler sets state, does not read-modify-write slots) |

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Branching Gastos Logic into the Existing `/whatsapp/webhook`

**What people do:** Add `if Body and is_gasto_sender(From):` inside the existing handler.
**Why it's wrong:** The existing handler's media gate (step 5) must be removed for gastos senders, creating two behavioral contracts in one function. Also breaks the existing handler's test suite.
**Do this instead:** Separate router at `/gastos/webhook`, registered at distinct prefix.

### Anti-Pattern 2: In-Memory Idempotency for Multi-Turn State

**What people do:** Extend `_processed_message_sids` set to cover gastos messages.
**Why it's wrong:** The set is cleared on restart. A manager mid-conversation whose message is replayed after a restart would get a "message already processed" skip, silently dropping their reply and leaving them stuck in a state.
**Do this instead:** `Conversation.last_message_id` column — DB-persisted, survives restarts.

### Anti-Pattern 3: GPT Decides When to Save

**What people do:** Give GPT a "save_gasto" tool/function and let it call it when it thinks all fields are present.
**Why it's wrong:** GPT can hallucinate a filled `monto` field, or decide to save before the required ticket photo step. Required-field enforcement becomes probabilistic.
**Do this instead:** Orchestrator code checks slot completeness and required-step completion before calling `GastoService.save()`. GPT only extracts slot values, never drives transitions.

### Anti-Pattern 4: Scheduler Holding a FOR UPDATE Lock

**What people do:** Have the scheduler acquire a row lock on each Conversation before upserting state.
**Why it's wrong:** If a manager's reply arrives during the 12:00 job, the reply's orchestrator call will block waiting for the lock. At low volume this is harmless but unnecessary — the scheduler only sets `state`, it does not read-then-write slots.
**Do this instead:** Scheduler uses a plain `INSERT ... ON CONFLICT DO UPDATE` (upsert) without `FOR UPDATE`. If a reply is being processed concurrently, the upsert races harmlessly — the `updated_at` will reflect whichever committed last, and the manager can always re-reply.

### Anti-Pattern 5: Importing TwilioProvider Directly in Scheduler or Orchestrator

**What people do:** `from app.providers.twilio import TwilioProvider` in `scheduler.py`.
**Why it's wrong:** Breaks provider swap via `WHATSAPP_PROVIDER` env var. Test overrides stop working.
**Do this instead:** Construct the provider via the same factory function in `whatsapp.py` (`get_whatsapp_provider` called with `get_settings()`), or extract that factory to `app/providers/__init__.py` so it can be imported without pulling the router.

---

## Scalability Considerations

| Concern | At 2-3 managers (v2.0) | At 20+ managers | At 100+ managers |
|---------|------------------------|-----------------|------------------|
| Conversation locking | FOR UPDATE per sender, zero contention | Still fine — lock scope is per row | Still fine — lock per row, not table |
| Scheduler fan-out | Sequential send to 2-3 senders is instant | Sequential send to 20 senders (~1-2s) | Parallelize with asyncio.gather |
| GPT calls | 2 types (slot extraction + ticket vision), low volume | Same — GPT rate limits not a concern | Check tier limits |
| DB connections | Single async pool sufficient | Same | Same for single-company deploy |

---

## Sources

- Existing codebase: `backend/app/routers/whatsapp.py`, `backend/app/main.py`, `backend/app/providers/base.py`, `backend/app/db/models.py` (inspected 2026-05-27)
- Approved design: `docs/plans/2026-05-27-gastos-bot-design.md` (inspected 2026-05-27)
- APScheduler 4.x async API: https://apscheduler.readthedocs.io/en/master/userguide.html
- SQLAlchemy `with_for_update()`: https://docs.sqlalchemy.org/en/20/orm/queryguide/select.html#sqlalchemy.orm.Query.with_for_update
- FastAPI lifespan context manager: https://fastapi.tiangolo.com/advanced/events/
- asyncio.create_task strong-ref pattern: Python docs asyncio-task.html (Pattern 4, already documented in whatsapp.py module docstring)

---
*Architecture research for: Compras Agent v2.0 Gastos Bot — integration with existing FastAPI app*
*Researched: 2026-05-27*
