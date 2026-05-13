# Phase 2: Extraction Pipeline - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-13
**Phase:** 2-Extraction-Pipeline
**Areas discussed:** Confidence Score Formula, ExtractionService Image Input, StorageBackend Design, GPT-4o Prompt & Test Fixtures

---

## Confidence Score Formula

| Option | Description | Selected |
|--------|-------------|----------|
| Document header fields | tipo_comprobante, numero_documento, proveedor, fecha — dedup/display fields. Simpler and tied directly to business value. | ✓ |
| Header + tax fields | Also include cuit_proveedor and CAE. Present on Factura A but nullable. | |
| You decide | Leave critical field set to researcher/planner. | |

**User's choice:** Document header fields only.
**Notes:** Keeps confidence logic simple and testable. The four critical fields map directly to EXT-03.

---

| Option | Description | Selected |
|--------|-------------|----------|
| Skip for Phase 2 | Base score = proportion of non-null critical fields. No cross-field checks. | ✓ |
| Light consistency checks | tipo=FACTURA_A penalizes missing CUIT/CAE; tipo=LISTA_INFORMAL does not. | |
| You decide | Leave to researcher/planner. | |

**User's choice:** Skip cross-field consistency for Phase 2.
**Notes:** Deferred to v2 enhancement list.

---

| Option | Description | Selected |
|--------|-------------|----------|
| status=pending_review | VAL-02: save invoice, flag for human review. Already the schema default. | ✓ |
| Reject and don't save | Discard low-confidence extractions. Conflicts with audit trail requirement. | |
| You decide | Leave to planner. | |

**User's choice:** status=pending_review — always save, never reject.

---

## ExtractionService Image Input

| Option | Description | Selected |
|--------|-------------|----------|
| Bytes + filename | extract(image_bytes: bytes, filename: str). Works for tests and Phase 3 WhatsApp bytes. | ✓ |
| File path only | extract(image_path: Path). Phase 3 would need to save before calling. | |
| URL (download inside service) | Service downloads image. Couples to HTTP, hard to test. | |

**User's choice:** Bytes + filename.

---

| Option | Description | Selected |
|--------|-------------|----------|
| Pytest only | ExtractionService is a plain Python class. No HTTP endpoint in Phase 2. | |
| Add POST /extraction/test endpoint | Exposes file upload for manual curl/browser testing. | ✓ |

**User's choice:** Add POST /extraction/test endpoint.
**Notes:** User clarified it should only be available locally, not in production. Led to the debug-flag gating decision below.

---

| Option | Description | Selected |
|--------|-------------|----------|
| Full extraction result | Return ExtractedInvoice JSON + confidence_score + status. No DB write. | ✓ |
| Result + DB record ID | Run full pipeline including DB persist. | |

**User's choice:** Full extraction result only.

---

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, use settings.debug | Conditionally register router when DEBUG=true. No new env var. | ✓ |
| Add ENVIRONMENT env var | Add ENVIRONMENT=development. More explicit but adds new convention. | |

**User's choice:** Gate on existing settings.debug flag.
**Notes:** User asked whether an env var for environment already existed. settings.debug covers this case.

---

## StorageBackend Design

User asked for clarification: "What is this StorageBackend in charge of?" — Explained it's the abstraction that saves original invoice image bytes to the local filesystem, returns the path stored in invoices.image_path, and is designed so a future S3/Supabase backend can be swapped in.

| Option | Description | Selected |
|--------|-------------|----------|
| save(bytes, filename) -> str path | Single method, returns stored relative path. | ✓ |
| save + delete + exists methods | Full CRUD. delete() is Phase 4 scope. | |
| You decide | Leave to researcher/planner. | |

**User's choice:** save(bytes, filename) -> str. User confirmed the explanation made sense.

---

| Option | Description | Selected |
|--------|-------------|----------|
| Add STORAGE_PATH to Settings | Configurable via env var. Default /data/invoices. Docker volume mount. | ✓ |
| Hardcode a default | Fixed ./data/invoices path. Not configurable. | |

**User's choice:** Add STORAGE_PATH to Settings.

---

| Option | Description | Selected |
|--------|-------------|----------|
| {invoice_uuid}/{original_filename} | UUID subdirectory, original filename preserved. Collision-free. | ✓ |
| {invoice_uuid}.{ext} | Flat directory, one file per UUID. Loses original filename. | |
| You decide | Leave to researcher/planner. | |

**User's choice:** {invoice_uuid}/{original_filename}.

---

## GPT-4o Prompt & Test Fixtures

| Option | Description | Selected |
|--------|-------------|----------|
| Mock OpenAI client in tests | Fast, deterministic, no API cost. Real validation via /extraction/test endpoint. | |
| Real invoice images + live GPT-4o calls | Commits fixture images, validates true extraction. Slow, costs tokens. | |
| Both | Mock for unit tests, one @pytest.mark.integration test with real image. | ✓ |

**User's choice:** Both — mock for unit/integration tests + one live integration test with fixture image.

---

| Option | Description | Selected |
|--------|-------------|----------|
| tests/fixtures/ — commit later | Placeholder now, real image before running integration test. | |
| tests/fixtures/ — real image now | User has image ready to commit as part of Phase 2. | ✓ |

**User's choice:** Real invoice image committed as part of Phase 2 implementation.

---

| Option | Description | Selected |
|--------|-------------|----------|
| Start with explicit Argentine field instructions | System prompt lists each field with Spanish label variants. | |
| Start minimal, iterate | Minimal prompt, calibrate based on eval results. | ✓ |

**User's choice:** Start minimal — calibrate iteratively using the validation dataset.
**Notes:** User described a full eval-driven calibration loop: ground truth → extraction → diff → adjust → repeat.

---

**Ground truth model selection (free-text discussion):**

User asked which model to use for ground truth generation (better than GPT-4o to avoid circular bias). Options discussed:
- Claude Opus 4.7 — most capable multimodal model, excellent at dense printed text
- Gemini 2.5 Pro — also excellent at document OCR
- o3/o4-mini — stronger reasoning but not significantly better vision

**User's choice:** Claude Opus 4.7 (`claude-opus-4-7` via Anthropic SDK).

---

| Option | Description | Selected |
|--------|-------------|----------|
| Part of Phase 2 deliverables | calibrate_prompt.py built and run in Phase 2. Validated prompt locked before Phase 2 complete. | ✓ |
| Documented process, run manually | Build service now, calibrate after as a manual step. | |

**User's choice:** Part of Phase 2 deliverables — calibration must pass before phase is marked complete.

---

## Claude's Discretion

- Internal structure of `ExtractionResult` return type
- Whether `LocalStorageBackend` uses Protocol or ABC
- Exact system prompt text (start minimal, calibration refines it)
- Error types raised by `ExtractionService` on failure

## Deferred Ideas

- Cross-field consistency checks in confidence scoring — v2
- `StorageBackend.delete()` — Phase 4
- Full pipeline /extraction/test endpoint (with DB persistence) — Phase 3
- CUIT mod-11 validation (EXT-V2-02) — v2
- AFIP QR code decoding (EXT-V2-01) — v2
