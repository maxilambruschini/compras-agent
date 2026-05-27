"""GastoService — gasto persistence layer.

Stateless service that takes a session + DraftGasto and writes a committed gastos row.
This is the write side of the confirmation gate (GASTO-05) — invoked by the orchestrator
(Plan 04) only after explicit confirmation.

Analog: InvoiceService in app/services/invoice.py — stateless, session-first methods,
build/add/flush/log pattern.

Design rules:
- Caller (orchestrator) owns the transaction — save_gasto does NOT call session.commit().
- session.flush() populates the id so the caller can reference it before committing.
- sender_phone "whatsapp:" prefix removed via str.removeprefix() — strips at most one
  leading occurrence. NOT .replace("whatsapp:", "") (strips embedded) and NOT
  .strip("whatsapp:") (strips chars, not prefix string).
- fecha defaults to date.today() (D-02: auto-date, no backdating).
- T-03-02: structlog gasto.saved logged with id + monto for audit trail.
"""
from __future__ import annotations

from datetime import date

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Gasto
from app.models.conversation import DraftGasto


class GastoService:
    """Stateless service for gasto persistence.

    All methods take `session` as the first argument — the service holds no
    session state. Instantiate once per orchestrator call and discard.
    """

    def __init__(self) -> None:
        self._log = structlog.get_logger()

    async def save_gasto(
        self,
        session: AsyncSession,
        draft: DraftGasto,
        sender_phone: str,
    ) -> Gasto:
        """Persist a confirmed DraftGasto as a Gasto row.

        Builds the Gasto ORM object from the draft, adds it to the session,
        and flushes (to populate id). Does NOT commit — the orchestrator owns
        the transaction (GASTO-05, RESEARCH Pattern 7 commit-ownership note).

        Args:
            session: Active AsyncSession. Caller owns the session lifecycle.
            draft: The confirmed DraftGasto from the conversation state.
            sender_phone: The sender's phone (may include 'whatsapp:' prefix — stripped
                          via removeprefix, which removes at most one leading occurrence).

        Returns:
            The persisted Gasto ORM object with id populated (after flush).
        """
        clean_phone = sender_phone.removeprefix("whatsapp:").strip()

        gasto = Gasto(
            fecha=date.today(),
            concepto=draft.concepto,
            monto=draft.monto,
            ticket_image_path=draft.ticket_image_path,
            sender_phone=clean_phone,
        )

        session.add(gasto)
        await session.flush()  # populate id without committing — caller commits

        self._log.info(
            "gasto.saved",
            id=str(gasto.id),
            monto=str(draft.monto),
        )

        return gasto
