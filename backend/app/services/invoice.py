"""InvoiceService — duplicate detection and invoice persistence.

Citations:
- D-13: Duplicate detection — app-level SELECT before INSERT using LOWER() on
         numero_documento + proveedor (matches the functional UNIQUE INDEX).
- D-15: Race-condition backstop — IntegrityError on commit triggers rollback,
         re-raise so the caller (process_invoice) can handle via find_existing_for_race.
- 03-REVIEWS.md MEDIUM concern #7: find_existing_for_race re-queries after IntegrityError
         so the D-12 duplicate reply can include the real original fecha of the winning row.
- 03-REVIEWS.md MEDIUM concern #8: image_path from ExtractionResult is persisted on Invoice.image_path
         (the original file was written by LocalStorageBackend inside ExtractionService.extract();
         this column is the audit trail link — no additional file-retention code needed).
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Invoice, InvoiceLineItem
from app.services.extraction import ExtractionResult

log = structlog.get_logger()


class InvoiceService:
    """Stateless service for duplicate detection and invoice persistence.

    All methods take `session` as the first argument — the service holds no
    session state. Instantiate once per background task and discard.
    """

    def __init__(self) -> None:
        self._log = structlog.get_logger()

    async def find_duplicate(
        self,
        session: AsyncSession,
        numero: Optional[str],
        proveedor: Optional[str],
    ) -> Optional[Invoice]:
        """Look up an Invoice by case-insensitive numero_documento + proveedor.

        Returns the existing Invoice if found, otherwise None. Returns None
        immediately when either argument is None or an empty string (a NULL in the
        unique index does NOT match another NULL — PostgreSQL behavior; partial
        extractions must never be flagged as duplicates).

        Args:
            session: Active AsyncSession. Caller owns the session lifecycle.
            numero: The extracted numero_documento to check.
            proveedor: The extracted proveedor name to check.

        Returns:
            The existing Invoice row if a duplicate is found, else None.
        """
        if not numero or not proveedor:
            self._log.info(
                "invoice.duplicate_check",
                numero=numero,
                proveedor=proveedor,
                found=False,
                reason="null_guard",
            )
            return None

        result = await session.execute(
            select(Invoice)
            .where(
                func.lower(Invoice.numero_documento) == func.lower(numero),
                func.lower(Invoice.proveedor) == func.lower(proveedor),
            )
            .limit(1)
        )
        existing = result.scalar_one_or_none()
        self._log.info(
            "invoice.duplicate_check",
            numero=numero,
            proveedor=proveedor,
            found=existing is not None,
        )
        return existing

    async def find_existing_for_race(
        self,
        session: AsyncSession,
        numero: Optional[str],
        proveedor: Optional[str],
    ) -> Optional[Invoice]:
        """Re-query the winning row after a concurrent INSERT's IntegrityError.

        Identical query shape to find_duplicate. Called by process_invoice AFTER
        catching IntegrityError and rolling back the session, so the D-12 reply
        can include the real original fecha of the row that won the race
        (03-REVIEWS.md MEDIUM concern #7).

        Args:
            session: The rolled-back AsyncSession. Caller is responsible for having
                     called session.rollback() before this call.
            numero: The numero_documento that triggered the race.
            proveedor: The proveedor that triggered the race.

        Returns:
            The existing (winning) Invoice row, or None if not found (pathological edge
            case where the row was deleted between the race and this re-query).
        """
        if not numero or not proveedor:
            self._log.info(
                "invoice.race_lookup",
                numero=numero,
                proveedor=proveedor,
                found=False,
                reason="null_guard",
            )
            return None

        result = await session.execute(
            select(Invoice)
            .where(
                func.lower(Invoice.numero_documento) == func.lower(numero),
                func.lower(Invoice.proveedor) == func.lower(proveedor),
            )
            .limit(1)
        )
        existing = result.scalar_one_or_none()
        self._log.info(
            "invoice.race_lookup",
            numero=numero,
            proveedor=proveedor,
            found=existing is not None,
        )
        return existing

    async def save_invoice(
        self,
        session: AsyncSession,
        result: ExtractionResult,
        message_id: str,
        sender_phone: str,
    ) -> Invoice:
        """Persist an Invoice and its line items from an ExtractionResult.

        Maps every header field from result.invoice to the Invoice ORM model,
        appends InvoiceLineItem rows via the relationship cascade, commits,
        and returns the saved Invoice (with id populated).

        On IntegrityError (race-condition duplicate), rolls back and re-raises so
        the caller (process_invoice) can catch it, call find_existing_for_race, and
        send the D-12 duplicate reply with the real original fecha.

        Args:
            session: Active AsyncSession. Caller owns the session lifecycle.
            result: The ExtractionResult from ExtractionService.extract().
            message_id: The Twilio MessageSid — stored for idempotency audit.
            sender_phone: The From field (may include 'whatsapp:' prefix — stripped).

        Returns:
            The persisted Invoice ORM object (id is populated after commit).

        Raises:
            IntegrityError: If the DB UNIQUE constraint fires (race condition duplicate).
                            Session is rolled back before re-raise.
        """
        inv = result.invoice

        # Map tipo_comprobante: enum value string or plain string
        tipo = None
        if inv.tipo_comprobante is not None:
            # use_enum_values=True means TipoComprobante stores as str already
            tipo = str(inv.tipo_comprobante)

        # Parse date fields from ISO strings
        fecha_val: Optional[date] = None
        if inv.fecha:
            try:
                fecha_val = date.fromisoformat(inv.fecha)
            except (ValueError, TypeError):
                fecha_val = None

        fecha_vencimiento_val: Optional[date] = None
        if inv.fecha_vencimiento_cae:
            try:
                fecha_vencimiento_val = date.fromisoformat(inv.fecha_vencimiento_cae)
            except (ValueError, TypeError):
                fecha_vencimiento_val = None

        # Strip whatsapp: prefix from sender phone
        clean_phone = sender_phone.replace("whatsapp:", "").strip()

        invoice = Invoice(
            tipo_comprobante=tipo,
            numero_documento=inv.numero_documento,
            proveedor=inv.proveedor,
            fecha=fecha_val,
            cuit_proveedor=inv.cuit_proveedor,
            cae=inv.cae,
            fecha_vencimiento_cae=fecha_vencimiento_val,
            confidence_score=Decimal(str(result.confidence_score)),
            status=result.status,
            whatsapp_message_id=message_id,
            sender_phone=clean_phone,
            # image_path links the DB row to the original file written by LocalStorageBackend
            # inside ExtractionService.extract() — resolves 03-REVIEWS.md MEDIUM concern #8.
            image_path=result.image_path,
            raw_extraction=inv.model_dump_json(),
        )

        # Append line items via ORM cascade (no manual foreign key assignment)
        for li in inv.line_items:
            invoice.line_items.append(
                InvoiceLineItem(
                    descripcion=li.descripcion,
                    codigo_sku=li.codigo_sku,
                    bultos=li.bultos,
                    unidades_por_bulto=li.unidades_por_bulto,
                    precio_unitario_sin_iva=li.precio_unitario_sin_iva,
                    descuento_pct=li.descuento_pct,
                    iva_rate=li.iva_rate,
                    percepciones_iibb=li.percepciones_iibb,
                )
            )

        session.add(invoice)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            self._log.warning(
                "invoice.duplicate_race",
                message_id=message_id,
            )
            raise

        self._log.info(
            "invoice.saved",
            id=str(invoice.id),
            status=result.status,
            image_path=result.image_path,
        )
        return invoice
