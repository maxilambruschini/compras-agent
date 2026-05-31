"""Admin read endpoints — Phase 4 UI-01 / UI-02.

Four read-only GET endpoints for the manager/accountant web UI:
  GET /gastos              -> list[GastoOut], newest-first; ?from=&to=&q= filters
  GET /gastos/{id}         -> GastoOut; 404 if unknown
  GET /gastos/{id}/ticket  -> FileResponse; 404 if no ticket_image_path or file missing
  GET /cierres             -> list[CierreOut], newest-first

Security mitigations:
  T-04-01: Query gastos / caja_cierres tables ONLY — never join or select from conversations.
  T-04-02: q search uses SQLAlchemy .ilike() (parameterized bind, not string interpolation).
  T-04-04: Ticket path-traversal guard — realpath + commonpath check before FileResponse.
  T-04-05: id typed uuid.UUID (FastAPI rejects non-UUID → 422); from_/to typed date.

Note: CORSMiddleware (T-04-03) is added in main.py create_app() — not here.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import CajaCierre, Gasto
from app.db.session import get_db

router = APIRouter()


# ---------------------------------------------------------------------------
# Response models (Pydantic v2)
# Decimal fields serialize as strings by default in Pydantic v2 — DO NOT
# override this; test_decimal_serialization asserts isinstance(monto, str).
# ---------------------------------------------------------------------------


class GastoOut(BaseModel):
    id: uuid.UUID
    fecha: date
    concepto: str
    monto: Decimal
    ticket_image_path: str | None
    sender_phone: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CierreOut(BaseModel):
    id: uuid.UUID
    fecha: date
    hora_cierre: str
    efectivo_en_caja: Decimal
    sender_phone: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Endpoints — paths are RELATIVE; main.py mounts with prefix="/api"
# ---------------------------------------------------------------------------


@router.get("/gastos", response_model=list[GastoOut])
async def list_gastos(
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    q: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[GastoOut]:
    """List committed gastos, newest-first. Optionally filter by date range and/or concepto.

    Query params:
      from  (alias for from_) — lower bound on fecha (inclusive)
      to    — upper bound on fecha (inclusive)
      q     — case-insensitive substring match on concepto (SQLAlchemy .ilike, parameterized)

    T-04-01: select(Gasto) only — never joins or selects from the conversations table.
    T-04-02: q uses .ilike(f"%{q.strip()}%") — SQLAlchemy bind parameter, not raw SQL.
    """
    stmt = select(Gasto).order_by(Gasto.created_at.desc())
    if from_ is not None:
        stmt = stmt.where(Gasto.fecha >= from_)
    if to is not None:
        stmt = stmt.where(Gasto.fecha <= to)
    if q and q.strip():
        stmt = stmt.where(Gasto.concepto.ilike(f"%{q.strip()}%"))
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/gastos/{id}", response_model=GastoOut)
async def get_gasto(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> GastoOut:
    """Return a single committed gasto by UUID, or 404 if not found.

    T-04-05: id typed as uuid.UUID — FastAPI rejects malformed UUIDs with 422.
    """
    result = await db.execute(select(Gasto).where(Gasto.id == id))
    gasto = result.scalar_one_or_none()
    if gasto is None:
        raise HTTPException(status_code=404, detail="Gasto not found")
    return gasto  # type: ignore[return-value]


@router.get("/gastos/{id}/ticket")
async def get_ticket(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """Stream the ticket image for a gasto via FileResponse.

    Returns 404 when:
      - The gasto does not exist.
      - ticket_image_path is None (no ticket was attached).
      - The resolved file path escapes settings.storage_path (traversal guard).
      - The file does not exist on disk.

    T-04-04: Defense-in-depth — realpath + commonpath check ensures the resolved
    file path cannot escape settings.storage_path even if ticket_image_path were
    somehow crafted. Mirrors the write-side guard in LocalStorageBackend.save().
    """
    result = await db.execute(select(Gasto).where(Gasto.id == id))
    gasto = result.scalar_one_or_none()
    if gasto is None:
        raise HTTPException(status_code=404, detail="Gasto not found")
    if not gasto.ticket_image_path:
        raise HTTPException(status_code=404, detail="No ticket for this gasto")

    full_path = os.path.join(settings.storage_path, gasto.ticket_image_path)

    # Defense-in-depth path-traversal guard (T-04-04)
    real_root = os.path.realpath(settings.storage_path)
    real_full = os.path.realpath(full_path)
    try:
        common = os.path.commonpath([real_full, real_root])
    except ValueError:
        # commonpath raises ValueError on Windows for cross-drive paths
        raise HTTPException(status_code=404, detail="Ticket file not found")
    if common != real_root:
        raise HTTPException(status_code=404, detail="Ticket file not found")

    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="Ticket file not found on disk")

    return FileResponse(full_path)


@router.get("/cierres", response_model=list[CierreOut])
async def list_cierres(
    db: AsyncSession = Depends(get_db),
) -> list[CierreOut]:
    """List all committed caja cierres, newest-first.

    T-04-01: select(CajaCierre) only — never joins or selects from the conversations table.
    """
    result = await db.execute(
        select(CajaCierre).order_by(CajaCierre.created_at.desc())
    )
    return list(result.scalars().all())
