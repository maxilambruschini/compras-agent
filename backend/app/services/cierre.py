"""CajaCierreService — caja closing persistence layer.

Mirrors GastoService: stateless, session-first, caller owns transaction.

Design rules:
- Caller (ConversationOrchestrator) owns the transaction — save_cierre does NOT commit.
- session.flush() populates the id so the caller can reference it before committing.
- hora_cierre and fecha are derived from current ART time (America/Argentina/Buenos_Aires).
- T-03: structlog cierre.saved logged with id + hora_cierre + monto for audit trail.

Wave 0 skeleton: _derive_hora_cierre and _today_art are fully implemented (pure functions,
tested by test_hora_cierre_morning/afternoon). save_cierre raises NotImplementedError —
full implementation lands in Plan 03 (Wave 2).

Patching note: tests patch `app.services.cierre.datetime` (the module-level `datetime`
name, not the stdlib module). Always call `datetime.now(_ART)` through this module-level
reference so the patch works correctly.
"""
from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CajaCierre

# ---------------------------------------------------------------------------
# Module-level timezone constants
# ---------------------------------------------------------------------------

_ART = ZoneInfo("America/Argentina/Buenos_Aires")
_CUTOFF = time(14, 30)  # 14:30 ART: before → "12:00", at/after → "17:00"

# ---------------------------------------------------------------------------
# Pure time helpers (fully implemented — no side effects, patchable via
# `unittest.mock.patch("app.services.cierre.datetime")`)
# ---------------------------------------------------------------------------


def _derive_hora_cierre() -> str:
    """Return '12:00' if the current ART time is before 14:30, else '17:00'.

    Argentina does not observe DST (stable UTC-3 since 2008), so the cutoff is
    deterministic. Uses the module-level `datetime` reference so tests can patch
    `app.services.cierre.datetime` to freeze the clock.
    """
    now_art = datetime.now(_ART)
    return "12:00" if now_art.time() < _CUTOFF else "17:00"


def _today_art():
    """Return today's date in ART (not UTC).

    At a late UTC evening instant (e.g. 23:30 UTC = 20:30 ART the same day, but
    02:30 UTC next day = 23:30 ART previous day), ART and UTC may differ by a
    calendar day. Always use this helper for fecha — never date.today() (which
    returns the system/UTC date).
    """
    return datetime.now(_ART).date()


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------


class CajaCierreService:
    """Stateless service for CajaCierre persistence.

    All methods take `session` as the first argument — the service holds no
    session state. Instantiate once per orchestrator call and discard.

    Wave 0 skeleton: save_cierre is a NotImplementedError stub. Full
    implementation lands in Plan 03 (Wave 2).
    """

    def __init__(self) -> None:
        self._log = structlog.get_logger()

    async def save_cierre(
        self,
        session: AsyncSession,
        efectivo_en_caja: Decimal,
        sender_phone: str,
    ) -> CajaCierre:
        """Persist a confirmed CajaCierre row.

        Caller owns the transaction — does NOT commit.
        session.flush() will populate the id (mirrors GastoService.save_gasto).

        Args:
            session: Active AsyncSession. Caller owns the session lifecycle.
            efectivo_en_caja: Cash amount as Decimal from parse_ars_amount().
                              Never convert to float — Numeric(14,2) stores Decimal directly.
            sender_phone: Sender's phone (may include 'whatsapp:' prefix — stripped
                          via removeprefix, which removes at most one leading occurrence).

        Returns:
            The persisted CajaCierre ORM object with id populated (after flush).

        Raises:
            NotImplementedError: Wave 0 stub — full implementation in Plan 03.
        """
        raise NotImplementedError("save_cierre: Plan 03 implementation pending")
