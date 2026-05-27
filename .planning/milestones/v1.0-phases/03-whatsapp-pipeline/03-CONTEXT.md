# Phase 3: WhatsApp Pipeline - Context

**Gathered:** 2026-05-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 3 wires Phases 1 and 2 into the full end-to-end flow: an allowlisted employee sends an invoice photo via WhatsApp → the webhook validates the request, replies immediately (within 5 seconds), and kicks off background extraction → `ExtractionService` extracts and stores the invoice → the employee receives a second reply with the extraction summary.

Deliverables:
- `backend/app/providers/` — `WhatsAppProvider` protocol + `TwilioProvider` implementation (demo) + `MetaCloudProvider` stub (production-ready later)
- `backend/app/handlers/whatsapp.py` — provider-agnostic message handler: allowlist check, media download, `asyncio.create_task()` dispatch, reply sending
- Twilio webhook router wired into `create_app()` (same conditional-registration pattern as extraction router)
- Duplicate detection query in `InvoiceService` or inline in handler
- All Spanish reply messages

**This phase does NOT include:** admin UI, authentication, changes to `ExtractionService` internals, or the Meta Cloud API integration (that's the production upgrade path, not this phase).

</domain>

<decisions>
## Implementation Decisions

### WhatsApp Provider

- **D-01:** Use **Twilio** for the demo deployment. Twilio sandbox requires no business verification and can be set up in 30 minutes. This is the initial implementation.
- **D-02:** Use **Meta WhatsApp Cloud API** (via pywa 3.9.0) for the production path. pywa is already pinned in `CLAUDE.md`. Not implemented in this phase — stub only.
- **D-03:** A `WhatsAppProvider` protocol (ABC or `typing.Protocol`) is required with at minimum three methods: `send_message(to: str, text: str) -> None`, `download_media(media_id: str) -> bytes`, `validate_signature(request: Request) -> bool`. The Twilio and Meta implementations both satisfy this interface. The handler never touches either SDK directly.
- **D-04:** Provider is selected via environment variable (e.g., `WHATSAPP_PROVIDER=twilio|meta`). `Settings` reads this and `create_app()` (or a provider factory) instantiates the correct implementation. Swapping providers = change one env var, no code changes.

### Background Task Mechanism

- **D-05:** Use `asyncio.create_task()` to schedule the extraction coroutine after sending the acknowledgement reply. This is the correct pattern for async work in FastAPI — `ExtractionService` uses `AsyncOpenAI` and `AsyncSession`, both of which require the running event loop. `FastAPI.BackgroundTasks` uses a thread pool and would require awkward `asyncio.run()` wrapping.
- **D-06:** Flow: (1) Validate signature → 401 if invalid. (2) Check allowlist → reject if not found. (3) Send immediate acknowledgement reply. (4) `asyncio.create_task(process_invoice(...))`. (5) Return HTTP 200 to WhatsApp. Extraction runs concurrently without blocking the webhook response.

### Reply Messages (Spanish, friendly tone, emoji allowed)

- **D-07:** **Acknowledgement (WA-01):** `✅ Factura recibida. Procesando...`
- **D-08:** **Extraction summary — auto_saved (WA-03):** Multi-line with core 4 fields:
  ```
  ✅ Factura registrada:
  • Proveedor: {proveedor}
  • Número: {numero_documento}
  • Fecha: {fecha}
  • Total: ${total}
  ```
- **D-09:** **Extraction summary — pending_review (WA-03 + VAL-02):** Same core 4 fields but with a review CTA:
  ```
  ⚠️ Algunos campos no se pudieron leer con certeza. Revisar factura desde la web.
  • Proveedor: {proveedor}
  • Número: {numero_documento}
  • Fecha: {fecha}
  • Total: ${total}
  ```
  (Fields that are `None` are omitted or shown as `—`.)
- **D-10:** **Non-allowlisted sender (WA-02):** `❌ Este número no está autorizado para enviar facturas.`
- **D-11:** **Unreadable image / unsupported format (WA-04):** `❌ No pudimos procesar la imagen. Asegurate de enviar una foto clara de la factura (JPG o PDF).`
- **D-12:** **Duplicate detected (VAL-01):** `🔁 Esta factura ya fue registrada el {fecha_original}. No se guardó de nuevo.`

### Duplicate Detection

- **D-13:** Duplicate check query: `SELECT id, created_at FROM invoices WHERE LOWER(numero_documento) = LOWER(:numero) AND LOWER(proveedor) = LOWER(:proveedor) LIMIT 1`. Case-insensitive exact match on both fields.
- **D-14:** Fuzzy matching on proveedor is deferred to v2. Exact case-insensitive match is sufficient for v1 where the same extraction model produces consistent proveedor strings.
- **D-15:** Race condition backstop: a `UNIQUE` constraint on `(LOWER(numero_documento), LOWER(proveedor))` at the DB level catches concurrent duplicates that slip past the application-level check. If the INSERT raises `UniqueViolation`, treat it the same as a detected duplicate and send the duplicate reply.

### Claude's Discretion

- Internal structure of `WhatsAppProvider` — Protocol vs ABC. Pick the conventional Python approach (likely `typing.Protocol` for duck-typing compatibility with tests).
- Whether `TwilioProvider.validate_signature()` uses the official Twilio request validator or a manual HMAC — use the official Twilio library approach.
- Error logging structure — follow existing `structlog` patterns from Phase 2 (`log.info("whatsapp.received", ...)` style).
- Whether duplicate detection lives in `InvoiceService` or inline in the handler — researcher/planner decides based on what exists after Phase 2.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` — Phase 3 requirements: WA-01, WA-02, WA-03, WA-04, VAL-01, VAL-02, VAL-03, INF-02, INF-04. Authoritative spec for what this phase must satisfy.
- `.planning/ROADMAP.md` §Phase 3 — Success criteria that define done.

### Architecture Decisions
- `CLAUDE.md` §Technology Stack — Pinned versions. `pywa==3.9.0` for the Meta path (stub now, implement later). `twilio` Python SDK for the demo path.
- `CLAUDE.md` §Key Architectural Decisions — WhatsApp abstraction rationale; `BackgroundTasks` vs async pattern guidance.

### Phase 2 Outputs (integrate directly)
- `backend/app/services/extraction.py` — `ExtractionService.extract(image_bytes, filename) -> ExtractionResult`. This is what the background task calls. Do not change its interface.
- `backend/app/services/storage.py` — `LocalStorageBackend`. Already wired into `ExtractionService`. No changes needed.
- `backend/app/config.py` — `Settings` with `whatsapp_token`, `whatsapp_phone_number_id`, `whatsapp_verify_token` already defined. Add `WHATSAPP_PROVIDER` env var.

### Phase 1 Outputs (schema)
- `backend/app/db/models.py` — `Invoice` ORM model. The duplicate detection query runs against `invoices` table. `whatsapp_message_id` and `sender_phone` columns already defined.
- `backend/app/db/session.py` — `AsyncSession` dependency. All DB queries in the handler use this.

### App Factory Pattern
- `backend/app/main.py` — `create_app()` factory. New Twilio webhook router follows the same conditional `include_router()` pattern as the extraction router.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/app/services/extraction.py` — `ExtractionService` + `ExtractionResult`. Phase 3 calls `extract(image_bytes, filename)` from the background task. Interface is stable.
- `backend/app/config.py` — `get_settings()` DI singleton. Add `whatsapp_provider: str = "twilio"` and any Twilio-specific fields (`twilio_account_sid`, `twilio_auth_token`) here.
- `backend/app/main.py` — `create_app()` with conditional router registration. Twilio webhook router follows the same pattern as the debug extraction router.
- `backend/app/db/session.py` — `AsyncSession` via `Depends(get_db)`. The handler uses this for allowlist lookup and duplicate check.
- `structlog` — already configured. Use `log.info("whatsapp.received", sender=..., media_id=...)` style.

### Established Patterns
- `AsyncSession` for all DB writes (D-06 from Phase 1) — applies to invoice INSERT in Phase 3.
- `get_settings()` as `lru_cache` singleton — inject via `Depends(get_settings)`.
- Router imported inside `create_app()` to avoid circular imports — apply same pattern to whatsapp router.
- `structlog` JSON logging — use for all webhook events.

### Integration Points
- `backend/app/providers/` — new directory for `WhatsAppProvider` protocol + implementations.
- `backend/app/handlers/` — new directory (or `backend/app/routers/whatsapp.py`) for the webhook handler.
- `backend/app/db/models.py` — duplicate detection query + new `UNIQUE` constraint migration needed.
- `docker-compose.yml` — add `WHATSAPP_PROVIDER`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` env vars.

</code_context>

<specifics>
## Specific Ideas

- The `WhatsAppProvider` abstraction is the core architectural constraint of this phase. Every decision about Twilio vs Meta flows through it. The handler must never import from `twilio` or `pywa` directly — only through the provider interface.
- The swap to Meta Cloud API later = (1) implement `MetaCloudProvider` using pywa, (2) set `WHATSAPP_PROVIDER=meta`, (3) done. No handler changes.
- The "Revisar factura desde la web" CTA in the pending_review message anticipates the Phase 4 admin UI. No URL is included yet (no production URL) — just the plain phrase.
- Twilio sandbox requires senders to opt in by sending "join [keyword]" to the sandbox number. This is a demo constraint, not a code constraint.

</specifics>

<deferred>
## Deferred Ideas

- **Meta Cloud API full implementation** — pywa wiring, Meta-specific HMAC validation, GET challenge handler. Production upgrade path. Not this phase.
- **Fuzzy proveedor matching** — string similarity for duplicate detection. v2 enhancement (INF-V2-02 in REQUIREMENTS.md).
- **Retry mechanism for failed extractions** — if `ExtractionService.extract()` raises, log and notify sender. A queue-based retry is overkill at <20 invoices/day; simple error reply is sufficient for v1.
- **PDF support** — WA-04 mentions unsupported formats. PDFs are listed in the error reply copy. Full PDF extraction is not scoped here — reject with the error message if format is not a supported image type.

</deferred>

---

*Phase: 3-WhatsApp-Pipeline*
*Context gathered: 2026-05-14*
