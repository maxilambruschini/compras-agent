---
phase: 03-prompt-trigger-endpoint
reviewed: 2026-05-30T14:40:00-03:00
depth: standard
files_reviewed: 4
files_reviewed_list:
  - backend/app/routers/prompt.py
  - backend/app/services/cierre.py
  - backend/app/services/conversation.py
  - backend/app/config.py
findings:
  critical: 0
  warning: 0
  info: 2
  total: 2
status: resolved
resolution: |
  Round 1: 2 BLOCKERs (CR-01 null cierre_monto, CR-02 double GPT call) + 3 WARNINGs
  (WR-01 phone validation, WR-02 amount correction, WR-03 import re) — all fixed.
  Round 2 re-review: the WR-01 fix introduced a new BLOCKER (prompt sent without the
  Twilio "whatsapp:" prefix → silent send failure) — fixed in commit 9dd1c1b with a
  dedicated test assertion (send recipient must start with "whatsapp:").
  Full suite green: 171 passed, 1 skipped.
  Remaining: 2 Info items (inline CajaCierreService() construction vs DI; residual
  deferred `from app.services.cierre import` inside method bodies) — non-blocking, deferred.
status_history: [issues_found, issues_found, resolved]
---

# Phase 03: Code Review Report (Iteration 2 — Post-Fix Re-Review)

**Reviewed:** 2026-05-30T14:40:00-03:00
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

This is a re-review after five fixes were applied (CR-01, CR-02, WR-01, WR-02, WR-03). Four of the five fixes are correct and complete. One prior warning (WR-01) introduced a new critical regression: the prompt endpoint now sends the WhatsApp message to a bare E.164 phone number (no `whatsapp:` prefix) while the Twilio provider explicitly requires the `whatsapp:` prefix on its `to` argument — the send will fail silently in production for every trigger call.

The CR-01 null guard, CR-02 single-extraction refactor, WR-02 correction path, and WR-03 top-level import are all correctly implemented with no regressions detected.

---

## Critical Issues

### CR-01 (NEW): Prompt endpoint sends to unprefixed number — Twilio rejects every message silently

**File:** `backend/app/routers/prompt.py:199`

**Issue:** `_safe_send` is called with `clean_phone` (line 199), which equals `body.phone_number` as validated by `PromptRequest.validate_phone` — a bare E.164 string such as `+5491112345678`. The Twilio provider's `send_message` docstring at `providers/twilio.py:84` explicitly states the `to` argument must carry the `whatsapp:` prefix (e.g. `whatsapp:+5491112345678`). Twilio's API will reject a bare E.164 number on the WhatsApp channel with a 400/21614 error.

By contrast, `ConversationOrchestrator.handle_message` correctly sends to `sender` (the original inbound string, which already carries the `whatsapp:` prefix) rather than to `clean_sender` (the DB-normalized, prefix-stripped form). The prompt endpoint does the opposite: it strips for DB storage (correct) and then also strips for the send call (incorrect).

The failure is swallowed silently by `_safe_send`'s `except Exception` wrapper (`gastos.py:163`), so the endpoint returns `200 {"status":"sent"}` while the message never reaches the manager. This is a behavioral regression introduced by WR-01's phone normalization consolidation.

The test suite does not catch this because `mock_provider.send_message` is a bare `AsyncMock` that accepts any `to` value without asserting prefix format.

**Fix:**

```python
# prompt.py — line 199: send to the whatsapp:-prefixed form, not clean_phone
await _safe_send(
    provider,
    "whatsapp:" + clean_phone,  # Twilio requires "whatsapp:+..." prefix
    PROMPT_TEXT,
    task_log,
)
```

Add a companion assertion in `test_prompt_text_sent` (or a new `test_send_uses_whatsapp_prefix`) to lock in the prefix requirement:

```python
call_to = mock_provider.send_message.call_args.kwargs.get("to") \
          or mock_provider.send_message.call_args.args[0]
assert call_to.startswith("whatsapp:"), (
    f"send_message 'to' must have whatsapp: prefix, got: {call_to!r}"
)
```

---

## Warnings

No warnings. All prior WR-01 through WR-03 findings are resolved (modulo the CR regression above which supersedes WR-01 as a blocker).

---

## Info

### IN-01: `CajaCierreService()` constructed inline — breaks DI pattern

**File:** `backend/app/services/conversation.py:681`

**Issue:** `CajaCierreService()` is constructed directly inside `_handle_cierre_confirm`:

```python
await CajaCierreService().save_cierre(session, cierre_draft.cierre_monto, conv.sender_phone)
```

`GastoService` is injected via the constructor (`self._gasto_service`) and is mockable without patching. `CajaCierreService` is not — tests that need to assert `save_cierre` was or was not called must patch `app.services.conversation.CajaCierreService` at the class level. This inconsistency will matter when integration tests need to isolate the cierre write path. Not a blocker for current tests (which drive the full FSM through `handle_message` with a real `db_session`).

**Fix:** Add `cierre_service` to `ConversationOrchestrator.__init__` alongside `gasto_service`, or document the patch target in the class docstring.

### IN-02: Two deferred `from app.services.cierre import` inside method bodies remain

**File:** `backend/app/services/conversation.py:602, 659`

**Issue:**

```python
# line 602 — inside _handle_awaiting_cierre
from app.services.cierre import _derive_hora_cierre

# line 659 — inside _handle_cierre_confirm
from app.services.cierre import CajaCierreService, _derive_hora_cierre
```

WR-03 correctly removed the `__import__("re")` call and added `import re` at the top of the file, but these two deferred imports were left in place. Python's module cache means there is no correctness or performance issue after the first call, but the pattern is inconsistent with the top-level import style used everywhere else in the file. There is no circular import risk: `cierre.py` does not import from `conversation.py`.

**Fix:** Hoist both imports to the top-level import block:

```python
from app.services.cierre import CajaCierreService, _derive_hora_cierre
```

---

## Prior Findings — Disposition

| ID | Original Finding | Status |
|----|-----------------|--------|
| CR-01 (orig) | None guard before `save_cierre` on corrupt/missing draft | **Resolved** — guard at line 671 correctly catches both null-draft and corrupt-draft paths; resets to `AWAITING_CIERRE`; `test_corrupt_draft_resets_to_awaiting_cierre` and `test_empty_draft_gasto_resets_to_awaiting_cierre` cover both cases. |
| CR-02 | Double LLM call in gasto handoff from `_handle_awaiting_cierre` | **Resolved** — `_handle_idle` is no longer called; slots are extracted once and applied directly via `patch_draft(DraftGasto(), slots)`; both sub-paths (monto-only → `AWAITING_MONTO`, concepto-known → `AWAITING_TICKET`) are correctly replicated without a second `extract()` call. |
| WR-01 | Phone number `field_validator` + unified `clean_phone` for DB and send | **Partially resolved — introduced new CR regression.** The `field_validator` is correct and `clean_phone` is correctly used for DB writes. However the send call (line 199) also uses `clean_phone` (stripped, no `whatsapp:` prefix) instead of the prefixed form that Twilio requires. See new CR-01 above. |
| WR-02 | Amount-correction path in `AWAITING_CIERRE_CONFIRM` | **Resolved** — `parse_ars_amount` is used deterministically (lines 691–694); no LLM call at the write gate; `DraftCierre` is reassigned not mutated; the corrected `cierre_draft.cierre_monto` is used in the re-echo. |
| WR-03 | `__import__("re")` replaced with top-level import | **Resolved** — `import re` at line 66 of `conversation.py`. |

---

_Reviewed: 2026-05-30T14:40:00-03:00_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
