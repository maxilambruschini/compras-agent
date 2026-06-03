---
phase: 01-data-conversation-core
plan: "02"
subsystem: backend/services
tags: [pydantic, openai, slot-extraction, amounts, tdd, gastos-bot]
dependency_graph:
  requires:
    - 01-01 (Gasto/Conversation ORM models; AGENT_MODE config)
  provides:
    - parse_ars_amount() utility (backend/app/services/amounts.py)
    - GastoSlots + DraftGasto DTOs (backend/app/models/conversation.py)
    - SlotExtractionService (backend/app/services/slot_extraction.py)
  affects:
    - backend/app/services/slot_extraction.py (new)
    - backend/app/models/conversation.py (new)
    - backend/app/services/amounts.py (new)
    - backend/tests/test_amounts.py (new)
    - backend/tests/test_slot_extraction.py (new)
tech_stack:
  added: []
  patterns:
    - parse_ars_amount(): module-level pure function (mirrors compute_confidence/assign_status in extraction.py)
    - GastoSlots/DraftGasto: all-Optional Pydantic BaseModel with ConfigDict(use_enum_values=True) — mirrors ExtractedInvoice
    - SlotExtractionService: constructor DI (AsyncOpenAI + Settings), async extract(), refusal-before-parsed check, SLOT_SYSTEM_PROMPT constant, SlotExtractionError hierarchy — mirrors ExtractionService
    - ARS format validation regex: dot=thousands-sep, comma=decimal-sep pattern before stripping
key_files:
  created:
    - path: backend/app/services/amounts.py
      purpose: parse_ars_amount() pure utility — handles Decimal("1.500") trap
    - path: backend/app/models/conversation.py
      purpose: GastoSlots (monto Optional[float]) and DraftGasto (monto Optional[Decimal]) DTOs
    - path: backend/app/services/slot_extraction.py
      purpose: SlotExtractionService using gpt-4o-mini .parse() → GastoSlots
    - path: backend/tests/test_amounts.py
      purpose: 11 tests for parse_ars_amount including ROADMAP success criterion 5 assertions
    - path: backend/tests/test_slot_extraction.py
      purpose: 14 tests for GastoSlots/DraftGasto DTOs and SlotExtractionService (mocked OpenAI)
decisions:
  - GastoSlots.monto is Optional[float] (JSON number) not Optional[Decimal] — GPT Structured Outputs emits a JSON number, completely sidestepping the Decimal("1.500") trap; orchestrator converts to Decimal(str(slots.monto)) after extraction (per D-06 + RESEARCH Pattern 2)
  - parse_ars_amount() uses a format-validation regex before stripping separators — prevents edge cases like "1.2.3.4" (malformed) from silently parsing as "1234"; also rejects Decimal("NaN") and Decimal("inf")
  - SlotExtractionService constructor takes Settings (matching RESEARCH Pattern 1) even though the service currently only uses openai_client — consistent with ExtractionService DI shape for future extensibility
metrics:
  duration: "~15 minutes"
  completed: "2026-05-27"
  tasks_completed: 2
  tasks_total: 2
  files_created: 5
  files_modified: 1
---

# Phase 01 Plan 02: Slot Extraction (Amounts, DTOs, SlotExtractionService) Summary

**One-liner:** parse_ars_amount() handles the Decimal("1.500") trap with format validation; GastoSlots/DraftGasto are all-Optional Pydantic DTOs; SlotExtractionService mirrors ExtractionService on gpt-4o-mini with refusal-before-parsed contract.

## What Was Built

### Task 1 — parse_ars_amount() utility (TDD)

Pure module-level function in `backend/app/services/amounts.py`:

- **The Decimal("1.500") trap:** `Decimal("1.500")` returns 1.5 in Python, not 1500. Argentine invoices use dot as a thousands separator. Without this utility, $1.500 ARS becomes $1.50.
- **Implementation:** validates ARS number format via regex (dot followed by exactly 3 digits = thousands separator), then strips dots and replaces comma with dot before `Decimal()` parsing.
- **Returns None** on: None input, empty string, whitespace-only, NaN, Infinity, malformed patterns — null > hallucination.
- **No `locale` module** — global mutable state, unsafe in async contexts.
- **11 tests** in `test_amounts.py` covering all ROADMAP success criterion 5 assertions plus edge cases.

### Task 2 — GastoSlots + DraftGasto DTOs and SlotExtractionService (TDD)

**`backend/app/models/conversation.py`** — two Pydantic DTOs:

- **GastoSlots**: `concepto: Optional[str] = None`, `monto: Optional[float] = None`. Float for monto forces GPT Structured Outputs to emit a JSON number — "$1.500" becomes 1500.0, never the locale-formatted string.
- **DraftGasto**: `concepto: Optional[str] = None`, `monto: Optional[Decimal] = None`, `ticket_image_path: Optional[str] = None`, `failure_count: int = 0`. Decimal for monto (converted by orchestrator in Plan 04). `failure_count` tracks CONV-06 re-prompt threshold.
- D-01 enforced: no `lugar`, `proveedor`, `entrada`, `category` on either DTO.
- `ConfigDict(use_enum_values=True)` on both — required for OpenAI Structured Outputs JSON Schema (mirrors ExtractedInvoice).

**`backend/app/services/slot_extraction.py`** — SlotExtractionService:

- Constructor: `__init__(self, openai_client: AsyncOpenAI, settings: Settings)` — DI, never constructed at import (Pitfall 3).
- `async extract(self, text: str) -> GastoSlots` — calls `await self._client.chat.completions.parse(model="gpt-4o-mini", ..., response_format=GastoSlots)`.
- **Refusal checked BEFORE parsed** (mirrors ExtractionService contract).
- Returns `GastoSlots()` (all None) on refusal OR parsed=None — orchestrator re-prompts (CONV-06).
- `SLOT_SYSTEM_PROMPT` constant (module-level) in Argentine Spanish: instructs GPT to return monto as a plain JSON number; null for any field not clearly stated.
- `SlotExtractionError` base exception + transport error wrapping.
- structlog per-call binding with text preview; never logs secrets (T-02-02).
- **14 tests** in `test_slot_extraction.py` covering all behavior cases with mocked AsyncOpenAI.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] parse_ars_amount("NaN") returning Decimal("NaN") instead of None**

- **Found during:** Task 1 GREEN phase — first test run
- **Issue:** `Decimal("NaN")` is valid Python (NaN is a valid Decimal value) but is not a valid monetary amount. The implementation returned `Decimal('NaN')` for input "NaN".
- **Fix:** Added explicit `result.is_nan() or result.is_infinite()` guard after parsing.
- **Files modified:** `backend/app/services/amounts.py`
- **Commit:** b58d7c1

**2. [Rule 1 - Bug] parse_ars_amount("1.2.3.4") incorrectly returning Decimal("1234")**

- **Found during:** Task 1 GREEN phase — second test run after NaN fix
- **Issue:** "1.2.3.4" has dots NOT followed by exactly 3 digits — not a valid ARS format. Without validation, the naive strip-dots approach yielded `Decimal("1234")`.
- **Fix:** Added format-validation regex before stripping separators. Pattern requires each dot to be followed by exactly 3 digits (thousands group). Malformed patterns return None.
- **Files modified:** `backend/app/services/amounts.py`
- **Commit:** b58d7c1

**3. [Rule 1 - Bug] Pydantic v2.11+ deprecation warning in tests**

- **Found during:** Task 2 GREEN phase — `model_fields` accessed on instance instead of class
- **Issue:** Two tests used `instance.model_fields` which Pydantic v2.11 deprecates (access on class only).
- **Fix:** Changed to `GastoSlots.model_fields` and `DraftGasto.model_fields` (class access).
- **Files modified:** `backend/tests/test_slot_extraction.py`
- **Commit:** 3481980

## Test Results

```
25 passed  (tests/test_amounts.py + tests/test_slot_extraction.py)
105 passed, 1 skipped  (full suite)
```

ROADMAP success criterion 5 assertions:
- `parse_ars_amount("1.500") == Decimal("1500")` — PASS
- `parse_ars_amount("1.234,56") == Decimal("1234.56")` — PASS
- `parse_ars_amount("1500") == Decimal("1500")` — PASS
- `parse_ars_amount("abc") is None` — PASS

## Known Stubs

None — this plan creates pure service/DTO code. No UI rendering, no data wiring.

## Threat Flags

None — no new network endpoints, no auth paths, no file access patterns, no schema changes beyond what the plan's threat model covers.

**T-02-01 (Tampering, monto):** mitigated — `monto: Optional[float]` in GastoSlots; GPT emits JSON number; orchestrator (Plan 04) bounds-checks and requires explicit confirmation.
**T-02-02 (Information Disclosure, structlog):** mitigated — structlog logs only `text_preview=text[:50]`; API key is in `_client` (never logged); no full text logged.
**T-02-03 (Tampering/injection, inbound text):** accepted — GPT extracts into a fixed Optional schema; worst case is a wrong slot value caught at the mandatory confirm step.

## Self-Check: PASSED

| Item | Status |
|------|--------|
| backend/app/services/amounts.py | FOUND |
| backend/app/models/conversation.py | FOUND |
| backend/app/services/slot_extraction.py | FOUND |
| backend/tests/test_amounts.py | FOUND |
| backend/tests/test_slot_extraction.py | FOUND |
| .planning/phases/01-data-conversation-core/01-02-SUMMARY.md | FOUND |
| Commit 37b74e2 (RED test_amounts) | FOUND |
| Commit b58d7c1 (GREEN parse_ars_amount) | FOUND |
| Commit 56748ff (RED test_slot_extraction) | FOUND |
| Commit 3481980 (GREEN DTOs + SlotExtractionService) | FOUND |
| 25 tests pass (test_amounts + test_slot_extraction) | PASSED |
| Full suite 105 passed 1 skipped | PASSED |
