# Phase 3: WhatsApp Pipeline - Pattern Map

**Mapped:** 2026-05-14
**Files analyzed:** 14 new/modified files
**Analogs found:** 12 / 14

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/app/providers/__init__.py` | config | — | `backend/app/services/__init__.py` | exact (empty module init) |
| `backend/app/providers/base.py` | protocol/interface | — | `backend/app/services/storage.py` | exact (typing.Protocol + @runtime_checkable) |
| `backend/app/providers/twilio.py` | service | request-response | `backend/app/services/extraction.py` | role-match (constructor injection, structlog, async methods) |
| `backend/app/providers/meta.py` | service stub | — | `backend/app/providers/twilio.py` (to be created) | partial (stub satisfies same Protocol) |
| `backend/app/routers/whatsapp.py` | router | request-response | `backend/app/routers/extraction.py` | exact (APIRouter, Depends, service injection, error handling) |
| `backend/app/services/invoice.py` | service | CRUD | `backend/app/services/extraction.py` | role-match (class, constructor injection, AsyncSession, structlog) |
| `backend/app/config.py` | config | — | self (modify) | self |
| `backend/app/main.py` | config | — | self (modify) | self |
| `backend/alembic/versions/<new>.py` | migration | — | `backend/alembic/versions/add_is_active_server_default.py` | exact (op.execute pattern for functional index) |
| `backend/tests/test_whatsapp.py` | test | request-response | `backend/tests/test_extraction.py` | exact (ASGI client, dependency_overrides, monkeypatch, structlog.testing) |
| `backend/tests/test_invoice_service.py` | test | CRUD | `backend/tests/test_extraction.py` + `backend/tests/test_health.py` | role-match (db_session fixture, async tests, AsyncSession) |
| `backend/tests/test_providers.py` | test | unit | `backend/tests/test_extraction.py` | role-match (MagicMock injection, unittest.mock) |
| `backend/requirements.txt` | config | — | self (modify) | self |
| `docker-compose.yml` | config | — | self (modify) | self |

---

## Pattern Assignments

### `backend/app/providers/__init__.py` (module init)

**Analog:** `backend/app/services/__init__.py` (empty file)

This file is empty. Use the same pattern as all other `__init__.py` files in the project — an empty file that marks the directory as a Python package.

```python
# empty
```

---

### `backend/app/providers/base.py` (protocol/interface)

**Analog:** `backend/app/services/storage.py`

**Imports pattern** (storage.py lines 25-28):
```python
from __future__ import annotations

import os
from typing import Protocol, runtime_checkable
```

**Protocol definition pattern** (storage.py lines 31-37):
```python
@runtime_checkable
class StorageBackend(Protocol):
    """Interface for invoice image storage. Phase 2: save only. delete() is Phase 4."""

    def save(self, data: bytes, filename: str) -> str:
        """Save data to storage. Returns relative path."""
        ...
```

**Apply to `WhatsAppProvider`:** Same `@runtime_checkable` + `typing.Protocol` pattern. Three async methods + one sync method:

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class WhatsAppProvider(Protocol):
    """Provider-agnostic WhatsApp interface (D-03).

    Implementations: TwilioProvider (demo), MetaCloudProvider (production stub).
    Handler code imports only this protocol — never twilio or pywa directly.
    """

    async def send_message(self, to: str, text: str) -> None:
        """Send a WhatsApp text message to the given phone number."""
        ...

    async def download_media(self, media_url: str) -> bytes:
        """Download media bytes from the provider-specific URL."""
        ...

    def validate_signature(
        self, request_url: str, params: dict, signature: str
    ) -> bool:
        """Validate the webhook request signature. Synchronous (CPU-bound)."""
        ...
```

**Why Protocol not ABC:** storage.py established this pattern (see its docstring lines 20-24: "No forced inheritance — LocalStorageBackend satisfies Protocol structurally. @runtime_checkable allows isinstance(backend, StorageBackend) in tests."). Apply identically.

---

### `backend/app/providers/twilio.py` (service, request-response)

**Analog:** `backend/app/services/extraction.py`

**Module docstring + imports pattern** (extraction.py lines 1-27):
```python
"""ExtractionService — GPT-4o vision extraction service.

Citations:
- D-01: ...
"""
from __future__ import annotations

import structlog
from openai import AsyncOpenAI

from app.config import Settings
from app.services.storage import StorageBackend

log = structlog.get_logger()
```

**Apply to TwilioProvider:** Same module-level `log = structlog.get_logger()`, same `from app.config import Settings`, same constructor injection pattern.

**Constructor injection pattern** (extraction.py lines 148-157):
```python
class ExtractionService:
    def __init__(
        self,
        openai_client: AsyncOpenAI,
        storage: StorageBackend,
        settings: Settings,
    ) -> None:
        self._client = openai_client
        self._storage = storage
        self._settings = settings
        self._log = structlog.get_logger()  # lazy proxy; bind at call time (Pattern 6)
```

**Apply to TwilioProvider constructor:**
```python
class TwilioProvider:
    def __init__(self, account_sid: str, auth_token: str, from_number: str) -> None:
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_number = from_number  # must include "whatsapp:" prefix
        self._validator = RequestValidator(auth_token)
        self._log = structlog.get_logger()
```

**Error logging pattern** (extraction.py lines 196-199):
```python
except Exception as exc:
    # Network errors, AuthenticationError, etc. — never log secrets (T-02-02)
    log.error("extraction.failed", error=str(exc), stage="openai_parse")
    raise ExtractionFailedError(f"openai parse failed: {exc}") from exc
```

**Apply to TwilioProvider:** Use `log.error("whatsapp.send_failed", error=str(exc))` style. Never log `auth_token` or `account_sid` — same T-02-02 constraint.

**Structlog binding pattern** (extraction.py lines 221):
```python
log = self._log.bind(filename=os.path.basename(filename))
log.info("extraction.start")
```

**Apply to TwilioProvider:** `log = self._log.bind(to=to)` before sending; `log.info("whatsapp.send_message")`.

---

### `backend/app/providers/meta.py` (service stub)

**Analog:** `backend/app/providers/twilio.py` (to be created in same phase)

This is a stub that satisfies `WhatsAppProvider` Protocol with `raise NotImplementedError` bodies. Pattern: same class structure as `TwilioProvider` but all methods raise `NotImplementedError("MetaCloudProvider not implemented — set WHATSAPP_PROVIDER=twilio")`.

No separate analog needed — mirror `TwilioProvider`'s class skeleton exactly, substitute `raise NotImplementedError` for all method bodies.

---

### `backend/app/routers/whatsapp.py` (router, request-response)

**Analog:** `backend/app/routers/extraction.py` (exact match)

**Module docstring + imports pattern** (extraction.py lines 1-23):
```python
"""Debug-only extraction test endpoint.

Citations:
- D-05: Registered ONLY when settings.debug is True (gated in create_app())
...
"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from openai import AsyncOpenAI

from app.config import Settings, get_settings
from app.services.extraction import ExtractionResult, ExtractionService
from app.services.storage import LocalStorageBackend

router = APIRouter()
```

**Apply to whatsapp router:**
```python
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response

from app.config import Settings, get_settings
from app.db.session import get_db
from app.providers.base import WhatsAppProvider
from app.services.invoice import InvoiceService

router = APIRouter()
```

**Provider factory dependency pattern** (extraction.py lines 27-42 — `get_extraction_service`):
```python
def get_extraction_service(
    settings: Settings = Depends(get_settings),
) -> ExtractionService:
    """Construct ExtractionService with all dependencies.

    This is the SOLE construction site for ExtractionService in production.
    Tests override this via:
        app.dependency_overrides[get_extraction_service] = lambda: mocked_service
    """
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    storage = LocalStorageBackend(root=settings.storage_path)
    return ExtractionService(
        openai_client=openai_client,
        storage=storage,
        settings=settings,
    )
```

**Apply to whatsapp router:** Create `get_whatsapp_provider(settings: Settings = Depends(get_settings)) -> WhatsAppProvider` as the SOLE construction site for the provider. Tests override via `app.dependency_overrides[get_whatsapp_provider]`.

**Route handler pattern** (extraction.py lines 45-64):
```python
@router.post("/test", response_model=ExtractionResult)
async def extraction_test(
    file: UploadFile = File(...),
    service: ExtractionService = Depends(get_extraction_service),
) -> ExtractionResult:
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")
    return await service.extract(
        image_bytes=data,
        filename=file.filename or "upload.bin",
    )
```

**Apply to whatsapp webhook:** Use `Form(...)` parameters instead of `File(...)`. Return `Response(status_code=200)` (empty body — Twilio accepts plain 200). The `asyncio.create_task` pattern goes between signature validation and the return.

**Module-level background task set** (from RESEARCH.md Pattern 4 — no existing codebase analog, new pattern):
```python
# Module-level strong reference set — prevents Python 3.12 GC from collecting tasks
# before they complete. Pattern: Python docs asyncio-task.html
_background_tasks: set = set()
```

**HTTPException pattern** (extraction.py line 62):
```python
raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")
```

**Apply to whatsapp router:** `raise HTTPException(status_code=401, detail="Invalid signature")` for HMAC failure.

---

### `backend/app/services/invoice.py` (service, CRUD)

**Analog:** `backend/app/services/extraction.py` (role-match — same service class pattern)

**Module docstring pattern** (extraction.py lines 1-11):
```python
"""ExtractionService — GPT-4o vision extraction service.

Citations:
- D-01: Confidence formula — non_null(tipo, numero, proveedor, fecha) / 4
...
"""
from __future__ import annotations
```

**Imports pattern** (extraction.py lines 12-27 + health.py lines 3-6):
```python
# From extraction.py — structlog + typing
import structlog
from app.config import Settings

# From health.py — DB imports
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# For invoice.py specifically:
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import func
from app.db.models import Invoice, InvoiceLineItem
from app.services.extraction import ExtractionResult
```

**Service class with constructor injection** (extraction.py lines 134-157):
```python
class ExtractionService:
    def __init__(
        self,
        openai_client: AsyncOpenAI,
        storage: StorageBackend,
        settings: Settings,
    ) -> None:
        self._client = openai_client
        self._storage = storage
        self._settings = settings
        self._log = structlog.get_logger()
```

**Apply to InvoiceService:** Lighter constructor — no external client deps needed. `InvoiceService` takes no constructor args (stateless utility service); all methods take `session: AsyncSession` as first argument. This keeps it testable with the `db_session` fixture directly.

**DB query pattern** (health.py lines 14-18):
```python
await db.execute(
    select(func.count()).select_from(SenderAllowlist)
)
```

**Apply to `find_duplicate`:**
```python
async def find_duplicate(
    self, session: AsyncSession, numero: str | None, proveedor: str | None
) -> Invoice | None:
    if not numero or not proveedor:
        return None
    result = await session.execute(
        select(Invoice).where(
            func.lower(Invoice.numero_documento) == func.lower(numero),
            func.lower(Invoice.proveedor) == func.lower(proveedor),
        ).limit(1)
    )
    return result.scalar_one_or_none()
```

**Error handling pattern** (extraction.py lines 265-272):
```python
except ExtractionError:
    # Re-raise ExtractionRefusalError / ExtractionFailedError as-is
    raise
except Exception as exc:
    # Unexpected error — log with context but NEVER include secrets (T-02-02)
    log.error("extraction.failed", error=str(exc))
    raise ExtractionFailedError(str(exc)) from exc
```

**Apply to `save_invoice`:** Catch `IntegrityError` (UniqueViolation) explicitly — re-raise after rollback. Caller in `process_invoice` treats it as duplicate.

```python
async def save_invoice(self, session: AsyncSession, ...) -> Invoice:
    invoice = Invoice(...)
    session.add(invoice)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise  # caller catches IntegrityError and sends duplicate reply
    return invoice
```

---

### `backend/app/config.py` (modify — add Twilio settings)

**Analog:** self (lines 1-30 — read above)

**Existing Settings pattern** (config.py lines 6-26):
```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Required — no default — app refuses to start if missing (INF-03)
    database_url: str
    openai_api_key: str
    whatsapp_token: str
    whatsapp_phone_number_id: str
    whatsapp_verify_token: str

    # Optional with defaults
    debug: bool = False
    log_level: str = "INFO"
    confidence_threshold: float = 0.85
    storage_path: str = "/data/invoices"
```

**Fields to add** — follow the same pattern (required fields no default, optional with default):
```python
    # WhatsApp provider selection (D-04)
    whatsapp_provider: str = "twilio"  # "twilio" | "meta"

    # Twilio credentials (required when whatsapp_provider="twilio")
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""  # e.g. "whatsapp:+14155238886"
```

Note: Give Twilio fields a default of `""` (not required at Settings validation time) because the Meta path doesn't need them. The provider factory validates presence at construction time if `whatsapp_provider == "twilio"`.

---

### `backend/app/main.py` (modify — register whatsapp router)

**Analog:** self (lines 35-57 — read above)

**Conditional router registration pattern** (main.py lines 49-52):
```python
    # Debug-only extraction test endpoint (D-05) — not registered in production
    if settings.debug:
        from app.routers.extraction import router as extraction_router
        app.include_router(extraction_router, prefix="/extraction", tags=["extraction"])
```

**Apply to whatsapp router:** Register unconditionally (always active — not debug-only):
```python
    # WhatsApp webhook — always registered; provider selected via WHATSAPP_PROVIDER env var
    from app.routers.whatsapp import router as whatsapp_router
    app.include_router(whatsapp_router, prefix="/whatsapp", tags=["whatsapp"])
```

Import inside `create_app()` body — same pattern as all other routers to avoid circular imports (main.py line 44 comment: "Import router inside factory — avoids circular import at module init time").

---

### `backend/alembic/versions/<new>_add_invoice_duplicate_constraint.py` (migration)

**Analog:** `backend/alembic/versions/add_is_active_server_default.py` (exact match for post-initial migration structure)

**Migration header pattern** (add_is_active lines 1-17):
```python
"""add server_default to sender_allowlist.is_active

Revision ID: 9f9e9cf65e1e
Revises: 0cd640399c29
Create Date: 2026-05-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '9f9e9cf65e1e'
down_revision: Union[str, Sequence[str], None] = '0cd640399c29'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
```

**Apply to new migration:** `down_revision` must point to `'9f9e9cf65e1e'` (the current head).

**op.execute pattern for functional index** (no existing analog — use `op.execute()` raw SQL as shown in RESEARCH.md):
```python
def upgrade() -> None:
    """Add functional unique index on (LOWER(numero_documento), LOWER(proveedor)).

    Backstops application-level duplicate check against race conditions (D-15).
    Postgres UNIQUE ignores rows where either indexed column is NULL — correct
    behavior for low-confidence extractions (Pitfall 6 in RESEARCH.md).
    WHERE clause is required to match this NULL-exclusion behavior explicitly.
    """
    op.execute(
        "CREATE UNIQUE INDEX uq_invoices_numero_proveedor_lower "
        "ON invoices (LOWER(numero_documento), LOWER(proveedor)) "
        "WHERE numero_documento IS NOT NULL AND proveedor IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_invoices_numero_proveedor_lower")
```

---

### `backend/tests/test_whatsapp.py` (test, request-response)

**Analog:** `backend/tests/test_extraction.py` (exact match — same ASGI client + dependency_overrides pattern)

**Imports pattern** (test_extraction.py lines 13-43):
```python
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
import structlog
import structlog.testing

from app.config import get_settings
from app.routers.extraction import get_extraction_service
from app.services.extraction import (
    ExtractionFailedError,
    ExtractionRefusalError,
    ExtractionResult,
    ExtractionService,
    assign_status,
    compute_confidence,
)
```

**Apply to test_whatsapp.py:**
```python
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
import structlog.testing

from app.config import get_settings
from app.routers.whatsapp import get_whatsapp_provider
from app.providers.base import WhatsAppProvider
```

**ASGI client fixture with dependency_overrides** (test_extraction.py lines 113-136):
```python
@pytest_asyncio.fixture
async def debug_client(monkeypatch):
    monkeypatch.setenv("DEBUG", "true")
    get_settings.cache_clear()

    from app.main import create_app
    app = create_app()

    mocked_service = make_mock_service(parsed_invoice=_stub_invoice())
    app.dependency_overrides[get_extraction_service] = lambda: mocked_service

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c

    app.dependency_overrides.clear()
    get_settings.cache_clear()
```

**Apply to test_whatsapp.py:** Use same `dependency_overrides[get_whatsapp_provider]` pattern. The mock provider's `validate_signature` returns `True` by default; override to `False` to test 401 path. The mock provider's `send_message` is an `AsyncMock` so `await provider.send_message(...)` works without live Twilio calls.

**Mock builder pattern** (test_extraction.py lines 51-65 — `make_mock_completion`):
```python
def make_mock_completion(...) -> MagicMock:
    """Verbatim Pattern 5 from 02-PATTERNS.md — verified against openai==2.36.0."""
    mock_message = MagicMock(spec=ParsedChatCompletionMessage)
    mock_message.parsed = parsed_invoice
    mock_message.refusal = refusal
    ...
```

**Apply:** Create `make_mock_provider(validate_returns=True) -> MagicMock` that returns a `MagicMock` with `validate_signature` returning the given bool and `send_message`/`download_media` as `AsyncMock`.

**Twilio form POST helper** (new pattern, no codebase analog — construct from RESEARCH.md payload):
```python
def make_twilio_form(
    From="whatsapp:+5491112345678",
    MessageSid="SMtest123",
    NumMedia="1",
    MediaUrl0="https://api.twilio.com/media/test",
    MediaContentType0="image/jpeg",
    Body="",
) -> dict:
    return {
        "From": From,
        "MessageSid": MessageSid,
        "NumMedia": NumMedia,
        "MediaUrl0": MediaUrl0,
        "MediaContentType0": MediaContentType0,
        "Body": Body,
    }

# Usage in test:
response = await client.post(
    "/whatsapp/webhook",
    data=make_twilio_form(),
    headers={"X-Twilio-Signature": "valid-sig"},
)
```

**Structlog capture pattern** (test_extraction.py lines 269-278):
```python
with structlog.testing.capture_logs() as cap_logs:
    with pytest.raises(ExtractionRefusalError):
        await service.extract(b"img", "photo.jpg")

failed_events = [e for e in cap_logs if e.get("event") == "extraction.failed"]
assert len(failed_events) >= 1
```

**Apply:** `with structlog.testing.capture_logs() as cap_logs:` then check `"whatsapp.received"`, `"whatsapp.rejected"` events.

**conftest env_setup — new env vars to add** (conftest.py lines 41-47):
```python
mp.setenv("WHATSAPP_TOKEN", "test-whatsapp-token")
mp.setenv("WHATSAPP_PHONE_NUMBER_ID", "test-phone-number-id")
mp.setenv("WHATSAPP_VERIFY_TOKEN", "test-verify-token")
```

**Phase 3 additions to conftest.py `env_setup`:**
```python
mp.setenv("WHATSAPP_PROVIDER", "twilio")
mp.setenv("TWILIO_ACCOUNT_SID", "test-twilio-sid")
mp.setenv("TWILIO_AUTH_TOKEN", "test-twilio-token")
mp.setenv("TWILIO_FROM_NUMBER", "whatsapp:+14155238886")
```

---

### `backend/tests/test_invoice_service.py` (test, CRUD)

**Analog:** `backend/tests/test_extraction.py` (service tests) + `backend/tests/test_health.py` (db_session fixture usage)

**db_session fixture usage** (test_health.py lines 15-27):
```python
@pytest_asyncio.fixture
async def client(db_session):
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with httpx.AsyncClient(...) as c:
        yield c
    app.dependency_overrides.clear()
```

**Apply to test_invoice_service.py:** Use `db_session` fixture directly (no ASGI client needed — service tests call `InvoiceService` methods directly with the session):

```python
@pytest.mark.asyncio
async def test_find_duplicate_returns_none_when_no_match(db_session):
    service = InvoiceService()
    result = await service.find_duplicate(db_session, "0001-001", "Proveedor SA")
    assert result is None
```

**DB seed pattern** (test_health.py lines 42-43):
```python
db_session.add(SenderAllowlist(phone_number="+5491100000000"))
await db_session.commit()
```

**Apply to duplicate detection tests:**
```python
db_session.add(Invoice(
    numero_documento="0001-00000001",
    proveedor="Acme SA",
    status="auto_saved",
))
await db_session.commit()
```

Note: The `UNIQUE INDEX` on `LOWER(numero_documento)` is a **functional index** created via `op.execute()` raw SQL. SQLite (used in tests via `aiosqlite`) does not support functional indexes. Tests for `IntegrityError` on duplicate INSERT must either: (a) skip the constraint test in unit tests and mark as integration-only, or (b) use a different assertion. The `find_duplicate()` SELECT path works on SQLite. Document this constraint in test file.

---

### `backend/tests/test_providers.py` (test, unit)

**Analog:** `backend/tests/test_extraction.py` (unit tests with mocked deps)

**MagicMock + AsyncMock pattern** (test_extraction.py lines 82-99):
```python
mock_openai = MagicMock()
mock_openai.chat.completions.parse = AsyncMock(
    return_value=make_mock_completion(parsed_invoice, refusal)
)
mock_storage = MagicMock(spec=StorageBackend)
mock_storage.save.return_value = storage_save_return
settings = get_settings()
return ExtractionService(
    openai_client=mock_openai,
    storage=mock_storage,
    settings=settings,
)
```

**Apply to test_providers.py:** Mock the `RequestValidator` and `AsyncTwilioHttpClient` to test `TwilioProvider` in isolation:

```python
from unittest.mock import AsyncMock, MagicMock, patch

def make_twilio_provider() -> TwilioProvider:
    return TwilioProvider(
        account_sid="ACtest",
        auth_token="test-token",
        from_number="whatsapp:+14155238886",
    )

@patch("app.providers.twilio.RequestValidator")
def test_validate_signature_calls_validator(mock_validator_cls):
    mock_validator = MagicMock()
    mock_validator.validate.return_value = True
    mock_validator_cls.return_value = mock_validator

    provider = make_twilio_provider()
    result = provider.validate_signature("https://example.com/webhook", {}, "sig")

    assert result is True
    mock_validator.validate.assert_called_once_with("https://example.com/webhook", {}, "sig")
```

---

## Shared Patterns

### structlog Logging
**Source:** `backend/app/services/extraction.py` lines 19, 27, 221-223, 253-257
**Apply to:** All new service and router files (`invoice.py`, `whatsapp.py`, `twilio.py`)

```python
# Module-level logger (lazy proxy)
log = structlog.get_logger()

# Bind context at call time, not in __init__
log = self._log.bind(sender=sender_phone, message_sid=message_sid)
log.info("whatsapp.received")

# Error logging — never include secret values
log.error("whatsapp.send_failed", error=str(exc))   # NOT: auth_token=self._auth_token
```

Event name convention: `"<domain>.<action>"` — e.g. `"whatsapp.received"`, `"whatsapp.rejected"`, `"invoice.duplicate"`, `"invoice.saved"`.

### Settings Dependency Injection
**Source:** `backend/app/config.py` lines 28-30; `backend/app/routers/extraction.py` lines 27-30
**Apply to:** `whatsapp.py` router (provider factory), any new service that needs settings

```python
@lru_cache
def get_settings() -> Settings:
    return Settings()

# In router dependency:
def get_whatsapp_provider(
    settings: Settings = Depends(get_settings),
) -> WhatsAppProvider:
    ...
```

### AsyncSession DB Dependency
**Source:** `backend/app/db/session.py` lines 1-17; `backend/app/routers/health.py` lines 12-13
**Apply to:** `whatsapp.py` webhook handler (allowlist check), `invoice.py` (called from background task with its own session)

```python
from app.db.session import get_db

@router.post("/whatsapp/webhook")
async def whatsapp_webhook(
    ...,
    db: AsyncSession = Depends(get_db),
):
    ...
```

Note: The background task `process_invoice(...)` runs outside the request lifecycle and CANNOT use `Depends(get_db)`. It must open its own session using `get_async_session_local()` directly (same pattern as `get_db` does internally in `session.py` lines 14-17).

### HTTPException for Request Rejection
**Source:** `backend/app/routers/extraction.py` line 62
**Apply to:** `whatsapp.py` — signature validation failure (401), not for business-logic rejections (allowlist, duplicate — those get a 200 + reply message)

```python
raise HTTPException(status_code=401, detail="Invalid signature")
```

### dependency_overrides Test Pattern
**Source:** `backend/tests/test_extraction.py` lines 129, 136; `backend/tests/test_health.py` lines 22-23
**Apply to:** `test_whatsapp.py` (override `get_whatsapp_provider` and `get_db`), `test_invoice_service.py` (use `db_session` directly)

```python
app.dependency_overrides[get_whatsapp_provider] = lambda: mock_provider
app.dependency_overrides[get_db] = override_get_db
# Always clear after test:
app.dependency_overrides.clear()
```

### conftest env_setup for New Settings Fields
**Source:** `backend/tests/conftest.py` lines 41-47
**Apply to:** Existing `conftest.py` — add new Twilio env vars to the session-scoped `env_setup` fixture so all Phase 3 tests see them without local patching.

```python
mp.setenv("WHATSAPP_PROVIDER", "twilio")
mp.setenv("TWILIO_ACCOUNT_SID", "test-twilio-sid")
mp.setenv("TWILIO_AUTH_TOKEN", "test-twilio-token")
mp.setenv("TWILIO_FROM_NUMBER", "whatsapp:+14155238886")
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `backend/app/providers/meta.py` | service stub | — | No stub/placeholder service pattern exists; copy TwilioProvider skeleton with `raise NotImplementedError` bodies |
| `docker-compose.yml` (env var additions) | config | — | No compose file read — add `WHATSAPP_PROVIDER`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` env vars under the `backend` service following the existing `DATABASE_URL`/`OPENAI_API_KEY` pattern |

---

## Metadata

**Analog search scope:** `backend/app/` (all routers, services, db, config), `backend/tests/`, `backend/alembic/versions/`
**Files scanned:** 13 Python source files + 2 Alembic migrations
**Pattern extraction date:** 2026-05-14
