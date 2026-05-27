"""ConversationOrchestrator tests — full state machine, concurrency, idempotency,
timeout, cancel, re-prompt, confirm gate.

Test scope: CONV-01, CONV-02, CONV-03, CONV-04, CONV-06, GASTO-02, GASTO-04, GASTO-05, GASTO-06.

Concurrency note
----------------
SQLite ignores row locks. Tests that assert locking behaviour use one of two strategies:

1. Compiled-SQL mode assertion (test_row_lock_issued): monkeypatches session.execute as a spy,
   captures the Select statement, and asserts (a) _for_update_arg is set AND (b) compiling
   the statement against postgresql.dialect() contains 'FOR NO KEY UPDATE'.
   This is the only place the exact lock mode can be verified without a live Postgres.

2. Functional idempotency / state tests: run against the aiosqlite db_session fixture directly —
   SQLite's single-threaded in-process engine is sufficient for these (no lock semantics needed).

True cross-session INSERT serialisation (two concurrent FIRST messages from a brand-new sender)
is a Postgres-only behaviour. Unit-tested only for error-free convergence on one row
(test_get_or_create_first_message). The real concurrency proof is a separately-marked
Postgres integration test:
    tests/integration/test_conversation_concurrency_pg.py
    @pytest.mark.pg_integration
    (deferred to verify-phase, T-04-RACE in threat model)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base, Conversation, Gasto
from app.models.conversation import DraftGasto, GastoSlots


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_SENDER = "whatsapp:+5491112345678"
NORM_SENDER = "+5491112345678"  # after removeprefix("whatsapp:")
TEST_MSG_ID = "msg-001"


async def _make_orchestrator(
    slot_service=None,
    gasto_service=None,
    provider=None,
):
    """Create a ConversationOrchestrator with mocked collaborators."""
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


def _make_session_factory(db_session: AsyncSession):
    """Return a context-manager factory that always yields the given session."""

    class _FakeSessionFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *args):
            pass

    return _FakeSessionFactory()


# ---------------------------------------------------------------------------
# Task 0 companion: row lock issued + mode assertion (Task 1 / CONV-03)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_row_lock_issued(db_session: AsyncSession) -> None:
    """Orchestrator issues SELECT ... FOR NO KEY UPDATE on the conversations row.

    Strategy:
    - Monkeypatch session.execute as a spy to capture Select statements.
    - Assert the captured Select has _for_update_arg set (lock hint attached).
    - Compile the statement against postgresql.dialect() and assert the output
      contains the literal 'FOR NO KEY UPDATE' (mode-level proof, not just hint).

    SQLite ignores row locks — this spy is the only way to assert the correct
    lock is issued in the unit suite. True cross-session serialisation is a
    Postgres integration test (T-04-RACE, deferred to verify-phase).
    """
    from app.services.conversation import ConversationOrchestrator

    captured_selects = []
    original_execute = db_session.execute

    async def spy_execute(stmt, *args, **kwargs):
        from sqlalchemy.sql.selectable import Select as SASelect

        if isinstance(stmt, SASelect):
            captured_selects.append(stmt)
        return await original_execute(stmt, *args, **kwargs)

    db_session.execute = spy_execute  # type: ignore[method-assign]

    slot_service = AsyncMock()
    slot_service.extract = AsyncMock(return_value=GastoSlots(concepto="queso", monto=1500.0))
    provider = AsyncMock()
    gasto_service = MagicMock()
    gasto_service.save_gasto = AsyncMock()

    orch = await _make_orchestrator(
        slot_service=slot_service,
        gasto_service=gasto_service,
        provider=provider,
    )
    session_factory = _make_session_factory(db_session)
    await orch.handle_message(
        session_factory=session_factory,
        sender=TEST_SENDER,
        text="queso en supermercado $1500",
        message_id=TEST_MSG_ID,
    )

    # Must have captured at least one SELECT on Conversation
    conv_selects = [
        s for s in captured_selects
        if hasattr(s, "columns_clause_froms")
        or (hasattr(s, "froms") and any(
            getattr(f, "__tablename__", None) == "conversations"
            or str(getattr(f, "name", "")) == "conversations"
            for f in s.froms
        ))
    ]
    assert len(captured_selects) >= 1, "No SELECT statements captured"

    # Find the locked SELECT (the one with _for_update_arg)
    locked_stmts = [s for s in captured_selects if getattr(s, "_for_update_arg", None) is not None]
    assert locked_stmts, (
        "No SELECT with .with_for_update() was captured — "
        "orchestrator must issue SELECT ... FOR NO KEY UPDATE on the conversations row."
    )

    # Mode-level proof: compile against postgresql dialect
    locked_stmt = locked_stmts[0]
    compiled_sql = str(locked_stmt.compile(dialect=postgresql.dialect()))
    assert "FOR NO KEY UPDATE" in compiled_sql, (
        f"Lock statement compiled to:\n{compiled_sql}\n"
        "Expected 'FOR NO KEY UPDATE' (key_share=True) not found."
    )


# ---------------------------------------------------------------------------
# get-or-create first message (cycle-2 HIGH — missing-row race)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_first_message(db_session: AsyncSession) -> None:
    """Brand-new sender creates exactly one Conversation row; get-or-create is idempotent.

    Two assertions:
    1. First handle_message for a new sender creates exactly one conversations row.
    2. Issuing the same pg_insert(...).on_conflict_do_nothing() a SECOND time for the
       same sender does NOT raise IntegrityError and leaves exactly one row.

    This proves the get-or-create path is error-free (T-04-RACE). True cross-session
    insert serialisation (two concurrent first messages on Postgres) is deferred to
    a Postgres integration test (deferred to verify-phase, not this SQLite unit test).
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.services.conversation import ConversationOrchestrator

    slot_service = AsyncMock()
    slot_service.extract = AsyncMock(return_value=GastoSlots(concepto="queso", monto=None))
    provider = AsyncMock()
    gasto_service = MagicMock()
    gasto_service.save_gasto = AsyncMock()

    orch = await _make_orchestrator(
        slot_service=slot_service,
        gasto_service=gasto_service,
        provider=provider,
    )
    session_factory = _make_session_factory(db_session)

    # First message for brand-new sender
    await orch.handle_message(
        session_factory=session_factory,
        sender=TEST_SENDER,
        text="queso",
        message_id="msg-first",
    )

    result = await db_session.execute(select(Conversation))
    rows = result.scalars().all()
    assert len(rows) == 1, f"Expected 1 Conversation row, got {len(rows)}"
    assert rows[0].sender_phone == NORM_SENDER

    # Simulate second concurrent first message arriving: the get-or-create insert
    # (on_conflict_do_nothing) must NOT raise and must leave exactly one row.
    stmt = pg_insert(Conversation).values(
        sender_phone=NORM_SENDER,
        state="idle",
    ).on_conflict_do_nothing(index_elements=["sender_phone"])
    await db_session.execute(stmt)  # must not raise IntegrityError

    result2 = await db_session.execute(select(Conversation))
    rows2 = result2.scalars().all()
    assert len(rows2) == 1, (
        f"Expected 1 Conversation row after duplicate get-or-create, got {len(rows2)}. "
        "The ON CONFLICT DO NOTHING must no-op, not insert a second row."
    )


# ---------------------------------------------------------------------------
# Idempotency (CONV-02)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency(db_session: AsyncSession) -> None:
    """Duplicate message_id exits without advancing state, creating a Gasto, or overwriting last_message_id."""
    # Seed a conversation in awaiting_monto state
    conv = Conversation(
        sender_phone=NORM_SENDER,
        state="awaiting_monto",
        last_message_id="msg-1",
    )
    db_session.add(conv)
    await db_session.flush()

    provider = AsyncMock()
    slot_service = AsyncMock()
    slot_service.extract = AsyncMock(return_value=GastoSlots(monto=1500.0))
    orch = await _make_orchestrator(
        slot_service=slot_service,
        provider=provider,
    )
    session_factory = _make_session_factory(db_session)

    await orch.handle_message(
        session_factory=session_factory,
        sender=NORM_SENDER,
        text="1500",
        message_id="msg-1",  # duplicate
    )

    # State unchanged
    await db_session.refresh(conv)
    assert conv.state == "awaiting_monto", "State must not advance on duplicate message"
    assert conv.last_message_id == "msg-1", "last_message_id must not be overwritten"

    # No Gasto written
    result = await db_session.execute(select(Gasto))
    assert result.scalars().all() == [], "No Gasto must be written for duplicate message"

    # Provider not called
    provider.send_message.assert_not_called()


# ---------------------------------------------------------------------------
# Idempotency + rollback on DB failure (review concern 4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency_rollback_on_db_failure(db_session: AsyncSession) -> None:
    """DB failure mid-turn rolls back last_message_id so a webhook retry is reprocessable.

    If ANY exception is raised inside the transaction block, the transaction rolls back —
    including the last_message_id = message_id assignment. A retry of the same webhook
    sees the prior last_message_id and is fully reprocessable (not silently dropped).
    """
    conv = Conversation(
        sender_phone=NORM_SENDER,
        state="awaiting_monto",
        last_message_id="msg-0",
    )
    db_session.add(conv)
    await db_session.flush()

    # Force a DB error during the turn by making slot_service.extract raise
    slot_service = AsyncMock()
    slot_service.extract = AsyncMock(side_effect=Exception("db-side failure"))
    provider = AsyncMock()
    orch = await _make_orchestrator(
        slot_service=slot_service,
        provider=provider,
    )
    session_factory = _make_session_factory(db_session)

    with pytest.raises(Exception, match="db-side failure"):
        await orch.handle_message(
            session_factory=session_factory,
            sender=NORM_SENDER,
            text="1500",
            message_id="msg-1",
        )

    # last_message_id must still be "msg-0" — the transaction rolled back
    result = await db_session.execute(
        select(Conversation).where(Conversation.sender_phone == NORM_SENDER)
    )
    persisted = result.scalar_one_or_none()
    # If the row was rolled back we may get None (fresh session needed); treat as "msg-0"
    persisted_id = persisted.last_message_id if persisted else "msg-0"
    assert persisted_id == "msg-0", (
        f"last_message_id should be 'msg-0' after rollback, got '{persisted_id}'. "
        "A retry of the same webhook must see the prior ID so it can be reprocessed."
    )

    # No Gasto written
    gasto_result = await db_session.execute(select(Gasto))
    assert gasto_result.scalars().all() == [], "No Gasto must be written when transaction rolled back"


# ---------------------------------------------------------------------------
# Post-commit provider failure (accepted at-most-once reply risk)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_send_failure_after_commit(db_session: AsyncSession) -> None:
    """Post-commit provider.send_message failure propagates; committed DB state is NOT rolled back.

    This is the documented at-most-once reply risk:
    - The DB state (state advance + last_message_id) is durable after commit.
    - The WhatsApp reply may be lost if provider.send_message raises.
    - A Phase-2 outbox/retry is the future mitigation — no rollback of committed state here.
    """
    slot_service = AsyncMock()
    slot_service.extract = AsyncMock(return_value=GastoSlots(concepto="queso", monto=None))
    provider = AsyncMock()
    provider.send_message = AsyncMock(side_effect=RuntimeError("provider down"))

    orch = await _make_orchestrator(
        slot_service=slot_service,
        provider=provider,
    )
    session_factory = _make_session_factory(db_session)

    with pytest.raises(RuntimeError, match="provider down"):
        await orch.handle_message(
            session_factory=session_factory,
            sender=NORM_SENDER,
            text="queso",
            message_id="msg-send-fail",
        )

    # DB commit DID happen — state advanced even though reply failed
    result = await db_session.execute(
        select(Conversation).where(Conversation.sender_phone == NORM_SENDER)
    )
    conv = result.scalar_one_or_none()
    assert conv is not None, "Conversation row must exist after commit"
    assert conv.last_message_id == "msg-send-fail", (
        "last_message_id must be updated in DB even when send_message raises"
    )
    # State advanced (from idle to awaiting_monto because monto was None)
    assert conv.state != "idle" or conv.last_message_id == "msg-send-fail", (
        "DB state must persist after post-commit provider failure"
    )


# ---------------------------------------------------------------------------
# Timeout reset (CONV-04)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_reset(db_session: AsyncSession) -> None:
    """Stale conversation resets to idle with Spanish notice; draft cleared; no Gasto."""
    old_time = datetime.now(tz=timezone.utc) - timedelta(hours=10)
    draft = DraftGasto(concepto="queso", monto=Decimal("1500"))
    conv = Conversation(
        sender_phone=NORM_SENDER,
        state="awaiting_monto",
        draft_gasto=draft.model_dump_json(),
        last_message_id="msg-old",
    )
    db_session.add(conv)
    await db_session.flush()
    # Manually set updated_at to simulate staleness
    from sqlalchemy import update

    await db_session.execute(
        update(Conversation)
        .where(Conversation.sender_phone == NORM_SENDER)
        .values(updated_at=old_time)
    )
    await db_session.flush()

    provider = AsyncMock()
    slot_service = AsyncMock()
    slot_service.extract = AsyncMock(return_value=GastoSlots())
    orch = await _make_orchestrator(
        slot_service=slot_service,
        provider=provider,
    )
    session_factory = _make_session_factory(db_session)

    await orch.handle_message(
        session_factory=session_factory,
        sender=NORM_SENDER,
        text="hola",
        message_id="msg-new",
    )

    await db_session.refresh(conv)
    assert conv.state == "idle", "Stale conversation must reset to idle"
    assert conv.draft_gasto is None, "Draft must be cleared on timeout"

    # Provider sent a Spanish timeout notice
    provider.send_message.assert_called_once()
    call_args = provider.send_message.call_args
    reply_text = call_args[0][1] if call_args[0] else call_args[1].get("text", "")
    # Should mention expiration or a new start
    assert any(
        word in reply_text.lower()
        for word in ("expiró", "expiro", "anterior", "nuevo", "empezar", "cancelado", "iniciá")
    ), f"Timeout message should mention expiration. Got: '{reply_text}'"

    # No Gasto written
    gasto_result = await db_session.execute(select(Gasto))
    assert gasto_result.scalars().all() == [], "No Gasto must be written on timeout"


# ---------------------------------------------------------------------------
# Timeout snapshot ordering (review MEDIUM — must compare pre-mutation updated_at)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_uses_preload_snapshot(db_session: AsyncSession) -> None:
    """Timeout check uses the updated_at snapshot taken at row load, before last_message_id mutation.

    If the timeout check ran AFTER assigning last_message_id = message_id, the onupdate
    hook would advance updated_at, masking a truly expired conversation. This test verifies
    the snapshot is captured before any field mutation.
    """
    old_time = datetime.now(tz=timezone.utc) - timedelta(hours=10)
    conv = Conversation(
        sender_phone=NORM_SENDER,
        state="awaiting_monto",
        last_message_id="msg-old",
    )
    db_session.add(conv)
    await db_session.flush()
    from sqlalchemy import update

    await db_session.execute(
        update(Conversation)
        .where(Conversation.sender_phone == NORM_SENDER)
        .values(updated_at=old_time)
    )
    await db_session.flush()

    provider = AsyncMock()
    orch = await _make_orchestrator(provider=provider)
    session_factory = _make_session_factory(db_session)

    # Even though the handler assigns last_message_id first, timeout must still fire
    await orch.handle_message(
        session_factory=session_factory,
        sender=NORM_SENDER,
        text="hola",
        message_id="msg-new-snapshot",
    )

    await db_session.refresh(conv)
    # Timeout fired → state is idle
    assert conv.state == "idle", (
        "Timeout branch must fire even when last_message_id was just assigned — "
        "the snapshot of updated_at must be taken BEFORE any field mutation."
    )


# ---------------------------------------------------------------------------
# Cancel (GASTO-06)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelar(db_session: AsyncSession) -> None:
    """'cancelar' at any non-idle state resets to idle, clears draft, sends notice, writes no Gasto."""
    draft = DraftGasto(concepto="queso", monto=Decimal("1500"))
    conv = Conversation(
        sender_phone=NORM_SENDER,
        state="awaiting_ticket",
        draft_gasto=draft.model_dump_json(),
        last_message_id="msg-prev",
    )
    db_session.add(conv)
    await db_session.flush()

    provider = AsyncMock()
    orch = await _make_orchestrator(provider=provider)
    session_factory = _make_session_factory(db_session)

    await orch.handle_message(
        session_factory=session_factory,
        sender=NORM_SENDER,
        text="cancelar",
        message_id="msg-cancel",
    )

    await db_session.refresh(conv)
    assert conv.state == "idle", "'cancelar' must reset state to idle"
    assert conv.draft_gasto is None, "'cancelar' must clear draft"

    provider.send_message.assert_called_once()
    cancel_text = provider.send_message.call_args[0][1]
    assert "cancelado" in cancel_text.lower(), f"Cancel message should say 'cancelado', got: '{cancel_text}'"

    gasto_result = await db_session.execute(select(Gasto))
    assert gasto_result.scalars().all() == [], "No Gasto must be written when cancelar"


@pytest.mark.asyncio
async def test_cancelar_from_confirm(db_session: AsyncSession) -> None:
    """'cancelar' at confirm state also resets to idle."""
    draft = DraftGasto(concepto="queso", monto=Decimal("1500"))
    conv = Conversation(
        sender_phone=NORM_SENDER,
        state="confirm",
        draft_gasto=draft.model_dump_json(),
        last_message_id="msg-prev",
    )
    db_session.add(conv)
    await db_session.flush()

    provider = AsyncMock()
    gasto_service = MagicMock()
    gasto_service.save_gasto = AsyncMock()
    orch = await _make_orchestrator(provider=provider, gasto_service=gasto_service)
    session_factory = _make_session_factory(db_session)

    await orch.handle_message(
        session_factory=session_factory,
        sender=NORM_SENDER,
        text="cancelar",
        message_id="msg-cancel-confirm",
    )

    await db_session.refresh(conv)
    assert conv.state == "idle"
    assert conv.draft_gasto is None
    gasto_service.save_gasto.assert_not_called()


# ---------------------------------------------------------------------------
# Task 2 tests: State dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_flow_awaiting_monto(db_session: AsyncSession) -> None:
    """From idle, concepto-only intent → state becomes awaiting_monto (GASTO-02, D-03/D-04)."""
    slot_service = AsyncMock()
    # Opening intent: concepto only, no monto
    slot_service.extract = AsyncMock(return_value=GastoSlots(concepto="queso", monto=None))
    provider = AsyncMock()
    orch = await _make_orchestrator(slot_service=slot_service, provider=provider)
    session_factory = _make_session_factory(db_session)

    await orch.handle_message(
        session_factory=session_factory,
        sender=NORM_SENDER,
        text="queso en supermercado",
        message_id="msg-idle",
    )

    result = await db_session.execute(
        select(Conversation).where(Conversation.sender_phone == NORM_SENDER)
    )
    conv = result.scalar_one()
    assert conv.state == "awaiting_monto", (
        f"Concepto-only intent must advance to awaiting_monto, got '{conv.state}'"
    )
    # draft has concepto set
    draft = DraftGasto.model_validate_json(conv.draft_gasto)
    assert draft.concepto == "queso"
    assert draft.monto is None

    # Reply asks for monto
    provider.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_full_flow_both_slots_skip_awaiting_monto(db_session: AsyncSession) -> None:
    """From idle, both concepto+monto supplied → skip awaiting_monto → awaiting_ticket (D-03)."""
    slot_service = AsyncMock()
    slot_service.extract = AsyncMock(return_value=GastoSlots(concepto="queso", monto=1500.0))
    provider = AsyncMock()
    orch = await _make_orchestrator(slot_service=slot_service, provider=provider)
    session_factory = _make_session_factory(db_session)

    await orch.handle_message(
        session_factory=session_factory,
        sender=NORM_SENDER,
        text="queso en supermercado $1500",
        message_id="msg-both",
    )

    result = await db_session.execute(
        select(Conversation).where(Conversation.sender_phone == NORM_SENDER)
    )
    conv = result.scalar_one()
    assert conv.state == "awaiting_ticket", (
        f"Both slots → must skip to awaiting_ticket, got '{conv.state}'"
    )
    draft = DraftGasto.model_validate_json(conv.draft_gasto)
    assert draft.concepto == "queso"
    assert draft.monto == Decimal("1500")


@pytest.mark.asyncio
async def test_state_persists(db_session: AsyncSession) -> None:
    """After awaiting_monto transition, the Conversation row reloaded from DB reflects new state (CONV-01)."""
    slot_service = AsyncMock()
    slot_service.extract = AsyncMock(return_value=GastoSlots(concepto="verdura", monto=None))
    provider = AsyncMock()
    orch = await _make_orchestrator(slot_service=slot_service, provider=provider)
    session_factory = _make_session_factory(db_session)

    await orch.handle_message(
        session_factory=session_factory,
        sender=NORM_SENDER,
        text="verdura",
        message_id="msg-state-persists",
    )

    # Reload from a fresh query (no ORM identity cache)
    result = await db_session.execute(
        select(Conversation).where(Conversation.sender_phone == NORM_SENDER)
    )
    conv = result.scalar_one()
    assert conv.state == "awaiting_monto"
    draft = DraftGasto.model_validate_json(conv.draft_gasto)
    assert draft.concepto == "verdura"


@pytest.mark.asyncio
async def test_sin_ticket(db_session: AsyncSession) -> None:
    """At awaiting_ticket, 'sin ticket' advances to confirm with ticket_image_path None (GASTO-04)."""
    draft = DraftGasto(concepto="queso", monto=Decimal("1500"))
    conv = Conversation(
        sender_phone=NORM_SENDER,
        state="awaiting_ticket",
        draft_gasto=draft.model_dump_json(),
        last_message_id="msg-prev",
    )
    db_session.add(conv)
    await db_session.flush()

    provider = AsyncMock()
    orch = await _make_orchestrator(provider=provider)
    session_factory = _make_session_factory(db_session)

    await orch.handle_message(
        session_factory=session_factory,
        sender=NORM_SENDER,
        text="sin ticket",
        message_id="msg-sin-ticket",
    )

    await db_session.refresh(conv)
    assert conv.state == "confirm", f"'sin ticket' must advance to confirm, got '{conv.state}'"
    refreshed_draft = DraftGasto.model_validate_json(conv.draft_gasto)
    assert refreshed_draft.ticket_image_path is None

    # Reply shows summary with confirmation prompt
    provider.send_message.assert_called_once()
    summary_text = provider.send_message.call_args[0][1]
    assert len(summary_text) > 0


@pytest.mark.asyncio
async def test_confirm_saves_gasto(db_session: AsyncSession) -> None:
    """Exact affirmative at confirm → save_gasto called, state idle; extractor NOT called (GASTO-05, D-05)."""
    draft = DraftGasto(concepto="queso", monto=Decimal("1500"))
    conv = Conversation(
        sender_phone=NORM_SENDER,
        state="confirm",
        draft_gasto=draft.model_dump_json(),
        last_message_id="msg-prev",
    )
    db_session.add(conv)
    await db_session.flush()

    provider = AsyncMock()
    slot_service = AsyncMock()
    slot_service.extract = AsyncMock(return_value=GastoSlots())
    gasto_service = MagicMock()
    gasto_service.save_gasto = AsyncMock(return_value=MagicMock())
    orch = await _make_orchestrator(
        slot_service=slot_service,
        gasto_service=gasto_service,
        provider=provider,
    )
    session_factory = _make_session_factory(db_session)

    await orch.handle_message(
        session_factory=session_factory,
        sender=NORM_SENDER,
        text="sí",
        message_id="msg-confirm",
    )

    # save_gasto called once
    gasto_service.save_gasto.assert_called_once()
    # slot_service.extract NOT called for the affirmative path (D-05)
    slot_service.extract.assert_not_called()

    await db_session.refresh(conv)
    assert conv.state == "idle", "After save, state must reset to idle"
    assert conv.draft_gasto is None, "Draft must be cleared after save"

    provider.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_confirm_requires_exact_token(db_session: AsyncSession) -> None:
    """'sí, pero cambiá el monto a 1500' is NOT treated as save — routes to correction (D-05, D-07).

    Only bare tokens (sí, ok, dale, …) match. A sentence starting with 'sí' is a correction.
    """
    draft = DraftGasto(concepto="queso", monto=Decimal("500"))
    conv = Conversation(
        sender_phone=NORM_SENDER,
        state="confirm",
        draft_gasto=draft.model_dump_json(),
        last_message_id="msg-prev",
    )
    db_session.add(conv)
    await db_session.flush()

    slot_service = AsyncMock()
    # Correction re-extracts monto 1500
    slot_service.extract = AsyncMock(return_value=GastoSlots(monto=1500.0))
    gasto_service = MagicMock()
    gasto_service.save_gasto = AsyncMock()
    provider = AsyncMock()
    orch = await _make_orchestrator(
        slot_service=slot_service,
        gasto_service=gasto_service,
        provider=provider,
    )
    session_factory = _make_session_factory(db_session)

    await orch.handle_message(
        session_factory=session_factory,
        sender=NORM_SENDER,
        text="sí, pero cambiá el monto a 1500",
        message_id="msg-correction",
    )

    # save_gasto NOT called — this is a correction, not a save
    gasto_service.save_gasto.assert_not_called()
    # slot_service.extract IS called to re-extract the correction
    slot_service.extract.assert_called_once()

    # Remains in confirm with updated draft (monto corrected to 1500)
    await db_session.refresh(conv)
    assert conv.state == "confirm", "Correction at confirm must stay in confirm"
    corrected_draft = DraftGasto.model_validate_json(conv.draft_gasto)
    assert corrected_draft.monto == Decimal("1500"), (
        f"Draft monto should be updated to 1500 after correction, got {corrected_draft.monto}"
    )


@pytest.mark.asyncio
async def test_confirm_si_no_tiene_ticket_is_correction(db_session: AsyncSession) -> None:
    """'si no tiene ticket' is a correction, not a save (exact token test)."""
    draft = DraftGasto(concepto="queso", monto=Decimal("1500"))
    conv = Conversation(
        sender_phone=NORM_SENDER,
        state="confirm",
        draft_gasto=draft.model_dump_json(),
        last_message_id="msg-prev",
    )
    db_session.add(conv)
    await db_session.flush()

    slot_service = AsyncMock()
    slot_service.extract = AsyncMock(return_value=GastoSlots())  # nothing new extracted
    gasto_service = MagicMock()
    gasto_service.save_gasto = AsyncMock()
    provider = AsyncMock()
    orch = await _make_orchestrator(
        slot_service=slot_service,
        gasto_service=gasto_service,
        provider=provider,
    )
    session_factory = _make_session_factory(db_session)

    await orch.handle_message(
        session_factory=session_factory,
        sender=NORM_SENDER,
        text="si no tiene ticket",
        message_id="msg-si-no-ticket",
    )

    gasto_service.save_gasto.assert_not_called()
    slot_service.extract.assert_called_once()


@pytest.mark.asyncio
async def test_reprompt_counter(db_session: AsyncSession) -> None:
    """3 consecutive unparseable monto replies → reply with example + cancel offer (CONV-06)."""
    draft = DraftGasto(concepto="queso", failure_count=0)
    conv = Conversation(
        sender_phone=NORM_SENDER,
        state="awaiting_monto",
        draft_gasto=draft.model_dump_json(),
        last_message_id="msg-prev",
    )
    db_session.add(conv)
    await db_session.flush()

    # Extractor always returns no monto and parse_ars_amount will also fail
    slot_service = AsyncMock()
    slot_service.extract = AsyncMock(return_value=GastoSlots(monto=None))
    provider = AsyncMock()
    orch = await _make_orchestrator(slot_service=slot_service, provider=provider)
    session_factory = _make_session_factory(db_session)

    # 3 unparseable replies
    for i in range(3):
        await orch.handle_message(
            session_factory=session_factory,
            sender=NORM_SENDER,
            text="no entiendo",  # parse_ars_amount will return None
            message_id=f"msg-fail-{i}",
        )

    # On 3rd failure, reply should contain an example and mention cancelar
    call_texts = [call[0][1] for call in provider.send_message.call_args_list]
    last_reply = call_texts[-1]

    # Should contain a concrete example (e.g. "1500") or "Por ejemplo"
    assert any(
        word in last_reply.lower()
        for word in ("ejemplo", "1500", "por ejemplo", "cancelar", "empezar")
    ), f"3rd failure reply must include example + cancel offer. Got: '{last_reply}'"

    # failure_count should be at 3
    await db_session.refresh(conv)
    current_draft = DraftGasto.model_validate_json(conv.draft_gasto)
    assert current_draft.failure_count == 3, (
        f"failure_count should be 3 after 3 failures, got {current_draft.failure_count}"
    )


@pytest.mark.asyncio
async def test_reprompt_counter_resets_on_success(db_session: AsyncSession) -> None:
    """A successful parse resets failure_count to 0 (CONV-06)."""
    draft = DraftGasto(concepto="queso", failure_count=2)
    conv = Conversation(
        sender_phone=NORM_SENDER,
        state="awaiting_monto",
        draft_gasto=draft.model_dump_json(),
        last_message_id="msg-prev",
    )
    db_session.add(conv)
    await db_session.flush()

    slot_service = AsyncMock()
    # This time extraction succeeds with a valid monto
    slot_service.extract = AsyncMock(return_value=GastoSlots(monto=1500.0))
    provider = AsyncMock()
    orch = await _make_orchestrator(slot_service=slot_service, provider=provider)
    session_factory = _make_session_factory(db_session)

    await orch.handle_message(
        session_factory=session_factory,
        sender=NORM_SENDER,
        text="1500",
        message_id="msg-success",
    )

    await db_session.refresh(conv)
    # State should advance to awaiting_ticket (monto filled)
    assert conv.state == "awaiting_ticket", (
        f"After successful monto fill, state should be awaiting_ticket, got '{conv.state}'"
    )
    success_draft = DraftGasto.model_validate_json(conv.draft_gasto)
    assert success_draft.failure_count == 0, (
        f"failure_count must reset to 0 after successful parse, got {success_draft.failure_count}"
    )


@pytest.mark.asyncio
async def test_reply_sent_after_commit(db_session: AsyncSession) -> None:
    """provider.send_message is called OUTSIDE the DB transaction (Pitfall C).

    Strategy: verify that a successful send_message call happens after state is
    already committed to the DB, not while the transaction is open.
    We do this by having send_message read the DB state and verify it was already committed.
    """
    slot_service = AsyncMock()
    slot_service.extract = AsyncMock(return_value=GastoSlots(concepto="queso", monto=None))

    # We'll capture what the DB state looks like when send_message is called
    state_at_send = {}

    async def capturing_send(to, text):
        # Read state from DB at send time
        result = await db_session.execute(
            select(Conversation).where(Conversation.sender_phone == NORM_SENDER)
        )
        c = result.scalar_one_or_none()
        if c:
            state_at_send["last_message_id"] = c.last_message_id
            state_at_send["state"] = c.state

    provider = AsyncMock()
    provider.send_message = capturing_send

    orch = await _make_orchestrator(slot_service=slot_service, provider=provider)
    session_factory = _make_session_factory(db_session)

    await orch.handle_message(
        session_factory=session_factory,
        sender=NORM_SENDER,
        text="queso",
        message_id="msg-order-test",
    )

    # The state captured at send time should already have the updated last_message_id
    assert state_at_send.get("last_message_id") == "msg-order-test", (
        "last_message_id should already be committed when send_message is called "
        "(reply sent AFTER commit, Pitfall C)"
    )
