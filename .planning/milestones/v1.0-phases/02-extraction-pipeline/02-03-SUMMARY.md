---
phase: "02"
plan: "03"
subsystem: "extraction-pipeline"
tags: [calibration, anthropic, ground-truth, fixtures, checkpoint]
dependency_graph:
  requires:
    - "02-01 (ExtractionService skeleton, StorageBackend, LocalStorageBackend)"
    - "02-02 (SYSTEM_PROMPT module-level constant, ExtractionService enrichment)"
  provides:
    - "backend/scripts/calibrate_prompt.py — ground-truth generation (Claude Opus 4.7) + GPT-4o diff loop"
    - "backend/scripts/__init__.py — marks scripts as importable package"
    - "backend/tests/fixtures/ — directory with README and .gitkeep"
    - "anthropic added to requirements-dev.txt (D-14)"
  affects:
    - "backend/requirements-dev.txt (anthropic dev dep added)"
tech_stack:
  added:
    - "anthropic (dev dep only — requirements-dev.txt, per D-14)"
  patterns:
    - "sys.path.insert(0, backend_dir) at script top — enables `cd backend && python scripts/calibrate_prompt.py` without PYTHONPATH"
    - "Anthropic().messages.create() with base64 image block (Pattern 8 from RESEARCH.md)"
    - "asyncio.run() to call async ExtractionService.extract() from sync calibration loop"
    - "tempfile.TemporaryDirectory for LocalStorageBackend root — calibration does not pollute /data/invoices"
    - "normalize_value() canonicalises Decimal strings before equality check — reduces diff noise"
    - "Line-item sort by descripcion before diffing — reduces GPT-4o row-reorder false positives (review LOW #7)"
key_files:
  created:
    - "backend/scripts/calibrate_prompt.py"
    - "backend/scripts/__init__.py"
    - "backend/tests/fixtures/.gitkeep"
    - "backend/tests/fixtures/README.md"
  modified:
    - "backend/requirements-dev.txt (anthropic appended)"
decisions:
  - "sys.path.insert at script top (not PYTHONPATH wrapper) — plan invocation is `cd backend && python scripts/calibrate_prompt.py`; path setup is the least-friction solution"
  - "tempfile.TemporaryDirectory for calibration storage root — avoids polluting /data/invoices with fixture bytes"
  - "asyncio.run() in cmd_diff for GPT-4o extraction — script is sync CLI, ExtractionService is async; asyncio.run() is the correct bridge"
  - "normalize_value() converts Decimal-shaped strings to canonical form — GPT-4o sometimes returns '1.0' vs '1.00'; normalisation reduces diff noise"
metrics:
  duration_minutes: 15
  completed_date: "2026-05-14"
  tasks_completed: 2
  tasks_total: 3
  files_created: 4
  files_modified: 1
---

# Phase 2 Plan 03: Calibration Script Summary

**One-liner:** Prompt calibration infrastructure — Claude Opus 4.7 ground-truth generation + GPT-4o diff loop with line-item sort, anthropic dev dep, and fixtures README; paused at human checkpoint awaiting real invoice images (D-11 done-gate).

## What Was Built

### Task 1: Dependencies, package init, fixtures directory

- **`backend/requirements-dev.txt`:** `anthropic` appended as a dev/scripts-only dependency (D-14). Main `requirements.txt` is unchanged — the production app never imports anthropic.
- **`backend/scripts/__init__.py`:** Empty file marking `scripts/` as an importable Python package.
- **`backend/tests/fixtures/.gitkeep`:** Keeps the empty fixtures directory tracked in git.
- **`backend/tests/fixtures/README.md`:** Documents required image filenames (`factura_a.jpg`, `remito.jpg`, `lista_informal.jpg`), generated file names (`*_ground_truth.json`, `calibration_report.json`), privacy guidance (redact employee PII; CUITs are public-registry), and step-by-step calibration run instructions.

### Task 2: calibrate_prompt.py

**`backend/scripts/calibrate_prompt.py`** implements the D-11..D-14 calibration workflow:

- **`require_env(name)`:** Exits with code 2 and prints only the variable name (never the value) when OPENAI_API_KEY or ANTHROPIC_API_KEY is missing (T-02-08).
- **`detect_media_type(path)`:** Maps `.jpg`/`.jpeg` → `image/jpeg`, `.png` → `image/png`. Passed to the Anthropic image block.
- **`find_fixture(name)`:** Searches `FIXTURE_DIR` for `{name}.jpg`, `.jpeg`, `.png`; returns the first match or None.
- **`generate_ground_truth(fixture_path, schema_json_str)`:** Calls `Anthropic().messages.create(model="claude-opus-4-7", ...)` with a base64 image block and the `ExtractedInvoice` JSON Schema embedded in the prompt. Strips markdown fences from the response and returns `json.loads(text)`. Never uses gpt-4o (D-12).
- **`run_gpt4o_extraction(fixture_path, settings)`:** Async function that constructs `ExtractionService` with a `tempfile.TemporaryDirectory`-rooted `LocalStorageBackend` (so calibration does not pollute `/data/invoices`), then calls `service.extract()`. Returns `result.invoice.model_dump(mode="json")`.
- **`normalize_value(v)`:** Recursive normalisation — converts Decimal-shaped strings to canonical `Decimal.normalize()` form, strips whitespace, converts `""` to `None`. Reduces diff noise from numeric formatting differences.
- **`diff_invoice(ground_truth, extracted, path)`:** Recursive field-by-field diff. For line_items (any list of dicts), both lists are sorted by `descripcion` before item-by-item comparison — reduces false positives from GPT-4o row reordering (review LOW #7). Returns human-readable diff strings.
- **`cmd_generate_ground_truth(args)`:** Iterates over fixture names, calls `generate_ground_truth`, writes `{name}_ground_truth.json`. Skips absent fixtures.
- **`cmd_diff(args)`:** Iterates over fixtures, runs GPT-4o extraction, diffs against ground truth, writes `calibration_report.json`. Exits 0 (clean), 1 (diffs found), or 2 (no fixtures checked).
- **`main()`:** argparse with `--generate-ground-truth`, `--fixture {factura_a,remito,lista_informal}`, `--report-only`.
- **Path safety:** `sys.path.insert(0, backend_dir)` at top of file enables `cd backend && python scripts/calibrate_prompt.py` without `PYTHONPATH=` prefix.

## SYSTEM_PROMPT Snapshot (at time of calibration checkpoint)

The calibration script imports the current SYSTEM_PROMPT from `app.services.extraction` — the value committed by Plan 02-02:

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

This is the baseline. The calibration loop may produce edits to this value after Task 3 completes.

## Task 3: Checkpoint — Awaiting Human Verification (D-11 done-gate)

**Status:** PAUSED at `checkpoint:human-verify`

Task 3 requires a human to:
1. Place real Argentine invoice images at `backend/tests/fixtures/{factura_a,remito,lista_informal}.jpg`
2. Export `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`
3. Run `--generate-ground-truth` and visually verify the JSON files
4. Run the diff loop; iterate on `SYSTEM_PROMPT` until exit 0
5. Run `pytest -m integration` and confirm `test_live_extraction_factura_a PASSED`

The calibration_report.json and final SYSTEM_PROMPT value will be recorded in the continuation SUMMARY once Task 3 is complete.

## Verification Results

- `python -c "import ast; ast.parse(open('backend/scripts/calibrate_prompt.py').read())"` — PASSED
- `cd backend && python scripts/calibrate_prompt.py --help` — PASSED (all three flags present)
- `env -u OPENAI_API_KEY python scripts/calibrate_prompt.py` exits 2 with "missing env: OPENAI_API_KEY" — PASSED
- `grep -c "claude-opus-4-7" backend/scripts/calibrate_prompt.py` = 1 — PASSED
- `grep -c "descripcion" backend/scripts/calibrate_prompt.py` = 6 — PASSED
- `grep -c "^anthropic$" backend/requirements-dev.txt` = 1 — PASSED
- `python -m pytest -m "not integration" -x -q` — 39 passed, 1 deselected — PASSED
- All required functions confirmed via AST walk — PASSED
- No `print(...OPENAI_API_KEY...)` or `print(...ANTHROPIC_API_KEY...)` lines — PASSED

## Deviations from Plan

### Auto-added: sys.path.insert for standalone script invocation [Rule 1 - Bug Fix]

- **Found during:** Task 2 verification
- **Issue:** Running `cd backend && python scripts/calibrate_prompt.py --help` (the exact invocation specified in the plan's verification section) raised `ModuleNotFoundError: No module named 'app'` because Python's module resolution did not include `backend/` in `sys.path` for standalone script invocation.
- **Fix:** Added `sys.path.insert(0, str(_BACKEND_DIR))` after imports at the top of the script, using `Path(__file__).resolve().parent.parent` to compute `backend/` regardless of cwd.
- **Files modified:** `backend/scripts/calibrate_prompt.py`
- **Commit:** d4b9714

## Known Stubs

None that block the plan's goal. The calibration infrastructure is complete. The script exits gracefully when fixture images are absent (skips with informative message). The human checkpoint (Task 3) is the intended gate before the calibration loop runs end-to-end.

## Threat Flags

No new security-relevant surface beyond what was planned in the threat model:

- **T-02-08** (key disclosure in logs): `require_env()` prints only the variable name on failure. `grep` gate confirms no `print(...KEY...)` lines. PASSED.
- **T-02-09** (fixture PII in repo): README documents privacy guidance and redaction instructions. Human checkpoint (Task 3 step 7) reviews images before commit.
- **T-02-11** (calibration_report.json on disk): Report contains only diff strings + SYSTEM_PROMPT. No API keys in any output path.
- **T-02-12** (wrong model for ground truth): `CLAUDE_MODEL = "claude-opus-4-7"` is a module-level constant. Grep gate confirmed ≥ 1 occurrence.

## Self-Check: PASSED

Files verified present:
- FOUND: backend/scripts/calibrate_prompt.py
- FOUND: backend/scripts/__init__.py
- FOUND: backend/tests/fixtures/.gitkeep
- FOUND: backend/tests/fixtures/README.md
- FOUND: backend/requirements-dev.txt (contains "anthropic")

Commits verified present:
- a500055 — chore(02-03): add anthropic dev dep, scripts package init, fixtures dir + README
- d4b9714 — feat(02-03): implement calibrate_prompt.py — ground-truth generation + diff loop
