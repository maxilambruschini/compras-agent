---
phase: 02-whatsapp-gastos-flow
plan: "02"
subsystem: webhook-router
tags: [router, webhook, twilio, d-05, d-06, d-09, fast-200, media-guard]
dependency_graph:
  requires:
    - 02-01 (ConversationOrchestrator.handle_message with ticket_image_path/ticket_amount, TicketVisionService.extract_amount)
    - 01-04 (ConversationOrchestrator, GastoService, SlotExtractionService)
    - 01-03 (LocalStorageBackend.save)
  provides:
    - /gastos/webhook (Twilio POST endpoint — signature → allowlist → fast-200 → background orchestrator dispatch)
    - process_gasto_message (background fn: MIME guard + magic-byte guard + store + vision + orchestrator)
    - AGENT_MODE=='gastos' router mount in main.py (D-09)
  affects:
    - main.py (gastos branch now live, replacing commented placeholder)
tech_stack:
  added: []
  patterns:
    - asyncio.create_task + _background_tasks strong-ref set (Pattern 4, D-05 fast-200)
    - Module-level service imports for test patching (ConversationOrchestrator, TicketVisionService, etc.)
    - Two-layer media guard: MIME type check pre-download + magic-byte check post-download (T-02-W4 / T-3-09)
    - Treat-as-no-photo on guard failure: bad bytes / unsupported MIME → orchestrator called with ticket_image_path=None
    - LocalStorageBackend.save with f"{message_sid}/{message_sid}{ext}" filename (T-02-W6 path-traversal-safe)
    - ExtractionFailedError caught in vision call → ticket_amount=None (D-01b fallback)
key_files:
  created:
    - backend/app/routers/gastos.py
    - backend/tests/test_gastos_webhook.py
  modified:
    - backend/app/main.py
decisions:
  - D-05 transport: fast-200 via asyncio.create_task; _processed_message_sids is router fast-path (not source of truth — orchestrator DB last_message_id is)
  - D-06 router-side media: gastos.py downloads, guards, stores, runs vision, feeds path+amount to handle_message
  - D-09 AGENT_MODE seam: gastos router mounts only under agent_mode=='gastos'; invoice branch untouched
  - No up-front ACK: orchestrator owns all conversational replies; webhook is pure transport
  - Module-level service class imports (not lazy inner imports) so tests can patch via patch.object/patch("app.routers.gastos.X")
metrics:
  duration: "12 minutes"
  completed: "2026-05-28"
  tasks_completed: 2
  files_changed: 3
---

# Phase 2 Plan 2: Gastos Webhook Router Summary

**One-liner:** Live /gastos/webhook Twilio router with fast-200, MIME+magic-byte guard, LocalStorageBackend ticket storage, TicketVisionService amount extraction, and ConversationOrchestrator dispatch — structural clone of v1.0 invoice webhook with gastos-specific differences.

## What Was Built

### Task 1: /gastos/webhook router (`backend/app/routers/gastos.py`)

Structural clone of `backend/app/routers/whatsapp.py`. Keeps the webhook shell (signature → dedupe → allowlist → fast-200 → background task) but dispatches into `ConversationOrchestrator.handle_message` with the D-06 media entry params.

**Key gastos-specific differences from invoice router:**
- No hard media gate: text-only messages ("sin ticket") are valid gasto conversations. `MediaUrl0` is `Optional` and the background task handles presence/absence per D-06.
- No `ACK_REPLY` sent by the webhook: the orchestrator owns all conversational replies. The webhook is pure transport.
- `process_gasto_message` background fn: two-layer guard (MIME pre-download + magic-byte post-download), `LocalStorageBackend.save(image_bytes, f"{message_sid}/{message_sid}{ext}")`, `TicketVisionService.extract_amount(image_bytes)` with `ExtractionFailedError` caught (falls back to `ticket_amount=None` for D-01b), then `orchestrator.handle_message(session_factory, sender, text, message_id, ticket_image_path, ticket_amount)`.

**Module-level imports for testability:** All service classes (`ConversationOrchestrator`, `TicketVisionService`, `LocalStorageBackend`, `SlotExtractionService`, `GastoService`) imported at module level — settings and `AsyncOpenAI` client are constructed inside the task (runtime env vars).

**Threat mitigations:**
- T-02-W1: Twilio HMAC signature → 401 before any work
- T-02-W2: `SenderAllowlist.is_active` gate before scheduling orchestrator; no DB write on rejection
- T-02-W3: `_processed_message_sids` fast-path + orchestrator DB `last_message_id` (source of truth)
- T-02-W4/T-3-09: MIME guard pre-download + magic-byte guard post-download; bad bytes never reach vision or storage
- T-02-W6: `LocalStorageBackend.save` path-traversal-safe; filename derived from `MessageSid`
- T-02-W7: `asyncio.create_task` + immediate `Response(status_code=200)` before DB/GPT work
- T-02-W8: API key never logged; `structlog` binds sender/message_sid only

**Tests (8):** invalid sig→401, non-allowlisted→NON_ALLOWLISTED_REPLY+no task, text-only allowlisted→200+task dispatched, duplicate MessageSid→no second task, fast-200 assertion (task in set before awaiting), media→download+store+vision+dispatch with path+amount, bad magic bytes→vision not called+orchestrator invoked with no-photo params, sin-ticket text-only→orchestrator with ticket_image_path=None.

### Task 2: AGENT_MODE=='gastos' router mount (`backend/app/main.py`)

Replaced the commented placeholder at lines 62-64 with a real `elif settings.agent_mode == "gastos":` branch that imports the gastos router inside `create_app()` and mounts it at `prefix="/gastos"`. Matches the invoice branch pattern (lazy import inside factory, avoids circular imports). Fail-closed behavior (unknown `agent_mode` mounts neither router) unchanged.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Module-level imports required for test patching**
- **Found during:** Task 1 GREEN phase — tests using `patch("app.routers.gastos.ConversationOrchestrator")` raised `AttributeError: module does not have attribute 'ConversationOrchestrator'`
- **Issue:** Initial implementation used lazy inner imports inside `process_gasto_message` (mirroring `process_invoice`'s pattern). `unittest.mock.patch` cannot patch a name that doesn't exist at module level at the time `patch.__enter__` resolves the target.
- **Fix:** Moved all service class imports (`ConversationOrchestrator`, `TicketVisionService`, `LocalStorageBackend`, `SlotExtractionService`, `GastoService`, `ExtractionFailedError`) to module level. Settings and `AsyncOpenAI` remain inside the task (runtime env vars).
- **Files modified:** `backend/app/routers/gastos.py`
- **Commit:** 8c7a0ab (same task commit)

**2. [Rule 1 - Bug] Background tasks hanging in tests without orchestrator mock**
- **Found during:** Task 1 GREEN phase — `test_allowlisted_text_only_dispatches_task` and related tests timed out (>30s) because the background task tried to connect to the real DB / call real OpenAI with test credentials.
- **Issue:** Initial test design checked `len(_background_tasks) == 1` without patching collaborators, so the real `process_gasto_message` ran and blocked on `get_async_session_local()`.
- **Fix:** Updated tests to patch `get_async_session_local`, `ConversationOrchestrator`, `TicketVisionService`, and `LocalStorageBackend` — same pattern as `test_whatsapp.py` process_invoice tests.
- **Files modified:** `backend/tests/test_gastos_webhook.py`
- **Commit:** 8c7a0ab (same task commit — tests updated before final commit)

## Known Stubs

None. All implemented behaviors are fully wired:
- Signature validation delegates to `provider.validate_signature` (real Twilio HMAC)
- Allowlist gate queries `SenderAllowlist` via the DB session
- `process_gasto_message` constructs all collaborators from live settings
- `ticket_image_path` and `ticket_amount` are real outputs from storage and vision, not placeholders

## Threat Surface Scan

New network endpoints introduced: `POST /gastos/webhook` — already covered by the plan's threat model (T-02-W1 through T-02-W8). All mitigations implemented and tested.

No additional threat surface beyond what the plan anticipated.

## Self-Check

All created/modified files verified:

- `backend/app/routers/gastos.py` — FOUND
- `backend/tests/test_gastos_webhook.py` — FOUND
- `backend/app/main.py` — FOUND
- `.planning/phases/02-whatsapp-gastos-flow/02-02-SUMMARY.md` — FOUND

Commits verified:
- `e22b4ad` — `test(02-02): add failing tests for gastos webhook router (TDD RED)`
- `8c7a0ab` — `feat(02-02): implement /gastos/webhook router with fast-200 + orchestrator dispatch (D-05, D-06)`
- `4069fa8` — `feat(02-02): mount gastos router under AGENT_MODE=='gastos' seam in main.py (D-09)`

Test run: `10 passed` (8 gastos_webhook + 2 health)

## Self-Check: PASSED
