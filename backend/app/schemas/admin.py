"""Pydantic v2 request/response schemas for the admin API.

These models are designed for ORM serialization via model_validate() and
model_config = {"from_attributes": True}. All id fields that correspond to
UUID primary keys use uuid.UUID (not str) — FastAPI serializes them to strings
in JSON automatically.

Security note (T-4-03): This API has no authentication in v1. UI-07 (admin
email/password login) is deferred to v2. All endpoints are publicly accessible
on localhost. The guessable image filenames expose invoice data (CUIT, CAE,
financial totals, vendor names) to any actor on the same network without an
auth gate. This is an explicit risk acceptance per the locked user decision.
Mitigation path: add auth middleware in v2 and replace /images/{filename} with
/invoices/{id}/image so the endpoint is covered by the same auth layer.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class LineItemResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    invoice_id: uuid.UUID
    descripcion: Optional[str] = None
    codigo_sku: Optional[str] = None
    bultos: Optional[Decimal] = None
    unidades_por_bulto: Optional[Decimal] = None
    precio_unitario_sin_iva: Optional[Decimal] = None
    descuento_pct: Optional[Decimal] = None
    iva_rate: Optional[Decimal] = None
    percepciones_iibb: Optional[Decimal] = None


class InvoiceListItem(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    tipo_comprobante: Optional[str] = None
    numero_documento: Optional[str] = None
    proveedor: Optional[str] = None
    fecha: Optional[date] = None
    status: str
    confidence_score: Optional[Decimal] = None
    created_at: datetime


class InvoiceDetailResponse(InvoiceListItem):
    model_config = {"from_attributes": True}

    cuit_proveedor: Optional[str] = None
    cae: Optional[str] = None
    fecha_vencimiento_cae: Optional[date] = None
    image_path: Optional[str] = None
    updated_at: datetime
    line_items: list[LineItemResponse] = []


class InvoiceListResponse(BaseModel):
    items: list[InvoiceListItem]
    total: int
    page: int
    page_size: int


class InvoiceDocumentPatch(BaseModel):
    tipo_comprobante: Optional[str] = None
    numero_documento: Optional[str] = None
    proveedor: Optional[str] = None
    fecha: Optional[date] = None
    cuit_proveedor: Optional[str] = None
    cae: Optional[str] = None
    fecha_vencimiento_cae: Optional[date] = None


class LineItemPatch(BaseModel):
    descripcion: Optional[str] = None
    codigo_sku: Optional[str] = None
    bultos: Optional[Decimal] = None
    unidades_por_bulto: Optional[Decimal] = None
    precio_unitario_sin_iva: Optional[Decimal] = None
    descuento_pct: Optional[Decimal] = None
    iva_rate: Optional[Decimal] = None
    percepciones_iibb: Optional[Decimal] = None


class InvoiceStatusPatch(BaseModel):
    status: str
