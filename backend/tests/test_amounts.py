"""Tests for parse_ars_amount() — Argentine number format utility.

ROADMAP success criterion 5 assertions are encoded below.
Tests cover the Decimal("1.500") trap (dot = thousands separator, not decimal).

Run: cd backend && python -m pytest tests/test_amounts.py -x -q
"""
from decimal import Decimal

import pytest

from app.services.amounts import parse_ars_amount


# ---------------------------------------------------------------------------
# ROADMAP success criterion 5 — exact assertions required
# ---------------------------------------------------------------------------


def test_parse_ars_amount_dot_thousands_sep():
    """'1.500' → Decimal('1500') — dot is a thousands separator, NOT decimal (the trap)."""
    assert parse_ars_amount("1.500") == Decimal("1500")


def test_parse_ars_amount_dot_thousands_comma_decimal():
    """'1.234,56' → Decimal('1234.56') — dot thousands, comma decimal."""
    assert parse_ars_amount("1.234,56") == Decimal("1234.56")


def test_parse_ars_amount_plain_integer():
    """'1500' → Decimal('1500') — no separator, plain integer."""
    assert parse_ars_amount("1500") == Decimal("1500")


def test_parse_ars_amount_comma_decimal_only():
    """'1500,50' → Decimal('1500.50') — comma decimal separator only."""
    assert parse_ars_amount("1500,50") == Decimal("1500.50")


def test_parse_ars_amount_unparseable_returns_none():
    """'abc' → None — unparseable input returns None, never raises."""
    assert parse_ars_amount("abc") is None


def test_parse_ars_amount_empty_string_returns_none():
    """'' → None — empty string returns None, never raises."""
    assert parse_ars_amount("") is None


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


def test_parse_ars_amount_none_input_returns_none():
    """None input → None — never raises (orchestrator safety)."""
    assert parse_ars_amount(None) is None  # type: ignore[arg-type]


def test_parse_ars_amount_whitespace_only_returns_none():
    """'   ' → None — whitespace only returns None."""
    assert parse_ars_amount("   ") is None


def test_parse_ars_amount_whitespace_around_value():
    """'  1500  ' → Decimal('1500') — strip surrounding whitespace."""
    assert parse_ars_amount("  1500  ") == Decimal("1500")


def test_parse_ars_amount_large_amount():
    """'1.234.567,89' → Decimal('1234567.89') — multiple thousands separators."""
    assert parse_ars_amount("1.234.567,89") == Decimal("1234567.89")


def test_parse_ars_amount_never_raises_on_bad_input():
    """Bad input never raises an exception — always returns None."""
    for bad in ["$abc", "1,2,3", "NaN", "inf", "-", "1.2.3.4"]:
        result = parse_ars_amount(bad)
        assert result is None, f"Expected None for {bad!r}, got {result!r}"
