---
phase: 3
slug: whatsapp-pipeline
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-14
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio (asyncio_mode = "auto") |
| **Config file** | `backend/pyproject.toml` |
| **Quick run command** | `cd backend && pytest tests/test_whatsapp.py -x` |
| **Full suite command** | `cd backend && pytest -m "not integration" -x` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && pytest tests/test_whatsapp.py -x`
- **After every plan wave:** Run `cd backend && pytest -m "not integration" -x`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 3-01-01 | 01 | 0 | INF-02 | T-3-01 | Valid HMAC → 200; invalid → 401 | unit | `pytest tests/test_whatsapp.py::test_valid_signature -x` | ❌ W0 | ⬜ pending |
| 3-01-02 | 01 | 0 | INF-02 | T-3-01 | Invalid signature returns HTTP 401 | unit | `pytest tests/test_whatsapp.py::test_invalid_signature -x` | ❌ W0 | ⬜ pending |
| 3-01-03 | 01 | 0 | WA-02 | — | Non-allowlisted sender receives rejection reply | unit | `pytest tests/test_whatsapp.py::test_non_allowlisted -x` | ❌ W0 | ⬜ pending |
| 3-01-04 | 01 | 0 | WA-01 | — | Allowlisted sender receives ack reply | unit | `pytest tests/test_whatsapp.py::test_allowlisted_ack -x` | ❌ W0 | ⬜ pending |
| 3-01-05 | 01 | 0 | WA-04 | — | NumMedia=0 returns error reply | unit | `pytest tests/test_whatsapp.py::test_no_media -x` | ❌ W0 | ⬜ pending |
| 3-01-06 | 01 | 0 | WA-04 | — | Unsupported content type returns error reply | unit | `pytest tests/test_whatsapp.py::test_unsupported_media_type -x` | ❌ W0 | ⬜ pending |
| 3-01-07 | 01 | 0 | VAL-01 | — | Duplicate invoice detected and not re-saved | unit | `pytest tests/test_invoice_service.py::test_duplicate_detection -x` | ❌ W0 | ⬜ pending |
| 3-01-08 | 01 | 0 | VAL-02 | — | Low confidence → status=pending_review → correct reply copy | unit | `pytest tests/test_whatsapp.py::test_pending_review_reply -x` | ❌ W0 | ⬜ pending |
| 3-01-09 | 01 | 0 | VAL-03 | — | High confidence → status=auto_saved → correct reply copy | unit | `pytest tests/test_whatsapp.py::test_auto_saved_reply -x` | ❌ W0 | ⬜ pending |
| 3-01-10 | 01 | 0 | WA-03 | — | Summary reply includes proveedor, numero, fecha, total | unit | `pytest tests/test_whatsapp.py::test_summary_format -x` | ❌ W0 | ⬜ pending |
| 3-01-11 | 01 | 1 | INF-04 | — | Webhook returns before background task completes (non-blocking) | smoke | manual + log timestamps | manual only | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_whatsapp.py` — stubs for WA-01, WA-02, WA-03, WA-04, INF-02, INF-04, VAL-02, VAL-03
- [ ] `backend/tests/test_invoice_service.py` — stubs for VAL-01 (duplicate detection + DB persist)
- [ ] `backend/tests/test_providers.py` — TwilioProvider unit tests (signature validation mock, send_message mock)

*Existing `conftest.py` with `env_setup`, `db_session`, `async_engine` fixtures can be reused directly — no conftest changes needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Webhook returns within 5 seconds | INF-04 | Timing depends on live Twilio roundtrip; not reliably automatable in unit tests | Send invoice via WhatsApp sandbox; verify ack received within 5s; check logs for `task_started` before webhook returns |
| Twilio sandbox opt-in (join keyword) | WA-01 | Operational Twilio constraint, not a code task | Each tester texts "join [keyword]" to the sandbox number before testing |
| ngrok tunnel active for signature validation | INF-02 | Runtime environment dependency | Run `ngrok http 8000`; update Twilio webhook URL in console; verify requests hit local server |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
