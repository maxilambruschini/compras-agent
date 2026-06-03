# Phase 1: Data + Conversation Core — Research

**Researched:** 2026-05-27
**Domain:** SQLAlchemy ORM models, deterministic state machine, GPT-4o-mini slot extraction, DB-backed idempotency + row locking, Argentine number parsing, Pydantic Settings extension
**Confidence:** HIGH — all findings derived from direct codebase inspection plus prior v2.0 research files

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Minimal Gasto field set: `concepto` (freeform), `monto` (salida, Decimal), `fecha` (auto = today), optional `ticket_image_path` (Phase 2). No lugar/proveedor, no entrada, no category in v2.0.
- **D-02:** `fecha` defaults to the day the gasto is recorded. Backdating not supported in v2.0.
- **D-03:** Ask only missing slots — one question per turn. If the opening intent already supplies a slot, don't re-ask it.
- **D-04:** State sequence: `idle` → `awaiting_monto` (only if monto missing) → `awaiting_ticket` → `confirm` → write Gasto → `idle`. Concepto from intent; if absent, bot asks before monto. Order: concepto → monto → ticket → confirm.
- **D-05:** Confirmation step uses deterministic string match (sí/dale/ok/confirmo…), never an LLM call.
- **D-06:** SlotExtractionService uses **gpt-4o-mini**. Mirror `client.chat.completions.parse()` + Pydantic pattern from `services/extraction.py`. All fields `Optional` with `default=None`.
- **D-07:** Correction at confirm = freeform re-state → re-extract onto draft → re-confirm. `cancelar` aborts draft → `idle`.
- **D-08:** `CONVERSATION_TIMEOUT_HOURS = 4`. Timeout detected via existing `updated_at`; no extra column. Manager receives Spanish notice on reset.
- **D-09:** `AGENT_MODE` env var (`invoice` | `gastos`, default `gastos`) selects which agent's webhook is registered in `app/main.py`. Config layer + conditional registration introduced in Phase 1; the gastos webhook itself is wired in Phase 2.

### Claude's Discretion

- Exact ORM column types/lengths, table/index names, Alembic migration structure.
- Whether `CajaCierre` model is created here or in Phase 2.
- Internal module layout of the orchestrator (single `conversation.py` `match` statement vs. helpers).
- Exact Spanish copy strings (re-prompts, timeout notice, confirmation) — concise Argentine Spanish.

### Deferred Ideas (OUT OF SCOPE)

- `entrada` (money in) alongside salida.
- Separate `lugar`/`proveedor` field.
- Expense `category` field.
- Backdating `fecha`.
- Structured field-picker correction UX (reply a number).
- Cross-check declared monto vs. extracted ticket total.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CONV-01 | Conversation state persisted per sender, survives restarts | `Conversation` ORM model; `conversations` table; DB-backed session |
| CONV-02 | Duplicate webhook deliveries do not advance state or create duplicate records | `Conversation.last_message_id` column; idempotency check before state read |
| CONV-03 | Concurrent messages from same sender serialized | `SELECT ... FOR NO KEY UPDATE` at orchestrator entry; test via monkeypatched lock assert |
| CONV-04 | Stale conversation auto-resets to idle after timeout | `updated_at` delta check on every inbound message; `CONVERSATION_TIMEOUT_HOURS` config |
| CONV-05 | Argentine number formats parsed correctly | `parse_ars_amount()` utility; GPT `Optional[float]` schema as primary path |
| CONV-06 | Unparseable/off-topic replies re-prompt current step; after 3 failures send example + offer cancel | `failure_count` field in draft or on `Conversation` row; re-prompt path in orchestrator |
| GASTO-01 | Manager records expense by free-form Spanish intent | `SlotExtractionService` using gpt-4o-mini `.parse()` into `GastoSlots` |
| GASTO-02 | Bot collects missing fields through follow-up questions | Orchestrator state machine; slot completeness check per turn |
| GASTO-04 | Manager can skip ticket ("sin ticket") and gasto is still saved | `awaiting_ticket` state accepts text "sin ticket"; `ticket_image_path` remains `None` |
| GASTO-05 | Bot shows summary and requires explicit confirmation before write | `confirm` state; deterministic affirmative set check before `GastoService.save_gasto()` |
| GASTO-06 | Manager can correct a field or cancel before save | Re-extract onto draft at `confirm` state; `cancelar` → `idle` |
</phase_requirements>

---

## Summary

Phase 1 is a brownfield backend-only phase. Every production pattern needed already exists in the v1.0 codebase. The work is primarily about adding three ORM models, one Alembic migration, three new service classes (SlotExtractionService, GastoService, ConversationOrchestrator), and minor config/main.py extensions — all mirroring patterns that are already established and tested.

The highest-risk implementation decisions are: (1) the `SELECT ... FOR NO KEY UPDATE` row lock, which is Postgres-only and cannot be tested with the project's existing aiosqlite test infrastructure without a special mocking strategy; (2) the `parse_ars_amount()` function where `Decimal("1.500")` silently returns 1.5 rather than 1500; and (3) the DraftGasto/GastoSlots Pydantic schema design, where all fields must be `Optional` with defaults to survive schema evolution without crashing in-progress conversations.

The phase requires no new dependencies. All library patterns are already established: `client.chat.completions.parse()` with Pydantic v2, `async_sessionmaker`, `structlog`, `mapped_column` with `Mapped`. The `AGENT_MODE` config addition is a two-line change to `config.py`. The `create_app()` conditional router registration follows the existing `if settings.debug:` pattern already in `main.py`.

**Primary recommendation:** Mirror ExtractionService and InvoiceService patterns exactly. The state machine is ~100 lines of `match` statements. All complexity lives in the idempotency + locking layer — read the Postgres locking section below before implementing the orchestrator.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Conversation state persistence | Database (Postgres) | — | Per-sender row; must survive restarts and hours-long reply gaps |
| Slot extraction from Spanish text | API / Backend (GPT-4o-mini) | Code post-processing | LLM extracts, code validates and gates writes |
| State machine transitions | API / Backend (ConversationOrchestrator) | — | Deterministic code; GPT never decides transitions |
| Gasto persistence | API / Backend (GastoService) | Database | Write only after explicit confirmation |
| Argentine number parsing | API / Backend (parse_ars_amount utility) | GPT JSON output | GPT normalises locale strings to JSON numbers; code is fallback defence |
| Config / env selection | API / Backend (Pydantic Settings) | — | Fail-fast validation at startup |
| Per-sender row locking | Database (Postgres FOR NO KEY UPDATE) | Test mock | Postgres-only; tests assert lock call, not lock semantics |

---

## Standard Stack

### Core (no new dependencies — all already in requirements.txt)

| Library | Version (pinned) | Purpose | Why Standard |
|---------|-----------------|---------|--------------|
| sqlalchemy (async) | existing (2.x) | ORM models, `with_for_update()` | Already established; dialect-agnostic `Uuid` type in use |
| pydantic v2 | existing 2.13.4 | `GastoSlots`, `DraftGasto`, Settings extension | `.parse()` pattern requires Pydantic v2 |
| openai | existing 2.36.0 | gpt-4o-mini slot extraction via `.parse()` | Same client used for invoice extraction |
| structlog | existing ^25.x | Structured JSON logging throughout | All v1.0 services use it; bind per call, not per `__init__` |
| pydantic-settings | existing | `AGENT_MODE` + `CONVERSATION_TIMEOUT_HOURS` additions to Settings | Already the pattern in `config.py` |
| alembic | existing | Migration for gastos + conversations (+ optionally caja_cierres) | Existing migration chain; same `op.create_table` + RLS pattern |

**No new packages to install.** [VERIFIED: codebase inspection]

### Package Legitimacy Audit

> No new external packages are introduced in this phase. All libraries are already pinned in `requirements.txt` and verified during v1.0 development.

**Packages removed due to slopcheck:** none  
**Packages flagged as suspicious:** none

---

## Architecture Patterns

### System Architecture Diagram (Phase 1 scope — no WhatsApp wire yet)

```
Unit test / pytest
        │
        │  call orchestrator.handle_message(sender, text, message_id)
        ▼
ConversationOrchestrator
  │
  ├── open AsyncSession (get_async_session_local())
  │     │
  │     ├── SELECT conversations WHERE sender_phone = X
  │     │   FOR NO KEY UPDATE   ← Postgres row lock (mocked in tests)
  │     │
  │     ├── idempotency check: conv.last_message_id == message_id → return
  │     │
  │     ├── timeout check: updated_at < now() - CONVERSATION_TIMEOUT_HOURS → reset to idle
  │     │
  │     └── match conv.state:
  │           "idle"           → SlotExtractionService.extract(text) → GastoSlots
  │           "awaiting_monto" → SlotExtractionService.extract(text) → patch monto
  │           "awaiting_ticket"→ accept "sin ticket" text → advance
  │           "confirm"        → deterministic affirmative check OR re-extract correction
  │
  ├── GastoService.save_gasto(session, draft) [only at confirm + "sí"]
  │
  └── commit → send reply via WhatsAppProvider (mocked in tests)

SlotExtractionService
  │
  └── client.chat.completions.parse(
          model="gpt-4o-mini",
          messages=[system_prompt, user_text],
          response_format=GastoSlots   ← Pydantic model
      )
      → msg.parsed  (GastoSlots | None)
      → msg.refusal (str | None)

GastoService
  └── save_gasto(session, draft: DraftGasto) → INSERT gastos row
      (mirrors InvoiceService.save_invoice pattern)

Postgres (Docker)
  ├── conversations  (NEW — per-sender state + draft JSON + last_message_id + updated_at)
  ├── gastos         (NEW — committed expense records)
  └── caja_cierres   (NEW or Phase 2 — depends on planner decision)
```

### Recommended Project Structure (new files only)

```
backend/
├── app/
│   ├── config.py                    # MODIFY: add AGENT_MODE, CONVERSATION_TIMEOUT_HOURS
│   ├── main.py                      # MODIFY: conditional router registration per AGENT_MODE
│   ├── db/
│   │   └── models.py                # MODIFY: add Gasto, Conversation (+ optionally CajaCierre)
│   └── services/
│       ├── slot_extraction.py       # NEW: SlotExtractionService + GastoSlots + parse_ars_amount
│       ├── gasto.py                 # NEW: GastoService (mirrors invoice.py)
│       └── conversation.py          # NEW: ConversationOrchestrator (match-based state machine)
├── alembic/
│   └── versions/
│       └── XXXX_add_gastos_tables.py  # NEW: gastos, conversations (+ caja_cierres if Phase 1)
└── tests/
    ├── test_slot_extraction.py      # NEW: mocked OpenAI, parse_ars_amount unit tests
    ├── test_gasto_service.py        # NEW: save_gasto with in-memory SQLite (mirrors test_invoice_service.py)
    └── test_conversation.py         # NEW: full state machine walkthrough, mocked provider + extractor
```

---

## Pattern 1: ExtractionService → SlotExtractionService (mirror exactly)

**What:** The existing `ExtractionService._call_gpt4o()` pattern is the authoritative template for `SlotExtractionService`. Mirror constructor signature, `Optional` field discipline, `.parsed`/`.refusal` check order, and structlog binding.

**Key differences from ExtractionService:**
- Model: `"gpt-4o-mini"` (not `"gpt-4o-2024-08-06"`)
- Input: plain text string (not base64 image)
- Output schema: `GastoSlots` (not `ExtractedInvoice`)
- No `StorageBackend` — no image handling in Phase 1
- System prompt: Spanish slot extraction, not AFIP invoice extraction

**Exact constructor shape to mirror:**

```python
# Source: backend/app/services/extraction.py (inspected 2026-05-27)
class SlotExtractionService:
    def __init__(self, openai_client: AsyncOpenAI) -> None:
        self._client = openai_client
        self._log = structlog.get_logger()  # lazy proxy; bind at call time

    async def extract(self, text: str) -> GastoSlots:
        """Returns GastoSlots with all slots that could be parsed; None fields for missing."""
        log = self._log.bind(text_preview=text[:50])
        try:
            completion = await self._client.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SLOT_SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                response_format=GastoSlots,
            )
        except Exception as exc:
            log.error("slot_extraction.failed", error=str(exc))
            raise SlotExtractionError(f"openai parse failed: {exc}") from exc
        msg = completion.choices[0].message
        if msg.refusal:
            log.warning("slot_extraction.refused", refusal=msg.refusal)
            return GastoSlots()   # all None — orchestrator will re-prompt
        if msg.parsed is None:
            return GastoSlots()
        return msg.parsed
```

[VERIFIED: codebase inspection of extraction.py]

---

## Pattern 2: GastoSlots + DraftGasto Pydantic Schemas

**Critical design rule:** Every field in both schemas must be `Optional` with `default=None`. This is enforced in the PITFALLS research for two reasons: (a) GPT must not hallucinate a missing field, and (b) draft JSON stored in the `conversations` row must survive schema evolution without crashing existing in-progress conversations (Pitfall 32).

```python
# Source: .planning/research/PITFALLS.md P32 + D-06 decision
from pydantic import BaseModel
from decimal import Decimal
from typing import Optional

class GastoSlots(BaseModel):
    """GPT-4o-mini structured output for slot extraction from free Spanish text.

    All fields Optional — null preferred over hallucination (mirrors ExtractedInvoice pattern).
    monto typed as Optional[float] so GPT outputs a JSON number (no locale formatting).
    Orchestrator converts to Decimal via Decimal(str(slots.monto)) after extraction.
    """
    concepto: Optional[str] = None   # freeform observación ("queso en supermercado")
    monto: Optional[float] = None    # JSON number; GPT normalises "1.500" → 1500.0

class DraftGasto(BaseModel):
    """In-progress gasto being assembled across conversation turns.
    Stored as JSON in conversations.draft_gasto. All fields Optional — see P32.
    """
    concepto: Optional[str] = None
    monto: Optional[Decimal] = None   # converted from GastoSlots.monto after extraction
    ticket_image_path: Optional[str] = None   # populated in Phase 2
    failure_count: int = 0            # consecutive parse failures for CONV-06 re-prompt logic
```

**D-01 note:** D-01 removes `lugar`/`proveedor` from v2.0. `GastoSlots` has only `concepto` + `monto`. Do NOT add `lugar` — it is deferred. [VERIFIED: 01-CONTEXT.md D-01]

---

## Pattern 3: parse_ars_amount() — The Decimal("1.500") Trap

**The trap:** Python's `Decimal("1.500")` returns `Decimal('1.500')` which equals 1.5 — not 1500. This silently corrupts amounts. [VERIFIED: .planning/research/PITFALLS.md P26]

**Primary defence:** `monto: Optional[float]` in `GastoSlots` — GPT Structured Outputs produces a JSON number (e.g., `1500.0`), not a locale-formatted string. `Decimal(str(float_val))` is then safe.

**Fallback utility (required for any non-GPT code path):**

```python
# Source: .planning/research/PITFALLS.md P26 (verified pattern)
from decimal import Decimal, InvalidOperation

def parse_ars_amount(text: str) -> Optional[Decimal]:
    """Parse an Argentine-formatted amount string to Decimal.

    Handles:
      "1.500"     → Decimal("1500")    (dot = thousands separator)
      "1.234,56"  → Decimal("1234.56") (comma = decimal separator)
      "1500"      → Decimal("1500")
      "1500,50"   → Decimal("1500.50")

    Returns None on parse failure (orchestrator will re-prompt).
    NEVER use Python's locale module — global mutable state, unsafe in async.
    """
    try:
        cleaned = text.strip()
        # Strip thousands separator (dot) then replace decimal separator (comma) with dot
        cleaned = cleaned.replace('.', '').replace(',', '.')
        return Decimal(cleaned)
    except InvalidOperation:
        return None
```

**Unit test requirement (ROADMAP success criterion 5):**
```python
assert parse_ars_amount("1.500") == Decimal("1500")
assert parse_ars_amount("1.234,56") == Decimal("1234.56")
assert parse_ars_amount("1500") == Decimal("1500")
assert parse_ars_amount("abc") is None
```

---

## Pattern 4: ORM Models — Mirror models.py Conventions Exactly

**Authoritative template:** `backend/app/db/models.py` (inspected 2026-05-27). [VERIFIED: codebase]

Key conventions to replicate:
- `DeclarativeBase` subclass `Base` already exists — do NOT create a new one; import and extend.
- `Mapped` + `mapped_column` with SQLAlchemy 2.0 type annotations.
- `sqlalchemy.Uuid` (NOT `postgresql.UUID`) — dialect-agnostic for aiosqlite test compatibility.
- `DateTime(timezone=True)` with `server_default=func.now()` and `onupdate=func.now()` for `updated_at`. This is the timestamp the timeout logic depends on.
- `Optional` columns: `Mapped[Optional[str]]` — matches pattern in `Invoice`.
- `Numeric(14, 4)` for money values (matches `InvoiceLineItem.precio_unitario_sin_iva`).
- `ENABLE ROW LEVEL SECURITY` in migration (Pitfall 3; required for all new tables).

```python
# Source: backend/app/db/models.py (inspected 2026-05-27)
# Add these classes to the existing models.py — do not create a new Base

class Conversation(Base):
    __tablename__ = "conversations"

    sender_phone: Mapped[str] = mapped_column(String(30), primary_key=True)
    state: Mapped[str] = mapped_column(String(50), nullable=False, default="idle")
    draft_gasto: Mapped[Optional[str]] = mapped_column(Text)   # JSON dump of DraftGasto
    last_message_id: Mapped[Optional[str]] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Gasto(Base):
    __tablename__ = "gastos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    concepto: Mapped[str] = mapped_column(Text, nullable=False)
    monto: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)  # salida
    ticket_image_path: Mapped[Optional[str]] = mapped_column(Text)
    sender_phone: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_gastos_fecha", "fecha"),
        Index("ix_gastos_sender_phone", "sender_phone"),
    )
```

**CajaCierre placement decision (planner's discretion per CONTEXT.md):**

Recommendation: create `CajaCierre` model in this phase alongside the migration. Rationale: (a) the migration must run once — splitting tables across phases adds a second migration with zero benefit; (b) the `conversations` state machine references `awaiting_caja_count` state in Phase 2, and having the target table ready avoids a blocking dependency; (c) the model itself has zero orchestration logic — it is just a data container. The reactive write to `CajaCierre` happens in Phase 2 but the table can exist in Phase 1.

```python
class CajaCierre(Base):
    __tablename__ = "caja_cierres"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    hora_cierre: Mapped[str] = mapped_column(String(5), nullable=False)  # "12:00" | "17:00"
    efectivo_en_caja: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    sender_phone: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_caja_cierres_fecha", "fecha"),
    )
```

---

## Pattern 5: ConversationOrchestrator — State Machine Structure

**State enum:** Use `StrEnum` (Python 3.11+) or plain string constants matching what is stored in `conversations.state`. Do not use an integer enum — the DB column stores the string literal. [ASSUMED — StrEnum is idiomatic but codebase uses plain strings; either works]

**State constants:**
```python
class ConvState:
    IDLE = "idle"
    AWAITING_MONTO = "awaiting_monto"
    AWAITING_TICKET = "awaiting_ticket"
    CONFIRM = "confirm"
```

**Orchestrator skeleton (the critical ordering):**

```python
# Source: derived from .planning/research/ARCHITECTURE.md + PITFALLS.md
# The ordering below is non-negotiable — see P20, P21, P22

async def handle_message(
    self,
    sender: str,
    text: str,
    message_id: str,
    session_factory: async_sessionmaker,
    provider,   # WhatsAppProvider — mocked in tests
) -> None:
    async with session_factory() as session:
        async with session.begin():
            # Step 1: acquire per-sender row lock (Postgres FOR NO KEY UPDATE)
            result = await session.execute(
                select(Conversation)
                .where(Conversation.sender_phone == sender)
                .with_for_update(key_share=True)   # FOR NO KEY UPDATE
            )
            conv = result.scalar_one_or_none()
            if conv is None:
                conv = Conversation(sender_phone=sender, state=ConvState.IDLE)
                session.add(conv)
                await session.flush()

            # Step 2: idempotency check — BEFORE reading state (P20)
            if conv.last_message_id == message_id:
                return   # already processed; release lock and exit

            conv.last_message_id = message_id

            # Step 3: timeout check (P22 / D-08)
            if conv.state != ConvState.IDLE:
                age = datetime.now(tz=timezone.utc) - conv.updated_at
                if age > timedelta(hours=self._settings.conversation_timeout_hours):
                    conv.state = ConvState.IDLE
                    conv.draft_gasto = None
                    # commit happens at end of block; reply sent after commit (below)
                    reply = "Tu registro anterior expiró. Podés empezar uno nuevo."
                    await session.commit()
                    await provider.send_message(sender, reply)
                    return

            # Step 4: global cancelar check
            if text.strip().lower() == "cancelar":
                conv.state = ConvState.IDLE
                conv.draft_gasto = None
                await session.commit()
                await provider.send_message(sender, "Registro cancelado.")
                return

            # Step 5: dispatch to state handler
            reply = await self._dispatch(conv, text, session)

        # commit releases the lock; WhatsApp reply sent OUTSIDE transaction (P21)
    await provider.send_message(sender, reply)
```

**Key implementation note:** `with_for_update(key_share=True)` maps to `FOR NO KEY UPDATE` in SQLAlchemy 2.0. `FOR NO KEY UPDATE` is preferred over `FOR UPDATE` because it does not block concurrent inserts into child tables that reference `conversations` (Pitfall 21 + SUMMARY.md). [VERIFIED: .planning/research/SUMMARY.md]

**Failure counter (CONV-06):** Store `failure_count` inside `DraftGasto` JSON (not a separate column). On each unparseable reply, increment `draft.failure_count`. At `failure_count >= 3`, send concrete example and offer to cancel. Reset to 0 on successful parse.

**Confirmation affirmative set (D-05 / P31):**
```python
AFFIRMATIVE = {"sí", "si", "dale", "ok", "confirmo", "listo", "va", "yes", "bueno", "claro"}

def is_confirmation(text: str) -> bool:
    return text.strip().lower() in AFFIRMATIVE
```
[VERIFIED: .planning/research/PITFALLS.md P31]

---

## Pattern 6: DB-Backed Idempotency — `SELECT ... FOR NO KEY UPDATE` in Tests

**The core problem:** `FOR NO KEY UPDATE` is a Postgres-only construct. The test suite runs on aiosqlite (SQLite in-memory). SQLite does not implement row-level locking — it silently ignores `FOR UPDATE` clauses in SQLAlchemy without raising an error. Tests that rely on SQLite lock semantics to verify idempotency will pass whether or not the lock is actually issued.

**How v1.0 solves the analogous problem:** `test_invoice_service.py` uses `monkeypatch` to patch `session.commit` to raise `IntegrityError`, verifying the catch logic without relying on SQLite enforcing a Postgres functional unique index. The same principle applies here. [VERIFIED: backend/tests/test_invoice_service.py, lines 216-231]

**Recommended test strategy for the lock:**

```python
# Source: derived from test_invoice_service.py monkeypatch pattern + ROADMAP success criterion 3
@pytest.mark.asyncio
async def test_row_lock_is_issued(db_session, monkeypatch):
    """Verify orchestrator issues SELECT ... FOR NO KEY UPDATE on the conversations row.

    We cannot verify the actual lock semantics in SQLite, but we can assert
    that with_for_update(key_share=True) was called on the Select statement.
    """
    lock_calls = []
    original_execute = db_session.execute

    async def tracking_execute(stmt, *args, **kwargs):
        # Detect if the statement has a FOR NO KEY UPDATE clause
        compiled = stmt.compile(dialect=...)
        if "FOR NO KEY UPDATE" in str(stmt):
            lock_calls.append(stmt)
        return await original_execute(stmt, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", tracking_execute)
    # ... drive orchestrator ... assert len(lock_calls) > 0
```

**Alternative (simpler) approach — recommended:** Patch `session.execute` via `AsyncMock`, assert it was called with a statement that has `with_for_update(key_share=True)`. This verifies the intent without needing SQLite to honour the lock:

```python
# In test: replace execute with a spy that captures calls and returns a mock result
execute_spy = AsyncMock(return_value=mock_result)
monkeypatch.setattr(session, "execute", execute_spy)
# After orchestrator runs:
call_args = execute_spy.call_args_list[0]
stmt = call_args[0][0]
assert stmt._for_update_arg is not None   # SQLAlchemy Select._for_update_arg set by .with_for_update()
```

**For the idempotency test (ROADMAP success criterion 2):** The real behaviour can be tested with the in-memory SQLite DB — insert a `Conversation` row with `last_message_id = "msg-001"`, call `orchestrator.handle_message(..., message_id="msg-001")`, assert the conversation state did not change and no `Gasto` row was created. This does not require the lock to actually work — it tests the code path that checks `last_message_id`. [VERIFIED: extrapolated from conftest.py + ROADMAP]

**For concurrent access test (ROADMAP success criterion 3):** Because SQLite is single-threaded and has no real row locking, the concurrent-serialization test should:
1. Assert that `with_for_update(key_share=True)` is present on the SELECT (via monkeypatch spy).
2. Use an integration comment noting that real concurrency is validated against the Docker Postgres DB in Phase 2.

---

## Pattern 7: GastoService — Mirror InvoiceService

**Constructor:** `__init__(self) -> None:` with `self._log = structlog.get_logger()`. Stateless — caller passes session. [VERIFIED: backend/app/services/invoice.py]

```python
class GastoService:
    def __init__(self) -> None:
        self._log = structlog.get_logger()

    async def save_gasto(
        self,
        session: AsyncSession,
        draft: DraftGasto,
        sender_phone: str,
    ) -> Gasto:
        """Persist a confirmed gasto. Called only from ConversationOrchestrator.
        Session is passed in — GastoService does NOT open its own session.
        fecha defaults to today (D-02).
        """
        from datetime import date
        gasto = Gasto(
            fecha=date.today(),
            concepto=draft.concepto,
            monto=draft.monto,
            ticket_image_path=draft.ticket_image_path,
            sender_phone=sender_phone.replace("whatsapp:", "").strip(),
        )
        session.add(gasto)
        # Commit done by caller (orchestrator) — GastoService does not commit
        await session.flush()   # populate gasto.id before returning
        self._log.info("gasto.saved", id=str(gasto.id), monto=str(draft.monto))
        return gasto
```

**Note on commit ownership:** The orchestrator owns the transaction (`async with session.begin()`). `GastoService.save_gasto()` calls `session.flush()` (to get the id) but does NOT call `session.commit()`. The orchestrator's `session.begin()` context manager commits on clean exit. This mirrors how `InvoiceService.save_invoice()` calls `session.commit()` because it owns its own session lifecycle in the background task — here the orchestrator owns the session. [VERIFIED: backend/app/services/invoice.py lines 229-238]

---

## Pattern 8: Config Extension — AGENT_MODE + CONVERSATION_TIMEOUT_HOURS

**File to modify:** `backend/app/config.py`. Add to `Settings`:

```python
# Source: backend/app/config.py (inspected 2026-05-27) — add these fields

# Agent selection (D-09 — v2.0 demo isolation)
agent_mode: str = "gastos"   # "invoice" | "gastos"

# Conversation timeout in hours (D-08)
conversation_timeout_hours: int = 4
```

**No validator needed** — `agent_mode` defaults to `"gastos"`, so existing invoice deployments that don't set this env var are unaffected. The conditional registration in `create_app()` gates on `settings.agent_mode`:

```python
# Source: backend/app/main.py pattern (inspected 2026-05-27)
# In create_app():
if settings.agent_mode == "invoice":
    from app.routers.whatsapp import router as whatsapp_router
    app.include_router(whatsapp_router, prefix="/whatsapp", tags=["whatsapp"])
# gastos webhook router registered in Phase 2 when agent_mode == "gastos"
```

**conftest.py addition required:** Add `mp.setenv("AGENT_MODE", "gastos")` to the session-scoped `env_setup` fixture so the new required-by-default setting is available in all tests. [VERIFIED: backend/tests/conftest.py]

---

## Pattern 9: Alembic Migration Conventions

**Existing pattern:** Single `upgrade()` function calling `op.create_table()` + `op.create_index()` in sequence. Alembic autogenerate output is accepted then manually reviewed. `server_default=sa.text('now()')` for timestamp columns. [VERIFIED: backend/alembic/versions/0cd640399c29_initial_schema.py]

**Required addition:** After `op.create_table()` for each new table, add:
```python
op.execute("ALTER TABLE gastos ENABLE ROW LEVEL SECURITY")
op.execute("ALTER TABLE conversations ENABLE ROW LEVEL SECURITY")
op.execute("ALTER TABLE caja_cierres ENABLE ROW LEVEL SECURITY")
```

This mirrors the RLS requirement from Pitfall 3. [VERIFIED: .planning/research/PITFALLS.md P3]

**`conversations` table needs `UNIQUE` constraint (not just primary key):** `sender_phone` is the primary key, so uniqueness is enforced by the PK constraint. No separate unique index needed.

**Migration chain:** New migration's `down_revision` must point to the last existing migration. The current last migration is `add_is_active_server_default.py`. Confirm the revision ID by running `alembic heads` or reading the file.

---

## Pattern 10: SlotExtractionService System Prompt Design

**Key requirements for the prompt:**
- Instruct GPT to output a JSON number for `monto` (not a locale-formatted string): "Return monto as a plain number. Example: for 'mil quinientos pesos' return 1500. For '$1.500' return 1500."
- All fields Optional with null instruction: "If a field is not clearly stated, return null. Do NOT guess."
- Concepto: "Return the item or description of what was purchased, as stated by the user."
- Short Argentine Spanish intent context: "The user is a restaurant manager recording a cash expense in Argentine Spanish."

**Handling the concepto-only vs concepto+monto open intent:**
- If the manager sends "queso en supermercado $1500" → GPT returns `{concepto: "queso en supermercado", monto: 1500.0}`
- If the manager sends "Pago de queso" → GPT returns `{concepto: "queso", monto: null}` → orchestrator moves to `awaiting_monto`
- If the manager sends just "1500" when in `awaiting_monto` → GPT returns `{concepto: null, monto: 1500.0}` → orchestrator patches `draft.monto` only

**Re-extraction at `confirm` state (D-07):** Same `SlotExtractionService.extract()` call. Orchestrator patches only the non-null returned slots onto the existing `DraftGasto`. Null slots in the re-extraction result leave the existing draft field unchanged.

```python
def patch_draft(draft: DraftGasto, slots: GastoSlots) -> DraftGasto:
    """Apply non-null extracted slots onto existing draft. Never overwrite with null."""
    if slots.concepto is not None:
        draft.concepto = slots.concepto
    if slots.monto is not None:
        draft.monto = Decimal(str(slots.monto))
    return draft
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| GPT call to OpenAI | Custom HTTP requests | `client.chat.completions.parse()` (existing pattern) | Handles retries, auth, Pydantic deserialization |
| Pydantic model → JSON Schema for Structured Outputs | Manual JSON schema | `response_format=GastoSlots` in `.parse()` | `.parse()` converts Pydantic model automatically |
| Async DB session lifecycle | Manual connection management | `async_sessionmaker` + `async with session.begin()` | Already established in engine.py; handles rollback on exception |
| Row-level locking | Application-level mutex or asyncio.Lock | `select(...).with_for_update(key_share=True)` | DB-level lock survives restarts; asyncio.Lock does not |
| Settings validation | Manual os.environ checks | `pydantic_settings.BaseSettings` extension | Fail-fast with clear error messages; already established in config.py |
| Argentine number parsing | `float()` or `Decimal()` directly | `parse_ars_amount()` utility + GPT JSON number output | `Decimal("1.500")` = 1.5 trap is silent; custom parser required |

---

## Common Pitfalls

### Pitfall A: `Decimal("1.500")` Returns 1.5, Not 1500

**What goes wrong:** `Decimal("1.500")` evaluates to `Decimal('1.500')` = 1.5. If the orchestrator receives "1.500" from a user and passes it through `Decimal(text)`, the stored `monto` is $1.50 instead of $1,500.
**Why:** Python's `Decimal` treats dot as decimal separator.
**Avoid:** Use GPT `Optional[float]` schema as primary path (GPT normalises locale strings to JSON numbers). Only run `parse_ars_amount()` on raw text fallback paths.
**Test:** `assert parse_ars_amount("1.500") == Decimal("1500")` — in ROADMAP success criterion 5.

### Pitfall B: `FOR NO KEY UPDATE` Ignored by SQLite → Tests Give False Confidence

**What goes wrong:** SQLAlchemy with aiosqlite silently ignores `with_for_update(key_share=True)`. A test that relies on SQLite enforcing the lock will pass even if the orchestrator omits the lock entirely.
**Avoid:** Monkeypatch `session.execute` as a spy. Assert `stmt._for_update_arg is not None` on the SELECT call.
**Reference:** Pattern 6 above; mirrors `test_invoice_service.py` monkeypatch pattern.

### Pitfall C: WhatsApp Reply Sent Inside the DB Transaction

**What goes wrong:** If `provider.send_message()` is called inside `async with session.begin():`, the Postgres row lock is held for the entire network round-trip.
**Avoid:** Commit first, then send reply outside the transaction. See Pattern 5 orchestrator skeleton — reply is sent after `async with session_factory() as session:` block exits.

### Pitfall D: DraftGasto Required Fields Crash In-Progress Conversations on Deploy

**What goes wrong:** Adding a required (non-Optional) field to `DraftGasto` breaks `model_validate()` on existing `draft_gasto` JSON rows that don't have the new key. Every active conversation becomes stuck.
**Avoid:** All `DraftGasto` fields must be `Optional` with `default=None`. Orchestrator code enforces required-ness by re-prompting, not by Pydantic field requirement.

### Pitfall E: `updated_at` Not Auto-Updated by SQLAlchemy `onupdate` on JSON Patch

**What goes wrong:** SQLAlchemy `onupdate=func.now()` triggers when SQLAlchemy detects a column change. If the orchestrator only modifies `draft_gasto` (a `Text` column storing JSON), SQLAlchemy must detect that the field changed — using `conv.draft_gasto = new_json_string` does this; mutating a dict in-place on the Python object does NOT.
**Avoid:** Always reassign `conv.draft_gasto = draft.model_dump_json()` (string reassignment) rather than mutating a parsed dict. This ensures SQLAlchemy tracks the change and emits `updated_at` update. [ASSUMED — standard SQLAlchemy change-tracking behaviour]

### Pitfall F: `last_message_id` Idempotency Check Order

**What goes wrong:** If the orchestrator loads conversation state, dispatches to the state handler, and ONLY THEN checks `last_message_id`, a duplicate delivery can advance state before the check runs.
**Avoid:** `last_message_id` check is step 2 — immediately after acquiring the lock and before ANY state read. See Pattern 5 orchestrator skeleton.

### Pitfall G: `get_settings()` lru_cache Must Be Cleared in Test envs

**What goes wrong:** `AGENT_MODE` and `CONVERSATION_TIMEOUT_HOURS` are new env vars added to `Settings`. If `conftest.py`'s `env_setup` fixture does not set them before `get_settings()` is first called, the cache stores Settings without the new vars.
**Avoid:** Add `mp.setenv("AGENT_MODE", "gastos")` to the session-scoped `env_setup` fixture in `conftest.py`. The fixture already calls `get_settings.cache_clear()` — this is sufficient. [VERIFIED: backend/tests/conftest.py]

---

## State of the Art

| Old Approach | Current Approach | Impact for this Phase |
|--------------|------------------|----------------------|
| APScheduler in ARCHITECTURE.md snippets (4.x API) | Scheduler dropped for demo; manual trigger endpoint in Phase 3 | No APScheduler in Phase 1. Ignore scheduler snippets entirely. |
| `_processed_message_sids` in-memory set (v1.0) | `Conversation.last_message_id` DB column | Phase 1 must implement DB idempotency; never use in-memory set |
| `FOR UPDATE` in ARCHITECTURE.md code snippet | `FOR NO KEY UPDATE` (preferred) | Use `with_for_update(key_share=True)` — less blocking than `FOR UPDATE` |
| `LangGraph` / agent frameworks | Hand-rolled `match` + state constants | 5 states, linear flow — no library adds value |
| `gpt-4o` for slot extraction | `gpt-4o-mini` (D-06) | Cheaper/faster for short-text slot parsing; accuracy sufficient |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `StrEnum` is available (Python 3.11+). If project runs on 3.10, use plain string constants or `enum.StrEnum` backport. | Pattern 5 | Low — state stored as string regardless; enum is just a convenience |
| A2 | `stmt._for_update_arg` is the internal SQLAlchemy attribute set by `.with_for_update()`. This is an internal API; may change across SQLAlchemy 2.x minor versions. | Pattern 6 | Medium — test may need to use `str(stmt.compile(...))` instead |
| A3 | `failure_count` stored in `DraftGasto` JSON (not a separate `Conversation` column). This is the planner's discretion — a separate column is also valid. | Pattern 2 | Low — either works; JSON is simpler for Phase 1 |
| A4 | CajaCierre model created in Phase 1 (this migration). | Pattern 4 | Low — if deferred to Phase 2, migration must be created then instead |

---

## Open Questions (RESOLVED)

1. **`CajaCierre` in Phase 1 or Phase 2?** — **RESOLVED: Phase 1.**
   - The model has no orchestration logic; the reactive write is Phase 2.
   - Resolution: Plan 01-01 creates all three tables (gastos, conversations, caja_cierres) in one Alembic migration — no schema debt, no Phase 2 hard dependency on a follow-up migration.

2. **`with_for_update(key_share=True)` vs `with_for_update()`?** — **RESOLVED: `key_share=True`.**
   - `FOR NO KEY UPDATE` is preferred (SUMMARY.md, ARCHITECTURE.md); SQLAlchemy 2.0's `with_for_update(key_share=True)` maps to it.
   - Resolution: Plan 01-04 uses `with_for_update(key_share=True)` throughout. Wave 0 includes a dialect-compile check (`select(Conversation).with_for_update(key_share=True).compile(dialect=postgresql.dialect())` must emit `FOR NO KEY UPDATE`) so the parameter name is verified before relying on it.

3. **Orchestrator session ownership:** — **RESOLVED: orchestrator opens its own session.**
   - `process_invoice` in the existing `whatsapp.py` router opens its own session inside `asyncio.create_task` (ARCHITECTURE.md).
   - Resolution: the orchestrator opens its own session via `async with session_factory()` (consistent with the v1.0 background-task pattern). Tests inject a test-scoped aiosqlite `session_factory` (or a spy) per Pattern 5.

---

## Environment Availability

> Phase 1 is backend-only code with no new external dependencies. All tools already verified during v1.0 development.

| Dependency | Required By | Available | Notes |
|------------|------------|-----------|-------|
| Python 3.12 | Runtime | Verified (v1.0) | Project CLAUDE.md specifies 3.12 |
| asyncpg (prod) | Postgres async driver | Verified (v1.0) | `postgresql+asyncpg://` in DATABASE_URL |
| aiosqlite (tests) | In-memory test DB | Verified (v1.0) | Used in conftest.py |
| openai 2.36.0 | gpt-4o-mini .parse() | Verified (v1.0) | Same client, new schema |
| Docker + Postgres | Integration validation | Verified (v1.0) | Used for Alembic migration run |

**Missing dependencies with no fallback:** None.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (existing) |
| Config file | `backend/pyproject.toml` or `pytest.ini` (existing) |
| Quick run command | `cd backend && pytest tests/test_slot_extraction.py tests/test_gasto_service.py tests/test_conversation.py -x` |
| Full suite command | `cd backend && pytest` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CONV-01 | Conversation row persists across orchestrator calls | unit | `pytest tests/test_conversation.py::test_state_persists -x` | Wave 0 |
| CONV-02 | Duplicate message_id → no state advance, no Gasto row | unit | `pytest tests/test_conversation.py::test_idempotency -x` | Wave 0 |
| CONV-03 | `with_for_update(key_share=True)` issued on SELECT | unit (spy) | `pytest tests/test_conversation.py::test_row_lock_issued -x` | Wave 0 |
| CONV-04 | Old `updated_at` → state reset to idle, Spanish notice sent | unit | `pytest tests/test_conversation.py::test_timeout_reset -x` | Wave 0 |
| CONV-05 | `parse_ars_amount("1.500")` == 1500, `("1.234,56")` == 1234.56 | unit | `pytest tests/test_slot_extraction.py::test_parse_ars_amount -x` | Wave 0 |
| CONV-06 | 3 failures → example + cancel offer; GPT NOT called at confirm | unit | `pytest tests/test_conversation.py::test_reprompt_counter -x` | Wave 0 |
| GASTO-01 | Intent "queso $1500" → GastoSlots(concepto="queso", monto=1500.0) | unit (mocked GPT) | `pytest tests/test_slot_extraction.py::test_extract_intent -x` | Wave 0 |
| GASTO-02 | Missing monto → orchestrator moves to awaiting_monto, asks follow-up | unit | `pytest tests/test_conversation.py::test_full_flow_awaiting_monto -x` | Wave 0 |
| GASTO-04 | "sin ticket" at awaiting_ticket → advances to confirm, ticket_image_path=None | unit | `pytest tests/test_conversation.py::test_sin_ticket -x` | Wave 0 |
| GASTO-05 | "sí" at confirm → GastoService.save_gasto called, state=idle | unit | `pytest tests/test_conversation.py::test_confirm_saves_gasto -x` | Wave 0 |
| GASTO-06 | "cancelar" at any state → idle, no Gasto row | unit | `pytest tests/test_conversation.py::test_cancelar -x` | Wave 0 |

### Sampling Rate

- **Per task commit:** `cd backend && pytest tests/test_slot_extraction.py tests/test_gasto_service.py tests/test_conversation.py -x -q`
- **Per wave merge:** `cd backend && pytest`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `backend/tests/test_slot_extraction.py` — covers CONV-05, GASTO-01
- [ ] `backend/tests/test_gasto_service.py` — covers GASTO-05 persistence layer
- [ ] `backend/tests/test_conversation.py` — covers CONV-01..06, GASTO-02, 04, 05, 06
- [ ] `backend/tests/conftest.py` — add `mp.setenv("AGENT_MODE", "gastos")` to existing `env_setup` fixture (one line, existing file)

---

## Security Domain

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | yes | `GastoSlots` Pydantic model; `parse_ars_amount()` rejects non-numeric; orchestrator bounds-checks monto > 0 |
| V2 Authentication | no | No auth in Phase 1; allowlist gate is Phase 2 |
| V3 Session Management | partial | DB-backed conversation state; `last_message_id` prevents replay; timeout prevents stale state |
| V4 Access Control | no | Phase 2 (allowlist gate) |
| V6 Cryptography | no | No crypto in Phase 1 |

**Threat patterns relevant to Phase 1:**

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Monto hallucination / mis-extraction | Tampering | `Optional[float]` in GastoSlots; bounds check; mandatory confirmation step |
| Draft schema injection via `draft_gasto` JSON | Tampering | `DraftGasto.model_validate()` with try/except; reset to idle on ValidationError |
| Stale conversation state exploited after process restart | Spoofing | DB-backed `last_message_id`; `updated_at`-based timeout |
| `draft_gasto` visible in admin UI before confirmation | Info disclosure | Admin UI (Phase 4) must only show committed `gastos` rows |

---

## Sources

### Primary (HIGH confidence — direct codebase inspection)

- `backend/app/services/extraction.py` — `.parse()` pattern, constructor shape, structlog binding, refusal/parsed check order
- `backend/app/services/invoice.py` — stateless service pattern, session-as-argument, monkeypatch IntegrityError test pattern
- `backend/app/db/models.py` — DeclarativeBase, Mapped, dialect-agnostic Uuid, server_default timestamps with onupdate
- `backend/app/config.py` — Pydantic Settings, lru_cache pattern, env var defaults
- `backend/app/main.py` — create_app() factory, conditional router registration pattern
- `backend/app/db/engine.py` — get_async_session_local(), reset_engine_for_tests(), lazy init
- `backend/tests/conftest.py` — env_setup session fixture, monkeypatch pattern, aiosqlite test engine
- `backend/tests/test_invoice_service.py` — AsyncMock commit spy, db_session usage, full CRUD test pattern
- `backend/alembic/versions/0cd640399c29_initial_schema.py` — op.create_table, server_default, index creation

### Primary (HIGH confidence — prior v2.0 research)

- `.planning/research/PITFALLS.md` — P20 (idempotency), P21 (FOR NO KEY UPDATE), P22 (timeout), P25 (monto), P26 (Argentine number), P31 (confirmation), P32 (draft schema)
- `.planning/research/SUMMARY.md` — FOR NO KEY UPDATE vs FOR UPDATE clarification, confirmation affirmative set
- `.planning/research/ARCHITECTURE.md` — orchestrator skeleton, locking sequence, `with_for_update()` usage (note: ignore APScheduler 4.x snippets)
- `.planning/phases/01-data-conversation-core/01-CONTEXT.md` — D-01..D-09 locked decisions

### Secondary (MEDIUM confidence)

- `.planning/ROADMAP.md` — 6 success criteria that define exactly what must be testable
- `docs/plans/2026-05-27-gastos-bot-design.md` — data model spec, demo-build amendment confirming no APScheduler in Phase 1

---

## Metadata

**Confidence breakdown:**

| Area | Level | Reason |
|------|-------|--------|
| ORM model conventions | HIGH | Direct inspection of models.py + migration file |
| ExtractionService mirror pattern | HIGH | Direct inspection of extraction.py; identical pattern |
| InvoiceService mirror pattern | HIGH | Direct inspection of invoice.py + test_invoice_service.py |
| FOR NO KEY UPDATE test strategy | MEDIUM | Test approach is extrapolated from the monkeypatch pattern; actual SQLAlchemy internal attribute name for `_for_update_arg` tagged ASSUMED |
| GastoSlots schema design | HIGH | Derived from D-06 + P32 + existing ExtractedInvoice Optional pattern |
| parse_ars_amount() implementation | HIGH | Exact implementation from PITFALLS.md P26 |
| Confirmation affirmative set | HIGH | Exact set from PITFALLS.md P31 |
| State machine structure | HIGH | Derived from ARCHITECTURE.md + D-03/D-04/D-05 + ROADMAP success criteria |

**Research date:** 2026-05-27
**Valid until:** 2026-06-27 (all sources are internal project files — stable unless codebase changes)
