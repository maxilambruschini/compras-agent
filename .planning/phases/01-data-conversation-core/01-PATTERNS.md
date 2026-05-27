# Phase 1: Data + Conversation Core - Pattern Map

**Mapped:** 2026-05-27
**Files analyzed:** 9 new/modified
**Analogs found:** 9 / 9

All new Phase 1 files have strong existing analogs in the v1.0 invoice backend. The codebase
conventions (SQLAlchemy 2.0 typed mapping, stateless `session`-first services, `client.chat.
completions.parse()` + Optional Pydantic, lazy settings factory, aiosqlite test fixtures) map
1:1 onto the Gastos Bot's data + conversation core. The only file with no direct analog is the
deterministic conversation orchestrator (state machine) — no FSM exists yet, so the planner
should lean on RESEARCH.md / ARCHITECTURE.md for its internal shape, while reusing this
codebase's service/DI/test conventions for everything around it.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/app/db/models.py` (Gasto, Conversation, opt. CajaCierre) | model | CRUD | `backend/app/db/models.py` (Invoice) | exact (same file, extend) |
| `backend/app/models/conversation.py` (DraftGasto / GastoSlots DTO) | model/schema | transform | `backend/app/models/extraction.py` (ExtractedInvoice) | exact |
| `backend/app/services/slot_extraction.py` (SlotExtractionService) | service | transform (LLM) | `backend/app/services/extraction.py` (ExtractionService) | exact |
| `backend/app/services/gasto.py` (GastoService) | service | CRUD | `backend/app/services/invoice.py` (InvoiceService) | exact |
| `backend/app/services/conversation.py` (ConversationOrchestrator) | service | event-driven / state-machine | `backend/app/services/invoice.py` (stateless service shape) | role-match (FSM is new) |
| `backend/app/services/amounts.py` (`parse_ars_amount`) | utility | transform | `compute_confidence` / `assign_status` in `extraction.py` (pure module helpers) | role-match |
| `backend/alembic/versions/<new>.py` (gastos schema migration) | migration | n/a | `add_invoice_duplicate_constraint.py` + `0cd640399c29_initial_schema.py` | exact |
| `backend/app/config.py` (add AGENT_MODE, CONVERSATION_TIMEOUT_HOURS) | config | n/a | `backend/app/config.py` (Settings) | exact (same file, extend) |
| `backend/app/main.py` (`create_app` conditional router on AGENT_MODE) | config/bootstrap | request-response | `backend/app/main.py` `create_app()` | exact (same file, extend) |
| `backend/tests/test_*` (per new module) | test | n/a | `tests/test_invoice_service.py`, `tests/test_extraction.py`, `tests/conftest.py` | exact |

## Migration head (for `down_revision`)

The current Alembic head is **`b1c2d3e4f5a6`** (`add_invoice_duplicate_constraint.py`). No
migration declares it as `down_revision`, so it is the head. The new gastos migration MUST set:

```python
revision: str = '<new_id>'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
```

Chain on disk: `0cd640399c29` (initial) → `9f9e9cf65e1e` (is_active default) → `b1c2d3e4f5a6` (dup index, HEAD).

## Pattern Assignments

### `backend/app/db/models.py` — Gasto + Conversation models (model, CRUD)

**Analog:** same file, `Invoice` / `SenderAllowlist` classes (lines 35-109).

**ORM conventions to copy verbatim** — SQLAlchemy 2.0 typed mapping, dialect-agnostic `Uuid`, `Optional[...]` for nullable, server-default + `onupdate` timestamps. Imports block (lines 14-28):
```python
from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, Index, Integer,
    Numeric, String, Text, Uuid, func, text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
```

**PK + timestamp pattern** (lines 38, 60-65) — reuse `updated_at` exactly; the D-08 timeout logic depends on `onupdate=func.now()`:
```python
id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
updated_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

**Money column** — mirror `confidence_score`'s `Numeric` usage for `monto`: `Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))` (cents precision; line-item analog uses `Numeric(14,4)` at line 91 — pick 2 dp for ARS pesos). `concepto`: `mapped_column(Text)`; `fecha`: `mapped_column(Date)`.

**Conversation model fields** — `sender_phone` String(30) (copy line 55), `state` String(30) `nullable=False, default="idle"` (copy `status` pattern line 51-53), `draft` `Text` (JSON dump, copy `raw_extraction` line 57). `updated_at` is the timeout anchor (D-08).

**`__table_args__` index pattern** (lines 72-76) — add an index on `Conversation.sender_phone` (the per-sender lookup/lock key).

---

### `backend/app/models/conversation.py` — DraftGasto / GastoSlots DTO (schema, transform)

**Analog:** `backend/app/models/extraction.py` (`ExtractedInvoice`, lines 42-58).

**All-Optional, null-over-hallucination pattern** (D-06, lines 49-58):
```python
from pydantic import BaseModel, ConfigDict

class GastoSlots(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    concepto: Optional[str] = None
    monto: Optional[Decimal] = None   # raw extracted amount; normalize via parse_ars_amount
```
Every field `Optional[...] = None` — the planner must NOT use bare `str`. `use_enum_values=True` is required for OpenAI Structured Outputs `.parse()` (line 5 of analog explains why).

---

### `backend/app/services/slot_extraction.py` — SlotExtractionService (service, LLM transform)

**Analog:** `backend/app/services/extraction.py` (`ExtractionService`, lines 134-203).

**Constructor injection (DI)** (lines 148-157) — caller builds `AsyncOpenAI` in the router dependency, NEVER at module import (testability + Pitfall 3):
```python
def __init__(self, openai_client: AsyncOpenAI, settings: Settings) -> None:
    self._client = openai_client
    self._settings = settings
    self._log = structlog.get_logger()
```

**`.parse()` + refusal-before-parsed pattern** (lines 176-203) — model is **gpt-4o-mini** per D-06 (NOT `gpt-4o-2024-08-06`); text-only messages (no image_url):
```python
completion = await self._client.chat.completions.parse(
    model="gpt-4o-mini",
    messages=[{"role": "system", "content": SLOT_SYSTEM_PROMPT},
              {"role": "user", "content": message_text}],
    response_format=GastoSlots,
)
msg = completion.choices[0].message
return (msg.parsed, msg.refusal)   # check refusal BEFORE parsed
```

**Exception hierarchy + module-level SYSTEM_PROMPT constant** (lines 36-79) — mirror `ExtractionError`/`...RefusalError`/`...FailedError` and a module-level `SLOT_SYSTEM_PROMPT`. Never log secrets (T-02-02, lines 196-199).

---

### `backend/app/services/gasto.py` — GastoService (service, CRUD)

**Analog:** `backend/app/services/invoice.py` (`InvoiceService`, lines 32-247).

**Stateless, `session`-first service** (lines 32-41) — holds no session state; methods take `AsyncSession` as first arg:
```python
class GastoService:
    def __init__(self) -> None:
        self._log = structlog.get_logger()

    async def save_gasto(self, session: AsyncSession, draft: DraftGasto, sender_phone: str) -> Gasto:
        ...
```

**Persist + commit + structured log** (lines 196-246) — build the ORM object, `session.add(...)`, `await session.commit()`, log `gasto.saved` with `id=str(...)`. `fecha` defaults to `date.today()` (D-02 — no backdating). Strip `whatsapp:` prefix from sender (line 194).

**Idempotency / row-lock note (D-08 / Pitfall):** the per-sender `SELECT ... FOR NO KEY UPDATE` is **Postgres-only**. Mirror `InvoiceService.save_invoice`'s `try/except IntegrityError → rollback → re-raise` (lines 230-238) for write races, and in tests **mock/assert the locking call** rather than relying on SQLite (see test analog note below).

---

### `backend/app/services/conversation.py` — ConversationOrchestrator (service, state machine)

**Analog (shape only):** stateless service + DI conventions from `invoice.py` / `extraction.py`. **No FSM exists in the codebase** — see "No Analog Found". Use RESEARCH.md / ARCHITECTURE.md `match`-based state machine for the internal transitions; reuse this repo's conventions for the wrapper:

- Constructor injects collaborators: `slot_service`, `gasto_service`, and a `provider: WhatsAppProvider` (see `providers/base.py` lines 19-39 — the send interface is `async def send_message(self, to: str, text: str)`; the orchestrator should call exactly this so Phase 2 can drop in the real Twilio provider).
- Methods take `session: AsyncSession` first (stateless service pattern).
- Confirmation is a **deterministic string match** (sí/dale/ok/confirmo), never an LLM call (D-05).
- Timeout: compare `Conversation.updated_at` against `settings.conversation_timeout_hours` and reset to `idle` on next inbound (D-08).
- `structlog` per-call binding (extraction.py line 221: `log = self._log.bind(...)`).

---

### `backend/app/services/amounts.py` — `parse_ars_amount()` (utility, pure transform)

**Analog:** module-level pure helpers `compute_confidence` / `assign_status` in `extraction.py` (lines 105-126) — importable, no class, fully unit-testable.

**Argentine number format** — the system prompt at `extraction.py` lines 53-56 documents the canonical rule (period = thousands sep, comma = decimal). `parse_ars_amount` must implement it in Python and avoid the `Decimal("1.500")` trap flagged in PITFALLS.md: `"1.500"` → `Decimal("1500")`, `"1.234,56"` → `Decimal("1234.56")`. Return `Optional[Decimal]` (None on unparseable input — null > hallucination).

---

### `backend/alembic/versions/<new>.py` — gastos schema migration (migration)

**Analogs:** `0cd640399c29_initial_schema.py` (table/index creation idiom, lines 21-81) + `add_invoice_duplicate_constraint.py` (header + reversible up/down, lines 15-46).

**Header block to copy** (set `down_revision` to current head `b1c2d3e4f5a6`):
```python
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '<new_id>'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
```

**`upgrade()` table-create idiom** (initial_schema lines 24-68) — `op.create_table(...)` with `sa.Column(... sa.Uuid(), nullable=...)`, `server_default=sa.text('now()')` for timestamps, `op.create_index(...)`. **`downgrade()` must mirror in reverse** (drop indexes then tables, lines 72-81). Migration must match `db/models.py` exactly (it is autogenerate source-of-truth, models.py line 1-6).

---

### `backend/app/config.py` — AGENT_MODE + CONVERSATION_TIMEOUT_HOURS (config)

**Analog:** same file, `Settings` (lines 6-44).

**Optional-with-default pattern** (lines 22-39) — add to the "Optional with defaults" block:
```python
agent_mode: str = "gastos"          # "invoice" | "gastos" (D-09 default = gastos)
conversation_timeout_hours: int = 4 # D-08
```
Keep the lazy `@lru_cache get_settings()` (lines 42-44) untouched — tests patch env then `cache_clear()` (conftest lines 57-59). Env names are case-insensitive (`case_sensitive=False`, line 10) → `AGENT_MODE`, `CONVERSATION_TIMEOUT_HOURS`.

---

### `backend/app/main.py` — conditional router registration (bootstrap, D-09)

**Analog:** same file, `create_app()` (lines 35-59). Routers imported INSIDE the factory to avoid circular imports (line 43 comment).

**Current state:** `main.py` registers `health`, debug-gated `extraction`, and `whatsapp` (line 54-57: "always registered; provider selected via WHATSAPP_PROVIDER"). **Phase 1 change:** make the invoice/whatsapp webhook conditional on `AGENT_MODE == "invoice"`. The gastos router itself is wired in Phase 2 — for Phase 1, only introduce the `settings.agent_mode` branch seam:
```python
if settings.agent_mode == "invoice":
    from app.routers.whatsapp import router as whatsapp_router
    app.include_router(whatsapp_router, prefix="/whatsapp", tags=["whatsapp"])
# elif settings.agent_mode == "gastos":  # gastos webhook wired in Phase 2
```

---

### `backend/tests/test_*.py` — per-module tests (test)

**Analogs:** `tests/test_invoice_service.py`, `tests/test_extraction.py`, `tests/conftest.py`.

**DB tests** — reuse conftest fixtures `async_engine` + `db_session` (aiosqlite in-memory, conftest lines 67-87). Build DTO factories like `make_extraction_result()` (test_invoice_service lines 41-70).

**LLM service tests** — mock the `AsyncOpenAI` client; use the verbatim `ParsedChatCompletion` mock helper (test_extraction lines 51-60) — `MagicMock(spec=ParsedChatCompletionMessage)` with `.parsed` / `.refusal` set. Never make live calls.

**Postgres-only-construct tests** — `FOR NO KEY UPDATE` row lock and the functional unique index are Postgres-only; SQLite does NOT enforce them. Follow test_invoice_service lines 8-15: monkeypatch `session.commit`/the lock call to assert the CATCH/lock path rather than relying on SQLite semantics.

## Shared Patterns

### Lazy settings + DI construction
**Source:** `app/config.py` lines 42-44, `app/services/extraction.py` lines 148-157.
**Apply to:** SlotExtractionService, GastoService, ConversationOrchestrator.
The `AsyncOpenAI` client and `Settings` are injected by the router dependency / app factory — never constructed at module import (Pitfall 3). Tests override via `app.dependency_overrides[...]`.

### Structlog, secret-safe logging
**Source:** `app/services/extraction.py` line 27 (`log = structlog.get_logger()`), line 157 (instance `self._log`), line 221 (`self._log.bind(filename=...)`), lines 196-199 (never log API keys, T-02-02).
**Apply to:** all new services.

### Stateless, session-first service methods
**Source:** `app/services/invoice.py` lines 32-41.
**Apply to:** GastoService, ConversationOrchestrator. Service holds no session; `AsyncSession` is the first method arg; caller owns lifecycle.

### Null-over-hallucination Pydantic DTOs
**Source:** `app/models/extraction.py` lines 42-58, `ConfigDict(use_enum_values=True)`.
**Apply to:** GastoSlots / DraftGasto. Every extractable field `Optional[...] = None`.

### Dialect-agnostic ORM + aiosqlite test parity
**Source:** `app/db/models.py` lines 1-6, 14-28; `tests/conftest.py` lines 67-87.
**Apply to:** Gasto / Conversation models. Use `sqlalchemy.Uuid` (not postgresql.UUID); Postgres-only behaviors (FOR NO KEY UPDATE, functional unique index) must be guarded/mocked in tests.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `backend/app/services/conversation.py` (ConversationOrchestrator FSM) | service | state-machine / event-driven | No finite-state-machine exists in the codebase. The v1.0 invoice flow is a linear background task (`process_invoice`), not a multi-turn deterministic state machine. Planner should source the `match`-based transition table and slot-fill ordering (idle → awaiting_monto → awaiting_ticket → confirm → idle, D-04) from RESEARCH.md / ARCHITECTURE.md, while reusing this repo's service/DI/logging/test conventions for the surrounding scaffold. |

## Metadata

**Analog search scope:** `backend/app/{db,models,services,providers,routers}/`, `backend/alembic/versions/`, `backend/tests/`, `backend/app/{config,main}.py`.
**Files scanned:** 12 read in full/targeted (extraction.py, invoice.py, models.py, config.py, main.py, models/extraction.py, providers/base.py, conftest.py, test_invoice_service.py, test_extraction.py, 2 migrations) + directory listings.
**Migration head verified:** `b1c2d3e4f5a6` (no down_revision points to it).
**Pattern extraction date:** 2026-05-27
