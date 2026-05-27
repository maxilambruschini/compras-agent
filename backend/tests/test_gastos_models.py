"""Smoke tests for Gasto, Conversation, and CajaCierre ORM models.

Proves CONV-01: conversation state (and gasto/caja records) survive process
restarts because they are DB-backed. Uses the existing conftest aiosqlite
async_engine + db_session fixtures — Base.metadata.create_all picks up the
new models automatically since they subclass the same Base.

No RLS tested here (deferred per review concern 5 — see migration comments).
"""
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.models import CajaCierre, Conversation, Gasto


@pytest.mark.asyncio
async def test_conversation_round_trip(db_session):
    """CONV-01: Conversation row persists and round-trips all fields."""
    conv = Conversation(
        sender_phone="+5491123456789",
        state="awaiting_monto",
        draft_gasto='{"concepto": "queso", "monto": null}',
        last_message_id="wamid.test001",
    )
    db_session.add(conv)
    await db_session.commit()

    result = await db_session.execute(
        select(Conversation).where(Conversation.sender_phone == "+5491123456789")
    )
    loaded = result.scalar_one()

    assert loaded.sender_phone == "+5491123456789"
    assert loaded.state == "awaiting_monto"
    assert loaded.draft_gasto == '{"concepto": "queso", "monto": null}'
    assert loaded.last_message_id == "wamid.test001"
    # updated_at is set by the DB server_default
    assert loaded.updated_at is not None


@pytest.mark.asyncio
async def test_gasto_round_trip(db_session):
    """CONV-01 + D-01: Gasto row persists with minimal field set; no lugar/proveedor/category."""
    today = date.today()
    gasto = Gasto(
        fecha=today,
        concepto="queso en supermercado",
        monto=Decimal("1500.00"),
        sender_phone="+5491123456789",
        # ticket_image_path intentionally omitted — must be nullable (GASTO-04)
    )
    db_session.add(gasto)
    await db_session.commit()

    result = await db_session.execute(select(Gasto).where(Gasto.fecha == today))
    loaded = result.scalar_one()

    assert loaded.fecha == today
    assert loaded.concepto == "queso en supermercado"
    assert loaded.monto == Decimal("1500.00")
    assert loaded.sender_phone == "+5491123456789"
    assert loaded.ticket_image_path is None  # GASTO-04: optional, defaults to None
    assert loaded.created_at is not None

    # D-01 compliance: Gasto must NOT have lugar/proveedor/entrada/category columns
    gasto_cols = {col.key for col in Gasto.__table__.columns}
    assert "lugar" not in gasto_cols
    assert "proveedor" not in gasto_cols
    assert "entrada" not in gasto_cols
    assert "category" not in gasto_cols


@pytest.mark.asyncio
async def test_caja_cierre_round_trip(db_session):
    """CajaCierre row persists and round-trips all fields."""
    today = date.today()
    cierre = CajaCierre(
        fecha=today,
        hora_cierre="17:00",
        efectivo_en_caja=Decimal("25000.50"),
        sender_phone="+5491123456789",
    )
    db_session.add(cierre)
    await db_session.commit()

    result = await db_session.execute(select(CajaCierre).where(CajaCierre.fecha == today))
    loaded = result.scalar_one()

    assert loaded.fecha == today
    assert loaded.hora_cierre == "17:00"
    assert loaded.efectivo_en_caja == Decimal("25000.50")
    assert loaded.sender_phone == "+5491123456789"
    assert loaded.created_at is not None


@pytest.mark.asyncio
async def test_multiple_gastos_same_sender(db_session):
    """Multiple Gasto rows for the same sender are all persisted (no unique constraint on sender)."""
    today = date.today()
    for concepto, monto in [("pan", "200.00"), ("leche", "350.00")]:
        db_session.add(
            Gasto(
                fecha=today,
                concepto=concepto,
                monto=Decimal(monto),
                sender_phone="+5491111111111",
            )
        )
    await db_session.commit()

    result = await db_session.execute(
        select(Gasto).where(Gasto.sender_phone == "+5491111111111")
    )
    rows = result.scalars().all()
    assert len(rows) == 2
    conceptos = {r.concepto for r in rows}
    assert conceptos == {"pan", "leche"}
