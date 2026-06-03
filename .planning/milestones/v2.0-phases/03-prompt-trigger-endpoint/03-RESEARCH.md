# Phase 3: Prompt Trigger Endpoint — Research

**Researched:** 2026-05-30
**Domain:** FastAPI bearer-auth endpoint, FSM extension (AWAITING_CIERRE), zoneinfo ART cutoff, CajaCierre write
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **Request body:** JSON `{"phone_number": "+54..."}` — single recipient per call.
- **Auth:** `Authorization: Bearer <token>` compared to env var `GASTOS_PROMPT_TOKEN`. Missing/invalid → HTTP 401, no message sent.
- **Active-conversation handling:** Non-idle recipient → skip send, return HTTP 200 `{"status":"skipped","reason":"active_conversation"}`.
- **Successful send:** Sets conversation state to `AWAITING_CIERRE`. Returns HTTP 200 `{"status":"sent"}`.
- **In AWAITING_CIERRE:** bare amount → caja-closing path; recognized gasto intent → existing gasto flow.
- **Confirm gate:** Echo "Cierre HH:MM: $X ¿confirmás?" before DB write. Same deterministic affirmative-set gate as gastos. After write → IDLE.
- **`hora_cierre` cutoff:** Before 14:30 ART → "12:00"; 14:30 or later → "17:00". Auto-derived.
- **Duplicates:** Insert a new `CajaCierre` row each time — no unique constraint.
- **Timezone:** `America/Argentina/Buenos_Aires` via `zoneinfo` for `fecha` and cutoff.
- **Mount:** Under the `AGENT_MODE == "gastos"` seam in `main.py`, same as the gastos webhook router.

### Claude's Discretion

- Exact JSON response envelopes and status strings.
- Module placement of the trigger endpoint (new router vs extend `gastos.py`).
- Exact Spanish copy for the prompt message and cierre confirm/echo strings.
- Internal FSM wiring for `AWAITING_CIERRE` (e.g. reuse of `draft_gasto` column vs a dedicated draft field) — provided the confirm gate and disambiguation rules hold.
- Whether the 14:30 cutoff constant is hard-coded or a settings value.

### Deferred Ideas (OUT OF SCOPE)

- Real APScheduler twice-daily scheduler + Twilio Utility template.
- Weekend/holiday suppression of prompts.
- Batch/multi-recipient prompts.
- Upsert/reject semantics for duplicate `(fecha, hora_cierre)` cierres.
- Cross-checking declared vs extracted amounts.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TRIG-01 | Protected endpoint — when called, sends prompt message to a given manager via WhatsApp | Bearer-auth dependency pattern (§ Pattern 1), `_safe_send` reuse, provider factory reuse |
| TRIG-02 | Triggered prompt asks for pending payments, cash-on-hand, and "¿hiciste otra compra hoy?", branches into capture/caja-closing flow | AWAITING_CIERRE state addition to FSM (§ Pattern 3), disambiguation branch (§ Pattern 4) |
| CAJA-01 | Manager reports cash-on-hand (efectivo en caja) for a twice-daily closing | `_handle_awaiting_cierre` method + `parse_ars_amount` reuse (§ Pattern 4) |
| CAJA-02 | Each closing recorded with date and which closing (12:00 / 17:00) | `hora_cierre` cutoff via `zoneinfo` ART (§ Pattern 5), `CajaCierreService.save_cierre` (§ Pattern 6) |
</phase_requirements>

---

## Summary

Phase 3 adds two tightly coupled things: a new **outbound POST endpoint** (`/gastos/prompt`) that fires the conversational prompt on demand, and a new **FSM branch** (`AWAITING_CIERRE`) in the existing `ConversationOrchestrator` that processes the manager's reply. The endpoint sets conversation state; the existing webhook router + orchestrator handles every subsequent turn — no new inbound route is needed.

The endpoint is structurally analogous to the existing `gastos_webhook` handler but inverted: it calls `provider.send_message` (outbound) and directly mutates the conversation row to `AWAITING_CIERRE` instead of dispatching a background task. The FSM extension follows the same dispatch table pattern already used for `ConvState.CONFIRM` — add a new constant, add a `case` arm, add a handler method.

All integration points are already verified to work in tests: the `_make_session_factory` helper, `_safe_send`, provider DI override, and the `pg_insert(...).on_conflict_do_nothing` get-or-create path are reused verbatim. The only net-new infrastructure is bearer-token extraction from `Authorization` header (a standard FastAPI `Security` dependency) and the ART timezone cutoff (one `datetime.now(ZoneInfo(...))` call).

**Primary recommendation:** Implement the trigger endpoint as a second handler in a new `backend/app/routers/prompt.py` (keeps gastos.py focused on webhook transport), mount it under the same `gastos` router prefix in `main.py`, and add `AWAITING_CIERRE` + `AWAITING_CIERRE_CONFIRM` as two new `ConvState` constants covering the cierre flow.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Bearer token auth | API / Backend (FastAPI dependency) | — | Token comparison is server-side; never sent to client or WhatsApp |
| Prompt send | API / Backend (router) | WhatsApp transport (Twilio) | Endpoint owns the send; Twilio is transport only |
| Conversation state mutation (AWAITING_CIERRE) | API / Backend (orchestrator) | Database / Storage | Orchestrator owns FSM; state persisted in `conversations` table |
| Amount disambiguation (bare amount vs gasto intent) | API / Backend (orchestrator) | AI (GPT-4o slot extraction) | GPT extracts intent signal; deterministic code makes the branch decision |
| `hora_cierre` derivation | API / Backend (service layer) | — | Pure server-side time calculation in ART; no user input |
| CajaCierre write | Database / Storage | API / Backend | Postgres row insert; orchestrator calls service, which owns the SQL |
| Cierre confirm gate | API / Backend (orchestrator) | — | Deterministic affirmative-set match; GPT never invoked at write boundary |

---

## Standard Stack

### Core (all already in pyproject.toml — no new packages)

| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| FastAPI | 0.136.1 | HTTP framework — `Security`, `HTTPException`, `Depends` | Already in use; `Security` is a typed alias of `Depends` for auth dependencies [VERIFIED: pyproject.toml] |
| Pydantic v2 | 2.13.4 | Request body model (`PromptRequest`) and response model | Already in use for all body parsing [VERIFIED: pyproject.toml] |
| SQLAlchemy 2.0 async | 2.0.49 | Conversation row read/write inside the trigger endpoint | Already in use; same `pg_insert + on_conflict_do_nothing + FOR NO KEY UPDATE` pattern [VERIFIED: pyproject.toml] |
| `zoneinfo` (stdlib) | Python 3.12 built-in | ART datetime for `fecha` + `hora_cierre` cutoff | Part of CPython 3.9+; no install needed [VERIFIED: stdlib] |
| `secrets.compare_digest` (stdlib) | Python 3.12 built-in | Constant-time bearer token comparison | Required to prevent timing oracle on token comparison (T-02-W8 lineage) [VERIFIED: stdlib] |

### No New Dependencies Required

The `python:3.12-slim` Docker base image includes the system timezone database (`/usr/share/zoneinfo`). Verified by running `python:3.12-slim` in Docker:

```
docker run --rm python:3.12-slim python3 -c \
  "import zoneinfo; zoneinfo.ZoneInfo('America/Argentina/Buenos_Aires'); print('OK')"
# Output: OK
```

**`tzdata` package is NOT required** for `python:3.12-slim`. The pending todo in STATE.md (`Confirm tzdata package required on Alpine containers`) is resolved: `python:3.12-slim` (Debian-based) ships tzdata; `python:3.12-alpine` does not. Since the Dockerfile uses `python:3.12-slim`, no change needed. [VERIFIED: Dockerfile + live Docker run]

### Installation

No new `pip install` commands. No new entries in `pyproject.toml`.

---

## Package Legitimacy Audit

No new external packages are introduced in this phase. All libraries used are either Python stdlib (`zoneinfo`, `secrets`) or already pinned in `pyproject.toml`. This section is satisfied by absence.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

---

## Architecture Patterns

### System Architecture Diagram

```
Caller (demo driver / scheduler)
        |
        | POST /gastos/prompt  {"phone_number": "+54..."}
        | Authorization: Bearer <token>
        v
[FastAPI: prompt router]
  1. verify_token dependency → 401 if invalid (no send)
  2. check Conversation row: non-idle? → 200 skipped
  3. ensure-row exists (pg_insert ON CONFLICT DO NOTHING)
  4. SELECT ... FOR NO KEY UPDATE
  5. set conv.state = AWAITING_CIERRE
  6. commit
  7. _safe_send(provider, phone, PROMPT_TEXT)
  8. return 200 {"status":"sent"}
        |
        | (async, WhatsApp delivery)
        v
Manager WhatsApp receives prompt message

Manager replies (any turn)
        |
        | POST /webhook  (existing Twilio webhook — unchanged)
        v
[gastos_webhook handler] (unchanged)
        |
        v
[process_gasto_message background task]
        |
        v
[ConversationOrchestrator.handle_message]
  match conv.state:
    AWAITING_CIERRE:
      bare amount → parse_ars_amount → store in draft → AWAITING_CIERRE_CONFIRM
      gasto intent → hand off to existing _handle_idle gasto path
      neither → re-prompt
    AWAITING_CIERRE_CONFIRM:
      is_confirmation() → CajaCierreService.save_cierre → IDLE
      is_cancel() → IDLE  (handled upstream)
      else → re-echo confirm (correction re-prompt)
        |
        v
[CajaCierreService.save_cierre]
  fecha = date.today() in ART tz
  hora_cierre = "12:00" if now_art.time() < 14:30 else "17:00"
  INSERT INTO caja_cierres (...)  -- new row, no UNIQUE constraint
  session.flush()  -- caller commits
```

### Recommended Project Structure

```
backend/app/
├── routers/
│   ├── gastos.py        # existing webhook handler (unchanged)
│   └── prompt.py        # NEW: POST /gastos/prompt trigger endpoint
├── services/
│   ├── conversation.py  # extend: AWAITING_CIERRE + AWAITING_CIERRE_CONFIRM states
│   └── cierre.py        # NEW: CajaCierreService.save_cierre (mirrors gasto.py)
├── config.py            # add gastos_prompt_token: str = ""
└── main.py              # mount prompt router under gastos seam
```

---

### Pattern 1: Bearer Token FastAPI Dependency (TRIG-01 auth)

**What:** A `Security` dependency (typed alias of `Depends`) extracts the `Authorization` header, parses the `Bearer <token>` scheme, and compares constant-time against `settings.gastos_prompt_token`. Returns 401 on any mismatch.

**When to use:** Every handler function that must be protected by the token. Pass as `_: None = Security(verify_token)` to make the dependency fire without injecting a value.

**Critical detail:** Use `secrets.compare_digest(a, b)` not `==` for the comparison. `==` returns early on the first mismatched byte — a timing oracle. `compare_digest` is constant-time regardless of where the mismatch occurs. Both arguments must be `str` (not `bytes`) or both `bytes`; mixing types raises `TypeError`. [VERIFIED: Python 3.12 stdlib docs]

**Critical detail:** If `settings.gastos_prompt_token` is the empty string `""` (the default before the env var is set), `compare_digest("", "")` returns `True`, which would make the endpoint open. Guard against this: if the configured token is empty, always return 401. This prevents misconfiguration from silently disabling auth.

```python
# Source: Python stdlib docs — secrets.compare_digest
# Source: FastAPI docs — Security dependency
import secrets
from fastapi import Security, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import get_settings, Settings

_bearer_scheme = HTTPBearer(auto_error=False)

def verify_token(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> None:
    """Constant-time bearer token check. Raises HTTP 401 on any failure."""
    configured = settings.gastos_prompt_token
    if not configured:
        # Token not configured → deny all (fail-closed)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    if not secrets.compare_digest(credentials.credentials, configured):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
```

**`HTTPBearer(auto_error=False)`** is required so that a missing `Authorization` header yields `credentials=None` instead of raising a 403 automatically. This lets the dependency return the correct 401 with the project's error schema.

**Settings addition (`config.py`):**

```python
# Add to Settings class
gastos_prompt_token: str = ""  # Required at runtime; empty = auth disabled (deny all)
```

The field uses an empty-string default (not `None` and not a required field) so the existing test suite — which does not set this env var in `conftest.py` — does not break. The token is never logged.

---

### Pattern 2: Prompt Endpoint — Conversation State Write (Race-Safe)

**What:** The trigger endpoint must set `conv.state = ConvState.AWAITING_CIERRE` using the **same** per-sender row lock (`SELECT ... FOR NO KEY UPDATE`) the orchestrator uses. This prevents a race where an inbound webhook and the trigger fire simultaneously.

**The race scenario:**
1. Trigger endpoint reads `conv.state == "idle"` → decides to send.
2. Inbound webhook fires for the same sender (concurrent).
3. Both write different states — one clobbers the other.

**Prevention:** The trigger endpoint must acquire the `FOR NO KEY UPDATE` row lock before reading `conv.state`. The lock serializes concurrent access between the endpoint and the orchestrator's `handle_message`. Since both run in the same Postgres process and use `asyncpg` (which multiplexes over a single connection pool), they will serialize at the DB level.

**Ordering inside the trigger endpoint (mirrors orchestrator's Step 1-4):**

```python
# Inside an async with session.begin() block:

# Step 1: ensure row exists (race-safe)
ensure_stmt = (
    pg_insert(Conversation)
    .values(sender_phone=clean_phone, state=ConvState.IDLE)
    .on_conflict_do_nothing(index_elements=["sender_phone"])
)
await session.execute(ensure_stmt)

# Step 2: lock row
result = await session.execute(
    select(Conversation)
    .where(Conversation.sender_phone == clean_phone)
    .with_for_update(key_share=True)  # FOR NO KEY UPDATE
)
conv = result.scalar_one()

# Step 3: check active state (BEFORE writing)
if conv.state != ConvState.IDLE:
    # Return skipped — do NOT send, do NOT change state
    return {"status": "skipped", "reason": "active_conversation"}

# Step 4: set state
conv.state = ConvState.AWAITING_CIERRE
# transaction commits when async with session.begin() exits
```

**After commit, outside the transaction:** call `_safe_send(provider, to, PROMPT_TEXT, log)`.

**Important:** The 200 `{"status":"skipped"}` return exits the `async with session.begin()` block normally (no exception), so the transaction commits with no mutations — this is correct behavior. The lock is released on commit either way.

**The endpoint is synchronous from the caller's perspective** — unlike the webhook which uses `asyncio.create_task` for fast-200, the trigger can `await` the send because the caller is a human/scheduler, not Twilio (which requires sub-5-second responses). No `create_task` needed here.

---

### Pattern 3: Extending ConvState and the _dispatch Match Block

**What:** Add two new state constants and two new `case` arms. The CONTEXT.md decision calls for a single `AWAITING_CIERRE` state but the confirm gate requires a second state to hold the pending cierre amount before the user affirms. Using two states mirrors the existing `AWAITING_TICKET → CONFIRM` pattern exactly.

**New constants (add to `ConvState` class):**

```python
class ConvState:
    IDLE = "idle"
    AWAITING_MONTO = "awaiting_monto"
    AWAITING_TICKET = "awaiting_ticket"
    CONFIRM = "confirm"
    AWAITING_CIERRE = "awaiting_cierre"          # NEW: bare amount → AWAITING_CIERRE_CONFIRM
    AWAITING_CIERRE_CONFIRM = "awaiting_cierre_confirm"  # NEW: holds amount pending confirmation
```

Both strings fit within `Conversation.state String(30)` (longest is 24 chars). No migration needed.

**_dispatch match block extension:**

```python
case ConvState.AWAITING_CIERRE:
    reply = await self._handle_awaiting_cierre(session, conv, text)

case ConvState.AWAITING_CIERRE_CONFIRM:
    reply = await self._handle_cierre_confirm(session, conv, text)
```

**Draft storage for cierre amount:** Store the pending `efectivo_en_caja` amount in `conv.draft_gasto` as a simple JSON string (e.g., `'{"cierre_monto": "1500.00"}'`). This avoids any schema change. The `_load_draft` method catches JSON/validation errors and resets — the same safety net applies. Alternatively, use a dedicated `DraftCierre` Pydantic model with `cierre_monto: Optional[Decimal]`. Using a `DraftCierre` model is cleaner and prevents future confusion between gasto and cierre drafts.

**Recommendation:** Use a small `DraftCierre(BaseModel)` with `cierre_monto: Optional[Decimal] = None`, serialized to `draft_gasto` JSON (same column). The `_load_draft` equivalent for cierre uses `DraftCierre.model_validate_json`. Since state is either in a gasto path or a cierre path, never both simultaneously, column reuse is safe.

---

### Pattern 4: AWAITING_CIERRE Disambiguation Branch

**What:** When `conv.state == AWAITING_CIERRE` and a reply arrives, the orchestrator must decide: bare cash amount → cierre path; recognized gasto intent → gasto path; neither → re-prompt.

**Decision logic (deterministic, no new GPT call added):**

```python
async def _handle_awaiting_cierre(
    self,
    session: AsyncSession,
    conv: Conversation,
    text: str,
) -> str:
    # 1. Try parse_ars_amount first (fast, no API call)
    monto = parse_ars_amount(text)
    if monto is not None:
        # Bare amount → cierre path
        # Store in draft, advance to AWAITING_CIERRE_CONFIRM
        draft = DraftCierre(cierre_monto=monto)
        conv.draft_gasto = draft.model_dump_json()
        conv.state = ConvState.AWAITING_CIERRE_CONFIRM
        hora = _derive_hora_cierre()
        return f"Cierre {hora}: ${monto} ¿confirmás? Respondé *sí* o *cancelar*."

    # 2. Try slot extraction (GPT) to detect gasto intent
    slots = await self._slot_service.extract(text)
    if slots.concepto is not None or slots.monto is not None:
        # Recognized gasto intent → hand off to gasto flow from IDLE
        # Reset state to IDLE first, then handle as if idle (reuses _handle_idle)
        conv.state = ConvState.IDLE
        conv.draft_gasto = None
        return await self._handle_idle(session, conv, DraftGasto(), text)

    # 3. Neither → re-prompt
    return (
        "No entendí. Indicá el efectivo en caja (ej: *1500*) "
        "o describí un gasto para registrarlo."
    )
```

**Important ordering:** `parse_ars_amount` first (no API cost). GPT only on parse failure. This preserves the "bare amount = cierre" semantics even for amounts like "1.500,50" that look like gastos.

**Gasto handoff detail:** When handing off to the gasto path, the state is reset to `IDLE` and `_handle_idle` is called directly. This means the orchestrator's `_dispatch` re-enters the idle handler in the same turn. The `last_message_id` is already set (idempotency guard fired before `_dispatch`). The gasto flow proceeds normally — next inbound message hits the new gasto state.

---

### Pattern 5: ART Timezone Cutoff for hora_cierre

**What:** Derive `hora_cierre` and `fecha` from current server time in `America/Argentina/Buenos_Aires`.

**Verified:** `zoneinfo.ZoneInfo('America/Argentina/Buenos_Aires')` works in `python:3.12-slim` without installing `tzdata`. [VERIFIED: live Docker run]

```python
# Source: Python 3.12 stdlib docs — zoneinfo
from datetime import datetime, time
from zoneinfo import ZoneInfo

_ART = ZoneInfo("America/Argentina/Buenos_Aires")
_CUTOFF = time(14, 30)  # 14:30 ART

def _derive_hora_cierre() -> str:
    """Return '12:00' if before 14:30 ART, else '17:00'."""
    now_art = datetime.now(_ART)
    return "12:00" if now_art.time() < _CUTOFF else "17:00"

def _today_art():
    """Return date.today() in ART (not UTC)."""
    return datetime.now(_ART).date()
```

**Argentina does not observe DST** — `America/Argentina/Buenos_Aires` is a fixed UTC-3 offset. The `zoneinfo` lookup is still the right approach (rather than `timedelta(hours=-3)`) because it is semantically correct and future-proof. [ASSUMED — Argentina DST policy. Stable since 2008 but not independently re-verified in this session.]

---

### Pattern 6: CajaCierreService (mirrors GastoService)

**What:** A stateless service class with a single `save_cierre(session, monto, sender_phone)` method. The caller (orchestrator) owns the transaction; `save_cierre` calls `session.flush()` to populate the UUID, then returns the ORM object.

```python
# backend/app/services/cierre.py
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CajaCierre

_ART = ZoneInfo("America/Argentina/Buenos_Aires")
_CUTOFF_TIME = __import__("datetime").time(14, 30)

log = structlog.get_logger()


class CajaCierreService:
    async def save_cierre(
        self,
        session: AsyncSession,
        efectivo_en_caja: Decimal,
        sender_phone: str,
    ) -> CajaCierre:
        now_art = datetime.now(_ART)
        hora_cierre = "12:00" if now_art.time() < _CUTOFF_TIME else "17:00"
        fecha = now_art.date()

        cierre = CajaCierre(
            fecha=fecha,
            hora_cierre=hora_cierre,
            efectivo_en_caja=efectivo_en_caja,
            sender_phone=sender_phone.removeprefix("whatsapp:").strip(),
        )
        session.add(cierre)
        await session.flush()
        log.info("cierre.saved", id=str(cierre.id), hora_cierre=hora_cierre, monto=str(efectivo_en_caja))
        return cierre
```

**Decimal precision:** `CajaCierre.efectivo_en_caja` is `Numeric(14, 2)`. The amount arrives as the result of `parse_ars_amount(text)` which returns a `Decimal`. Store it directly — no float conversion needed. Never do `Decimal(float(amount))` as this introduces binary floating-point error. [VERIFIED: models.py line 178 + GastoService pattern in gasto.py]

---

### Pattern 7: main.py Mount Point

The trigger endpoint must mount under the same `AGENT_MODE == "gastos"` seam. Two clean options:

**Option A (recommended): separate router, same mount block**

```python
elif settings.agent_mode == "gastos":
    from app.routers.gastos import router as gastos_router
    from app.routers.prompt import router as prompt_router

    app.include_router(gastos_router, tags=["gastos"])
    app.include_router(prompt_router, tags=["gastos"])
```

Where `prompt.py` defines `router = APIRouter()` and registers `@router.post("/gastos/prompt")`.

**Option B: extend gastos.py with a second handler.** Simpler but mixes webhook-transport concerns with outbound-trigger concerns in one file. Option A is cleaner per the single-responsibility pattern established in the codebase.

---

### Anti-Patterns to Avoid

- **`==` for token comparison:** Use `secrets.compare_digest`. The `==` operator short-circuits on the first mismatched byte, leaking timing information. [T-02-W8 lineage]
- **Setting `conv.state` without acquiring the row lock first:** The orchestrator will overwrite state if a webhook fires concurrently. Always lock before read-and-set.
- **Calling `_safe_send` inside the `async with session.begin()` block:** The send must happen OUTSIDE the transaction. A send failure inside the block would roll back the state mutation — the row would remain IDLE, the prompt would never be re-sent (the caller got 200), and the manager would not receive the message and the DB would be inconsistent. Pitfall C from the orchestrator module docstring applies here too.
- **`float()` for efectivo_en_caja:** `parse_ars_amount` returns `Decimal`. Keep it as `Decimal` all the way to the `Numeric(14,2)` column.
- **Logging the bearer token in error paths:** The token must never appear in structlog output. Log `"auth.invalid_token"` with no token value — same as T-02-W8.
- **Empty-string token allows all:** If `GASTOS_PROMPT_TOKEN` is not set (empty string default), `compare_digest("", presented_token)` returns `False` for any non-empty presented token, which is safe — but `compare_digest("", "")` returns `True`, which would allow a request with `Authorization: Bearer ` (empty credential). Guard: fail-closed when `configured == ""`.
- **Mutating `conv.draft_gasto` in-place:** Always reassign with `conv.draft_gasto = new_json_string`. The `onupdate=func.now()` hook on `updated_at` fires only on column reassignment, not on in-place dict/string mutation of the ORM attribute. (Pitfall E, documented in conversation.py module docstring.)
- **State transitions from AWAITING_CIERRE bypassing the cancel check:** The global `is_cancel(text)` check in `handle_message` runs BEFORE `_dispatch`. It already resets state to IDLE on `"cancelar"` regardless of state. No special cancel handling needed in `_handle_awaiting_cierre`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Constant-time string comparison | Custom byte-by-byte loop | `secrets.compare_digest` | stdlib; timing-safe; handles str and bytes |
| Bearer token extraction from header | Manual `request.headers.get("Authorization").split()` | `HTTPBearer` scheme from `fastapi.security` | Handles missing header, wrong scheme, malformed value; returns typed `HTTPAuthorizationCredentials` |
| ART time | Manual UTC-3 offset via `timedelta` | `zoneinfo.ZoneInfo("America/Argentina/Buenos_Aires")` | Semantically correct; future-proof against any hypothetical DST policy changes |
| Decimal from user text | `float(text)` | `parse_ars_amount(text)` | Already handles Argentine separators ("1.500,50"); regex-validated; returns `Decimal` directly |
| Per-sender row serialization | Custom mutex / asyncio.Lock | `SELECT ... FOR NO KEY UPDATE` via `with_for_update(key_share=True)` | Already proven in Phase 1/2; serializes at DB level across workers |

---

## Common Pitfalls

### Pitfall 1: Send-Before-Commit Ordering
**What goes wrong:** `_safe_send` is called inside the `async with session.begin()` block. The send succeeds, the DB write then fails and rolls back. The manager received the prompt but state is still IDLE. Next trigger call re-sends a duplicate prompt.
**Why it happens:** Putting the send inside the transaction is intuitive but wrong.
**How to avoid:** Call `_safe_send` strictly AFTER the `async with session.begin()` block exits (same as orchestrator Pitfall C).
**Warning signs:** The response returns before the send completes (should not happen — trigger awaits the send unlike webhook).

### Pitfall 2: Missing Row Lock in the Trigger Endpoint
**What goes wrong:** Trigger endpoint reads `conv.state == "idle"` and then sets AWAITING_CIERRE without holding the lock. Concurrent inbound webhook also reads the same state and runs the gasto flow. Both commit — state is AWAITING_CIERRE but the orchestrator ran the IDLE handler and already set a new state (e.g., AWAITING_TICKET).
**Why it happens:** The trigger is a separate code path from the orchestrator and the lock is easy to forget.
**How to avoid:** Always use the same `pg_insert ON CONFLICT DO NOTHING` + `SELECT FOR NO KEY UPDATE` sequence before any read-then-write on the conversation row.
**Warning signs:** Tests pass in isolation but fail under concurrent load; race revealed only by `pg_integration` test.

### Pitfall 3: AWAITING_CIERRE_CONFIRM Not Handling "cancelar"
**What goes wrong:** Manager replies "cancelar" while in AWAITING_CIERRE_CONFIRM. Orchestrator's global cancel check fires first (before `_dispatch`) — this is actually the correct behavior. The cancel check at Step 6 of `handle_message` already handles this.
**Why it happens:** Developer adds a duplicate cancel check inside `_handle_cierre_confirm`, creating two code paths.
**How to avoid:** Trust the existing global cancel handler. Do NOT add a special-case cancel check inside either cierre handler method.
**Warning signs:** Tests for cancel at AWAITING_CIERRE state pass, but cancel at AWAITING_CIERRE_CONFIRM doesn't clear the draft (it does — the global handler sets `conv.draft_gasto = None`).

### Pitfall 4: Gasto Intent Handoff Leaves Orphaned Cierre Draft
**What goes wrong:** Manager is in AWAITING_CIERRE and replies with a gasto intent. The handler calls `_handle_idle` but forgets to reset `conv.draft_gasto = None` first. The old cierre draft (if any) is still in `draft_gasto`; when the gasto flow tries to load it with `DraftGasto.model_validate_json`, it gets a `ValidationError` from a `DraftCierre` JSON blob.
**Why it happens:** `_load_draft` is called at the top of `_dispatch` before the branch, and the cierre handler manually sets a `DraftCierre` blob before calling `_handle_idle`.
**How to avoid:** When handing off to the gasto path from AWAITING_CIERRE, explicitly set `conv.draft_gasto = None` before calling `_handle_idle`. `_load_draft` already catches `ValidationError` and returns `DraftGasto()`, so this is a double-safety — but the explicit reset is cleaner.
**Warning signs:** Gasto handoff works on first prompt but fails on second if a partial cierre draft was stored.

### Pitfall 5: GASTOS_PROMPT_TOKEN Empty-String Allows Blank Bearer
**What goes wrong:** `secrets.compare_digest("", "")` returns `True`. A request with `Authorization: Bearer ` (empty string credential) passes auth when the token is not configured.
**Why it happens:** `HTTPBearer` passes the empty string as `credentials.credentials` for a blank `Bearer ` header.
**How to avoid:** Fail-closed when `settings.gastos_prompt_token == ""` — raise 401 before the comparison.
**Warning signs:** CI tests that don't set the env var accidentally pass the auth check.

### Pitfall 6: conftest.py Does Not Set GASTOS_PROMPT_TOKEN
**What goes wrong:** The new endpoint test fixture does not set `GASTOS_PROMPT_TOKEN` in env_setup. Tests that call the endpoint without setting the token get 401 (expected if testing the 401 path), but tests that try to exercise the happy path also get 401 unexpectedly because the configured token is `""`.
**Why it happens:** Adding a new required env var to `Settings` without adding it to the session-scoped `env_setup` fixture.
**How to avoid:** Add `mp.setenv("GASTOS_PROMPT_TOKEN", "test-prompt-token")` to the existing `env_setup` fixture in `conftest.py`. Tests that check 401 behavior use a deliberately wrong token.

### Pitfall 7: Twilio 24-Hour Customer Service Window
**What goes wrong:** The trigger fires when the manager has not messaged in >24h. Twilio rejects the outbound free-form message with a 63016/63038 error ("Template not approved for this session").
**Why it happens:** WhatsApp's customer care window closes 24h after the last message from the user. Free-form messages can only be sent within this window; outside it requires a pre-approved template.
**How to avoid:** For the demo, the CONTEXT.md explicitly assumes the window is open ("within a live demo the recipient has just messaged the bot"). Document this assumption in the endpoint's docstring. `_safe_send` will log the error without crashing.
**Warning signs:** `provider.send_message` raises an exception that `_safe_send` catches and logs as `gastos.reply_failed`; the endpoint still returns 200 `{"status":"sent"}` because the DB write committed. This is the accepted at-most-once send risk.

---

## Code Examples

### Verified Patterns from Existing Codebase

#### Bearer dependency usage in a FastAPI handler

```python
# Source: fastapi docs + existing get_whatsapp_provider pattern (gastos.py:85)
@router.post("/gastos/prompt", response_model=PromptResponse)
async def trigger_prompt(
    body: PromptRequest,
    _: None = Security(verify_token),          # auth gate fires before handler body
    db: AsyncSession = Depends(get_db),
    provider: WhatsAppProvider = Depends(get_whatsapp_provider),
    settings: Settings = Depends(get_settings),
) -> PromptResponse:
    ...
```

#### Reusing the existing _make_session_local_mock in new tests

```python
# Source: test_gastos_webhook.py lines 275-286 — verbatim reuse
from contextlib import asynccontextmanager

@asynccontextmanager
async def _session_ctx():
    yield db_session

def _session_factory():
    return _session_ctx()
```

#### get_async_session_local usage for the trigger endpoint

The trigger endpoint is a route handler (has `Depends`), so it CAN use `get_db` directly (unlike background tasks which cannot). Use `db: AsyncSession = Depends(get_db)` — same as the webhook handler's allowlist check. Do NOT construct the session factory manually inside the handler.

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| `request.headers.get("Authorization")` manual parse | `HTTPBearer` security scheme + `HTTPAuthorizationCredentials` | Typed, handles malformed headers cleanly |
| Token comparison with `==` | `secrets.compare_digest` | Timing-safe |
| `pytz` for timezone | `zoneinfo` (stdlib 3.9+) | No extra dependency; `pytz` is EOL-adjacent |

**Deprecated/outdated:**
- `pytz`: Do not use. `zoneinfo` is the stdlib successor since Python 3.9. The existing codebase has zero `pytz` references.
- `datetime.utcnow()`: Do not use (deprecated in 3.12). Use `datetime.now(tz=timezone.utc)` or `datetime.now(ZoneInfo(...))`.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Argentina does not observe DST; ART is a fixed UTC-3 offset | Pattern 5 | If DST re-introduced, `hora_cierre` cutoff would be wrong by 1h during transition; use `zoneinfo` (not a fixed offset) mitigates this |
| A2 | `_handle_idle` can be called directly from `_handle_awaiting_cierre` with a fresh `DraftGasto()` and the result is correct | Pattern 4 | If `_handle_idle` has side effects that assume `conv.state == IDLE` was the prior state, it could behave unexpectedly; review during implementation |

---

## Open Questions (RESOLVED)

1. **Draft column reuse vs separate column for cierre amount**
   - What we know: `Conversation.draft_gasto TEXT` stores arbitrary JSON; both gasto and cierre states use it.
   - What's unclear: If a manager somehow transitions mid-flow (shouldn't happen but edge case), mixing `DraftGasto` and `DraftCierre` JSON blobs in the same column creates a parse-error fallback path.
   - Recommendation: Use the existing column with a `DraftCierre` Pydantic model. The `_load_draft` safety net (catches `ValidationError`, returns fresh draft) provides adequate protection. A separate column is out of scope — it would require a migration.

2. **AWAITING_CIERRE_CONFIRM or reuse CONFIRM**
   - What we know: CONTEXT.md says "confirm gate" without specifying whether to reuse the `CONFIRM` state or add a new one.
   - What's unclear: Reusing `CONFIRM` would require the `_handle_confirm` method to distinguish gasto vs cierre context (from the draft JSON content).
   - Recommendation: Two new states (`AWAITING_CIERRE` + `AWAITING_CIERRE_CONFIRM`). Cleaner dispatch, no draft-type inspection required. `String(30)` comfortably fits both.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `zoneinfo` stdlib | ART cutoff (Pattern 5) | ✓ | Python 3.12 stdlib | — |
| `secrets` stdlib | Token comparison (Pattern 1) | ✓ | Python 3.12 stdlib | — |
| `python:3.12-slim` tzdata | `zoneinfo.ZoneInfo('America/Argentina/...')` | ✓ | system tzdata | Would need `tzdata` PyPI package if Alpine |
| Twilio 24h CS window | `provider.send_message` in demo | Assumed open | — | `_safe_send` logs error without crash |

**Missing dependencies with no fallback:** none.

**Missing dependencies with fallback:** Twilio window (demo assumption; `_safe_send` handles gracefully).

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (`asyncio_mode = "auto"`) |
| Config file | `backend/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `cd backend && python -m pytest tests/test_prompt_trigger.py tests/test_conversation_cierre.py -x -q` |
| Full suite command | `cd backend && python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TRIG-01 (auth) | Valid token → 200 + send | unit | `pytest tests/test_prompt_trigger.py::test_valid_token_sends -x` | ❌ Wave 0 |
| TRIG-01 (auth) | Missing token → 401, no send | unit | `pytest tests/test_prompt_trigger.py::test_missing_token_401 -x` | ❌ Wave 0 |
| TRIG-01 (auth) | Wrong token → 401, no send | unit | `pytest tests/test_prompt_trigger.py::test_wrong_token_401 -x` | ❌ Wave 0 |
| TRIG-01 (skip) | Non-idle recipient → 200 skipped | unit | `pytest tests/test_prompt_trigger.py::test_active_conversation_skipped -x` | ❌ Wave 0 |
| TRIG-01 (state) | Successful send sets AWAITING_CIERRE | unit | `pytest tests/test_prompt_trigger.py::test_state_set_to_awaiting_cierre -x` | ❌ Wave 0 |
| TRIG-02 | Prompt message reaches provider.send_message | unit | `pytest tests/test_prompt_trigger.py::test_prompt_text_sent -x` | ❌ Wave 0 |
| CAJA-01 | Bare amount in AWAITING_CIERRE → AWAITING_CIERRE_CONFIRM | unit | `pytest tests/test_conversation_cierre.py::test_bare_amount_advances_to_confirm -x` | ❌ Wave 0 |
| CAJA-01 | Gasto intent in AWAITING_CIERRE → gasto flow | unit | `pytest tests/test_conversation_cierre.py::test_gasto_intent_handoff -x` | ❌ Wave 0 |
| CAJA-01 | Confirm in AWAITING_CIERRE_CONFIRM → CajaCierre row written | unit | `pytest tests/test_conversation_cierre.py::test_confirm_saves_cierre -x` | ❌ Wave 0 |
| CAJA-01 | Confirm gate: exact token only (CONV-05 analog) | unit | `pytest tests/test_conversation_cierre.py::test_confirm_requires_exact_token -x` | ❌ Wave 0 |
| CAJA-02 | hora_cierre = "12:00" before 14:30 ART | unit | `pytest tests/test_conversation_cierre.py::test_hora_cierre_morning -x` | ❌ Wave 0 |
| CAJA-02 | hora_cierre = "17:00" at/after 14:30 ART | unit | `pytest tests/test_conversation_cierre.py::test_hora_cierre_afternoon -x` | ❌ Wave 0 |
| CAJA-02 | fecha is today() in ART, not UTC | unit | `pytest tests/test_conversation_cierre.py::test_fecha_art_not_utc -x` | ❌ Wave 0 |
| — | Token comparison is constant-time (fail-closed on empty token) | unit | `pytest tests/test_prompt_trigger.py::test_empty_configured_token_denies -x` | ❌ Wave 0 |
| — | Duplicate CajaCierre inserts (no unique constraint) | unit | `pytest tests/test_conversation_cierre.py::test_duplicate_cierres_allowed -x` | ❌ Wave 0 |
| — | Row lock issued in trigger endpoint | unit | `pytest tests/test_prompt_trigger.py::test_row_lock_issued -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `cd backend && python -m pytest tests/test_prompt_trigger.py tests/test_conversation_cierre.py -x -q`
- **Per wave merge:** `cd backend && python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

All new test files must be created before implementation (RED-GREEN pattern established in phases 1 and 2):

- [ ] `backend/tests/test_prompt_trigger.py` — covers TRIG-01, TRIG-02, auth edge cases, row lock
- [ ] `backend/tests/test_conversation_cierre.py` — covers CAJA-01, CAJA-02, FSM transitions, duplicate insert
- [ ] `backend/tests/conftest.py` — add `mp.setenv("GASTOS_PROMPT_TOKEN", "test-prompt-token")` to the existing `env_setup` session fixture
- [ ] `backend/app/services/cierre.py` — skeleton only (class with `pass` methods) so test imports don't fail at collection time

**Existing test infrastructure is sufficient** — `db_session`, `async_engine`, `_make_session_factory`, `env_setup`, `_make_session_local_mock`, `make_mock_provider` are all reused verbatim.

**hora_cierre test strategy:** Use `unittest.mock.patch("app.services.cierre.datetime")` (or the equivalent module-level `datetime.now` patch) to freeze time at a known ART value. Pattern: `patch("app.services.cierre.datetime") as mock_dt; mock_dt.now.return_value = datetime(2026, 5, 30, 11, 0, tzinfo=_ART)`.

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Bearer token via `HTTPBearer` + `secrets.compare_digest` |
| V3 Session Management | no | Endpoint is stateless; session state is in WhatsApp/DB, not HTTP |
| V4 Access Control | yes | Token-gated endpoint; 401 before any message send |
| V5 Input Validation | yes | Pydantic `PromptRequest(phone_number: str)` body model; phone format validated |
| V6 Cryptography | no | Token comparison only (no encryption); secrets.compare_digest is timing-safe |

### Known Threat Patterns for this Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Timing attack on token comparison | Information Disclosure | `secrets.compare_digest` — constant time regardless of prefix match length |
| Token logged in error path | Information Disclosure | Never log the token value; log `"auth.invalid_token"` with no credential |
| Empty configured token allows blank bearer | Elevation of Privilege | Fail-closed: if `settings.gastos_prompt_token == ""` → always 401 |
| Active conversation clobber via concurrent trigger | Tampering | `SELECT FOR NO KEY UPDATE` before read-then-set |
| Prompt sent outside Twilio 24h window | Denial (send failure) | `_safe_send` catches and logs; endpoint returns 200 (accepted risk for demo) |
| Phone number injection in `PromptRequest.phone_number` | Tampering | Pydantic validates the field is a non-empty string; pass directly to `provider.send_message` without shell interpretation |

---

## Sources

### Primary (HIGH confidence)

- Existing codebase: `backend/app/routers/gastos.py` — reuse patterns for `get_whatsapp_provider`, `_safe_send`, provider DI override
- Existing codebase: `backend/app/services/conversation.py` — FSM structure, `ConvState`, `_dispatch` match block, `handle_message` entry sequence
- Existing codebase: `backend/app/db/models.py` — `CajaCierre` model (line 166), `Conversation.state String(30)` (line 128)
- Existing codebase: `backend/app/config.py` — `Settings` pydantic-settings pattern for adding env vars
- Existing codebase: `backend/tests/conftest.py` — `env_setup`, `db_session`, `async_engine` fixture patterns
- Existing codebase: `backend/tests/test_conversation.py` — `_make_session_factory`, lock spy pattern, state machine test structure
- Existing codebase: `backend/tests/test_gastos_webhook.py` — `_make_session_local_mock`, `make_mock_provider`, `dependency_overrides` pattern
- Python 3.12 stdlib: `zoneinfo` — `ZoneInfo('America/Argentina/Buenos_Aires')` confirmed working in `python:3.12-slim` (live Docker run)
- Python 3.12 stdlib: `secrets.compare_digest` — constant-time string comparison
- `backend/Dockerfile`: `FROM python:3.12-slim` — Debian-based; system tzdata available; `tzdata` PyPI package not required

### Secondary (MEDIUM confidence)

- CONTEXT.md decisions — authoritative, gathered 2026-05-30 via smart discuss
- REQUIREMENTS.md — TRIG-01, TRIG-02, CAJA-01, CAJA-02 requirement text

### Tertiary (LOW confidence)

- A1: Argentina no-DST claim — stable since 2008 but not re-verified against a live source in this session

---

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — all dependencies already in pyproject.toml; no new packages
- Architecture: HIGH — direct codebase read; all patterns are exact analogs of existing code
- Pitfalls: HIGH — derived from existing code comments (Pitfall C, Pitfall E, T-02-W8), plus concurrency analysis of the new endpoint's interaction with the existing orchestrator
- tzdata: HIGH — verified by live Docker run
- ART DST assumption: LOW — long-stable policy but not independently verified in this session

**Research date:** 2026-05-30
**Valid until:** 2026-06-30 (stable stdlib + existing codebase; only risk is tzdata if Docker base image changes)
