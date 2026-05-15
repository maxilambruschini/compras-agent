"""Unit tests for WhatsApp provider implementations.

Tests TwilioProvider in isolation using mocked Twilio SDK objects (RequestValidator,
AsyncTwilioHttpClient, httpx.AsyncClient). No live Twilio calls are made.

Run: cd backend && python -m pytest tests/test_providers.py -x -q
"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_twilio_provider():
    """Return a TwilioProvider constructed with test credentials."""
    from app.providers.twilio import TwilioProvider
    return TwilioProvider(
        account_sid="ACtest-sid",
        auth_token="test-auth-token",
        from_number="whatsapp:+14155238886",
    )


# ---------------------------------------------------------------------------
# test_validate_signature_calls_validator
# ---------------------------------------------------------------------------


@patch("app.providers.twilio.RequestValidator")
def test_validate_signature_calls_validator(mock_validator_cls):
    """TwilioProvider.validate_signature delegates to RequestValidator.validate(url, params, sig)."""
    mock_validator = MagicMock()
    mock_validator.validate.return_value = True
    mock_validator_cls.return_value = mock_validator

    provider = make_twilio_provider()
    result = provider.validate_signature("https://example.com/whatsapp/webhook", {"From": "+1"}, "sig123")

    assert result is True
    mock_validator.validate.assert_called_once_with(
        "https://example.com/whatsapp/webhook",
        {"From": "+1"},
        "sig123",
    )


# ---------------------------------------------------------------------------
# test_send_message_uses_async_client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.providers.twilio.AsyncTwilioHttpClient")
@patch("app.providers.twilio.Client")
async def test_send_message_uses_async_client(mock_client_cls, mock_http_client_cls):
    """TwilioProvider.send_message calls client.messages.create_async(body=text, from_=..., to=...)."""
    mock_http_client = MagicMock()
    mock_http_client.close = AsyncMock()
    mock_http_client_cls.return_value = mock_http_client

    mock_messages = MagicMock()
    mock_messages.create_async = AsyncMock(return_value=MagicMock())
    mock_client_instance = MagicMock()
    mock_client_instance.messages = mock_messages
    mock_client_cls.return_value = mock_client_instance

    provider = make_twilio_provider()
    await provider.send_message(to="whatsapp:+5491112345678", text="Hello!")

    mock_client_cls.assert_called_once_with(
        "ACtest-sid", "test-auth-token", http_client=mock_http_client
    )
    mock_messages.create_async.assert_awaited_once_with(
        body="Hello!",
        from_="whatsapp:+14155238886",
        to="whatsapp:+5491112345678",
    )
    mock_http_client.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# test_download_media_uses_basic_auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.providers.twilio.httpx.AsyncClient")
async def test_download_media_uses_basic_auth(mock_async_client_cls):
    """TwilioProvider.download_media calls httpx.AsyncClient.get(media_url, auth=(account_sid, auth_token))."""
    mock_response = MagicMock()
    mock_response.content = b"fake-image-bytes"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_async_client_cls.return_value = mock_client

    provider = make_twilio_provider()
    result = await provider.download_media("https://api.twilio.com/media/test-image")

    mock_client.get.assert_awaited_once_with(
        "https://api.twilio.com/media/test-image",
        auth=("ACtest-sid", "test-auth-token"),
    )
    mock_response.raise_for_status.assert_called_once()
    assert result == b"fake-image-bytes"


# ---------------------------------------------------------------------------
# test_download_media_rejects_non_twilio_host
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_media_rejects_non_twilio_host():
    """SSRF guard: download_media raises ValueError for URLs not starting with https://api.twilio.com/."""
    provider = make_twilio_provider()

    with pytest.raises(ValueError, match="Refusing to fetch non-Twilio media URL"):
        await provider.download_media("https://evil.example.com/malicious-payload")

    with pytest.raises(ValueError, match="Refusing to fetch non-Twilio media URL"):
        await provider.download_media("http://api.twilio.com/media/test")  # HTTP, not HTTPS

    with pytest.raises(ValueError, match="Refusing to fetch non-Twilio media URL"):
        await provider.download_media("https://api.twilio.com.evil.com/media/test")  # Subdomain hijack
