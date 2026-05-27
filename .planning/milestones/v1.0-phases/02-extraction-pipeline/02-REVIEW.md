---
phase: 02-extraction-pipeline
reviewed: 2026-05-14T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - backend/app/config.py
  - backend/app/main.py
  - backend/app/routers/extraction.py
  - backend/app/services/extraction.py
  - backend/app/services/storage.py
  - backend/scripts/calibrate_prompt.py
  - backend/tests/test_extraction.py
  - backend/tests/test_storage.py
findings:
  critical: 3
  warning: 5
  info: 3
  total: 11
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-05-14T00:00:00Z
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

This phase implements the GPT-4o invoice extraction pipeline: a StorageBackend abstraction with path-traversal defense, an ExtractionService with confidence scoring, a debug-gated FastAPI router, and a Opus-vs-GPT-4o calibration script. Overall the architecture is sound and the path-traversal mitigation is thorough. However, three blockers were found: a silent path-traversal bypass in the storage sanitizer that drops `..` segments instead of rejecting them, exposing an unintended write target; the extraction router accepting unbounded file uploads with no size cap; and the calibration script writing the full SYSTEM_PROMPT string into a world-readable JSON report file on disk, which leaks the entire prompt to any process that can read the filesystem. Several warnings cover missing error handling in the OpenAI response, a race condition in the storage write, and structural issues in the test suite.

---

## Critical Issues

### CR-01: Path-traversal sanitizer silently rewrites malicious paths instead of rejecting them

**File:** `backend/app/services/storage.py:74-83`

**Issue:** The sanitizer strips `..` components and reassembles the remaining parts. For the caller-constructed path `"{uuid}/../../etc/passwd"`, safe_parts becomes `[uuid_str, "etc", "passwd"]` and the file is written to `{root}/{uuid}/etc/passwd`. This is the *intended* caller-side contract, but the test at `test_storage.py:38-57` exposes that the sanitizer also accepts *attacker-controlled* filenames like `"../../etc/passwd"` — dropping the `..` segments and writing to `{root}/etc/passwd`. Because the extraction router passes `file.filename` (an HTTP multipart `Content-Disposition` header value controlled by the client) into `ExtractionService.extract()`, which then calls `storage.save(image_bytes, f"{invoice_uuid}/{safe_basename}")`, the `os.path.basename(filename)` call on line 225 of `extraction.py` is the *only* guard on the basename. A filename like `"../../evil"` would be reduced to `"evil"` by `os.path.basename`, so the router path is actually safe. But `LocalStorageBackend.save()` is a public API method that accepts arbitrary `filename` strings. Any future caller — or the calibration script — that does not first apply `os.path.basename` before calling `save()` will silently write to an attacker-influenced path inside the storage root. The current contract (test line 55-56) explicitly asserts that `"../../etc/passwd"` results in a write to `{root}/etc/passwd`, which means the storage layer *accepts and normalizes* traversal input rather than *rejecting* it. This is a correctness-as-security-boundary issue: the defense-in-depth realpath check (step 7) only catches escapes *outside* the root; traversal *within* the root (to unintended subdirectories) is silently permitted.

More concretely, a caller passing `save(data, "../../other-tenant-uuid/invoice.jpg")` would write `{root}/other-tenant-uuid/invoice.jpg` with no error or log, silently overwriting another invoice file. While multi-tenancy is out of v1 scope, the surface grows every time a new caller uses this API.

**Fix:** Reject any filename that contains `..` segments before reassembly. The per-component filter should raise `ValueError` if any component is `".."`, rather than silently dropping it:

```python
# Step 3: reject traversal tokens; drop only empty strings and single dots
safe_parts = []
for p in parts:
    if p == "..":
        raise ValueError(
            f"filename {filename!r} contains '..' traversal component; rejected"
        )
    if p and p != ".":
        safe_parts.append(p)
```

The existing defense-in-depth realpath check (step 7) can remain as a belt-and-suspenders guard, but the primary defense should be explicit rejection, not silent rewriting.

---

### CR-02: No file size limit on the debug upload endpoint — trivial memory exhaustion / OOM

**File:** `backend/app/routers/extraction.py:58`

**Issue:** `data = await file.read()` reads the entire uploaded file into memory with no size cap. The extraction endpoint is gated behind `DEBUG=True`, but debug mode is commonly enabled on developer laptops and staging servers. A developer or anyone with network access to a staging instance can upload a multi-gigabyte file, causing the process to OOM-kill itself or exhaust the host's memory. Additionally, `await file.read()` with large files blocks the event loop for the duration of the read if the underlying transport is slow (pywa or httpx transports vary in chunking behavior).

This is also the pattern that will be copy-pasted into the production webhook handler in Phase 3. Establishing no size limit here propagates the bug forward.

**Fix:** Enforce an explicit size cap before passing bytes to the service. FastAPI provides no built-in upload size limit, so it must be done manually:

```python
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB — sufficient for any invoice photo

@router.post("/test", response_model=ExtractionResult)
async def extraction_test(
    file: UploadFile = File(...),
    service: ExtractionService = Depends(get_extraction_service),
) -> ExtractionResult:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_UPLOAD_BYTES // 1024 // 1024} MB.",
        )
    return await service.extract(
        image_bytes=data,
        filename=file.filename or "upload.bin",
    )
```

---

### CR-03: SYSTEM_PROMPT written verbatim into the calibration report JSON on disk

**File:** `backend/scripts/calibrate_prompt.py:409-415`

**Issue:** The `cmd_diff()` function writes the full `SYSTEM_PROMPT` string into `calibration_report.json` under the `"system_prompt"` key:

```python
report: dict[str, Any] = {
    "system_prompt": SYSTEM_PROMPT,
    ...
}
...
REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))
```

`REPORT_PATH` is `backend/tests/fixtures/calibration_report.json`. This file lands inside the `tests/fixtures/` directory which, based on plan comments about committing fixture images in Plan 03, is likely tracked by git. Once committed, the prompt is permanently in git history. Even if `.gitignore` excludes it, the file is world-readable on any machine that runs the calibration script, including CI runners. Prompt leakage is a confidentiality issue (the prompt embeds business logic about Argentine invoice types, field disambiguation rules, etc.) and makes prompt injection attacks easier by revealing the exact system prompt structure.

**Fix:** Replace the verbatim prompt with a hash or truncated excerpt in the report. Store the full prompt separately if diff-tracking is needed:

```python
import hashlib

report: dict[str, Any] = {
    "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
    "system_prompt_length": len(SYSTEM_PROMPT),
    # Do NOT embed the full prompt text in the report file
    ...
}
```

If full prompt archiving is desired for calibration history, write it to a separate file that is explicitly `.gitignore`d.

---

## Warnings

### WR-01: `completion.choices[0]` accessed without checking that `choices` is non-empty

**File:** `backend/app/services/extraction.py:200`

**Issue:** After `await self._client.chat.completions.parse(...)`, the code immediately accesses `completion.choices[0].message` without verifying that `completion.choices` is non-empty. The OpenAI API can return an empty `choices` list when the request is rate-limited, when a content filter triggers at the response level (distinct from a per-message refusal), or when the model returns a `stop_reason` other than `stop`. In these cases, `completion.choices[0]` raises `IndexError`, which falls through to the outer `except Exception` handler and becomes a generic `ExtractionFailedError` with an opaque `"list index out of range"` message — losing all diagnostic context.

**Fix:**

```python
msg = completion.choices[0].message if completion.choices else None
if msg is None:
    log.error("extraction.failed", error="empty_choices", stage="openai_parse")
    raise ExtractionFailedError("GPT-4o returned an empty choices list")
return (msg.parsed, msg.refusal)
```

---

### WR-02: Storage write is not atomic — partial writes produce corrupt files

**File:** `backend/app/services/storage.py:109-111`

**Issue:** The file is opened with `open(full_path, "wb")` and written in a single `fh.write(data)` call. If the process is killed mid-write (SIGKILL, OOM, power loss), a zero-byte or partial file is left at the target path. Subsequent reads will see a corrupt file without any indication that the write was incomplete. For an invoice audit system where original files are "retained for audit" (per CLAUDE.md), silent partial writes are a data-integrity issue.

**Fix:** Write to a temp file in the same directory and rename atomically:

```python
import tempfile

parent = os.path.dirname(full_path)
if parent:
    os.makedirs(parent, exist_ok=True)

with tempfile.NamedTemporaryFile(dir=parent, delete=False, suffix=".tmp") as tmp:
    tmp.write(data)
    tmp_path = tmp.name

os.replace(tmp_path, full_path)  # atomic on POSIX; best-effort on Windows
return relative_path
```

---

### WR-03: `get_extraction_service` dependency creates a new `AsyncOpenAI` client on every request

**File:** `backend/app/routers/extraction.py:27-42`

**Issue:** `get_extraction_service()` is a plain function (not a FastAPI dependency with `yield` or caching). FastAPI resolves it on every request, creating a fresh `AsyncOpenAI(api_key=...)` client and a fresh `LocalStorageBackend` instance each time. `AsyncOpenAI` opens an internal `httpx.AsyncClient` connection pool on construction. Creating and discarding a new pool per request prevents connection reuse to the OpenAI API, adding TCP handshake and TLS overhead to every extraction call. For a debug endpoint this is tolerable, but the pattern will be carried into the production handler in Phase 3.

**Fix:** Use `lru_cache` or module-level singletons for the OpenAI client, or convert the dependency to use FastAPI's application-state pattern:

```python
# In main.py lifespan, store on app.state:
app.state.openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
app.state.storage = LocalStorageBackend(root=settings.storage_path)

# In the router dependency:
def get_extraction_service(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> ExtractionService:
    return ExtractionService(
        openai_client=request.app.state.openai_client,
        storage=request.app.state.storage,
        settings=settings,
    )
```

---

### WR-04: `generate_ground_truth` uses a synchronous Anthropic client from inside an `asyncio.run()` context

**File:** `backend/scripts/calibrate_prompt.py:165-203`

**Issue:** `generate_ground_truth()` is called from the synchronous `cmd_generate_ground_truth()` function. Internally it calls `client.messages.create(...)` via the synchronous `Anthropic()` client — this blocks the calling thread for the full network round-trip duration. However, `cmd_diff()` calls `asyncio.run(run_gpt4o_extraction(...))` per fixture (line 429), which creates and tears down an event loop per fixture. If someone adds a concurrent calibration mode later (e.g., calling both GPT-4o and Opus inside the same asyncio context), mixing sync Anthropic calls inside an active event loop will deadlock or raise `RuntimeError: This event loop is already running`. The pattern is fragile and will break the moment the calling context is made async.

**Fix:** Either use the `AsyncAnthropic` client in `generate_ground_truth()` (and make the function `async`), or document explicitly that `generate_ground_truth()` must never be called from within a running event loop.

---

### WR-05: `overwrite` flag on `cmd_generate_ground_truth` args checked with `getattr` — missing from `argparse` definition

**File:** `backend/scripts/calibrate_prompt.py:375`

**Issue:** The code uses `getattr(args, "overwrite", False)` to check for an `--overwrite` flag, but no `--overwrite` argument is added to the `argparse` parser (lines 479-505). This means `--overwrite` is never available to users; the `getattr` with a default silently masks the missing registration. A user who expects `--overwrite` to force regeneration of existing ground-truth files will find the flag silently ignored.

**Fix:** Either add the argument to the parser:

```python
parser.add_argument(
    "--overwrite",
    action="store_true",
    help="Overwrite existing ground-truth files.",
)
```

Or replace `getattr(args, "overwrite", False)` with `args.overwrite` (which will raise `AttributeError` at runtime if the flag is missing, making the oversight immediately visible).

---

## Info

### IN-01: `status` field on `ExtractionResult` is an unconstrained `str` — use a `Literal` or `Enum`

**File:** `backend/app/services/extraction.py:96`

**Issue:** `status: str` accepts any string. The domain only ever produces `"auto_saved"` or `"pending_review"` (per D-03). Downstream consumers (Phase 3 DB write, Phase 4 UI filter) will need to branch on these values. Using a bare `str` provides no type-system enforcement.

**Fix:**

```python
from typing import Literal
status: Literal["auto_saved", "pending_review"]
```

---

### IN-02: Hardcoded `"gpt-4o"` model string in `ExtractionService._call_gpt4o()`

**File:** `backend/app/services/extraction.py:177`

**Issue:** The model is hardcoded as `"gpt-4o"` rather than being read from `settings`. The CLAUDE.md recommendation is `gpt-4o-2024-08-06` or later for guaranteed Structured Output compliance. Using the bare alias `"gpt-4o"` means the pinned model changes whenever OpenAI rotates the alias pointer, breaking Structured Output compatibility silently. Additionally, the calibration script uses a separate `GPT_MODEL = "gpt-4o"` constant (line 63), creating two independent points of truth.

**Fix:** Add `openai_model: str = "gpt-4o-2024-08-06"` to `Settings` and reference `self._settings.openai_model` in `_call_gpt4o()`. Remove the separate `GPT_MODEL` constant in `calibrate_prompt.py` and derive it from settings.

---

### IN-03: `normalize_value` strips trailing `"."` from strings — may corrupt CUIT strings

**File:** `backend/scripts/calibrate_prompt.py:252`

**Issue:** `stripped = v.strip().rstrip(".")` removes any trailing period from string values before the decimal pattern check. Argentine CUIT numbers are formatted as `"XX-XXXXXXXX-X"` — no trailing period — so this is not a direct bug. However, `rstrip(".")` is applied unconditionally to all string fields, including `proveedor` and `numero_documento`. A company name ending with a period (e.g., `"Distribuidora S.A."` extracted by the model) would become `"Distribuidora S.A"` after normalization, producing a spurious diff against the ground truth if one model preserves the period and the other does not. This causes false positives in the calibration report rather than false negatives, so it does not affect production correctness, but it pollutes the diff signal and may cause unnecessary prompt iteration.

**Fix:** Apply `rstrip(".")` only to strings that match the decimal pattern, not all strings:

```python
if isinstance(v, str):
    stripped = v.strip()  # strip whitespace only
    if stripped == "":
        return None
    clean = stripped.rstrip(".")  # remove trailing period for decimal check
    if _DECIMAL_PATTERN.match(clean):
        try:
            return str(Decimal(clean).normalize())
        except InvalidOperation:
            pass
    return stripped  # return original (whitespace-stripped) value, not rstripped
```

---

_Reviewed: 2026-05-14T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
