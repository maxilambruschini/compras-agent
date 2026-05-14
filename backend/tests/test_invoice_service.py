"""Unit tests for InvoiceService (find_duplicate, find_existing_for_race, save_invoice).

Citations:
- D-13: Duplicate detection — app-level SELECT before INSERT
- D-15: Race-condition backstop — IntegrityError → rollback → re-raise → re-query
- 03-REVIEWS.md MEDIUM concern #7: re-query on IntegrityError so D-12 reply shows real fecha

NOTE on SQLite vs Postgres constraint behavior:
The functional UNIQUE INDEX uq_invoices_numero_proveedor_lower (Plan 01 migration) is a Postgres
construct. SQLite (used in test fixtures via aiosqlite) does NOT enforce functional unique indexes
— it only enforces exact-value UNIQUE constraints. Therefore:
- find_duplicate + find_existing_for_race tests can use SQLite freely (SELECT logic, not constraint).
- test_save_invoice_re_raises_integrity_error monkeypatches session.commit to raise IntegrityError
  rather than relying on SQLite enforcing the constraint. This accurately tests the CATCH logic
  without requiring Postgres.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Invoice, InvoiceLineItem
from app.models.extraction import ExtractedInvoice, LineItem, TipoComprobante
from app.services.extraction import ExtractionResult
from app.services.invoice import InvoiceService


# ---------------------------------------------------------------------------
# Helper: build a fully-formed ExtractionResult for testing
# ---------------------------------------------------------------------------


def _make_line_item(n: int = 0) -> LineItem:
    """Build a stub ExtractedLineItem with non-null numeric fields."""
    return LineItem(
        descripcion=f"Item {n}",
        codigo_sku=f"SKU-{n:03d}",
        bultos=Decimal("1"),
        unidades_por_bulto=Decimal("6"),
        precio_unitario_sin_iva=Decimal("100.00"),
        descuento_pct=Decimal("0"),
        iva_rate=Decimal("21.0"),
        percepciones_iibb=Decimal("0"),
    )


def make_extraction_result(
    numero: str = "0001-001",
    proveedor: str = "Acme SA",
    status: str = "auto_saved",
    confidence: float = 0.9,
    line_items_count: int = 2,
    image_path: str = "/tmp/invoices/SM-test.jpg",
) -> ExtractionResult:
    """Build a fully-formed ExtractionResult for use in InvoiceService tests."""
    invoice = ExtractedInvoice(
        tipo_comprobante=TipoComprobante.FACTURA_A,
        numero_documento=numero,
        proveedor=proveedor,
        fecha="2026-05-10",
        cuit_proveedor="20-12345678-9",
        cae="12345678901234",
        fecha_vencimiento_cae="2026-06-10",
        line_items=[_make_line_item(i) for i in range(line_items_count)],
    )
    return ExtractionResult(
        invoice=invoice,
        confidence_score=confidence,
        status=status,
        image_path=image_path,
    )


def _seed_invoice(
    numero: str = "0001-00000001",
    proveedor: str = "Acme SA",
    fecha: date | None = date(2026, 5, 10),
) -> Invoice:
    """Build an Invoice ORM object ready to be added to a session."""
    return Invoice(
        tipo_comprobante="FACTURA_A",
        numero_documento=numero,
        proveedor=proveedor,
        fecha=fecha,
        status="auto_saved",
        whatsapp_message_id="SM-seed-001",
        sender_phone="+5491112345678",
        image_path="/tmp/invoices/seed.jpg",
    )


# ---------------------------------------------------------------------------
# Tests for find_duplicate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_duplicate_returns_none_when_no_match(db_session: AsyncSession):
    """Empty DB: find_duplicate returns None."""
    svc = InvoiceService()
    result = await svc.find_duplicate(db_session, "0001-001", "Acme")
    assert result is None


@pytest.mark.asyncio
async def test_find_duplicate_returns_none_when_numero_null(db_session: AsyncSession):
    """find_duplicate with numero=None returns None (early-return guard)."""
    svc = InvoiceService()
    result = await svc.find_duplicate(db_session, None, "Acme")
    assert result is None


@pytest.mark.asyncio
async def test_find_duplicate_returns_none_when_proveedor_null(db_session: AsyncSession):
    """find_duplicate with proveedor=None returns None (early-return guard)."""
    svc = InvoiceService()
    result = await svc.find_duplicate(db_session, "0001-001", None)
    assert result is None


@pytest.mark.asyncio
async def test_find_duplicate_case_insensitive_match(db_session: AsyncSession):
    """find_duplicate matches regardless of case on both numero and proveedor."""
    db_session.add(_seed_invoice(numero="0001-00000001", proveedor="Acme SA"))
    await db_session.commit()

    svc = InvoiceService()
    result = await svc.find_duplicate(db_session, "0001-00000001", "ACME SA")
    assert result is not None
    assert result.proveedor == "Acme SA"


@pytest.mark.asyncio
async def test_find_duplicate_returns_existing_when_both_match(db_session: AsyncSession):
    """find_duplicate returns the existing row when both fields match exactly."""
    db_session.add(_seed_invoice(numero="0001-00000001", proveedor="Acme SA"))
    await db_session.commit()

    svc = InvoiceService()
    result = await svc.find_duplicate(db_session, "0001-00000001", "Acme SA")
    assert result is not None
    assert result.numero_documento == "0001-00000001"


# ---------------------------------------------------------------------------
# Tests for find_existing_for_race
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_existing_for_race_returns_seeded_row(db_session: AsyncSession):
    """find_existing_for_race uses same case-insensitive logic as find_duplicate."""
    db_session.add(_seed_invoice(numero="0001-RACE", proveedor="Race SA", fecha=date(2026, 5, 10)))
    await db_session.commit()

    svc = InvoiceService()
    result = await svc.find_existing_for_race(db_session, "0001-RACE", "race sa")
    assert result is not None
    assert result.numero_documento == "0001-RACE"
    assert result.fecha == date(2026, 5, 10)


# ---------------------------------------------------------------------------
# Tests for save_invoice
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_invoice_persists_invoice_and_line_items(db_session: AsyncSession):
    """save_invoice inserts one Invoice row and the correct number of line items."""
    extraction = make_extraction_result(line_items_count=2)
    svc = InvoiceService()
    saved = await svc.save_invoice(db_session, extraction, "SM-test-001", "whatsapp:+5491112345678")

    assert saved.id is not None

    # Verify DB counts
    inv_count = (await db_session.execute(
        select(Invoice)
    )).scalars().all()
    assert len(inv_count) == 1

    li_count = (await db_session.execute(
        select(InvoiceLineItem)
    )).scalars().all()
    assert len(li_count) == 2


@pytest.mark.asyncio
async def test_save_invoice_sets_message_metadata(db_session: AsyncSession):
    """save_invoice stores whatsapp_message_id, sender_phone, confidence_score, status, image_path."""
    extraction = make_extraction_result(
        status="pending_review",
        confidence=0.5,
        image_path="/tmp/invoices/SM-meta-test.jpg",
    )
    svc = InvoiceService()
    saved = await svc.save_invoice(db_session, extraction, "SM-meta-test", "whatsapp:+5491199999999")

    assert saved.whatsapp_message_id == "SM-meta-test"
    assert saved.sender_phone == "+5491199999999"  # whatsapp: prefix stripped
    assert saved.status == "pending_review"
    assert float(saved.confidence_score) == pytest.approx(0.5, abs=1e-3)
    assert saved.image_path == "/tmp/invoices/SM-meta-test.jpg"


@pytest.mark.asyncio
async def test_save_invoice_re_raises_integrity_error(db_session: AsyncSession, monkeypatch):
    """save_invoice rolls back and re-raises IntegrityError on commit failure."""
    # Monkeypatch session.commit to raise IntegrityError
    commit_mock = AsyncMock(side_effect=IntegrityError("UNIQUE constraint", None, None))
    rollback_mock = AsyncMock()
    monkeypatch.setattr(db_session, "commit", commit_mock)
    monkeypatch.setattr(db_session, "rollback", rollback_mock)

    extraction = make_extraction_result()
    svc = InvoiceService()

    with pytest.raises(IntegrityError):
        await svc.save_invoice(db_session, extraction, "SM-race-001", "whatsapp:+5491112345678")

    # rollback MUST have been called before re-raise
    rollback_mock.assert_awaited_once()
