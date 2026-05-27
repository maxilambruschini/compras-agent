---
phase: 03-whatsapp-pipeline
plan: "01"
subsystem: whatsapp-inbound
tags:
  - whatsapp
  - twilio
  - webhook
  - signature
  - allowlist
  - provider-protocol
  - alembic

dependency_graph:
  requires:
    - 02-extraction-pipeline (ExtractionService, StorageBackend, InvoiceModel)
    - 01-foundation (SenderAllowlist table, db/session, config Settings)
  provides:
    - POST /whatsapp/webhook (signature → allowlist → ack → create_task)
    - WhatsAppProvider Protocol (base.py)
    - TwilioProvider (twilio.py)
    - MetaCloudProvider stub (meta.py)
    - _background_tasks, _processed_message_sids, get_whatsapp_provider (Plan 02 imports)
    - uq_invoices_numero_proveedor_lower functional UNIQUE INDEX (Alembic b1c2d3e4f5a6)
  affects:
    - 03-02: imports _process_invoice_placeholder, get_whatsapp_provider, _background_tasks

tech_stack:
  added:
    - twilio==9.10.9 (RequestValidator, AsyncTwilioHttpClient, REST Client)
    - httpx (media download with Basic Auth — already in project)
  patterns:
    - WhatsAppProvider typing.Protocol + @runtime_checkable (mirrors StorageBackend)
    - get_whatsapp_provider factory as sole provider construction site (mirrors get_extraction_service)
    - asyncio.create_task + module-level _background_tasks set (GC prevention, Pattern 4)
    - In-memory _processed_message_sids dedupe set (MessageSid idempotency)
    - WEBHOOK_BASE_URL setting for reverse-proxy/ngrok signature validation
    - HMAC-SHA1 via Twilio RequestValidator (not SHA-256 — algorithm clarified in docstring)

key_files:
  created:
    - backend/app/providers/__init__.py
    - backend/app/providers/base.py (WhatsAppProvider Protocol)
    - backend/app/providers/twilio.py (TwilioProvider with SSRF guard + HMAC-SHA1 docstring)
    - backend/app/providers/meta.py (MetaCloudProvider stub)
    - backend/app/routers/whatsapp.py (POST /whatsapp/webhook)
    - backend/alembic/versions/add_invoice_duplicate_constraint.py (revision b1c2d3e4f5a6)
    - backend/tests/test_providers.py (4 TwilioProvider unit tests)
    - backend/tests/test_whatsapp.py (8 webhook integration tests)
  modified:
    - backend/requirements.txt (added twilio==9.10.9)
    - backend/app/config.py (5 new fields: whatsapp_provider, twilio_*, webhook_base_url)
    - backend/app/main.py (unconditional whatsapp_router registration)
    - backend/tests/conftest.py (4 new Twilio env var setenv calls)
    - docker-compose.yml (5 new WhatsApp/Twilio env var forwarding entries)

decisions:
  - "WhatsApp provider as typing.Protocol + @runtime_checkable — no forced inheritance, swappable at startup via WHATSAPP_PROVIDER env var"
  - "Twilio signature validation uses HMAC-SHA1 (RequestValidator) — INF-02 HMAC-SHA256 wording refers to security property not literal algorithm (resolved Codex HIGH concern #1)"
  - "asyncio.create_task v1 approach documented with explicit production upgrade path: Celery/ARQ when >100 invoices/day (resolved Codex HIGH concern #2)"
  - "WEBHOOK_BASE_URL optional setting: when set, overrides str(request.url) for signature validation — supports ngrok/reverse-proxy deployments (resolved Codex MEDIUM concern #3)"
  - "_processed_message_sids in-memory set deduplicated MessageSid retries — acceptable for v1; cleared on restart; UNIQUE INDEX is DB-level backstop (resolved Codex MEDIUM concern #4)"
  - "Functional UNIQUE INDEX uq_invoices_numero_proveedor_lower uses WHERE NOT NULL clause — correct behavior for partial extractions where either campo may be NULL"

metrics:
  duration: "~45 minutes"
  completed: "2026-05-14"
  tasks_completed: 3
  tasks_total: 3
  files_created: 8
  files_modified: 5
  tests_added: 12
  tests_passing: 51
---

# Phase 3 Plan 01: WhatsApp Inbound Slice Summary

**One-liner:** Twilio webhook with HMAC-SHA1 signature validation, allowlist gating, Spanish ack/rejection replies, asyncio.create_task background hook, MessageSid idempotency, and functional UNIQUE INDEX migration.

## What Was Built

This plan delivers the thinnest end-to-end WhatsApp inbound slice: a Twilio webhook that validates inbound signatures, gates on the sender allowlist, sends an immediate Spanish acknowledgement (or rejection), and schedules a background task placeholder within Twilio's 5-second window.

### Components

**Provider package** (`app/providers/`):
- `base.py`: `WhatsAppProvider` `@runtime_checkable` Protocol — the only import surface for the webhook router. Mirrors `StorageBackend` pattern from Phase 2.
- `twilio.py`: `TwilioProvider` implementing the Protocol via Twilio's SDK. Key design points: `RequestValidator` for HMAC-SHA1 signature validation (with explicit algorithm-clarification docstring resolving 03-REVIEWS.md Codex HIGH concern #1); `AsyncTwilioHttpClient` for async message sending; httpx Basic Auth for media download; SSRF guard rejecting non-`https://api.twilio.com/` URLs.
- `meta.py`: `MetaCloudProvider` stub raising `NotImplementedError` on all methods — production path placeholder.

**Webhook router** (`app/routers/whatsapp.py`):
- POST `/whatsapp/webhook` handler following the D-06 flow: validate signature → MessageSid dedupe → allowlist gate → ack → `asyncio.create_task`.
- Module docstring documents the v1 `asyncio.create_task` limitation and production upgrade path (resolves Codex HIGH concern #2).
- `_compute_effective_url` helper: uses `WEBHOOK_BASE_URL` when set, falling back to `str(request.url)` — supports ngrok/reverse-proxy (resolves Codex MEDIUM concern #3).
- `_processed_message_sids` in-memory set: MessageSid idempotency gate before any business logic (resolves Codex MEDIUM concern #4).
- `_background_tasks` module-level set: strong reference preventing GC of in-flight tasks.
- `_process_invoice_placeholder`: stable-signature coroutine for Plan 02 to replace.

**Alembic migration** (`add_invoice_duplicate_constraint.py`, revision `b1c2d3e4f5a6`):
- Adds `uq_invoices_numero_proveedor_lower` functional UNIQUE INDEX on `LOWER(numero_documento), LOWER(proveedor) WHERE NOT NULL`.
- Applied and verified on the dev Postgres DB. Downgrade tested.

**Settings** (`app/config.py`):
- 5 new optional fields: `whatsapp_provider`, `twilio_account_sid`, `twilio_auth_token`, `twilio_from_number`, `webhook_base_url`.
- All have safe defaults; Twilio credentials validated at provider construction time.

## Test Results

- **12 new tests** added (4 provider unit tests, 8 webhook integration tests).
- **51 tests passing** (including all Phase 1 + Phase 2 tests — no regressions).
- 1 integration test deselected (requires real OpenAI key).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_duplicate_message_sid assertion adjusted for fast placeholder**
- **Found during:** Task 3 execution
- **Issue:** Test asserted `len(_background_tasks) == 1` after two POSTs, but the `_process_invoice_placeholder` coroutine runs `asyncio.sleep(0)` and completes before the assert, causing `_background_tasks` to be empty (discard callback already fired).
- **Fix:** Changed assertion to verify `"SM-dedupe-001" in _processed_message_sids` (which proves the MessageSid was recorded) and `mock_provider.send_message.await_count == 1` (which proves the second POST was deduplicated). Both assertions are stronger behavioral proofs than checking the transient set size.
- **Files modified:** `backend/tests/test_whatsapp.py`
- **Commit:** 7969b56

## Known Stubs

| Stub | File | Line | Reason |
|------|------|------|--------|
| `_process_invoice_placeholder` | `app/routers/whatsapp.py` | ~155 | Placeholder coroutine — Plan 02 replaces with real `process_invoice` pipeline (download → extract → save → reply) |
| `MetaCloudProvider` | `app/providers/meta.py` | ~1 | Raises NotImplementedError — future implementation when migrating from Twilio to Meta Cloud API |

These stubs do NOT prevent the plan's goal (WA-01, WA-02, INF-02, INF-04) from being achieved — the ack/rejection flow is fully wired via TwilioProvider.

## Threat Flags

No new security-relevant surfaces beyond what the plan's `<threat_model>` covers. All STRIDE threats (T-3-01 through T-3-07, T-3-13) were mitigated as specified.

## Self-Check

### Files created/exist
- backend/app/providers/__init__.py: EXISTS
- backend/app/providers/base.py: EXISTS
- backend/app/providers/twilio.py: EXISTS
- backend/app/providers/meta.py: EXISTS
- backend/app/routers/whatsapp.py: EXISTS
- backend/alembic/versions/add_invoice_duplicate_constraint.py: EXISTS
- backend/tests/test_providers.py: EXISTS
- backend/tests/test_whatsapp.py: EXISTS

### Commits
- 4a96315: feat(03-01): Wave 0 test scaffolds, Settings extension, twilio dep pin
- cba978e: feat(03-01): WhatsAppProvider Protocol + TwilioProvider + MetaCloudProvider + migration
- 7969b56: feat(03-01): Twilio webhook router, main.py registration, webhook tests GREEN

## Self-Check: PASSED
