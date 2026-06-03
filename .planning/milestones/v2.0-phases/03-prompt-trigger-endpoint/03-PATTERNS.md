# Phase 3: Prompt Trigger Endpoint - Pattern Map

**Mapped:** 2026-05-30
**Files analyzed:** 7 new/modified files
**Analogs found:** 7 / 7

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/app/routers/prompt.py` | router | request-response (outbound) | `backend/app/routers/gastos.py` | role-match (inbound→outbound inversion) |
| `backend/app/services/cierre.py` | service | CRUD | `backend/app/services/gasto.py` | exact |
| `backend/app/services/conversation.py` | service | event-driven FSM | self (extend existing) | self-analog |
| `backend/app/config.py` | config | — | self (extend existing) | self-analog |
| `backend/app/main.py` | config/router mount | — | self (extend existing) | self-analog |
| `backend/tests/test_prompt_trigger.py` | test | request-response | `backend/tests/test_gastos_webhook.py` | exact |
| `backend/tests/test_conversation_cierre.py` | test | event-driven FSM | `backend/tests/test_conversation.py` | exact |
| `backend/tests/conftest.py` | test config | — | self (extend existing) | self-analog |

---

## Pattern Assignments

### `backend/app/routers/prompt.py` (router, request-response outbound)

**Analog:** `backend/app/routers/gastos.py`

**Imports pattern** (gastos.py lines 23–45):
```python
from __future__ import annotations

import secrets
import structlog
from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Conversation
from app.db.session import get_db
from app.providers.base import WhatsAppProvider
from app.routers.gastos import get_whatsapp_provider, _safe_send
from app.services.conversation import ConvState
```

**Bearer auth dependency** (research Pattern 1 — no codebase analog yet, copy verbatim):
```python
_bearer_scheme = HTTPBearer(auto_error=False)

def verify_token(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> None:
    """Constant-time bearer token check. Raises HTTP 401 on any failure."""
    configured = settings.gastos_prompt_token
    if not configured:
        # Fail-closed: empty config → deny all (prevents misconfiguration bypass)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    if not secrets.compare_digest(credentials.credentials, configured):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
```

**Request/response models** (mirror gastos.py pattern of pydantic body models):
```python
class PromptRequest(BaseModel):
    phone_number: str

class PromptResponse(BaseModel):
    status: str
    reason: str | None = None
```

**Provider factory reuse** (gastos.py lines 85–118 — import, do not duplicate):
```python
# Reuse get_whatsapp_provider from gastos.py directly:
from app.routers.gastos import get_whatsapp_provider, _safe_send
```

**Core handler pattern** — conversation row lock sequence (research Pattern 2, mirrors conversation.py lines 221–238):
```python
router = APIRouter()

PROMPT_TEXT = (
    "Hola. Es hora del cierre de caja.\n"
    "• ¿Tenés pagos pendientes de registrar?\n"
    "• ¿Cuánto efectivo hay en caja?\n"
    "• ¿Hiciste otra compra hoy?\n\n"
    "Podés reportar el efectivo (ej: *1500*) o describir un gasto."
)

@router.post("/gastos/prompt", response_model=PromptResponse)
async def trigger_prompt(
    body: PromptRequest,
    _: None = Security(verify_token),
    db: AsyncSession = Depends(get_db),
    provider: WhatsAppProvider = Depends(get_whatsapp_provider),
    settings: Settings = Depends(get_settings),
) -> PromptResponse:
    clean_phone = body.phone_number.strip()

    async with db.begin():
        # Step 1: ensure row exists (race-safe — mirrors conversation.py lines 222-227)
        ensure_stmt = (
            pg_insert(Conversation)
            .values(sender_phone=clean_phone, state=ConvState.IDLE)
            .on_conflict_do_nothing(index_elements=["sender_phone"])
        )
        await db.execute(ensure_stmt)

        # Step 2: lock row (mirrors conversation.py lines 233-238)
        result = await db.execute(
            select(Conversation)
            .where(Conversation.sender_phone == clean_phone)
            .with_for_update(key_share=True)
        )
        conv = result.scalar_one()

        # Step 3: check for active (non-idle) conversation
        if conv.state != ConvState.IDLE:
            return PromptResponse(status="skipped", reason="active_conversation")

        # Step 4: set state to AWAITING_CIERRE
        conv.state = ConvState.AWAITING_CIERRE
    # transaction commits here

    # Step 5: send OUTSIDE the transaction (mirrors conversation.py module docstring Pitfall C)
    log = structlog.get_logger()
    await _safe_send(provider, body.phone_number, PROMPT_TEXT, log)
    return PromptResponse(status="sent")
```

**Error handling pattern** (gastos.py lines 278–281 — never crash, log cleanly):
```python
# _safe_send already wraps send_message in try/except (gastos.py lines 151-168):
async def _safe_send(provider, to, text, task_log):
    try:
        await provider.send_message(to=to, text=text)
    except Exception as exc:
        task_log.error("gastos.reply_failed", error=str(exc), reply_text=text[:64])
```

---

### `backend/app/services/cierre.py` (service, CRUD)

**Analog:** `backend/app/services/gasto.py` (exact structural match)

**Imports pattern** (gasto.py lines 1–27 adapted for cierre):
```python
"""CajaCierreService — caja closing persistence layer.

Mirrors GastoService: stateless, session-first, caller owns transaction.
"""
from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CajaCierre
```

**ART timezone helpers** (research Pattern 5):
```python
_ART = ZoneInfo("America/Argentina/Buenos_Aires")
_CUTOFF = time(14, 30)  # 14:30 ART → "12:00" before, "17:00" at/after

def _derive_hora_cierre() -> str:
    """Return '12:00' if before 14:30 ART, else '17:00'."""
    now_art = datetime.now(_ART)
    return "12:00" if now_art.time() < _CUTOFF else "17:00"

def _today_art():
    """Return date in ART (not UTC)."""
    return datetime.now(_ART).date()
```

**Core service pattern** (mirrors gasto.py lines 30–80 exactly):
```python
class CajaCierreService:
    def __init__(self) -> None:
        self._log = structlog.get_logger()

    async def save_cierre(
        self,
        session: AsyncSession,
        efectivo_en_caja: Decimal,
        sender_phone: str,
    ) -> CajaCierre:
        """Persist a confirmed CajaCierre row.

        Caller owns the transaction — does NOT commit.
        Mirrors GastoService.save_gasto (session.flush() populates id).
        """
        clean_phone = sender_phone.removeprefix("whatsapp:").strip()
        hora_cierre = _derive_hora_cierre()
        fecha = _today_art()

        cierre = CajaCierre(
            fecha=fecha,
            hora_cierre=hora_cierre,
            efectivo_en_caja=efectivo_en_caja,  # Decimal from parse_ars_amount — never float()
            sender_phone=clean_phone,
        )
        session.add(cierre)
        await session.flush()  # populate id — caller commits (mirrors gasto.py line 72)

        self._log.info(
            "cierre.saved",
            id=str(cierre.id),
            hora_cierre=hora_cierre,
            monto=str(efectivo_en_caja),
        )
        return cierre
```

---

### `backend/app/services/conversation.py` (service, FSM extension)

**Self-analog** — extend existing file. Key insertion points:

**ConvState extension** (add after line 90, current ConvState class):
```python
class ConvState:
    IDLE = "idle"
    AWAITING_MONTO = "awaiting_monto"
    AWAITING_TICKET = "awaiting_ticket"
    CONFIRM = "confirm"
    AWAITING_CIERRE = "awaiting_cierre"                  # NEW Phase 3
    AWAITING_CIERRE_CONFIRM = "awaiting_cierre_confirm"  # NEW Phase 3
```

**DraftCierre model** (add near DraftGasto import — mirrors DraftGasto in app/models/conversation.py):
```python
class DraftCierre(BaseModel):
    cierre_monto: Optional[Decimal] = None
```

**_dispatch match block extension** (add after line 349, after `case ConvState.CONFIRM:` arm):
```python
case ConvState.AWAITING_CIERRE:
    reply = await self._handle_awaiting_cierre(session, conv, text)

case ConvState.AWAITING_CIERRE_CONFIRM:
    reply = await self._handle_cierre_confirm(session, conv, text)
```

**_handle_awaiting_cierre method** (mirrors _handle_awaiting_monto disambiguation pattern, conversation.py lines 426–480):
```python
async def _handle_awaiting_cierre(
    self,
    session: AsyncSession,
    conv: Conversation,
    text: str,
) -> str:
    # 1. Try parse_ars_amount first (fast, no API cost) — mirrors _handle_awaiting_monto line 456
    monto = parse_ars_amount(text)
    if monto is not None:
        draft = DraftCierre(cierre_monto=monto)
        conv.draft_gasto = draft.model_dump_json()  # reassign, never mutate (Pitfall E)
        conv.state = ConvState.AWAITING_CIERRE_CONFIRM
        hora = _derive_hora_cierre()
        return f"Cierre {hora}: ${monto} ¿confirmás? Respondé *sí* o *cancelar*."

    # 2. GPT slot extraction to detect gasto intent — only on parse failure
    slots = await self._slot_service.extract(text)
    if slots.concepto is not None or slots.monto is not None:
        # Hand off to gasto flow — reset state and draft first (Pitfall 4 from research)
        conv.state = ConvState.IDLE
        conv.draft_gasto = None
        return await self._handle_idle(session, conv, DraftGasto(), text)

    # 3. Neither → re-prompt
    return (
        "No entendí. Indicá el efectivo en caja (ej: *1500*) "
        "o describí un gasto para registrarlo."
    )
```

**_handle_cierre_confirm method** (mirrors _handle_confirm, conversation.py lines 536–563):
```python
async def _handle_cierre_confirm(
    self,
    session: AsyncSession,
    conv: Conversation,
    text: str,
) -> str:
    # Load cierre draft
    cierre_draft = DraftCierre()
    if conv.draft_gasto:
        try:
            cierre_draft = DraftCierre.model_validate_json(conv.draft_gasto)
        except Exception:
            self._log.warning("conversation.cierre_draft_parse_error")

    if is_confirmation(text):
        # Deterministic confirm gate — GPT never invoked (mirrors _handle_confirm line 549)
        from app.services.cierre import CajaCierreService
        await CajaCierreService().save_cierre(
            session, cierre_draft.cierre_monto, conv.sender_phone
        )
        conv.state = ConvState.IDLE
        conv.draft_gasto = None
        return "Cierre registrado. ✓"
    else:
        # Re-echo confirm (correction path — mirrors _handle_confirm lines 556-562)
        hora = _derive_hora_cierre()
        return (
            f"Cierre {hora}: ${cierre_draft.cierre_monto} ¿confirmás? "
            "Respondé *sí* o *cancelar*."
        )
```

**_derive_hora_cierre** (import or duplicate from cierre.py — put as module-level function or import):
```python
# Either import from cierre.py or inline — if inlined, mirrors the pattern in cierre.py
from app.services.cierre import _derive_hora_cierre
```

---

### `backend/app/config.py` (config, self-analog)

**Analog:** self — extend existing `Settings` class.

**Existing pattern** (config.py lines 1–56 — follow exactly):
```python
# Add to Settings class after the existing twilio_from_number field (line 45)
# Same pattern as other optional-with-default fields:
gastos_prompt_token: str = ""  # Required at runtime; empty = fail-closed (deny all)
```

**Pattern rule:** Empty string default (not `None`, not required field) so existing tests that don't set this env var don't fail at settings instantiation. The `verify_token` dependency enforces the fail-closed behavior at runtime.

---

### `backend/app/main.py` (router mount, self-analog)

**Analog:** self — extend existing `elif settings.agent_mode == "gastos":` block (lines 63–66).

**Current mount pattern** (main.py lines 63–66):
```python
elif settings.agent_mode == "gastos":
    from app.routers.gastos import router as gastos_router

    app.include_router(gastos_router, tags=["gastos"])
```

**Extended pattern** (add prompt router import after gastos_router):
```python
elif settings.agent_mode == "gastos":
    from app.routers.gastos import router as gastos_router
    from app.routers.prompt import router as prompt_router

    app.include_router(gastos_router, tags=["gastos"])
    app.include_router(prompt_router, tags=["gastos"])
```

---

### `backend/tests/test_prompt_trigger.py` (test, request-response)

**Analog:** `backend/tests/test_gastos_webhook.py`

**Imports pattern** (test_gastos_webhook.py lines 19–36):
```python
import pytest
import pytest_asyncio
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import get_settings
from app.db.models import Conversation
from app.routers.gastos import get_whatsapp_provider
from app.routers.prompt import verify_token
from app.services.conversation import ConvState
```

**ASGI client fixture pattern** (test_gastos_webhook.py lines 92–120):
```python
@pytest_asyncio.fixture
async def prompt_client(db_session, monkeypatch):
    """ASGI client for the prompt endpoint with mocked provider and DB."""
    monkeypatch.setenv("AGENT_MODE", "gastos")
    monkeypatch.setenv("GASTOS_PROMPT_TOKEN", "test-prompt-token")
    get_settings.cache_clear()

    from app.main import create_app
    from app.db.session import get_db

    app = create_app()
    mock_provider = make_mock_provider()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_whatsapp_provider] = lambda: mock_provider
    app.dependency_overrides[get_db] = override_get_db

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client, mock_provider, app

    app.dependency_overrides.clear()
    get_settings.cache_clear()
```

**Mock provider helper** (test_gastos_webhook.py lines 67–74 — reuse make_mock_provider):
```python
def make_mock_provider(validate_returns: bool = True) -> MagicMock:
    from app.providers.base import WhatsAppProvider
    mock = MagicMock(spec=WhatsAppProvider)
    mock.validate_signature = MagicMock(return_value=validate_returns)
    mock.send_message = AsyncMock()
    mock.download_media = AsyncMock(return_value=b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    return mock
```

**Auth test pattern** (mirrors test_gastos_webhook.py signature validation tests):
```python
# Valid token → 200 + send
async def test_valid_token_sends(prompt_client):
    client, mock_provider, app = prompt_client
    resp = await client.post(
        "/gastos/prompt",
        json={"phone_number": "+5491112345678"},
        headers={"Authorization": "Bearer test-prompt-token"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "sent"
    mock_provider.send_message.assert_awaited_once()

# Missing token → 401
async def test_missing_token_401(prompt_client):
    client, mock_provider, app = prompt_client
    resp = await client.post("/gastos/prompt", json={"phone_number": "+5491112345678"})
    assert resp.status_code == 401
    mock_provider.send_message.assert_not_awaited()

# Wrong token → 401
async def test_wrong_token_401(prompt_client):
    client, mock_provider, app = prompt_client
    resp = await client.post(
        "/gastos/prompt",
        json={"phone_number": "+5491112345678"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401
```

**Row lock spy pattern** (mirrors test_conversation.py lines 99–120):
```python
async def test_row_lock_issued(db_session):
    """Assert SELECT ... FOR NO KEY UPDATE is issued in trigger endpoint."""
    captured_selects = []
    original_execute = db_session.execute

    async def spy_execute(stmt, *args, **kwargs):
        from sqlalchemy.sql.selectable import Select as SASelect
        if isinstance(stmt, SASelect):
            captured_selects.append(stmt)
        return await original_execute(stmt, *args, **kwargs)

    db_session.execute = spy_execute
    # ... call endpoint, then assert:
    lock_selects = [s for s in captured_selects if s._for_update_arg is not None]
    assert len(lock_selects) >= 1
    compiled = lock_selects[0].compile(dialect=postgresql.dialect())
    assert "FOR NO KEY UPDATE" in str(compiled)
```

---

### `backend/tests/test_conversation_cierre.py` (test, FSM)

**Analog:** `backend/tests/test_conversation.py`

**Session factory helper** (test_conversation.py lines 77–90 — copy verbatim):
```python
def _make_session_factory(db_session):
    class _FakeSessionFactory:
        def __call__(self):
            return self
        async def __aenter__(self):
            return db_session
        async def __aexit__(self, *args):
            pass
    return _FakeSessionFactory()
```

**Orchestrator factory helper** (test_conversation.py lines 52–74):
```python
async def _make_orchestrator(slot_service=None, gasto_service=None, provider=None):
    from app.services.conversation import ConversationOrchestrator
    if slot_service is None:
        slot_service = AsyncMock()
        slot_service.extract = AsyncMock(return_value=GastoSlots())
    if gasto_service is None:
        gasto_service = MagicMock()
        gasto_service.save_gasto = AsyncMock(return_value=None)
    if provider is None:
        provider = AsyncMock()
        provider.send_message = AsyncMock(return_value=None)
    return ConversationOrchestrator(
        slot_service=slot_service,
        gasto_service=gasto_service,
        provider=provider,
    )
```

**FSM state test pattern** (mirrors test_conversation.py structure for state transitions):
```python
@pytest.mark.asyncio
async def test_bare_amount_advances_to_confirm(db_session):
    """Bare amount in AWAITING_CIERRE → state becomes AWAITING_CIERRE_CONFIRM."""
    from app.db.models import Conversation
    from app.services.conversation import ConvState

    # Seed conversation in AWAITING_CIERRE
    conv = Conversation(sender_phone="+5491112345678", state=ConvState.AWAITING_CIERRE)
    db_session.add(conv)
    await db_session.flush()

    orch = await _make_orchestrator()
    sf = _make_session_factory(db_session)
    await orch.handle_message(sf, "whatsapp:+5491112345678", "1500", "msg-cierre-001")

    await db_session.refresh(conv)
    assert conv.state == ConvState.AWAITING_CIERRE_CONFIRM
```

**hora_cierre time-mock pattern** (research Validation Architecture section):
```python
@pytest.mark.asyncio
async def test_hora_cierre_morning(db_session):
    """hora_cierre = '12:00' when ART time is before 14:30."""
    from unittest.mock import patch
    from datetime import datetime
    from zoneinfo import ZoneInfo

    _ART = ZoneInfo("America/Argentina/Buenos_Aires")
    mock_time = datetime(2026, 5, 30, 11, 0, tzinfo=_ART)

    with patch("app.services.cierre.datetime") as mock_dt:
        mock_dt.now.return_value = mock_time
        from app.services.cierre import _derive_hora_cierre
        assert _derive_hora_cierre() == "12:00"

@pytest.mark.asyncio
async def test_hora_cierre_afternoon(db_session):
    """hora_cierre = '17:00' when ART time is at/after 14:30."""
    from unittest.mock import patch
    from datetime import datetime
    from zoneinfo import ZoneInfo

    _ART = ZoneInfo("America/Argentina/Buenos_Aires")
    mock_time = datetime(2026, 5, 30, 14, 30, tzinfo=_ART)

    with patch("app.services.cierre.datetime") as mock_dt:
        mock_dt.now.return_value = mock_time
        from app.services.cierre import _derive_hora_cierre
        assert _derive_hora_cierre() == "17:00"
```

---

### `backend/tests/conftest.py` (test config, self-analog)

**Analog:** self — extend existing `env_setup` fixture.

**Current env_setup pattern** (conftest.py lines 34–67):
```python
@pytest.fixture(scope="session", autouse=True)
def env_setup():
    mp = pytest.MonkeyPatch()
    mp.setenv("DATABASE_URL", TEST_DATABASE_URL)
    mp.setenv("OPENAI_API_KEY", "test-openai-key")
    # ... existing setenv calls ...
    mp.setenv("AGENT_MODE", "gastos")
    # ADD THIS LINE (research Pitfall 6):
    mp.setenv("GASTOS_PROMPT_TOKEN", "test-prompt-token")
    # ...
```

**Single addition required:** `mp.setenv("GASTOS_PROMPT_TOKEN", "test-prompt-token")` added after the `AGENT_MODE` line. Tests that verify 401 behavior pass a deliberately wrong token in the request headers, not by unsetting this env var.

---

## Shared Patterns

### `pg_insert` + `FOR NO KEY UPDATE` Row Lock Sequence
**Source:** `backend/app/services/conversation.py` lines 221–238
**Apply to:** `routers/prompt.py` trigger handler (must replicate this exact sequence before any state read/write)
```python
# 1. Ensure row exists
ensure_stmt = (
    pg_insert(Conversation)
    .values(sender_phone=clean_phone, state=ConvState.IDLE)
    .on_conflict_do_nothing(index_elements=["sender_phone"])
)
await session.execute(ensure_stmt)

# 2. Lock and read
result = await session.execute(
    select(Conversation)
    .where(Conversation.sender_phone == clean_phone)
    .with_for_update(key_share=True)  # → FOR NO KEY UPDATE
)
conv = result.scalar_one()
```

### Send-After-Commit Ordering (Pitfall C)
**Source:** `backend/app/services/conversation.py` module docstring + lines 307–310
**Apply to:** `routers/prompt.py` — `_safe_send` must be called STRICTLY after the `async with db.begin()` block exits. Never inside the transaction.
```python
# WRONG — send inside transaction block (will cause state rollback on send failure):
async with db.begin():
    conv.state = ConvState.AWAITING_CIERRE
    await _safe_send(...)  # WRONG

# CORRECT:
async with db.begin():
    conv.state = ConvState.AWAITING_CIERRE
# commit happens here
await _safe_send(...)  # send AFTER commit
```

### draft_gasto Column Reassignment (Pitfall E)
**Source:** `backend/app/services/conversation.py` lines 375–381, module docstring
**Apply to:** `services/conversation.py` cierre handlers — always reassign, never mutate in-place
```python
# WRONG — in-place mutation, SQLAlchemy change-tracking misses it:
conv.draft_gasto["cierre_monto"] = 1500  # WRONG

# CORRECT — reassign the column:
conv.draft_gasto = draft.model_dump_json()
```

### Constant-Time Token Comparison
**Source:** research Pattern 1, Python stdlib `secrets.compare_digest`
**Apply to:** `routers/prompt.py` `verify_token` dependency — never use `==` for token comparison
```python
import secrets
# Always compare with secrets.compare_digest — timing-safe:
if not secrets.compare_digest(credentials.credentials, configured):
    raise HTTPException(status_code=401, detail="Unauthorized")
```

### Caller-Owns-Transaction Pattern
**Source:** `backend/app/services/gasto.py` lines 40–78
**Apply to:** `services/cierre.py` `save_cierre` — call `session.flush()` (not `commit()`); orchestrator commits
```python
session.add(cierre)
await session.flush()  # populate id — caller commits, NOT this method
```

### structlog Binding Pattern
**Source:** `backend/app/routers/gastos.py` lines 45, 197; `backend/app/services/gasto.py` lines 37, 74–78
**Apply to:** `routers/prompt.py`, `services/cierre.py`
```python
log = structlog.get_logger()
# In handler: bind per-request context
log = structlog.get_logger().bind(phone=clean_phone)
# In service: plain get_logger (no binding — caller provides context)
self._log = structlog.get_logger()
self._log.info("cierre.saved", id=str(cierre.id), hora_cierre=hora_cierre)
```

### dependency_overrides Test Pattern
**Source:** `backend/tests/test_gastos_webhook.py` lines 107–118
**Apply to:** `tests/test_prompt_trigger.py` — override both provider and db
```python
app.dependency_overrides[get_whatsapp_provider] = lambda: mock_provider
app.dependency_overrides[get_db] = override_get_db
# Always clear after test:
app.dependency_overrides.clear()
```

### is_confirmation / is_cancel Reuse
**Source:** `backend/app/services/conversation.py` lines 122–146
**Apply to:** `services/conversation.py` `_handle_cierre_confirm` — reuse verbatim, no new logic
```python
# Already defined at module level — just call:
if is_confirmation(text):
    # write cierre, reset to IDLE
elif is_cancel(text):
    # handled upstream (global cancel at handle_message Step 6) — do NOT duplicate
```

---

## No Analog Found

All files have close analogs in the codebase. No files require falling back to RESEARCH.md patterns exclusively — though `routers/prompt.py`'s bearer auth dependency (`verify_token`) has no codebase analog yet and must be written fresh from research Pattern 1.

| File | Note |
|------|------|
| `verify_token` function in `routers/prompt.py` | Novel pattern — no existing FastAPI Security dependency in codebase. Use research Pattern 1 exactly. |
| `_derive_hora_cierre` / `_today_art` in `services/cierre.py` | Novel pattern — no existing `zoneinfo` usage in codebase. Use research Pattern 5 exactly. |

---

## Metadata

**Analog search scope:** `backend/app/routers/`, `backend/app/services/`, `backend/app/config.py`, `backend/app/main.py`, `backend/app/db/models.py`, `backend/tests/`
**Files scanned:** 8 source files, 2 test files, 1 config file
**Pattern extraction date:** 2026-05-30

**Critical implementation ordering constraints (anti-patterns from research):**
1. `_safe_send` MUST be called after `async with db.begin()` exits — never inside
2. `verify_token` MUST fail-closed when `settings.gastos_prompt_token == ""`
3. `conv.draft_gasto` MUST be reassigned (not mutated in-place) to trigger SQLAlchemy change-tracking
4. `parse_ars_amount` is tried BEFORE GPT slot extraction in `_handle_awaiting_cierre`
5. When handing off to gasto flow from `AWAITING_CIERRE`, MUST set `conv.draft_gasto = None` BEFORE calling `_handle_idle`
6. Global `is_cancel()` check in `handle_message` (Step 6) covers ALL states including cierre states — do NOT add duplicate cancel handling in cierre handlers
