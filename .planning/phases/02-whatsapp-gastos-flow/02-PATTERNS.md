# Phase 2: WhatsApp Gastos Flow - Pattern Map

**Mapped:** 2026-05-27
**Files analyzed:** 4 (1 new router, 3 modified)
**Analogs found:** 4 / 4 (all in-codebase; no RESEARCH.md — patterns reused from Phase 1 / v1.0)

All analogs live in this repo. Every "create" file has a strong in-codebase analog; the
phase is deliberately a structural clone + rework exercise (CONTEXT.md "Code to mirror").

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/app/routers/gastos.py` (NEW) | router | request-response → background event | `backend/app/routers/whatsapp.py` | exact (structural clone) |
| `backend/app/services/conversation.py` (MODIFY) | service | event-driven FSM | itself (Phase 1) + `_handle_awaiting_ticket` rework | self / role-match |
| `backend/app/services/extraction.py` (REUSE pattern; likely NEW lightweight amount extractor) | service | transform (vision→struct) | `backend/app/services/extraction.py` `_call_gpt4o` | exact |
| `backend/app/main.py` (MODIFY) | config / app factory | wiring | existing `agent_mode == "invoice"` branch | exact |

Reused untouched (no new file, referenced as collaborators):
`backend/app/providers/base.py`, `backend/app/providers/twilio.py`,
`backend/app/services/storage.py`, `backend/app/services/gasto.py`,
`backend/app/services/slot_extraction.py`, `backend/app/db/models.py`,
`backend/app/models/conversation.py`.

---

## Pattern Assignments

### `backend/app/routers/gastos.py` (NEW — router, fast-200 + background dispatch)

**Analog:** `backend/app/routers/whatsapp.py` (the entire file is the template).

The gastos router is a structural clone of the v1.0 invoice webhook. It keeps the
webhook shell (signature → dedupe → allowlist → fast-200 → background task) but the
background task dispatches into `ConversationOrchestrator.handle_message(...)` instead
of `process_invoice`. Copy these blocks verbatim, then swap the task body.

**Module-level state — strong-ref set + in-memory dedupe** (`whatsapp.py:64-71`):
```python
# Module-level strong reference set — prevents Python 3.12 GC from collecting tasks
# before they complete. Pattern: asyncio-task.html (Pattern 4).
_background_tasks: set = set()
# In-memory dedupe set for webhook retries on the same MessageSid.
_processed_message_sids: set[str] = set()
```
Note (D-05): the orchestrator already does DB-backed idempotency via
`conv.last_message_id` (`conversation.py:220-223`). Router-level `_processed_message_sids`
is planner discretion — keep it as a cheap fast-path, but it is NOT the source of truth.

**Provider factory — sole construction site, lazy import, tests override via DI**
(`whatsapp.py:119-158`). Copy `get_whatsapp_provider` verbatim — the
`WhatsAppProvider` Protocol and `TwilioProvider` are reused untouched (CONTEXT D-06).

**Effective-URL helper for signature validation** (`whatsapp.py:166-183`) — copy
`_compute_effective_url`, changing the path suffix from `/whatsapp/webhook` to
`/gastos/webhook`:
```python
if settings.webhook_base_url:
    return f"{settings.webhook_base_url.rstrip('/')}/gastos/webhook"
return str(request.url)
```

**Magic-byte image guard** (`whatsapp.py:110-111, 186-210`) — copy `JPEG_MAGIC`,
`PNG_MAGIC`, `SUPPORTED_IMAGE_TYPES`, and `_validate_image_bytes` verbatim. The ticket
photo path (D-02) needs the same two-layer defense (MIME guard + magic bytes) before
handing bytes to vision.

**`_safe_send` reply wrapper** (`whatsapp.py:303-329`) — copy verbatim; reply-send
failures must not crash the background task.

**Fast-200 webhook handler — the 9-step shell** (`whatsapp.py:475-572`). Copy the
handler signature (Twilio `Form(...)` fields), then keep steps 1–6 (form read,
signature validate→401, MessageSid dedupe, allowlist gate→D-10-style reply, return 200).
The gastos differences:
- Step 5 media gate is NOT a hard reject — a gasto conversation can be text-only
  ("sin ticket"). Media is optional and only relevant at `awaiting_ticket`.
- Step 8 schedules the orchestrator instead of `process_invoice`:
```python
task = asyncio.create_task(
    process_gasto_message(            # new background fn (see below)
        sender=From,
        message_sid=MessageSid,
        body=Body,
        media_url=MediaUrl0,          # may be None
        media_content_type=MediaContentType0,
        provider=provider,
    )
)
_background_tasks.add(task)
task.add_done_callback(_background_tasks.discard)
return Response(status_code=200)
```

**Allowlist gate** (`whatsapp.py:522-536`) — copy verbatim including the
`From.replace("whatsapp:", "").strip()` normalization and the `SenderAllowlist`
`select(...).where(is_active == True).limit(1)` query.

**Background task — construct services inside the task, open own session**
(`whatsapp.py:337-468` is the structural template; the body changes). Background tasks
**cannot** use `Depends()` — construct collaborators inline exactly as `process_invoice`
does at `whatsapp.py:377-388`:
```python
from app.config import get_settings as _get_settings
from openai import AsyncOpenAI
from app.services.storage import LocalStorageBackend
settings = _get_settings()
# ... build SlotExtractionService, GastoService, the amount-vision extractor, provider
```
Then dispatch:
```python
from app.db.engine import get_async_session_local   # module-level for test patching
orchestrator = ConversationOrchestrator(slot_service, gasto_service, provider)
await orchestrator.handle_message(
    session_factory=get_async_session_local(),
    sender=sender, text=body, message_id=message_sid,
    # + media path / extended entry per D-06 (see conversation.py rework below)
)
```

**Media handling for D-06:** when `MediaUrl0` is present, download via
`provider.download_media(media_url)` (`twilio.py:107-135`), run the magic-byte guard,
store via `LocalStorageBackend.save(bytes, f"{message_sid}{ext}")`
(`storage.py:55`), run amount-vision, and feed the resulting amount + stored path into
the orchestrator's extended entry path. Planner decides: router downloads/stores and
passes path+amount in, OR orchestrator gains media params (CONTEXT D-06 leaves this open).

---

### `backend/app/services/conversation.py` (MODIFY — FSM rework for D-01 ticket-first + D-06 media)

**Analog:** itself. The non-negotiable entry sequence (`conversation.py:159-274`) is
preserved exactly — ensure-row → lock → snapshot → idempotency → timeout → cancel →
dispatch → commit-in-`session.begin()` → reply-outside-txn. Do NOT touch that ordering;
it encodes the race-safety and at-most-once-reply contract (module docstring lines 1-63).

**ConvState enum to rework** (`conversation.py:85-89`) — current:
```python
class ConvState:
    IDLE = "idle"
    AWAITING_MONTO = "awaiting_monto"
    AWAITING_TICKET = "awaiting_ticket"
    CONFIRM = "confirm"
```
D-01 reorders the *transitions*, not necessarily the constants: ticket step now comes
**before** the amount step. `awaiting_monto` becomes the "sin ticket" fallback branch,
not the default next step. Exact names are planner discretion (D-90/Claude's Discretion).

**Dispatch table** (`conversation.py:296-317`) — `match conv.state` stays; rewire which
handler each state routes to under the new order.

**`_handle_idle` rework** (`conversation.py:341-392`) — the current code has confused
inline comments (lines 360-376) trying to reconcile concepto/monto ordering. Under D-01:
after slot extraction + `patch_draft`, if `concepto` missing → ask concepto; else →
go straight to `AWAITING_TICKET` and ask for the ticket photo (NOT monto). The
existing "both present" branch (lines 385-392) already targets `AWAITING_TICKET` — make
that the default whenever concepto is known.

**`_handle_awaiting_ticket` rework — THIS is the core D-02/D-06 change**
(`conversation.py:446-469`). Phase 1 stub ignores photos and treats everything as
"sin ticket". Phase 2:
- `"sin ticket"` (case-insensitive, current line 457) → keep `ticket_image_path=None`,
  then route to `AWAITING_MONTO` (ask the amount) — this is the only path that still
  needs `awaiting_monto`. Re-uses the existing `_handle_awaiting_monto` 3-strikes /
  `parse_ars_amount` re-prompt logic (lines 394-444, D-01b).
- Photo present → amount came from vision (passed in via the D-06 media path); set
  `draft.monto`, `draft.ticket_image_path = stored_path`, advance to `CONFIRM`,
  return `_confirm_summary(draft)` (line 499).
- Vision unreadable (D-01b) → fall back to `AWAITING_MONTO` re-prompt.
This handler is currently sync (`def`, line 446); with vision/media it likely becomes
`async def` and is awaited in `_dispatch` (line 305).

**Pure helpers to reuse unchanged:** `is_confirmation` (line 107, exact-token affirmative
set line 98-100), `is_cancel` (line 120), `patch_draft` (line 125),
`_load_draft`/`_save_draft` (lines 319-339 — reassign-don't-mutate for `onupdate` per
Pitfall E), `_confirm_summary` (line 499). The `_save_draft` reassignment pattern is
load-bearing for `updated_at` change-tracking — do not mutate `draft_gasto` in place.

**Collaborator interfaces (fixed):**
- `SlotExtractionService.extract(text) -> GastoSlots` (`slot_extraction.py:86`)
- `GastoService.save_gasto(session, draft, sender_phone) -> Gasto` (`gasto.py:40`)
- `WhatsAppProvider.send_message(to, text)` / `download_media(url)` (`base.py:27-39`)

---

### Ticket amount vision extraction (REUSE `extraction.py` pattern — D-02)

**Analog:** `backend/app/services/extraction.py` `_call_gpt4o` (`extraction.py:159-203`).

D-02 requires **amount-only** extraction on `gpt-4o` vision — NOT the full
`ExtractedInvoice` schema. Planner discretion: lightweight amount-only Pydantic model +
prompt, or reuse `ExtractedInvoice` and pull the total. "Amount only" is the hard req.

**The `.parse()` vision call to copy** (`extraction.py:170-203`):
```python
b64 = base64.b64encode(image_bytes).decode("utf-8")
completion = await self._client.chat.completions.parse(
    model="gpt-4o-2024-08-06",
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},   # amount-only prompt for gastos
        {"role": "user", "content": [
            {"type": "text", "text": "..."},
            {"type": "image_url",
             "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]},
    ],
    response_format=AmountOnly,    # amount-only Pydantic model (Optional[float], null > guess)
)
msg = completion.choices[0].message
return (msg.parsed, msg.refusal)    # check refusal BEFORE parsed (Pitfall 2)
```

**Patterns to carry over:**
- Constructor DI: `(openai_client, storage, settings)` (`extraction.py:148-157`) so tests
  inject a MagicMock client.
- All extracted fields `Optional` with `default=None` — null > hallucination
  (CONTEXT "Established Patterns"; mirrors `GastoSlots.monto: Optional[float]` at
  `models/conversation.py:40`, which keeps GPT emitting a JSON number and sidesteps the
  `Decimal("1.500")` Argentine-separator trap). Convert via `Decimal(str(...))` in the
  orchestrator (`conversation.py:411-413`).
- Exception hierarchy `ExtractionRefusalError` / `ExtractionFailedError`
  (`extraction.py:70-79`) — reuse or mirror for the unreadable-ticket fallback (D-01b).
- NEVER log the API key (`extraction.py:197-198`, T-02-02).
- Image stored via `StorageBackend.save` before/around extraction
  (`extraction.py:228-231`); for gastos the image is **always** stored when provided (D-02).

---

### `backend/app/main.py` (MODIFY — mount gastos router via AGENT_MODE seam, D-09)

**Analog:** the existing `agent_mode == "invoice"` branch (`main.py:57-64`).

The gastos branch is currently a commented placeholder (`main.py:62-64`). Replace it,
mirroring the invoice branch — import inside `create_app()` (avoids circular import,
matches the established pattern at `main.py:43-46`):
```python
if settings.agent_mode == "invoice":
    from app.routers.whatsapp import router as whatsapp_router
    app.include_router(whatsapp_router, prefix="/whatsapp", tags=["whatsapp"])
elif settings.agent_mode == "gastos":
    from app.routers.gastos import router as gastos_router
    app.include_router(gastos_router, prefix="/gastos", tags=["gastos"])
```
`settings.agent_mode` defaults to `"gastos"` (`config.py:30`) — the milestone default;
flipping to `"invoice"` resurrects the v1.0 demo unchanged (CONTEXT "Specific Ideas").
Unknown values mount neither router (fail-closed, T-01-04, comment at `main.py:54-56`).

---

## Shared Patterns

### Fast-200 + background task (asyncio.create_task + strong-ref set)
**Source:** `backend/app/routers/whatsapp.py:64-66, 558-572`
**Apply to:** `gastos.py` webhook handler.
Return HTTP 200 before any DB/GPT work so Twilio's 5s timeout is never hit; retain the
task in `_background_tasks` to prevent GC; discard via `add_done_callback`.

### Background tasks construct services inline (no Depends)
**Source:** `backend/app/routers/whatsapp.py:377-388, 421-425`
**Apply to:** the gastos background fn.
`get_settings()`, `AsyncOpenAI(...)`, `LocalStorageBackend(...)`, and
`get_async_session_local()` are constructed/imported inside the task; the session factory
import stays at module level so tests can patch it.

### Provider abstraction via Protocol; tests override the factory
**Source:** `backend/app/providers/base.py:19-39`, `whatsapp.py:119-158`
**Apply to:** all WhatsApp interaction in `gastos.py`.
Handler imports only `WhatsAppProvider`; tests do
`app.dependency_overrides[get_whatsapp_provider] = lambda: mock_provider`.

### `SELECT ... FOR NO KEY UPDATE` row lock (Postgres-only)
**Source:** `backend/app/services/conversation.py:203-208`
```python
select(Conversation).where(Conversation.sender_phone == clean_sender).with_for_update(key_share=True)
```
`key_share=True` compiles to `FOR NO KEY UPDATE` under postgresql. Preserved as-is in the
rework. SQLite ignores row locks — tests assert the compiled lock hint, not semantics
(CONTEXT "Established Patterns"; module docstring lines 38-42).

### Atomic txn + reply-outside-transaction
**Source:** `backend/app/services/conversation.py:185-274`
All DB mutations inside one `async with session.begin()`; reply sent via
`provider.send_message` strictly AFTER commit (at-most-once reply risk is accepted).
Preserved unchanged in the rework.

### Two-layer image guard (MIME + magic bytes)
**Source:** `backend/app/routers/whatsapp.py:100, 110-111, 186-210, 368-405`
**Apply to:** the ticket-photo path in `gastos.py` before vision.

### Optional-everything Pydantic (null > hallucination)
**Source:** `backend/app/models/conversation.py:37-61`, `backend/app/services/extraction.py`
**Apply to:** the amount-only vision model.

### Path-traversal-safe storage
**Source:** `backend/app/services/storage.py:55-119`
**Apply to:** ticket image save — reuse `LocalStorageBackend.save(bytes, "{key}/{basename}")`
untouched; caller builds the relative path.

## No Analog Found

None. Every Phase 2 file has a strong in-codebase analog. The only genuinely new code is
the amount-only vision prompt/schema (D-02), which is a trimmed variant of
`extraction.py`'s `.parse()` pattern, not a new architecture.

## Metadata

**Analog search scope:** `backend/app/{routers,services,providers,models,db}/`
**Files scanned:** 11 read in full + dir listing + config/signature greps
**Pattern extraction date:** 2026-05-27
