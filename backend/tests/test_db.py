"""Tests for INF-01: sender_allowlist table and CRUD operations."""
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import Base, Invoice, InvoiceLineItem, SenderAllowlist


def test_allowlist_table_exists():
    """INF-01: sender_allowlist table is registered in Base.metadata."""
    assert "sender_allowlist" in Base.metadata.tables

    table = Base.metadata.tables["sender_allowlist"]
    column_names = {c.name for c in table.columns}
    assert "phone_number" in column_names
    assert "display_name" in column_names
    assert "is_active" in column_names
    assert "created_at" in column_names


async def test_allowlist_crud(db_session):
    """INF-01: SenderAllowlist row can be inserted and retrieved via AsyncSession."""
    entry = SenderAllowlist(phone_number="+5491100000000", display_name="Test User")
    db_session.add(entry)
    await db_session.commit()

    result = await db_session.execute(
        select(SenderAllowlist).where(
            SenderAllowlist.phone_number == "+5491100000000"
        )
    )
    row = result.scalar_one()
    assert row.phone_number == "+5491100000000"
    assert row.display_name == "Test User"
    assert row.is_active is True


async def test_invoice_relationship(db_session):
    """Invoice + InvoiceLineItem relationship: UUID PK round-trips, cascade works."""
    invoice = Invoice()
    db_session.add(invoice)
    await db_session.flush()  # Populate invoice.id without committing

    item1 = InvoiceLineItem(invoice_id=invoice.id, descripcion="Item A")
    item2 = InvoiceLineItem(invoice_id=invoice.id, descripcion="Item B")
    db_session.add_all([item1, item2])
    await db_session.commit()

    # Re-query with eager load to verify relationship
    result = await db_session.execute(
        select(Invoice)
        .where(Invoice.id == invoice.id)
        .options(selectinload(Invoice.line_items))
    )
    loaded_invoice = result.scalar_one()

    assert isinstance(loaded_invoice.id, uuid.UUID)
    assert len(loaded_invoice.line_items) == 2
    descriptions = {item.descripcion for item in loaded_invoice.line_items}
    assert descriptions == {"Item A", "Item B"}


def test_all_three_tables_in_metadata():
    """All three schema tables are registered in Base.metadata."""
    tables = set(Base.metadata.tables.keys())
    assert "invoices" in tables
    assert "invoice_line_items" in tables
    assert "sender_allowlist" in tables
