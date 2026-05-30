---
phase: 03-prompt-trigger-endpoint
reviewed: 2026-05-30T14:30:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - backend/app/routers/prompt.py
  - backend/app/services/cierre.py
  - backend/app/services/conversation.py
  - backend/app/config.py
  - backend/app/main.py
  - backend/tests/conftest.py
  - backend/tests/test_prompt_trigger.py
  - backend/tests/test_conversation_cierre.py
findings:
  critical: 2
  warning: 3
  info: 2
  total: 7
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-05-30T14:30:00Z
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Phase 3 introduces the `POST /gastos/prompt` bearer-token endpoint and the `AWAITING_CIERRE` / `AWAITING_CIERRE_CONFIRM` FSM arms. The authentication (constant-time compare, fail-closed empty-token guard), the lock ordering (INSERT-then-FOR-NO-KEY-UPDATE before state read/write), and the send-after-commit sequencing are all correctly implemented. The `begin_nested()` / `db.commit()` transaction dance is sound for both production (autobegun outer transaction) and the test fixture pattern.

Two blockers were found: (1) `_handle_cierre_confirm` passes `cierre_draft.cierre_monto` (which is `Optional[Decimal]`, default `None`) directly to `save_cierre` without a null guard — corrupt or missing draft JSON causes a `None` to reach a `NOT NULL` database column, producing an `IntegrityError` crash at the write boundary; (2) the gasto handoff path inside `_handle_awaiting_cierre` calls `self._slot_service.extract(text)` twice for the same message, discarding the first result and re-rolling the LLM dice — if the second call returns `None` for a field the first call found, the handler deflects instead of advancing the gasto flow, creating a silent correctness failure.

---

## Structural Findings (fallow)

No structural pre-pass was provided for this phase.

---

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: `_handle_cierre_confirm` passes `Optional[Decimal] = None` to `save_cierre` without null guard — crashes on corrupt draft

**File:** `backend/app/services/conversation.py:644-659`

**Issue:** `DraftCierre.cierre_monto` is declared `Optional[Decimal] = None` (conversation.py line 78). In `_handle_cierre_confirm`, the draft is initialized to `DraftCierre()` (i.e., `cierre_monto=None`) before the parse attempt:

```python
cierre_draft = DraftCierre()          # cierre_monto = None
if conv.draft_gasto:
    try:
        cierre_draft = DraftCierre.model_validate_json(conv.draft_gasto)
    except Exception:
        self._log.warning("conversation.cierre_draft_parse_error")
        # cierre_draft remains DraftCierre() — cierre_monto stays None
```

When the parse fails (corrupt JSON, schema mismatch after deploy, or `draft_gasto` containing a `DraftGasto` serialization due to a state machine bug), execution falls through to:

```python
if is_confirmation(text):
    await CajaCierreService().save_cierre(
        session, cierre_draft.cierre_monto, conv.sender_phone   # None passed here
    )
```

`save_cierre` accepts `efectivo_en_caja: Decimal` (not `Optional[Decimal]`) and immediately constructs `CajaCierre(efectivo_en_caja=None, ...)`. `CajaCierre.efectivo_en_caja` is `nullable=False` in the ORM and the DB schema. SQLAlchemy will raise an `IntegrityError` (or `StatementError`) at flush time, crashing the entire transaction, leaving the conversation stuck in `AWAITING_CIERRE_CONFIRM` forever (the last_message_id rollback means the next retry of this message will re-enter the same crash path).

The non-affirmative re-echo path also prints `$None` to the user: `f"Cierre {hora}: ${cierre_draft.cierre_monto} ¿confirmás?"`.

No test covers this scenario — `test_confirm_saves_cierre` seeds a well-formed draft JSON directly; the corrupt-draft path is untested.

**Fix:** Add a null guard and graceful recovery before calling `save_cierre`:

```python
if is_confirmation(text):
    if cierre_draft.cierre_monto is None:
        # Draft was corrupt or missing — cannot save. Reset to prompt state
        # so the manager can re-enter the amount.
        conv.state = ConvState.AWAITING_CIERRE
        conv.draft_gasto = None
        return (
            "No pude recuperar el monto. "
            "Ingresalo de nuevo (ej: *1500*)."
        )
    await CajaCierreService().save_cierre(
        session, cierre_draft.cierre_monto, conv.sender_phone
    )
    conv.state = ConvState.IDLE
    conv.draft_gasto = None
    return "Cierre registrado. ✓"
else:
    if cierre_draft.cierre_monto is None:
        conv.state = ConvState.AWAITING_CIERRE
        conv.draft_gasto = None
        return "No pude recuperar el monto. Ingresalo de nuevo (ej: *1500*)."
    hora = _derive_hora_cierre()
    return (
        f"Cierre {hora}: ${cierre_draft.cierre_monto} ¿confirmás? "
        "Respondé *sí* o *cancelar*."
    )
```

---

### CR-02: Double LLM call in `_handle_awaiting_cierre` gasto-handoff path — second result silently replaces first, can cause incorrect deflection

**File:** `backend/app/services/conversation.py:612-619`

**Issue:** When a message in `AWAITING_CIERRE` state is classified as a gasto intent (concepto or monto extracted by GPT), the handler calls `_handle_idle` with the original `text`, which re-invokes `self._slot_service.extract(text)` independently:

```python
# Line 612-613: first GPT call — result used only for routing decision
slots = await self._slot_service.extract(text)
if slots.concepto is not None or slots.monto is not None:
    conv.state = ConvState.IDLE
    conv.draft_gasto = None
    # Line 619: second GPT call inside _handle_idle with same text
    return await self._handle_idle(session, conv, DraftGasto(), text)
```

Inside `_handle_idle` (line 406): `slots = await self._slot_service.extract(text)` — a fresh call. Because LLMs are non-deterministic, the second call can return `concepto=None, monto=None` for text that the first call successfully parsed. When that happens, `_handle_idle` returns the `DEFLECTION_REPLY` and the state stays `IDLE` — the manager's gasto intent is silently discarded. The extra API call also doubles latency and cost for this path.

`test_gasto_intent_handoff` uses `assert_awaited()` (at-least-once), so the double call is not caught by the test suite.

**Fix:** Pass the already-extracted `slots` to `_handle_idle` instead of re-extracting. This requires either passing slots as a parameter or inlining the state transition:

```python
slots = await self._slot_service.extract(text)
if slots.concepto is not None or slots.monto is not None:
    conv.state = ConvState.IDLE
    conv.draft_gasto = None
    # Apply the already-extracted slots directly — avoid second LLM call
    draft = patch_draft(DraftGasto(), slots)
    if draft.concepto is None:
        self._save_draft(conv, draft)
        conv.state = ConvState.AWAITING_MONTO
        return "¿Cuál fue el concepto del gasto? (ej: queso en supermercado)"
    else:
        conv.state = ConvState.AWAITING_TICKET
        self._save_draft(conv, draft)
        return (
            f"Entendido, *{draft.concepto}*. "
            "¿Tenés foto del ticket de pago? Enviá la foto o respondé *sin ticket*."
        )
```

---

## Warnings

### WR-01: `phone_number` field in `PromptRequest` has no validation — empty string or oversized value bypasses DB constraints

**File:** `backend/app/routers/prompt.py:97-99`

**Issue:** `PromptRequest.phone_number: str` has no Pydantic validators. An empty string after strip (`clean_phone = ""`) is inserted as the primary key of the `conversations` table (`sender_phone`, PK, `String(30)`). SQLAlchemy permits empty-string PKs; the DB row is created with PK `""` and `_safe_send` is called with `body.phone_number` (possibly also empty), which the WhatsApp provider will reject at runtime (after the DB write is committed). Additionally, `body.phone_number` is sent to the provider without stripping (line 188), while `clean_phone` (stripped) is used for DB writes — if the phone number has surrounding whitespace, the DB key and the provider target diverge.

**Fix:** Add Pydantic field validation to `PromptRequest`:

```python
from pydantic import BaseModel, field_validator

class PromptRequest(BaseModel):
    phone_number: str

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("phone_number must not be empty")
        if len(v) > 30:
            raise ValueError("phone_number exceeds maximum length of 30 characters")
        return v
```

And update `trigger_prompt` to use the already-validated (and stripped) `body.phone_number` for both DB and send:

```python
clean_phone = body.phone_number  # already stripped by validator
# ...
await _safe_send(provider, clean_phone, PROMPT_TEXT, task_log)
```

---

### WR-02: `_handle_awaiting_cierre` re-prompts without clearing state on unknown input — `cancelar` handled upstream but no re-prompt recovery path for cierre flow

**File:** `backend/app/services/conversation.py:623-625`

**Issue:** The re-prompt at line 623-625 returns a message telling the manager to enter efectivo or describe a gasto, but `conv.state` stays at `AWAITING_CIERRE` and `conv.draft_gasto` is unchanged. This is correct design, but there is a subtlety: when the manager sends a bare amount that `parse_ars_amount` parses successfully, `conv.draft_gasto` is assigned a `DraftCierre` JSON. On a subsequent "correction" non-affirmative in `AWAITING_CIERRE_CONFIRM`, the state transitions back to... it does not — the re-echo path stays in `AWAITING_CIERRE_CONFIRM` with the old `draft_gasto` intact. If the manager then says "cancelar", the global cancel path clears `draft_gasto=None` and resets to `IDLE`. This is correct.

The actual bug is subtler: when `_handle_cierre_confirm` is in the re-echo path (non-affirmative), the response echoes the amount from `cierre_draft.cierre_monto`, but there is no path for the manager to correct the amount — they can only say `sí` or `cancelar`. If they type a different amount (e.g., "no, 2000"), the non-affirmative branch re-echoes the original amount rather than updating it. This is a UX-level logic gap: the manager is stuck with the original amount with no correction mechanism short of `cancelar` + restart.

**Fix:** In the non-affirmative arm of `_handle_cierre_confirm`, attempt `parse_ars_amount` on the correction text; if a new amount is found, update `draft_gasto` with the new `DraftCierre` before re-echoing:

```python
else:
    # Check if the manager is providing a corrected amount
    corrected = parse_ars_amount(text)
    if corrected is not None:
        cierre_draft = DraftCierre(cierre_monto=corrected)
        conv.draft_gasto = cierre_draft.model_dump_json()
    hora = _derive_hora_cierre()
    monto_display = cierre_draft.cierre_monto
    return (
        f"Cierre {hora}: ${monto_display} ¿confirmás? "
        "Respondé *sí* o *cancelar*."
    )
```

---

### WR-03: `__import__("re")` at module level is unconventional and bypasses static analysis

**File:** `backend/app/services/conversation.py:105`

**Issue:**

```python
_AFFIRMATIVE_SPLIT_RE = __import__("re").compile(r"[\s,.;!]+")
```

`re` is a standard library module and is always available, so this does not cause a runtime error. However, using `__import__()` at module scope instead of a top-level `import re` is unconventional and prevents static analysis tools (mypy, ruff, pylance) from resolving the `re` reference. It also makes the dependency invisible to `import` scanners and code navigation tools.

**Fix:** Add `import re` to the import block at the top of the file and replace the inline `__import__` call:

```python
import re
# ...
_AFFIRMATIVE_SPLIT_RE = re.compile(r"[\s,.;!]+")
```

---

## Info

### IN-01: `test_active_conversation_skipped` uses `flush()` without `commit()` — seed row visible only within the same session

**File:** `backend/tests/test_prompt_trigger.py:195-198`

**Issue:**

```python
conv = Conversation(sender_phone=TEST_PHONE, state=ConvState.AWAITING_MONTO)
db_session.add(conv)
await db_session.flush()
```

The `flush()` writes the row to the DB within the current transaction but does not commit. The `prompt_client` fixture's `override_get_db` yields the same `db_session`, so the endpoint can see the flushed (but uncommitted) row — this works because both share the same session. However, if the fixture ever changes to yield a different session or connection (e.g., for Postgres integration tests where isolation level matters), the flushed-but-not-committed row would be invisible to the endpoint. Other cierre tests consistently use `await db_session.commit()` before calling the orchestrator. This test should follow the same pattern for consistency and future robustness.

**Fix:**

```python
conv = Conversation(sender_phone=TEST_PHONE, state=ConvState.AWAITING_MONTO)
db_session.add(conv)
await db_session.commit()  # match the pattern in test_conversation_cierre.py
```

---

### IN-02: `test_prompt_text_sent` text extraction fallback silently masks a calling-convention change

**File:** `backend/tests/test_prompt_trigger.py:262-266`

**Issue:**

```python
if call_kwargs.kwargs.get("text"):
    sent_text = call_kwargs.kwargs["text"]
else:
    sent_text = call_kwargs.args[1] if len(call_kwargs.args) > 1 else call_kwargs.args[0]
```

The `else` branch falls back to `call_kwargs.args[0]` when `len(call_kwargs.args) <= 1`. If `send_message` is called with a single positional argument, `args[0]` would be the `to` parameter (the phone number), not the `text`. The test would then assert that the phone number string contains "efectivo" and "otra compra", which would fail with a confusing assertion message rather than a useful error. The condition should be `call_kwargs.args[1]` always when falling through (since send_message signature is `(to, text)`) with an explicit guard that at least 2 positional args are present.

**Fix:**

```python
if call_kwargs.kwargs.get("text"):
    sent_text = call_kwargs.kwargs["text"]
elif len(call_kwargs.args) >= 2:
    sent_text = call_kwargs.args[1]
else:
    pytest.fail(
        f"send_message called with unexpected arguments: "
        f"args={call_kwargs.args!r}, kwargs={call_kwargs.kwargs!r}"
    )
```

---

_Reviewed: 2026-05-30T14:30:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
