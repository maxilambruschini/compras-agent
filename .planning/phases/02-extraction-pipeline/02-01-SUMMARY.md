---
phase: "02"
plan: "01"
subsystem: "extraction-pipeline"
tags: [extraction, storage, scaffold, mvp-skeleton, tdd]
dependency_graph:
  requires: []
  provides:
    - "StorageBackend Protocol (runtime_checkable)"
    - "LocalStorageBackend with path-traversal sanitization (T-02-01)"
    - "ExtractionService skeleton with GPT-4o vision call shape"
    - "ExtractionResult Pydantic DTO"
    - "compute_confidence() and assign_status() helpers"
    - "ExtractionError / ExtractionRefusalError / ExtractionFailedError"
    - "get_extraction_service() dependency (sole ExtractionService construction site)"
    - "POST /extraction/test debug-gated endpoint (D-05)"
    - "settings.storage_path with default /data/invoices (D-08)"
    - "pytest 'integration' marker"
  affects:
    - "backend/app/main.py (conditional router registration)"
    - "backend/app/config.py (new storage_path field)"
tech_stack:
  added: []
  patterns:
    - "typing.Protocol @runtime_checkable for service interface"
    - "Per-component path sanitization (no os.path.basename directory reconstruction)"
    - "structlog.get_logger() in __init__, .bind() at call time"
    - "app.dependency_overrides[get_extraction_service] for ASGI test injection"
    - "get_settings.cache_clear() before each ASGI fixture to prevent cache pollution"
    - "Constructor injection for AsyncOpenAI, StorageBackend, Settings"
key_files:
  created:
    - "backend/app/services/__init__.py"
    - "backend/app/services/storage.py"
    - "backend/app/services/extraction.py"
    - "backend/app/routers/extraction.py"
    - "backend/tests/test_storage.py"
    - "backend/tests/test_extraction.py"
  modified:
    - "backend/app/config.py (added storage_path field)"
    - "backend/app/main.py (conditional extraction router registration)"
    - "backend/pyproject.toml (added integration pytest marker)"
decisions:
  - "Per-component split/filter sanitization in LocalStorageBackend.save() — no directory-part reconstruction (review HIGH #1 fix)"
  - "get_extraction_service() exported as module-level dependency for dependency_overrides injection (review HIGH #2)"
  - "get_settings.cache_clear() called in both debug_client and nodebug_client fixtures before create_app() (review MEDIUM #4)"
  - "MIME type hardcoded as image/jpeg with explicit inline comment noting limitation (review MEDIUM #5)"
  - "services/__init__.py created as docstring-only (review LOW #6)"
metrics:
  duration_minutes: 5
  completed_date: "2026-05-14"
  tasks_completed: 3
  tasks_total: 3
  files_created: 6
  files_modified: 3
---

# Phase 2 Plan 01: Extraction Pipeline Scaffold Summary

**One-liner:** Thin end-to-end extraction pipeline scaffold — StorageBackend Protocol + LocalStorageBackend with T-02-01 path-traversal mitigation, ExtractionService skeleton with GPT-4o call shape and confidence/status logic, debug-gated POST /extraction/test router, and 18 fully-mocked tests all GREEN.

## What Was Built

### StorageBackend Protocol + LocalStorageBackend (`backend/app/services/storage.py`)

- `@runtime_checkable` Protocol with single `save(data: bytes, filename: str) -> str` method
- `LocalStorageBackend` implements per-component path sanitization:
  - Split filename on `/`, drop empty + `"."` + `".."` segments, rejoin
  - Defense-in-depth: `os.path.commonpath([realpath(full), realpath(root)]) == realpath(root)`
  - Auto-creates parent directories via `os.makedirs(..., exist_ok=True)`
  - Returns sanitized relative path
- No `os.path.basename` used for directory-part reconstruction (review HIGH #1 fix)

### ExtractionService + helpers (`backend/app/services/extraction.py`)

- `ExtractionResult(BaseModel)`: invoice, confidence_score, status, image_path
- `compute_confidence(invoice) -> float`: non-null(tipo, numero, proveedor, fecha) / 4 (D-01)
- `assign_status(score, threshold) -> str`: D-03 boundary (>= → auto_saved)
- `ExtractionError / ExtractionRefusalError / ExtractionFailedError` hierarchy
- `ExtractionService.__init__`: injects AsyncOpenAI, StorageBackend, Settings
- `_call_gpt4o()`: `chat.completions.parse()` + `image_url` vision content block; explicit MIME hardcoding comment (review MEDIUM #5)
- `extract()`: UUID generation, storage-first, refusal/None gates, structlog VAL-05 logging; API key never referenced

### Debug Router (`backend/app/routers/extraction.py`)

- `get_extraction_service()`: sole ExtractionService construction site; dependency_overrides target
- `POST /extraction/test`: UploadFile → service.extract() → ExtractionResult JSON (no DB write, D-06)
- Registered in `create_app()` only when `settings.debug is True` (D-05, T-02-03)

### Config + infra

- `backend/app/config.py`: `storage_path: str = "/data/invoices"` added (D-08)
- `backend/app/main.py`: `if settings.debug: include_router(extraction_router)` 
- `backend/pyproject.toml`: `integration` marker registered

## TDD Execution Log

### Task 1 — RED State (commit: 325ac21)

- Created `test_storage.py` (6 tests) and `test_extraction.py` (13 tests)
- Collection fails with `ModuleNotFoundError: No module named 'app.services.storage'` — expected RED
- Registered `integration` pytest marker; no marker warnings on collection
- Phase 1 tests (11) unmodified and still GREEN

### Task 2 — GREEN: Storage (commit: 1253fd9)

- Created `backend/app/services/__init__.py` (docstring-only)
- Created `backend/app/services/storage.py` with StorageBackend Protocol + LocalStorageBackend
- Added `storage_path` to Settings
- `pytest tests/test_storage.py`: 6/6 GREEN; `pytest tests/test_config.py`: 2/2 GREEN (regression)

### Task 3 — GREEN: Extraction + Router (commit: d4071b5)

- Created `backend/app/services/extraction.py` (ExtractionService + helpers + exceptions)
- Created `backend/app/routers/extraction.py` (get_extraction_service + POST /test)
- Modified `backend/app/main.py` (conditional router registration)
- `pytest -m "not integration"`: 29/29 GREEN (11 Phase 1 + 6 storage + 12 extraction mocked)

## Test Coverage

| Test | Requirement | Result |
|------|-------------|--------|
| test_save_writes_bytes_and_returns_relative_path | VAL-04 | PASS |
| test_save_creates_parent_directories | VAL-04 | PASS |
| test_save_sanitizes_path_traversal | T-02-01 | PASS |
| test_save_with_uuid_prefix_and_traversal_filename | T-02-01 | PASS |
| test_save_rejects_only_dot_segments | T-02-01 | PASS |
| test_save_returns_correct_relative_path_for_uuid_prefix | VAL-04 | PASS |
| test_compute_confidence_all_four_critical_fields_present | EXT-07, D-01 | PASS |
| test_compute_confidence_two_of_four_present | EXT-07, D-01 | PASS |
| test_compute_confidence_all_none | EXT-07, D-01 | PASS |
| test_assign_status_auto_saved_at_threshold | D-03 | PASS |
| test_assign_status_pending_review_below_threshold | D-03 | PASS |
| test_extract_calls_storage_with_uuid_and_basename | D-09, VAL-04 | PASS |
| test_extract_returns_extraction_result_with_image_path | D-04 | PASS |
| test_extract_raises_refusal_error_when_message_refusal_set | EXT-06 | PASS |
| test_extract_raises_extraction_failed_when_parsed_is_none_and_no_refusal | EXT-06 | PASS |
| test_extract_logs_error_with_filename_on_failure | VAL-05 | PASS |
| test_post_extraction_test_returns_extraction_result_when_debug_true | D-05, D-06 | PASS |
| test_post_extraction_test_404_when_debug_false | D-05, T-02-03 | PASS |

## Deviations from Plan

None — plan executed exactly as written. All review feedback items addressed:
- **Review HIGH #1**: Per-component split sanitization (no directory-part reconstruction)
- **Review HIGH #2**: Explicit `dependency_overrides[get_extraction_service]` in ASGI tests
- **Review MEDIUM #4**: `get_settings.cache_clear()` in both debug_client and nodebug_client fixtures
- **Review MEDIUM #5**: Explicit inline MIME type limitation comment in `_call_gpt4o()`
- **Review LOW #6**: `services/__init__.py` created with docstring

## Known Stubs

- `ExtractionService.SYSTEM_PROMPT`: Intentional placeholder — "You are an invoice extraction system. Extract the invoice fields exactly as visible." Plan 02 calibrates this prompt against real fixture images.
- `_call_gpt4o()` MIME type: Hardcoded as `image/jpeg`. Plan 03 may add detection.

These stubs do NOT block the plan's goal — the extraction pipeline scaffold is complete and mockable. Plan 02 enriches the prompt semantics; Plan 03 adds fixture calibration.

## Threat Flags

No new security-relevant surface beyond what was planned in the threat model:
- T-02-01 mitigated: path-traversal test GREEN
- T-02-02 mitigated: `openai_api_key` absent from extraction.py non-comment code
- T-02-03 mitigated: 404 test with `get_settings.cache_clear()` GREEN

## Self-Check: PASSED

Files verified present:
- FOUND: backend/app/services/__init__.py
- FOUND: backend/app/services/storage.py
- FOUND: backend/app/services/extraction.py
- FOUND: backend/app/routers/extraction.py
- FOUND: backend/app/config.py
- FOUND: backend/app/main.py
- FOUND: backend/tests/test_storage.py
- FOUND: backend/tests/test_extraction.py
- FOUND: backend/pyproject.toml

Commits verified present:
- 325ac21 — test(02-01): RED state
- 1253fd9 — feat(02-01): StorageBackend
- d4071b5 — feat(02-01): ExtractionService + router
