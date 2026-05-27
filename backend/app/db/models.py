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


# ---------------------------------------------------------------------------
# v2.0 Gastos Bot models
# ---------------------------------------------------------------------------


class Conversation(Base):
    """Per-sender conversation state for the Gastos Bot.

    sender_phone is the primary key (one active conversation per sender).
    updated_at uses onupdate=func.now() — this is the D-08 timeout anchor:
    the orchestrator checks this column against CONVERSATION_TIMEOUT_HOURS.
    Always reassign conv.draft_gasto = new_string (not mutate in-place) so
    SQLAlchemy change-tracking fires and updated_at is refreshed (Pitfall E).
    """
    __tablename__ = "conversations"

    sender_phone: Mapped[str] = mapped_column(String(30), primary_key=True)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="idle")
    draft_gasto: Mapped[Optional[str]] = mapped_column(Text)  # JSON dump of DraftGasto
    last_message_id: Mapped[Optional[str]] = mapped_column(String(100))  # CONV-02 idempotency key
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_conversations_sender_phone", "sender_phone"),
    )


class Gasto(Base):
    """Committed cash expense record — written only after explicit confirmation (D-05).

    Field set follows D-01 minimal schema: concepto (freeform observación),
    monto (salida / amount paid out, Decimal), fecha (auto = today per D-02),
    optional ticket_image_path (populated in Phase 2, GASTO-04 allows None).
    NO lugar/proveedor/entrada/category — deferred per D-01.
    """
    __tablename__ = "gastos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    concepto: Mapped[str] = mapped_column(Text, nullable=False)
    monto: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)  # ARS pesos salida
    ticket_image_path: Mapped[Optional[str]] = mapped_column(Text)  # Phase 2; None is valid
    sender_phone: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_gastos_fecha", "fecha"),
        Index("ix_gastos_sender_phone", "sender_phone"),
    )


class CajaCierre(Base):
    """Twice-daily cash-closing record (12:00 / 17:00).

    Created here in Phase 1 alongside the other gastos tables so all three
    land in a single Alembic migration. The reactive write (when a manager
    reports efectivo en caja) is implemented in Phase 2.
    """
    __tablename__ = "caja_cierres"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    hora_cierre: Mapped[str] = mapped_column(String(5), nullable=False)  # "12:00" | "17:00"
    efectivo_en_caja: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    sender_phone: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_caja_cierres_fecha", "fecha"),
    )
