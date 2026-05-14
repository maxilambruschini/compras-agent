"""ExtractionService — GPT-4o vision extraction service.

System prompt calibrated in Plan 02; further refined in Plan 03's calibration loop.

Citations:
- D-01: Confidence formula — non_null(tipo, numero, proveedor, fecha) / 4
- D-03: Status thresholds — score >= threshold → 'auto_saved' else 'pending_review'
- D-04: ExtractionService.extract(image_bytes, filename) -> ExtractionResult interface
- D-10: Initial prompt minimal — calibrate iteratively in Plan 03
- T-02-02: OpenAI API key NEVER logged — AsyncOpenAI client holds it; service never logs it
"""
from __future__ import annotations

import base64
import os
import uuid
from typing import Optional, Tuple

import structlog
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.config import Settings
from app.models.extraction import ExtractedInvoice
from app.services.storage import StorageBackend

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# System prompt (module-level constant — Plan 03's calibration script reads and
# may propose edits to this value; ExtractionService references SYSTEM_PROMPT
# directly so the calibration loop can mutate this constant only without
# touching ExtractionService internals).
# ---------------------------------------------------------------------------

SYSTEM_PROMPT: str = (
    "You are extracting structured data from photographs of Argentine purchase documents "
    "(Factura A, Factura B, Factura C, Remito, Lista informal). "
    "Extract every visible field into the provided schema. "
    "Use null (not empty string, not a guess) whenever a field is not clearly visible "
    "or not present on the document.\n\n"
    "FIELD RULES:\n"
    "- tipo_comprobante: one of FACTURA_A, FACTURA_B, FACTURA_C, REMITO, LISTA_INFORMAL, UNKNOWN. "
    "REMITO = delivery note (shows items delivered, may say 'no válido como factura'). "
    "LISTA_INFORMAL = informal price list without AFIP structure (no numbered items to deliver). "
    "A document with delivery quantities per product row is REMITO, not LISTA_INFORMAL.\n"
    "- fecha, fecha_vencimiento_cae: ISO 8601 YYYY-MM-DD only (e.g. 2026-01-07). Never DD/MM/YYYY.\n"
    "- cuit_proveedor: format XX-XXXXXXXX-X with hyphens. Extract the SELLER's CUIT, not the buyer's.\n"
    "- cae: numeric string exactly as printed, no spaces.\n"
    "- proveedor: the SELLER/SUPPLIER company name as printed on the document header. "
    "The supplier is who ISSUED the document. The buyer/recipient/delivery address is NOT the proveedor. "
    "On a remito, the recipient (e.g. 'VICO LA BOCA', 'A:', 'Para:') is the BUYER — use null for proveedor if only the buyer is visible.\n"
    "NUMBER FORMAT — Argentine invoices use period (.) as thousands separator and comma (,) as "
    "decimal separator. Always convert to standard decimal notation before outputting: "
    "remove all thousands separators, replace the decimal comma with a period "
    "(e.g. $107.156,13 → 107156.13; $1.234.567,89 → 1234567.89; $1.500 → 1500).\n"
    "- unidades_por_bulto: numeric count of units per box/bundle (e.g. 6, 12). "
    "If the column shows a unit-of-measure label like UNI, UN, KG, use null.\n"
    "- iva_rate: IVA percentage as a number (e.g. 21.0 for 21%). "
    "Extract from the line item's IVA column if shown; null if not shown.\n"
    "- Line items: one entry per product row visible; never invent rows.\n"
)


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class ExtractionError(Exception):
    """Base class for extraction failures."""


class ExtractionRefusalError(ExtractionError):
    """GPT-4o refused to process the image (message.refusal is set)."""


class ExtractionFailedError(ExtractionError):
    """GPT-4o returned no parsed content and no refusal, or another error occurred."""


# ---------------------------------------------------------------------------
# Return type DTO
# ---------------------------------------------------------------------------


class ExtractionResult(BaseModel):
    """Structured output of ExtractionService.extract().

    Serializes directly to JSON for the debug endpoint (D-06).
    Plan 03 extends this for DB persistence.
    """

    invoice: ExtractedInvoice
    confidence_score: float  # 0.0..1.0 per D-01
    status: str  # "auto_saved" | "pending_review" per D-03
    image_path: str  # relative path returned by StorageBackend.save


# ---------------------------------------------------------------------------
# Pure helpers (module-level, importable for testing)
# ---------------------------------------------------------------------------


def compute_confidence(invoice: ExtractedInvoice) -> float:
    """Confidence score = proportion of the four critical header fields that are non-null.

    Critical fields (D-01): tipo_comprobante, numero_documento, proveedor, fecha.
    Range: 0.0 (all None) to 1.0 (all present).
    """
    critical = [
        invoice.tipo_comprobante,
        invoice.numero_documento,
        invoice.proveedor,
        invoice.fecha,
    ]
    return sum(1.0 for f in critical if f is not None) / 4.0


def assign_status(score: float, threshold: float) -> str:
    """Assign extraction status based on confidence score vs threshold (D-03).

    Returns 'auto_saved' when score >= threshold, else 'pending_review'.
    Invoice is always saved — never rejected based on confidence alone.
    """
    return "auto_saved" if score >= threshold else "pending_review"


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------


class ExtractionService:
    """GPT-4o vision extraction service.

    Constructor injection: caller provides openai_client, storage, and settings.
    This ensures the service is testable without live API calls — tests inject a
    MagicMock openai_client via app.dependency_overrides[get_extraction_service].

    AsyncOpenAI client is constructed in the router's get_extraction_service()
    dependency (the SOLE construction site) — never at module import time (Pitfall 3).

    The module-level SYSTEM_PROMPT constant is used by _call_gpt4o; Plan 03's
    calibration script may edit its value without touching ExtractionService.
    """

    def __init__(
        self,
        openai_client: AsyncOpenAI,
        storage: StorageBackend,
        settings: Settings,
    ) -> None:
        self._client = openai_client
        self._storage = storage
        self._settings = settings
        self._log = structlog.get_logger()  # lazy proxy; bind at call time (Pattern 6)

    async def _call_gpt4o(
        self, image_bytes: bytes
    ) -> Tuple[Optional[ExtractedInvoice], Optional[str]]:
        """Call GPT-4o with the invoice image. Returns (parsed_invoice, refusal_reason).

        Exactly one of (parsed, refusal) will be non-None on a well-formed response.
        Check refusal BEFORE accessing parsed (Pitfall 2).

        Uses module-level SYSTEM_PROMPT — Plan 03's calibration loop edits that
        constant without touching this method.
        """
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        # NOTE: MIME type hardcoded as image/jpeg. OpenAI vision accepts PNG/JPEG bytes
        # labeled as image/jpeg in practice (verified against fixtures in Plan 03). A
        # follow-up may wire detect_media_type() from scripts/calibrate_prompt.py — see
        # RESEARCH.md open question #1. (Addresses review MEDIUM #5.)
        try:
            completion = await self._client.chat.completions.parse(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Extract all invoice fields from this image.",
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                            },
                        ],
                    },
                ],
                response_format=ExtractedInvoice,
            )
        except Exception as exc:
            # Network errors, AuthenticationError, etc. — never log secrets (T-02-02)
            log.error("extraction.failed", error=str(exc), stage="openai_parse")
            raise ExtractionFailedError(f"openai parse failed: {exc}") from exc
        msg = completion.choices[0].message
        return (msg.parsed, msg.refusal)

    async def extract(self, image_bytes: bytes, filename: str) -> ExtractionResult:
        """Extract invoice data from image bytes.

        Steps (per 02-01-PLAN.md interfaces):
        1. Generate invoice UUID for storage namespacing (D-09).
        2. Sanitize filename to basename only (path-traversal defense at service layer).
        3. Save raw image via StorageBackend — write-receipt only in Phase 2.
        4. Call GPT-4o; check refusal; raise ExtractionRefusalError if refused.
        5. Raise ExtractionFailedError if parsed is None (should not happen on non-refusal).
        6. Compute confidence score (D-01) and assign status (D-03).
        7. Return ExtractionResult.

        Logging (VAL-05): filename is bound in structlog context so failures are
        traceable. API keys are NEVER logged (T-02-02).
        """
        # Bind filename at call time — not in __init__ (Pattern 6 / Pitfall 7)
        log = self._log.bind(filename=os.path.basename(filename))
        log.info("extraction.start")

        try:
            # Step 1-3: store the image before extraction
            invoice_uuid = str(uuid.uuid4())
            safe_basename = os.path.basename(filename)
            try:
                relative_path = self._storage.save(
                    image_bytes, f"{invoice_uuid}/{safe_basename}"
                )
            except ValueError as exc:
                log.error("extraction.failed", error=str(exc), stage="storage_save")
                raise ExtractionFailedError(f"storage rejected filename: {exc}") from exc

            # Step 4: call GPT-4o
            parsed, refusal = await self._call_gpt4o(image_bytes)

            if refusal is not None:
                log.error("extraction.failed", error="refusal", refusal=refusal)
                raise ExtractionRefusalError(refusal)

            if parsed is None:
                log.error("extraction.failed", error="parsed_none")
                raise ExtractionFailedError(
                    "GPT-4o returned no parsed content and no refusal"
                )

            # Step 6: confidence + status
            score = compute_confidence(parsed)
            status = assign_status(score, self._settings.confidence_threshold)

            log.info(
                "extraction.complete",
                confidence=score,
                status=status,
                image_path=relative_path,
            )
            return ExtractionResult(
                invoice=parsed,
                confidence_score=score,
                status=status,
                image_path=relative_path,
            )

        except ExtractionError:
            # Re-raise ExtractionRefusalError / ExtractionFailedError as-is
            raise
        except Exception as exc:
            # Unexpected error — log with context but NEVER include secrets (T-02-02)
            log.error("extraction.failed", error=str(exc))
            raise ExtractionFailedError(str(exc)) from exc
