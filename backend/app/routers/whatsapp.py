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
- INF-02: HMAC-based signature validation (Twilio HMAC-SHA1 via RequestValidator)
- INF-04: Handler returns 200 within Twilio's 5-second timeout window
- D-06: Request flow: validate → dedupe → allowlist → ack → background task
- D-07: Ack copy: "✅ Factura recibida. Procesando..."
- D-10: Rejection copy: "❌ Este número no está autorizado para enviar facturas."
- D-11: No-media copy: "❌ No pudimos procesar la imagen. Asegurate de enviar una foto clara de la factura (JPG o PDF)."
"""
from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import SenderAllowlist
from app.db.session import get_db
from app.providers.base import WhatsAppProvider

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
# Supported image MIME types (Plan 02 uses this set for content-type gating)
# ---------------------------------------------------------------------------

SUPPORTED_IMAGE_TYPES: frozenset[str] = frozenset({"image/jpeg", "image/jpg", "image/png"})


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
        return f"{settings.webhook_base_url.rstrip('/')}/whatsapp/webhook"
    return str(request.url)


# ---------------------------------------------------------------------------
# Background task placeholder (Plan 02 replaces this with process_invoice)
# ---------------------------------------------------------------------------


async def _process_invoice_placeholder(
    sender: str,
    message_sid: str,
    media_url: str | None,
    media_content_type: str | None,
    provider: WhatsAppProvider,
) -> None:
    """Placeholder background coroutine scheduled by the webhook handler.

    This v1 stub yields once and logs. Plan 02 replaces this function with the
    real process_invoice pipeline (download → extract → save → reply). The
    signature MUST remain stable so Plan 02 can monkey-patch or override at the
    import point without touching the webhook handler body.

    Args:
        sender: Sender phone number (From field, with 'whatsapp:' prefix).
        message_sid: Twilio MessageSid for idempotency.
        media_url: MediaUrl0 from the webhook form (may be None).
        media_content_type: MediaContentType0 from the webhook form (may be None).
        provider: The active WhatsApp provider instance.
    """
    await asyncio.sleep(0)
    log.info(
        "whatsapp.background_placeholder",
        sender=sender,
        message_sid=message_sid,
    )


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
    7. Schedule background invoice processing via asyncio.create_task (retained in
       _background_tasks to prevent GC before completion — Pattern 4).
    8. Return HTTP 200 (empty body; Twilio accepts plain 200 as ACK).

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

    # Step 7: schedule background work (Pattern 4 — asyncio.create_task + strong ref)
    task = asyncio.create_task(
        _process_invoice_placeholder(
            sender=From,
            message_sid=MessageSid,
            media_url=MediaUrl0,
            media_content_type=MediaContentType0,
            provider=provider,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    # Step 8: return 200 within Twilio's 5-second window (INF-04)
    return Response(status_code=200)
