# Architecture Patterns

**Domain:** WhatsApp-to-database invoice capture (Argentine AFIP invoices)
**Researched:** 2026-05-12
**Confidence:** HIGH — all major decisions verified against official docs or authoritative sources

---

## Recommended Architecture

```
WhatsApp Provider (Cloud API or Twilio)
         │ HTTP POST webhook
         ▼
┌────────────────────────────────────────────────────────────┐
│  FastAPI Application                                       │
│                                                            │
│  ┌─────────────────┐     ┌──────────────────────────────┐ │
│  │  Webhook Router  │────▶│  WhatsApp Gateway (Protocol) │ │
│  │  /webhook/wa     │     │  - parse_inbound_message()   │ │
│  │  /webhook/twilio │     │  - send_reply()              │ │
│  └─────────────────┘     │  - download_media()          │ │
│           │               └──────────────────────────────┘ │
│           ▼                         │                       │
│  ┌──────────────────┐               │ normalized            │
│  │ BackgroundTasks  │◀──────────────┘ InboundMessage        │
│  │ process_invoice()│                                       │
│  └──────────────────┘                                       │
│           │                                                 │
│           ▼                                                 │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  InvoiceProcessingService                            │  │
│  │  1. Verify sender allowlist                          │  │
│  │  2. Download + upload image to Supabase Storage      │  │
│  │  3. Insert purchase_document (status=extracting)     │  │
│  │  4. Call OpenAI GPT-4o vision → ExtractedInvoice     │  │
│  │  5. Validate extraction (confidence threshold)       │  │
│  │  6. Write purchase_items + update document status    │  │
│  │  7. Reply to sender via WhatsApp gateway             │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Admin API Routes (/api/v1/...)                       │  │
│  │  - GET  /invoices (list, filter, search)              │  │
│  │  - GET  /invoices/{id}                                │  │
│  │  - PATCH /invoices/{id} (edit extracted fields)      │  │
│  │  - POST  /invoices/{id}/confirm                       │  │
│  │  - DELETE /invoices/{id}                              │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
         │ service_role key (bypasses RLS)
         ▼
┌────────────────────────────────────────────────────────────┐
│  Supabase                                                  │
│  ├── Postgres (purchase_documents, purchase_items,         │
│  │             allowed_senders, processing_log)            │
│  └── Storage (invoice-images bucket)                       │
└────────────────────────────────────────────────────────────┘
         ▲ anon key + JWT (Supabase Auth)
         │
┌────────────────────────────────────────────────────────────┐
│  React + Vite Admin UI                                     │
│  - Supabase JS client (direct reads via anon key + RLS)    │
│  - Fetch to FastAPI /api/v1/ for writes and actions        │
│  - Supabase Auth (email/password) for session management   │
└────────────────────────────────────────────────────────────┘
```

---

## Component Boundaries

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| **WhatsApp Gateway (Protocol)** | Translate Cloud API / Twilio payloads to/from a single `InboundMessage` / `OutboundReply` schema. Signature verification lives here. | Webhook Router (inbound), InvoiceProcessingService (replies) |
| **Webhook Router** | Receive HTTP POST, ACK with 200 immediately, hand off to BackgroundTasks | WhatsApp Gateway, BackgroundTasks |
| **InvoiceProcessingService** | Orchestrate the full pipeline: allowlist check → storage upload → DB write → AI extraction → status update → WhatsApp reply | Supabase (DB + Storage), OpenAI, WhatsApp Gateway |
| **ExtractionService** | Call GPT-4o vision, parse response into `ExtractedInvoice` Pydantic model, compute confidence | OpenAI API |
| **Admin API Routes** | CRUD for invoices accessible by authenticated admins. Validate writes, status transitions | Supabase (service_role) |
| **React Admin UI** | List/search/edit invoices. Reads directly from Supabase; writes and action calls go to FastAPI. | Supabase JS (reads), FastAPI /api/v1/ (writes/actions) |
| **Supabase Auth** | Session management for admin UI users. JWT issued on login. | React UI |
| **Supabase Storage** | Stores original invoice images. Backend writes via service_role; frontend reads via signed URLs from FastAPI | InvoiceProcessingService, Admin API |

---

## Data Flow

### Inbound invoice (happy path)

```
1. Employee sends image via WhatsApp
2. Provider POSTs webhook → /webhook/wa (or /webhook/twilio)
3. Gateway verifies HMAC signature, parses to InboundMessage{sender, media_url, message_id}
4. Router returns HTTP 200 immediately (< 5 seconds required by providers)
5. BackgroundTask fires: InvoiceProcessingService.process(message)
   a. Check allowed_senders → reject if not found, reply with rejection
   b. Download media from provider URL
   c. Upload to Supabase Storage bucket "invoice-images/{uuid}.jpg"
   d. INSERT purchase_documents(status="extracting", storage_path, sender_phone, raw_message_id)
   e. Call ExtractionService → ExtractedInvoice (Pydantic model with confidence fields)
   f. If confidence >= threshold:
        UPDATE purchase_documents SET status="auto_saved", ...extracted fields...
        INSERT purchase_items(document_id, ...)
        Reply: "Factura registrada: [summary]. Número: [comprobante]. Total: $[total]"
      Else:
        UPDATE purchase_documents SET status="pending_review"
        Reply: "Factura recibida pero requiere revisión. Un operador la revisará."
6. Duplicate detection: unique constraint on (cuit_proveedor, tipo_comprobante, punto_de_venta, numero_comprobante) prevents double entries
```

### Admin UI data flow

```
Read path:
  React → Supabase JS client (anon key + user JWT)
  RLS policy: SELECT allowed WHERE auth.role() = 'authenticated'
  Direct DB query — no FastAPI roundtrip for reads

Write path:
  React → FastAPI /api/v1/invoices/{id} (PATCH / DELETE / POST confirm)
  FastAPI validates + applies business rules
  FastAPI → Supabase (service_role key, bypasses RLS)

Image display:
  React → FastAPI GET /api/v1/invoices/{id}/image-url
  FastAPI generates Supabase Storage signed URL (short TTL)
  React fetches image directly from signed URL
```

---

## Question Answers

### 1. Synchronous vs Async Processing

**Decision: FastAPI BackgroundTasks — no external worker needed for 20 invoices/day.**

At 20 invoices/day, the processing pipeline (image download + GPT-4o call + DB write) takes roughly 3-10 seconds total. WhatsApp Cloud API and Twilio both require a 200 ACK within ~5 seconds or they will retry. The correct pattern is:

1. Webhook endpoint does only: signature verification + minimal DB log + 200 response
2. `background_tasks.add_task(process_invoice, message)` fires after response is sent

FastAPI's `BackgroundTasks` runs tasks in the same process after the response. This is sufficient for < 20 concurrent operations and requires no Redis, Celery, or ARQ. The failure mode — if the process restarts mid-extraction — is acceptable at this volume. The `processing_log` table (see schema) can flag stuck `extracting` records for manual reprocessing.

**Upgrade path:** If volume grows to hundreds/day or crash-safe delivery is required, add ARQ (async Redis queue) with minimal code change — same service layer, different dispatcher.

### 2. WhatsApp Abstraction Layer

**Use a Python Protocol class defining the gateway contract. Each provider is a concrete implementation.**

```python
# app/gateways/base.py
from typing import Protocol
from dataclasses import dataclass

@dataclass
class InboundMessage:
    sender_phone: str       # E.164 format e.g. "+5491112345678"
    message_id: str         # provider-specific dedup ID
    media_url: str | None   # temporary media download URL
    text: str | None        # text body if any
    timestamp: int          # Unix epoch

class WhatsAppGateway(Protocol):
    def verify_signature(self, body: bytes, headers: dict) -> bool: ...
    def parse_inbound(self, payload: dict) -> InboundMessage: ...
    def send_reply(self, to: str, message: str) -> None: ...
    def download_media(self, media_url: str, headers: dict | None = None) -> bytes: ...

# app/gateways/meta.py  — implements WhatsAppGateway
# app/gateways/twilio.py — implements WhatsAppGateway
```

The webhook router has two endpoints (`/webhook/wa` for Meta, `/webhook/twilio` for Twilio) but both resolve to the same `gateway: WhatsAppGateway` dependency and call `process_invoice(gateway, message)`. Switching providers = swap the injected gateway. The pipeline code never imports Meta or Twilio directly.

**Key differences to encapsulate:**
- Signature verification: Meta uses `X-Hub-Signature-256`, Twilio uses `X-Twilio-Signature`
- Payload shape: Meta is nested JSON; Twilio is form-encoded
- Media download: Meta requires Authorization Bearer with page access token; Twilio URL is public but short-lived
- Phone number format: Meta sends `+549...`; Twilio may omit the `+`

### 3. Database Schema

**Core tables:**

```sql
-- Allowlisted senders (employees who can submit)
CREATE TABLE allowed_senders (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  phone       TEXT NOT NULL UNIQUE,   -- E.164 format
  name        TEXT NOT NULL,
  is_active   BOOLEAN NOT NULL DEFAULT true,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per invoice submission
CREATE TABLE purchase_documents (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  -- Submission metadata
  status                TEXT NOT NULL DEFAULT 'extracting'
                            CHECK (status IN ('extracting','pending_review','auto_saved','confirmed','rejected')),
  sender_phone          TEXT NOT NULL REFERENCES allowed_senders(phone),
  storage_path          TEXT,           -- Supabase Storage key
  raw_message_id        TEXT,           -- provider dedup ID
  submitted_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Argentine invoice fields (null = not found in image)
  tipo_comprobante      TEXT,           -- 'Factura A', 'Factura B', 'Remito', etc.
  punto_de_venta        TEXT,
  numero_comprobante    TEXT,
  cuit_proveedor        TEXT,
  razon_social          TEXT,
  fecha_emision         DATE,
  cae                   TEXT,
  fecha_vencimiento_cae DATE,
  condicion_iva         TEXT,
  neto_gravado          NUMERIC(14,2),
  iva                   NUMERIC(14,2),
  percepciones          NUMERIC(14,2),
  total                 NUMERIC(14,2),
  moneda                TEXT DEFAULT 'ARS',
  -- AI metadata
  extraction_confidence NUMERIC(4,3),  -- 0.000–1.000
  extraction_model      TEXT,
  -- Review
  reviewed_by           UUID REFERENCES auth.users(id),
  reviewed_at           TIMESTAMPTZ,
  notes                 TEXT,
  -- Timestamps
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Duplicate guard: same invoice from same supplier
  UNIQUE NULLS NOT DISTINCT (cuit_proveedor, tipo_comprobante, punto_de_venta, numero_comprobante)
);

-- Line items extracted from the invoice
CREATE TABLE purchase_items (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id    UUID NOT NULL REFERENCES purchase_documents(id) ON DELETE CASCADE,
  description    TEXT,
  quantity       NUMERIC(12,4),
  unit_price     NUMERIC(14,2),
  subtotal       NUMERIC(14,2),
  sort_order     SMALLINT NOT NULL DEFAULT 0
);

-- Optional: audit log of status transitions
CREATE TABLE processing_log (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id  UUID NOT NULL REFERENCES purchase_documents(id) ON DELETE CASCADE,
  from_status  TEXT,
  to_status    TEXT NOT NULL,
  actor        TEXT NOT NULL,   -- 'system', 'admin:{user_id}'
  detail       TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for common queries
CREATE INDEX idx_purchase_documents_status ON purchase_documents(status);
CREATE INDEX idx_purchase_documents_submitted_at ON purchase_documents(submitted_at DESC);
CREATE INDEX idx_purchase_documents_cuit ON purchase_documents(cuit_proveedor);
CREATE INDEX idx_purchase_documents_sender ON purchase_documents(sender_phone);
```

**What the original question listed + what was added:**
- `purchase_documents` — core table with Argentine AFIP fields + status + AI metadata
- `purchase_items` — line items with cascade delete
- `allowed_senders` — allowlist
- `processing_log` — added: audit trail of status transitions (lightweight, helps detect stuck extractions)

**Not needed for v1:** A separate `suppliers` normalized table — CUIT is enough to identify supplier, normalization can wait until reporting requirements emerge.

### 4. React Frontend — Reads vs Writes

**Direct Supabase JS for reads; FastAPI for writes and stateful actions.**

Rationale:
- Reads are high-frequency and need filtering/sorting. Supabase JS gives a fluent query builder with automatic type safety. Going through FastAPI adds an unnecessary hop and forces you to re-implement query building.
- Writes and actions (confirm, edit extracted fields, delete) need business-rule validation (e.g., can only confirm a `pending_review` document, not a `confirmed` one). These checks belong in the service layer, not the DB. FastAPI enforces them cleanly.
- Supabase Auth issues a JWT; the React client attaches it automatically to Supabase JS queries. RLS policies restrict reads to authenticated users. FastAPI validates the same JWT via `python-jose` or `supabase-py` to authenticate admin API calls.

```
React reads:  supabase.from('purchase_documents').select('*').order('submitted_at', {ascending: false})
React writes: fetch('/api/v1/invoices/{id}', { method: 'PATCH', body: ... })
```

**Signed URLs for images:** React never calls Supabase Storage directly for private images. It calls `GET /api/v1/invoices/{id}/image-url` → FastAPI generates a short-lived signed URL (e.g., 5-minute TTL) using the service_role client → returns URL to React → React displays.

### 5. Validation Logic — Where It Lives

**Two-layer model: Pydantic for shape/format, Service layer for business rules.**

| Validation Type | Where | Example |
|----------------|-------|---------|
| Type, format, required fields | Pydantic model | `cuit_proveedor: str | None`, `total: Annotated[float, Field(ge=0)]` |
| Cross-field arithmetic | Pydantic `@model_validator` | `neto + iva + percepciones ≈ total (±1%)` |
| DB-dependent checks | Service layer | Duplicate detection (before insert), sender allowlist lookup |
| State transition rules | Service layer | Only `pending_review` → `confirmed`/`rejected` is allowed |
| DB hard constraints | Postgres | UNIQUE constraint on invoice identity fields, CHECK on status enum |

**Never put DB queries inside Pydantic validators.** Pydantic models are used in two contexts: validating AI extraction output (no DB available) and validating API request bodies (DB available but should stay in service). Mixing these causes coupling and unpredictable behavior.

### 6. Status State Machine

```
                     ┌─────────┐
     webhook arrives │         │
         ───────────▶│extracting│
                     └────┬────┘
                          │
              ┌───────────┴──────────┐
              │ confidence >= 0.85   │ confidence < 0.85
              │ (or all required     │ (required fields
              │  fields present)     │  missing/uncertain)
              ▼                      ▼
         ┌──────────┐         ┌──────────────┐
         │auto_saved│         │pending_review│
         └────┬─────┘         └──────┬───────┘
              │                      │
              │ admin confirms        │ admin reviews
              ▼                      ▼
         ┌───────────┐         ┌───────────┐
         │ confirmed │         │ confirmed │  (or rejected)
         └───────────┘         └───────────┘

Also from any state:
     ────────────────────────────────▶ rejected  (admin explicit action)
```

**State transition rules (enforced in service layer):**
- `extracting` → `auto_saved` or `pending_review` — system only
- `extracting` → `rejected` — system only (e.g., media type not image, sender blocked)
- `auto_saved` → `confirmed` — admin only
- `auto_saved` → `pending_review` — admin only (manually flag for review)
- `pending_review` → `confirmed` — admin only (after editing if needed)
- `pending_review` → `rejected` — admin only
- `confirmed` → unconfirm is NOT allowed (append-only at that point; create a correction record)
- `rejected` → not reversible in v1

**Stuck detection:** A cron job or startup check flags documents stuck in `extracting` for > 5 minutes. These are logged in `processing_log` and surfaced in the UI as an error state.

---

## Suggested Build Order (Phase Dependencies)

```
Phase 1: Supabase schema + Pydantic models
  → Tables, migrations, RLS policies, storage bucket
  → ExtractedInvoice Pydantic model (shapes the extraction contract)
  → No other components depend on this; everything else depends on it

Phase 2: WhatsApp Gateway abstraction + ExtractionService
  → WhatsApp Protocol class + one concrete implementation (pick Cloud API first)
  → ExtractionService: GPT-4o call → ExtractedInvoice → confidence score
  → Can be tested in isolation with mock gateway and test images

Phase 3: Webhook router + InvoiceProcessingService (pipeline integration)
  → Wire gateway + extraction + DB writes + BackgroundTasks
  → Full end-to-end flow: WhatsApp image → DB record
  → Depends on Phase 1 (schema) and Phase 2 (gateway + extraction)

Phase 4: Admin FastAPI routes
  → CRUD endpoints, JWT auth middleware, signed URL generation
  → Depends on Phase 1 (schema) and Phase 3 (status machine logic)

Phase 5: React Admin UI
  → Can start in parallel with Phase 4 using mock data
  → Supabase JS client setup, auth flow, invoice list/detail/edit views
  → Full integration requires Phase 4 complete

Phase 6: Second WhatsApp provider (Twilio)
  → Implement the Twilio concrete gateway
  → No pipeline changes needed — gateway abstraction isolates this
```

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Synchronous OpenAI call inside webhook handler
**What:** Await the GPT-4o API call before returning 200 to the provider.
**Why bad:** GPT-4o latency is 2-8s. Providers time out in ~5s and retry — you get duplicate processing.
**Instead:** Return 200 immediately. Fire BackgroundTasks.

### Anti-Pattern 2: Pydantic validators with DB lookups
**What:** Validate sender allowlist inside a Pydantic `@field_validator`.
**Why bad:** Couples data models to infrastructure. Makes models untestable in isolation. Validators run on deserialization, not just on API boundaries.
**Instead:** Sender check is first step in `InvoiceProcessingService.process()`.

### Anti-Pattern 3: Anon key on backend
**What:** Initialize the FastAPI Supabase client with the anon key.
**Why bad:** Anon key respects RLS. The backend needs to write to tables that RLS would block for anonymous users, and it needs to create signed URLs.
**Instead:** FastAPI always uses the service_role key (server-side only, never shipped to browser). React uses the anon key + user JWT.

### Anti-Pattern 4: Provider-specific code in the pipeline
**What:** `if provider == "twilio": ... else: ...` branches inside InvoiceProcessingService.
**Why bad:** Adding a third provider requires touching business logic. Testing requires mocking two providers.
**Instead:** The gateway Protocol hides all provider differences. The pipeline only sees `InboundMessage`.

### Anti-Pattern 5: Storing media URLs instead of uploading to Storage
**What:** Save the temporary `media_url` from the provider payload to the DB instead of downloading and re-uploading to Supabase Storage.
**Why bad:** Provider media URLs expire (Meta: 5 min, Twilio: similar). You lose the audit trail.
**Instead:** Download media in the background task and immediately upload to `invoice-images/` bucket.

---

## Scalability Considerations

| Concern | At 20/day (v1) | At 500/day | At 5000/day |
|---------|---------------|-----------|-------------|
| Processing queue | FastAPI BackgroundTasks (in-process) | ARQ + Redis | ARQ or Celery with multiple workers |
| DB connections | Single Supabase connection pool sufficient | PgBouncer (Supabase handles this) | Read replicas for admin UI queries |
| OpenAI rate limits | No issue | Check tier limits (~TPM) | Implement retry with exponential backoff |
| Storage | Supabase Storage (generous free tier) | Standard pricing, no changes | CDN for image delivery |
| Concurrent webhooks | Single process handles fine | Multiple FastAPI replicas | Load balancer in front |

---

## Sources

- FastAPI BackgroundTasks official docs: https://fastapi.tiangolo.com/tutorial/background-tasks/
- FastAPI BackgroundTasks reference: https://fastapi.tiangolo.com/reference/background/
- Supabase RLS + service_role key: https://supabase.com/docs/guides/database/postgres/row-level-security
- Supabase service key guidance: https://supabase.com/docs/guides/api/api-keys
- OpenAI Structured Outputs with vision: https://developers.openai.com/api/docs/guides/structured-outputs
- WhatsApp Cloud API webhook docs: https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/
- PyWa (Python WhatsApp Cloud API wrapper, for reference): https://pywa.readthedocs.io/
- FastAPI webhook implementation best practices: https://blog.greeden.me/en/2026/04/07/a-practical-guide-to-safely-implementing-webhook-receiver-apis-in-fastapi-from-signature-verification-and-retry-handling-to-idempotency-and-asynchronous-processing/
- Pydantic validation vs service layer separation (MEDIUM): Multiple sources agree on this split
