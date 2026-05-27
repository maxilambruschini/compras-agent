---
phase: 1
slug: data-conversation-core
status: draft
nyquist_compliant: false
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
| (filled by planner) | | | | | | unit | `cd backend && pytest -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Test files + fixtures for the Conversation orchestrator, SlotExtractionService (mocked OpenAI), GastoService, and `parse_ars_amount()` — mirror existing `backend/tests/` patterns
- [ ] Mocked-OpenAI fixture (reuse existing pattern from extraction tests)
- [ ] aiosqlite in-memory session fixture + a spy/monkeypatch helper to assert `with_for_update(key_share=True)` on the conversation SELECT (Postgres-only lock not exercised by SQLite)

*Existing pytest infrastructure covers framework setup — no install needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| (none expected) | | Phase 1 is fully unit-testable with no WhatsApp/network | — |

*All phase behaviors have automated verification (success criterion: every state transition unit-tested with mocks).*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
