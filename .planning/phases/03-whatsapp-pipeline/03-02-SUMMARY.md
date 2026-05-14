---
phase: 03-whatsapp-pipeline
plan: "02"
subsystem: whatsapp-extraction-pipeline
tags:
  - whatsapp
  - extraction
  - duplicate-detection
  - background-task
  - reply-formatter
  - magic-byte-validation
  - race-condition
  - invoice-service

dependency_graph:
  requires:
    - phase: 03-01
      provides: "WhatsAppProvider Protocol, TwilioProvider, _background_tasks, _processed_message_sids, get_whatsapp_provider, SUPPORTED_IMAGE_TYPES, uq_invoices_numero_proveedor_lower UNIQUE INDEX"
    - phase: 02-extraction-pipeline
      provides: "ExtractionService.extract(), ExtractionResult, ExtractionRefusalError, ExtractionFailedError, LocalStorageBackend"
    - phase: 01-foundation
      provides: "Invoice + InvoiceLineItem ORM models, AsyncSession, get_async_session_local"
  provides:
    - "InvoiceService: find_duplicate (case-insensitive), find_existing_for_race (race re-query), save_invoice (with image_path retention)"
    - "process_invoice background task: MIME gate + magic-byte gate + extraction + duplicate check + persist + summary reply"
    - "_validate_image_bytes helper (JPEG SOI + PNG magic-byte defense)"
    - "format_summary_reply / format_duplicate_reply / _compute_total reply formatters"
    - "_safe_send helper (reply-send failure isolation)"
    - "D-08 auto_saved + D-09 pending_review + D-11 unreadable + D-12 duplicate Spanish reply templates"
    - "03-HUMAN-UAT.md with 6 deferred Twilio sandbox scenarios (pending Phase 4)"
  affects:
    - "04-admin-ui: InvoiceService.find_duplicate + save_invoice are the write surface for invoice data; image_path column links to original files on disk"

tech_stack:
  added: []
  patterns:
    - "InvoiceService stateless utility class — all methods accept AsyncSession as first arg (mirrors ExtractionService pattern)"
    - "IntegrityError catch + rollback + re-raise in save_invoice; caller (process_invoice) handles race path via find_existing_for_race"
    - "Two-layer content validation: MIME type pre-download + magic-byte post-download (_validate_image_bytes)"
    - "_safe_send wrapper isolates reply-send failures from task lifecycle (no re-raise)"
    - "structlog bound logger per background-task invocation (sender + message_sid context)"
    - "ExtractionService + LocalStorageBackend constructed inline inside background task (not via Depends — background tasks run outside request lifecycle)"
    - "Total computed as sum over line_items (bultos x precio_unitario_sin_iva x (1 + iva_rate/100) x (1 - descuento_pct)) — no document-level total field on ExtractedInvoice"
    - "format_duplicate_reply prefers existing.fecha then created_at.date() then EM_DASH fallback"

key_files:
  created:
    - backend/app/services/invoice.py
    - backend/tests/test_invoice_service.py
    - .planning/phases/03-whatsapp-pipeline/03-HUMAN-UAT.md
  modified:
    - backend/app/routers/whatsapp.py
    - backend/tests/test_whatsapp.py

key_decisions:
  - "find_existing_for_race introduced as a separate method from find_duplicate so the caller (process_invoice) explicitly controls when re-query happens post-rollback — clearer contract than overloading find_duplicate"
  - "save_invoice re-raises IntegrityError rather than silently returning None — keeps the error visible to the caller, which decides the duplicate-reply semantics"
  - "Magic-byte validation added AFTER download as defense in depth: Twilio's MediaContentType0 is provider-supplied metadata that could be spoofed; actual byte signature is ground truth"
  - "_safe_send used consistently across ALL non-summary reply branches (MIME reject, magic-byte reject, download fail, extraction error, duplicate) so reply failures never crash the task regardless of branch"
  - "Twilio sandbox UAT (Task 3) deferred post-Phase-4: admin UI and a deployed environment are prerequisites for a meaningful live end-to-end test; automated test coverage proves correctness for all 8 must_haves except INF-04 timing"

patterns_established:
  - "InvoiceService pattern: stateless class, AsyncSession injected per call, structlog bound at call site"
  - "Race-condition pattern: save → catch IntegrityError → rollback → re-query → send duplicate reply with real fecha"
  - "Two-layer media validation: MIME guard (pre-download) + magic-byte guard (post-download)"
  - "Reply isolation pattern: wrap final send_message in try/except, log whatsapp.reply_failed, do NOT re-raise"

requirements_completed:
  - WA-03
  - WA-04
  - VAL-01
  - VAL-02
  - VAL-03

duration: "~60 minutes"
completed: "2026-05-14"
---

# Phase 3 Plan 02: InvoiceService + process_invoice Pipeline Summary

**Race-safe invoice persistence with magic-byte validation, duplicate detection (app-level SELECT + IntegrityError re-query), and Spanish summary/duplicate/error replies isolated from reply-send failures.**

## Performance

- **Duration:** ~60 minutes
- **Started:** 2026-05-14
- **Completed:** 2026-05-14
- **Tasks:** 2 of 3 completed (Task 3 deferred — see Deviations)
- **Files modified:** 4 files (2 created, 2 modified) + 1 UAT tracking file

## Accomplishments

- `InvoiceService` class with `find_duplicate` (case-insensitive LOWER() match), `find_existing_for_race` (post-rollback re-query for real original `fecha`), and `save_invoice` (full field mapping + image_path retention link + IntegrityError rollback + re-raise)
- Replaced `_process_invoice_placeholder` with the real `process_invoice` pipeline: MIME gate → magic-byte gate → ExtractionService.extract → duplicate check → persist → summary reply, with reply-send failures isolated via `_safe_send` and the post-save `try/except`
- 76 tests passing, 1 deselected (integration test requiring live OpenAI key) — no regressions against Phase 1 or Phase 2

## Task Commits

Each task was committed atomically:

1. **Task 1: InvoiceService (find_duplicate + save_invoice + find_existing_for_race) with tests** - `102e93c` (feat)
2. **Task 2: Replace placeholder with real process_invoice pipeline + magic-byte validator + reply formatters** - `1998604` (feat)
3. **Task 3: Live Twilio sandbox end-to-end verification** - `7ae5c5e` (test — UAT file persisted, deferred)

## Files Created/Modified

- `backend/app/services/invoice.py` — `InvoiceService` class: `find_duplicate`, `find_existing_for_race`, `save_invoice`; case-insensitive `func.lower()` queries; `IntegrityError` catch + rollback + re-raise; `image_path=result.image_path` persisted on row (original-file retention link)
- `backend/tests/test_invoice_service.py` — 9 unit tests: null-arg early returns, case-insensitive match, save success path, message metadata, race re-query, IntegrityError monkeypatched rollback + re-raise
- `backend/app/routers/whatsapp.py` — `process_invoice` replaces placeholder; `_validate_image_bytes` helper (JPEG SOI + PNG magic); `format_summary_reply`, `format_duplicate_reply`, `_compute_total` helpers; `_safe_send` reply isolation; `AUTO_SAVED_HEADER`, `PENDING_REVIEW_HEADER`, `DUPLICATE_REPLY_TEMPLATE`, `EM_DASH`, `JPEG_MAGIC`, `PNG_MAGIC` module-level constants; `whatsapp.multi_media_ignored` log for v1 limitation
- `backend/tests/test_whatsapp.py` — 16 new test cases added to Plan 01's 8: unsupported MIME, invalid magic bytes, valid JPEG/PNG pass-through, auto_saved reply, pending_review reply, summary format/em-dash, duplicate app-level, duplicate race with real fecha, duplicate race no-existing-row edge case, extraction refusal, extraction failure, reply-send failure after save, background task cleared, multi-media v1 log
- `.planning/phases/03-whatsapp-pipeline/03-HUMAN-UAT.md` — 6 Twilio sandbox scenarios persisted for post-Phase-4 human verification

## Decisions Made

- `find_existing_for_race` is a separate method from `find_duplicate` — the two have different call-site semantics (pre-duplicate-check vs. post-IntegrityError re-query on a rolled-back session). Keeping them separate makes the contract explicit and avoids confusion about session state.
- `save_invoice` re-raises `IntegrityError` rather than silently returning `None` — the caller (`process_invoice`) owns the decision to send a duplicate reply; the service layer should not swallow exceptions that carry meaning to the caller.
- Magic-byte validation runs AFTER download as defense in depth against spoofed `MediaContentType0` metadata — actual byte signatures are ground truth regardless of what Twilio reports.
- `_safe_send` wraps ALL non-summary reply sends (MIME reject, magic-byte reject, download fail, extraction error, duplicate) — consistent isolation means any reply-send failure is logged but never crashes the task regardless of which branch triggered it.
- Task 3 (live Twilio sandbox UAT) deferred post-Phase-4: the 6 scenarios require a deployed environment with ngrok + seeded allowlist + real phone. Automated tests cover all 8 `must_haves` except INF-04 (timing). UAT file created at `03-HUMAN-UAT.md`.

## Deviations from Plan

### Task 3: Live Twilio Sandbox Verification — Deferred (not failed)

- **Found during:** Task 3 (checkpoint:human-verify)
- **Issue:** The live end-to-end Twilio sandbox verification (INF-04 timing + two-message flow) requires a deployed environment: ngrok tunnel, seeded allowlist with a real phone, Twilio sandbox activation, and running Postgres. None of these are available in the current development context at this stage.
- **Decision:** Deferred to post-Phase-4, when the admin UI and a more complete deployment environment will be in place. This is the appropriate prerequisite gate — verifying the pipeline against a running UI makes the full flow observable.
- **Tracking:** `.planning/phases/03-whatsapp-pipeline/03-HUMAN-UAT.md` created with all 6 scenarios, exact verification steps, and pre-conditions. The file is committed and will be picked up by the Phase 4 executor or the first post-Phase-4 verification session.
- **Coverage impact:** All 8 `must_haves` are covered by automated tests EXCEPT INF-04 (response < 5 seconds — can only be observed live). The deferred UAT explicitly lists which scenarios map to which requirements.
- **Committed in:** `7ae5c5e`

---

**Total deviations:** 1 (Task 3 deferred — not an auto-fix, a gate deferral approved by the orchestrator)
**Impact on plan:** Requirements WA-03, WA-04, VAL-01, VAL-02, VAL-03 are all provable via `pytest`. INF-04 timing remains pending live verification post-Phase-4.

## Self-Check

### Must-Have Coverage (Automated vs. Pending UAT)

| must_have | Automated Test | UAT Required |
|-----------|---------------|--------------|
| auto_saved reply (D-08) with proveedor/numero/fecha/total | test_auto_saved_reply | Scenario 1 (timing) |
| pending_review reply (D-09) same four fields | test_pending_review_reply | Scenario 2 |
| Duplicate → D-12 reply with original fecha (app-level) | test_duplicate_app_level | Scenario 3 |
| Race IntegrityError → re-query → D-12 with real fecha | test_duplicate_race_integrity_error | — |
| ExtractionRefusalError / ExtractionFailedError → D-11 | test_extraction_refusal/failed_sends_error | — |
| Unsupported MediaContentType0 → D-11, no extract call | test_unsupported_media_type | Scenario 4 |
| Invalid magic bytes → D-11, no extract call | test_invalid_magic_bytes | — |
| Original files retained (image_path on Invoice row) | test_save_invoice_sets_message_metadata | Scenario 1 (ls -la) |
| Reply-send failure post-save → invoice persisted, logged | test_send_message_failure_after_save | — |

### Commits verified

- `102e93c`: InvoiceService — EXISTS
- `1998604`: process_invoice pipeline — EXISTS
- `7ae5c5e`: deferred UAT — EXISTS

### Key files exist

- `backend/app/services/invoice.py` — EXISTS
- `backend/tests/test_invoice_service.py` — EXISTS
- `backend/app/routers/whatsapp.py` — EXISTS (process_invoice, _validate_image_bytes, format_summary_reply, _safe_send)
- `backend/tests/test_whatsapp.py` — EXISTS
- `.planning/phases/03-whatsapp-pipeline/03-HUMAN-UAT.md` — EXISTS

## Threat Flags

No new security-relevant surfaces beyond the plan's `<threat_model>`. All STRIDE threats T-3-08 through T-3-15 were mitigated as specified:
- T-3-08 (concurrent duplicate INSERT): IntegrityError → rollback → re-query → D-12 with real fecha
- T-3-09 (spoofed MediaContentType0): two-layer MIME + magic-byte defense
- T-3-10 (extraction failure → no reply): explicit `_safe_send` on all error branches
- T-3-11 (raw_extraction PII): accepted; no log exposure added
- T-3-12 (reply injection via extracted fields): plain string substitution, no rendering
- T-3-14 (send_message failure post-persistence): try/except + whatsapp.reply_failed log, no re-raise
- T-3-15 (original file lost): image_path persisted from ExtractionResult → LocalStorageBackend path

## Known Stubs

| Stub | File | Reason |
|------|------|--------|
| `MetaCloudProvider` (from Plan 01) | `backend/app/providers/meta.py` | Raises NotImplementedError — future Meta Cloud API implementation |
| Multi-attachment handling (`MediaUrl1+`) | `backend/app/routers/whatsapp.py` | v1 processes only `MediaUrl0`; logged via `whatsapp.multi_media_ignored`; deferred to v2 |
| Accent/whitespace/CUIT duplicate normalization | `backend/app/services/invoice.py` | LOWER() functional index covers primary case; accent/punctuation normalization deferred to v2 |

These stubs do NOT prevent the plan's goal from being achieved. The UAT file documents which live scenarios will verify the production flow.

## Next Phase Readiness

- Phase 4 (admin UI) can consume `InvoiceService.find_duplicate` and the `Invoice`/`InvoiceLineItem` ORM directly
- `image_path` on Invoice rows enables Phase 4 to serve signed image URLs from the admin UI
- `03-HUMAN-UAT.md` is ready for execution once Phase 4 provides a deployed environment with ngrok + real phone

---
*Phase: 03-whatsapp-pipeline*
*Completed: 2026-05-14*
