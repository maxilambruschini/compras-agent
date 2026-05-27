"""SlotExtractionService — GPT-4o-mini slot extraction for free-form Spanish expense intents.

Mirrors ExtractionService in app/services/extraction.py exactly:
- Constructor injection of AsyncOpenAI + Settings (DI — never construct at import).
- async extract() calling client.chat.completions.parse() with response_format=GastoSlots.
- Refusal checked BEFORE parsed (Pitfall 2 — check refusal first).
- Exception hierarchy: SlotExtractionError (base) mirrors ExtractionError hierarchy.
- Module-level SLOT_SYSTEM_PROMPT constant (calibration script can edit without touching service).
- structlog per-call binding with text preview; never log secrets (T-02-02).

D-06: Model is gpt-4o-mini (cheaper/faster for short-text slot parsing; accuracy sufficient).
GASTO-01: Extracts concepto + monto from a free-form Spanish expense intent.
"""
from __future__ import annotations

import structlog
from openai import AsyncOpenAI

from app.config import Settings
from app.models.conversation import GastoSlots

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# System prompt (module-level constant — calibration can edit without touching service)
# ---------------------------------------------------------------------------

SLOT_SYSTEM_PROMPT: str = (
    "Eres un asistente que registra gastos en efectivo para un restaurante argentino. "
    "El usuario te envía un mensaje en español describiendo un gasto. "
    "Extraé los campos del esquema a partir del mensaje del usuario.\n\n"
    "REGLAS:\n"
    "- concepto: el artículo o descripción de lo que se compró, tal como lo dice el usuario.\n"
    "- monto: el monto pagado como número JSON. Ejemplos: '$1.500' → 1500, "
    "'mil quinientos pesos' → 1500, '$1.234,56' → 1234.56.\n"
    "- Si un campo no está claramente indicado, devolvé null. NO inventes ni supongas valores.\n"
    "- Devolvé monto como número plano (sin formato de moneda, sin puntos de miles, sin comas decimales).\n"
)


# ---------------------------------------------------------------------------
# Exception hierarchy — mirrors ExtractionError hierarchy in extraction.py
# ---------------------------------------------------------------------------


class SlotExtractionError(Exception):
    """Base class for slot extraction failures."""


class SlotExtractionRefusalError(SlotExtractionError):
    """GPT-4o-mini refused to process the text (message.refusal is set)."""


class SlotExtractionFailedError(SlotExtractionError):
    """GPT-4o-mini returned no parsed content, or a transport error occurred."""


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------


class SlotExtractionService:
    """GPT-4o-mini slot extraction service for free-form Spanish expense text.

    Constructor injection: caller provides openai_client and settings.
    This ensures the service is testable without live API calls — tests inject a
    MagicMock openai_client (mirrors ExtractionService pattern).

    AsyncOpenAI client is constructed by the router/orchestrator dependency — never
    at module import time (Pitfall 3 — testability).

    The module-level SLOT_SYSTEM_PROMPT constant is used by extract(); calibration
    scripts may edit its value without touching SlotExtractionService internals.
    """

    def __init__(
        self,
        openai_client: AsyncOpenAI,
        settings: Settings,
    ) -> None:
        self._client = openai_client
        self._settings = settings
        self._log = structlog.get_logger()  # lazy proxy; bind at call time

    async def extract(self, text: str) -> GastoSlots:
        """Extract GastoSlots from a free-form Spanish expense intent.

        Returns GastoSlots with extracted fields; None fields for slots not
        clearly stated in the text. Returns an empty GastoSlots() on refusal
        or when parsing yields None — orchestrator will re-prompt (CONV-06).

        Checks msg.refusal BEFORE msg.parsed (mirrors ExtractionService contract).
        Never logs API keys or full text beyond a preview (T-02-02).

        Args:
            text: Free-form Spanish text from the manager (e.g. "queso en supermercado $1500").

        Returns:
            GastoSlots with extracted slots; empty GastoSlots() on refusal or failure.

        Raises:
            SlotExtractionError: On transport error (network, authentication, etc.).
        """
        log = self._log.bind(text_preview=text[:50] if text else "")
        try:
            completion = await self._client.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SLOT_SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                response_format=GastoSlots,
            )
        except Exception as exc:
            # Network errors, AuthenticationError, etc. — never log secrets (T-02-02)
            log.error("slot_extraction.failed", error=str(exc), stage="openai_parse")
            raise SlotExtractionError(f"openai parse failed: {exc}") from exc

        msg = completion.choices[0].message

        # Check refusal BEFORE parsed — mirrors ExtractionService._call_gpt4o() contract
        if msg.refusal:
            log.warning("slot_extraction.refused", refusal=msg.refusal)
            return GastoSlots()  # all None — orchestrator will re-prompt

        if msg.parsed is None:
            log.warning("slot_extraction.parsed_none")
            return GastoSlots()  # all None — orchestrator will re-prompt

        log.info(
            "slot_extraction.complete",
            concepto=msg.parsed.concepto,
            monto=msg.parsed.monto,
        )
        return msg.parsed
