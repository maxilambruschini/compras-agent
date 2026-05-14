"""FastAPI admin router — 7 CRUD endpoints for invoice management.

Security note (T-4-03): No authentication in v1. UI-07 (admin email/password
login) is deferred to v2 by locked user decision. All endpoints are publicly
accessible on localhost. The guessable image filenames expose full invoice scans
(CUIT, CAE, financial totals, vendor data) to any actor on the same network
without an auth gate. This is an explicit risk acceptance. Mitigation path for
v2: add auth middleware and replace /images/{filename} with /invoices/{id}/image
so the endpoint is covered by the same auth layer as other admin routes without
frontend URL changes. See REVIEWS.md HIGH concern #3.

# A4: /images/{filename} assumes globally unique flat filenames in storage_path.
# If StorageBackend uses subdirectories or non-unique basenames, this endpoint
# must be replaced with /invoices/{id}/image that resolves by invoice ID.
# See REVIEWS.md HIGH concern #2.
"""
import pathlib
import uuid

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings, get_settings
from app.db.models import Invoice, InvoiceLineItem
from app.db.session import get_db
from app.schemas.admin import (
    InvoiceDetailResponse,
    InvoiceDocumentPatch,
    InvoiceListItem,
    InvoiceListResponse,
    InvoiceStatusPatch,
    LineItemPatch,
    LineItemResponse,
)

router = APIRouter()


@router.get("/invoices", response_model=InvoiceListResponse)
async def list_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    proveedor: str | None = Query(None),
    fecha_from: str | None = Query(None),
    fecha_to: str | None = Query(None),
    q: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> InvoiceListResponse:
    """List invoices with optional filtering and pagination."""
    # Stub — implement in Task 2
    raise HTTPException(status_code=501, detail="Not implemented")


@router.get("/invoices/{invoice_id}", response_model=InvoiceDetailResponse)
async def get_invoice(
    invoice_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
) -> InvoiceDetailResponse:
    """Get a single invoice with line items."""
    # Stub — implement in Task 2
    raise HTTPException(status_code=501, detail="Not implemented")


@router.patch("/invoices/{invoice_id}", response_model=InvoiceDetailResponse)
async def patch_invoice(
    invoice_id: uuid.UUID = Path(...),
    body: InvoiceDocumentPatch = ...,
    db: AsyncSession = Depends(get_db),
) -> InvoiceDetailResponse:
    """Update editable document fields on an invoice."""
    # Stub — implement in Task 2
    raise HTTPException(status_code=501, detail="Not implemented")


@router.patch("/invoices/{invoice_id}/items/{item_id}", response_model=LineItemResponse)
async def patch_line_item(
    invoice_id: uuid.UUID = Path(...),
    item_id: int = Path(...),
    body: LineItemPatch = ...,
    db: AsyncSession = Depends(get_db),
) -> LineItemResponse:
    """Update editable fields on a line item."""
    # Stub — implement in Task 2
    raise HTTPException(status_code=501, detail="Not implemented")


@router.patch("/invoices/{invoice_id}/status", response_model=InvoiceDetailResponse)
async def patch_invoice_status(
    invoice_id: uuid.UUID = Path(...),
    body: InvoiceStatusPatch = ...,
    db: AsyncSession = Depends(get_db),
) -> InvoiceDetailResponse:
    """Update invoice status (confirmed or rejected only)."""
    # Stub — implement in Task 2
    raise HTTPException(status_code=501, detail="Not implemented")


@router.delete("/invoices/{invoice_id}", status_code=204)
async def delete_invoice(
    invoice_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete an invoice row. Does NOT delete the image file (audit retention)."""
    # Stub — implement in Task 2
    raise HTTPException(status_code=501, detail="Not implemented")


@router.get("/images/{filename}")
async def serve_image(
    filename: str = Path(..., pattern=r"^[^/\\]+$"),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """Serve invoice image files with path traversal protection (T-4-01).

    # A4: assumes globally unique flat filenames in storage_path.
    """
    # Stub — implement in Task 2
    raise HTTPException(status_code=501, detail="Not implemented")
