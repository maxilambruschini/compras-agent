# Phase 3: WhatsApp Pipeline - Research

**Researched:** 2026-05-14
**Domain:** Twilio WhatsApp webhook integration, FastAPI async patterns, duplicate detection, provider abstraction
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Use **Twilio** for the demo deployment. Twilio sandbox requires no business verification and can be set up in 30 minutes. This is the initial implementation.
- **D-02:** Use **Meta WhatsApp Cloud API** (via pywa 3.9.0) for the production path. pywa is already pinned in `CLAUDE.md`. Not implemented in this phase — stub only.
- **D-03:** A `WhatsAppProvider` protocol (ABC or `typing.Protocol`) is required with at minimum three methods: `send_message(to: str, text: str) -> None`, `download_media(media_id: str) -> bytes`, `validate_signature(request: Request) -> bool`. The Twilio and Meta implementations both satisfy this interface. The handler never touches either SDK directly.
- **D-04:** Provider is selected via environment variable (e.g., `WHATSAPP_PROVIDER=twilio|meta`). `Settings` reads this and `create_app()` (or a provider factory) instantiates the correct implementation. Swapping providers = change one env var, no code changes.
- **D-05:** Use `asyncio.create_task()` to schedule the extraction coroutine after sending the acknowledgement reply. This is the correct pattern for async work in FastAPI — `ExtractionService` uses `AsyncOpenAI` and `AsyncSession`, both of which require the running event loop. `FastAPI.BackgroundTasks` uses a thread pool and would require awkward `asyncio.run()` wrapping.
- **D-06:** Flow: (1) Validate signature → 401 if invalid. (2) Check allowlist → reject if not found. (3) Send immediate acknowledgement reply. (4) `asyncio.create_task(process_invoice(...))`. (5) Return HTTP 200 to WhatsApp. Extraction runs concurrently without blocking the webhook response.
- **D-07:** Acknowledgement (WA-01): `✅ Factura recibida. Procesando...`
- **D-08:** Extraction summary — auto_saved (WA-03): Multi-line with proveedor, numero_documento, fecha, total.
- **D-09:** Extraction summary — pending_review (WA-03 + VAL-02): Same fields with review CTA.
- **D-10:** Non-allowlisted sender (WA-02): `❌ Este número no está autorizado para enviar facturas.`
- **D-11:** Unreadable image / unsupported format (WA-04): `❌ No pudimos procesar la imagen. Asegurate de enviar una foto clara de la factura (JPG o PDF).`
- **D-12:** Duplicate detected (VAL-01): `🔁 Esta factura ya fue registrada el {fecha_original}. No se guardó de nuevo.`
- **D-13:** Duplicate check query: `SELECT id, created_at FROM invoices WHERE LOWER(numero_documento) = LOWER(:numero) AND LOWER(proveedor) = LOWER(:proveedor) LIMIT 1`. Case-insensitive exact match on both fields.
- **D-14:** Fuzzy matching on proveedor is deferred to v2. Exact case-insensitive match is sufficient for v1.
- **D-15:** Race condition backstop: a `UNIQUE` constraint on `(LOWER(numero_documento), LOWER(proveedor))` at the DB level catches concurrent duplicates. If the INSERT raises `UniqueViolation`, treat it the same as a detected duplicate.

### Claude's Discretion

- Internal structure of `WhatsAppProvider` — Protocol vs ABC. Pick the conventional Python approach (likely `typing.Protocol` for duck-typing compatibility with tests).
- Whether `TwilioProvider.validate_signature()` uses the official Twilio request validator or a manual HMAC — use the official Twilio library approach.
- Error logging structure — follow existing `structlog` patterns from Phase 2.
- Whether duplicate detection lives in `InvoiceService` or inline in the handler — researcher/planner decides based on what exists after Phase 2.

### Deferred Ideas (OUT OF SCOPE)

- Meta Cloud API full implementation (pywa wiring, HMAC, GET challenge) — production upgrade path, not this phase.
- Fuzzy proveedor matching — v2 enhancement.
- Retry mechanism for failed extractions — simple error reply is sufficient for v1.
- PDF support — reject with error message if format is not a supported image type.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| WA-01 | Employee can send an invoice photo via WhatsApp and receive a reply acknowledging receipt | Twilio sandbox + TwiML acknowledgement reply pattern documented |
| WA-02 | System rejects messages from non-allowlisted numbers with explanatory message in Spanish | `sender_allowlist` table exists in DB; allowlist query pattern from Phase 1 |
| WA-03 | System replies with summary of extracted fields after processing completes | `asyncio.create_task` + REST API outbound reply via Twilio client after extraction |
| WA-04 | System notifies sender if the image is unreadable or the file format is not supported | `ExtractionRefusalError` / `ExtractionFailedError` → error reply path |
| VAL-01 | System detects duplicate submissions using numero_documento + proveedor | Case-insensitive SELECT + DB-level UNIQUE constraint migration |
| VAL-02 | Extractions below confidence threshold saved with `status=pending_review` | `assign_status()` already implemented in `ExtractionService`; status flows into WA-03 reply |
| VAL-03 | Extractions above confidence threshold saved with `status=auto_saved` | Same — `ExtractionResult.status` drives reply copy selection |
| INF-02 | WhatsApp webhook HMAC-SHA256 signature is validated on every inbound request | `twilio.request_validator.RequestValidator` validates `X-Twilio-Signature`; reject with HTTP 401 |
| INF-04 | WhatsApp webhook responds within 5 seconds; invoice processing runs as background task | `asyncio.create_task` with strong reference retention pattern; TwiML response returned immediately |
</phase_requirements>

---

## Summary

Phase 3 wires the two existing services (ExtractionService from Phase 2, allowlist + Invoice schema from Phase 1) into a live WhatsApp channel using Twilio's sandbox. The core deliverable is a provider-abstracted webhook handler: Twilio sends a form-encoded POST, the handler validates the HMAC-SHA256 signature, checks the allowlist, sends an immediate TwiML acknowledgement, fires a background `asyncio.create_task` for extraction, and returns HTTP 200 — all within 5 seconds. The background task runs `ExtractionService.extract()`, persists the invoice to Postgres, and sends a follow-up reply via the Twilio REST client.

The two highest-risk areas are: (1) the `asyncio.create_task` garbage-collection trap — Python 3.12's event loop holds only weak references to tasks, so fire-and-forget tasks without a strong reference are silently collected before completion; and (2) the new Alembic migration needed for the DB-level UNIQUE constraint on `(LOWER(numero_documento), LOWER(proveedor))` to backstop the application-level duplicate check against race conditions. Both are resolved by established patterns documented below.

The Twilio SDK is synchronous by default but ships `AsyncTwilioHttpClient` for async contexts. For Phase 3, outbound replies (send_message) must use `client.messages.create_async(...)` with `AsyncTwilioHttpClient` to avoid blocking the event loop. Media download happens via `httpx.AsyncClient` (already in dev requirements) using HTTP Basic Auth (Account SID / Auth Token) against the `MediaUrl0` field from the webhook payload.

**Primary recommendation:** Build `TwilioProvider` with async-first send (via `AsyncTwilioHttpClient`) and sync-safe signature validation (via `RequestValidator`). Return a plain `200 OK` with empty body or a minimal TwiML `<Response/>` to Twilio for the webhook acknowledgement; send the actual content reply via the REST API from the background task. This two-message pattern (immediate ack + delayed summary) requires Twilio's REST API, not TwiML — TwiML responses are consumed synchronously and cannot be deferred.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Webhook receive + HMAC validation | API / Backend | — | Server-only; signature requires the Auth Token secret |
| Allowlist check | API / Backend | Database / Storage | Query against `sender_allowlist` table |
| Immediate acknowledgement reply | API / Backend | — | Must happen before `asyncio.create_task` returns |
| Media download (invoice image) | API / Backend | — | Twilio MediaUrl0 requires HTTP Basic Auth with account credentials |
| Invoice extraction | API / Backend | — | `ExtractionService.extract()` already owns this |
| Invoice persistence | Database / Storage | — | `invoices` + `invoice_line_items` tables via AsyncSession |
| Duplicate detection | Database / Storage | API / Backend | DB UNIQUE constraint backstop + app-level SELECT |
| Summary reply (post-extraction) | API / Backend | — | REST API call from background task |
| Provider abstraction | API / Backend | — | `WhatsAppProvider` protocol isolates SDK from handler |

---

## Standard Stack

### Core (Phase 3 additions)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| twilio | 9.10.9 | Webhook signature validation + outbound messages | Official Twilio Python SDK; `RequestValidator` is the only correct way to verify `X-Twilio-Signature` |
| httpx | 0.28.1 | Async media download from Twilio MediaUrl0 | Already in dev requirements; async-native, avoids blocking the event loop during image fetch |
| ngrok | 3.36.1 | Expose localhost:8000 to Twilio sandbox | Required for local demo; already installed on the machine |

**Verified:** twilio 9.10.9 from PyPI index (checked 2026-05-14). [VERIFIED: pip index]
**Verified:** httpx 0.28.1 installed. [VERIFIED: pip show httpx]
**Verified:** ngrok 3.36.1 installed at `/opt/homebrew/bin/ngrok`. [VERIFIED: which ngrok]

### Existing Stack (consumed, not changed)

| Asset | Location | Role in Phase 3 |
|-------|----------|-----------------|
| `ExtractionService.extract()` | `backend/app/services/extraction.py` | Called from background task |
| `ExtractionResult`, `ExtractionRefusalError`, `ExtractionFailedError` | same | Used to drive reply copy selection |
| `Invoice`, `SenderAllowlist` ORM models | `backend/app/db/models.py` | Allowlist lookup + invoice INSERT |
| `get_db()` → `AsyncSession` | `backend/app/db/session.py` | DB dependency injection pattern |
| `get_settings()` | `backend/app/config.py` | Settings singleton; add Twilio fields here |
| `structlog` | already configured | Logging; use `log.info("whatsapp.received", ...)` pattern |
| `create_app()` / conditional router | `backend/app/main.py` | Add Twilio router using same conditional pattern |

### Installation

```bash
pip install twilio==9.10.9
```

Add to `backend/requirements.txt`:
```
twilio==9.10.9
```

`httpx` and `ngrok` are already available.

---

## Architecture Patterns

### System Architecture Diagram

```
WhatsApp User
    |
    | (sends image)
    v
Twilio Sandbox
    |
    | POST /whatsapp/webhook
    | X-Twilio-Signature: <hmac>
    | From, MessageSid, NumMedia, MediaUrl0, MediaContentType0
    v
FastAPI webhook handler (async def)
    |
    +-- [1] Validate X-Twilio-Signature via RequestValidator → 401 if invalid
    |
    +-- [2] Read Form data: From, MessageSid, NumMedia, MediaUrl0
    |
    +-- [3] Allowlist check (SELECT sender_allowlist WHERE phone=From AND is_active)
    |       → if not found: send rejection reply via Twilio REST → return 200
    |
    +-- [4] NumMedia check
    |       → if 0: send error reply (no image) → return 200
    |
    +-- [5] Send immediate ack: "✅ Factura recibida. Procesando..."
    |       (Twilio REST: client.messages.create_async)
    |
    +-- [6] asyncio.create_task(process_invoice(...))  ← background task starts
    |       stored in module-level set for strong reference retention
    |
    +-- [7] return HTTP 200 (plain or empty TwiML <Response/>)
    |
    v
Background task: process_invoice(...)
    |
    +-- Download image bytes via httpx.AsyncClient(auth=(sid, token)).get(MediaUrl0)
    |
    +-- ExtractionService.extract(image_bytes, filename) → ExtractionResult
    |   (raises ExtractionRefusalError / ExtractionFailedError on failure)
    |
    +-- Duplicate check: SELECT invoices WHERE LOWER(numero) = ... AND LOWER(proveedor) = ...
    |   → if duplicate: send duplicate reply → done
    |
    +-- INSERT Invoice + line_items via AsyncSession
    |   → on UniqueViolation (race condition): treat as duplicate → send duplicate reply
    |
    +-- Send summary reply based on ExtractionResult.status:
    |   auto_saved → "✅ Factura registrada: ..."
    |   pending_review → "⚠️ Algunos campos no se pudieron leer..."
    |
    v
  Done
```

### Recommended Project Structure

```
backend/app/
├── providers/
│   ├── __init__.py
│   ├── base.py          # WhatsAppProvider typing.Protocol
│   ├── twilio.py        # TwilioProvider implementation
│   └── meta.py          # MetaCloudProvider stub (pass-through, not implemented)
├── routers/
│   ├── whatsapp.py      # Twilio webhook router (POST /whatsapp/webhook)
│   └── ...existing...
├── services/
│   ├── extraction.py    # unchanged
│   ├── storage.py       # unchanged
│   └── invoice.py       # NEW: InvoiceService with duplicate check + DB persist
└── ...existing...
```

**On `invoice.py`:** Duplicate detection belongs in a new `InvoiceService` (not inline in the handler). Phase 2 left no `InvoiceService` — the extraction router did not persist to DB. A dedicated service keeps the handler thin and makes the duplicate-check logic independently testable. [ASSUMED: no InvoiceService exists — verified by inspecting `backend/app/services/` directory]

### Pattern 1: WhatsAppProvider Protocol

```python
# Source: CONTEXT.md D-03 + Python typing.Protocol docs
from typing import Protocol, runtime_checkable
from fastapi import Request

@runtime_checkable
class WhatsAppProvider(Protocol):
    async def send_message(self, to: str, text: str) -> None: ...
    async def download_media(self, media_url: str) -> bytes: ...
    def validate_signature(self, request_url: str, params: dict, signature: str) -> bool: ...
```

**Key implementation note:** `validate_signature` is synchronous — `RequestValidator.validate()` is CPU-bound and does not need to be async. `send_message` and `download_media` are async to avoid blocking the event loop.

**Why `typing.Protocol` not ABC:** Protocol enables structural subtyping — `TwilioProvider` satisfies the protocol without explicit inheritance, which makes test doubles (mock providers) trivial. [CITED: Python typing docs]

### Pattern 2: TwilioProvider — Signature Validation

```python
# Source: Context7 /twilio/twilio-python + https://www.twilio.com/en-us/blog/build-secure-twilio-webhook-python-fastapi
from twilio.request_validator import RequestValidator

class TwilioProvider:
    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        self._validator = RequestValidator(auth_token)
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_number = from_number  # e.g. "whatsapp:+14155238886"

    def validate_signature(self, request_url: str, params: dict, signature: str) -> bool:
        # params = dict(await request.form())
        # Twilio webhook always sends form-encoded POST for WhatsApp
        return self._validator.validate(request_url, params, signature)
```

**Critical:** `validator.validate(url, form_dict, signature)` — the URL must be the exact public URL including scheme and host that Twilio POSTed to. Under ngrok this is `https://<ngrok-id>.ngrok-free.app/whatsapp/webhook`. URL mismatch is the most common cause of signature validation failures.

### Pattern 3: TwilioProvider — Async Send + Media Download

```python
# Source: Context7 /twilio/twilio-python (AsyncTwilioHttpClient)
import httpx
from twilio.http.async_http_client import AsyncTwilioHttpClient
from twilio.rest import Client

class TwilioProvider:
    async def send_message(self, to: str, text: str) -> None:
        http_client = AsyncTwilioHttpClient()
        client = Client(self._account_sid, self._auth_token, http_client=http_client)
        await client.messages.create_async(
            body=text,
            from_=self._from_number,
            to=to,  # e.g. "whatsapp:+5491112345678"
        )
        await http_client.close()

    async def download_media(self, media_url: str) -> bytes:
        # Twilio MediaUrl0 requires HTTP Basic Auth (Account SID + Auth Token)
        # Source: Twilio docs media-resource
        async with httpx.AsyncClient() as client:
            response = await client.get(
                media_url,
                auth=(self._account_sid, self._auth_token),
            )
            response.raise_for_status()
            return response.content
```

**Note on AsyncTwilioHttpClient:** Each call creates and closes a client. For < 20 calls/day this is fine. A longer-lived client can be managed via the lifespan context if needed later. [ASSUMED: per-call client is sufficient at this volume]

### Pattern 4: asyncio.create_task with Strong Reference Retention

This is the critical safety pattern for Python 3.12. Without it, background tasks are silently garbage collected.

```python
# Source: https://docs.python.org/3.12/library/asyncio-task.html
# Source: https://github.com/python/cpython/issues/91887

# Module-level (in the router or app module) — strong reference set
_background_tasks: set = set()

async def webhook_handler(request: Request, ...):
    # ... validate, allowlist, send ack ...
    
    task = asyncio.create_task(
        process_invoice(sender, message_sid, media_url, media_content_type, provider)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)  # auto-cleanup on completion
    
    return Response(status_code=200)
```

**Why this matters:** Python's event loop holds only **weak references** to tasks. A `create_task` result not stored elsewhere will be garbage collected before completion — no exception, no log, task simply never finishes. The set + `add_done_callback(discard)` pattern is the canonical fix from Python's own documentation since 3.12.

### Pattern 5: Webhook Handler — Form Data + Signature

```python
# Source: https://www.twilio.com/en-us/blog/build-secure-twilio-webhook-python-fastapi
from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import PlainTextResponse

router = APIRouter()

@router.post("/whatsapp/webhook")
async def whatsapp_webhook(
    request: Request,
    From: str = Form(...),
    MessageSid: str = Form(...),
    NumMedia: str = Form("0"),
    MediaUrl0: str = Form(None),
    MediaContentType0: str = Form(None),
    Body: str = Form(""),
    settings: Settings = Depends(get_settings),
):
    form_data = dict(await request.form())
    provider = get_provider(settings)  # factory, injected
    
    # Step 1: Validate signature (INF-02)
    signature = request.headers.get("X-Twilio-Signature", "")
    if not provider.validate_signature(str(request.url), form_data, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    # ... steps 2-7 per D-06 ...
    return Response(status_code=200)
```

**Return value:** Return `Response(status_code=200)` with empty body. Twilio accepts a plain 200. An empty `<Response/>` TwiML is also valid. Do NOT embed the acknowledgement message in TwiML — send it via REST before returning so the background task can send the summary later without conflict.

### Pattern 6: InvoiceService — Duplicate Check + DB Persist

```python
# Source: CONTEXT.md D-13, D-15; SQLAlchemy 2.0 docs
from sqlalchemy import text, select
from sqlalchemy.exc import IntegrityError
from app.db.models import Invoice, InvoiceLineItem

class InvoiceService:
    async def find_duplicate(
        self, session: AsyncSession, numero: str | None, proveedor: str | None
    ) -> Invoice | None:
        if not numero or not proveedor:
            return None
        result = await session.execute(
            select(Invoice).where(
                func.lower(Invoice.numero_documento) == func.lower(numero),
                func.lower(Invoice.proveedor) == func.lower(proveedor),
            ).limit(1)
        )
        return result.scalar_one_or_none()

    async def save_invoice(
        self, session: AsyncSession, result: ExtractionResult,
        message_id: str, sender_phone: str
    ) -> Invoice:
        invoice = Invoice(
            # ... fields from result.invoice ...
            whatsapp_message_id=message_id,
            sender_phone=sender_phone,
            confidence_score=result.confidence_score,
            status=result.status,
            image_path=result.image_path,
        )
        session.add(invoice)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise  # caller catches and treats as duplicate
        return invoice
```

### Anti-Patterns to Avoid

- **Blocking the event loop in the webhook handler:** Do not call `client.messages.create()` (sync Twilio) in an `async def` handler. Use `create_async()` with `AsyncTwilioHttpClient` or run in a thread via `asyncio.to_thread()`.
- **TwiML for the delayed summary reply:** TwiML is consumed by Twilio synchronously from the webhook response. The summary reply comes minutes later (after extraction) and MUST use the REST API (`client.messages.create_async`), not TwiML.
- **`asyncio.create_task()` without storing the reference:** In Python 3.12, the task will be garbage collected before completion. Always store in the module-level set.
- **Using `FastAPI.BackgroundTasks` for extraction:** `BackgroundTasks` runs in a thread pool; `ExtractionService` uses `AsyncOpenAI` which requires the running event loop. Mixing them requires `asyncio.run()` inside a thread, which creates a new loop — incompatible with the existing async session. Use `asyncio.create_task()` instead (D-05).
- **Using the phone number without the `whatsapp:` prefix:** Twilio WhatsApp numbers must be prefixed: `whatsapp:+15551234567`. Strip or add the prefix consistently in `TwilioProvider`.
- **Signature validation with wrong URL:** The URL passed to `validator.validate()` must exactly match what Twilio posted to, including scheme. Under ngrok, the public URL (not localhost) must be used. Store it in settings or reconstruct from the request headers.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HMAC-SHA256 signature verification | Custom HMAC implementation | `twilio.request_validator.RequestValidator` | Twilio's validator handles URL canonicalization, parameter sorting, and edge cases; manual HMAC is error-prone |
| Async HTTP client for media download | `urllib` / `requests` | `httpx.AsyncClient` | Requests is sync-only and blocks the event loop; httpx is already in dev requirements |
| Async Twilio REST calls | Wrapping sync Client in `asyncio.to_thread` | `AsyncTwilioHttpClient` + `create_async()` | Official async client is simpler and purpose-built |
| WhatsApp phone number formatting | Custom `whatsapp:` prefix logic | Standardize in `TwilioProvider.__init__` | One place to normalize `+` country code and `whatsapp:` prefix |

**Key insight:** The Twilio SDK's `RequestValidator` contains subtle canonicalization logic for the URL and parameter sort order. Any hand-rolled HMAC will fail on edge cases (query parameters, trailing slashes, URL encoding). Use the SDK.

---

## Schema Changes Required

The Phase 1 migration created `invoices` with only a composite **index** on `(numero_documento, proveedor)` — not a UNIQUE constraint. D-15 requires adding a functional unique constraint on `(LOWER(numero_documento), LOWER(proveedor))` to backstop race conditions.

**What exists:**
```sql
-- From 0cd640399c29_initial_schema.py
CREATE INDEX ix_invoices_numero_documento_proveedor ON invoices (numero_documento, proveedor);
-- No UNIQUE constraint
```

**What Phase 3 must add (new Alembic migration):**
```sql
-- New migration: add_invoice_duplicate_constraint
CREATE UNIQUE INDEX uq_invoices_numero_proveedor_lower
  ON invoices (LOWER(numero_documento), LOWER(proveedor));
```

This is a **functional unique index** — Postgres supports it; SQLAlchemy's `Index` with `func.lower()` supports it via `text()`. The constraint only fires when both columns are non-null (Postgres UNIQUE ignores rows with NULL in any indexed column — correct behavior for low-confidence extractions).

**Alembic pattern for functional index:**
```python
# In the new migration's upgrade():
op.execute(
    "CREATE UNIQUE INDEX uq_invoices_numero_proveedor_lower "
    "ON invoices (LOWER(numero_documento), LOWER(proveedor)) "
    "WHERE numero_documento IS NOT NULL AND proveedor IS NOT NULL"
)
```

---

## Twilio Webhook Payload Reference

When an employee sends a WhatsApp image, Twilio delivers a form-encoded POST with these fields:
[CITED: https://www.twilio.com/docs/messaging/guides/webhook-request]
[CITED: https://www.twilio.com/docs/whatsapp/api]

| Field | Value Example | Notes |
|-------|---------------|-------|
| `From` | `whatsapp:+5491112345678` | Sender's phone with `whatsapp:` prefix |
| `To` | `whatsapp:+14155238886` | Twilio sandbox number |
| `MessageSid` | `SMxxxxxxxx` | Store as `whatsapp_message_id` |
| `Body` | `` | Usually empty for image-only messages |
| `NumMedia` | `"1"` | String, not int — parse before comparison |
| `MediaUrl0` | `https://api.twilio.com/2010-04-01/Accounts/.../Messages/.../Media/...` | Authenticated URL; requires Basic Auth |
| `MediaContentType0` | `image/jpeg` | Use to validate supported formats before downloading |

**WhatsApp restriction:** WhatsApp allows only one media attachment per message. `MediaUrl0` is always the correct field — no need to handle `MediaUrl1+`.

**Media download authentication:** Twilio enforces HTTP Basic Auth on `MediaUrl0` URLs. Credentials: Account SID as username, Auth Token as password. [CITED: https://www.twilio.com/docs/messaging/api/media-resource]

---

## Common Pitfalls

### Pitfall 1: asyncio.create_task GC Trap
**What goes wrong:** Background task is created but silently garbage collected before the extraction completes. No exception, no log, invoice never saved.
**Why it happens:** Python 3.12's event loop holds only weak references to tasks. A task not referenced from user code is eligible for GC at the next collection cycle.
**How to avoid:** Always store the task reference in a module-level set and use `add_done_callback(set.discard)` for cleanup. [CITED: https://docs.python.org/3.12/library/asyncio-task.html]
**Warning signs:** Webhook returns 200, acknowledgement message is sent, but no invoice appears in DB and no error in logs.

### Pitfall 2: Signature Validation URL Mismatch
**What goes wrong:** `RequestValidator.validate()` returns `False` for all requests, causing spurious 401s.
**Why it happens:** The URL used for validation must exactly match the URL Twilio POSTed to. Under ngrok, the public HTTPS URL must be used, not the internal `http://localhost:8000` URL.
**How to avoid:** Either (a) configure `WEBHOOK_BASE_URL` in Settings and reconstruct the full URL, or (b) use `str(request.url)` which FastAPI populates from the incoming Host header (ngrok forwards the correct host). Verify the URL matches what's configured in the Twilio sandbox console.
**Warning signs:** All requests return 401 even during local testing with valid sandbox credentials.

### Pitfall 3: Sync Twilio Client Blocks Event Loop
**What goes wrong:** Using `Client.messages.create()` (synchronous) in an `async def` handler blocks the entire uvicorn event loop during the outbound REST call.
**Why it happens:** The standard `twilio.rest.Client` is synchronous. Calling it from an async context without wrapping blocks the loop.
**How to avoid:** Use `AsyncTwilioHttpClient` + `client.messages.create_async()`. [CITED: Context7 /twilio/twilio-python]
**Warning signs:** 5-second response times on webhook even when extraction is fast.

### Pitfall 4: TwiML for Delayed Summary Reply
**What goes wrong:** The developer returns the summary message as TwiML from the webhook response, but the TwiML is consumed immediately when Twilio reads the 200 response — before extraction is done.
**Why it happens:** TwiML is a synchronous instruction set consumed at response time. It cannot be "deferred."
**How to avoid:** Return an empty `<Response/>` or plain `200 OK` from the webhook. Send the summary via `client.messages.create_async()` from inside the background task. [CITED: Twilio docs]
**Warning signs:** Summary message arrives before extraction completes, or extraction result is never included.

### Pitfall 5: NumMedia String Comparison
**What goes wrong:** `if NumMedia > 0:` raises `TypeError` because Twilio sends `NumMedia` as a string (`"1"`, `"0"`).
**Why it happens:** All Twilio webhook form fields are strings.
**How to avoid:** Parse with `int(NumMedia)` before comparison.
**Warning signs:** `TypeError: '>' not supported between instances of 'str' and 'int'`

### Pitfall 6: UNIQUE Constraint NULL Behavior
**What goes wrong:** Two invoices with `numero_documento=None` and `proveedor=None` both insert successfully — the UNIQUE constraint doesn't prevent it.
**Why it happens:** Postgres UNIQUE indexes treat NULL as distinct from every other value, so two NULLs do not violate uniqueness.
**How to avoid:** This is correct behavior — low-confidence extractions with both fields null are not duplicates. The `find_duplicate()` method in `InvoiceService` returns `None` when either field is None (early-return guard). Both the app-level check and the DB constraint correctly handle this.
**Warning signs:** None needed — this is expected behavior, document it so the plan doesn't try to "fix" it.

---

## Code Examples

### Allowlist Check Pattern
```python
# Source: SQLAlchemy 2.0 docs + Phase 1 SenderAllowlist model
from sqlalchemy import select
from app.db.models import SenderAllowlist

async def is_allowlisted(session: AsyncSession, phone: str) -> bool:
    # phone arrives as "whatsapp:+5491112345678" — strip prefix for lookup
    normalized = phone.replace("whatsapp:", "").strip()
    result = await session.execute(
        select(SenderAllowlist).where(
            SenderAllowlist.phone_number == normalized,
            SenderAllowlist.is_active == True,
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None
```

### Sending a Reply via Twilio REST
```python
# Source: Context7 /twilio/twilio-python
from twilio.http.async_http_client import AsyncTwilioHttpClient
from twilio.rest import Client

async def send_whatsapp_reply(account_sid: str, auth_token: str, from_: str, to: str, text: str) -> None:
    http_client = AsyncTwilioHttpClient()
    try:
        client = Client(account_sid, auth_token, http_client=http_client)
        await client.messages.create_async(body=text, from_=from_, to=to)
    finally:
        await http_client.close()
```

### Media Download with Authentication
```python
# Source: Twilio media-resource docs + httpx docs
import httpx

async def download_twilio_media(media_url: str, account_sid: str, auth_token: str) -> bytes:
    async with httpx.AsyncClient() as client:
        response = await client.get(media_url, auth=(account_sid, auth_token))
        response.raise_for_status()
        return response.content
```

### Supported Media Type Check
```python
# Source: Twilio WhatsApp guidance-whatsapp-media-messages
SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png"}

def is_supported_media(content_type: str | None) -> bool:
    if not content_type:
        return False
    return content_type.lower().split(";")[0].strip() in SUPPORTED_IMAGE_TYPES
```

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | Runtime | ✓ | 3.12.3 | — |
| twilio SDK | Signature validation + outbound messages | ✗ (not installed) | — | None — must install |
| httpx | Async media download | ✓ | 0.28.1 | — |
| ngrok | Expose localhost to Twilio sandbox | ✓ | 3.36.1 | cloudflared tunnel (alternative) |
| Postgres (Docker) | Invoice + allowlist storage | ✓ (via docker-compose) | 16-alpine | — |

**Missing dependencies with no fallback:**
- `twilio==9.10.9` — must add to `requirements.txt` and install before any work proceeds.

**Missing dependencies with fallback:**
- ngrok is available; cloudflared is an alternative if ngrok has issues.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (asyncio_mode = "auto") |
| Config file | `backend/pyproject.toml` |
| Quick run command | `cd backend && pytest tests/test_whatsapp.py -x` |
| Full suite command | `cd backend && pytest -m "not integration" -x` |
| Integration run | `cd backend && pytest -m integration -x` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INF-02 | Valid HMAC signature accepted (200), invalid rejected (401) | unit | `pytest tests/test_whatsapp.py::test_valid_signature -x` | ❌ Wave 0 |
| INF-02 | Invalid signature returns HTTP 401 | unit | `pytest tests/test_whatsapp.py::test_invalid_signature -x` | ❌ Wave 0 |
| WA-02 | Non-allowlisted sender receives rejection reply | unit | `pytest tests/test_whatsapp.py::test_non_allowlisted -x` | ❌ Wave 0 |
| WA-01 | Allowlisted sender receives ack reply | unit | `pytest tests/test_whatsapp.py::test_allowlisted_ack -x` | ❌ Wave 0 |
| WA-04 | No media (NumMedia=0) returns error reply | unit | `pytest tests/test_whatsapp.py::test_no_media -x` | ❌ Wave 0 |
| WA-04 | Unsupported content type returns error reply | unit | `pytest tests/test_whatsapp.py::test_unsupported_media_type -x` | ❌ Wave 0 |
| VAL-01 | Duplicate invoice detected and not re-saved | unit | `pytest tests/test_invoice_service.py::test_duplicate_detection -x` | ❌ Wave 0 |
| VAL-02 | Low confidence → status=pending_review → correct reply copy | unit | `pytest tests/test_whatsapp.py::test_pending_review_reply -x` | ❌ Wave 0 |
| VAL-03 | High confidence → status=auto_saved → correct reply copy | unit | `pytest tests/test_whatsapp.py::test_auto_saved_reply -x` | ❌ Wave 0 |
| WA-03 | Summary reply includes proveedor, numero, fecha, total | unit | `pytest tests/test_whatsapp.py::test_summary_format -x` | ❌ Wave 0 |
| INF-04 | Webhook returns within 5 seconds (background task does not block) | smoke | manual + log timestamps | manual only |

### Wave 0 Gaps

- [ ] `tests/test_whatsapp.py` — webhook handler tests (all WA-*, INF-02, INF-04 automated cases)
- [ ] `tests/test_invoice_service.py` — duplicate detection + DB persist tests (VAL-01, VAL-02, VAL-03)
- [ ] `tests/test_providers.py` — TwilioProvider unit tests (signature validation mock, send_message mock)

*(Existing `conftest.py` with `env_setup`, `db_session`, `async_engine` fixtures can be reused directly — no conftest changes needed for Phase 3 tests)*

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No user auth in this phase |
| V3 Session Management | no | Stateless webhook — no sessions |
| V4 Access Control | yes | Allowlist check gates all invoice submissions |
| V5 Input Validation | yes | `MediaContentType0` validated before download; form fields not trusted |
| V6 Cryptography | yes | Twilio `RequestValidator` (HMAC-SHA256) — do not hand-roll |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Spoofed webhook (fake Twilio POST) | Spoofing | `RequestValidator.validate()` on every request → HTTP 401 |
| Non-employee submits invoice | Elevation of Privilege | Allowlist check with `is_active=True` guard |
| Path traversal via filename in MediaUrl | Tampering | Media is downloaded by URL; filename derived from MessageSid, not user input |
| SSRF via crafted MediaUrl0 | Tampering | Only download from `api.twilio.com` domain; validate URL prefix before fetch |
| Auth Token exposure in logs | Information Disclosure | `structlog` must never log `auth_token`, `account_sid` values; follow T-02-02 pattern from Phase 2 |
| Duplicate invoice injection | Tampering | App-level duplicate check + DB UNIQUE constraint backstop |
| Race condition INSERT duplicate | Tampering | `IntegrityError` caught and treated as duplicate |

**SSRF note:** The `download_media(media_url)` method in `TwilioProvider` should validate that the URL starts with `https://api.twilio.com/` before fetching. This prevents a hypothetical future scenario where a malicious `MediaUrl0` points to an internal service. [ASSUMED — not mandated by CONTEXT.md but consistent with ASVS V5]

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual HMAC + reply via TwiML only | `RequestValidator` + REST API for async replies | Twilio SDK v6+ | TwiML cannot defer replies; REST API is the correct path for background reply sending |
| `BackgroundTasks` for async IO work | `asyncio.create_task` with strong reference set | Python 3.11+ | `BackgroundTasks` uses thread pool; async services (AsyncOpenAI, AsyncSession) need the event loop |
| `asyncio.create_task` fire-and-forget | Must store reference in set | Python 3.12 GC change | Tasks without strong references are silently garbage collected |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | No `InvoiceService` class exists after Phase 2 — duplicate check and DB persist logic will be new | Project Structure | If an InvoiceService was added, plan would need to extend it rather than create it |
| A2 | Per-call `AsyncTwilioHttpClient` construction is acceptable at < 20 invoices/day | Pattern 3 | At higher volume, a long-lived client would be needed |
| A3 | SSRF mitigation (URL prefix validation before media download) is the correct approach | Security Domain | Low risk — MediaUrl0 is always from Twilio, but defense-in-depth is appropriate |
| A4 | `ExtractionService.extract()` interface is stable and will not change in Phase 3 | Existing Stack | Phase 2 marked its interface stable; if it changes, background task call site must be updated |

---

## Open Questions (RESOLVED)

1. **DB-level UNIQUE constraint on NULL-containing rows**
   - What we know: Postgres UNIQUE ignores NULLs; two rows with both fields NULL will both insert.
   - What's unclear: Is this acceptable behavior for low-confidence extractions?
   - Recommendation: Yes — low-confidence invoices with no numero/proveedor are not duplicates of each other; the planner should document this explicitly in the migration.

2. **ngrok URL in Settings**
   - What we know: Signature validation requires the exact public URL.
   - What's unclear: Should `WEBHOOK_BASE_URL` be a required setting or derived from the request's Host header?
   - Recommendation: Use `str(request.url)` in the handler — FastAPI reconstructs the full URL from the incoming Host/X-Forwarded-Host headers that ngrok sets. This eliminates a required env var. Validate in testing.

3. **Twilio sandbox opt-in requirement**
   - What we know: Twilio sandbox requires each sender to join by texting "join [keyword]" to the sandbox number.
   - What's unclear: This is a demo operational constraint, not a code constraint.
   - Recommendation: Document in the plan's human verification step. Not a code task.

---

## Sources

### Primary (HIGH confidence)
- Context7 `/twilio/twilio-python` — RequestValidator, AsyncTwilioHttpClient, create_async, send_message patterns
- Context7 `/websites/twilio` — webhook payload fields, media download, sandbox setup
- [Twilio FastAPI webhook tutorial](https://www.twilio.com/en-us/blog/build-secure-twilio-webhook-python-fastapi) — form data handling, signature validation with FastAPI
- [Twilio media resource docs](https://www.twilio.com/docs/messaging/api/media-resource) — authentication requirement for media URLs
- [Python 3.12 asyncio.create_task docs](https://docs.python.org/3.12/library/asyncio-task.html) — weak reference + GC warning + strong reference pattern

### Secondary (MEDIUM confidence)
- [Python CPython issue #91887](https://github.com/python/cpython/issues/91887) — historical context on task GC behavior
- [Twilio WhatsApp media messages tutorial](https://www.twilio.com/docs/whatsapp/tutorial/send-and-receive-media-messages-whatsapp-python) — MediaUrl0, MediaContentType0 field names, one-attachment-per-message constraint
- [Leapcell FastAPI async pitfalls](https://leapcell.io/blog/understanding-pitfalls-of-async-task-management-in-fastapi-requests) — asyncio.create_task vs BackgroundTasks tradeoffs

### Tertiary (LOW confidence)
- WebSearch cross-reference on Twilio media auth requirements — confirmed against official Twilio media-resource docs

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified via pip index and Context7
- Twilio webhook payload fields: HIGH — official Twilio docs via Context7 + WebFetch
- asyncio.create_task GC pattern: HIGH — CPython docs + cpython issue tracker
- Architecture patterns: HIGH — derived from CONTEXT.md decisions + verified SDK docs
- Schema migration pattern: HIGH — alembic + Postgres functional index is established

**Research date:** 2026-05-14
**Valid until:** 2026-06-14 (Twilio SDK API is stable; asyncio behavior is stable in 3.12.x)
