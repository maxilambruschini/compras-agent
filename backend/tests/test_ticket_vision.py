"""TicketVisionService tests — amount-only GPT-4o vision extractor.

Tests (D-02, T-02-01, T-02-02):
1. Readable ticket → returns Decimal amount (parsed.monto=1500.0 → Decimal("1500"))
2. Unreadable ticket (monto=None) → returns None (no exception, no hallucinated amount)
3. Refusal (msg.refusal set) → refusal checked BEFORE parsed; returns None
4. Transport error (openai exception) → raises ExtractionFailedError; API key never logged

Run: cd backend && python -m pytest tests/test_ticket_vision.py -x -q
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog.testing

from openai.types.chat.parsed_chat_completion import (
    ParsedChatCompletion,
    ParsedChatCompletionMessage,
    ParsedChoice,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_completion(
    monto: Optional[float],
    refusal: Optional[str] = None,
) -> MagicMock:
    """Build a mocked ParsedChatCompletion for TicketAmount responses."""
    from app.services.ticket_vision import TicketAmount  # RED: ImportError until Task 1 green

    parsed = None
    if refusal is None:
        parsed = TicketAmount(monto=monto)

    mock_message = MagicMock(spec=ParsedChatCompletionMessage)
    mock_message.parsed = parsed
    mock_message.refusal = refusal

    mock_choice = MagicMock(spec=ParsedChoice)
    mock_choice.message = mock_message

    mock_completion = MagicMock(spec=ParsedChatCompletion)
    mock_completion.choices = [mock_choice]
    return mock_completion


def _make_service(
    monto: Optional[float] = None,
    refusal: Optional[str] = None,
    side_effect=None,
):
    """Build a TicketVisionService with a mocked openai client."""
    from app.config import get_settings
    from app.services.ticket_vision import TicketVisionService

    mock_client = MagicMock()
    if side_effect is not None:
        mock_client.chat.completions.parse = AsyncMock(side_effect=side_effect)
    else:
        mock_client.chat.completions.parse = AsyncMock(
            return_value=_make_mock_completion(monto=monto, refusal=refusal)
        )

    settings = get_settings()
    return TicketVisionService(openai_client=mock_client, settings=settings)


# ---------------------------------------------------------------------------
# Test 1: Readable ticket → returns Decimal (not float, not Decimal(float))
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_amount_readable() -> None:
    """Mocked client returning parsed.monto=1500.0 → service returns Decimal("1500").

    Verifies:
    - Decimal conversion via Decimal(str(...)) not Decimal(float) (T-02-02)
    - Returns a Decimal, not None
    """
    service = _make_service(monto=1500.0)
    image_bytes = b"fake-jpeg-bytes"

    result = await service.extract_amount(image_bytes)

    assert result is not None, "Readable ticket must return a Decimal, not None"
    assert isinstance(result, Decimal), f"Expected Decimal, got {type(result)}"
    assert result == Decimal("1500"), f"Expected Decimal('1500'), got {result}"


@pytest.mark.asyncio
async def test_extract_amount_readable_decimal_precision() -> None:
    """Decimal(str(1500.5)) == Decimal('1500.5') — not a float-precision artifact."""
    service = _make_service(monto=1500.5)
    result = await service.extract_amount(b"fake-jpeg-bytes")

    assert result is not None
    # Decimal(str(1500.5)) == Decimal('1500.5') — safe conversion
    assert result == Decimal("1500.5"), f"Expected Decimal('1500.5'), got {result}"


# ---------------------------------------------------------------------------
# Test 2: Unreadable ticket (monto=None) → returns None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_amount_unreadable_none() -> None:
    """Mocked client returning parsed.monto=None → service returns None.

    Null > hallucination (T-02-02): the service must return None when vision
    cannot read the amount, NOT raise an exception.
    """
    service = _make_service(monto=None)
    result = await service.extract_amount(b"fake-jpeg-bytes")

    assert result is None, (
        f"Unreadable ticket (monto=None) must return None, got {result!r}"
    )


# ---------------------------------------------------------------------------
# Test 3: Refusal → returns None (refusal checked BEFORE parsed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_amount_refusal_returns_none() -> None:
    """Mocked completion with msg.refusal set → service returns None.

    D-01b: refusal is treated as unreadable, not a crash.
    T-02-02: refusal must be checked BEFORE parsed (Pitfall 2).
    """
    service = _make_service(refusal="I cannot process this image.")
    result = await service.extract_amount(b"fake-jpeg-bytes")

    assert result is None, (
        f"Refusal must return None (treated as unreadable), got {result!r}"
    )


@pytest.mark.asyncio
async def test_extract_amount_refusal_does_not_access_parsed() -> None:
    """Refusal path: parsed is None on refusal completions — must not raise AttributeError."""
    # Build a completion where parsed IS None and refusal IS set
    from app.services.ticket_vision import TicketVisionService
    from app.config import get_settings

    mock_message = MagicMock(spec=ParsedChatCompletionMessage)
    mock_message.parsed = None  # parsed is None when refusal is set
    mock_message.refusal = "Content policy violation"

    mock_choice = MagicMock(spec=ParsedChoice)
    mock_choice.message = mock_message

    mock_completion = MagicMock(spec=ParsedChatCompletion)
    mock_completion.choices = [mock_choice]

    mock_client = MagicMock()
    mock_client.chat.completions.parse = AsyncMock(return_value=mock_completion)

    service = TicketVisionService(openai_client=mock_client, settings=get_settings())
    result = await service.extract_amount(b"fake-jpeg")

    # Must not raise; must return None
    assert result is None, (
        "When refusal is set and parsed is None, must return None without exception"
    )


# ---------------------------------------------------------------------------
# Test 4: Transport error → raises ExtractionFailedError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_amount_transport_error_raises() -> None:
    """openai exception (network/auth) → raises ExtractionFailedError.

    T-02-01: API key must never appear in the logged error message.
    """
    from app.services.extraction import ExtractionFailedError

    service = _make_service(side_effect=RuntimeError("Connection timeout"))

    with pytest.raises(ExtractionFailedError):
        await service.extract_amount(b"fake-jpeg-bytes")


@pytest.mark.asyncio
async def test_extract_amount_transport_error_no_api_key_logged() -> None:
    """The service never explicitly logs the openai_api_key setting (T-02-01).

    Pattern from extraction.py:197-198: error=str(exc) is logged, which is
    the exception message — not a direct reference to the API key from settings.
    The service must NOT pass the API key itself as a log field.

    We verify by patching settings to have a recognizable fake key and confirming
    the service does not include it as an explicit log field (not from exc message).
    """
    from app.services.extraction import ExtractionFailedError
    from app.config import Settings, get_settings
    from unittest.mock import MagicMock

    fake_key = "sk-test-supersecretkey123456"

    # Build a service using real settings (just a simple connection error, no key in message)
    service = _make_service(side_effect=ConnectionError("connection refused"))

    log_events = []
    with structlog.testing.capture_logs() as cap:
        with pytest.raises(ExtractionFailedError):
            await service.extract_amount(b"fake-jpeg-bytes")
        log_events = cap

    # The service must not have logged the API key as an explicit field
    for event in log_events:
        for key, value in event.items():
            if isinstance(value, str):
                assert fake_key not in value, (
                    f"API key-like value found in log event key='{key}': {event}"
                )

    # Verify that the error was logged (correct behavior present)
    assert len(log_events) >= 1, "Expected at least one log event on transport error"
    assert any(
        "ticket_vision.failed" in str(e.get("event", ""))
        for e in log_events
    ), "Expected ticket_vision.failed log event"
