"""Prompt trigger endpoint — POST /gastos/prompt.

Protected outbound trigger for the cierre prompt message. A caller (demo operator
or future scheduler) sends a single HTTP request with a Bearer token and a phone number;
the endpoint authenticates the caller, acquires the per-sender row lock, checks conversation
state, sets the state to AWAITING_CIERRE (under lock), commits, then sends the prompt
message via the WhatsApp provider.

Key design decisions:
- Bearer token via HTTPBearer(auto_error=False) + secrets.compare_digest (constant-time,
  timing-safe). Fail-closed: empty GASTOS_PROMPT_TOKEN → 401 before any comparison.
- Row lock mirrors conversation.py exactly: pg_insert ON CONFLICT DO NOTHING then
  SELECT ... FOR NO KEY UPDATE (with_for_update(key_share=True)) before any state read/write.
- _safe_send is called STRICTLY AFTER the async with db.begin() block exits (Pitfall C).
  A send failure logs "gastos.reply_failed" but does NOT roll back the committed state.
- asyncio.create_task is NOT used — unlike the webhook (Twilio 5s deadline), the trigger
  caller is a human/scheduler and can await the send.
- Twilio 24h customer-service-window assumption: for the v2.0 demo, the trigger is assumed
  to fire while the manager has an open CS window (i.e., they messaged the bot recently).
  If the window is closed, _safe_send catches Twilio's 63016/63038 error and logs it;
  the endpoint still returns 200 {"status":"sent"} because the DB write committed.
  This is the accepted at-most-once send risk for the demo (Pitfall 7 from RESEARCH.md).

Security mitigations:
- T-03-A1: secrets.compare_digest constant-time compare (never == for tokens).
- T-03-A2: fail-closed guard before compare (empty configured token → deny all).
- T-03-A3: token value never logged; auth failure logs "auth.invalid_token" only.
- T-03-R1: SELECT FOR NO KEY UPDATE before state read/write (race-safe with orchestrator).
- T-03-R2: _safe_send called after commit (send-then-rollback risk eliminated).
"""
from __future__ import annotations

import secrets

import structlog
from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Conversation
from app.db.session import get_db
from app.providers.base import WhatsAppProvider
from app.routers.gastos import _safe_send, get_whatsapp_provider
from app.services.conversation import ConvState

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Bearer auth scheme (auto_error=False → credentials=None on missing header,
# not an automatic 403 — lets verify_token emit the correct 401 with our schema)
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)


def verify_token(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> None:
    """Constant-time bearer token check. Raises HTTP 401 on any failure.

    Fail-closed: if settings.gastos_prompt_token is empty, ALL requests are denied
    (prevents a misconfigured deployment from accidentally accepting any credential).
    Token value is never logged — auth failures emit "auth.invalid_token" with no value.
    """
    configured = settings.gastos_prompt_token
    if not configured:
        # Fail-closed: token not configured → deny all (T-03-A2, Pitfall 5)
        log.warning("auth.invalid_token", reason="token_not_configured")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )
    if credentials is None or credentials.scheme.lower() != "bearer":
        log.warning("auth.invalid_token", reason="missing_or_wrong_scheme")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )
    if not secrets.compare_digest(credentials.credentials, configured):
        log.warning("auth.invalid_token", reason="digest_mismatch")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------


class PromptRequest(BaseModel):
    phone_number: str

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("phone_number must not be empty")
        if len(v) > 30:
            raise ValueError("phone_number exceeds maximum length of 30 characters")
        return v


class PromptResponse(BaseModel):
    status: str
    reason: str | None = None


# ---------------------------------------------------------------------------
# Prompt text constant (TRIG-02)
# Must contain "efectivo" and "otra compra" substrings (asserted by test_prompt_text_sent).
# ---------------------------------------------------------------------------

PROMPT_TEXT = (
    "Hola! Es hora del cierre de caja.\n"
    "• ¿Tenés pagos pendientes de registrar?\n"
    "• ¿Cuánto efectivo hay en caja? (ej: *1500*)\n"
    "• ¿Hiciste otra compra hoy?\n\n"
    "Podés reportar el efectivo en caja directamente "
    "o describir un gasto para registrarlo."
)

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter()


@router.post("/gastos/prompt", response_model=PromptResponse)
async def trigger_prompt(
    body: PromptRequest,
    _: None = Security(verify_token),
    db: AsyncSession = Depends(get_db),
    provider: WhatsAppProvider = Depends(get_whatsapp_provider),
    settings: Settings = Depends(get_settings),
) -> PromptResponse:
    """Send the cierre prompt to a manager and prime conversation state to AWAITING_CIERRE.

    Flow:
    1. verify_token dependency fires before this body executes (auth gate).
    2. Acquire per-sender row lock (mirrors conversation.py exactly).
    3. Skip non-idle recipients (return 200 skipped, no send, no state change).
    4. Set state = AWAITING_CIERRE and commit.
    5. Send PROMPT_TEXT via _safe_send AFTER the transaction closes (Pitfall C).

    Twilio 24h CS window assumption: see module docstring.
    """
    # phone_number is already stripped and validated by PromptRequest.validate_phone
    clean_phone = body.phone_number
    task_log = log.bind(phone=clean_phone)

    # Use begin_nested() (SAVEPOINT) if a transaction is already active (test isolation
    # pattern: test fixtures may seed rows in the same session before the handler runs).
    # In production, get_db yields a fresh session with no active transaction, so
    # begin_nested() behaves as a regular savepoint inside the autobegun transaction — both
    # release (RELEASE SAVEPOINT) and the autobegin commit are correct in that case.
    # Under the async with block, a return statement commits the savepoint and leaves
    # the outer transaction open — which is the correct skip semantics for the test.
    async with db.begin_nested():
        # Step 1: Ensure conversation row exists — race-safe (mirrors conversation.py:222-227)
        ensure_stmt = (
            pg_insert(Conversation)
            .values(sender_phone=clean_phone, state=ConvState.IDLE)
            .on_conflict_do_nothing(index_elements=["sender_phone"])
        )
        await db.execute(ensure_stmt)

        # Step 2: Lock the now-guaranteed-to-exist row — FOR NO KEY UPDATE (mirrors conversation.py:233-238)
        result = await db.execute(
            select(Conversation)
            .where(Conversation.sender_phone == clean_phone)
            .with_for_update(key_share=True)
        )
        conv = result.scalar_one()

        # Step 3: Skip non-idle recipients — no send, no state change (TRIG-01 skip requirement)
        if conv.state != ConvState.IDLE:
            task_log.info("prompt.skipped", conv_state=conv.state)
            return PromptResponse(status="skipped", reason="active_conversation")

        # Step 4: Set state to AWAITING_CIERRE
        conv.state = ConvState.AWAITING_CIERRE
        task_log.info("prompt.state_set", new_state=ConvState.AWAITING_CIERRE)

    # Savepoint released (RELEASE SAVEPOINT) — flush the mutations to the outer transaction.
    # Then commit the outer transaction so the state is durable before we send.
    await db.commit()

    # Step 5: Send OUTSIDE the transaction (Pitfall C — send-after-commit ordering).
    # A send failure must NOT roll back the committed state.
    # Twilio requires the "whatsapp:" prefix on the recipient (providers/twilio.py); clean_phone
    # is the prefix-free DB key, so re-add the prefix for the send — mirrors the orchestrator's
    # use of the prefixed `sender` (conversation.py:311-313) rather than the stripped form.
    await _safe_send(provider, f"whatsapp:{clean_phone}", PROMPT_TEXT, task_log)
    task_log.info("prompt.sent")
    return PromptResponse(status="sent")
