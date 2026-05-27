---
phase: 02
slug: extraction-pipeline
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-05-13
updated: 2026-05-13
---

# Phase 02 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio |
| **Config file** | backend/pyproject.toml [tool.pytest.ini_options] |
| **Quick run command** | `cd backend && python -m pytest -m "not integration" -x -q` |
| **Full suite command** | `cd backend && python -m pytest -v` |
| **Integration command** | `cd backend && OPENAI_API_KEY=... python -m pytest -m integration -v` |
| **Estimated runtime** | ~5 seconds (mocked), ~30 seconds (with integration) |

---

## Sampling Rate

- **After every task commit:** `cd backend && python -m pytest -m "not integration" -x -q`
- **After every plan wave:** `cd backend && python -m pytest -v`
- **Before `/gsd-verify-work`:** Full suite must be green; calibration_report.json `clean=true`
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-T1 | 01 | 1 | Wave-0 scaffolding | — | — | scaffold | `cd backend && python -m pytest tests/test_storage.py tests/test_extraction.py --collect-only 2>&1 \| grep -E "ImportError\|errors during collection"` | ❌ W0 | ⬜ pending |
| 02-01-T2 | 01 | 1 | VAL-04 | T-02-01 | Path traversal sanitized via os.path.basename + commonpath check | unit | `cd backend && python -m pytest tests/test_storage.py -x -q` | ❌ W0 | ⬜ pending |
| 02-01-T3 | 01 | 1 | EXT-06, EXT-07, VAL-04, VAL-05 | T-02-02, T-02-03 | No openai_api_key in service; debug-gated router | unit + ASGI | `cd backend && python -m pytest -m "not integration" -x -q` | ❌ W0 | ⬜ pending |
| 02-02-T1 | 02 | 2 | EXT-06, VAL-05 | T-02-02, T-02-06 | SYSTEM_PROMPT module constant; no secrets logged | unit | `cd backend && python -m pytest -m "not integration" -x -q` | ❌ W0 | ⬜ pending |
| 02-02-T2 | 02 | 2 | EXT-01..EXT-07, VAL-04, VAL-05 | T-02-05, T-02-06 | Mocked round-trip + integration marker | unit + integration | `cd backend && python -m pytest tests/test_extraction.py -v -m "not integration"` | ❌ W0 | ⬜ pending |
| 02-03-T1 | 03 | 2 | (infra for EXT-05) | — | Privacy guidance in README | scaffold | `cd backend && grep -c "^anthropic$" requirements-dev.txt && test -f tests/fixtures/README.md` | ❌ W0 | ⬜ pending |
| 02-03-T2 | 03 | 2 | (script for D-11) | T-02-08, T-02-12 | claude-opus-4-7 for ground truth; no key prints | script | `cd backend && python scripts/calibrate_prompt.py --help` | ❌ W0 | ⬜ pending |
| 02-03-T3 | 03 | 2 | EXT-05, EXT-07 (D-11 done-gate) | T-02-09, T-02-10 | Human PII review before commit | human-verify | `cat backend/tests/fixtures/calibration_report.json \| python -c "import json,sys; r=json.load(sys.stdin); assert r['clean']"` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Requirement → Plan Coverage

| Req ID | Plan(s) | Test Function(s) |
|--------|---------|------------------|
| EXT-01 | 02 | test_line_items_extracted_with_full_field_set |
| EXT-02 | 02 | test_line_items_extracted_with_full_field_set (iva_rate, percepciones_iibb) |
| EXT-03 | 02 | test_document_level_fields_extracted |
| EXT-04 | 02 | test_cuit_and_cae_nullable_remain_none |
| EXT-05 | 02, 03 | test_remito_extraction_does_not_crash, test_lista_informal_extraction_does_not_crash, test_unknown_tipo_does_not_crash; calibration loop on remito.jpg + lista_informal.jpg |
| EXT-06 | 01, 02 | test_extract_raises_refusal_error_when_message_refusal_set, test_extraction_returns_null_field_when_gpt_returns_null_field |
| EXT-07 | 01, 02, 03 | test_compute_confidence_*, test_assign_status_*, test_status_pending_review_just_below_threshold; calibration confidence baseline |
| VAL-04 | 01, 02 | test_save_*, test_extract_calls_storage_with_uuid_and_basename, test_storage_save_called_with_uuid_and_basename_returns_image_path |
| VAL-05 | 01, 02 | test_extract_logs_error_with_filename_on_failure, test_log_payload_does_not_contain_secrets |

---

## Wave 0 Requirements

- [ ] `backend/tests/test_extraction.py` — stubs for EXT-01 through VAL-05 (Plan 01 Task 1 creates RED, Task 3 turns GREEN; Plan 02 Task 2 extends)
- [ ] `backend/tests/test_storage.py` — Plan 01 Task 1 creates RED, Task 2 turns GREEN
- [ ] `backend/tests/conftest.py` — inherited from Phase 1; no changes needed (env_setup already patches OPENAI_API_KEY)
- [ ] `backend/pyproject.toml` — `markers = ["integration: ..."]` registered (Plan 01 Task 1)
- [ ] `backend/tests/fixtures/` — directory + README (Plan 03 Task 1) + real images (Plan 03 Task 3 human-verify)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| calibrate_prompt.py runs clean against all fixture images | D-11 | Requires real OPENAI_API_KEY + ANTHROPIC_API_KEY + fixture images; ground truth correctness is a human judgement | `cd backend && python scripts/calibrate_prompt.py`; verify exit 0 and calibration_report.json `clean=true` |
| @pytest.mark.integration live extraction test passes | EXT-01 | Requires real OPENAI_API_KEY and valid fixture image | `cd backend && OPENAI_API_KEY=... python -m pytest -m integration -v`; verify ExtractedInvoice has expected AFIP fields |
| Fixture image PII redaction | T-02-09 | Visual inspection of invoice photos | Human review before commit per backend/tests/fixtures/README.md privacy section |
| Ground-truth JSON correctness | D-13 step 1 | Human compares Claude Opus 4.7 output to the actual invoice | Inspect `{name}_ground_truth.json` against the photo before locking baseline |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** ready for execution
