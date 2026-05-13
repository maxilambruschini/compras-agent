"""Pydantic extraction models — output contract for GPT-4o structured extraction.

All fields are Optional per EXT-06 (null > hallucination).
TipoComprobante uses str Enum per D-08 so Postgres stores readable labels.
use_enum_values=True required for OpenAI Structured Outputs JSON Schema in Phase 2.
"""
from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class TipoComprobante(str, Enum):
    """Argentine invoice document types. str Enum stores readable labels in Postgres."""

    FACTURA_A = "FACTURA_A"
    FACTURA_B = "FACTURA_B"
    FACTURA_C = "FACTURA_C"
    REMITO = "REMITO"
    LISTA_INFORMAL = "LISTA_INFORMAL"
    UNKNOWN = "UNKNOWN"  # Required fallback — GPT-4o may see unknown types (D-08)


class LineItem(BaseModel):
    """Extracted line item — all fields Optional per EXT-06 (null > hallucination)."""

    model_config = ConfigDict(use_enum_values=True)

    descripcion: Optional[str] = None
    codigo_sku: Optional[str] = None
    bultos: Optional[Decimal] = None
    unidades_por_bulto: Optional[Decimal] = None
    precio_unitario_sin_iva: Optional[Decimal] = None
    descuento_pct: Optional[Decimal] = None
    iva_rate: Optional[Decimal] = None
    percepciones_iibb: Optional[Decimal] = None


class ExtractedInvoice(BaseModel):
    """Top-level extraction output contract for GPT-4o response parsing.

    All fields are Optional per EXT-06. The UNKNOWN fallback on tipo_comprobante
    ensures the model never fails on unrecognized document types (EXT-05).
    """

    model_config = ConfigDict(use_enum_values=True)

    tipo_comprobante: Optional[TipoComprobante] = None
    numero_documento: Optional[str] = None
    proveedor: Optional[str] = None
    fecha: Optional[str] = None  # ISO 8601 string; parse to date in service layer
    cuit_proveedor: Optional[str] = None
    cae: Optional[str] = None
    fecha_vencimiento_cae: Optional[str] = None
    line_items: List[LineItem] = []
    # confidence_score is computed in Phase 2 ExtractionService, not by GPT-4o
