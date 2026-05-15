---
phase: 03-whatsapp-pipeline
verified: 2026-05-14T17:50:00Z
status: human_needed
score: 9/9 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Allowlisted happy path (WA-01 + WA-03 + INF-04)"
    expected: "ACK reply arrives within 5s; second summary reply with Proveedor/Número/Fecha/Total arrives within ~30s; invoice row and image_path present in DB; image file exists on disk"
    why_human: "INF-04 timing can only be observed against a live Twilio sandbox. The two-message flow, real HMAC-SHA1 signature validation, and original-file retention via LocalStorageBackend require a real WhatsApp session."
  - test: "Pending-review path (VAL-02)"
    expected: "Blurry photo produces reply starting with '⚠️ Algunos campos no se pudieron leer...'; DB row has status=pending_review"
    why_human: "Requires real GPT-4o extraction returning low confidence score — not testable without live OpenAI + Twilio."
  - test: "Duplicate detection end-to-end (VAL-01)"
    expected: "Resending same invoice produces '🔁 Esta factura ya fue registrada el YYYY-MM-DD...'; DB count stays at 1"
    why_human: "Requires two sequential real WhatsApp submissions with the same document data."
  - test: "Unsupported media type via live WhatsApp (WA-04)"
    expected: "PDF sent over WhatsApp produces unreadable-image reply; no DB row inserted"
    why_human: "Requires Twilio sandbox to deliver a real PDF with MediaContentType0=application/pdf."
  - test: "Non-allowlisted sender (WA-02)"
    expected: "Phone not in sender_allowlist receives rejection reply; no DB row"
    why_human: "Requires a second real WhatsApp number not in the allowlist table."
  - test: "Invalid HMAC signature (INF-02)"
    expected: "curl with bogus X-Twilio-Signature header receives HTTP 401"
    why_human: "Requires the ngrok tunnel to be live so Twilio signature validation uses the real public URL via WEBHOOK_BASE_URL. Unit tests cover this path but live verification of the URL resolution is part of the UAT."
deferred: []
gaps: []
---

# Phase 3: WhatsApp Pipeline Verification Report

**Phase Goal:** An allowlisted employee can send an invoice photo on WhatsApp and receive a reply; the invoice data is stored in the database within seconds
**Verified:** 2026-05-14T17:50:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Inbound POST /whatsapp/webhook with invalid X-Twilio-Signature returns HTTP 401 | VERIFIED | `test_invalid_signature` passes; handler raises HTTPException(401) at line 513; `test_invalid_signature` confirmed green in pytest run |
| 2 | Inbound POST with valid signature from allowlisted sender returns 200 and triggers ack via TwilioProvider.send_message | VERIFIED | `test_valid_signature_allowlisted_sends_ack` passes; ACK_REPLY constant wired at line 545; route registered unconditionally in create_app() |
| 3 | Non-allowlisted sender returns 200 with Spanish rejection, no invoice processing or DB writes | VERIFIED | `test_non_allowlisted` passes; NON_ALLOWLISTED_REPLY wired at line 533; comment at line 535 documents no DB writes; test asserts zero invoice rows |
| 4 | Webhook handler schedules background work via asyncio.create_task; task reference retained in module-level _background_tasks set | VERIFIED | `_background_tasks` set defined at line 66; `asyncio.create_task(process_invoice(...))` at line 559; `_background_tasks.add(task)` + `task.add_done_callback(_background_tasks.discard)` at lines 568-569; `test_background_task_scheduled` passes |
| 5 | Duplicate MessageSid returns 200 without scheduling a second task or sending a second ack | VERIFIED | `_processed_message_sids` set defined at line 71; gate at lines 517-520; `test_duplicate_message_sid` passes (asserts `send_message.await_count == 1` and MessageSid recorded in set) |
| 6 | WhatsAppProvider Protocol is the only import surface used by routers/whatsapp.py (no direct twilio imports in router) | VERIFIED | `grep "from twilio|import twilio" backend/app/routers/whatsapp.py` returns 0 matches; TwilioProvider imported lazily inside get_whatsapp_provider factory function only |
| 7 | When WEBHOOK_BASE_URL is set, signature validation uses that URL with /whatsapp/webhook path | VERIFIED | `_compute_effective_url` helper at line 166; `test_webhook_base_url_overrides_request_url` passes; `test_webhook_url_passed_to_validator` passes |
| 8 | After extraction completes, sender receives summary reply (D-08 auto_saved or D-09 pending_review) with proveedor, número, fecha, total | VERIFIED | `format_summary_reply` at line 242; `_compute_total` at line 213; `test_auto_saved_reply`, `test_pending_review_reply`, `test_summary_format`, `test_summary_omits_missing_fields` all pass; iva_rate bug fixed in commit 4e7d482 (was dividing fraction by 100 again; removed) |
| 9 | Duplicate submission produces exactly one Invoice row and D-12 reply with real original fecha; race-condition path uses find_existing_for_race | VERIFIED | `test_duplicate_app_level` passes; `test_duplicate_race_integrity_error` passes; `test_duplicate_race_integrity_error_no_existing_row` (em-dash edge case) passes; `find_existing_for_race` wired at line 441 |

**Score:** 9/9 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/providers/base.py` | WhatsAppProvider @runtime_checkable Protocol with 3 methods | VERIFIED | Exists; `@runtime_checkable` at line 19; all 3 method stubs present |
| `backend/app/providers/twilio.py` | TwilioProvider satisfying Protocol; HMAC-SHA1 docstring; SSRF guard | VERIFIED | Exists; `isinstance(TwilioProvider(...), WhatsAppProvider)` returns True; HMAC-SHA1 docstring present; TWILIO_MEDIA_URL_PREFIX guard at line 124 |
| `backend/app/providers/meta.py` | MetaCloudProvider stub raising NotImplementedError | VERIFIED | Exists; raises NotImplementedError on all methods |
| `backend/app/routers/whatsapp.py` | POST /whatsapp/webhook handler; _background_tasks; _processed_message_sids; process_invoice pipeline | VERIFIED | Exists; 573 lines; all required symbols present; process_invoice replaces placeholder (grep for _process_invoice_placeholder returns 0) |
| `backend/app/services/invoice.py` | InvoiceService with find_duplicate, find_existing_for_race, save_invoice | VERIFIED | Exists; all 3 methods present and async; func.lower() used 4 times; IntegrityError caught + rollback; image_path persisted |
| `backend/alembic/versions/add_invoice_duplicate_constraint.py` | Functional UNIQUE INDEX migration (revision b1c2d3e4f5a6, down_revision 9f9e9cf65e1e) | VERIFIED | Exists; down_revision='9f9e9cf65e1e' correct; CREATE UNIQUE INDEX uq_invoices_numero_proveedor_lower with WHERE NOT NULL clause; DROP INDEX IF EXISTS in downgrade |
| `backend/tests/test_whatsapp.py` | 24 webhook tests (8 from Plan 01, 16 from Plan 02) | VERIFIED | 24 tests collected; all pass; no skips |
| `backend/tests/test_providers.py` | 4 TwilioProvider unit tests | VERIFIED | 4 tests collected; all pass |
| `backend/tests/test_invoice_service.py` | 9 InvoiceService unit tests | VERIFIED | 9 tests collected; all pass |
| `.planning/phases/03-whatsapp-pipeline/03-HUMAN-UAT.md` | 6 deferred Twilio sandbox scenarios | VERIFIED | Exists; 6 scenarios documented with [pending] status; deferred_until: after Phase 4 |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `backend/app/main.py::create_app` | `backend/app/routers/whatsapp.py::router` | `app.include_router(whatsapp_router, prefix='/whatsapp', tags=['whatsapp'])` | WIRED | Lines 55-57 in main.py; unconditional (outside if settings.debug block); route /whatsapp/webhook confirmed in runtime route table |
| `backend/app/routers/whatsapp.py::get_whatsapp_provider` | `backend/app/providers/twilio.py::TwilioProvider` | Settings-driven factory; `settings.whatsapp_provider == 'twilio'` constructs TwilioProvider | WIRED | Lines 131-150; lazy import inside factory; missing credentials raise RuntimeError |
| `backend/app/routers/whatsapp.py::whatsapp_webhook` | `WhatsAppProvider.validate_signature` | `provider.validate_signature(effective_url, form_data, signature)` | WIRED | Line 512; effective_url computed by _compute_effective_url helper |
| `backend/app/routers/whatsapp.py::process_invoice` | `backend/app/services/extraction.py::ExtractionService.extract` | `await extraction_service.extract(image_bytes, filename)` | WIRED | Line 415; ExtractionService constructed inline in background task |
| `backend/app/routers/whatsapp.py::process_invoice` | `backend/app/services/invoice.py::InvoiceService.find_duplicate` | `await invoice_service.find_duplicate(session, ...)` | WIRED | Line 427 |
| `backend/app/routers/whatsapp.py::process_invoice` | `backend/app/services/invoice.py::InvoiceService.save_invoice` | `await invoice_service.save_invoice(session, result, message_sid, sender)` | WIRED | Line 437 |
| `backend/app/routers/whatsapp.py::_validate_image_bytes` | JPEG/PNG magic-byte signatures | `data[:2] == JPEG_MAGIC or data[:4] == PNG_MAGIC` | WIRED | Lines 206-210; called at line 399 before extraction |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `whatsapp.py::format_summary_reply` | `result.invoice` | `ExtractionService.extract(image_bytes, filename)` returns `ExtractionResult` with live GPT-4o extraction | Yes — real async OpenAI call inside ExtractionService | FLOWING |
| `invoice.py::save_invoice` | `Invoice` ORM object | Fields mapped from `ExtractionResult.invoice`; committed to Postgres via AsyncSession | Yes — `session.commit()` writes to DB | FLOWING |
| `invoice.py::find_duplicate` | `existing: Invoice | None` | `SELECT ... WHERE func.lower(numero) == func.lower(proveedor)` against Postgres | Yes — real DB query | FLOWING |
| `whatsapp.py::process_invoice` | `image_bytes` | `provider.download_media(MediaUrl0)` — httpx GET with Basic Auth to api.twilio.com | Yes — real HTTPS download | FLOWING (unit-tested with mocks; live download requires UAT) |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All Phase 3 tests pass | `pytest tests/test_whatsapp.py tests/test_providers.py tests/test_invoice_service.py -q` | 37 passed in 3.80s | PASS |
| Full suite (no integration) passes | `pytest -m "not integration" -q` | 76 passed, 1 deselected in 3.86s | PASS |
| /whatsapp/webhook in route table | Python import check via create_app() | Route confirmed | PASS |
| TwilioProvider satisfies Protocol | `isinstance(TwilioProvider(...), WhatsAppProvider)` | True | PASS |
| All Plan 02 module exports importable | Import check for process_invoice, format_summary_reply, _validate_image_bytes, etc. | All OK | PASS |
| InvoiceService 3 methods present and async | Attribute + iscoroutinefunction checks | All OK | PASS |
| _process_invoice_placeholder removed | grep search | 0 matches — removed | PASS |
| iva_rate bug fix confirmed (CR-01) | grep for /100 division in _compute_total | No division found; commit 4e7d482 confirmed in git log | PASS |
| No debt markers (TBD/FIXME/XXX) in production files | grep across all 6 phase 3 production files | 0 matches | PASS |

---

### Probe Execution

No probe scripts declared in PLAN frontmatter. No conventional `scripts/*/tests/probe-*.sh` files found for this phase. Step 7c: SKIPPED (no probes).

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| WA-01 | 03-01 | Employee sends invoice photo and receives acknowledgement reply | SATISFIED | ACK_REPLY constant; test_valid_signature_allowlisted_sends_ack passes |
| WA-02 | 03-01 | System rejects non-allowlisted numbers with Spanish message | SATISFIED | NON_ALLOWLISTED_REPLY constant; test_non_allowlisted passes; no DB writes asserted |
| WA-03 | 03-02 | System replies with extraction summary after processing | SATISFIED | format_summary_reply wired in process_invoice; test_auto_saved_reply and test_pending_review_reply pass |
| WA-04 | 03-02 | System notifies sender if image unreadable or format unsupported | SATISFIED | Two-layer defense: MIME guard + magic-byte guard; test_unsupported_media_type, test_invalid_magic_bytes pass |
| VAL-01 | 03-02 | Duplicate detection via numero_documento + proveedor; not saved again | SATISFIED | InvoiceService.find_duplicate (LOWER() match); UNIQUE INDEX backstop; test_duplicate_app_level and test_duplicate_race_integrity_error pass |
| VAL-02 | 03-02 | Low-confidence extractions saved as pending_review, flagged in reply | SATISFIED | format_summary_reply uses PENDING_REVIEW_HEADER for status='pending_review'; test_pending_review_reply passes. Admin UI flagging is Phase 4. |
| VAL-03 | 03-02 | High-confidence extractions saved as auto_saved | SATISFIED | format_summary_reply uses AUTO_SAVED_HEADER for status='auto_saved'; test_auto_saved_reply passes |
| INF-02 | 03-01 | WhatsApp webhook HMAC signature validated on every inbound request | SATISFIED | TwilioProvider.validate_signature wraps twilio.request_validator.RequestValidator (HMAC-SHA1); test_invalid_signature passes (401 returned); algorithm clarification docstring in twilio.py |
| INF-04 | 03-01 | Webhook responds within 5 seconds; processing runs as background task | NEEDS HUMAN | asyncio.create_task pattern wired correctly (test_background_task_scheduled passes); timing can only be confirmed via live Twilio sandbox (UAT Scenario 1) |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `backend/app/providers/meta.py` | all | MetaCloudProvider raises NotImplementedError on all methods | Info | Known stub — intentional for v1; SUMMARY documents it; MetaCloudProvider is only reachable when WHATSAPP_PROVIDER=meta which is not the configured default |
| `backend/app/routers/whatsapp.py` | module | asyncio.create_task without durable queue | Warning | Documented v1 limitation; module docstring explicitly records it with production upgrade path (Celery/ARQ); acceptable for <20 invoices/day single-company deployment |
| `backend/app/routers/whatsapp.py` | 69-71 | _processed_message_sids cleared on process restart | Warning | Documented v1 limitation; UNIQUE INDEX is the DB-level backstop; module comment at line 69 records this explicitly |

No TBD, FIXME, or XXX markers found in any Phase 3 production file. No unlabeled hardcoded stubs found. No untracked debt.

---

### Human Verification Required

The code is complete and all automated checks pass. The following 6 scenarios require a live Twilio sandbox with ngrok and a real phone to verify. They are tracked in `.planning/phases/03-whatsapp-pipeline/03-HUMAN-UAT.md`.

**Pre-conditions:**
1. `cd backend && uv sync && alembic upgrade head`
2. Activate Twilio Sandbox and join with your phone
3. Seed your phone: `psql $DATABASE_URL -c "INSERT INTO sender_allowlist (phone_number, display_name, is_active) VALUES ('+<e164>', 'Tester', true);"`
4. Start stack: `docker compose up -d` or `uvicorn app.main:app --reload`
5. `ngrok http 8000` → set `WEBHOOK_BASE_URL=https://<ngrok-id>.ngrok-free.app` → restart backend
6. Set Twilio Sandbox webhook to `https://<ngrok-id>.ngrok-free.app/whatsapp/webhook` (POST)

---

#### 1. Allowlisted Happy Path (WA-01 + WA-03 + INF-04)

**Test:** Send a clear photo of a Factura A or Remito from an allowlisted phone.
**Expected:** (a) `✅ Factura recibida. Procesando...` arrives within 5 seconds. (b) Second message arrives within ~30s beginning with `✅ Factura registrada:` and containing Proveedor, Número, Fecha, Total lines. (c) `SELECT image_path FROM invoices ORDER BY created_at DESC LIMIT 1` shows a path; `ls -la <image_path>` shows a non-zero file.
**Why human:** INF-04 timing + two-message flow + file retention can only be observed against a live Twilio sandbox with real GPT-4o extraction.

---

#### 2. Pending-Review Path (VAL-02)

**Test:** Send an intentionally blurry or partially obscured invoice photo.
**Expected:** Reply begins with `⚠️ Algunos campos no se pudieron leer con certeza. Revisar factura desde la web.` DB row has `status = 'pending_review'`.
**Why human:** Requires real GPT-4o extraction returning a below-threshold confidence score.

---

#### 3. Duplicate Detection (VAL-01)

**Test:** Resend the same invoice photo from Scenario 1.
**Expected:** Reply is `🔁 Esta factura ya fue registrada el YYYY-MM-DD. No se guardó de nuevo.` with the original fecha. `SELECT count(*) FROM invoices WHERE numero_documento='<the-numero>'` returns 1.
**Why human:** Requires two real WhatsApp submissions with identical extracted fields.

---

#### 4. Unsupported Media Type (WA-04)

**Test:** Send a PDF from an allowlisted phone (Twilio delivers MediaContentType0=application/pdf).
**Expected:** Reply is `❌ No pudimos procesar la imagen. Asegurate de enviar una foto clara de la factura (JPG o PDF).` No new Invoice row.
**Why human:** Requires real Twilio delivery of a PDF with the application/pdf content type header.

---

#### 5. Non-Allowlisted Sender (WA-02)

**Test:** Send any image from a phone number NOT in sender_allowlist (or temporarily deactivate: `UPDATE sender_allowlist SET is_active = false WHERE phone_number = '<yours>'`).
**Expected:** Reply is `❌ Este número no está autorizado para enviar facturas.` No new Invoice row.
**Why human:** Requires a second real WhatsApp number or allowlist manipulation in a live DB.

---

#### 6. Invalid HMAC Signature (INF-02)

**Test:** `curl -X POST https://<ngrok-id>.ngrok-free.app/whatsapp/webhook -H "X-Twilio-Signature: bogus" -d "From=whatsapp:+1&MessageSid=SMtest&NumMedia=0"`
**Expected:** HTTP 401 response.
**Why human:** Verifies that WEBHOOK_BASE_URL is correctly set so the public URL is used in signature validation. Unit test covers the logic; live verification confirms the ngrok URL wiring.

---

### Gaps Summary

No code gaps found. All 9 must-haves verified in the codebase. The 6 pending items are live-environment UAT scenarios (not code defects) — they require a real Twilio sandbox, ngrok, and a phone. They are tracked in `03-HUMAN-UAT.md` and approved for deferral until after Phase 4 (Admin UI), as documented in both SUMMARY files.

The critical IVA rate bug (CR-01) was found during code review and fixed before this verification (commit 4e7d482). No remaining code-level issues.

---

_Verified: 2026-05-14T17:50:00Z_
_Verifier: Claude (gsd-verifier)_
