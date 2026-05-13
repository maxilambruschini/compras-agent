---
phase: 02
reviewers: [claude]
reviewed_at: 2026-05-13T16:52:00-03:00
plans_reviewed: [02-01-PLAN.md, 02-02-PLAN.md, 02-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 2

## Claude Review

## Phase 2 Extraction Pipeline — Plan Review

---

### Summary

These three plans form a well-structured wave-based delivery of the extraction pipeline. The TDD discipline is tight, the threat model is thorough, and the calibration-as-deliverable (D-11) is the right call. The interfaces are precisely specified and the research artifacts are unusually complete. That said, there are two HIGH-severity issues that would break implementation — one a logic bug in the storage sanitization algorithm, the other a missing mock strategy in the ASGI test — plus several MEDIUM issues worth addressing before execution.

---

### Strengths

- **TDD wave discipline**: RED→GREEN per task, explicit Wave-0 scaffolding before implementation. No shortcuts.
- **Interface locking before enrichment**: Plan 01 locks all public surfaces; Plans 02/03 only enrich internals and tests. Clean dependency ordering.
- **Threat model specificity**: T-02-01 (path traversal), T-02-02 (key leakage), T-02-03 (debug endpoint exposure) all have grep-verifiable acceptance criteria tied directly to tests.
- **Ground truth anti-circularity (D-12)**: Using Claude Opus 4.7 instead of GPT-4o for ground truth is the correct call. Enforcement via `grep -c "claude-opus-4-7"` acceptance gate is pragmatic.
- **Calibration as first-class deliverable**: D-11 gate on `calibration_report.json clean=true` prevents premature phase close.
- **structlog secret exclusion**: The `grep -v '^#' | grep -c "openai_api_key"` gate is a simple but effective T-02-02 mitigation.
- **`os.path.commonpath` double-check**: Defense-in-depth on top of basename stripping — good.

---

### Concerns

**HIGH — Storage path reconstruction algorithm bug (Plan 01, Task 2)**

The algorithm for preserving the UUID prefix has a broken step. For `filename = "uuid-xxx/../../bad"`:

```
os.path.split("uuid-xxx/../../bad") → directory_part="uuid-xxx/../..", basename="bad"
os.path.basename("uuid-xxx/../..") → ".."
relative_path = os.path.join("..", "bad") → "../bad"
full_path = os.path.join(root, "../bad") → escapes root
commonpath check → raises ValueError
```

But `test_save_with_uuid_prefix_filename` asserts the file **is written** to `{tmp_path}/bad`, not that a ValueError is raised. The test behavior and the implementation description are contradictory.

**Fix**: Use `os.path.basename(filename)` as the sole sanitizer for the filename component, and extract only `PurePosixPath(filename).parts[0]` as the directory prefix (only when `parts[0]` doesn't start with `.`). Alternatively, drop the directory-part preservation entirely in `save()` — the service already constructs `f"{invoice_uuid}/{safe_basename}"` before calling storage, so `LocalStorageBackend.save()` can just do `os.path.basename(filename)` for everything. The UUID comes from the service layer, not storage's responsibility to preserve it.

---

**HIGH — ASGI test has no OpenAI mock strategy (Plan 01, Task 1 + Task 3)**

`test_post_extraction_test_returns_extraction_result_when_debug_true` POSTs a multipart file to `/extraction/test`. The router's `get_extraction_service` dependency constructs a real `AsyncOpenAI(api_key=settings.openai_api_key)`. Nothing in the test instructs how to prevent the live GPT-4o call.

The test action says "monkeypatch settings.debug=True" but doesn't say how `get_extraction_service` is overridden. Three viable approaches:
1. Override `get_extraction_service` via `app.dependency_overrides` in the fixture (same pattern as `override_get_db` in `test_health.py`)
2. Patch `AsyncOpenAI` at the openai module level
3. Have the fixture construct a `LocalStorageBackend`-backed `ExtractionService` with mocked `openai_client` and inject it

The plan needs to specify which. Option 1 is the cleanest and matches the existing dependency override pattern.

---

**MEDIUM — Plan 03 `depends_on` is incomplete**

```yaml
depends_on: [02-01]
```

Plan 03 imports `SYSTEM_PROMPT` from `app.services.extraction`, which is added in Plan 02 Task 1. Without Plan 02 completing first, the import will fail. Should be:

```yaml
depends_on: [02-01, 02-02]
```

---

**MEDIUM — `app = create_app()` cache interaction in test fixtures**

`create_app()` calls `get_settings()` which is `lru_cached`. The `debug_client` and `nodebug_client` fixtures need to produce apps with different `debug` values. The `env_setup` fixture clears the cache at session start, but within the session, switching DEBUG between True and False requires:
1. Monkeypatching the `DEBUG` env var
2. Clearing `get_settings.cache_clear()`
3. Calling `create_app()` fresh

The plan mentions monkeypatching but doesn't spell out cache clearing. This is likely to produce flaky tests where the `nodebug_client` fixture inherits a cached debug=True settings from the `debug_client` fixture.

---

**MEDIUM — MIME type hardcoded as `image/jpeg` for all files**

`_call_gpt4o` constructs `data:image/jpeg;base64,{b64}` regardless of the actual file extension. OpenAI's vision API accepts PNG labeled as JPEG in practice, but the RESEARCH.md open question (#1) correctly flags this. The calibration script's `detect_media_type()` is defined but `ExtractionService._call_gpt4o` doesn't use it. Either wire it in or document the known limitation explicitly in the service.

---

**MEDIUM — `asyncio.run()` per fixture in calibration diff loop**

`cmd_diff` calls `asyncio.run(run_gpt4o_extraction(path, settings))` inside a for loop. Each fixture creates and destroys a full event loop. On some Python implementations this emits deprecation warnings. Cleaner: collect all fixtures first, then run a single `asyncio.run(run_all_extractions(fixtures, settings))` with `asyncio.gather`.

---

**LOW — `diff_invoice` line_items comparison drops field-level diffs when length matches**

When lengths match but item order differs (GPT-4o reorders line items), all fields look wrong. The calibration report will show many spurious field diffs. Consider sorting line items by `descripcion` before diffing, or at minimum noting this limitation in the script docstring.

---

**LOW — `backend/app/services/__init__.py` not mentioned**

PATTERNS.md notes the `services/` directory is "empty, ready for extraction.py and storage.py" but Plan 01 doesn't verify the `__init__.py` exists. If it doesn't, the entire import chain fails. Add a check or creation step.

---

### Suggestions

1. **Simplify `LocalStorageBackend.save()` sanitization**: Make the rule explicit — `save()` takes a pre-constructed relative path from the caller (`{uuid}/{basename}`). Sanitization: `os.path.basename(filename)` + `commonpath` reject. Remove directory-part reconstruction logic; it adds complexity and has the bug. Document that callers pre-construct paths.

2. **Add `app.dependency_overrides[get_extraction_service]` pattern to ASGI tests**: Mirror `test_health.py`'s `override_get_db` exactly. This lets the debug test avoid real GPT-4o calls.

3. **Add `anthropic` import guard to `calibrate_prompt.py`**: Wrap `from anthropic import Anthropic` in `try/except ImportError` with message: `"Install anthropic: pip install anthropic (dev dep only, see requirements-dev.txt)"`.

4. **Add `STORAGE_PATH` to the `env_setup` fixture**: Tests constructing `LocalStorageBackend` rely on the default `/data/invoices` which may not exist in CI. Patching `STORAGE_PATH=str(tmp_path)` at session or fixture level prevents silent write failures.

5. **Sort line items before diffing in `calibrate_prompt.py`**: Add `key=lambda x: x.get("descripcion") or ""` sort before item-by-item comparison to reduce false positives from GPT-4o row reordering.

---

### Risk Assessment: **MEDIUM**

The two HIGH issues are fixable before execution begins — they don't require plan restructuring, just specification corrections in Task 2's storage algorithm and explicit mock strategy in Task 1's ASGI test. The MEDIUM issues are implementation details that a careful executor will work around but could silently produce incorrect behavior (cache interactions) or CI failures (asyncio warnings). The overall plan architecture is sound, the TDD discipline is exemplary, and the calibration loop as a done-gate is the right philosophy for an AI extraction feature. Resolve the HIGH items before starting Wave 1 execution.

---

## Consensus Summary

*Single reviewer — no cross-reviewer consensus applicable.*

### Agreed Strengths

- TDD wave discipline with RED→GREEN per task and explicit Wave-0 scaffolding
- Interface locking in Plan 01 before enrichment in Plans 02/03 — clean dependency ordering
- Threat model is specific and grep-verifiable (T-02-01, T-02-02, T-02-03)
- Calibration loop as a Phase 2 done-gate (D-11) is the right call for an AI extraction feature
- Ground truth anti-circularity: Claude Opus 4.7 for ground truth, not GPT-4o

### HIGH Concerns (block execution)

1. **Storage path reconstruction bug in `LocalStorageBackend.save()`** — test assertions and implementation description are contradictory; path traversal escape is possible with crafted filenames. Fix: simplify to `os.path.basename()` only; service layer owns UUID path construction.
2. **ASGI router test lacks explicit OpenAI mock strategy** — no `dependency_overrides[get_extraction_service]` specified; test would make live API calls. Fix: mirror `override_get_db` pattern from `test_health.py`.

### MEDIUM Concerns (address before execution)

- Plan 03 `depends_on` should include `02-02` (imports `SYSTEM_PROMPT` defined there)
- `get_settings()` lru_cache interaction in debug/nodebug test fixtures needs explicit `cache_clear()` call
- MIME type hardcoded as `image/jpeg` — calibration script's `detect_media_type()` not wired into service

### Divergent Views

*N/A — single reviewer.*
