"""Tests for the WhatsApp webhook router.

Tests signature validation, allowlist gating, acknowledgement, background task
scheduling, WEBHOOK_BASE_URL override, and MessageSid idempotency.

Strategy:
- ASGI tests use app.dependency_overrides[get_whatsapp_provider] to inject a
  mocked provider (no live Twilio calls).
- Database dependency is overridden with the db_session fixture so allowlist rows
  can be seeded per test.
- A function-scoped fixture clears _background_tasks and _processed_message_sids
  between tests to prevent cross-test state bleed.

Run: cd backend && python -m pytest tests/test_whatsapp.py -x -q
"""
import asyncio
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock, MagicMock

from app.config import get_settings
from app.db.models import Invoice, SenderAllowlist
from app.routers.whatsapp import (
    ACK_REPLY,
    NON_ALLOWLISTED_REPLY,
    UNREADABLE_REPLY,
    _background_tasks,
    _processed_message_sids,
    get_whatsapp_provider,
)


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


def make_mock_provider(validate_returns: bool = True) -> MagicMock:
    """Build a mock WhatsApp provider suitable for webhook tests."""
    from app.providers.base import WhatsAppProvider
    mock = MagicMock(spec=WhatsAppProvider)
    mock.validate_signature = MagicMock(return_value=validate_returns)
    mock.send_message = AsyncMock()
    mock.download_media = AsyncMock(return_value=b"fake-image-bytes")
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_module_state():
    """Clear module-level sets between tests to prevent cross-test bleed."""
    _background_tasks.clear()
    _processed_message_sids.clear()
    yield
    _background_tasks.clear()
    _processed_message_sids.clear()


@pytest_asyncio.fixture
async def webhook_client(db_session):
    """ASGI client for the WhatsApp webhook with mocked provider and DB."""
    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    mock_provider = make_mock_provider(validate_returns=True)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_whatsapp_provider] = lambda: mock_provider
    app.dependency_overrides[get_settings.__wrapped__ if hasattr(get_settings, '__wrapped__') else get_settings] = lambda: get_settings()

    # Override get_db with the test db_session
    from app.db.session import get_db
    app.dependency_overrides[get_db] = override_get_db

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client, mock_provider, app

    app.dependency_overrides.clear()
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Webhook tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_signature(webhook_client):
    """Webhook returns HTTP 401 when provider.validate_signature returns False."""
    client, mock_provider, app = webhook_client
    mock_provider.validate_signature.return_value = False

    response = await client.post(
        "/whatsapp/webhook",
        data=make_twilio_form(),
        headers={"X-Twilio-Signature": "invalid-sig"},
    )

    assert response.status_code == 401
    mock_provider.send_message.assert_not_awaited()
    assert len(_background_tasks) == 0


@pytest.mark.asyncio
async def test_valid_signature_allowlisted_sends_ack(webhook_client, db_session):
    """Webhook returns 200; send_message awaited with the D-07 Spanish ack string."""
    client, mock_provider, app = webhook_client

    # Seed allowlist
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    response = await client.post(
        "/whatsapp/webhook",
        data=make_twilio_form(From="whatsapp:+5491112345678"),
        headers={"X-Twilio-Signature": "valid-sig"},
    )

    assert response.status_code == 200
    mock_provider.send_message.assert_awaited_once()
    call_kwargs = mock_provider.send_message.await_args.kwargs
    assert call_kwargs["to"] == "whatsapp:+5491112345678"
    assert call_kwargs["text"] == ACK_REPLY


@pytest.mark.asyncio
async def test_non_allowlisted(webhook_client, db_session):
    """Non-allowlisted sender returns 200 + D-10 rejection; no task scheduled; no DB writes."""
    client, mock_provider, app = webhook_client
    # Do NOT seed allowlist row for this sender

    response = await client.post(
        "/whatsapp/webhook",
        data=make_twilio_form(From="whatsapp:+5499999999999"),
        headers={"X-Twilio-Signature": "valid-sig"},
    )

    assert response.status_code == 200
    mock_provider.send_message.assert_awaited_once()
    call_kwargs = mock_provider.send_message.await_args.kwargs
    assert call_kwargs["text"] == NON_ALLOWLISTED_REPLY
    assert len(_background_tasks) == 0

    # No rows inserted into invoices (T-3-02 explicit no-write assertion)
    result = await db_session.execute(select(func.count()).select_from(Invoice))
    count = result.scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_no_media(webhook_client, db_session):
    """NumMedia=0 returns 200 + D-11 unreadable-image reply; no background task scheduled."""
    client, mock_provider, app = webhook_client

    # Seed allowlist
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    response = await client.post(
        "/whatsapp/webhook",
        data=make_twilio_form(From="whatsapp:+5491112345678", NumMedia="0"),
        headers={"X-Twilio-Signature": "valid-sig"},
    )

    assert response.status_code == 200
    mock_provider.send_message.assert_awaited_once()
    call_kwargs = mock_provider.send_message.await_args.kwargs
    assert call_kwargs["text"] == UNREADABLE_REPLY
    assert len(_background_tasks) == 0


@pytest.mark.asyncio
async def test_background_task_scheduled(webhook_client, db_session):
    """Allowlisted + NumMedia=1: _background_tasks contains exactly one task after the call."""
    client, mock_provider, app = webhook_client

    # Seed allowlist
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    response = await client.post(
        "/whatsapp/webhook",
        data=make_twilio_form(From="whatsapp:+5491112345678", NumMedia="1"),
        headers={"X-Twilio-Signature": "valid-sig"},
    )

    assert response.status_code == 200
    assert len(_background_tasks) == 1

    # Wait for the placeholder coroutine to finish and the discard callback to fire
    await asyncio.sleep(0.05)
    assert len(_background_tasks) == 0


@pytest.mark.asyncio
async def test_webhook_url_passed_to_validator(webhook_client, db_session):
    """When WEBHOOK_BASE_URL is unset (default), validate_signature receives str(request.url)."""
    client, mock_provider, app = webhook_client

    # Seed allowlist
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    response = await client.post(
        "/whatsapp/webhook",
        data=make_twilio_form(From="whatsapp:+5491112345678"),
        headers={"X-Twilio-Signature": "valid-sig"},
    )

    assert response.status_code == 200
    call_args = mock_provider.validate_signature.call_args
    effective_url = call_args.args[0]
    # When webhook_base_url is None, the effective URL is str(request.url)
    assert effective_url == "http://testserver/whatsapp/webhook"


@pytest.mark.asyncio
async def test_webhook_base_url_overrides_request_url(db_session, monkeypatch):
    """When WEBHOOK_BASE_URL is set, validate_signature receives the override URL."""
    monkeypatch.setenv("WEBHOOK_BASE_URL", "https://abcd.ngrok-free.app")
    get_settings.cache_clear()

    from app.main import create_app
    from app.db.session import get_db

    app = create_app()
    mock_provider = make_mock_provider(validate_returns=True)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_whatsapp_provider] = lambda: mock_provider
    app.dependency_overrides[get_db] = override_get_db

    # Seed allowlist
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/whatsapp/webhook",
            data=make_twilio_form(From="whatsapp:+5491112345678"),
            headers={"X-Twilio-Signature": "valid-sig"},
        )

    app.dependency_overrides.clear()
    get_settings.cache_clear()

    assert response.status_code == 200
    call_args = mock_provider.validate_signature.call_args
    effective_url = call_args.args[0]
    assert effective_url == "https://abcd.ngrok-free.app/whatsapp/webhook"


@pytest.mark.asyncio
async def test_duplicate_message_sid(webhook_client, db_session):
    """Two POSTs with the same MessageSid: only one ack sent and one task scheduled."""
    client, mock_provider, app = webhook_client

    # Seed allowlist
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    form = make_twilio_form(
        From="whatsapp:+5491112345678",
        message_sid="SM-dedupe-001",
        NumMedia="1",
    )

    # First POST
    response1 = await client.post(
        "/whatsapp/webhook",
        data=form,
        headers={"X-Twilio-Signature": "valid-sig"},
    )
    # Second POST with same MessageSid
    response2 = await client.post(
        "/whatsapp/webhook",
        data=form,
        headers={"X-Twilio-Signature": "valid-sig"},
    )

    assert response1.status_code == 200
    assert response2.status_code == 200

    # Only one ack was sent (first call only)
    assert mock_provider.send_message.await_count == 1

    # The MessageSid was deduplicated: only one task was ever scheduled.
    # Since the placeholder coroutine runs immediately (asyncio.sleep(0)), the task may
    # already be done and discarded from _background_tasks by the time we assert here.
    # We verify deduplication by checking that send_message was called exactly once
    # (which proves the second POST was short-circuited before any ack or task creation).
    # We also verify _processed_message_sids contains the MessageSid (dedup record exists).
    assert "SM-dedupe-001" in _processed_message_sids
