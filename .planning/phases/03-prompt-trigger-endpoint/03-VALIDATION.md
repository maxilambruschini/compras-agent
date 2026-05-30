---
phase: 3
slug: prompt-trigger-endpoint
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-30
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `03-RESEARCH.md` §Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio (`asyncio_mode = "auto"`) |
| **Config file** | `backend/pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `cd backend && python -m pytest tests/test_prompt_trigger.py tests/test_conversation_cierre.py -x -q` |
| **Full suite command** | `cd backend && python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~20 seconds (quick) / ~60 seconds (full) |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && python -m pytest tests/test_prompt_trigger.py tests/test_conversation_cierre.py -x -q`
- **After every plan wave:** Run `cd backend && python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | 01 | 1 | TRIG-01 | T-03-A1 | Valid token → 200 + send | unit | `pytest tests/test_prompt_trigger.py::test_valid_token_sends -x` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | TRIG-01 | T-03-A1 | Missing token → 401, no send | unit | `pytest tests/test_prompt_trigger.py::test_missing_token_401 -x` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | TRIG-01 | T-03-A1 | Wrong token → 401, no send | unit | `pytest tests/test_prompt_trigger.py::test_wrong_token_401 -x` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | TRIG-01 | T-03-A2 | Empty configured token denies all (fail-closed) | unit | `pytest tests/test_prompt_trigger.py::test_empty_configured_token_denies -x` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | TRIG-01 | — | Non-idle recipient → 200 skipped | unit | `pytest tests/test_prompt_trigger.py::test_active_conversation_skipped -x` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | TRIG-01 | T-03-R1 | Successful send sets AWAITING_CIERRE | unit | `pytest tests/test_prompt_trigger.py::test_state_set_to_awaiting_cierre -x` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | TRIG-01 | T-03-R1 | Row lock issued in trigger endpoint | unit | `pytest tests/test_prompt_trigger.py::test_row_lock_issued -x` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | TRIG-02 | — | Prompt text reaches provider.send_message | unit | `pytest tests/test_prompt_trigger.py::test_prompt_text_sent -x` | ❌ W0 | ⬜ pending |
| TBD | 02 | 2 | CAJA-01 | — | Bare amount in AWAITING_CIERRE → confirm | unit | `pytest tests/test_conversation_cierre.py::test_bare_amount_advances_to_confirm -x` | ❌ W0 | ⬜ pending |
| TBD | 02 | 2 | CAJA-01 | — | Gasto intent in AWAITING_CIERRE → gasto flow | unit | `pytest tests/test_conversation_cierre.py::test_gasto_intent_handoff -x` | ❌ W0 | ⬜ pending |
| TBD | 02 | 2 | CAJA-01 | — | Confirm → CajaCierre row written | unit | `pytest tests/test_conversation_cierre.py::test_confirm_saves_cierre -x` | ❌ W0 | ⬜ pending |
| TBD | 02 | 2 | CAJA-01 | — | Confirm gate: exact affirmative token only | unit | `pytest tests/test_conversation_cierre.py::test_confirm_requires_exact_token -x` | ❌ W0 | ⬜ pending |
| TBD | 02 | 2 | CAJA-02 | — | hora_cierre = "12:00" before 14:30 ART | unit | `pytest tests/test_conversation_cierre.py::test_hora_cierre_morning -x` | ❌ W0 | ⬜ pending |
| TBD | 02 | 2 | CAJA-02 | — | hora_cierre = "17:00" at/after 14:30 ART | unit | `pytest tests/test_conversation_cierre.py::test_hora_cierre_afternoon -x` | ❌ W0 | ⬜ pending |
| TBD | 02 | 2 | CAJA-02 | — | fecha is today() in ART, not UTC | unit | `pytest tests/test_conversation_cierre.py::test_fecha_art_not_utc -x` | ❌ W0 | ⬜ pending |
| TBD | 02 | 2 | CAJA-01 | — | Duplicate CajaCierre inserts allowed (no unique constraint) | unit | `pytest tests/test_conversation_cierre.py::test_duplicate_cierres_allowed -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky. Task IDs finalized by the planner.*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_prompt_trigger.py` — stubs for TRIG-01, TRIG-02, auth edge cases, row lock
- [ ] `backend/tests/test_conversation_cierre.py` — stubs for CAJA-01, CAJA-02, FSM transitions, duplicate insert
- [ ] `backend/tests/conftest.py` — add `mp.setenv("GASTOS_PROMPT_TOKEN", "test-prompt-token")` to the existing `env_setup` session fixture
- [ ] `backend/app/services/cierre.py` — skeleton (class with `pass` methods) so test imports resolve at collection time

**Existing test infrastructure is sufficient** — `db_session`, `async_engine`, `_make_session_factory`, `env_setup`, `_make_session_local_mock`, `make_mock_provider` reused verbatim.

**hora_cierre test strategy:** patch the module-level `datetime` in `app.services.cierre` to freeze ART time (e.g. `datetime(2026, 5, 30, 11, 0, tzinfo=ART)` for morning, `14, 30` for the boundary).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end Twilio sandbox: POST triggers a real WhatsApp prompt, manager replies, CajaCierre lands | TRIG-01/02, CAJA-01/02 | Requires live Twilio sandbox + a phone with the 24h CS window open | Open sandbox, ensure recipient messaged the bot, `curl -X POST /gastos/prompt` with Bearer token + phone, confirm prompt arrives, reply with an amount, confirm, check `caja_cierres` row |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
