# Phase 02: Extraction Pipeline - Research

**Researched:** 2026-05-13
**Domain:** OpenAI structured extraction, async service layer, filesystem storage abstraction, pytest mocking
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Critical fields for confidence scoring: `tipo_comprobante`, `numero_documento`, `proveedor`, `fecha`. Score = non-null count / 4 (range 0.0–1.0).
- **D-02:** Cross-field consistency checks skipped in Phase 2. Base score only.
- **D-03:** Confidence threshold from `settings.confidence_threshold` (default 0.85). Score ≥ 0.85 → `status=auto_saved`. Score < 0.85 → `status=pending_review`. Always save — never reject.
- **D-04:** `ExtractionService.extract(image_bytes: bytes, filename: str) -> ExtractionResult`
- **D-05:** `/extraction/test` endpoint registered only when `settings.debug is True`.
- **D-06:** `POST /extraction/test` returns full extraction result (no DB persistence — developer surface only).
- **D-07:** `StorageBackend.save(data: bytes, filename: str) -> str` (returns relative path).
- **D-08:** Storage root via `STORAGE_PATH` env var in `Settings` (default: `/data/invoices`).
- **D-09:** File naming: `{invoice_uuid}/{original_filename}`.
- **D-10:** Initial GPT-4o prompt is minimal — let schema do the heavy lifting.
- **D-11:** Prompt calibration is a Phase 2 deliverable. Phase not done until calibration passes on all fixtures.
- **D-12:** Ground truth via Claude Opus 4.7 (`claude-opus-4-7`), NOT GPT-4o.
- **D-13:** Calibration loop: Claude Opus 4.7 → ground truth JSON → GPT-4o extraction → field diff → prompt adjustment → repeat.
- **D-14:** `anthropic` SDK is dev/scripts-only (`requirements-dev.txt` or `scripts/requirements.txt`).
- **D-15:** Mocked tests cover all service logic.
- **D-16:** One `@pytest.mark.integration` live test uses real fixture image + GPT-4o. Skipped by default.
- **D-17:** Fixtures in `backend/tests/fixtures/`. Real invoice images + ground truth JSON committed.

### Claude's Discretion

- Internal structure of `ExtractionResult` return type (Pydantic model preferred).
- `StorageBackend` abstraction mechanism: Protocol vs ABC.
- Exact system prompt text — start minimal.
- Error types raised by `ExtractionService` on failure.

### Deferred Ideas (OUT OF SCOPE)

- Cross-field consistency checks in confidence scoring.
- `StorageBackend.delete()` — Phase 4.
- Full pipeline endpoint with DB persistence — Phase 3 scope.
- CUIT mod-11 validation (EXT-V2-02).
- AFIP QR code decoding (EXT-V2-01).

</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EXT-01 | Extract line-item fields per product: descripción, SKU, bultos, unidades_por_bulto, precio_unitario_sin_iva, descuento_% | `LineItem` model already defined with all fields Optional. GPT-4o structured output with `ExtractedInvoice` as `response_format` covers this. |
| EXT-02 | Extract tax fields per line item: IVA rate (0%, 10.5%, 21%) and percepciones/IIBB | `LineItem.iva_rate` and `LineItem.percepciones_iibb` fields in place. |
| EXT-03 | Extract document-level fields: numero_documento, proveedor, fecha | `ExtractedInvoice` top-level fields cover this. |
| EXT-04 | Extract CUIT proveedor and CAE + fecha_vencimiento_cae when visible (nullable) | All Optional fields on `ExtractedInvoice`. |
| EXT-05 | Handle 3 document types without failing: Factura A, Remito, Lista informal | `TipoComprobante` enum includes REMITO, LISTA_INFORMAL, UNKNOWN. All nullable fields prevent crashes. |
| EXT-06 | All extracted fields nullable — null > hallucination | `Optional[T] = None` on all fields already enforced. Service must gate on `message.refusal`. |
| EXT-07 | Per-extraction confidence score (0.0–1.0) | D-01 formula: `sum(1 for f in [tipo, numero, proveedor, fecha] if f is not None) / 4` |
| VAL-04 | Original image stored on local filesystem via StorageBackend, linked to DB record | `LocalStorageBackend.save()` returns relative path → stored in `invoices.image_path`. |
| VAL-05 | Processing errors logged with WhatsApp message ID (or equivalent ref) | `structlog` binds message reference context; `ExtractionService` catches and logs failures. |

</phase_requirements>

---

## Summary

Phase 2 builds the extraction pipeline core: `ExtractionService`, `StorageBackend`/`LocalStorageBackend`, a debug test endpoint, and a calibration script. All infrastructure is in place from Phase 1 — the DB schema, Pydantic models, and test harness are ready to use directly.

The central technical challenge is correctly combining GPT-4o's `client.chat.completions.parse()` (Structured Outputs) with vision (base64-encoded image in `image_url` content block). These are two separate API features that must be composed in a single call. The `parse()` method is available on `AsyncOpenAI` as `await client.chat.completions.parse(...)` and returns a `ParsedChatCompletion[T]` where `message.parsed` is the typed Pydantic model instance.

Testing strategy uses `MagicMock(spec=ParsedChatCompletion)` for mocking the parse() response — verified to work in-tree with the installed `openai==2.36.0`. The `StorageBackend` abstraction uses `typing.Protocol` (the modern, conventional approach for duck-typed service interfaces). The calibration script uses the `anthropic` SDK (already installed at 0.76.0) with the model string `claude-opus-4-7`.

**Primary recommendation:** Build `ExtractionService` with `AsyncOpenAI` injected at construction time (not imported globally), use `Protocol` for `StorageBackend`, and define `ExtractionResult` as a Pydantic `BaseModel` for clean serialization to the debug endpoint.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| GPT-4o extraction call | API / Backend (service layer) | — | Network I/O + secrets; never in router or client |
| Image base64 encoding | API / Backend (service layer) | — | Pre-processing before API call |
| Confidence score computation | API / Backend (service layer) | — | Pure Python logic on `ExtractedInvoice` fields |
| File storage (image) | API / Backend (service layer) | Local filesystem | `StorageBackend.save()` writes to mounted volume |
| DB write (Invoice + line items) | API / Backend (service layer via session) | — | Session injected; service layer owns persistence |
| Debug `/extraction/test` endpoint | API / Backend (router) | — | Thin wrapper: receives bytes, calls service, returns result |
| Calibration script | Scripts (dev-only) | — | Offline, not part of FastAPI app |
| Ground truth generation | Scripts (dev-only) | Anthropic API | `calibrate_prompt.py` uses Anthropic SDK |

---

## Standard Stack

### Core (already installed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| openai | 2.36.0 | GPT-4o extraction via `chat.completions.parse()` | Pinned in `requirements.txt` [VERIFIED: requirements.txt] |
| pydantic | 2.13.4 | `ExtractedInvoice` model, `ExtractionResult` return type | Pinned; v2 required by FastAPI 0.136.1 [VERIFIED: requirements.txt] |
| sqlalchemy | 2.0.49 | ORM for `Invoice` / `InvoiceLineItem` writes | Pinned; 2.0 typed mapping already in use [VERIFIED: requirements.txt] |
| structlog | 25.5.0 | Structured JSON logging in service classes | Pinned; already configured in `main.py` [VERIFIED: requirements.txt] |

### Dev/Scripts Only (add to requirements-dev.txt)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| anthropic | 0.76.0 | Claude Opus 4.7 ground truth generation | `calibrate_prompt.py` only; already installed [VERIFIED: pip show] |

### Already in requirements-dev.txt (confirmed present)
| Library | Version | Purpose |
|---------|---------|---------|
| pytest | 9.0.3 | Test runner [VERIFIED: in venv] |
| pytest-asyncio | 1.3.0 | Async test support [VERIFIED: in venv] |
| aiosqlite | latest | In-memory SQLite for tests [VERIFIED: requirements-dev.txt] |
| httpx | latest | Async HTTP client for TestClient [VERIFIED: requirements-dev.txt] |

**Installation (nothing new for main requirements):**
```bash
# anthropic is already installed; ensure it's listed in requirements-dev.txt
# No new packages needed in requirements.txt
```

---

## Architecture Patterns

### System Architecture Diagram

```
[test endpoint / Phase 3 WhatsApp handler]
          |
          | image_bytes: bytes, filename: str
          v
   ExtractionService.extract()
          |
          +---> [1] StorageBackend.save(image_bytes, path)
          |          └── returns relative_path (str)
          |
          +---> [2] base64.b64encode(image_bytes)
          |
          +---> [3] AsyncOpenAI.chat.completions.parse(
          |              model="gpt-4o",
          |              messages=[system_prompt, user_vision_message],
          |              response_format=ExtractedInvoice
          |          )
          |          └── ParsedChatCompletion[ExtractedInvoice]
          |               ├── message.parsed  → ExtractedInvoice (success)
          |               └── message.refusal → None / error string
          |
          +---> [4] compute_confidence(extracted_invoice)
          |          └── non_null_critical / 4
          |
          +---> [5] assign_status(confidence, threshold)
          |          └── "auto_saved" or "pending_review"
          |
          v
   ExtractionResult(
       invoice=ExtractedInvoice,
       confidence_score=float,
       status=str,
       image_path=str
   )
          |
          v
   [Router: return JSON response]
   [Phase 3: DB write via AsyncSession]
```

### Recommended Project Structure
```
backend/
├── app/
│   ├── models/
│   │   └── extraction.py        # ExtractedInvoice, LineItem (Phase 1, DO NOT MODIFY)
│   ├── services/
│   │   ├── __init__.py          # empty (already exists)
│   │   ├── extraction.py        # ExtractionService
│   │   └── storage.py           # StorageBackend Protocol + LocalStorageBackend
│   └── routers/
│       └── extraction.py        # POST /extraction/test (debug-only)
├── scripts/
│   ├── calibrate_prompt.py      # Calibration script (uses anthropic SDK)
│   └── requirements.txt         # scripts-only deps (anthropic)
└── tests/
    ├── fixtures/
    │   ├── factura_a.jpg         # Real invoice image
    │   └── factura_a_ground_truth.json
    ├── test_extraction_service.py
    └── test_storage.py
```

### Pattern 1: AsyncOpenAI `parse()` with Vision (Base64)

The key insight: `chat.completions.parse()` and vision (image content block) are composed in the same call. The `image_url` content type accepts `data:image/jpeg;base64,{b64}` URIs.

```python
# Source: Context7 /openai/openai-python + https://developers.openai.com/api/docs/guides/images-vision
import base64
from openai import AsyncOpenAI
from app.models.extraction import ExtractedInvoice

async def _call_gpt4o(client: AsyncOpenAI, image_bytes: bytes, prompt: str) -> ExtractedInvoice | None:
    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    completion = await client.chat.completions.parse(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract all invoice fields from this image."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"},
                    },
                ],
            },
        ],
        response_format=ExtractedInvoice,
    )
    message = completion.choices[0].message
    if message.refusal:
        return None  # Model refused — treat as extraction failure
    return message.parsed
```

**Critical notes:**
- `model="gpt-4o"` (not `"gpt-4o-2024-08-06"`) — the alias resolves to the latest compliant snapshot [CITED: CLAUDE.md Key Architectural Decisions]
- `image_url` content type is `{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}` — NOT `input_image` (that is the newer Responses API) [VERIFIED: official docs + chat.completions tested pattern]
- `use_enum_values=True` on `ExtractedInvoice` ensures `TipoComprobante` serializes to string, compatible with OpenAI JSON Schema generation [VERIFIED: extraction.py]
- Check `message.refusal` BEFORE accessing `message.parsed`. `parsed` may be `None` on refusal without raising [CITED: Context7 /openai/openai-python helpers.md]

### Pattern 2: StorageBackend as typing.Protocol

`Protocol` is the conventional modern approach for a single-implementation service interface. It enables structural subtyping (duck typing) without forcing `LocalStorageBackend` to inherit from anything — cleaner, zero coupling, mypy-compatible.

```python
# Source: PEP 544 + mypy docs [CITED: https://typing.python.org/en/latest/spec/protocol.html]
from typing import Protocol, runtime_checkable

@runtime_checkable
class StorageBackend(Protocol):
    """Interface for invoice image storage."""
    def save(self, data: bytes, filename: str) -> str:
        """Save data to storage. Returns relative path."""
        ...

class LocalStorageBackend:
    """Filesystem implementation of StorageBackend."""
    def __init__(self, root: str) -> None:
        self._root = root

    def save(self, data: bytes, filename: str) -> str:
        path = os.path.join(self._root, filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return filename  # relative path — root excluded
```

**Why Protocol over ABC:**
- No forced inheritance on `LocalStorageBackend` [CITED: PEP 544]
- `@runtime_checkable` allows `isinstance(backend, StorageBackend)` in tests
- Matches established Python service-layer pattern (cf. FastAPI's own `Depends` ecosystem)

### Pattern 3: ExtractionResult as Pydantic BaseModel

Claude's discretion: `ExtractionResult` should be a Pydantic `BaseModel`. This enables direct JSON serialization in the debug endpoint without a manual `dict()` call.

```python
# Source: [ASSUMED] — Pydantic BaseModel as DTO is the standard FastAPI pattern
from pydantic import BaseModel
from app.models.extraction import ExtractedInvoice

class ExtractionResult(BaseModel):
    invoice: ExtractedInvoice
    confidence_score: float
    status: str  # "auto_saved" | "pending_review"
    image_path: str
```

### Pattern 4: ExtractionService constructor with injected dependencies

```python
# Source: [ASSUMED] — constructor injection is standard; matches get_settings() DI pattern in project
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

    async def extract(self, image_bytes: bytes, filename: str) -> ExtractionResult:
        log = self._log.bind(filename=filename)
        ...
```

### Pattern 5: pytest mock for AsyncOpenAI `parse()`

Verified in-tree with `openai==2.36.0` and the project's `ExtractedInvoice` model:

```python
# Source: [VERIFIED: manually tested in project venv, 2026-05-13]
from unittest.mock import MagicMock, AsyncMock
from openai.types.chat.parsed_chat_completion import (
    ParsedChatCompletion,
    ParsedChoice,
    ParsedChatCompletionMessage,
)
from app.models.extraction import ExtractedInvoice

def make_mock_completion(parsed_invoice: ExtractedInvoice) -> MagicMock:
    mock_message = MagicMock(spec=ParsedChatCompletionMessage)
    mock_message.parsed = parsed_invoice
    mock_message.refusal = None

    mock_choice = MagicMock(spec=ParsedChoice)
    mock_choice.message = mock_message

    mock_completion = MagicMock(spec=ParsedChatCompletion)
    mock_completion.choices = [mock_choice]
    return mock_completion

# In a test:
async def test_extract_factura_a(db_session):
    mock_openai = MagicMock()
    mock_openai.chat.completions.parse = AsyncMock(
        return_value=make_mock_completion(
            ExtractedInvoice(
                tipo_comprobante="FACTURA_A",
                proveedor="Test SA",
                numero_documento="0001-00000123",
                fecha="2026-01-15",
            )
        )
    )
    mock_storage = MagicMock(spec=StorageBackend)
    mock_storage.save.return_value = "some-uuid/factura.jpg"
    ...
```

### Pattern 6: structlog in service classes

```python
# Source: [CITED: https://www.structlog.org/en/stable/contextvars.html]
import structlog

class ExtractionService:
    def __init__(self, ...):
        self._log = structlog.get_logger()  # Do NOT bind at class level

    async def extract(self, image_bytes: bytes, filename: str) -> ExtractionResult:
        log = self._log.bind(filename=filename)  # Bind at call time
        log.info("extraction.start")
        try:
            ...
            log.info("extraction.complete", confidence=score, status=status)
        except Exception as exc:
            log.error("extraction.failed", error=str(exc))
            raise
```

**Rule:** Never call `.bind()` at `__init__` time — structlog loggers are lazy proxies; binding must happen at call time when data is available [CITED: structlog docs, structlog.org/en/stable].

### Pattern 7: Conditional router registration (debug-gating)

Extends the existing `create_app()` factory pattern:

```python
# Source: [VERIFIED: backend/app/main.py — existing pattern]
def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Compras Agent API", lifespan=lifespan, debug=settings.debug)
    from app.routers.health import router as health_router
    app.include_router(health_router)

    if settings.debug:
        from app.routers.extraction import router as extraction_router
        app.include_router(extraction_router, prefix="/extraction", tags=["extraction"])

    return app
```

### Pattern 8: Anthropic SDK for ground truth generation (calibrate_prompt.py)

```python
# Source: Context7 /anthropics/anthropic-sdk-python + [VERIFIED: anthropic==0.76.0 installed]
import base64
from pathlib import Path
from anthropic import Anthropic

client = Anthropic()  # Reads ANTHROPIC_API_KEY from env

image_data = base64.b64encode(Path("tests/fixtures/factura_a.jpg").read_bytes()).decode("utf-8")

response = client.messages.create(
    model="claude-opus-4-7",  # Exact model string [VERIFIED: platform.claude.com/docs]
    max_tokens=4096,
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": "Extract all invoice fields as JSON matching this schema: ..."},
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
ground_truth = response.content[0].text  # Raw JSON string to parse
```

### Anti-Patterns to Avoid

- **Using `response_format={"type": "json_object"}` instead of `.parse()`:** Loses automatic Pydantic deserialization and type safety. Always use `.parse()` with a Pydantic model. [CITED: CLAUDE.md Key Architectural Decisions]
- **Accessing `message.parsed` without checking `message.refusal`:** If the model refuses, `message.parsed` is `None` and `message.refusal` is a string. Accessing `.parsed` directly will silently propagate `None`. [CITED: Context7 /openai/openai-python helpers.md]
- **Using `gpt-4o-mini` for extraction:** Accuracy on dense Argentine invoice text is materially worse. [CITED: CLAUDE.md]
- **Binding structlog context at `__init__` time:** Will capture pre-configuration defaults; always bind in method scope. [CITED: structlog docs]
- **Using `responses.create()` with `input_image` content type for chat.completions calls:** The `responses` API uses `input_image`; `chat.completions` uses `image_url`. These are different APIs. [VERIFIED: official docs + in-tree verification]
- **Writing to DB from the debug endpoint directly:** The `/extraction/test` endpoint returns JSON only (D-06). DB persistence is Phase 3. The endpoint must NOT call session.add().
- **Creating `AsyncOpenAI` client at module import time:** Reads `OPENAI_API_KEY` immediately, breaking tests. Inject via constructor or FastAPI `Depends`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON Schema from Pydantic model | Custom schema serialization | `client.chat.completions.parse(response_format=ExtractedInvoice)` | SDK auto-converts Pydantic to JSON Schema + deserializes response |
| HMAC webhook validation | Custom SHA256 | pywa (Phase 3) | Already covers this; Phase 2 has no webhook |
| Structured output retry on refusal | Custom retry loop | Gate on `message.refusal` and raise | One check is sufficient; retrying rarely helps on refusals |
| Concurrent image I/O | `asyncio.gather` over many files | Standard `aiofiles` or sync `open()` in threadpool | At < 20 invoices/day, sync file I/O is fine; don't over-engineer |
| Directory creation | Recursive mkdir logic | `os.makedirs(path, exist_ok=True)` | One-liner; stdlib |

---

## Common Pitfalls

### Pitfall 1: `image_url` vs `input_image` content type
**What goes wrong:** Developer copies base64 example from OpenAI README (uses `responses.create()` with `input_image`) into a `chat.completions.parse()` call. The content type key is different.
**Why it happens:** OpenAI has two APIs — the newer `responses` API uses `input_image`; `chat.completions` uses `image_url`.
**How to avoid:** For `chat.completions.parse()`, content type is `{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}`.
**Warning signs:** `400 Bad Request` or `Invalid content type` from OpenAI API.

### Pitfall 2: `message.parsed` is None without checking refusal
**What goes wrong:** Service code accesses `completion.choices[0].message.parsed.tipo_comprobante` directly. When GPT-4o refuses (e.g., unrecognizable image), `parsed` is `None` and raises `AttributeError`.
**Why it happens:** `.parse()` does not raise on refusal — it returns a completion with `refusal` set.
**How to avoid:** Always check `if message.refusal: raise ExtractionError(...)` before accessing `message.parsed`.
**Warning signs:** Sporadic `AttributeError: 'NoneType' object has no attribute 'tipo_comprobante'` in production.

### Pitfall 3: AsyncOpenAI constructed at module level
**What goes wrong:** `client = AsyncOpenAI()` at module top level. Test session patches `OPENAI_API_KEY`, but the client was already instantiated with the real key (or no key), causing test failures.
**Why it happens:** `AsyncOpenAI()` reads env vars immediately at construction.
**How to avoid:** Instantiate inside `create_app()` or inject via FastAPI `Depends`. Use `AsyncOpenAI(api_key=settings.openai_api_key)`.
**Warning signs:** Tests fail with `AuthenticationError` even with monkeypatched env vars.

### Pitfall 4: `use_enum_values=True` and OpenAI JSON Schema
**What goes wrong:** Without `use_enum_values=True` on `ExtractedInvoice`, Pydantic v2 serializes `TipoComprobante` as the enum object. OpenAI Structured Outputs converts this to a non-string schema. The model may return the enum label correctly but deserialization fails.
**Why it happens:** Pydantic v2's JSON Schema generation for enums differs from v1.
**How to avoid:** `ExtractedInvoice` already has `model_config = ConfigDict(use_enum_values=True)` — do not remove it.
**Warning signs:** `ValidationError` on deserialization despite correct JSON from GPT-4o.

### Pitfall 5: SQLAlchemy `updated_at` not auto-updating
**What goes wrong:** `Invoice.updated_at` uses `onupdate=func.now()` but this only fires on UPDATE statements issued by SQLAlchemy's ORM — not on raw SQL. Phase 2 writes are ORM writes (session.add), so this is safe.
**Why it happens:** SQLAlchemy `onupdate` applies to ORM-level updates only.
**How to avoid:** Always use `session.add(invoice)` + `await session.commit()` for writes. Never bypass ORM for invoice records.

### Pitfall 6: File path collision with D-09 naming
**What goes wrong:** Two invoices from the same proveedor with same filename (e.g., both named `photo.jpg`) overwrite each other.
**Why it happens:** `original_filename` is not unique across invoices.
**How to avoid:** D-09 mandates `{invoice_uuid}/{original_filename}`. The `invoice_uuid` prefix makes the path globally unique. Service must generate the UUID before calling `StorageBackend.save()`.

### Pitfall 7: structlog binding at class scope
**What goes wrong:** `self._log = structlog.get_logger().bind(service="extraction")` in `__init__`. Structlog is called before its configuration runs, binding defaults.
**Why it happens:** `structlog.get_logger()` returns a lazy proxy, but `.bind()` captures the current (unconfigured) state.
**How to avoid:** Call `structlog.get_logger()` in `__init__` (lazy proxy is fine), but call `.bind()` only within methods.

---

## Code Examples

### Combined parse() + vision call (verified in-tree pattern)
```python
# Source: [VERIFIED: in-tree test 2026-05-13 + CITED: developers.openai.com/api/docs/guides/images-vision]
import base64
from openai import AsyncOpenAI
from app.models.extraction import ExtractedInvoice

async def call_extraction(
    client: AsyncOpenAI,
    image_bytes: bytes,
    system_prompt: str,
) -> tuple[ExtractedInvoice | None, str | None]:
    """Returns (parsed_invoice, refusal_reason). Exactly one will be non-None."""
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    completion = await client.chat.completions.parse(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
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
    return (msg.parsed, msg.refusal)
```

### Confidence score computation (D-01)
```python
# Source: [VERIFIED: from D-01 in 02-CONTEXT.md]
def compute_confidence(invoice: ExtractedInvoice) -> float:
    critical = [
        invoice.tipo_comprobante,
        invoice.numero_documento,
        invoice.proveedor,
        invoice.fecha,
    ]
    return sum(1.0 for f in critical if f is not None) / 4.0
```

### Mock construction for pytest (verified in-tree)
```python
# Source: [VERIFIED: manually verified against openai==2.36.0 in project venv, 2026-05-13]
from unittest.mock import MagicMock, AsyncMock
from openai.types.chat.parsed_chat_completion import (
    ParsedChatCompletion, ParsedChoice, ParsedChatCompletionMessage
)

def make_mock_parse_result(invoice: ExtractedInvoice) -> MagicMock:
    msg = MagicMock(spec=ParsedChatCompletionMessage)
    msg.parsed = invoice
    msg.refusal = None
    choice = MagicMock(spec=ParsedChoice)
    choice.message = msg
    completion = MagicMock(spec=ParsedChatCompletion)
    completion.choices = [choice]
    return completion
```

### Anthropic ground truth call
```python
# Source: Context7 /anthropics/anthropic-sdk-python [VERIFIED: anthropic==0.76.0 installed]
import base64, json
from pathlib import Path
from anthropic import Anthropic

def generate_ground_truth(image_path: Path, schema_description: str) -> dict:
    client = Anthropic()  # reads ANTHROPIC_API_KEY
    image_data = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": f"Extract invoice fields as JSON. Schema: {schema_description}"},
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

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `response_format={"type": "json_object"}` | `client.chat.completions.parse(response_format=PydanticModel)` | openai-python v1.40+ (stable v2.x) | Auto-deserialization, no manual JSON parse |
| `openai.ChatCompletion.create()` module-level function | `AsyncOpenAI().chat.completions.parse()` on client instance | openai-python v1.0 | Client is instantiated, injectable, testable |
| `ABC` for service interfaces | `typing.Protocol` with `@runtime_checkable` | Python 3.8 / PEP 544 | Structural typing, no forced inheritance |
| `responses.create()` (Responses API) | `chat.completions.parse()` (Chat Completions API) | Still separate APIs in 2026 | Different content type keys for images |

**Note:** The `responses` API (`client.responses.create()`) is the newer OpenAI API surface used in README examples. Phase 2 uses `chat.completions.parse()` because Structured Outputs + vision is confirmed working there. The `responses` API does support structured outputs but the `parse()` convenience method is specifically documented for `chat.completions`. [ASSUMED - responses API structured outputs not verified for parity; sticking with chat.completions which is confirmed]

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `ExtractionResult` as Pydantic `BaseModel` is the right DTO pattern | Architecture Patterns | Low — could use dataclass; Pydantic just adds free JSON serialization for debug endpoint |
| A2 | `client.responses.create()` Structured Outputs has same parity as `chat.completions.parse()` | State of the Art | Low — Phase 2 uses `chat.completions.parse()` which is verified; no migration risk |
| A3 | JPEG MIME type (`image/jpeg`) is appropriate for fixture images | Code Examples | Low — `image/png` also accepted; detection can be done with `imghdr` or `filetype` lib if needed |
| A4 | Sync `open()` for `LocalStorageBackend.save()` is acceptable at < 20 invoices/day | Don't Hand-Roll | Low — at this volume, sync I/O blocking the thread pool is negligible |

---

## Open Questions

1. **MIME type detection for StorageBackend**
   - What we know: Images arrive as raw bytes; `image/jpeg` is the most common format for phone photos.
   - What's unclear: Should `LocalStorageBackend.save()` detect MIME type from bytes, or trust the `filename` extension?
   - Recommendation: Trust filename extension for Phase 2. Add `filetype` detection in a future hardening pass.

2. **Multi-page PDF invoice support**
   - What we know: `EXT-05` mentions 3 document types, all image-based. PDFs not explicitly mentioned in Phase 2 scope.
   - What's unclear: Phase 2 input is always `bytes` from a `filename` parameter — PDF bytes would be valid input.
   - Recommendation: Phase 2 service accepts any bytes; PDF handling can be added when WhatsApp handler identifies a PDF attachment in Phase 3.

3. **`scripts/requirements.txt` vs `requirements-dev.txt` for anthropic**
   - What we know: D-14 says anthropic is dev/scripts-only. It is already installed (0.76.0).
   - What's unclear: Whether to add it to the existing `requirements-dev.txt` or create `scripts/requirements.txt`.
   - Recommendation: Add to `requirements-dev.txt` for simplicity (only one dev requirements file to manage). Create `scripts/requirements.txt` only if there's a reason to isolate script deps.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Runtime | ✓ | 3.12.3 | — |
| openai SDK | ExtractionService | ✓ | 2.36.0 | — |
| anthropic SDK | calibrate_prompt.py | ✓ | 0.76.0 | — |
| pytest | Test suite | ✓ | 9.0.3 | — |
| pytest-asyncio | Async tests | ✓ | 1.3.0 | — |
| aiosqlite | In-memory test DB | ✓ | (in venv) | — |
| OPENAI_API_KEY | Integration test only | ✓ (assumed env) | — | Skip via `@pytest.mark.integration` |
| ANTHROPIC_API_KEY | calibrate_prompt.py only | Not verified | — | Script fails gracefully with AuthenticationError |

**Missing dependencies with no fallback:** None — all required for Phase 2 execution are present.

**Missing dependencies with fallback:** `ANTHROPIC_API_KEY` — calibration script requires it but can be skipped until the key is available. The script is a Phase 2 deliverable but does not block the service implementation.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 + pytest-asyncio 1.3.0 |
| Config file | `backend/pyproject.toml` (`asyncio_mode = "auto"`) |
| Quick run command | `python -m pytest tests/test_extraction_service.py tests/test_storage.py -x -q` |
| Full suite command | `python -m pytest tests/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| EXT-01 | Line items extracted with all fields or None | unit (mocked) | `pytest tests/test_extraction_service.py::test_line_items_extracted -x` | ❌ Wave 0 |
| EXT-02 | IVA rate and percepciones extracted correctly | unit (mocked) | `pytest tests/test_extraction_service.py::test_tax_fields -x` | ❌ Wave 0 |
| EXT-03 | Document-level fields (numero, proveedor, fecha) | unit (mocked) | `pytest tests/test_extraction_service.py::test_document_fields -x` | ❌ Wave 0 |
| EXT-04 | CUIT and CAE nullable, no hallucination | unit (mocked) | `pytest tests/test_extraction_service.py::test_cuit_cae_nullable -x` | ❌ Wave 0 |
| EXT-05 | Remito/lista informal does not crash | unit (mocked) | `pytest tests/test_extraction_service.py::test_remito_no_crash -x` | ❌ Wave 0 |
| EXT-06 | All fields Optional; refusal returns None fields | unit (mocked) | `pytest tests/test_extraction_service.py::test_refusal_handling -x` | ❌ Wave 0 |
| EXT-07 | Confidence score computed correctly | unit (pure) | `pytest tests/test_extraction_service.py::test_confidence_score -x` | ❌ Wave 0 |
| EXT-07 | Status auto_saved / pending_review assignment | unit (pure) | `pytest tests/test_extraction_service.py::test_status_assignment -x` | ❌ Wave 0 |
| VAL-04 | StorageBackend.save() called; image_path in result | unit (mocked) | `pytest tests/test_extraction_service.py::test_storage_called -x` | ❌ Wave 0 |
| VAL-05 | Extraction errors logged with context | unit (mocked) | `pytest tests/test_extraction_service.py::test_error_logging -x` | ❌ Wave 0 |
| EXT-01..07 | Live GPT-4o integration on real fixture | integration | `pytest tests/test_extraction_service.py -m integration` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_extraction_service.py tests/test_storage.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -q`
- **Phase gate:** Full suite green (11 existing + new tests) before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_extraction_service.py` — covers EXT-01 through VAL-05
- [ ] `tests/test_storage.py` — covers `LocalStorageBackend.save()`, path construction, directory creation
- [ ] `tests/fixtures/` directory — real invoice images + ground truth JSON
- [ ] `tests/conftest.py` update — add `@pytest.mark.integration` marker registration to `pyproject.toml`

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No user auth in Phase 2 (debug endpoint, no auth) |
| V3 Session Management | No | No sessions |
| V4 Access Control | Partial | Debug endpoint gated on `settings.debug` — not exposed in production |
| V5 Input Validation | Yes | `ExtractedInvoice` Pydantic validation; `image_bytes` type-checked by signature |
| V6 Cryptography | No | No crypto in Phase 2 |

### Known Threat Patterns for this Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Prompt injection via invoice image | Tampering | Structured Outputs (JSON Schema constraint) limits GPT-4o output to defined schema fields — cannot inject arbitrary text |
| Path traversal in `filename` parameter | Tampering | `LocalStorageBackend.save()` must sanitize `filename` — use `os.path.basename()` to strip directory components |
| OpenAI API key exposure | Info Disclosure | Key in `settings.openai_api_key` from env; never logged (structlog bind excludes secrets) |
| Large image DoS | DoS | Phase 2 has no size limit — acceptable for developer-only debug endpoint; Phase 3 WhatsApp handler applies limits |

**Path traversal mitigation (critical):**
```python
# Source: [ASSUMED] — stdlib best practice
import os
safe_filename = os.path.basename(filename)  # strips any ../../../ prefix
path = f"{invoice_uuid}/{safe_filename}"
```

---

## Sources

### Primary (HIGH confidence)
- Context7 `/openai/openai-python` — `parse()` API, `ParsedChatCompletion` type structure, `AsyncMock` pattern
- Context7 `/anthropics/anthropic-sdk-python` — vision message structure, base64 image content block
- `backend/app/models/extraction.py` — `ExtractedInvoice`, `TipoComprobante`, `LineItem` (Phase 1 output, in-tree)
- `backend/app/db/models.py` — `Invoice`, `InvoiceLineItem` ORM schema (Phase 1 output, in-tree)
- `backend/app/main.py` — `create_app()` conditional router pattern (in-tree)
- `backend/tests/conftest.py` — established `AsyncSession` test fixture pattern (in-tree)
- `backend/requirements.txt` + `requirements-dev.txt` — pinned versions (in-tree)
- https://developers.openai.com/api/docs/guides/images-vision — `image_url` content type for `chat.completions`
- https://platform.claude.com/docs/en/about-claude/models/overview — `claude-opus-4-7` model string

### Secondary (MEDIUM confidence)
- https://typing.python.org/en/latest/spec/protocol.html — Protocol structural subtyping
- https://www.structlog.org/en/stable/contextvars.html — structlog bind patterns in service classes

### Tertiary (LOW confidence)
- https://deepwiki.com/openai/openai-python/4.1.3-parsed-responses-and-structured-outputs — ParsedChatCompletion class structure (informational; actual structure verified in-tree)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all versions verified in-tree against installed packages
- Architecture: HIGH — `parse()` + vision pattern verified in-tree; mock pattern verified in venv
- Pitfalls: HIGH — image_url vs input_image verified against official docs; refusal pattern from Context7

**Research date:** 2026-05-13
**Valid until:** 2026-06-13 (30 days — openai-python API is stable; Anthropic model names stable)
