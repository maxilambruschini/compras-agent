"""Tests for the WhatsApp webhook router.

Tests signature validation, allowlist gating, acknowledgement, background task
scheduling, WEBHOOK_BASE_URL override, MessageSid idempotency, and the full
process_invoice pipeline (Plan 02: magic-byte validation, extraction, duplicate
detection, reply formatting, race-condition handling, reply-send failure logging).

Strategy:
- ASGI tests use app.dependency_overrides[get_whatsapp_provider] to inject a
  mocked provider (no live Twilio calls).
- Database dependency is overridden with the db_session fixture so allowlist rows
  can be seeded per test.
- A function-scoped fixture clears _background_tasks and _processed_message_sids
  between tests to prevent cross-test state bleed.
- process_invoice tests monkeypatch ExtractionService and InvoiceService inside
  the whatsapp module so the background task uses injected mocks without live
  OpenAI or DB calls.

Run: cd backend && python -m pytest tests/test_whatsapp.py -x -q
"""
import asyncio
import uuid
from datetime import date
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
import structlog.testing
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import get_settings
from app.db.models import Invoice, SenderAllowlist
from app.models.extraction import ExtractedInvoice, LineItem, TipoComprobante
from app.routers.whatsapp import (
    ACK_REPLY,
    NON_ALLOWLISTED_REPLY,
    UNREADABLE_REPLY,
    _background_tasks,
    _processed_message_sids,
    get_whatsapp_provider,
)
from app.services.extraction import ExtractionResult


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
async def webhook_client(db_session, monkeypatch):
    """ASGI client for the WhatsApp webhook with mocked provider and DB.

    Forces AGENT_MODE=invoice so create_app() mounts the invoice webhook router
    (the suite's default AGENT_MODE is "gastos", which intentionally leaves it unmounted).
    """
    monkeypatch.setenv("AGENT_MODE", "invoice")
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
        "/webhook",
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
        "/webhook",
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
        "/webhook",
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
        "/webhook",
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
        "/webhook",
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
        "/webhook",
        data=make_twilio_form(From="whatsapp:+5491112345678"),
        headers={"X-Twilio-Signature": "valid-sig"},
    )

    assert response.status_code == 200
    call_args = mock_provider.validate_signature.call_args
    effective_url = call_args.args[0]
    # When webhook_base_url is None, the effective URL is str(request.url)
    assert effective_url == "http://testserver/webhook"


@pytest.mark.asyncio
async def test_webhook_base_url_overrides_request_url(db_session, monkeypatch):
    """When WEBHOOK_BASE_URL is set, validate_signature receives the override URL."""
    monkeypatch.setenv("AGENT_MODE", "invoice")
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
            "/webhook",
            data=make_twilio_form(From="whatsapp:+5491112345678"),
            headers={"X-Twilio-Signature": "valid-sig"},
        )

    app.dependency_overrides.clear()
    get_settings.cache_clear()

    assert response.status_code == 200
    call_args = mock_provider.validate_signature.call_args
    effective_url = call_args.args[0]
    assert effective_url == "https://abcd.ngrok-free.app/webhook"


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
        "/webhook",
        data=form,
        headers={"X-Twilio-Signature": "valid-sig"},
    )
    # Second POST with same MessageSid
    response2 = await client.post(
        "/webhook",
        data=form,
        headers={"X-Twilio-Signature": "valid-sig"},
    )

    assert response1.status_code == 200
    assert response2.status_code == 200

    # Wait for background task to complete (process_invoice now runs the real pipeline)
    await asyncio.sleep(0.1)

    # The MessageSid was deduplicated: only ONE task was ever scheduled (second POST was
    # short-circuited by _processed_message_sids before any ack or task creation).
    # We verify deduplication by checking _processed_message_sids and that exactly ONE
    # ack was sent. The background task also sends UNREADABLE_REPLY (fake bytes fail
    # magic-byte validation) so total send count is 2 (ack + UNREADABLE), NOT 3.
    assert "SM-dedupe-001" in _processed_message_sids

    # Exactly one ack was sent (from the first POST) — the second POST was short-circuited
    ack_calls = [
        c for c in mock_provider.send_message.call_args_list
        if c.kwargs.get("text") == ACK_REPLY
    ]
    assert len(ack_calls) == 1


# ===========================================================================
# Plan 02 tests: process_invoice pipeline
# ===========================================================================
# These tests import new symbols from the whatsapp router. They will fail in
# RED phase because the symbols do not exist yet.
# ===========================================================================


# ---------------------------------------------------------------------------
# Helper builders for Plan 02 tests
# ---------------------------------------------------------------------------

def _make_stub_invoice(
    numero: str = "0001-00001",
    proveedor: str = "Acme SA",
    fecha: str = "2026-05-10",
) -> ExtractedInvoice:
    """Build a stub ExtractedInvoice for process_invoice test fixtures."""
    return ExtractedInvoice(
        tipo_comprobante=TipoComprobante.FACTURA_A,
        numero_documento=numero,
        proveedor=proveedor,
        fecha=fecha,
        cuit_proveedor="20-12345678-9",
        line_items=[
            LineItem(
                descripcion="Widget",
                bultos=Decimal("2"),
                precio_unitario_sin_iva=Decimal("100"),
                iva_rate=Decimal("0.21"),
                descuento_pct=Decimal("0"),
            )
        ],
    )


def _make_extraction_result(
    numero: str = "0001-00001",
    proveedor: str = "Acme SA",
    status: str = "auto_saved",
    confidence: float = 0.9,
    image_path: str = "/tmp/invoices/SM-001.jpg",
) -> ExtractionResult:
    """Build a stub ExtractionResult."""
    return ExtractionResult(
        invoice=_make_stub_invoice(numero=numero, proveedor=proveedor),
        confidence_score=confidence,
        status=status,
        image_path=image_path,
    )


def _make_mock_extraction_service(result: ExtractionResult) -> MagicMock:
    """Build a mock ExtractionService whose .extract() coroutine returns result."""
    from app.services.extraction import ExtractionService
    mock_svc = MagicMock(spec=ExtractionService)
    mock_svc.extract = AsyncMock(return_value=result)
    return mock_svc


def _make_mock_invoice_service(
    find_dup_return=None,
    save_return=None,
    find_race_return=None,
) -> MagicMock:
    """Build a mock InvoiceService."""
    from app.services.invoice import InvoiceService
    mock_svc = MagicMock(spec=InvoiceService)
    mock_svc.find_duplicate = AsyncMock(return_value=find_dup_return)
    mock_svc.find_existing_for_race = AsyncMock(return_value=find_race_return)
    if save_return is not None:
        mock_svc.save_invoice = AsyncMock(return_value=save_return)
    else:
        import uuid as _uuid
        stub_inv = Invoice(
            id=_uuid.UUID("12345678-1234-5678-1234-567812345678"),
            status="auto_saved",
        )
        mock_svc.save_invoice = AsyncMock(return_value=stub_inv)
    return mock_svc


def _make_session_local_mock(db_session):
    """Return an async_sessionmaker-compatible mock that yields db_session.

    Used to patch app.routers.whatsapp.get_async_session_local so that the
    background task's DB operations run against the test db_session (not the
    singleton engine which points to a separate in-memory SQLite instance).
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _session_ctx():
        yield db_session

    # The real get_async_session_local() returns an async_sessionmaker (callable).
    # process_invoice calls: session_local = get_async_session_local(); async with session_local() as session:
    # So our mock needs to return a callable that returns an async context manager.
    def _session_factory():
        return _session_ctx()

    return _session_factory


@pytest_asyncio.fixture
async def process_invoice_client(db_session, monkeypatch):
    """ASGI client with mocked provider and DB override — shared base for process_invoice tests."""
    monkeypatch.setenv("AGENT_MODE", "invoice")
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
        yield client, mock_provider, app, db_session

    app.dependency_overrides.clear()
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Plan 02 process_invoice tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unsupported_media_type(process_invoice_client):
    """application/pdf MIME type → D-11 UNREADABLE_REPLY; ExtractionService never called."""
    client, mock_provider, app, db_session = process_invoice_client
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    from app.routers import whatsapp as wa_module

    mock_extraction_svc = _make_mock_extraction_service(_make_extraction_result())
    session_local_mock = _make_session_local_mock(db_session)

    with patch.object(wa_module, "ExtractionService", return_value=mock_extraction_svc):
        with patch.object(wa_module, "get_async_session_local", return_value=session_local_mock):
            response = await client.post(
                "/webhook",
                data=make_twilio_form(
                    From="whatsapp:+5491112345678",
                    MediaContentType0="application/pdf",
                ),
                headers={"X-Twilio-Signature": "valid-sig"},
            )
            await asyncio.sleep(0.15)

    assert response.status_code == 200

    # All sends: ack was NOT sent (pdf fails before ack? No — ack is sent before task. pdf fails in task)
    # Actually: ack IS sent (step 6 in webhook), then task sends UNREADABLE_REPLY
    calls = mock_provider.send_message.call_args_list
    texts = [c.kwargs.get("text", c.args[1] if len(c.args) > 1 else "") for c in calls]
    assert UNREADABLE_REPLY in texts
    mock_extraction_svc.extract.assert_not_awaited()

    # No Invoice row inserted
    count = (await db_session.execute(select(func.count()).select_from(Invoice))).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_invalid_magic_bytes(process_invoice_client):
    """MIME=image/jpeg but PDF magic bytes → D-11 reply; ExtractionService never called."""
    client, mock_provider, app, db_session = process_invoice_client
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    from app.routers import whatsapp as wa_module

    # Provider returns PDF bytes (not JPEG/PNG)
    pdf_bytes = b"%PDF-1.4 fake pdf content"
    mock_provider.download_media = AsyncMock(return_value=pdf_bytes)

    mock_extraction_svc = _make_mock_extraction_service(_make_extraction_result())
    session_local_mock = _make_session_local_mock(db_session)

    with patch.object(wa_module, "ExtractionService", return_value=mock_extraction_svc):
        with patch.object(wa_module, "get_async_session_local", return_value=session_local_mock):
            with structlog.testing.capture_logs() as log_entries:
                response = await client.post(
                    "/webhook",
                    data=make_twilio_form(From="whatsapp:+5491112345678"),
                    headers={"X-Twilio-Signature": "valid-sig"},
                )
                await asyncio.sleep(0.15)

    assert response.status_code == 200
    calls = mock_provider.send_message.call_args_list
    texts = [c.kwargs.get("text", c.args[1] if len(c.args) > 1 else "") for c in calls]
    assert UNREADABLE_REPLY in texts
    mock_extraction_svc.extract.assert_not_awaited()

    # whatsapp.invalid_image_bytes must be logged
    events = [e.get("event") for e in log_entries]
    assert "whatsapp.invalid_image_bytes" in events


@pytest.mark.asyncio
async def test_valid_jpeg_magic_bytes_passes(process_invoice_client):
    """Valid JPEG magic bytes → magic-byte gate passes; ExtractionService.extract IS called."""
    client, mock_provider, app, db_session = process_invoice_client
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    from app.routers import whatsapp as wa_module

    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    mock_provider.download_media = AsyncMock(return_value=jpeg_bytes)

    extraction_result = _make_extraction_result()
    mock_extraction_svc = _make_mock_extraction_service(extraction_result)
    mock_invoice_svc = _make_mock_invoice_service()
    session_local_mock = _make_session_local_mock(db_session)

    with patch.object(wa_module, "ExtractionService", return_value=mock_extraction_svc):
        with patch.object(wa_module, "InvoiceService", return_value=mock_invoice_svc):
            with patch.object(wa_module, "get_async_session_local", return_value=session_local_mock):
                response = await client.post(
                    "/webhook",
                    data=make_twilio_form(From="whatsapp:+5491112345678"),
                    headers={"X-Twilio-Signature": "valid-sig"},
                )
                await asyncio.sleep(0.15)

    assert response.status_code == 200
    mock_extraction_svc.extract.assert_awaited_once()


@pytest.mark.asyncio
async def test_valid_png_magic_bytes_passes(process_invoice_client):
    """Valid PNG magic bytes → magic-byte gate passes; ExtractionService.extract IS called."""
    client, mock_provider, app, db_session = process_invoice_client
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    from app.routers import whatsapp as wa_module

    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    mock_provider.download_media = AsyncMock(return_value=png_bytes)

    extraction_result = _make_extraction_result()
    mock_extraction_svc = _make_mock_extraction_service(extraction_result)
    mock_invoice_svc = _make_mock_invoice_service()
    session_local_mock = _make_session_local_mock(db_session)

    with patch.object(wa_module, "ExtractionService", return_value=mock_extraction_svc):
        with patch.object(wa_module, "InvoiceService", return_value=mock_invoice_svc):
            with patch.object(wa_module, "get_async_session_local", return_value=session_local_mock):
                response = await client.post(
                    "/webhook",
                    data=make_twilio_form(From="whatsapp:+5491112345678"),
                    headers={"X-Twilio-Signature": "valid-sig"},
                )
                await asyncio.sleep(0.15)

    assert response.status_code == 200
    mock_extraction_svc.extract.assert_awaited_once()


@pytest.mark.asyncio
async def test_auto_saved_reply(process_invoice_client):
    """auto_saved status → D-08 reply with all four fields and computed total."""
    client, mock_provider, app, db_session = process_invoice_client
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    from app.routers import whatsapp as wa_module

    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    mock_provider.download_media = AsyncMock(return_value=jpeg_bytes)

    # 2 bultos × $100 × 1.21 × 1.0 = $242.00
    result = ExtractionResult(
        invoice=ExtractedInvoice(
            tipo_comprobante=TipoComprobante.FACTURA_A,
            numero_documento="0001-00001",
            proveedor="Acme SA",
            fecha="2026-05-10",
            line_items=[
                LineItem(
                    bultos=Decimal("2"),
                    precio_unitario_sin_iva=Decimal("100"),
                    iva_rate=Decimal("0.21"),
                    descuento_pct=Decimal("0"),
                )
            ],
        ),
        confidence_score=0.9,
        status="auto_saved",
        image_path="/tmp/invoices/SM.jpg",
    )

    mock_extraction_svc = _make_mock_extraction_service(result)
    import uuid as _uuid
    stub_saved = Invoice(
        id=_uuid.UUID("12345678-1234-5678-1234-567812345678"),
        status="auto_saved",
    )
    mock_invoice_svc = _make_mock_invoice_service(save_return=stub_saved)
    session_local_mock = _make_session_local_mock(db_session)

    with patch.object(wa_module, "ExtractionService", return_value=mock_extraction_svc):
        with patch.object(wa_module, "InvoiceService", return_value=mock_invoice_svc):
            with patch.object(wa_module, "get_async_session_local", return_value=session_local_mock):
                response = await client.post(
                    "/webhook",
                    data=make_twilio_form(From="whatsapp:+5491112345678"),
                    headers={"X-Twilio-Signature": "valid-sig"},
                )
                await asyncio.sleep(0.15)

    assert response.status_code == 200
    # Find the summary reply (second send_message call — first is the ack)
    calls = mock_provider.send_message.call_args_list
    assert len(calls) >= 2
    summary_text = calls[-1].kwargs.get("text", "")

    assert "Acme SA" in summary_text
    assert "0001-00001" in summary_text
    assert "2026-05-10" in summary_text
    assert "242.00" in summary_text
    assert "✅" in summary_text


@pytest.mark.asyncio
async def test_pending_review_reply(process_invoice_client):
    """pending_review status → D-09 reply with warning header."""
    client, mock_provider, app, db_session = process_invoice_client
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    from app.routers import whatsapp as wa_module

    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    mock_provider.download_media = AsyncMock(return_value=jpeg_bytes)

    result = _make_extraction_result(status="pending_review", confidence=0.5)
    mock_extraction_svc = _make_mock_extraction_service(result)
    mock_invoice_svc = _make_mock_invoice_service()
    session_local_mock = _make_session_local_mock(db_session)

    with patch.object(wa_module, "ExtractionService", return_value=mock_extraction_svc):
        with patch.object(wa_module, "InvoiceService", return_value=mock_invoice_svc):
            with patch.object(wa_module, "get_async_session_local", return_value=session_local_mock):
                response = await client.post(
                    "/webhook",
                    data=make_twilio_form(From="whatsapp:+5491112345678"),
                    headers={"X-Twilio-Signature": "valid-sig"},
                )
                await asyncio.sleep(0.15)

    assert response.status_code == 200
    calls = mock_provider.send_message.call_args_list
    assert len(calls) >= 2
    summary_text = calls[-1].kwargs.get("text", "")
    assert "⚠️" in summary_text


@pytest.mark.asyncio
async def test_summary_format(process_invoice_client):
    """Reply contains exactly the four field labels."""
    client, mock_provider, app, db_session = process_invoice_client
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    from app.routers import whatsapp as wa_module

    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    mock_provider.download_media = AsyncMock(return_value=jpeg_bytes)

    result = _make_extraction_result()
    mock_extraction_svc = _make_mock_extraction_service(result)
    mock_invoice_svc = _make_mock_invoice_service()
    session_local_mock = _make_session_local_mock(db_session)

    with patch.object(wa_module, "ExtractionService", return_value=mock_extraction_svc):
        with patch.object(wa_module, "InvoiceService", return_value=mock_invoice_svc):
            with patch.object(wa_module, "get_async_session_local", return_value=session_local_mock):
                response = await client.post(
                    "/webhook",
                    data=make_twilio_form(From="whatsapp:+5491112345678"),
                    headers={"X-Twilio-Signature": "valid-sig"},
                )
                await asyncio.sleep(0.15)

    calls = mock_provider.send_message.call_args_list
    summary_text = calls[-1].kwargs.get("text", "")
    assert summary_text.count("Proveedor:") == 1
    assert summary_text.count("Número:") == 1
    assert summary_text.count("Fecha:") == 1
    assert summary_text.count("Total:") == 1


@pytest.mark.asyncio
async def test_summary_omits_missing_fields(process_invoice_client):
    """When a field is None, the summary line shows em-dash instead of 'None'."""
    client, mock_provider, app, db_session = process_invoice_client
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    from app.routers import whatsapp as wa_module

    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    mock_provider.download_media = AsyncMock(return_value=jpeg_bytes)

    # Invoice with proveedor=None
    result = ExtractionResult(
        invoice=ExtractedInvoice(
            tipo_comprobante=TipoComprobante.FACTURA_A,
            numero_documento="0001-00001",
            proveedor=None,
            fecha=None,
            line_items=[],
        ),
        confidence_score=0.5,
        status="pending_review",
        image_path="/tmp/invoices/SM.jpg",
    )

    mock_extraction_svc = _make_mock_extraction_service(result)
    mock_invoice_svc = _make_mock_invoice_service()
    session_local_mock = _make_session_local_mock(db_session)

    with patch.object(wa_module, "ExtractionService", return_value=mock_extraction_svc):
        with patch.object(wa_module, "InvoiceService", return_value=mock_invoice_svc):
            with patch.object(wa_module, "get_async_session_local", return_value=session_local_mock):
                response = await client.post(
                    "/webhook",
                    data=make_twilio_form(From="whatsapp:+5491112345678"),
                    headers={"X-Twilio-Signature": "valid-sig"},
                )
                await asyncio.sleep(0.15)

    calls = mock_provider.send_message.call_args_list
    summary_text = calls[-1].kwargs.get("text", "")
    # Should show em-dash for None fields, NOT "None"
    assert "None" not in summary_text
    assert "—" in summary_text


@pytest.mark.asyncio
async def test_duplicate_app_level(process_invoice_client):
    """Pre-seeded duplicate: D-12 reply sent; no second Invoice row inserted."""
    client, mock_provider, app, db_session = process_invoice_client
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    # Seed the existing invoice
    existing = Invoice(
        numero_documento="0001-00001",
        proveedor="Acme SA",
        fecha=date(2026, 5, 10),
        status="auto_saved",
        whatsapp_message_id="SM-original-001",
        sender_phone="+5491112345678",
    )
    db_session.add(existing)
    await db_session.commit()

    from app.routers import whatsapp as wa_module

    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    mock_provider.download_media = AsyncMock(return_value=jpeg_bytes)

    result = _make_extraction_result()
    mock_extraction_svc = _make_mock_extraction_service(result)

    # InvoiceService.find_duplicate returns the seeded invoice
    mock_invoice_svc = _make_mock_invoice_service(find_dup_return=existing)
    session_local_mock = _make_session_local_mock(db_session)

    with patch.object(wa_module, "ExtractionService", return_value=mock_extraction_svc):
        with patch.object(wa_module, "InvoiceService", return_value=mock_invoice_svc):
            with patch.object(wa_module, "get_async_session_local", return_value=session_local_mock):
                response = await client.post(
                    "/webhook",
                    data=make_twilio_form(From="whatsapp:+5491112345678"),
                    headers={"X-Twilio-Signature": "valid-sig"},
                )
                await asyncio.sleep(0.15)

    assert response.status_code == 200
    # D-12 reply must contain the original fecha
    calls = mock_provider.send_message.call_args_list
    texts = [c.kwargs.get("text", "") for c in calls]
    assert any("2026-05-10" in t for t in texts)
    # No second Invoice row
    count = (await db_session.execute(select(func.count()).select_from(Invoice))).scalar_one()
    assert count == 1  # only the seeded one


@pytest.mark.asyncio
async def test_duplicate_race_integrity_error(process_invoice_client):
    """Race condition: save_invoice raises IntegrityError; find_existing_for_race called; real fecha in reply."""
    client, mock_provider, app, db_session = process_invoice_client
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    existing = Invoice(
        numero_documento="0001-00001",
        proveedor="Acme SA",
        fecha=date(2026, 5, 10),
        status="auto_saved",
        whatsapp_message_id="SM-original-001",
        sender_phone="+5491112345678",
    )
    db_session.add(existing)
    await db_session.commit()

    from app.routers import whatsapp as wa_module

    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    mock_provider.download_media = AsyncMock(return_value=jpeg_bytes)

    result = _make_extraction_result()
    mock_extraction_svc = _make_mock_extraction_service(result)

    # save_invoice raises IntegrityError; find_existing_for_race returns the seeded row
    mock_invoice_svc = MagicMock()
    mock_invoice_svc.find_duplicate = AsyncMock(return_value=None)
    mock_invoice_svc.save_invoice = AsyncMock(side_effect=IntegrityError("UNIQUE", None, None))
    mock_invoice_svc.find_existing_for_race = AsyncMock(return_value=existing)
    session_local_mock = _make_session_local_mock(db_session)

    with patch.object(wa_module, "ExtractionService", return_value=mock_extraction_svc):
        with patch.object(wa_module, "InvoiceService", return_value=mock_invoice_svc):
            with patch.object(wa_module, "get_async_session_local", return_value=session_local_mock):
                response = await client.post(
                    "/webhook",
                    data=make_twilio_form(From="whatsapp:+5491112345678"),
                    headers={"X-Twilio-Signature": "valid-sig"},
                )
                await asyncio.sleep(0.15)

    assert response.status_code == 200
    calls = mock_provider.send_message.call_args_list
    texts = [c.kwargs.get("text", "") for c in calls]
    # Must show real fecha "2026-05-10", NOT em-dash
    assert any("2026-05-10" in t for t in texts)
    assert not any("🔁" in t and "—" in t for t in texts)
    # find_existing_for_race was called
    mock_invoice_svc.find_existing_for_race.assert_awaited_once()


@pytest.mark.asyncio
async def test_duplicate_race_integrity_error_no_existing_row(process_invoice_client):
    """Edge case: IntegrityError fires but re-query finds nothing → em-dash fallback."""
    client, mock_provider, app, db_session = process_invoice_client
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    from app.routers import whatsapp as wa_module

    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    mock_provider.download_media = AsyncMock(return_value=jpeg_bytes)

    result = _make_extraction_result()
    mock_extraction_svc = _make_mock_extraction_service(result)

    mock_invoice_svc = MagicMock()
    mock_invoice_svc.find_duplicate = AsyncMock(return_value=None)
    mock_invoice_svc.save_invoice = AsyncMock(side_effect=IntegrityError("UNIQUE", None, None))
    mock_invoice_svc.find_existing_for_race = AsyncMock(return_value=None)
    session_local_mock = _make_session_local_mock(db_session)

    with patch.object(wa_module, "ExtractionService", return_value=mock_extraction_svc):
        with patch.object(wa_module, "InvoiceService", return_value=mock_invoice_svc):
            with patch.object(wa_module, "get_async_session_local", return_value=session_local_mock):
                with structlog.testing.capture_logs() as log_entries:
                    response = await client.post(
                        "/webhook",
                        data=make_twilio_form(From="whatsapp:+5491112345678"),
                        headers={"X-Twilio-Signature": "valid-sig"},
                    )
                    await asyncio.sleep(0.15)

    assert response.status_code == 200
    calls = mock_provider.send_message.call_args_list
    texts = [c.kwargs.get("text", "") for c in calls]
    # D-12 with em-dash fallback
    assert any("🔁" in t and "—" in t for t in texts)
    # whatsapp.race_no_existing_row must be logged
    events = [e.get("event") for e in log_entries]
    assert "whatsapp.race_no_existing_row" in events


@pytest.mark.asyncio
async def test_extraction_refusal_sends_error(process_invoice_client):
    """ExtractionRefusalError → D-11 UNREADABLE_REPLY; no Invoice inserted."""
    client, mock_provider, app, db_session = process_invoice_client
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    from app.routers import whatsapp as wa_module
    from app.services.extraction import ExtractionRefusalError, ExtractionService

    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    mock_provider.download_media = AsyncMock(return_value=jpeg_bytes)

    mock_extraction_svc = MagicMock(spec=ExtractionService)
    mock_extraction_svc.extract = AsyncMock(side_effect=ExtractionRefusalError("refused"))
    session_local_mock = _make_session_local_mock(db_session)

    with patch.object(wa_module, "ExtractionService", return_value=mock_extraction_svc):
        with patch.object(wa_module, "get_async_session_local", return_value=session_local_mock):
            response = await client.post(
                "/webhook",
                data=make_twilio_form(From="whatsapp:+5491112345678"),
                headers={"X-Twilio-Signature": "valid-sig"},
            )
            await asyncio.sleep(0.15)

    assert response.status_code == 200
    calls = mock_provider.send_message.call_args_list
    texts = [c.kwargs.get("text", "") for c in calls]
    assert UNREADABLE_REPLY in texts
    count = (await db_session.execute(select(func.count()).select_from(Invoice))).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_extraction_failed_sends_error(process_invoice_client):
    """ExtractionFailedError → D-11 UNREADABLE_REPLY; no Invoice inserted."""
    client, mock_provider, app, db_session = process_invoice_client
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    from app.routers import whatsapp as wa_module
    from app.services.extraction import ExtractionFailedError, ExtractionService

    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    mock_provider.download_media = AsyncMock(return_value=jpeg_bytes)

    mock_extraction_svc = MagicMock(spec=ExtractionService)
    mock_extraction_svc.extract = AsyncMock(side_effect=ExtractionFailedError("failed"))
    session_local_mock = _make_session_local_mock(db_session)

    with patch.object(wa_module, "ExtractionService", return_value=mock_extraction_svc):
        with patch.object(wa_module, "get_async_session_local", return_value=session_local_mock):
            response = await client.post(
                "/webhook",
                data=make_twilio_form(From="whatsapp:+5491112345678"),
                headers={"X-Twilio-Signature": "valid-sig"},
            )
            await asyncio.sleep(0.15)

    assert response.status_code == 200
    calls = mock_provider.send_message.call_args_list
    texts = [c.kwargs.get("text", "") for c in calls]
    assert UNREADABLE_REPLY in texts
    count = (await db_session.execute(select(func.count()).select_from(Invoice))).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_send_message_failure_after_save(process_invoice_client):
    """Reply-send failure after save: invoice persisted; task does NOT crash; reply_failed logged."""
    client, mock_provider, app, db_session = process_invoice_client
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    from app.routers import whatsapp as wa_module

    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    mock_provider.download_media = AsyncMock(return_value=jpeg_bytes)

    # First send (ack) returns None; second send (summary after save) raises
    mock_provider.send_message = AsyncMock(
        side_effect=[None, httpx.HTTPError("twilio-down")]
    )

    result = _make_extraction_result()
    mock_extraction_svc = _make_mock_extraction_service(result)

    import uuid as _uuid
    stub_saved = Invoice(
        id=_uuid.UUID("12345678-1234-5678-1234-567812345678"),
        status="auto_saved",
    )
    mock_invoice_svc = _make_mock_invoice_service(save_return=stub_saved)
    session_local_mock = _make_session_local_mock(db_session)

    with patch.object(wa_module, "ExtractionService", return_value=mock_extraction_svc):
        with patch.object(wa_module, "InvoiceService", return_value=mock_invoice_svc):
            with patch.object(wa_module, "get_async_session_local", return_value=session_local_mock):
                with structlog.testing.capture_logs() as log_entries:
                    response = await client.post(
                        "/webhook",
                        data=make_twilio_form(From="whatsapp:+5491112345678"),
                        headers={"X-Twilio-Signature": "valid-sig"},
                    )
                    await asyncio.sleep(0.15)

    # (a) Invoice WAS persisted (save_invoice was called)
    mock_invoice_svc.save_invoice.assert_awaited_once()
    # (b) No exception propagated — background tasks are empty after completion
    assert len(_background_tasks) == 0
    # (c) whatsapp.reply_failed logged with invoice_id and error keys
    reply_failed_events = [e for e in log_entries if e.get("event") == "whatsapp.reply_failed"]
    assert len(reply_failed_events) >= 1
    event = reply_failed_events[-1]
    assert "invoice_id" in event
    assert "error" in event
    assert "twilio-down" in str(event.get("error", ""))


@pytest.mark.asyncio
async def test_background_task_cleared_after_completion(process_invoice_client):
    """After process_invoice completes, _background_tasks set is empty."""
    client, mock_provider, app, db_session = process_invoice_client
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    from app.routers import whatsapp as wa_module

    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    mock_provider.download_media = AsyncMock(return_value=jpeg_bytes)

    result = _make_extraction_result()
    mock_extraction_svc = _make_mock_extraction_service(result)
    mock_invoice_svc = _make_mock_invoice_service()
    session_local_mock = _make_session_local_mock(db_session)

    with patch.object(wa_module, "ExtractionService", return_value=mock_extraction_svc):
        with patch.object(wa_module, "InvoiceService", return_value=mock_invoice_svc):
            with patch.object(wa_module, "get_async_session_local", return_value=session_local_mock):
                response = await client.post(
                    "/webhook",
                    data=make_twilio_form(From="whatsapp:+5491112345678"),
                    headers={"X-Twilio-Signature": "valid-sig"},
                )
                await asyncio.sleep(0.2)

    assert response.status_code == 200
    assert len(_background_tasks) == 0


@pytest.mark.asyncio
async def test_multi_media_processes_only_url0(process_invoice_client):
    """NumMedia=2: only MediaUrl0 is downloaded; whatsapp.multi_media_ignored logged."""
    client, mock_provider, app, db_session = process_invoice_client
    db_session.add(SenderAllowlist(phone_number="+5491112345678"))
    await db_session.commit()

    from app.routers import whatsapp as wa_module

    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    mock_provider.download_media = AsyncMock(return_value=jpeg_bytes)

    result = _make_extraction_result()
    mock_extraction_svc = _make_mock_extraction_service(result)
    mock_invoice_svc = _make_mock_invoice_service()
    session_local_mock = _make_session_local_mock(db_session)

    with patch.object(wa_module, "ExtractionService", return_value=mock_extraction_svc):
        with patch.object(wa_module, "InvoiceService", return_value=mock_invoice_svc):
            with patch.object(wa_module, "get_async_session_local", return_value=session_local_mock):
                with structlog.testing.capture_logs() as log_entries:
                    form = make_twilio_form(From="whatsapp:+5491112345678", NumMedia="2")
                    form["MediaUrl1"] = "https://api.twilio.com/media/test2"
                    response = await client.post(
                        "/webhook",
                        data=form,
                        headers={"X-Twilio-Signature": "valid-sig"},
                    )
                    await asyncio.sleep(0.15)

    assert response.status_code == 200
    # Only one download call (MediaUrl0 only)
    assert mock_provider.download_media.await_count == 1
    # whatsapp.multi_media_ignored must be logged
    events = [e.get("event") for e in log_entries]
    assert "whatsapp.multi_media_ignored" in events
