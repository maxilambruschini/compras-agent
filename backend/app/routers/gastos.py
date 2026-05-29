"""Gastos webhook router — WhatsApp transport for the Gastos Bot (v2.0).

Structural clone of backend/app/routers/whatsapp.py (v1.0 invoice router).
Key difference: no hard media gate (gastos can be text-only — "sin ticket"); the
background task dispatches into ConversationOrchestrator.handle_message instead of
process_invoice.

Decisions implemented:
- D-05: fast-200 + asyncio.create_task; router _processed_message_sids fast-path
- D-06: router downloads, guards, stores ticket image and feeds path+amount to orchestrator
- D-09: router only mounts when AGENT_MODE='gastos' (enforced in main.py)

Threat model mitigations:
- T-02-W1: Twilio HMAC-SHA1 signature validation → 401 before any work
- T-02-W2: SenderAllowlist gate (is_active==True) before scheduling orchestrator
- T-02-W3: _processed_message_sids fast-path + orchestrator DB last_message_id
- T-02-W4: two-layer guard — MIME check + magic-byte check; bad bytes never reach vision
- T-02-W5: only download URLs from signature-validated Twilio webhook
- T-02-W6: filename derived from MessageSid; LocalStorageBackend.save is path-traversal-safe
- T-02-W7: HTTP 200 returned before any DB/GPT work
- T-02-W8: API key never logged
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.engine import get_async_session_local
from app.db.models import SenderAllowlist
from app.db.session import get_db
from app.providers.base import WhatsAppProvider
from app.services.conversation import ConversationOrchestrator
from app.services.extraction import ExtractionFailedError
from app.services.gasto import GastoService
from app.services.slot_extraction import SlotExtractionService
from app.services.storage import LocalStorageBackend
from app.services.ticket_vision import TicketVisionService

log = structlog.get_logger()
router = APIRouter()

# Module-level strong reference set — prevents Python 3.12 GC from collecting tasks
# before they complete. Pattern: Python docs asyncio-task.html (Pattern 4).
_background_tasks: set = set()

# In-memory dedupe set for webhook retries on the same MessageSid.
# Cleared on process restart (acceptable for v1; durable dedupe = orchestrator
# DB last_message_id which is the source of truth — D-05).
_processed_message_sids: set[str] = set()

# ---------------------------------------------------------------------------
# Spanish reply constants
# ---------------------------------------------------------------------------

NON_ALLOWLISTED_REPLY: str = "❌ Este número no está autorizado."

# NOTE: No ACK_REPLY constant — the orchestrator sends the first conversational
# reply. The webhook's job is transport only; the orchestrator owns all replies.

# ---------------------------------------------------------------------------
# Supported image MIME types (MIME guard — T-02-W4 layer 1)
# ---------------------------------------------------------------------------

SUPPORTED_IMAGE_TYPES: frozenset[str] = frozenset({"image/jpeg", "image/jpg", "image/png"})

# ---------------------------------------------------------------------------
# Magic-byte signature constants (T-02-W4 layer 2 — T-3-09)
# ---------------------------------------------------------------------------

JPEG_MAGIC: bytes = b"\xff\xd8"
PNG_MAGIC: bytes = b"\x89\x50\x4e\x47"  # \x89PNG


# ---------------------------------------------------------------------------
# Provider factory (sole construction site — tests override via dependency_overrides)
# ---------------------------------------------------------------------------


def get_whatsapp_provider(settings: Settings = Depends(get_settings)) -> WhatsAppProvider:
    """Construct the active WhatsApp provider from settings.

    Verbatim clone of whatsapp.py:119-158.
    Tests override via: app.dependency_overrides[get_whatsapp_provider] = lambda: mock
    """
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
    """Return the URL used for Twilio signature validation.

    Clone of whatsapp.py:166-183 — both agents share the canonical /webhook path
    so a single Twilio config works across AGENT_MODE.
    """
    if settings.webhook_base_url:
        return f"{settings.webhook_base_url.rstrip('/')}/webhook"
    return str(request.url)


def _validate_image_bytes(data: bytes) -> bool:
    """Return True iff data starts with a known image magic-byte signature.

    Verbatim clone of whatsapp.py:186-210. Defense-in-depth against spoofed MIME types.
    """
    if len(data) < 2:
        return False
    if data[:2] == JPEG_MAGIC:
        return True
    if len(data) >= 4 and data[:4] == PNG_MAGIC:
        return True
    return False


async def _safe_send(
    provider: WhatsAppProvider,
    to: str,
    text: str,
    task_log: structlog.stdlib.BoundLogger,
) -> None:
    """Send a WhatsApp message without crashing the background task on failure.

    Verbatim clone of whatsapp.py:303-329.
    """
    try:
        await provider.send_message(to=to, text=text)
    except Exception as exc:
        task_log.error(
            "gastos.reply_failed",
            error=str(exc),
            reply_text=text[:64],
        )


# ---------------------------------------------------------------------------
# Background task: orchestrator dispatch with optional media handling (D-06)
# ---------------------------------------------------------------------------


async def process_gasto_message(
    sender: str,
    message_sid: str,
    body: str,
    media_url: str | None,
    media_content_type: str | None,
    provider: WhatsAppProvider,
) -> None:
    """Gastos pipeline: media guard/store/vision → orchestrator dispatch.

    Constructs collaborators inline (no Depends — background tasks cannot use DI).
    Mirrors process_invoice collaborator construction at whatsapp.py:377-388.

    D-06 media handling:
    1. If media_url present: MIME guard (skip vision if unsupported, treat as no-photo)
    2. Download bytes via provider.download_media
    3. Magic-byte guard (bad bytes never reach vision — T-3-09)
    4. Store via LocalStorageBackend.save (always stored when valid, D-02)
    5. Call TicketVisionService.extract_amount; on ExtractionFailedError → ticket_amount=None
    6. Feed stored path + amount into orchestrator.handle_message
    """
    task_log = structlog.get_logger().bind(sender=sender, message_sid=message_sid)
    task_log.info("gastos.process_started")

    try:
        # Construct collaborators inside the task (no Depends).
        # Classes are imported at module level (so tests can patch them via patch.object
        # or patch("app.routers.gastos.X")). Settings and OpenAI client are constructed
        # here to pick up the runtime env vars (not at import time).
        from app.config import get_settings as _get_settings
        from openai import AsyncOpenAI

        settings = _get_settings()
        openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
        storage = LocalStorageBackend(root=settings.storage_path)
        slot_service = SlotExtractionService(
            openai_client=openai_client,
            settings=settings,
        )
        gasto_service = GastoService()
        vision = TicketVisionService(openai_client=openai_client, settings=settings)
        orchestrator = ConversationOrchestrator(
            slot_service=slot_service,
            gasto_service=gasto_service,
            provider=provider,
        )

        # D-06: media handling
        ticket_path: str | None = None
        ticket_amount: Decimal | None = None

        if media_url is not None:
            # Layer 1: MIME guard (pre-download — avoids downloading unsupported content)
            mime_type = (media_content_type or "").lower().split(";")[0].strip()
            if mime_type not in SUPPORTED_IMAGE_TYPES:
                task_log.info("gastos.unsupported_media_type", media_content_type=media_content_type)
                # Treat as no-photo: ticket_path=None, ticket_amount=None; orchestrator handles
            else:
                # Download
                try:
                    image_bytes = await provider.download_media(media_url)
                except Exception as exc:
                    task_log.error("gastos.media_download_failed", error=str(exc))
                    image_bytes = None

                if image_bytes is not None:
                    # Layer 2: magic-byte guard (post-download — T-3-09)
                    if not _validate_image_bytes(image_bytes):
                        task_log.warning(
                            "gastos.invalid_image_bytes",
                            first_bytes=image_bytes[:4].hex() if image_bytes else "",
                        )
                        # Bad bytes: treat as no-photo (never reach vision)
                    else:
                        # Store (always store valid bytes, D-02)
                        ext_map = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png"}
                        ext = ext_map.get(mime_type, ".jpg")
                        filename = f"{message_sid}/{message_sid}{ext}"
                        try:
                            ticket_path = storage.save(image_bytes, filename)
                        except Exception as exc:
                            task_log.error("gastos.storage_failed", error=str(exc))
                            ticket_path = None

                        if ticket_path is not None:
                            # Vision: extract amount (on ExtractionFailedError → None, D-01b fallback)
                            try:
                                ticket_amount = await vision.extract_amount(image_bytes)
                            except ExtractionFailedError as exc:
                                task_log.warning("gastos.vision_failed", error=str(exc))
                                ticket_amount = None

        # Dispatch to orchestrator
        await orchestrator.handle_message(
            session_factory=get_async_session_local(),
            sender=sender,
            text=body,
            message_id=message_sid,
            ticket_image_path=ticket_path,
            ticket_amount=ticket_amount,
        )

    except Exception as exc:
        # Never crash the worker — log and exit cleanly (T-02-W8: never log API key)
        task_log.error("gastos.process_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Webhook handler
# ---------------------------------------------------------------------------


@router.post("/webhook")
async def gastos_webhook(
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
    """POST /gastos/webhook — inbound Twilio WhatsApp webhook handler.

    Flow (mirroring whatsapp.py with gastos-specific differences):
    1. Read form data and X-Twilio-Signature header.
    2. Validate signature via provider.validate_signature → 401 on failure (T-02-W1).
    3. MessageSid idempotency gate — dedupe retries before any business logic (T-02-W3).
    4. Allowlist gate — reject non-allowlisted senders with Spanish reply (T-02-W2).
    5. NO hard media gate — gastos conversations can be text-only ("sin ticket").
    6. Schedule background dispatch via asyncio.create_task (T-02-W7 fast-200).
    7. Return HTTP 200 immediately (D-05).

    Returns HTTP 401 only for signature failures.
    All business-logic rejections return HTTP 200 (Twilio expects 200; non-200 retries).
    """
    # Step 1: read form data
    form_data = dict(await request.form())

    # Step 2: signature validation (T-02-W1)
    signature = request.headers.get("X-Twilio-Signature", "")
    effective_url = _compute_effective_url(request, settings)
    if not provider.validate_signature(effective_url, form_data, signature):
        log.warning("gastos.invalid_signature", effective_url=effective_url)
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Step 3: MessageSid idempotency gate (D-05 router fast-path; T-02-W3)
    if MessageSid in _processed_message_sids:
        log.info("gastos.duplicate_message_sid", message_sid=MessageSid)
        return Response(status_code=200)
    _processed_message_sids.add(MessageSid)

    # Step 4: allowlist gate (T-02-W2)
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
        log.info("gastos.rejected", sender=normalized, message_sid=MessageSid)
        # No orchestrator call, no DB write (T-02-W2)
        return Response(status_code=200)

    # Step 5: NOTE — no hard media gate for gastos.
    # A gasto conversation can be text-only ("sin ticket") — this is the key difference
    # from the invoice webhook (which rejects NumMedia==0). MediaUrl0 is optional; the
    # background task handles media presence/absence per D-06.

    # Step 6: schedule background dispatch (Pattern 4 — asyncio.create_task + strong ref)
    task = asyncio.create_task(
        process_gasto_message(
            sender=From,
            message_sid=MessageSid,
            body=Body,
            media_url=MediaUrl0,
            media_content_type=MediaContentType0,
            provider=provider,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    # Step 7: return 200 before any DB/GPT work (D-05 fast-200, T-02-W7)
    return Response(status_code=200)
