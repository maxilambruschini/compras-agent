"""Tests for the WhatsApp webhook router.

Tests signature validation, allowlist gating, acknowledgement, background task scheduling,
WEBHOOK_BASE_URL override, and MessageSid idempotency.

These are Wave 0 scaffolds — Task 3 removes the skip markers and writes real assertions.

Run: cd backend && python -m pytest tests/test_whatsapp.py -x -q
"""
import uuid

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import structlog.testing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_twilio_form(
    From: str = "whatsapp:+5491112345678",
    message_sid: str | None = None,
    NumMedia: str = "1",
    MediaUrl0: str = "https://api.twilio.com/media/test",
    MediaContentType0: str = "image/jpeg",
    Body: str = "",
) -> dict:
    """Build a dict that mimics the form fields Twilio sends in a webhook POST.

    The `message_sid` kwarg defaults to a fresh SM-test-<uuid4> so each call
    gets a unique sid. Pass an explicit fixed value for dedupe tests.
    """
    if message_sid is None:
        message_sid = f"SM-test-{uuid.uuid4()}"
    return {
        "From": From,
        "MessageSid": message_sid,
        "NumMedia": NumMedia,
        "MediaUrl0": MediaUrl0,
        "MediaContentType0": MediaContentType0,
        "Body": Body,
    }


# ---------------------------------------------------------------------------
# Webhook tests (Wave 0 stubs — Task 3 implements)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.skip(reason="Wave 0 stub — implemented in Task 3")
async def test_invalid_signature():
    """Webhook returns HTTP 401 when provider.validate_signature returns False."""
    pass


@pytest.mark.asyncio
@pytest.mark.skip(reason="Wave 0 stub — implemented in Task 3")
async def test_valid_signature_allowlisted_sends_ack():
    """Webhook returns 200; send_message awaited with the D-07 Spanish ack string."""
    pass


@pytest.mark.asyncio
@pytest.mark.skip(reason="Wave 0 stub — implemented in Task 3")
async def test_non_allowlisted():
    """Non-allowlisted sender returns 200 + D-10 rejection; no task scheduled; no DB writes."""
    pass


@pytest.mark.asyncio
@pytest.mark.skip(reason="Wave 0 stub — implemented in Task 3")
async def test_no_media():
    """NumMedia=0 returns 200 + D-11 unreadable-image reply; no background task scheduled."""
    pass


@pytest.mark.asyncio
@pytest.mark.skip(reason="Wave 0 stub — implemented in Task 3")
async def test_background_task_scheduled():
    """Allowlisted + NumMedia=1: _background_tasks contains exactly one task after the call."""
    pass


@pytest.mark.asyncio
@pytest.mark.skip(reason="Wave 0 stub — implemented in Task 3")
async def test_webhook_url_passed_to_validator():
    """When WEBHOOK_BASE_URL is unset, validate_signature receives str(request.url)."""
    pass


@pytest.mark.asyncio
@pytest.mark.skip(reason="Wave 0 stub — implemented in Task 3")
async def test_webhook_base_url_overrides_request_url():
    """When WEBHOOK_BASE_URL is set, validate_signature receives the override URL."""
    pass


@pytest.mark.asyncio
@pytest.mark.skip(reason="Wave 0 stub — implemented in Task 3")
async def test_duplicate_message_sid():
    """Two POSTs with the same MessageSid: only one ack sent and one task scheduled."""
    pass
