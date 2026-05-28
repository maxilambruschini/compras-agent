"""ConversationOrchestrator — deterministic match-based FSM for the Gastos Bot.

Wires together SlotExtractionService (Plan 02), GastoService (Plan 03), and the
Conversation/Gasto models (Plan 01) behind a per-sender row lock, DB-backed
idempotency, and timeout reset.

Failure model (review concern 4)
---------------------------------
All DB mutations (last_message_id, state, draft) happen inside one
`async with session.begin()` block that commits atomically. If ANY exception
is raised inside that block, the transaction rolls back — including the
`last_message_id = message_id` assignment — so a retry of the same webhook
sees the prior last_message_id and is fully reprocessable (no silently-lost
message). The exception propagates after rollback so the caller/webhook handler
can retry.

The dispatched reply is sent via provider.send_message strictly AFTER the commit,
OUTSIDE the transaction (Pitfall C). A provider-send failure does NOT roll back
the committed DB state — this is the accepted at-most-once reply risk: the
gasto/state is durable but the WhatsApp reply may be lost.
A Phase-2 outbox/retry is the future mitigation if reliable replies become required.
Do not attempt to reverse committed state on a send failure.

Entry sequence (non-negotiable ordering — see RESEARCH Pattern 5 + cycle-2 HIGH fix)
--------------------------------------------------------------------------------------
1. Ensure-row-exists FIRST, race-safe (ON CONFLICT DO NOTHING):
   `pg_insert(Conversation).values(...).on_conflict_do_nothing(index_elements=["sender_phone"])`
   This is also valid SQLite ON CONFLICT syntax, so the unit suite exercises this path.
   Two concurrent FIRST messages from a brand-new sender: the losing INSERT no-ops
   instead of raising IntegrityError. Both then converge on the single row under the
   SELECT ... FOR NO KEY UPDATE lock.
   TRUE cross-session insert serialisation is a Postgres-only behaviour — SQLite's
   in-process test engine cannot reproduce a genuine cross-connection insert race,
   so it is a separately-marked Postgres integration test:
       tests/integration/test_conversation_concurrency_pg.py
       @pytest.mark.pg_integration (deferred to verify-phase, T-04-RACE)

2. SELECT conversations WHERE sender_phone = X WITH FOR NO KEY UPDATE (row lock).
   `select(Conversation).with_for_update(key_share=True)` — key_share=True compiles
   to 'FOR NO KEY UPDATE' under the postgresql dialect (verified; Task 0 pins this).
   SQLite ignores row locks — tests assert the lock hint and compiled mode via spy
   (RESEARCH Pattern 6), not SQLite semantics.

3. Capture `loaded_updated_at = conv.updated_at` IMMEDIATELY — before any mutation.
   All timeout logic compares against this snapshot; never against conv.updated_at
   after assignment (onupdate=func.now() would advance it, masking an expired convo).

4. Idempotency check BEFORE any state read:
   if conv.last_message_id == message_id → return no-op (no write, no advance).
   Else: conv.last_message_id = message_id.

5. Timeout: if state != idle and now(utc) − loaded_updated_at > timeout_hours →
   reset state=idle, draft=None, commit, then send Spanish notice OUTSIDE txn.

6. Global 'cancelar' (exact normalized token match):
   reset state=idle, draft=None, commit, send "Registro cancelado." OUTSIDE txn.

7. Dispatch to _dispatch() state handler → reply string.

8. Commit (inside session.begin() block — atomic with all mutations from step 4-7).

9. Send reply via provider.send_message() OUTSIDE the transaction.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Conversation
from app.models.conversation import DraftGasto, GastoSlots
from app.services.amounts import parse_ars_amount


# ---------------------------------------------------------------------------
# State constants
# ---------------------------------------------------------------------------

class ConvState:
    IDLE = "idle"
    AWAITING_MONTO = "awaiting_monto"
    AWAITING_TICKET = "awaiting_ticket"
    CONFIRM = "confirm"


# ---------------------------------------------------------------------------
# Affirmative set (D-05 / PITFALLS.md P31)
# Exact normalized-token match only: strip + lower + rstrip(".!")
# "sí" matches; "sí, pero …" does NOT match — that routes to the correction path.
# ---------------------------------------------------------------------------

AFFIRMATIVE = frozenset({
    "sí", "si", "dale", "ok", "confirmo", "listo", "va", "yes", "bueno", "claro",
})

# ---------------------------------------------------------------------------
# Deflection reply (D-04)
# Returned for off-topic idle messages. State stays IDLE.
# Argentine Spanish — concise description of what the bot does.
# ---------------------------------------------------------------------------

DEFLECTION_REPLY: str = (
    "Hola, soy el asistente de gastos. "
    "Puedo ayudarte a registrar gastos en efectivo. "
    "Describí un gasto (ej: 'pagué $1500 de queso en el super') y te guío paso a paso."
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def is_confirmation(text: str) -> bool:
    """Return True only if text is EXACTLY one of the affirmative tokens (D-05).

    Uses EXACT normalized-token match — strip + lower + rstrip(".!").
    This is NOT a prefix, startswith, or substring match. Concretely:
    - "sí"    → True
    - "si"    → True
    - "sí, pero cambiá el monto a 1500" → False (routes to correction path)
    - "si no tiene ticket"              → False (routes to correction path)
    """
    return text.strip().lower().rstrip(".!") in AFFIRMATIVE


def is_cancel(text: str) -> bool:
    """Return True only if text is EXACTLY 'cancelar' (normalized)."""
    return text.strip().lower().rstrip(".!") == "cancelar"


def patch_draft(draft: DraftGasto, slots: GastoSlots) -> DraftGasto:
    """Apply non-null extracted slots onto the existing draft. Never overwrite with null.

    monto from GastoSlots (Optional[float]) is converted to Decimal(str(...)) per D-06.
    """
    if slots.concepto is not None:
        draft.concepto = slots.concepto
    if slots.monto is not None:
        draft.monto = Decimal(str(slots.monto))
    return draft


# ---------------------------------------------------------------------------
# ConversationOrchestrator
# ---------------------------------------------------------------------------

class ConversationOrchestrator:
    """Deterministic match-based FSM for the Gastos Bot conversation flow.

    Constructor takes all collaborators via DI so tests can inject mocks
    without touching production singletons.

    Args:
        slot_service: SlotExtractionService — async .extract(text) → GastoSlots.
        gasto_service: GastoService — async .save_gasto(session, draft, sender_phone) → Gasto.
        provider: WhatsAppProvider — async .send_message(to, text) → None.
    """

    def __init__(self, slot_service, gasto_service, provider) -> None:
        self._slot_service = slot_service
        self._gasto_service = gasto_service
        self._provider = provider
        self._log = structlog.get_logger()

    async def handle_message(
        self,
        session_factory,
        sender: str,
        text: str,
        message_id: str,
        ticket_image_path: Optional[str] = None,
        ticket_amount: Optional[Decimal] = None,
    ) -> None:
        """Handle one inbound message for a sender.

        Follows the non-negotiable entry sequence (see module docstring):
        ensure-row → lock → snapshot → idempotency → timeout → cancel → dispatch → commit → reply.

        Args:
            session_factory: Callable context manager returning an AsyncSession.
            sender: Sender phone number (may include 'whatsapp:' prefix — stripped once).
            text: Inbound message text.
            message_id: Unique message ID from the messaging platform (idempotency key).
            ticket_image_path: Optional path to a stored ticket image (D-06 media entry).
                Passed by the router after downloading + storing the media.
            ticket_amount: Optional Decimal amount extracted by vision from the ticket (D-06).
                None when vision was unreadable or no media present.
        """
        settings = get_settings()
        log = self._log.bind(sender=sender, message_id=message_id)

        # Normalize sender: strip at most one leading "whatsapp:" prefix (Pitfall — removeprefix)
        clean_sender = sender.removeprefix("whatsapp:")

        reply: Optional[str] = None

        async with session_factory() as session:
            async with session.begin():
                # -----------------------------------------------------------
                # Step 1: Ensure-row-exists FIRST, race-safe (cycle-2 HIGH fix)
                # ON CONFLICT DO NOTHING is also valid SQLite syntax.
                # True cross-session serialisation deferred (T-04-RACE).
                # -----------------------------------------------------------
                ensure_stmt = (
                    pg_insert(Conversation)
                    .values(sender_phone=clean_sender, state=ConvState.IDLE)
                    .on_conflict_do_nothing(index_elements=["sender_phone"])
                )
                await session.execute(ensure_stmt)

                # -----------------------------------------------------------
                # Step 2: Lock the now-guaranteed-to-exist row
                # key_share=True → FOR NO KEY UPDATE (verified Task 0)
                # -----------------------------------------------------------
                result = await session.execute(
                    select(Conversation)
                    .where(Conversation.sender_phone == clean_sender)
                    .with_for_update(key_share=True)
                )
                conv = result.scalar_one()

                # -----------------------------------------------------------
                # Step 3: Snapshot updated_at BEFORE any field mutation.
                # All timeout logic uses this snapshot — never conv.updated_at
                # after assignment (onupdate=func.now() would advance it).
                # -----------------------------------------------------------
                loaded_updated_at = conv.updated_at

                # -----------------------------------------------------------
                # Step 4: Idempotency — BEFORE any state read or write
                # -----------------------------------------------------------
                if conv.last_message_id == message_id:
                    log.info("conversation.duplicate_message", state=conv.state)
                    return  # already processed — no-op, release lock
                conv.last_message_id = message_id

                # -----------------------------------------------------------
                # Step 5: Timeout check (D-08 / CONV-04)
                # Compares NOW against the PRE-MUTATION snapshot.
                # -----------------------------------------------------------
                if conv.state != ConvState.IDLE and loaded_updated_at is not None:
                    now_utc = datetime.now(tz=timezone.utc)
                    # Ensure loaded_updated_at is timezone-aware for comparison
                    ref_time = loaded_updated_at
                    if ref_time.tzinfo is None:
                        ref_time = ref_time.replace(tzinfo=timezone.utc)
                    age = now_utc - ref_time
                    if age > timedelta(hours=settings.conversation_timeout_hours):
                        log.info(
                            "conversation.timeout",
                            state=conv.state,
                            age_hours=age.total_seconds() / 3600,
                        )
                        conv.state = ConvState.IDLE
                        conv.draft_gasto = None
                        reply = "Tu registro anterior expiró. Podés empezar uno nuevo cuando quieras."
                        # Transaction commits at end of async with session.begin() block
                        # Reply sent OUTSIDE transaction below (Pitfall C)

                if reply is not None:
                    # Timeout path — skip dispatch, commit happens when block exits
                    pass
                else:
                    # -----------------------------------------------------------
                    # Step 6: Global 'cancelar' (exact token, not substring)
                    # -----------------------------------------------------------
                    if is_cancel(text):
                        log.info("conversation.cancelled", state=conv.state)
                        conv.state = ConvState.IDLE
                        conv.draft_gasto = None
                        reply = "Registro cancelado."
                    else:
                        # -----------------------------------------------------------
                        # Step 7: Dispatch to state handler
                        # -----------------------------------------------------------
                        reply = await self._dispatch(
                            session, conv, text,
                            ticket_image_path=ticket_image_path,
                            ticket_amount=ticket_amount,
                        )

            # session.begin() commits here (or rolls back on exception)

        # -----------------------------------------------------------
        # Step 9: Send reply OUTSIDE the transaction (Pitfall C)
        # A provider failure here does NOT roll back committed DB state.
        # This is the at-most-once reply risk (see module docstring).
        # -----------------------------------------------------------
        if reply is not None:
            await self._provider.send_message(clean_sender, reply)

    async def _dispatch(
        self,
        session: AsyncSession,
        conv: Conversation,
        text: str,
        ticket_image_path: Optional[str] = None,
        ticket_amount: Optional[Decimal] = None,
    ) -> str:
        """Dispatch to the correct state handler and return the reply string.

        All state mutations (conv.state, conv.draft_gasto) happen here.
        The caller (handle_message) commits after this returns.

        Failure model: any exception propagates to handle_message, which lets
        session.begin() roll back the transaction — including the last_message_id
        assignment, so the webhook is retryable.
        """
        log = self._log.bind(state=conv.state)

        # Load or initialize draft
        draft = self._load_draft(conv)

        match conv.state:

            case ConvState.IDLE:
                reply = await self._handle_idle(session, conv, draft, text)

            case ConvState.AWAITING_MONTO:
                reply = await self._handle_awaiting_monto(session, conv, draft, text)

            case ConvState.AWAITING_TICKET:
                reply = await self._handle_awaiting_ticket(
                    conv, draft, text,
                    ticket_image_path=ticket_image_path,
                    ticket_amount=ticket_amount,
                )

            case ConvState.CONFIRM:
                reply = await self._handle_confirm(session, conv, draft, text)

            case _:
                # Unknown state — reset to idle
                log.warning("conversation.unknown_state", state=conv.state)
                conv.state = ConvState.IDLE
                conv.draft_gasto = None
                reply = "Algo salió mal. Empecemos de nuevo. ¿Qué gasto querés registrar?"

        return reply

    def _load_draft(self, conv: Conversation) -> DraftGasto:
        """Load draft from conversation JSON, or return a fresh DraftGasto on error.

        DraftGasto.model_validate wrapped in try/except → reset to fresh draft on
        ValidationError (T-04-03 mitigation: malformed JSON or schema evolution).
        """
        if conv.draft_gasto:
            try:
                return DraftGasto.model_validate_json(conv.draft_gasto)
            except Exception:
                self._log.warning("conversation.draft_parse_error", state=conv.state)
                return DraftGasto()
        return DraftGasto()

    def _save_draft(self, conv: Conversation, draft: DraftGasto) -> None:
        """Reassign conv.draft_gasto as a JSON string (never mutate in-place).

        Reassignment triggers SQLAlchemy change-tracking so onupdate=func.now()
        fires on updated_at (Pitfall E).
        """
        conv.draft_gasto = draft.model_dump_json()

    async def _handle_idle(
        self,
        session: AsyncSession,
        conv: Conversation,
        draft: DraftGasto,
        text: str,
    ) -> str:
        """Handle message in idle state — D-01 ticket-first ordering.

        Extract slots from opening intent. Branch on concepto presence:
        - No slots at all (concepto=None, monto=None) → off-topic deflection, stay IDLE (D-04).
        - Concepto missing but message looks like a gasto attempt → ask for concepto.
        - Concepto known (regardless of monto) → ticket-first: advance to AWAITING_TICKET (D-01).
          Vision will read the amount from the ticket; monto comes from ticket, not this turn.
        """
        slots = await self._slot_service.extract(text)
        draft = patch_draft(draft, slots)

        if slots.concepto is None and slots.monto is None:
            # Off-topic: no recognizable gasto slots extracted → fixed deflection (D-04)
            # Do NOT save draft, do NOT advance state
            return DEFLECTION_REPLY

        if draft.concepto is None:
            # Message had some gasto signal (e.g. monto only) but concepto still missing.
            # Ask for concepto — reuse AWAITING_MONTO state as concepto-collecting state
            # (there's no separate awaiting_concepto state per ConvState design).
            # The reply explicitly asks for concepto, not monto.
            self._save_draft(conv, draft)
            conv.state = ConvState.AWAITING_MONTO
            return "¿Cuál fue el concepto del gasto? (ej: queso en supermercado)"

        else:
            # Concepto is known — D-01 ticket-first: go to AWAITING_TICKET
            # Ask for ticket photo (or 'sin ticket') regardless of whether monto was stated.
            # Vision re-reads amount from ticket; confirm summary shows the resolved amount (D-01a).
            conv.state = ConvState.AWAITING_TICKET
            self._save_draft(conv, draft)
            return (
                f"Entendido, *{draft.concepto}*. "
                "¿Tenés foto del ticket de pago? Enviá la foto o respondé *sin ticket*."
            )

    async def _handle_awaiting_monto(
        self,
        session: AsyncSession,
        conv: Conversation,
        draft: DraftGasto,
        text: str,
    ) -> str:
        """Handle message in awaiting_monto state.

        Try to extract monto via SlotExtractionService, then fall back to parse_ars_amount.
        On success: reset failure_count, advance to awaiting_ticket.
        On failure: increment failure_count; on >=3, include example + cancel offer.

        Note: AWAITING_MONTO is also used as a concepto-collecting state when concepto
        is missing (reusing the same state for simplicity, per plan). When concepto
        is still missing, a correct monto reply will also extract concepto from context.
        """
        # Try GPT extraction first
        slots = await self._slot_service.extract(text)

        monto: Optional[Decimal] = None
        if slots.monto is not None:
            monto = Decimal(str(slots.monto))

        # Also update concepto if GPT found one and we didn't have it yet
        if slots.concepto is not None and draft.concepto is None:
            draft.concepto = slots.concepto

        # Fallback: try parse_ars_amount on raw text
        if monto is None:
            monto = parse_ars_amount(text)

        if monto is not None:
            # Success — update draft and advance
            draft.monto = monto
            draft.failure_count = 0
            conv.state = ConvState.AWAITING_TICKET
            self._save_draft(conv, draft)
            return (
                f"Anotado: ${draft.monto}. "
                "¿Tenés foto del ticket? Si no, respondé *sin ticket*."
            )
        else:
            # Parse failure — increment failure counter
            draft.failure_count += 1
            self._save_draft(conv, draft)

            if draft.failure_count >= 3:
                return (
                    "No pude entender el monto. "
                    "Por ejemplo: *1500* o *1.500,50*. "
                    "Si querés cancelar, respondé *cancelar*."
                )
            else:
                return "No pude entender el monto. ¿Cuánto fue? (ej: 1500)"

    async def _handle_awaiting_ticket(
        self,
        conv: Conversation,
        draft: DraftGasto,
        text: str,
        ticket_image_path: Optional[str] = None,
        ticket_amount: Optional[Decimal] = None,
    ) -> str:
        """Handle message in awaiting_ticket state — D-01/D-02/D-06 core logic.

        Branches:
        (a) text == "sin ticket" (case-insensitive) → ticket_image_path stays None,
            state → AWAITING_MONTO, ask manager to type the amount (D-01, GASTO-04).
        (b) ticket_image_path is not None AND ticket_amount is not None → vision read ok:
            set draft.monto = ticket_amount, draft.ticket_image_path = path,
            state → CONFIRM, reply is confirm summary showing resolved amount (D-01a, D-02).
        (c) ticket_image_path is not None AND ticket_amount is None → vision unreadable (D-01b):
            still store ticket_image_path on draft, state → AWAITING_MONTO,
            ask manager to type the amount (falls into the re-prompt path).
        (d) plain text that is neither "sin ticket" nor an accompanying photo →
            re-prompt asking for a photo or 'sin ticket'.
        """
        # Branch (a): 'sin ticket' — manager explicitly skips the ticket
        if text.strip().lower() == "sin ticket":
            draft.ticket_image_path = None
            conv.state = ConvState.AWAITING_MONTO
            self._save_draft(conv, draft)
            return "Entendido, sin ticket. ¿Cuánto fue el monto? (ej: 1500)"

        # Branch (b): photo received + vision extracted amount successfully
        if ticket_image_path is not None and ticket_amount is not None:
            draft.ticket_image_path = ticket_image_path
            draft.monto = ticket_amount
            conv.state = ConvState.CONFIRM
            self._save_draft(conv, draft)
            return self._confirm_summary(draft)

        # Branch (c): photo received but vision could not read amount (D-01b)
        if ticket_image_path is not None and ticket_amount is None:
            draft.ticket_image_path = ticket_image_path  # always store when provided (D-02)
            conv.state = ConvState.AWAITING_MONTO
            self._save_draft(conv, draft)
            return (
                "Guardé la foto del ticket pero no pude leer el monto. "
                "¿Cuánto fue? (ej: 1500)"
            )

        # Branch (d): plain text, not 'sin ticket', no accompanying photo
        # Re-prompt for a photo or 'sin ticket'
        return (
            "Enviá la foto del ticket de pago o respondé *sin ticket* "
            "si no tenés comprobante."
        )

    async def _handle_confirm(
        self,
        session: AsyncSession,
        conv: Conversation,
        draft: DraftGasto,
        text: str,
    ) -> str:
        """Handle message in confirm state.

        Exact affirmative token → save_gasto, reset to idle.
        Non-affirmative, non-cancel → re-extract correction onto draft, re-confirm (D-07).
        GPT is NEVER called to decide the confirmation itself (D-05).
        """
        if is_confirmation(text):
            # Deterministic match — GPT never invoked here (D-05)
            await self._gasto_service.save_gasto(session, draft, conv.sender_phone)
            conv.state = ConvState.IDLE
            conv.draft_gasto = None
            return "¡Gasto registrado! ✓"
        else:
            # Correction (D-07): re-extract onto draft, re-confirm
            # is_cancel() was already handled upstream — this is a true correction
            slots = await self._slot_service.extract(text)
            draft = patch_draft(draft, slots)
            self._save_draft(conv, draft)
            # Stay in confirm
            return self._confirm_summary(draft)

    def _confirm_summary(self, draft: DraftGasto) -> str:
        """Build the confirmation summary string for the confirm state."""
        concepto = draft.concepto or "(sin concepto)"
        monto = draft.monto or "(sin monto)"
        ticket = "sin ticket" if draft.ticket_image_path is None else "con ticket"
        return (
            f"Resumen del gasto:\n"
            f"• Concepto: {concepto}\n"
            f"• Monto: ${monto}\n"
            f"• Ticket: {ticket}\n\n"
            f"¿Confirmás? Respondé *sí*, *dale*, etc. o *cancelar* para cancelar."
        )
