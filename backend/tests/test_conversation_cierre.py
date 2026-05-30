"""RED tests for Phase 3 CAJA-01 and CAJA-02 requirements.

Tests:
  CAJA-01 FSM transitions:
    - Bare amount in AWAITING_CIERRE → AWAITING_CIERRE_CONFIRM
    - Gasto intent in AWAITING_CIERRE → gasto flow (handoff)
    - Affirmative in AWAITING_CIERRE_CONFIRM → CajaCierre row written, IDLE
    - Non-affirmative in AWAITING_CIERRE_CONFIRM → no write, re-echo
  CAJA-02 hora_cierre + fecha:
    - Before 14:30 ART → "12:00"
    - At/after 14:30 ART → "17:00"
    - fecha is ART date (not UTC)
    - Duplicate inserts allowed (no unique constraint)

Wave 0 RED phase: tests that reference ConvState.AWAITING_CIERRE,
ConvState.AWAITING_CIERRE_CONFIRM, or DraftCierre will error at runtime until
Plan 03 adds those symbols. Imports of not-yet-existing symbols are deferred to
test bodies so that pytest --collect-only succeeds without ImportError.

Note on test_fecha_art_not_utc: We drive CajaCierreService.save_cierre directly
with a real db_session. This test is RED because save_cierre raises
NotImplementedError in the Wave 0 skeleton (Plan 03 fills the implementation).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.db.models import Conversation
from app.models.conversation import DraftGasto, GastoSlots

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_SENDER = "whatsapp:+5491112345678"
NORM_SENDER = "+5491112345678"
_ART = ZoneInfo("America/Argentina/Buenos_Aires")


# ---------------------------------------------------------------------------
# Helpers (verbatim from test_conversation.py)
# ---------------------------------------------------------------------------


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


def _make_session_factory(db_session):
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
# CAJA-01: FSM transition tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bare_amount_advances_to_confirm(db_session):
    """Bare amount in AWAITING_CIERRE → state becomes AWAITING_CIERRE_CONFIRM."""
    # Import AWAITING_CIERRE inside test body so collection works before Plan 03
    from app.services.conversation import ConvState

    conv = Conversation(sender_phone=NORM_SENDER, state=ConvState.AWAITING_CIERRE)
    db_session.add(conv)
    await db_session.commit()  # commit so orchestrator can begin its own transaction

    orch = await _make_orchestrator()
    sf = _make_session_factory(db_session)
    await orch.handle_message(sf, TEST_SENDER, "1500", "msg-cierre-001")

    await db_session.refresh(conv)
    assert conv.state == ConvState.AWAITING_CIERRE_CONFIRM, (
        f"Expected AWAITING_CIERRE_CONFIRM, got {conv.state!r}"
    )
    # draft_gasto should hold the parsed amount
    assert conv.draft_gasto is not None, "draft_gasto must be set after bare amount"
    assert "1500" in conv.draft_gasto, f"Amount not found in draft: {conv.draft_gasto!r}"


@pytest.mark.asyncio
async def test_gasto_intent_handoff(db_session):
    """Gasto intent in AWAITING_CIERRE → orchestrator routes into the gasto/idle flow.

    parse_ars_amount must return None (non-bare-amount text) so the handler falls
    through to GPT slot extraction. Slot service returns a GastoSlots with concepto
    set → handoff to gasto flow. State moves out of AWAITING_CIERRE into a gasto path.
    """
    from app.services.conversation import ConvState

    # Seed conversation in AWAITING_CIERRE
    conv = Conversation(sender_phone=NORM_SENDER, state=ConvState.AWAITING_CIERRE)
    db_session.add(conv)
    await db_session.commit()  # commit so orchestrator can begin its own transaction

    # Slot service returns a gasto intent (concepto set)
    slot_service = AsyncMock()
    slot_service.extract = AsyncMock(
        return_value=GastoSlots(concepto="queso", monto=None)
    )

    orch = await _make_orchestrator(slot_service=slot_service)
    sf = _make_session_factory(db_session)

    # Use text that parse_ars_amount will NOT parse as a bare amount
    await orch.handle_message(sf, TEST_SENDER, "pagué queso en el super", "msg-gasto-001")

    await db_session.refresh(conv)
    # State should have moved out of AWAITING_CIERRE into a gasto path
    assert conv.state != ConvState.AWAITING_CIERRE, (
        f"State must have transitioned away from AWAITING_CIERRE, got {conv.state!r}"
    )
    assert conv.state != ConvState.AWAITING_CIERRE_CONFIRM, (
        f"State must NOT be AWAITING_CIERRE_CONFIRM after gasto handoff, got {conv.state!r}"
    )
    # Verify slot_service.extract WAS called (gasto path triggered GPT)
    slot_service.extract.assert_awaited()


@pytest.mark.asyncio
async def test_confirm_saves_cierre(db_session):
    """Affirmative in AWAITING_CIERRE_CONFIRM → CajaCierre row written, state IDLE.

    Seeds a conversation in AWAITING_CIERRE_CONFIRM with a DraftCierre JSON in
    draft_gasto. After an affirmative reply, a CajaCierre row must exist and
    conv.state must be IDLE.
    """
    from sqlalchemy import select as sa_select

    from app.db.models import CajaCierre
    from app.services.conversation import ConvState

    # DraftCierre import deferred — may not exist until Plan 03
    # We write the JSON directly using the expected schema
    cierre_draft_json = '{"cierre_monto": "1500.00"}'

    conv = Conversation(
        sender_phone=NORM_SENDER,
        state=ConvState.AWAITING_CIERRE_CONFIRM,
        draft_gasto=cierre_draft_json,
    )
    db_session.add(conv)
    await db_session.commit()  # commit so orchestrator can begin its own transaction

    orch = await _make_orchestrator()
    sf = _make_session_factory(db_session)
    await orch.handle_message(sf, TEST_SENDER, "sí", "msg-confirm-001")

    await db_session.refresh(conv)
    assert conv.state == ConvState.IDLE, (
        f"Expected IDLE after confirm, got {conv.state!r}"
    )
    assert conv.draft_gasto is None, "draft_gasto must be cleared after confirm"

    result = await db_session.execute(
        sa_select(CajaCierre).where(CajaCierre.sender_phone == NORM_SENDER)
    )
    cierre = result.scalar_one_or_none()
    assert cierre is not None, "A CajaCierre row must exist after confirmation"
    assert cierre.efectivo_en_caja == Decimal("1500.00"), (
        f"Expected 1500.00, got {cierre.efectivo_en_caja!r}"
    )


@pytest.mark.asyncio
async def test_confirm_requires_exact_token(db_session):
    """Non-affirmative reply in AWAITING_CIERRE_CONFIRM → no write, re-echo.

    Verifies:
    - No CajaCierre row is written
    - Conversation stays in AWAITING_CIERRE_CONFIRM
    - slot_service.extract is NOT awaited at the confirm gate (deterministic gate,
      no GPT at the write boundary)
    """
    from sqlalchemy import select as sa_select

    from app.db.models import CajaCierre
    from app.services.conversation import ConvState

    cierre_draft_json = '{"cierre_monto": "1500.00"}'

    conv = Conversation(
        sender_phone=NORM_SENDER,
        state=ConvState.AWAITING_CIERRE_CONFIRM,
        draft_gasto=cierre_draft_json,
    )
    db_session.add(conv)
    await db_session.commit()  # commit so orchestrator can begin its own transaction

    slot_service = AsyncMock()
    slot_service.extract = AsyncMock(return_value=GastoSlots())

    orch = await _make_orchestrator(slot_service=slot_service)
    sf = _make_session_factory(db_session)
    await orch.handle_message(sf, TEST_SENDER, "tal vez", "msg-nonconfirm-001")

    await db_session.refresh(conv)
    # State must remain in the confirm state
    assert conv.state == ConvState.AWAITING_CIERRE_CONFIRM, (
        f"State must stay AWAITING_CIERRE_CONFIRM on non-affirmative, got {conv.state!r}"
    )

    # No CajaCierre row written
    result = await db_session.execute(
        sa_select(CajaCierre).where(CajaCierre.sender_phone == NORM_SENDER)
    )
    cierre = result.scalar_one_or_none()
    assert cierre is None, "No CajaCierre row must be written on non-affirmative reply"

    # GPT must NOT be invoked at the confirm gate (deterministic gate)
    slot_service.extract.assert_not_awaited()


# ---------------------------------------------------------------------------
# CAJA-02: hora_cierre derivation tests (pure function — implemented in Wave 0)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hora_cierre_morning(db_session):
    """hora_cierre = '12:00' when ART time is before 14:30."""
    mock_time = datetime(2026, 5, 30, 11, 0, tzinfo=_ART)

    with patch("app.services.cierre.datetime") as mock_dt:
        mock_dt.now.return_value = mock_time
        from app.services.cierre import _derive_hora_cierre

        result = _derive_hora_cierre()

    assert result == "12:00", f"Expected '12:00' at 11:00 ART, got {result!r}"


@pytest.mark.asyncio
async def test_hora_cierre_afternoon(db_session):
    """hora_cierre = '17:00' when ART time is at/after 14:30 (boundary inclusive)."""
    mock_time = datetime(2026, 5, 30, 14, 30, tzinfo=_ART)  # exactly at cutoff

    with patch("app.services.cierre.datetime") as mock_dt:
        mock_dt.now.return_value = mock_time
        from app.services.cierre import _derive_hora_cierre

        result = _derive_hora_cierre()

    assert result == "17:00", f"Expected '17:00' at 14:30 ART (boundary), got {result!r}"


@pytest.mark.asyncio
async def test_fecha_art_not_utc(db_session):
    """fecha saved by save_cierre is the ART date, not the UTC date.

    Uses an ART time that falls on a *different calendar day* than UTC:
      2026-05-31 02:00 UTC = 2026-05-30 23:00 ART
    UTC date: 2026-05-31 (tomorrow)
    ART date: 2026-05-30 (today in Argentina)

    Drives CajaCierreService.save_cierre directly with a real db_session.
    This test is RED in Wave 0 because save_cierre raises NotImplementedError —
    it becomes GREEN when Plan 03 provides the implementation.
    """
    from sqlalchemy import select as sa_select

    from app.db.models import CajaCierre
    from app.services.cierre import CajaCierreService, _today_art

    # UTC time: 2026-05-31 02:00 → ART (UTC-3): 2026-05-30 23:00
    # So ART date is 2026-05-30 but UTC date is 2026-05-31
    art_time = datetime(2026, 5, 30, 23, 0, tzinfo=_ART)
    expected_art_date = art_time.date()  # 2026-05-30

    with patch("app.services.cierre.datetime") as mock_dt:
        mock_dt.now.return_value = art_time
        # _today_art() uses datetime.now(_ART).date() — must return 2026-05-30
        today = _today_art()
        assert today == expected_art_date, (
            f"_today_art() returned {today!r}, expected {expected_art_date!r}"
        )

        svc = CajaCierreService()
        await svc.save_cierre(
            session=db_session,
            efectivo_en_caja=Decimal("2000.00"),
            sender_phone=NORM_SENDER,
        )

    result = await db_session.execute(
        sa_select(CajaCierre).where(CajaCierre.sender_phone == NORM_SENDER)
    )
    cierre = result.scalar_one_or_none()
    assert cierre is not None, "CajaCierre row must exist after save_cierre"
    assert cierre.fecha == expected_art_date, (
        f"fecha must be ART date {expected_art_date}, got {cierre.fecha!r}"
    )


@pytest.mark.asyncio
async def test_duplicate_cierres_allowed(db_session):
    """Two save_cierre calls for same (fecha, hora_cierre) → 2 rows, no IntegrityError.

    Confirms there is no UNIQUE constraint on (fecha, hora_cierre) — inserts are
    append-only and the UI shows the latest.

    This test is RED in Wave 0 because save_cierre raises NotImplementedError.
    """
    from sqlalchemy import func, select as sa_select

    from app.db.models import CajaCierre
    from app.services.cierre import CajaCierreService

    # Freeze time so both calls get the same hora_cierre and fecha
    fixed_time = datetime(2026, 5, 30, 11, 0, tzinfo=_ART)

    svc = CajaCierreService()

    with patch("app.services.cierre.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_time

        await svc.save_cierre(
            session=db_session,
            efectivo_en_caja=Decimal("1500.00"),
            sender_phone=NORM_SENDER,
        )
        await svc.save_cierre(
            session=db_session,
            efectivo_en_caja=Decimal("1600.00"),
            sender_phone=NORM_SENDER,
        )

    result = await db_session.execute(
        sa_select(func.count()).select_from(CajaCierre).where(
            CajaCierre.sender_phone == NORM_SENDER
        )
    )
    count = result.scalar_one()
    assert count == 2, (
        f"Expected 2 CajaCierre rows (no unique constraint), got {count}"
    )
