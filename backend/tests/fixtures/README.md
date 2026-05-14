# Phase 2 Extraction Fixtures

Real Argentine invoice photographs used by `tests/test_extraction.py::test_live_extraction_factura_a`
(when `-m integration` is enabled) and by `scripts/calibrate_prompt.py` (D-11 calibration loop).

## Required Image Files

Place the following image files in this directory before running calibration:

| Filename | Document Type | Notes |
|----------|--------------|-------|
| `factura_a.jpg` | Factura A | AFIP-format; required for integration test |
| `remito.jpg` | Remito | Delivery note; optional but recommended |
| `lista_informal.jpg` | Lista informal | Informal price list; optional but recommended |

Both `.jpg` and `.png` extensions are accepted. The calibration script will detect the
format automatically.

## Generated Files

The following files are produced by `python scripts/calibrate_prompt.py --generate-ground-truth`
(uses Claude Opus 4.7 as the ground-truth model — D-12):

- `factura_a_ground_truth.json`
- `remito_ground_truth.json`
- `lista_informal_ground_truth.json`
- `calibration_report.json` (produced by the diff loop)

**Do NOT hand-edit** the `*_ground_truth.json` files — source-of-truth is Claude Opus 4.7.
If a value is clearly wrong after visual inspection (step 4 of the checkpoint), open the JSON
and correct it before running the diff loop. Document any edits.

## Privacy Guidance

These are photographs of REAL purchase documents. Redact personally identifying information
(employee names, addresses) before committing. CUITs may remain visible — they are
public-registry numbers per Argentine law.

## Running Calibration

1. Place images here.
2. Export API keys:
   ```bash
   export OPENAI_API_KEY=...
   export ANTHROPIC_API_KEY=...
   ```
3. Generate ground truth:
   ```bash
   cd backend && python scripts/calibrate_prompt.py --generate-ground-truth
   ```
4. Run diff loop (D-11 done-gate):
   ```bash
   cd backend && python scripts/calibrate_prompt.py
   ```

Exit code 0 = clean diffs across all fixtures. Exit code 1 = diffs found (iterate on SYSTEM_PROMPT).
