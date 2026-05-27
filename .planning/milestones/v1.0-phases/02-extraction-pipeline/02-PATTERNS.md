# Phase 2: Extraction Pipeline - Pattern Map

**Mapped:** 2026-05-13
**Files analyzed:** 8
**Analogs found:** 7 / 8

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/app/services/extraction.py` | service | request-response | `backend/app/routers/health.py` + research patterns | partial (no service analog yet) |
| `backend/app/services/storage.py` | service | file-I/O | `backend/app/db/session.py` (provider pattern) | partial |
| `backend/app/routers/extraction.py` | router | request-response | `backend/app/routers/health.py` | exact role-match |
| `backend/scripts/calibrate_prompt.py` | utility | batch | `backend/app/models/extraction.py` (import patterns) | partial |
| `backend/tests/test_extraction.py` | test | request-response | `backend/tests/test_health.py` + `backend/tests/test_extraction_models.py` | role-match |
| `backend/app/config.py` | config | — | self (MODIFY) | self |
| `backend/app/main.py` | config/factory | — | self (MODIFY) | self |
| `requirements-dev.txt` | config | — | self (MODIFY) | self |

---

## Pattern Assignments

### `backend/app/services/extraction.py` (service, request-response)

**Analog:** `backend/app/routers/health.py` (router structure), `backend/app/db/session.py` (dependency injection), `backend/app/models/extraction.py` (model imports)

**Imports pattern** — copy from `backend/app/routers/health.py` lines 1–6 + research:
```python
"""ExtractionService — GPT-4o vision extraction with confidence scoring."""
from __future__ import annotations

import base64
import os
import uuid
from typing import Optional

import structlog
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.config import Settings
from app.models.extraction import ExtractedInvoice
```

**structlog pattern** — copy from `backend/app/main.py` lines 16 + 22–23 (get_logger at module level, bind at call time):
```python
# backend/app/main.py lines 16, 22-23
log = structlog.get_logger()

# Inside a method — bind at call time, NOT at __init__ time:
log.info("app.starting", log_level=settings.log_level)
```
For the service: `self._log = structlog.get_logger()` in `__init__`; `log = self._log.bind(filename=filename)` inside `extract()`.

**Constructor injection pattern** — matches `get_settings()` DI pattern from `backend/app/config.py` lines 26–28:
```python
# backend/app/config.py lines 26-28
@lru_cache
def get_settings() -> Settings:
    return Settings()
```
Service constructor receives `openai_client: AsyncOpenAI`, `storage: StorageBackend`, `settings: Settings` — never constructs them internally.

**Core extraction pattern** (from RESEARCH.md Pattern 1, verified in-tree):
```python
async def _call_gpt4o(self, image_bytes: bytes) -> tuple[ExtractedInvoice | None, str | None]:
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    completion = await self._client.chat.completions.parse(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": self._prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract all invoice fields from this image."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                ],
            },
        ],
        response_format=ExtractedInvoice,
    )
    msg = completion.choices[0].message
    return (msg.parsed, msg.refusal)  # check refusal BEFORE parsed
```

**Confidence score pattern** (D-01, from RESEARCH.md Code Examples):
```python
def _compute_confidence(self, invoice: ExtractedInvoice) -> float:
    critical = [
        invoice.tipo_comprobante,
        invoice.numero_documento,
        invoice.proveedor,
        invoice.fecha,
    ]
    return sum(1.0 for f in critical if f is not None) / 4.0
```

**Status assignment pattern** (D-03):
```python
def _assign_status(self, score: float) -> str:
    return "auto_saved" if score >= self._settings.confidence_threshold else "pending_review"
```

**File naming pattern** (D-09) — UUID prefix prevents collisions:
```python
invoice_uuid = str(uuid.uuid4())
safe_filename = os.path.basename(filename)   # strips ../../../ path traversal
storage_filename = f"{invoice_uuid}/{safe_filename}"
image_path = self._storage.save(image_bytes, storage_filename)
```

**ExtractionResult DTO** (Claude's discretion — Pydantic BaseModel for free JSON serialization, from RESEARCH.md Pattern 3):
```python
class ExtractionResult(BaseModel):
    invoice: ExtractedInvoice
    confidence_score: float
    status: str   # "auto_saved" | "pending_review"
    image_path: str
```

**Error handling pattern** — copy structlog error style from `backend/app/main.py` lifespan pattern:
```python
try:
    ...
    log.info("extraction.complete", confidence=score, status=status)
    return ExtractionResult(...)
except Exception as exc:
    log.error("extraction.failed", error=str(exc), filename=filename)
    raise
```

---

### `backend/app/services/storage.py` (service, file-I/O)

**Analog:** `backend/app/db/session.py` (provider/dependency pattern — yields a resource abstraction)

**Imports pattern** (copy from `backend/app/db/session.py` lines 1–6, adapt):
```python
# backend/app/db/session.py lines 1-6
"""FastAPI dependency for per-request async database sessions."""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_async_session_local
```
For storage: replace with `import os` + `from typing import Protocol, runtime_checkable`.

**Protocol pattern** (from RESEARCH.md Pattern 2, research-verified):
```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class StorageBackend(Protocol):
    """Interface for invoice image storage. Phase 2: save only. delete() is Phase 4."""
    def save(self, data: bytes, filename: str) -> str:
        """Save data to storage. Returns relative path (stored in invoices.image_path)."""
        ...
```

**LocalStorageBackend implementation** — same file-I/O stdlib style as alembic/env.py uses for path operations:
```python
class LocalStorageBackend:
    """Filesystem implementation of StorageBackend.

    Storage root from settings.storage_path (STORAGE_PATH env var, default /data/invoices).
    """
    def __init__(self, root: str) -> None:
        self._root = root

    def save(self, data: bytes, filename: str) -> str:
        full_path = os.path.join(self._root, filename)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(data)
        return filename   # relative path — root excluded per D-07
```

---

### `backend/app/routers/extraction.py` (router, request-response)

**Analog:** `backend/app/routers/health.py` — exact role match

**Imports pattern** (copy from `backend/app/routers/health.py` lines 1–7):
```python
# backend/app/routers/health.py lines 1-7
"""Health endpoint — walking skeleton proof of FastAPI -> AsyncSession -> Postgres round-trip."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SenderAllowlist
from app.db.session import get_db
```
For extraction router: replace DB imports with `UploadFile`, `File`, `ExtractionService`, `ExtractionResult`.

**Router instantiation pattern** (copy from `backend/app/routers/health.py` line 9):
```python
# backend/app/routers/health.py line 9
router = APIRouter()
```

**Endpoint pattern** (copy from `backend/app/routers/health.py` lines 12–18, adapt to POST + UploadFile):
```python
# backend/app/routers/health.py lines 12-18
@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    """Walking skeleton: proves FastAPI -> AsyncSession -> Postgres round-trip works."""
    await db.execute(
        select(func.count()).select_from(SenderAllowlist)
    )
    return {"status": "ok", "db": "connected"}
```
Extraction endpoint uses `@router.post("/test")`, accepts `UploadFile`, calls `ExtractionService.extract()`, returns `ExtractionResult` — no DB write (D-06).

**Debug-gating in create_app** — copy from `backend/app/main.py` lines 35–50, add conditional block:
```python
# backend/app/main.py lines 35-47
def create_app() -> FastAPI:
    """Application factory — import routers here to avoid circular imports."""
    settings = get_settings()
    app = FastAPI(
        title="Compras Agent API",
        lifespan=lifespan,
        debug=settings.debug,
    )
    from app.routers.health import router as health_router
    app.include_router(health_router)
    return app
```
Add after `app.include_router(health_router)`:
```python
if settings.debug:
    from app.routers.extraction import router as extraction_router
    app.include_router(extraction_router, prefix="/extraction", tags=["extraction"])
```

---

### `backend/scripts/calibrate_prompt.py` (utility, batch)

**Analog:** No direct script analog in codebase. Use RESEARCH.md Pattern 8 (Anthropic SDK) + `backend/app/models/extraction.py` import conventions.

**File header pattern** — copy docstring style from `backend/app/models/extraction.py` lines 1–5:
```python
# backend/app/models/extraction.py lines 1-5
"""Pydantic extraction models — output contract for GPT-4o structured extraction.

All fields are Optional per EXT-06 (null > hallucination).
TipoComprobante uses str Enum per D-08 so Postgres stores readable labels.
use_enum_values=True required for OpenAI Structured Outputs JSON Schema in Phase 2.
"""
```

**Anthropic ground truth call pattern** (from RESEARCH.md Pattern 8, verified):
```python
import base64
import json
from pathlib import Path
from anthropic import Anthropic

def generate_ground_truth(image_path: Path) -> dict:
    client = Anthropic()  # reads ANTHROPIC_API_KEY from env
    image_data = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    response = client.messages.create(
        model="claude-opus-4-7",   # exact model string — NOT gpt-4o (D-12, circular bias)
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Extract invoice fields as JSON..."},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_data,
                    },
                },
            ],
        }],
    )
    return json.loads(response.content[0].text)
```

**Calibration loop structure** (D-13):
1. `generate_ground_truth(fixture_path)` → save to `{name}_ground_truth.json`
2. Run `ExtractionService.extract()` with current prompt
3. Field-by-field diff against ground truth JSON
4. Print differences; exit code 0 only when zero diffs

---

### `backend/tests/test_extraction.py` (test, request-response)

**Analog:** `backend/tests/test_health.py` (ASGI client + fixture pattern) + `backend/tests/test_extraction_models.py` (pure model assertions)

**File header + imports pattern** — copy from `backend/tests/test_health.py` lines 1–12:
```python
# backend/tests/test_health.py lines 1-12
"""Integration tests for GET /health endpoint.

Uses httpx.AsyncClient + ASGI transport against the in-memory aiosqlite test DB.
The session-scoped autouse env_setup fixture in conftest.py patches env vars before
collection, so `from app.main import app` is safe at module-level import.
"""
import pytest
import pytest_asyncio
import httpx

from app.db.models import SenderAllowlist
from app.db.session import get_db
```

**pytest-asyncio mark pattern** — copy from `backend/tests/test_health.py` lines 32, 42:
```python
# backend/tests/test_health.py lines 31-32
@pytest.mark.asyncio
async def test_health_empty_allowlist(client):
```

**Fixture client pattern** — copy from `backend/tests/test_health.py` lines 15–28:
```python
# backend/tests/test_health.py lines 15-28
@pytest_asyncio.fixture
async def client(db_session):
    """Function-scoped ASGI test client wired to the test DB session."""
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    app.dependency_overrides.clear()
```

**Mock OpenAI parse() pattern** (from RESEARCH.md Pattern 5, verified against openai==2.36.0 in venv):
```python
from unittest.mock import MagicMock, AsyncMock
from openai.types.chat.parsed_chat_completion import (
    ParsedChatCompletion,
    ParsedChoice,
    ParsedChatCompletionMessage,
)

def make_mock_completion(parsed_invoice: ExtractedInvoice) -> MagicMock:
    mock_message = MagicMock(spec=ParsedChatCompletionMessage)
    mock_message.parsed = parsed_invoice
    mock_message.refusal = None
    mock_choice = MagicMock(spec=ParsedChoice)
    mock_choice.message = mock_message
    mock_completion = MagicMock(spec=ParsedChatCompletion)
    mock_completion.choices = [mock_choice]
    return mock_completion
```

**Integration test marker pattern** (D-16) — new pattern, no existing analog:
```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_extraction():
    """Live GPT-4o integration test — skipped by default. Run with: pytest -m integration"""
    ...
```
Register `integration` marker in `backend/pyproject.toml` under `[tool.pytest.ini_options]`:
```toml
markers = ["integration: marks tests as live API integration tests (deselect with '-m not integration')"]
```

**conftest.py reuse** — `db_session` and `env_setup` fixtures from `backend/tests/conftest.py` are inherited automatically. No need to redefine.

---

### `backend/app/config.py` (config, MODIFY)

**Analog:** self — modify existing file

**Current Settings class** (`backend/app/config.py` lines 6–23) — add `storage_path` field after `confidence_threshold`:
```python
# backend/app/config.py lines 19-23 (existing)
    # Optional with defaults
    debug: bool = False
    log_level: str = "INFO"
    confidence_threshold: float = 0.85
```
Add (D-08):
```python
    storage_path: str = "/data/invoices"
```
**No other changes** — `get_settings()` lru_cache singleton pattern at lines 26–28 is unchanged.

---

### `backend/app/main.py` (factory, MODIFY)

**Analog:** self — modify existing file

**Existing `create_app()` pattern** (`backend/app/main.py` lines 35–50) is the direct template. Insert conditional router block after `app.include_router(health_router)` at line 46:
```python
# Insert after line 46:
    if settings.debug:
        from app.routers.extraction import router as extraction_router
        app.include_router(extraction_router, prefix="/extraction", tags=["extraction"])
```
Pattern matches the existing lazy import-inside-factory convention (lines 44–45):
```python
# backend/app/main.py lines 44-46
    from app.routers.health import router as health_router
    app.include_router(health_router)
```

---

### `requirements-dev.txt` (config, MODIFY)

**Analog:** self — modify existing file

**Current content** (`backend/requirements-dev.txt` lines 1–5):
```
-r requirements.txt
pytest
pytest-asyncio
aiosqlite
httpx
```
Add `anthropic` (D-14 — dev/scripts only, already installed at 0.76.0):
```
anthropic
```

---

## Shared Patterns

### structlog Logging
**Source:** `backend/app/main.py` lines 16, 22–23
**Apply to:** `extraction.py` service, `storage.py` (optional)
```python
import structlog
log = structlog.get_logger()          # module-level or __init__
log.info("event.name", key=value)     # bind context at call time
log.error("event.failed", error=str(exc))
```
**Rule:** Never `log.bind()` at class init. Always bind inside the method where data is available.

### Settings Dependency Injection
**Source:** `backend/app/config.py` lines 26–28; `backend/app/routers/health.py` lines 3–5
**Apply to:** `extraction.py` service (constructor injection), `extraction.py` router (Depends)
```python
from app.config import get_settings
# In router:
settings: Settings = Depends(get_settings)
# In service constructor:
def __init__(self, ..., settings: Settings) -> None:
```

### AsyncSession DB Access
**Source:** `backend/app/db/session.py` lines 9–17; `backend/app/routers/health.py` lines 12–18
**Apply to:** Phase 3 DB writes (not Phase 2 `/extraction/test` — D-06 prohibits DB writes from debug endpoint)
```python
# backend/app/routers/health.py lines 12-13
@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
```

### Optional[T] = None Field Convention
**Source:** `backend/app/models/extraction.py` lines 27–59
**Apply to:** `ExtractionResult` model, any new Pydantic models in Phase 2
```python
# backend/app/models/extraction.py lines 30-38
from typing import List, Optional
from pydantic import BaseModel, ConfigDict

class LineItem(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    descripcion: Optional[str] = None
    codigo_sku: Optional[str] = None
    ...
```

### Test env_setup + db_session Fixtures
**Source:** `backend/tests/conftest.py` lines 19–64
**Apply to:** `backend/tests/test_extraction.py` — inherit automatically, no redefinition needed
```python
# Fixtures available to all tests via conftest.py:
# - env_setup (session, autouse) — patches all required env vars + clears lru_cache
# - async_engine (function) — in-memory SQLite with full schema
# - db_session (function) — AsyncSession bound to test engine
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `backend/scripts/calibrate_prompt.py` | utility | batch | No script analogs exist in codebase. Use RESEARCH.md Pattern 8 (Anthropic SDK ground truth call) + RESEARCH.md Pattern 1 (GPT-4o extraction call) as primary references. |

---

## Metadata

**Analog search scope:** `backend/app/`, `backend/tests/`, `backend/alembic/`
**Files scanned:** 12 Python files (full codebase at Phase 1 state)
**Pattern extraction date:** 2026-05-13
