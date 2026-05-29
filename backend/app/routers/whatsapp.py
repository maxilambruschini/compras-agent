"""WhatsApp webhook router.

NOTE on background tasks: this v1 implementation uses `asyncio.create_task` inside
the FastAPI worker for invoice extraction. This is acceptable for <20 invoices/day
(worst case: process restart loses an in-flight invoice; the user re-sends and the
UNIQUE INDEX prevents duplicates). Production upgrade path: replace asyncio.create_task
with a durable task queue (Celery + Redis, ARQ, or RQ) when traffic exceeds ~100
invoices/day or when an SLA requires guaranteed processing.
Resolves 03-REVIEWS.md Codex HIGH concern #2.

Citations:
- WA-01: Allowlisted sender receives Spanish acknowledgement within 5s
- WA-02: Non-allowlisted sender receives Spanish rejection; no invoice created
- WA-03: After background extraction, sender receives summary reply (D-08 or D-09)
- WA-04: Non-image/unsupported/corrupted media → D-11 unreadable-image reply
- VAL-01: Duplicate submissions produce exactly one Invoice row and one D-12 reply
- VAL-02: pending_review status → D-09 reply
- VAL-03: auto_saved status → D-08 reply
- INF-02: HMAC-based signature validation (Twilio HMAC-SHA1 via RequestValidator)
- INF-04: Handler returns 200 within Twilio's 5-second timeout window
- D-06: Request flow: validate → dedupe → allowlist → ack → background task
- D-07: Ack copy: "✅ Factura recibida. Procesando..."
- D-08: auto_saved reply header
- D-09: pending_review reply header
- D-10: Rejection copy: "❌ Este número no está autorizado para enviar facturas."
- D-11: No-media copy: "❌ No pudimos procesar la imagen. Asegurate de enviar una foto clara de la factura (JPG o PDF)."
- D-12: Duplicate copy: "🔁 Esta factura ya fue registrada el {fecha_original}. No se guardó de nuevo."
- T-3-09: Two-layer defense: MIME guard + magic-byte guard (03-REVIEWS.md HIGH concern #5)
- T-3-14: Reply-send failure after save is logged but does NOT crash the task (03-REVIEWS.md HIGH concern #6)

V1 limitations (documented per 03-REVIEWS.md):
- Only MediaUrl0 is processed. Multi-attachment messages (MediaUrl1+) are silently
  dropped and a whatsapp.multi_media_ignored log entry is emitted.
- Duplicate detection is case-insensitive on numero_documento + proveedor. Whitespace,
  accent, punctuation, and CUIT-based normalization are deferred to v2.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.engine import get_async_session_local
from app.db.models import Invoice, SenderAllowlist
from app.db.session import get_db
from app.providers.base import WhatsAppProvider
from app.services.extraction import (
    ExtractionFailedError,
    ExtractionRefusalError,
    ExtractionResult,
    ExtractionService,
)
from app.services.invoice import InvoiceService

log = structlog.get_logger()
router = APIRouter()

# Module-level strong reference set — prevents Python 3.12 GC from collecting tasks
# before they complete. Pattern: Python docs asyncio-task.html (Pattern 4 in 03-RESEARCH.md)
_background_tasks: set = set()

# In-memory dedupe set for webhook retries on the same MessageSid.
# Cleared on process restart (acceptable for v1; durable dedupe = task-queue upgrade).
# Resolves 03-REVIEWS.md Codex MEDIUM concern #4.
_processed_message_sids: set[str] = set()

# ---------------------------------------------------------------------------
# Spanish reply constants (D-07, D-10, D-11)
# ---------------------------------------------------------------------------

ACK_REPLY: str = "✅ Factura recibida. Procesando..."
NON_ALLOWLISTED_REPLY: str = "❌ Este número no está autorizado para enviar facturas."
UNREADABLE_REPLY: str = (
    "❌ No pudimos procesar la imagen. Asegurate de enviar una foto clara de la factura (JPG o PDF)."
)

# ---------------------------------------------------------------------------
# Plan 02: Spanish reply templates (D-08, D-09, D-12)
# ---------------------------------------------------------------------------

AUTO_SAVED_HEADER: str = "✅ Factura registrada:"
PENDING_REVIEW_HEADER: str = (
    "⚠️ Algunos campos no se pudieron leer con certeza. Revisar factura desde la web."
)
DUPLICATE_REPLY_TEMPLATE: str = (
    "🔁 Esta factura ya fue registrada el {fecha_original}. No se guardó de nuevo."
)
EM_DASH: str = "—"

# ---------------------------------------------------------------------------
# Supported image MIME types (Plan 02 uses this set for content-type gating)
# ---------------------------------------------------------------------------

SUPPORTED_IMAGE_TYPES: frozenset[str] = frozenset({"image/jpeg", "image/jpg", "image/png"})

# ---------------------------------------------------------------------------
# Plan 02: Magic-byte signature constants
# Resolves 03-REVIEWS.md HIGH concern #5 (T-3-09: spoofed MediaContentType0)
# Defense in depth — MIME type is provider-supplied metadata and could be
# spoofed by a misconfigured upstream. These constants validate the actual
# byte signature of downloaded media.
# ---------------------------------------------------------------------------

JPEG_MAGIC: bytes = b"\xff\xd8"  # JPEG SOI (Start of Image) marker
PNG_MAGIC: bytes = b"\x89\x50\x4e\x47"  # \x89PNG — PNG file signature first 4 bytes


# ---------------------------------------------------------------------------
# Provider factory (sole construction site — tests override via dependency_overrides)
# ---------------------------------------------------------------------------


def get_whatsapp_provider(settings: Settings = Depends(get_settings)) -> WhatsAppProvider:
    """Construct the active WhatsApp provider from settings.

    This is the SOLE construction site for WhatsApp provider instances in production.
    Tests override this via:
        app.dependency_overrides[get_whatsapp_provider] = lambda: mock_provider

    Raises:
        RuntimeError: If required credentials for the selected provider are missing.
        RuntimeError: If WHATSAPP_PROVIDER is set to an unknown value.
    """
    # Lazy imports inside factory — keeps test imports fast (no top-level twilio import)
    if settings.whatsapp_provider == "twilio":
        missing = [
            name
            for name, val in [
                ("TWILIO_ACCOUNT_SID", settings.twilio_account_sid),
                ("TWILIO_AUTH_TOKEN", settings.twilio_auth_token),
                ("TWILIO_FROM_NUMBER", settings.twilio_from_number),
            ]
            if not val
        ]
        if missing:
            raise RuntimeError(
                f"WHATSAPP_PROVIDER=twilio requires these env vars to be set: {', '.join(missing)}"
            )
        from app.providers.twilio import TwilioProvider
        return TwilioProvider(
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token,
            from_number=settings.twilio_from_number,
        )
    elif settings.whatsapp_provider == "meta":
        from app.providers.meta import MetaCloudProvider
        return MetaCloudProvider()
    else:
        raise RuntimeError(
            f"Unknown WHATSAPP_PROVIDER: {settings.whatsapp_provider!r}. "
            "Accepted values: 'twilio', 'meta'."
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_effective_url(request: Request, settings: Settings) -> str:
    """Return the URL to use for Twilio signature validation.

    When WEBHOOK_BASE_URL is set (e.g. when behind ngrok or a reverse proxy),
    Twilio signed the request against the public-facing URL, not the internal
    host reflected in request.url. This helper resolves 03-REVIEWS.md Codex
    MEDIUM concern #3.

    Args:
        request: The incoming FastAPI Request object.
        settings: The current Settings instance.

    Returns:
        The URL string Twilio used when computing X-Twilio-Signature.
    """
    if settings.webhook_base_url:
        return f"{settings.webhook_base_url.rstrip('/')}/webhook"
    return str(request.url)


def _validate_image_bytes(data: bytes) -> bool:
    """Return True iff data starts with a known image magic-byte signature.

    Defense in depth — MediaContentType0 from Twilio is provider-supplied metadata
    and could be spoofed by a misconfigured upstream. This validates the actual byte
    signature of the downloaded media before passing it to ExtractionService.
    Resolves 03-REVIEWS.md HIGH concern #5 (T-3-09).

    Recognized signatures:
      - JPEG: first 2 bytes == 0xFF 0xD8
      - PNG: first 4 bytes == 0x89 0x50 0x4E 0x47 (\\x89PNG)

    Args:
        data: Downloaded media bytes.

    Returns:
        True if the bytes begin with a recognized image signature, else False.
    """
    if len(data) < 2:
        return False
    if data[:2] == JPEG_MAGIC:
        return True
    if len(data) >= 4 and data[:4] == PNG_MAGIC:
        return True
    return False


def _compute_total(line_items: list) -> Decimal | None:
    """Compute total invoice value from extracted line items.

    Formula per REQUIREMENTS.md (precio_final_con_iva):
        total = Σ bultos × precio_unitario_sin_iva × (1 + iva_rate) × (1 - descuento_pct)

    Note: iva_rate and descuento_pct are stored as fractions (e.g. 0.21 = 21%, 0.05 = 5%),
    matching the ExtractedInvoice Pydantic model convention from Phase 2.

    Returns None when no usable line items produce a non-zero total
    (signals em-dash display to the caller).
    """
    total = Decimal("0")
    has_usable = False
    for li in line_items:
        bultos = li.bultos or Decimal("0")
        precio = li.precio_unitario_sin_iva or Decimal("0")
        iva = li.iva_rate or Decimal("0")
        descuento = li.descuento_pct or Decimal("0")
        line_total = bultos * precio * (Decimal("1") + iva) * (Decimal("1") - descuento)
        if precio != Decimal("0"):
            has_usable = True
        total += line_total

    if total == Decimal("0") and not has_usable:
        return None
    return total.quantize(Decimal("0.01"))


def format_summary_reply(result: ExtractionResult) -> str:
    """Format the D-08 (auto_saved) or D-09 (pending_review) WhatsApp reply.

    Uses the four critical header fields from result.invoice plus the computed
    total from line items. None fields are displayed as EM_DASH.

    Args:
        result: The ExtractionResult from ExtractionService.extract().

    Returns:
        Formatted multi-line Spanish reply string.
    """
    if result.status == "auto_saved":
        header = AUTO_SAVED_HEADER
    else:
        header = PENDING_REVIEW_HEADER

    inv = result.invoice
    total = _compute_total(inv.line_items)

    if total is not None:
        total_str = f"${total:,.2f}"
    else:
        total_str = EM_DASH

    lines = [
        header,
        f"• Proveedor: {inv.proveedor or EM_DASH}",
        f"• Número: {inv.numero_documento or EM_DASH}",
        f"• Fecha: {inv.fecha or EM_DASH}",
        f"• Total: {total_str}",
    ]
    return "\n".join(lines)


def format_duplicate_reply(existing: Invoice | None) -> str:
    """Format the D-12 duplicate WhatsApp reply.

    Prefers existing.fecha (the invoice's own date field) over created_at.
    Falls back to em-dash if neither is available or existing is None.

    Args:
        existing: The duplicate Invoice row, or None if the re-query after
                  IntegrityError found no row (pathological edge case).

    Returns:
        The D-12 Spanish duplicate reply string.
    """
    if existing is None:
        return DUPLICATE_REPLY_TEMPLATE.format(fecha_original=EM_DASH)

    if existing.fecha is not None:
        fecha_str = str(existing.fecha)
    elif existing.created_at is not None:
        fecha_str = existing.created_at.date().isoformat()
    else:
        fecha_str = EM_DASH

    return DUPLICATE_REPLY_TEMPLATE.format(fecha_original=fecha_str)


async def _safe_send(
    provider: WhatsAppProvider,
    to: str,
    text: str,
    task_log: structlog.stdlib.BoundLogger,
) -> None:
    """Send a WhatsApp message without crashing the background task on failure.

    Used for all non-summary reply branches (error paths, duplicate paths) so
    that a transient Twilio outage does not silently kill an in-flight task.
    The invoice has NOT been saved at these call sites — so failure means no
    data loss, just a missed notification.

    Args:
        provider: The active WhatsApp provider.
        to: Recipient phone number.
        text: Message text to send.
        task_log: Bound structlog logger for the current task context.
    """
    try:
        await provider.send_message(to=to, text=text)
    except Exception as exc:
        task_log.error(
            "whatsapp.reply_failed",
            error=str(exc),
            reply_text=text[:64],
        )


# ---------------------------------------------------------------------------
# Background task: real process_invoice pipeline (replaces Plan 01 placeholder)
# ---------------------------------------------------------------------------


async def process_invoice(
    sender: str,
    message_sid: str,
    media_url: str,
    media_content_type: str | None,
    provider: WhatsAppProvider,
) -> None:
    """Full invoice processing pipeline scheduled as an asyncio background task.

    Sequence (per 03-REVIEWS.md revisions and STRIDE threat model):
    1. Bind structlog context; log whatsapp.process_started.
    2. MIME type guard (pre-download) — rejects non-image MIME types without downloading.
    3. Construct ExtractionService and InvoiceService inside the task (not from DI).
    4. Download media bytes from the provider URL.
    5. Magic-byte guard (post-download) — validates actual byte signature (T-3-09).
    6. Extract invoice data via ExtractionService (writes original file via LocalStorageBackend).
    7. Open an async DB session (not from request lifecycle — uses get_async_session_local).
    8a. App-level duplicate check via InvoiceService.find_duplicate.
    8b. Persist via InvoiceService.save_invoice; on IntegrityError, re-query for real fecha (T-3-08).
    8c. Send summary reply; wrap in try/except so failure does NOT crash the task (T-3-14).

    Args:
        sender: From field value from webhook form (may include 'whatsapp:' prefix).
        message_sid: Twilio MessageSid — used as filename base and audit key.
        media_url: MediaUrl0 from the webhook form.
        media_content_type: MediaContentType0 from the webhook form (may be None).
        provider: The active WhatsApp provider instance.
    """
    task_log = structlog.get_logger().bind(sender=sender, message_sid=message_sid)
    task_log.info("whatsapp.process_started")

    # Step 2: MIME type guard (pre-download — avoids downloading unsupported content)
    if (
        media_content_type is None
        or media_content_type.lower().split(";")[0].strip() not in SUPPORTED_IMAGE_TYPES
    ):
        await _safe_send(provider, sender, UNREADABLE_REPLY, task_log)
        task_log.info("whatsapp.unsupported_media_type", media_content_type=media_content_type)
        return

    # Step 3: Construct services inside the task (background tasks cannot use Depends())
    from app.config import get_settings as _get_settings
    from openai import AsyncOpenAI
    from app.services.storage import LocalStorageBackend

    settings = _get_settings()
    extraction_service = ExtractionService(
        openai_client=AsyncOpenAI(api_key=settings.openai_api_key),
        storage=LocalStorageBackend(root=settings.storage_path),
        settings=settings,
    )
    invoice_service = InvoiceService()

    # Step 4: Download media
    try:
        image_bytes = await provider.download_media(media_url)
    except Exception as exc:
        await _safe_send(provider, sender, UNREADABLE_REPLY, task_log)
        task_log.error("whatsapp.media_download_failed", error=str(exc))
        return

    # Step 5: Magic-byte guard (post-download — T-3-09, resolves 03-REVIEWS.md HIGH concern #5)
    if not _validate_image_bytes(image_bytes):
        await _safe_send(provider, sender, UNREADABLE_REPLY, task_log)
        task_log.warning(
            "whatsapp.invalid_image_bytes",
            first_bytes=image_bytes[:4].hex() if image_bytes else "",
        )
        return

    # Step 6: Derive filename from MessageSid + content type extension
    ext_map = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png"}
    mime_key = media_content_type.lower().split(";")[0].strip()
    ext = ext_map.get(mime_key, ".jpg")
    filename = f"{message_sid}{ext}"

    # Extract invoice — ExtractionService also saves original file via LocalStorageBackend
    try:
        result = await extraction_service.extract(image_bytes, filename)
    except (ExtractionRefusalError, ExtractionFailedError) as exc:
        await _safe_send(provider, sender, UNREADABLE_REPLY, task_log)
        task_log.error("whatsapp.extraction_failed", error=str(exc))
        return

    # Step 7: Open DB session (background task cannot use Depends(get_db))
    # get_async_session_local is imported at module level so tests can patch it.
    session_local = get_async_session_local()

    async with session_local() as session:
        # Step 8a: App-level duplicate check
        existing = await invoice_service.find_duplicate(
            session, result.invoice.numero_documento, result.invoice.proveedor
        )
        if existing is not None:
            await _safe_send(provider, sender, format_duplicate_reply(existing), task_log)
            task_log.info("whatsapp.duplicate_detected", numero=result.invoice.numero_documento)
            return

        # Step 8b: Persist invoice (IntegrityError = race-condition duplicate)
        try:
            saved = await invoice_service.save_invoice(session, result, message_sid, sender)
        except IntegrityError:
            # Race condition: another concurrent task won the INSERT race.
            # Re-query so D-12 reply can show the real original fecha (03-REVIEWS.md MEDIUM #7).
            existing = await invoice_service.find_existing_for_race(
                session, result.invoice.numero_documento, result.invoice.proveedor
            )
            if existing is None:
                # Pathological: row was deleted between race and re-query
                task_log.warning("whatsapp.race_no_existing_row")
            await _safe_send(provider, sender, format_duplicate_reply(existing), task_log)
            task_log.info("whatsapp.duplicate_race")
            return

        # Step 8c: Send summary reply — wrap so failure does NOT crash the task (T-3-14)
        # Resolves 03-REVIEWS.md HIGH concern #6
        try:
            await provider.send_message(to=sender, text=format_summary_reply(result))
            task_log.info(
                "whatsapp.process_completed",
                status=result.status,
                invoice_id=str(saved.id),
            )
        except Exception as exc:
            # Invoice IS saved — this is a missed notification, not data loss.
            task_log.error(
                "whatsapp.reply_failed",
                invoice_id=str(saved.id),
                error=str(exc),
            )
            # Do NOT re-raise — task completes cleanly


# ---------------------------------------------------------------------------
# Webhook handler
# ---------------------------------------------------------------------------


@router.post("/webhook")
async def whatsapp_webhook(
    request: Request,
    From: str = Form(...),
    MessageSid: str = Form(...),
    NumMedia: str = Form("0"),
    MediaUrl0: str | None = Form(None),
    MediaContentType0: str | None = Form(None),
    Body: str = Form(""),
    db: AsyncSession = Depends(get_db),
    provider: WhatsAppProvider = Depends(get_whatsapp_provider),
    settings: Settings = Depends(get_settings),
) -> Response:
    """POST /whatsapp/webhook — inbound Twilio WhatsApp webhook handler.

    Flow (D-06 + 03-REVIEWS.md revisions):
    1. Read form data and X-Twilio-Signature header.
    2. Validate signature via provider.validate_signature → 401 on failure.
    3. MessageSid idempotency gate — dedupe retries before any business logic.
    4. Allowlist gate — reject non-allowlisted senders with D-10 Spanish reply.
    5. Media gate — reject messages with no media with D-11 Spanish reply.
    6. Send D-07 Spanish acknowledgement.
    7. Log multi-media v1 limitation if NumMedia > 1 (only MediaUrl0 is processed).
    8. Schedule background invoice processing via asyncio.create_task (retained in
       _background_tasks to prevent GC before completion — Pattern 4).
    9. Return HTTP 200 (empty body; Twilio accepts plain 200 as ACK).

    Returns HTTP 401 only for signature failures (security rejection).
    All business-logic rejections return HTTP 200 with a reply message (Twilio
    expects 200 even when we reject the sender — non-200 triggers retries).
    """
    # Step 1: read form data
    form_data = dict(await request.form())

    # Step 2: signature validation (INF-02, T-3-01)
    signature = request.headers.get("X-Twilio-Signature", "")
    effective_url = _compute_effective_url(request, settings)
    if not provider.validate_signature(effective_url, form_data, signature):
        log.warning("whatsapp.invalid_signature", effective_url=effective_url)
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Step 3: MessageSid idempotency gate (T-3-13, resolves 03-REVIEWS.md concern #4)
    if MessageSid in _processed_message_sids:
        log.info("whatsapp.duplicate_message_sid", message_sid=MessageSid)
        return Response(status_code=200)
    _processed_message_sids.add(MessageSid)

    # Step 4: allowlist gate (WA-02, T-3-02)
    normalized = From.replace("whatsapp:", "").strip()
    result = await db.execute(
        select(SenderAllowlist)
        .where(
            SenderAllowlist.phone_number == normalized,
            SenderAllowlist.is_active == True,  # noqa: E712
        )
        .limit(1)
    )
    if result.scalar_one_or_none() is None:
        await provider.send_message(to=From, text=NON_ALLOWLISTED_REPLY)
        log.info("whatsapp.rejected", sender=normalized, message_sid=MessageSid)
        # Explicit: no DB writes to invoices in this branch (T-3-02)
        return Response(status_code=200)

    # Step 5: media gate (D-11)
    if int(NumMedia) == 0 or MediaUrl0 is None:
        await provider.send_message(to=From, text=UNREADABLE_REPLY)
        log.info("whatsapp.no_media", sender=normalized, message_sid=MessageSid)
        return Response(status_code=200)

    # Step 6: send acknowledgement (WA-01, D-07)
    await provider.send_message(to=From, text=ACK_REPLY)
    log.info("whatsapp.ack_sent", sender=normalized, message_sid=MessageSid)

    # Step 7: log v1 multi-media limitation — only MediaUrl0 is processed
    # (MediaUrl1+ are silently dropped; user's primary invoice still gets processed)
    num_media_int = int(NumMedia)
    if num_media_int > 1:
        log.info(
            "whatsapp.multi_media_ignored",
            num_media=NumMedia,
            message_sid=MessageSid,
        )

    # Step 8: schedule background work (Pattern 4 — asyncio.create_task + strong ref)
    task = asyncio.create_task(
        process_invoice(
            sender=From,
            message_sid=MessageSid,
            media_url=MediaUrl0,
            media_content_type=MediaContentType0,
            provider=provider,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    # Step 9: return 200 within Twilio's 5-second window (INF-04)
    return Response(status_code=200)
