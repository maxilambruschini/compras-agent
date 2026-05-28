"""TicketVisionService — Amount-only GPT-4o vision extractor for payment tickets.

Extracts only the total amount paid from a ticket/receipt image.
Reuses the ExtractionService .parse() pattern (extraction.py:159-203).

Design rules:
- D-02: Amount-only extraction — NOT the full ExtractedInvoice schema.
- T-02-01: API key NEVER logged — structlog binds only sender/message_id context.
- T-02-02: msg.refusal checked BEFORE msg.parsed (Pitfall 2). Null > hallucination.
- TicketAmount.monto is Optional[float]: GPT JSON number sidesteps Decimal("1.500") trap.
  Caller converts via Decimal(str(parsed.monto)) — never Decimal(float).
"""
from __future__ import annotations

import base64
from decimal import Decimal
from typing import Optional

import structlog
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict

from app.config import Settings
from app.services.extraction import ExtractionFailedError

# ---------------------------------------------------------------------------
# Amount-only system prompt (module-level constant, Argentine Spanish context)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT: str = (
    "Sos un asistente que extrae el monto total de tickets de pago argentinos. "
    "Mirá la imagen del ticket y devolvé únicamente el monto total pagado como número. "
    "Si el monto no se puede leer claramente, devolvé null. "
    "NUNCA inventes un monto — null es preferible a un número incorrecto.\n\n"
    "REGLAS DE FORMATO NUMÉRICO:\n"
    "Los tickets argentinos usan punto (.) como separador de miles y coma (,) como decimal. "
    "Convertí siempre al formato decimal estándar: "
    "eliminá los separadores de miles, reemplazá la coma decimal por punto "
    "(ej: $1.500 → 1500; $1.234,50 → 1234.5; $107.156,13 → 107156.13).\n"
    "Devolvé solo el monto TOTAL (el importe más alto si hay subtotal + impuestos, "
    "o el importe final marcado como 'TOTAL', 'TOTAL A PAGAR', etc.)."
)


# ---------------------------------------------------------------------------
# Pydantic model for amount-only structured output
# ---------------------------------------------------------------------------


class TicketAmount(BaseModel):
    """Amount-only structured output for ticket vision extraction.

    monto typed as Optional[float] so GPT Structured Outputs emits a JSON number.
    This sidesteps the Decimal("1.500") Argentine-separator trap (mirrors GastoSlots.monto).
    Null is preferred over hallucination — return None when unreadable.

    use_enum_values=True required for OpenAI Structured Outputs JSON Schema compliance
    (mirrors ExtractedInvoice and GastoSlots convention).
    """

    model_config = ConfigDict(use_enum_values=True)

    monto: Optional[float] = None  # JSON number; null if unreadable


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class TicketVisionService:
    """Amount-only GPT-4o vision extractor for payment ticket images.

    Constructor injection: caller provides openai_client and settings.
    No storage param — the router/orchestrator owns image storage (D-06).
    Tests inject a MagicMock openai_client without live API calls.

    AsyncOpenAI client is constructed at the call site (background task) —
    never at module import time (Pitfall 3 from extraction.py).
    """

    def __init__(
        self,
        openai_client: AsyncOpenAI,
        settings: Settings,
    ) -> None:
        self._client = openai_client
        self._settings = settings
        self._log = structlog.get_logger()  # lazy proxy; bind at call time (Pattern 6)

    async def extract_amount(self, image_bytes: bytes) -> Optional[Decimal]:
        """Extract the total amount from a ticket image.

        Returns Decimal on success, None when unreadable or refused.
        Raises ExtractionFailedError on transport/API errors (never logs the API key).

        Refusal is checked BEFORE parsed (Pitfall 2 — T-02-02).
        Conversion: Decimal(str(parsed.monto)) — never Decimal(float) directly.

        Args:
            image_bytes: Raw image bytes (JPEG or PNG).

        Returns:
            Decimal total amount, or None when unreadable/refused.

        Raises:
            ExtractionFailedError: On network errors, auth errors, or other OpenAI failures.
        """
        log = self._log.bind(service="ticket_vision")

        b64 = base64.b64encode(image_bytes).decode("utf-8")

        try:
            completion = await self._client.chat.completions.parse(
                model="gpt-4o-2024-08-06",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Extraé el monto total de este ticket.",
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                            },
                        ],
                    },
                ],
                response_format=TicketAmount,
            )
        except Exception as exc:
            # Network errors, AuthenticationError, etc. — NEVER log the API key (T-02-01)
            log.error("ticket_vision.failed", error=str(exc), stage="openai_parse")
            raise ExtractionFailedError(f"ticket vision parse failed: {exc}") from exc

        if not completion.choices:
            raise ExtractionFailedError("openai returned empty choices list")

        msg = completion.choices[0].message

        # Check refusal BEFORE parsed (Pitfall 2 / T-02-02)
        if msg.refusal is not None:
            log.warning("ticket_vision.refusal", refusal=msg.refusal)
            return None  # treat as unreadable — D-01b routes to type-the-amount fallback

        if msg.parsed is None or msg.parsed.monto is None:
            log.info("ticket_vision.unreadable")
            return None  # null > hallucination

        # Convert via Decimal(str(...)) — never Decimal(float) (T-02-02, Decimal trap)
        amount = Decimal(str(msg.parsed.monto))
        log.info("ticket_vision.success", amount=str(amount))
        return amount
