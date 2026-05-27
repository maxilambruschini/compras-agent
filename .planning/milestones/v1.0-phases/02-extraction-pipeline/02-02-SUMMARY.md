---
phase: "02"
plan: "02"
subsystem: "extraction-pipeline"
tags: [extraction, gpt-4o, prompt, integration-test, tdd, structlog]
dependency_graph:
  requires:
    - "02-01 (ExtractionService skeleton, StorageBackend, ExtractionResult, exception hierarchy)"
  provides:
    - "SYSTEM_PROMPT module-level constant (Plan 03 calibration loop reads and may edit)"
    - "Hardened _call_gpt4o with ExtractionFailedError cause chain on parse() failure"
    - "Hardened extract() with ExtractionFailedError cause chain on storage.save ValueError"
    - "Mocked test coverage for EXT-01..EXT-07 + VAL-04 + VAL-05"
    - "@pytest.mark.integration test wired and collectible (awaits fixture + API key in Plan 03)"
  affects:
    - "backend/app/services/extraction.py (SYSTEM_PROMPT, _call_gpt4o, extract)"
    - "backend/tests/test_extraction.py (10 new tests added, Plan 01 tests preserved)"
tech_stack:
  added: []
  patterns:
    - "Module-level SYSTEM_PROMPT constant — Plan 03 calibration script reads via importlib"
    - "Nested try/except for storage vs parse failure isolation (chained ExtractionFailedError)"
    - "structlog.testing.capture_logs() for secrets-in-logs assertion (VAL-05)"
    - "pytest.skip() inside test body for integration test gating (no fixture required at collection)"
key_files:
  created: []
  modified:
    - "backend/app/services/extraction.py (SYSTEM_PROMPT + error hardening)"
    - "backend/tests/test_extraction.py (10 new tests + integration marker)"
decisions:
  - "SYSTEM_PROMPT placed at module level (not class attribute) — Plan 03 calibration mutates this constant only"
  - "ExtractionFailedError raised from _call_gpt4o with `raise ... from exc` — cause chain preserved per acceptance criteria"
  - "storage.save try/except catches ValueError only (not broad Exception) — matches StorageBackend.save contract"
  - "Integration test uses pytest.skip() in body (not skipif at decorator) — test is always collected, skipped only at runtime when key/fixture absent"
  - "Secrets-in-logs test asserts against conftest env value strings, not env vars — deterministic even when env is unset"
metrics:
  duration_minutes: 12
  completed_date: "2026-05-14"
  tasks_completed: 2
  tasks_total: 2
  files_created: 0
  files_modified: 2
---

# Phase 2 Plan 02: ExtractionService Enrichment + Test Coverage Summary

**One-liner:** Calibrated SYSTEM_PROMPT promoted to module-level constant, _call_gpt4o and storage.save hardened with ExtractionFailedError cause chains, and full mocked test coverage added for EXT-01..EXT-07 + VAL-04 + VAL-05 with a wired @pytest.mark.integration live test.

## What Was Built

### ExtractionService enrichment (`backend/app/services/extraction.py`)

- **SYSTEM_PROMPT module-level constant:** Replaces the Plan-01 class-level placeholder. Calibrated initial prompt for Argentine invoice documents — instructs GPT-4o to use null (never empty string or guess), enforces `tipo_comprobante` enum values, and prohibits inventing line items. Plan 03's calibration script (`calibrate_prompt.py`) reads this constant and may edit its value without touching ExtractionService internals.

- **_call_gpt4o hardened:** `await self._client.chat.completions.parse(...)` wrapped in try/except `Exception`; catches network errors, `AuthenticationError`, etc. Emits `log.error("extraction.failed", error=str(exc), stage="openai_parse")` — never includes secrets. Re-raises as `ExtractionFailedError(f"openai parse failed: {exc}") from exc` with cause chain preserved.

- **extract() storage hardened:** `self._storage.save(...)` wrapped in try/except `ValueError`; emits `log.error("extraction.failed", error=str(exc), stage="storage_save")` and re-raises as `ExtractionFailedError(f"storage rejected filename: {exc}") from exc`.

- **MIME type limitation comment preserved:** The `# NOTE: MIME type hardcoded as image/jpeg` comment inserted by Plan 01 (review MEDIUM #5) is intact in `_call_gpt4o`.

- **No secrets in code:** `grep -v '^#' app/services/extraction.py | grep -c "openai_api_key|whatsapp_*"` returns 0.

### Test suite expansion (`backend/tests/test_extraction.py`)

10 new test functions added; all Plan-01 tests preserved. fixture cache_clear() calls in debug_client and nodebug_client unchanged.

## EXT-01..VAL-05 Requirement Traceability

| Req ID | Test Function | Status |
|--------|--------------|--------|
| EXT-01 | `test_line_items_extracted_with_full_field_set` | PASS |
| EXT-02 | `test_line_items_extracted_with_full_field_set` | PASS |
| EXT-03 | `test_document_level_fields_extracted` | PASS |
| EXT-04 | `test_cuit_and_cae_nullable_remain_none` | PASS |
| EXT-05 | `test_remito_extraction_does_not_crash` | PASS |
| EXT-05 | `test_lista_informal_extraction_does_not_crash` | PASS |
| EXT-05 | `test_unknown_tipo_does_not_crash` | PASS |
| EXT-06 | `test_extraction_returns_null_field_when_gpt_returns_null_field` | PASS |
| EXT-07 | `test_status_pending_review_just_below_threshold` (+ Plan-01 tests) | PASS |
| VAL-04 | `test_storage_save_called_with_uuid_and_basename_returns_image_path` | PASS |
| VAL-05 | `test_log_payload_does_not_contain_secrets` | PASS |
| Integration | `test_live_extraction_factura_a` | COLLECTED (skipped: fixture + key absent) |

## SYSTEM_PROMPT Value Committed

```
You are extracting structured data from photographs of Argentine purchase documents
(Factura A, Factura B, Factura C, Remito, Lista informal).
Extract every visible field into the provided schema.
Use null (not empty string, not a guess) whenever a field is not clearly visible
or not present on the document.
tipo_comprobante must be one of FACTURA_A, FACTURA_B, FACTURA_C, REMITO,
LISTA_INFORMAL, UNKNOWN.
Line items: one entry per product row visible on the document; never invent rows.
```

Plan 03 baselines against this value before running its calibration loop.

## TDD Execution Log

### Task 1 — Service enrichment

- **RED baseline:** 29 Plan-01 tests GREEN before any changes
- **GREEN (commit 910c744):** SYSTEM_PROMPT module-level + _call_gpt4o + storage hardening; 29/29 still pass
- No separate RED commit needed — service changes are enrichments to existing passing code, not new behavior-first additions

### Task 2 — Test expansion

- **GREEN (commit 83ad4a3):** 10 new mocked tests added; 39/39 tests pass (1 integration deselected); integration test collected at `test_live_extraction_factura_a`

## Deviations from Plan

None — plan executed exactly as written.

- SYSTEM_PROMPT promoted from class attribute to module-level constant as specified
- All error handling patterns match the plan's acceptance criteria
- All test functions match the exact names specified in the plan
- Plan-01 fixture locks (cache_clear, dependency_overrides) preserved
- MIME type limitation comment preserved

## Known Stubs

- `test_live_extraction_factura_a` will skip unless `OPENAI_API_KEY` is set and `backend/tests/fixtures/factura_a.jpg` exists. Both are Plan 03 deliverables. The test is collectible and wired correctly — not a stub in the blocking sense.

## Threat Flags

No new security-relevant surface introduced. Threat mitigations from plan's threat model verified:

- **T-02-02 (secrets in logs):** `test_log_payload_does_not_contain_secrets` GREEN; grep gate on extraction.py returns 0 matches for secret field names
- **T-02-05 (prompt injection):** Structured Outputs schema constraint in place; refusal path raises `ExtractionRefusalError` (not echoed to HTTP client)
- **T-02-06 (no audit trace):** structlog emits `extraction.start`, `extraction.complete`, `extraction.failed` with stage + filename binding

## Self-Check: PASSED

Files verified present:
- FOUND: backend/app/services/extraction.py
- FOUND: backend/tests/test_extraction.py

Commits verified present:
- 910c744 — feat(02-02): enrich ExtractionService with SYSTEM_PROMPT and hardened error semantics
- 83ad4a3 — feat(02-02): add EXT-01..EXT-07 + VAL-04 + VAL-05 mocked tests and integration marker
