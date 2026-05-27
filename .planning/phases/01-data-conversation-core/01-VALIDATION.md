---
phase: 1
slug: data-conversation-core
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-05-27
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio |
| **Config file** | backend/pyproject.toml / pytest config (existing) |
| **Quick run command** | `cd backend && pytest -q` |
| **Full suite command** | `cd backend && pytest` |
| **Estimated runtime** | ~30 seconds (unit-only; no WhatsApp/network) |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && pytest -q`
- **After every plan wave:** Run `cd backend && pytest`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | CONV-01 | — | ORM models import + tables defined | unit | `cd backend && python -c "from app.db.models import Gasto, Conversation, CajaCierre"` | ❌ W0 | ⬜ pending |
| 01-01-02 | 01 | 1 | CONV-01 | T-01-AGENT | AGENT_MODE gates webhook registration; defaults correct | unit | `cd backend && pytest tests/test_config.py -q` | ❌ W0 | ⬜ pending |
| 01-01-03 | 01 | 1 | CONV-01 | T-01-RLS (deferred) | gastos/conversations/caja_cierres migrate (no RLS — deferred per review concern 5); conversation row persists | unit | `cd backend && pytest tests/test_gastos_models.py -x -q` | ❌ W0 | ⬜ pending |
| 01-02-01 | 02 | 2 | CONV-05 | T-02-AMT | `parse_ars_amount` blocks the Decimal("1.500") trap | unit | `cd backend && pytest tests/test_amounts.py -x -q` | ❌ W0 | ⬜ pending |
| 01-02-02 | 02 | 2 | GASTO-01 | T-02-INJ | slot extraction (gpt-4o-mini) returns Optional slots; refusal-checked | unit | `cd backend && pytest tests/test_slot_extraction.py -x -q` | ❌ W0 | ⬜ pending |
| 01-03-01 | 03 | 3 | GASTO-05 | T-03-PERSIST | confirmed draft → committed gastos row, orchestrator owns commit | unit | `cd backend && pytest tests/test_gasto_service.py -x -q` | ❌ W0 | ⬜ pending |
| 01-04-00 | 04 | 4 | CONV-03 | T-04-LOCK | compiled-SQL contract: `with_for_update(key_share=True)` emits `FOR NO KEY UPDATE` (postgresql dialect), not `FOR KEY SHARE`/`FOR UPDATE` | unit | `cd backend && pytest tests/test_conversation_lock_sql.py -x -q` | ❌ W0 | ⬜ pending |
| 01-04-01 | 04 | 4 | CONV-02, CONV-03, CONV-04 | T-04-IDEM / T-04-LOCK / T-04-TMO | idempotency no-op + rollback-of-last_message_id on DB failure, at-most-once post-commit send, FOR NO KEY UPDATE lock (compiled-SQL asserted), 4h timeout vs pre-mutation updated_at snapshot | unit | `cd backend && pytest tests/test_conversation.py -k "row_lock or idempotency or timeout or cancelar or rollback or send_failure or snapshot" -x -q` | ❌ W0 | ⬜ pending |
| 01-04-02 | 04 | 4 | CONV-06, GASTO-02, GASTO-04, GASTO-06 | T-04-CONFIRM | one-at-a-time slot flow, sin-ticket, deterministic confirm (no LLM), reprompt counter | unit | `cd backend && pytest tests/test_conversation.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Test files + fixtures for the Conversation orchestrator, SlotExtractionService (mocked OpenAI), GastoService, and `parse_ars_amount()` — mirror existing `backend/tests/` patterns
- [ ] Mocked-OpenAI fixture (reuse existing pattern from extraction tests)
- [ ] aiosqlite in-memory session fixture + a spy/monkeypatch helper to assert `with_for_update(key_share=True)` on the conversation SELECT, PLUS a standalone compiled-SQL contract test (`tests/test_conversation_lock_sql.py`) asserting the statement compiles to `FOR NO KEY UPDATE` under the postgresql dialect (SQLite ignores row locks, so the exact lock MODE is only verifiable via compiled SQL; true cross-session serialization is a deferred Postgres integration test)

*Existing pytest infrastructure covers framework setup — no install needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| (none expected) | | Phase 1 is fully unit-testable with no WhatsApp/network | — |

*All phase behaviors have automated verification (success criterion: every state transition unit-tested with mocks).*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (TDD: each task writes its failing test first)
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-05-27 (per-task map populated; wave_0_complete remains false — TDD fixtures created as the first step of each task during execution)
