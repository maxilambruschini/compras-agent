"""Conversation DTOs — GastoSlots and DraftGasto Pydantic models.

Analog: app/models/extraction.py (ExtractedInvoice — all-Optional, ConfigDict(use_enum_values=True)).

Design rules (D-01, D-06, PITFALLS.md P32):
- All fields Optional with default=None — null > hallucination.
- GastoSlots.monto is Optional[float]: GPT Structured Outputs emits a JSON number
  (e.g. 1500.0) — avoids the Decimal("1.500") trap entirely.
- DraftGasto.monto is Optional[Decimal]: converted by the orchestrator via
  Decimal(str(slots.monto)) after extraction.
- D-01 minimal field set: concepto + monto only (no lugar/proveedor/entrada/category in v2.0).
- DraftGasto.failure_count: int default 0 — tracks consecutive parse failures for CONV-06.
- use_enum_values=True required for OpenAI Structured Outputs JSON Schema (mirrors ExtractedInvoice).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class GastoSlots(BaseModel):
    """GPT-4o-mini structured output for slot extraction from free Spanish text.

    All fields Optional — null preferred over hallucination (mirrors ExtractedInvoice pattern).

    monto typed as Optional[float] so GPT Structured Outputs emits a JSON number
    (no locale formatting). This sidesteps the Decimal("1.500") trap — GPT normalises
    "$1.500" (Argentine thousands separator) → 1500.0 before it reaches Python.

    The orchestrator converts to Decimal via Decimal(str(slots.monto)) after extraction.

    D-01: Minimal field set for v2.0. No lugar, proveedor, entrada, or category.
    """

    model_config = ConfigDict(use_enum_values=True)

    concepto: Optional[str] = None  # freeform observación ("queso en supermercado")
    monto: Optional[float] = None   # JSON number; GPT normalises "1.500" → 1500.0


class DraftGasto(BaseModel):
    """In-progress gasto assembled across conversation turns.

    Stored as JSON in conversations.draft_gasto (Text column).
    All fields Optional per P32 — draft JSON must survive schema evolution
    without crashing in-progress conversations on deploy.

    monto is Decimal here (converted from GastoSlots.monto by orchestrator).
    failure_count tracks consecutive unparseable replies for CONV-06 re-prompt logic.

    D-01: No lugar/proveedor/entrada/category in v2.0 (deferred).
    """

    model_config = ConfigDict(use_enum_values=True)

    concepto: Optional[str] = None
    monto: Optional[Decimal] = None          # converted from GastoSlots.monto after extraction
    ticket_image_path: Optional[str] = None  # populated in Phase 2
    failure_count: int = 0                   # consecutive parse failures (CONV-06)
