"""Unit tests for WhatsApp provider implementations.

Tests TwilioProvider in isolation using mocked Twilio SDK objects.
These are Wave 0 scaffolds — Task 2 removes the skip markers and writes real assertions.

Run: cd backend && python -m pytest tests/test_providers.py -x -q
"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx


# ---------------------------------------------------------------------------
# test_validate_signature_calls_validator
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Wave 0 stub — implemented in Task 2")
def test_validate_signature_calls_validator():
    """TwilioProvider.validate_signature delegates to RequestValidator.validate(url, params, sig)."""
    pass


# ---------------------------------------------------------------------------
# test_send_message_uses_async_client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.skip(reason="Wave 0 stub — implemented in Task 2")
async def test_send_message_uses_async_client():
    """TwilioProvider.send_message calls client.messages.create_async(body=text, from_=..., to=...)."""
    pass


# ---------------------------------------------------------------------------
# test_download_media_uses_basic_auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.skip(reason="Wave 0 stub — implemented in Task 2")
async def test_download_media_uses_basic_auth():
    """TwilioProvider.download_media calls httpx.AsyncClient.get(media_url, auth=(account_sid, auth_token))."""
    pass


# ---------------------------------------------------------------------------
# test_download_media_rejects_non_twilio_host
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.skip(reason="Wave 0 stub — implemented in Task 2")
async def test_download_media_rejects_non_twilio_host():
    """SSRF guard: download_media raises ValueError for URLs not starting with https://api.twilio.com/."""
    pass
