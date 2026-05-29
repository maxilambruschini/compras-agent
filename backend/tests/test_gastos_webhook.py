"""Tests for the gastos webhook router.

Tests signature validation, allowlist gating, background task scheduling,
MessageSid idempotency, media download/store/vision pipeline, and the
orchestrator dispatch path.

Strategy:
- ASGI tests use app.dependency_overrides[get_whatsapp_provider] to inject a
  mocked provider (no live Twilio calls).
- Database dependency is overridden with the db_session fixture so allowlist rows
  can be seeded per test.
- A function-scoped fixture clears _background_tasks and _processed_message_sids
  between tests to prevent cross-test state bleed.
- process_gasto_message tests monkeypatch collaborators inside the gastos module
  so the background task uses injected mocks without live OpenAI or DB calls.

Run: cd backend && python -m pytest tests/test_gastos_webhook.py -x -q
"""
import asyncio
import uuid
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import get_settings
from app.db.models import SenderAllowlist
from app.routers.gastos import (
    NON_ALLOWLISTED_REPLY,
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
    NumMedia: str = "0",
    MediaUrl0: str | None = None,
    MediaContentType0: str | None = None,
    Body: str = "Pago de queso en supermercado",
) -> dict:
    """Build a dict that mimics the form fields Twilio sends in a webhook POST."""
    if message_sid is None:
        message_sid = f"SM-test-{uuid.uuid4()}"
    d = {
        "From": From,
        "MessageSid": message_sid,
        "NumMedia": NumMedia,
        "Body": Body,
    }
    if MediaUrl0 is not None:
        d["MediaUrl0"] = MediaUrl0
    if MediaContentType0 is not None:
        d["MediaContentType0"] = MediaContentType0
    return d


def make_mock_provider(validate_returns: bool = True) -> MagicMock:
    """Build a mock WhatsApp provider suitable for webhook tests."""
    from app.providers.base import WhatsAppProvider
    mock = MagicMock(spec=WhatsAppProvider)
    mock.validate_signature = MagicMock(return_value=validate_returns)
    mock.send_message = AsyncMock()
    mock.download_media = AsyncMock(return_value=b"\xff\xd8\xff\xe0" + b"\x00" * 100)
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
async def webhook_client(db_session, monkeypatch):
    """ASGI client for the gastos webhook with mocked provider and DB.

    AGENT_MODE is already "gastos" (conftest.py env_setup line 55) so create_app()
    mounts the gastos router automatically. This fixture re-creates the app to pick up
    the current env.
    """
    monkeypatch.setenv("AGENT_MODE", "gastos")
    get_settings.cache_clear()

    from app.main import create_app
    from app.db.session import get_db

    app = create_app()
    mock_provider = make_mock_provider(validate_returns=True)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_whatsapp_provider] = lambda: mock_provider
    app.dependency_overrides[get_db] = override_get_db

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client, mock_provider, app

    app.dependency_overrides.clear()
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Webhook handler tests — fast-path assertions (no background task wait)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_signature(webhook_client):
    """Webhook returns 401 when provider.validate_signature returns False."""
    client, mock_provider, app = webhook_client
    mock_provider.validate_signature.return_value = False

    response = await client.post(
        "/webhook",
        data=make_twilio_form(),
        headers={"X-Twilio-Signature": "invalid-sig"},
    )

    assert response.status_code == 401
    mock_provider.send_message.assert_not_awaited()
    assert len(_background_tasks) == 0


@pytest.mark.asyncio
async def test_non_allowlisted_sender(webhook_client, db_session):
    """Non-allowlisted sender → 200, NON_ALLOWLISTED_REPLY sent, NO background task (success criterion 3)."""
    client, mock_provider, app = webhook_client
    # Do NOT seed allowlist for this sender

    response = await client.post(
        "/webhook",
        data=make_twilio_form(From="whatsapp:+5499999999999"),
        headers={"X-Twilio-Signature": "valid-sig"},
    )

    assert response.status_code == 200
    mock_provider.send_message.assert_awaited_once()
    call_kwargs = mock_provider.send_message.await_args.kwargs
    assert call_kwargs["text"] == NON_ALLOWLISTED_REPLY
    # No orchestrator dispatched
    assert len(_background_tasks) == 0


@pytest.mark.asyncio
async def test_allowlisted_text_only_dispatches_task(webhook_client, db_session):
    """Allowlisted sender, text-only (NumMedia=0) → 200 + background task scheduled (success criteria 1 + 5)."""
    import app.routers.gastos as gastos_module

    client, mock_provider, app_inst = webhook_client
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    mock_orchestrator = MagicMock()
    mock_orchestrator.handle_message = AsyncMock()

    with patch.object(gastos_module, "get_async_session_local", return_value=_make_session_local_mock(db_session)):
        with patch("app.routers.gastos.ConversationOrchestrator", return_value=mock_orchestrator):
            response = await client.post(
                "/webhook",
                data=make_twilio_form(From="whatsapp:+5491112345678", NumMedia="0"),
                headers={"X-Twilio-Signature": "valid-sig"},
            )
            # 200 returned immediately (success criterion 5 — before DB/GPT work)
            assert response.status_code == 200
            # Background task was scheduled (asyncio.create_task, not awaited)
            assert len(_background_tasks) == 1
            # Wait for task to complete
            await asyncio.sleep(0.2)

    mock_orchestrator.handle_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_duplicate_message_sid_no_second_task(webhook_client, db_session):
    """Duplicate MessageSid → second POST returns 200 but no second task scheduled (success criterion 4)."""
    import app.routers.gastos as gastos_module

    client, mock_provider, app_inst = webhook_client
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    mock_orchestrator = MagicMock()
    mock_orchestrator.handle_message = AsyncMock()

    form = make_twilio_form(
        From="whatsapp:+5491112345678",
        message_sid="SM-dedupe-gastos-001",
        NumMedia="0",
    )

    with patch.object(gastos_module, "get_async_session_local", return_value=_make_session_local_mock(db_session)):
        with patch("app.routers.gastos.ConversationOrchestrator", return_value=mock_orchestrator):
            response1 = await client.post(
                "/webhook",
                data=form,
                headers={"X-Twilio-Signature": "valid-sig"},
            )
            response2 = await client.post(
                "/webhook",
                data=form,
                headers={"X-Twilio-Signature": "valid-sig"},
            )
            await asyncio.sleep(0.2)

    assert response1.status_code == 200
    assert response2.status_code == 200
    # Only one task was ever scheduled (second POST was short-circuited by _processed_message_sids)
    assert "SM-dedupe-gastos-001" in _processed_message_sids
    # Orchestrator was called exactly once (from first POST only)
    mock_orchestrator.handle_message.assert_awaited_once()
    # The non-allowlisted reply should NOT have been sent (sender IS allowlisted)
    texts = [c.kwargs.get("text", "") for c in mock_provider.send_message.call_args_list]
    assert NON_ALLOWLISTED_REPLY not in texts


@pytest.mark.asyncio
async def test_response_returns_before_background_work(webhook_client, db_session):
    """The HTTP 200 response is produced without awaiting background task (success criterion 5).

    Verified by: the handler uses asyncio.create_task (not await) so the response
    returns with _background_tasks having exactly 1 pending task immediately after.
    """
    import app.routers.gastos as gastos_module

    client, mock_provider, app_inst = webhook_client
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    mock_orchestrator = MagicMock()
    mock_orchestrator.handle_message = AsyncMock()

    with patch.object(gastos_module, "get_async_session_local", return_value=_make_session_local_mock(db_session)):
        with patch("app.routers.gastos.ConversationOrchestrator", return_value=mock_orchestrator):
            response = await client.post(
                "/webhook",
                data=make_twilio_form(From="whatsapp:+5491112345678", NumMedia="0"),
                headers={"X-Twilio-Signature": "valid-sig"},
            )

            assert response.status_code == 200
            # The background task was scheduled (asyncio.create_task, not awaited inline)
            # This proves fast-200: the response returned with the task still in the set
            assert len(_background_tasks) == 1
            assert response.content == b""  # no task output leaked into response body
            await asyncio.sleep(0.1)


# ---------------------------------------------------------------------------
# Background task: media handling tests (success criterion 2)
# ---------------------------------------------------------------------------


def _make_session_local_mock(db_session):
    """Return an async_sessionmaker-compatible mock that yields db_session."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _session_ctx():
        yield db_session

    def _session_factory():
        return _session_ctx()

    return _session_factory


@pytest_asyncio.fixture
async def gastos_process_client(db_session, monkeypatch):
    """ASGI client for process_gasto_message pipeline tests."""
    monkeypatch.setenv("AGENT_MODE", "gastos")
    get_settings.cache_clear()

    from app.main import create_app
    from app.db.session import get_db

    app = create_app()
    mock_provider = make_mock_provider(validate_returns=True)
    mock_provider.download_media = AsyncMock(
        return_value=b"\xff\xd8\xff\xe0" + b"\x00" * 100
    )

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_whatsapp_provider] = lambda: mock_provider
    app.dependency_overrides[get_db] = override_get_db

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client, mock_provider, app, db_session

    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_media_present_downloads_stores_vision_dispatches(gastos_process_client):
    """Photo present → download, magic-byte guard, store via LocalStorageBackend,
    vision extract_amount, feed path+amount into handle_message (success criterion 2, D-06)."""
    client, mock_provider, app, db_session = gastos_process_client
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    from app import routers
    import app.routers.gastos as gastos_module

    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    mock_provider.download_media = AsyncMock(return_value=jpeg_bytes)

    mock_vision = MagicMock()
    mock_vision.extract_amount = AsyncMock(return_value=Decimal("1500.00"))

    mock_orchestrator = MagicMock()
    mock_orchestrator.handle_message = AsyncMock()

    mock_storage = MagicMock()
    mock_storage.save = MagicMock(return_value="SM-media-001/SM-media-001.jpg")

    with patch.object(gastos_module, "get_async_session_local", return_value=_make_session_local_mock(db_session)):
        with patch("app.routers.gastos.TicketVisionService", return_value=mock_vision):
            with patch("app.routers.gastos.LocalStorageBackend", return_value=mock_storage):
                with patch("app.routers.gastos.ConversationOrchestrator", return_value=mock_orchestrator):
                    response = await client.post(
                        "/webhook",
                        data=make_twilio_form(
                            From="whatsapp:+5491112345678",
                            message_sid="SM-media-001",
                            NumMedia="1",
                            MediaUrl0="https://api.twilio.com/media/test",
                            MediaContentType0="image/jpeg",
                            Body="ticket adjunto",
                        ),
                        headers={"X-Twilio-Signature": "valid-sig"},
                    )
                    await asyncio.sleep(0.2)

    assert response.status_code == 200
    # Vision was called with the downloaded bytes
    mock_vision.extract_amount.assert_awaited_once_with(jpeg_bytes)
    # Storage save was called
    mock_storage.save.assert_called_once()
    # Orchestrator was called with ticket_image_path and ticket_amount
    mock_orchestrator.handle_message.assert_awaited_once()
    call_kwargs = mock_orchestrator.handle_message.await_args.kwargs
    assert call_kwargs.get("ticket_amount") == Decimal("1500.00")
    assert call_kwargs.get("ticket_image_path") is not None


@pytest.mark.asyncio
async def test_bad_magic_bytes_no_vision_call(gastos_process_client):
    """Bad magic bytes → magic-byte guard fails; vision never called; orchestrator still invoked (no-photo path)."""
    client, mock_provider, app, db_session = gastos_process_client
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    import app.routers.gastos as gastos_module

    pdf_bytes = b"%PDF-1.4 fake pdf content"
    mock_provider.download_media = AsyncMock(return_value=pdf_bytes)

    mock_vision = MagicMock()
    mock_vision.extract_amount = AsyncMock(return_value=Decimal("500.00"))

    mock_orchestrator = MagicMock()
    mock_orchestrator.handle_message = AsyncMock()

    mock_storage = MagicMock()
    mock_storage.save = MagicMock(return_value="bad/bad.jpg")

    with patch.object(gastos_module, "get_async_session_local", return_value=_make_session_local_mock(db_session)):
        with patch("app.routers.gastos.TicketVisionService", return_value=mock_vision):
            with patch("app.routers.gastos.LocalStorageBackend", return_value=mock_storage):
                with patch("app.routers.gastos.ConversationOrchestrator", return_value=mock_orchestrator):
                    response = await client.post(
                        "/webhook",
                        data=make_twilio_form(
                            From="whatsapp:+5491112345678",
                            NumMedia="1",
                            MediaUrl0="https://api.twilio.com/media/bad",
                            MediaContentType0="image/jpeg",
                        ),
                        headers={"X-Twilio-Signature": "valid-sig"},
                    )
                    await asyncio.sleep(0.2)

    assert response.status_code == 200
    # Bad bytes never reach vision (T-3-09)
    mock_vision.extract_amount.assert_not_awaited()
    # Orchestrator IS still called but with ticket_image_path=None, ticket_amount=None
    mock_orchestrator.handle_message.assert_awaited_once()
    call_kwargs = mock_orchestrator.handle_message.await_args.kwargs
    assert call_kwargs.get("ticket_image_path") is None
    assert call_kwargs.get("ticket_amount") is None


@pytest.mark.asyncio
async def test_text_only_sin_ticket_dispatches_no_media(gastos_process_client):
    """Text-only message ("sin ticket", no MediaUrl0) → orchestrator called with ticket_image_path=None, ticket_amount=None."""
    client, mock_provider, app, db_session = gastos_process_client
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    import app.routers.gastos as gastos_module

    mock_orchestrator = MagicMock()
    mock_orchestrator.handle_message = AsyncMock()

    with patch.object(gastos_module, "get_async_session_local", return_value=_make_session_local_mock(db_session)):
        with patch("app.routers.gastos.ConversationOrchestrator", return_value=mock_orchestrator):
            response = await client.post(
                "/webhook",
                data=make_twilio_form(
                    From="whatsapp:+5491112345678",
                    NumMedia="0",
                    Body="sin ticket",
                ),
                headers={"X-Twilio-Signature": "valid-sig"},
            )
            await asyncio.sleep(0.2)

    assert response.status_code == 200
    mock_orchestrator.handle_message.assert_awaited_once()
    call_kwargs = mock_orchestrator.handle_message.await_args.kwargs
    assert call_kwargs.get("ticket_image_path") is None
    assert call_kwargs.get("ticket_amount") is None
    assert call_kwargs.get("text") == "sin ticket"
