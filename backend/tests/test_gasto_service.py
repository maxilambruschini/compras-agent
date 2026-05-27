"""Unit tests for GastoService.save_gasto (TDD RED → GREEN).

Analog: test_invoice_service.py — db_session aiosqlite fixture, monkeypatch commit pattern.

Behaviors tested:
- One gastos row inserted with fecha=date.today(), correct concepto/monto/ticket_image_path
- sender_phone "whatsapp:" prefix stripped via removeprefix (not .replace/.strip)
- Double-prefix "whatsapp:whatsapp:+549..." stripped to one bare number
- No prefix "+549..." left untouched (removeprefix is idempotent on non-matching prefix)
- save_gasto does NOT commit — returns a Gasto with populated id (flushed only)
- ticket_image_path=None on the draft yields None in the DB row (GASTO-04)
- GastoService is stateless (holds no session reference)
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Gasto
from app.models.conversation import DraftGasto
from app.services.gasto import GastoService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_draft(
    concepto: str = "queso en supermercado",
    monto: Decimal = Decimal("1500.00"),
    ticket_image_path: str | None = "/tmp/tickets/SM-test.jpg",
    failure_count: int = 0,
) -> DraftGasto:
    """Build a DraftGasto for testing."""
    return DraftGasto(
        concepto=concepto,
        monto=monto,
        ticket_image_path=ticket_image_path,
        failure_count=failure_count,
    )


# ---------------------------------------------------------------------------
# Core persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_gasto_inserts_one_row(db_session: AsyncSession):
    """save_gasto inserts exactly one row into gastos."""
    svc = GastoService()
    draft = _make_draft()
    await svc.save_gasto(db_session, draft, "whatsapp:+5491122334455")
    await db_session.commit()

    rows = (await db_session.execute(select(Gasto))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_save_gasto_fields(db_session: AsyncSession):
    """save_gasto writes fecha=today, concepto, monto, ticket_image_path correctly."""
    svc = GastoService()
    draft = _make_draft(
        concepto="pan en panadería",
        monto=Decimal("250.50"),
        ticket_image_path="/tmp/tickets/pan.jpg",
    )
    gasto = await svc.save_gasto(db_session, draft, "whatsapp:+5491122334455")
    await db_session.commit()

    assert gasto.fecha == date.today()
    assert gasto.concepto == "pan en panadería"
    assert gasto.monto == Decimal("250.50")
    assert gasto.ticket_image_path == "/tmp/tickets/pan.jpg"


# ---------------------------------------------------------------------------
# sender_phone prefix stripping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_gasto_strips_whatsapp_prefix(db_session: AsyncSession):
    """save_gasto strips exactly one 'whatsapp:' prefix from sender_phone."""
    svc = GastoService()
    gasto = await svc.save_gasto(db_session, _make_draft(), "whatsapp:+5491122334455")
    await db_session.commit()

    assert gasto.sender_phone == "+5491122334455"


@pytest.mark.asyncio
async def test_save_gasto_strips_only_one_whatsapp_prefix(db_session: AsyncSession):
    """save_gasto with double prefix 'whatsapp:whatsapp:+549...' strips exactly one prefix.

    removeprefix strips at most one occurrence of the leading string.
    Result is 'whatsapp:+5491122334455' (one prefix remaining) then .strip()
    leaves 'whatsapp:+5491122334455'.
    This confirms removeprefix behaviour vs .replace('whatsapp:', '') which would
    strip both occurrences.
    """
    svc = GastoService()
    gasto = await svc.save_gasto(db_session, _make_draft(), "whatsapp:whatsapp:+5491122334455")
    await db_session.commit()

    # removeprefix strips the first "whatsapp:" only — leaving "whatsapp:+5491122334455"
    assert gasto.sender_phone == "whatsapp:+5491122334455"


@pytest.mark.asyncio
async def test_save_gasto_no_prefix_unchanged(db_session: AsyncSession):
    """save_gasto with no 'whatsapp:' prefix leaves the number untouched."""
    svc = GastoService()
    gasto = await svc.save_gasto(db_session, _make_draft(), "+5491122334455")
    await db_session.commit()

    assert gasto.sender_phone == "+5491122334455"


# ---------------------------------------------------------------------------
# No commit inside save_gasto — caller owns the transaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_gasto_returns_id_before_caller_commits(db_session: AsyncSession):
    """save_gasto flushes to populate id; row is visible within session before commit."""
    svc = GastoService()
    gasto = await svc.save_gasto(db_session, _make_draft(), "whatsapp:+5491122334455")

    # id is populated (flushed) but caller has NOT yet committed
    assert gasto.id is not None

    # Row is visible in the same session (same transaction, pre-commit)
    row = (await db_session.execute(
        select(Gasto).where(Gasto.id == gasto.id)
    )).scalar_one_or_none()
    assert row is not None

    # Explicit commit by caller — not by save_gasto
    await db_session.commit()


# ---------------------------------------------------------------------------
# ticket_image_path=None (GASTO-04: ticket is optional)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_gasto_ticket_image_path_none(db_session: AsyncSession):
    """save_gasto with ticket_image_path=None stores None in the DB row (GASTO-04)."""
    svc = GastoService()
    draft = _make_draft(ticket_image_path=None)
    gasto = await svc.save_gasto(db_session, draft, "whatsapp:+5491122334455")
    await db_session.commit()

    assert gasto.ticket_image_path is None
    # Verify DB
    row = (await db_session.execute(select(Gasto).where(Gasto.id == gasto.id))).scalar_one()
    assert row.ticket_image_path is None


# ---------------------------------------------------------------------------
# Stateless service
# ---------------------------------------------------------------------------


def test_gasto_service_is_stateless():
    """GastoService holds no session or mutable state — only _log."""
    svc = GastoService()
    # Only attribute should be _log (structlog logger)
    attrs = {k for k in vars(svc) if not k.startswith("__")}
    assert attrs == {"_log"}, f"Unexpected state attributes: {attrs - {'_log'}}"
