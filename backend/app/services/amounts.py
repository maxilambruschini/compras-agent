"""parse_ars_amount() — Argentine number format utility.

Module-level pure function, importable with no side effects.
Mirror: compute_confidence / assign_status in extraction.py (pure helpers, no class).

The Decimal("1.500") Trap (PITFALLS.md P26 / CONV-05):
    Python's Decimal("1.500") == Decimal("1.5") == 1.5, NOT 1500.
    Argentine invoices use period as a thousands separator ("1.500" means one thousand
    five hundred), NOT as a decimal point. Passing raw Argentine-formatted strings to
    Decimal() silently corrupts every amount with a thousands separator.

Defence:
    1. Primary path: GastoSlots.monto is typed Optional[float] so GPT Structured Outputs
       emits a JSON number (e.g. 1500.0) — no locale formatting reaches Decimal().
    2. Fallback path (this function): strip thousands separator (dot) first, then replace
       decimal separator (comma) with dot, then parse with Decimal().

NEVER use Python's locale module — global mutable state, unsafe in async contexts.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Optional


def parse_ars_amount(text: Optional[str]) -> Optional[Decimal]:
    """Parse an Argentine-formatted amount string to Decimal.

    Handles:
        "1.500"       → Decimal("1500")    (dot = thousands separator)
        "1.234,56"    → Decimal("1234.56") (comma = decimal separator)
        "1500"        → Decimal("1500")
        "1500,50"     → Decimal("1500.50")
        "1.234.567,89"→ Decimal("1234567.89") (multiple thousands separators)

    Returns None on any parse failure — null > hallucination (never raises).
    The Decimal("1.500") trap: without this utility, Decimal("1.500") == 1.5 (not 1500).

    Args:
        text: Raw Argentine-formatted amount string (may include whitespace, None).

    Returns:
        Parsed Decimal, or None if input is None, empty, or unparseable.
    """
    if text is None:
        return None
    try:
        cleaned = text.strip()
        if not cleaned:
            return None
        # Validate Argentine number format before stripping separators.
        # Valid patterns (ARS):
        #   - Optional thousands groups: each dot must be followed by exactly 3 digits.
        #   - Optional decimal: a trailing comma followed by 1+ digits.
        #   - Examples: "1500", "1.500", "1.234,56", "1.234.567,89"
        # Invalid: "1.2.3.4" (dots NOT followed by exactly 3 digits), "NaN", "abc".
        import re
        # Pattern: optional leading digits, then groups of (dot + exactly 3 digits),
        # then optional (comma + 1-2 digits for cents).
        _ARS_PATTERN = re.compile(
            r"^\d{1,3}(\.\d{3})*(,\d{1,4})?$"   # e.g. 1.234,56 or 1.234.567,89
            r"|^\d+(,\d{1,4})?$"                 # e.g. 1500 or 1500,50
        )
        if not _ARS_PATTERN.match(cleaned):
            return None
        # Remove thousands separator (dot) then replace decimal separator (comma) with dot.
        cleaned = cleaned.replace(".", "").replace(",", ".")
        result = Decimal(cleaned)
        # Reject NaN and Infinity — not valid monetary amounts
        if result.is_nan() or result.is_infinite():
            return None
        return result
    except (InvalidOperation, ValueError):
        return None
