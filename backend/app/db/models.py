"""SQLAlchemy ORM models — source of truth for Postgres schema and Alembic autogenerate.

Uses SQLAlchemy 2.0 typed mapping (DeclarativeBase, Mapped, mapped_column).
Uses sqlalchemy.Uuid (dialect-agnostic) NOT sqlalchemy.dialects.postgresql.UUID
so that tests can use aiosqlite and production can use asyncpg without divergence.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Document header (nullable — extraction may be partial)
    tipo_comprobante: Mapped[Optional[str]] = mapped_column(String(50))
    numero_documento: Mapped[Optional[str]] = mapped_column(String(100))
    proveedor: Mapped[Optional[str]] = mapped_column(String(255))
    fecha: Mapped[Optional[date]] = mapped_column(Date)
    cuit_proveedor: Mapped[Optional[str]] = mapped_column(String(13))
    cae: Mapped[Optional[str]] = mapped_column(String(20))
    fecha_vencimiento_cae: Mapped[Optional[date]] = mapped_column(Date)

    # Processing metadata
    confidence_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(4, 3))
    status: Mapped[str] = mapped_column(
        String(30), default="pending_review", nullable=False
    )
    whatsapp_message_id: Mapped[Optional[str]] = mapped_column(String(100))
    sender_phone: Mapped[Optional[str]] = mapped_column(String(30))
    image_path: Mapped[Optional[str]] = mapped_column(Text)
    raw_extraction: Mapped[Optional[str]] = mapped_column(Text)  # JSON dump

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    line_items: Mapped[List["InvoiceLineItem"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_invoices_numero_documento_proveedor", "numero_documento", "proveedor"),
        Index("ix_invoices_status", "status"),
        Index("ix_invoices_created_at", "created_at"),
    )


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("invoices.id", ondelete="CASCADE")
    )

    descripcion: Mapped[Optional[str]] = mapped_column(Text)
    codigo_sku: Mapped[Optional[str]] = mapped_column(String(100))
    bultos: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4))
    unidades_por_bulto: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4))
    precio_unitario_sin_iva: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4))
    descuento_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4))
    iva_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4))
    percepciones_iibb: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4))

    invoice: Mapped["Invoice"] = relationship(back_populates="line_items")


class SenderAllowlist(Base):
    __tablename__ = "sender_allowlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text('true'))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
