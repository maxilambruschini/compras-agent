"""FastAPI admin router — 7 CRUD endpoints for invoice management.

Security note (T-4-03): No authentication in v1. UI-07 (admin email/password
login) is deferred to v2 by locked user decision. All endpoints are publicly
accessible on localhost. The guessable image filenames expose full invoice scans
(CUIT, CAE, financial totals, vendor data) to any actor on the same network
without an auth gate. This risk is explicitly accepted. Mitigation path for v2:
add auth middleware and replace /images/{filename} with /invoices/{id}/image so
the endpoint is covered by the same auth layer as other admin routes without
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
    """List invoices with optional filtering and pagination.

    Filters: status (exact), proveedor (ILIKE), fecha_from/to (date range),
    q (full-text ILIKE across proveedor, numero_documento, and line item descripcion).
    All filter params use SQLAlchemy parameterized binds (T-4-02 mitigation).
    """
    stmt = select(Invoice).order_by(Invoice.created_at.desc())

    if status:
        stmt = stmt.where(Invoice.status == status)
    if proveedor:
        stmt = stmt.where(
            func.lower(Invoice.proveedor).like(f"%{proveedor.lower()}%")
        )
    if fecha_from:
        stmt = stmt.where(Invoice.fecha >= fecha_from)
    if fecha_to:
        stmt = stmt.where(Invoice.fecha <= fecha_to)
    if q:
        search = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Invoice.proveedor).like(search),
                func.lower(Invoice.numero_documento).like(search),
                Invoice.id.in_(
                    select(InvoiceLineItem.invoice_id)
                    .where(func.lower(InvoiceLineItem.descripcion).like(search))
                    .scalar_subquery()
                ),
            )
        )

    # Count total before applying pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    # Apply pagination
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    invoices = result.scalars().all()

    return InvoiceListResponse(
        items=[InvoiceListItem.model_validate(inv) for inv in invoices],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/invoices/{invoice_id}", response_model=InvoiceDetailResponse)
async def get_invoice(
    invoice_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
) -> InvoiceDetailResponse:
    """Get a single invoice with all line items eagerly loaded."""
    result = await db.execute(
        select(Invoice)
        .where(Invoice.id == invoice_id)
        .options(selectinload(Invoice.line_items))
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return InvoiceDetailResponse.model_validate(invoice)


@router.patch("/invoices/{invoice_id}", response_model=InvoiceDetailResponse)
async def patch_invoice(
    invoice_id: uuid.UUID = Path(...),
    body: InvoiceDocumentPatch = ...,
    db: AsyncSession = Depends(get_db),
) -> InvoiceDetailResponse:
    """Update editable document fields on an invoice.

    Only provided fields are updated (exclude_unset=True).
    """
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id)
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    patch_data = body.model_dump(exclude_unset=True)
    for field, value in patch_data.items():
        setattr(invoice, field, value)

    await db.commit()

    # Re-query with selectinload so line_items are populated in the response
    result = await db.execute(
        select(Invoice)
        .where(Invoice.id == invoice_id)
        .options(selectinload(Invoice.line_items))
    )
    invoice = result.scalar_one()
    return InvoiceDetailResponse.model_validate(invoice)


@router.patch(
    "/invoices/{invoice_id}/items/{item_id}", response_model=LineItemResponse
)
async def patch_line_item(
    invoice_id: uuid.UUID = Path(...),
    item_id: int = Path(...),
    body: LineItemPatch = ...,
    db: AsyncSession = Depends(get_db),
) -> LineItemResponse:
    """Update editable fields on a line item.

    Verifies the item belongs to the specified invoice.
    """
    item = await db.get(InvoiceLineItem, item_id)
    if item is None or item.invoice_id != invoice_id:
        raise HTTPException(status_code=404, detail="Line item not found")

    patch_data = body.model_dump(exclude_unset=True)
    for field, value in patch_data.items():
        setattr(item, field, value)

    await db.commit()
    await db.refresh(item)
    return LineItemResponse.model_validate(item)


@router.patch("/invoices/{invoice_id}/status", response_model=InvoiceDetailResponse)
async def patch_invoice_status(
    invoice_id: uuid.UUID = Path(...),
    body: InvoiceStatusPatch = ...,
    db: AsyncSession = Depends(get_db),
) -> InvoiceDetailResponse:
    """Update invoice status. Only 'confirmed' and 'rejected' are accepted."""
    if body.status not in {"confirmed", "rejected"}:
        raise HTTPException(
            status_code=422, detail="status must be 'confirmed' or 'rejected'"
        )

    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id)
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    setattr(invoice, "status", body.status)
    await db.commit()

    # Re-query with selectinload for the response
    result = await db.execute(
        select(Invoice)
        .where(Invoice.id == invoice_id)
        .options(selectinload(Invoice.line_items))
    )
    invoice = result.scalar_one()
    return InvoiceDetailResponse.model_validate(invoice)


@router.delete("/invoices/{invoice_id}", status_code=204)
async def delete_invoice(
    invoice_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete an invoice row. Does NOT delete the image file (audit retention, D-09, UI-05)."""
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id)
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    await db.delete(invoice)
    await db.commit()
    return Response(status_code=204)


@router.get("/invoices/{invoice_id}/image")
async def serve_invoice_image(
    invoice_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """Serve invoice image by invoice ID. Resolves image_path from DB — no path traversal risk."""
    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    invoice = result.scalar_one_or_none()
    if invoice is None or not invoice.image_path:
        raise HTTPException(status_code=404, detail="Image not found")
    storage_root = pathlib.Path(settings.storage_path).resolve()
    file_path = (storage_root / invoice.image_path).resolve()
    if not str(file_path).startswith(str(storage_root) + "/"):
        raise HTTPException(status_code=400, detail="Invalid image path")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image file not found")
    return FileResponse(str(file_path))


@router.get("/images/{filename}")
async def serve_image(
    filename: str = Path(..., pattern=r"^[^/\\]+$"),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """Serve invoice image files with path traversal protection (T-4-01 mitigation).

    Primary guard: FastAPI Path regex rejects filenames containing / or \\.
    Secondary guard: resolves both paths and verifies containment even after
    URL-decoding, guarding against %2F and similar bypass attempts (ASVS V5.3).

    # A4: assumes globally unique flat filenames in storage_path.
    """
    storage_root = pathlib.Path(settings.storage_path).resolve()
    file_path = (storage_root / filename).resolve()

    # Secondary containment check
    if not str(file_path).startswith(str(storage_root) + "/") and file_path != storage_root:
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(str(file_path))
