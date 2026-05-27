"""Tests for GastoSlots, DraftGasto DTOs and SlotExtractionService.

Strategy:
- DTOs: field type and default assertions (all Optional, correct types).
- SlotExtractionService: mocked AsyncOpenAI client (never makes live calls).
  Mock helper mirrors test_extraction.py verbatim (ParsedChatCompletionMessage spec).
- Refusal checked BEFORE parsed (mirrors ExtractionService contract).
- extract() model and response_format verified via call_args.

Run: cd backend && python -m pytest tests/test_slot_extraction.py -x -q
"""
from decimal import Decimal
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai.types.chat.parsed_chat_completion import (
    ParsedChatCompletion,
    ParsedChatCompletionMessage,
    ParsedChoice,
)

from app.config import get_settings
from app.models.conversation import DraftGasto, GastoSlots
from app.services.slot_extraction import SlotExtractionService


# ---------------------------------------------------------------------------
# Mock helper — mirrors test_extraction.py verbatim
# ---------------------------------------------------------------------------


def make_mock_completion(
    parsed_slots: Optional[GastoSlots],
    refusal: Optional[str] = None,
) -> MagicMock:
    """Pattern from test_extraction.py — verified against openai==2.36.0."""
    mock_message = MagicMock(spec=ParsedChatCompletionMessage)
    mock_message.parsed = parsed_slots
    mock_message.refusal = refusal

    mock_choice = MagicMock(spec=ParsedChoice)
    mock_choice.message = mock_message

    mock_completion = MagicMock(spec=ParsedChatCompletion)
    mock_completion.choices = [mock_choice]
    return mock_completion


def make_slot_service(
    parsed_slots: Optional[GastoSlots] = None,
    refusal: Optional[str] = None,
) -> SlotExtractionService:
    """Build a SlotExtractionService with mocked AsyncOpenAI client."""
    mock_openai = MagicMock()
    mock_openai.chat.completions.parse = AsyncMock(
        return_value=make_mock_completion(parsed_slots, refusal)
    )
    settings = get_settings()
    return SlotExtractionService(openai_client=mock_openai, settings=settings)


# ---------------------------------------------------------------------------
# GastoSlots DTO tests
# ---------------------------------------------------------------------------


def test_gasto_slots_all_fields_optional_default_none():
    """GastoSlots() with no args → all fields default to None (D-01, P32)."""
    slots = GastoSlots()
    assert slots.concepto is None
    assert slots.monto is None


def test_gasto_slots_concepto_is_optional_str():
    """GastoSlots.concepto accepts str or None."""
    slots = GastoSlots(concepto="queso en supermercado", monto=1500.0)
    assert slots.concepto == "queso en supermercado"
    assert isinstance(slots.monto, float)
    assert slots.monto == 1500.0


def test_gasto_slots_monto_is_optional_float():
    """GastoSlots.monto is typed Optional[float] — GPT outputs JSON number, not locale string."""
    slots = GastoSlots(monto=1234.56)
    assert isinstance(slots.monto, float)
    assert slots.monto == 1234.56


def test_gasto_slots_no_extra_fields():
    """GastoSlots has only concepto and monto — D-01 minimal field set (no lugar/proveedor/category)."""
    # Access model_fields on class (not instance) — Pydantic v2.11+ deprecates instance access
    assert set(GastoSlots.model_fields.keys()) == {"concepto", "monto"}


# ---------------------------------------------------------------------------
# DraftGasto DTO tests
# ---------------------------------------------------------------------------


def test_draft_gasto_all_optional_with_defaults():
    """DraftGasto() with no args → concepto/monto/ticket_image_path all None, failure_count=0."""
    draft = DraftGasto()
    assert draft.concepto is None
    assert draft.monto is None
    assert draft.ticket_image_path is None
    assert draft.failure_count == 0


def test_draft_gasto_monto_is_optional_decimal():
    """DraftGasto.monto is typed Optional[Decimal] — converted from GastoSlots.monto by orchestrator."""
    draft = DraftGasto(monto=Decimal("1500.00"))
    assert isinstance(draft.monto, Decimal)
    assert draft.monto == Decimal("1500.00")


def test_draft_gasto_no_extra_fields():
    """DraftGasto has no lugar/proveedor/entrada/category per D-01."""
    # Access model_fields on class (not instance) — Pydantic v2.11+ deprecates instance access
    allowed = {"concepto", "monto", "ticket_image_path", "failure_count"}
    assert set(DraftGasto.model_fields.keys()) == allowed


def test_draft_gasto_failure_count_default_zero():
    """DraftGasto.failure_count defaults to 0 (CONV-06 counter)."""
    draft = DraftGasto()
    assert draft.failure_count == 0


# ---------------------------------------------------------------------------
# SlotExtractionService.extract() — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_returns_parsed_slots_on_success():
    """extract() returns GastoSlots from mocked .parse() — GASTO-01."""
    expected = GastoSlots(concepto="queso en supermercado", monto=1500.0)
    service = make_slot_service(parsed_slots=expected)

    result = await service.extract("queso en supermercado $1500")

    assert isinstance(result, GastoSlots)
    assert result.concepto == "queso en supermercado"
    assert result.monto == 1500.0


@pytest.mark.asyncio
async def test_extract_calls_parse_with_gpt4o_mini_and_gasto_slots_format():
    """extract() calls client.chat.completions.parse with model='gpt-4o-mini' and response_format=GastoSlots."""
    expected = GastoSlots(concepto="queso", monto=1500.0)
    service = make_slot_service(parsed_slots=expected)

    await service.extract("queso $1500")

    call_args = service._client.chat.completions.parse.call_args
    assert call_args is not None
    kwargs = call_args.kwargs if call_args.kwargs else {}
    # Support positional or keyword args
    if not kwargs:
        kwargs = call_args[1]
    assert kwargs.get("model") == "gpt-4o-mini", (
        f"Expected model='gpt-4o-mini', got {kwargs.get('model')!r}"
    )
    assert kwargs.get("response_format") is GastoSlots, (
        f"Expected response_format=GastoSlots, got {kwargs.get('response_format')!r}"
    )


# ---------------------------------------------------------------------------
# SlotExtractionService.extract() — refusal / None paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_returns_empty_slots_on_refusal():
    """When msg.refusal is set, extract() returns empty GastoSlots() — refusal checked BEFORE parsed."""
    service = make_slot_service(parsed_slots=None, refusal="I cannot extract this")

    result = await service.extract("some text")

    assert isinstance(result, GastoSlots)
    assert result.concepto is None
    assert result.monto is None


@pytest.mark.asyncio
async def test_extract_returns_empty_slots_when_parsed_is_none():
    """When msg.parsed is None (no refusal), extract() returns empty GastoSlots()."""
    service = make_slot_service(parsed_slots=None, refusal=None)

    result = await service.extract("some text")

    assert isinstance(result, GastoSlots)
    assert result.concepto is None
    assert result.monto is None


@pytest.mark.asyncio
async def test_extract_refusal_takes_priority_over_parsed():
    """When both refusal and parsed are set, refusal wins — checked first per ExtractionService contract."""
    # Construct a completion where both refusal and parsed are non-None
    # (unusual, but must not crash and must return empty slots)
    mock_openai = MagicMock()
    mock_message = MagicMock(spec=ParsedChatCompletionMessage)
    mock_message.refusal = "I refuse"
    mock_message.parsed = GastoSlots(concepto="test", monto=100.0)  # should be ignored

    mock_choice = MagicMock(spec=ParsedChoice)
    mock_choice.message = mock_message

    mock_completion = MagicMock(spec=ParsedChatCompletion)
    mock_completion.choices = [mock_choice]

    mock_openai.chat.completions.parse = AsyncMock(return_value=mock_completion)
    settings = get_settings()
    service = SlotExtractionService(openai_client=mock_openai, settings=settings)

    result = await service.extract("some text")

    # Refusal checked first → returns empty GastoSlots
    assert result.concepto is None
    assert result.monto is None


# ---------------------------------------------------------------------------
# No live OpenAI calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_live_openai_call_made():
    """Mocked service never makes a live network call — parse is an AsyncMock."""
    service = make_slot_service(parsed_slots=GastoSlots(concepto="test", monto=100.0))
    await service.extract("test input")

    # AsyncMock was called exactly once (the test call above)
    service._client.chat.completions.parse.assert_awaited_once()
