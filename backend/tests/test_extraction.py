"""Tests for ExtractionService, ExtractionResult, confidence/status helpers,
and the debug-gated POST /extraction/test endpoint.

Strategy:
- Unit tests exercise compute_confidence, assign_status, and service internals
  using a mocked AsyncOpenAI client (never makes live OpenAI calls).
- ASGI tests use app.dependency_overrides[get_extraction_service] to inject a
  pre-built mock service (mirrors override_get_db pattern in test_health.py).
- Two ASGI fixtures: debug_client (DEBUG=true, router registered) and
  nodebug_client (DEBUG=false, router absent → 404).

Run: cd backend && python -m pytest tests/test_extraction.py -x -q -m 'not integration'
"""
import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
import structlog
import structlog.testing
from openai.types.chat.parsed_chat_completion import (
    ParsedChatCompletion,
    ParsedChatCompletionMessage,
    ParsedChoice,
)

from app.config import get_settings
from app.models.extraction import ExtractedInvoice, LineItem, TipoComprobante
from app.routers.extraction import get_extraction_service  # RED: ImportError until Task 3
from app.services.extraction import (  # RED: ImportError until Task 2
    ExtractionFailedError,
    ExtractionRefusalError,
    ExtractionResult,
    ExtractionService,
    assign_status,
    compute_confidence,
)
from app.services.storage import StorageBackend  # RED: ImportError until Task 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_mock_completion(
    parsed_invoice: Optional[ExtractedInvoice],
    refusal: Optional[str] = None,
) -> MagicMock:
    """Verbatim Pattern 5 from 02-PATTERNS.md — verified against openai==2.36.0."""
    mock_message = MagicMock(spec=ParsedChatCompletionMessage)
    mock_message.parsed = parsed_invoice
    mock_message.refusal = refusal

    mock_choice = MagicMock(spec=ParsedChoice)
    mock_choice.message = mock_message

    mock_completion = MagicMock(spec=ParsedChatCompletion)
    mock_completion.choices = [mock_choice]
    return mock_completion


def _stub_invoice() -> ExtractedInvoice:
    return ExtractedInvoice(
        tipo_comprobante=TipoComprobante.FACTURA_A,
        numero_documento="0001-00000001",
        proveedor="Test SA",
        fecha="2026-01-01",
    )


def make_mock_service(
    parsed_invoice: Optional[ExtractedInvoice] = None,
    refusal: Optional[str] = None,
    storage_save_return: str = "fake-uuid/photo.jpg",
) -> ExtractionService:
    """Build a real ExtractionService with mocked openai_client and storage."""
    if parsed_invoice is None and refusal is None:
        parsed_invoice = _stub_invoice()

    mock_openai = MagicMock()
    mock_openai.chat.completions.parse = AsyncMock(
        return_value=make_mock_completion(parsed_invoice, refusal)
    )

    mock_storage = MagicMock(spec=StorageBackend)
    mock_storage.save.return_value = storage_save_return

    settings = get_settings()
    return ExtractionService(
        openai_client=mock_openai,
        storage=mock_storage,
        settings=settings,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def extraction_service():
    """A real ExtractionService with mocked deps and a default stub invoice."""
    yield make_mock_service()


@pytest_asyncio.fixture
async def debug_client(monkeypatch):
    """ASGI client with DEBUG=true — extraction router registered.

    Uses app.dependency_overrides[get_extraction_service] to inject a mocked
    service so NO live OpenAI call is made. Mirrors override_get_db in test_health.py.
    """
    monkeypatch.setenv("DEBUG", "true")
    # MANDATORY: clear cached Settings from any prior fixture (review issue #4)
    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    mocked_service = make_mock_service(parsed_invoice=_stub_invoice())
    app.dependency_overrides[get_extraction_service] = lambda: mocked_service

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c

    app.dependency_overrides.clear()
    get_settings.cache_clear()  # restore clean state


@pytest_asyncio.fixture
async def nodebug_client(monkeypatch):
    """ASGI client with DEBUG=false — extraction router NOT registered.

    Calls get_settings.cache_clear() BEFORE create_app() to prevent inheriting
    a cached debug=True Settings from a prior debug_client invocation (review issue #4).
    """
    monkeypatch.setenv("DEBUG", "false")
    # MANDATORY: clear cache BEFORE constructing app
    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c

    get_settings.cache_clear()  # restore clean state


# ---------------------------------------------------------------------------
# compute_confidence tests
# ---------------------------------------------------------------------------


def test_compute_confidence_all_four_critical_fields_present():
    """All four critical fields non-null → confidence 1.0 (D-01)."""
    invoice = ExtractedInvoice(
        tipo_comprobante=TipoComprobante.FACTURA_A,
        numero_documento="X",
        proveedor="Y",
        fecha="2026-01-01",
    )
    assert compute_confidence(invoice) == 1.0


def test_compute_confidence_two_of_four_present():
    """Two of four critical fields (proveedor + fecha) non-null → 0.5."""
    invoice = ExtractedInvoice(proveedor="Y", fecha="2026-01-01")
    assert compute_confidence(invoice) == 0.5


def test_compute_confidence_all_none():
    """All critical fields None → 0.0."""
    invoice = ExtractedInvoice()
    assert compute_confidence(invoice) == 0.0


# ---------------------------------------------------------------------------
# assign_status tests
# ---------------------------------------------------------------------------


def test_assign_status_auto_saved_at_threshold():
    """score == threshold → 'auto_saved' (D-03 boundary)."""
    assert assign_status(0.85, 0.85) == "auto_saved"


def test_assign_status_pending_review_below_threshold():
    """score < threshold → 'pending_review' (D-03)."""
    assert assign_status(0.5, 0.85) == "pending_review"


def test_status_pending_review_just_below_threshold():
    """score just below threshold (0.84) → 'pending_review' (EXT-07 boundary)."""
    assert assign_status(0.84, 0.85) == "pending_review"


# ---------------------------------------------------------------------------
# ExtractionService.extract() unit tests (Plan 01)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_calls_storage_with_uuid_and_basename(extraction_service):
    """extract() calls storage.save with '<uuid>/photo.jpg' pattern (D-09)."""
    await extraction_service.extract(b"img", "photo.jpg")

    call_args = extraction_service._storage.save.call_args
    assert call_args is not None
    _data, filename_arg = call_args[0]
    assert re.match(r"^[0-9a-f-]{36}/photo\.jpg$", filename_arg), (
        f"Expected UUID-prefixed filename, got: {filename_arg!r}"
    )


@pytest.mark.asyncio
async def test_extract_returns_extraction_result_with_image_path(extraction_service):
    """image_path on result equals the mocked storage.save return value."""
    extraction_service._storage.save.return_value = "my-uuid/invoice.jpg"
    result = await extraction_service.extract(b"img", "invoice.jpg")

    assert isinstance(result, ExtractionResult)
    assert result.image_path == "my-uuid/invoice.jpg"


@pytest.mark.asyncio
async def test_extract_raises_refusal_error_when_message_refusal_set():
    """When msg.refusal is set and msg.parsed is None → ExtractionRefusalError raised."""
    service = make_mock_service(parsed_invoice=None, refusal="I cannot process this image")
    with pytest.raises(ExtractionRefusalError):
        await service.extract(b"img", "photo.jpg")


@pytest.mark.asyncio
async def test_extract_raises_extraction_failed_when_parsed_is_none_and_no_refusal():
    """When msg.parsed is None and msg.refusal is None → ExtractionFailedError raised."""
    mock_openai = MagicMock()
    mock_openai.chat.completions.parse = AsyncMock(
        return_value=make_mock_completion(parsed_invoice=None, refusal=None)
    )
    mock_storage = MagicMock(spec=StorageBackend)
    mock_storage.save.return_value = "uuid/photo.jpg"
    settings = get_settings()
    service = ExtractionService(
        openai_client=mock_openai,
        storage=mock_storage,
        settings=settings,
    )
    with pytest.raises(ExtractionFailedError):
        await service.extract(b"img", "photo.jpg")


@pytest.mark.asyncio
async def test_extract_logs_error_with_filename_on_failure():
    """On failure, structlog emits 'extraction.failed' with filename binding (VAL-05)."""
    service = make_mock_service(parsed_invoice=None, refusal="Model refused")

    with structlog.testing.capture_logs() as cap_logs:
        with pytest.raises(ExtractionRefusalError):
            await service.extract(b"img", "photo.jpg")

    failed_events = [e for e in cap_logs if e.get("event") == "extraction.failed"]
    assert len(failed_events) >= 1, f"No 'extraction.failed' log event found. Logs: {cap_logs}"
    assert any(
        e.get("filename") == "photo.jpg" for e in failed_events
    ), f"filename='photo.jpg' not bound in any failed event. Events: {failed_events}"


# ---------------------------------------------------------------------------
# EXT-01 + EXT-02: Line item extraction with full field set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_line_items_extracted_with_full_field_set():
    """Mock parse() returns invoice with two LineItems; all fields preserved verbatim (EXT-01, EXT-02)."""
    item_full = LineItem(
        descripcion="Tornillos 5mm",
        codigo_sku="SKU-001",
        bultos=Decimal("2"),
        unidades_por_bulto=Decimal("10"),
        precio_unitario_sin_iva=Decimal("150.00"),
        descuento_pct=Decimal("0.05"),
        iva_rate=Decimal("0.21"),
        percepciones_iibb=Decimal("3.00"),
    )
    item_partial = LineItem(
        descripcion="Tuercas M8",
        iva_rate=Decimal("0.105"),
        # all other fields are None
    )
    invoice = ExtractedInvoice(
        tipo_comprobante=TipoComprobante.FACTURA_A,
        numero_documento="0001-00000001",
        proveedor="Ferretería SA",
        fecha="2026-01-15",
        line_items=[item_full, item_partial],
    )
    service = make_mock_service(parsed_invoice=invoice)
    result = await service.extract(b"img", "factura.jpg")

    assert len(result.invoice.line_items) == 2

    li0 = result.invoice.line_items[0]
    assert li0.descripcion == "Tornillos 5mm"
    assert li0.codigo_sku == "SKU-001"
    assert li0.bultos == Decimal("2")
    assert li0.unidades_por_bulto == Decimal("10")
    assert li0.precio_unitario_sin_iva == Decimal("150.00")
    assert li0.descuento_pct == Decimal("0.05")
    assert li0.iva_rate == Decimal("0.21")
    assert li0.percepciones_iibb == Decimal("3.00")

    li1 = result.invoice.line_items[1]
    assert li1.descripcion == "Tuercas M8"
    assert li1.iva_rate == Decimal("0.105")
    assert li1.codigo_sku is None
    assert li1.bultos is None
    assert li1.unidades_por_bulto is None
    assert li1.precio_unitario_sin_iva is None
    assert li1.descuento_pct is None
    assert li1.percepciones_iibb is None


# ---------------------------------------------------------------------------
# EXT-03: Document-level fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_level_fields_extracted():
    """Mock invoice with all four document-level fields; all propagate to result (EXT-03)."""
    invoice = ExtractedInvoice(
        tipo_comprobante=TipoComprobante.FACTURA_A,
        numero_documento="0001-00000123",
        proveedor="Acme SA",
        fecha="2026-01-15",
    )
    service = make_mock_service(parsed_invoice=invoice)
    result = await service.extract(b"img", "factura.jpg")

    assert result.invoice.tipo_comprobante == "FACTURA_A"
    assert result.invoice.numero_documento == "0001-00000123"
    assert result.invoice.proveedor == "Acme SA"
    assert result.invoice.fecha == "2026-01-15"


# ---------------------------------------------------------------------------
# EXT-04: CUIT and CAE nullable fields remain None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cuit_and_cae_nullable_remain_none():
    """Mock invoice with cuit_proveedor=None, cae=None — no hallucination (EXT-04)."""
    invoice = ExtractedInvoice(
        tipo_comprobante=TipoComprobante.FACTURA_B,
        proveedor="Test SA",
        cuit_proveedor=None,
        cae=None,
        fecha_vencimiento_cae=None,
    )
    service = make_mock_service(parsed_invoice=invoice)
    result = await service.extract(b"img", "factura.jpg")

    assert result.invoice.cuit_proveedor is None
    assert result.invoice.cae is None
    assert result.invoice.fecha_vencimiento_cae is None


# ---------------------------------------------------------------------------
# EXT-05: Remito, Lista informal, UNKNOWN — extraction does not crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remito_extraction_does_not_crash():
    """REMITO tipo_comprobante extracts without raising; confidence reflects sparse fields (EXT-05)."""
    invoice = ExtractedInvoice(
        tipo_comprobante=TipoComprobante.REMITO,
        proveedor="Distribuidora Norte",
        # numero_documento and fecha are None — confidence will be 0.5
    )
    service = make_mock_service(parsed_invoice=invoice)
    result = await service.extract(b"img", "remito.jpg")

    assert isinstance(result, ExtractionResult)
    assert result.invoice.tipo_comprobante == "REMITO"
    # tipo + proveedor present (2/4) → 0.5
    assert result.confidence_score == 0.5


@pytest.mark.asyncio
async def test_lista_informal_extraction_does_not_crash():
    """LISTA_INFORMAL tipo_comprobante extracts without raising; confidence reflects sparse fields (EXT-05)."""
    invoice = ExtractedInvoice(
        tipo_comprobante=TipoComprobante.LISTA_INFORMAL,
        proveedor="Proveedor X",
        # numero_documento and fecha are None — confidence will be 0.5
    )
    service = make_mock_service(parsed_invoice=invoice)
    result = await service.extract(b"img", "lista.jpg")

    assert isinstance(result, ExtractionResult)
    assert result.invoice.tipo_comprobante == "LISTA_INFORMAL"
    assert result.confidence_score == 0.5


@pytest.mark.asyncio
async def test_unknown_tipo_does_not_crash():
    """UNKNOWN tipo_comprobante extracts without raising (EXT-05)."""
    invoice = ExtractedInvoice(
        tipo_comprobante=TipoComprobante.UNKNOWN,
    )
    service = make_mock_service(parsed_invoice=invoice)
    result = await service.extract(b"img", "unknown.jpg")

    assert isinstance(result, ExtractionResult)
    assert result.invoice.tipo_comprobante == "UNKNOWN"


# ---------------------------------------------------------------------------
# EXT-06: Null field handling — no fabrication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extraction_returns_null_field_when_gpt_returns_null_field():
    """numero_documento=None in mocked invoice → result.invoice.numero_documento is None (EXT-06)."""
    invoice = ExtractedInvoice(
        tipo_comprobante=TipoComprobante.FACTURA_C,
        proveedor="Test SA",
        numero_documento=None,  # explicitly absent
        fecha="2026-02-01",
    )
    service = make_mock_service(parsed_invoice=invoice)
    result = await service.extract(b"img", "factura.jpg")

    assert result.invoice.numero_documento is None


# ---------------------------------------------------------------------------
# VAL-04: storage.save called exactly once and image_path matches return value
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_storage_save_called_with_uuid_and_basename_returns_image_path():
    """storage.save called exactly once; ExtractionResult.image_path equals save return value (VAL-04)."""
    expected_path = "abc-uuid/invoice.jpg"
    service = make_mock_service(
        parsed_invoice=_stub_invoice(),
        storage_save_return=expected_path,
    )
    result = await service.extract(b"img", "invoice.jpg")

    service._storage.save.assert_called_once()
    assert result.image_path == expected_path


# ---------------------------------------------------------------------------
# VAL-05: Log payload does not contain secrets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_payload_does_not_contain_secrets():
    """structlog captured logs contain no secret values from conftest env (VAL-05, T-02-02)."""
    # These are the values set by conftest.py / test env — must never appear in logs
    secret_values = [
        "test-openai-key",
        "test-whatsapp-token",
        "test-verify-token",
        "test-phone-number-id",
    ]

    service = make_mock_service(parsed_invoice=_stub_invoice())

    with structlog.testing.capture_logs() as cap_logs:
        await service.extract(b"img", "invoice.jpg")

    all_log_text = str(cap_logs)
    for secret in secret_values:
        assert secret not in all_log_text, (
            f"Secret value '{secret}' found in log output: {cap_logs}"
        )


# ---------------------------------------------------------------------------
# ASGI endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_extraction_test_returns_extraction_result_when_debug_true(debug_client):
    """POST /extraction/test with multipart file → 200 JSON with expected keys.

    Uses app.dependency_overrides[get_extraction_service] — no live OpenAI call.
    """
    response = await debug_client.post(
        "/extraction/test",
        files={"file": ("invoice.jpg", b"fake-image-bytes", "image/jpeg")},
    )
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    body = response.json()
    assert set(body.keys()) == {"invoice", "confidence_score", "status", "image_path"}, (
        f"Unexpected keys: {set(body.keys())}"
    )


@pytest.mark.asyncio
async def test_post_extraction_test_404_when_debug_false(nodebug_client):
    """With DEBUG=false the extraction router is not registered → 404.

    nodebug_client fixture calls get_settings.cache_clear() BEFORE create_app()
    so the app does not inherit a cached debug=True Settings from a prior fixture.
    """
    response = await nodebug_client.post(
        "/extraction/test",
        files={"file": ("invoice.jpg", b"fake-image-bytes", "image/jpeg")},
    )
    assert response.status_code == 404, (
        f"Expected 404 (router absent), got {response.status_code}: {response.text}"
    )


# ---------------------------------------------------------------------------
# Integration test — @pytest.mark.integration (skipped by default)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_extraction_factura_a(tmp_path):
    """Live GPT-4o extraction on a real fixture image (EXT-01..EXT-07, VAL-04).

    Skipped unless:
    - OPENAI_API_KEY is set in the environment
    - backend/tests/fixtures/factura_a.jpg exists (committed in Plan 03)

    Run explicitly with: pytest -m integration
    """
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set — live integration test skipped")

    fixture_path = Path(__file__).parent / "fixtures" / "factura_a.jpg"
    if not fixture_path.exists():
        pytest.skip(f"Fixture image missing: {fixture_path} — will be committed in Plan 03")

    from openai import AsyncOpenAI
    from app.services.storage import LocalStorageBackend
    from app.services.extraction import ExtractionService, ExtractionResult

    settings = get_settings()
    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    storage = LocalStorageBackend(root=str(tmp_path))

    # Patch storage_path so LocalStorageBackend resolves to tmp_path
    import unittest.mock
    with unittest.mock.patch.object(settings, "storage_path", str(tmp_path)):
        service = ExtractionService(
            openai_client=client,
            storage=storage,
            settings=settings,
        )
        image_bytes = fixture_path.read_bytes()
        result = await service.extract(image_bytes, "factura_a.jpg")

    assert isinstance(result, ExtractionResult)
    assert isinstance(result.invoice, ExtractedInvoice)
    assert result.invoice.tipo_comprobante in {
        "FACTURA_A", "FACTURA_B", "FACTURA_C", "REMITO", "LISTA_INFORMAL", "UNKNOWN", None
    }
    assert 0.0 <= result.confidence_score <= 1.0
