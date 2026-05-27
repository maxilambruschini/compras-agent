---
phase: 1
slug: foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-13
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio |
| **Config file** | `backend/pyproject.toml` — Wave 0 installs |
| **Quick run command** | `pytest backend/tests/ -x -q` |
| **Full suite command** | `pytest backend/tests/ -v` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest backend/tests/ -x -q`
- **After every plan wave:** Run `pytest backend/tests/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-config | config | 1 | INF-03 | — | ValidationError on missing env var | unit | `pytest backend/tests/test_config.py -x -q` | ❌ W0 | ⬜ pending |
| 01-db-models | db | 1 | INF-01 | — | SenderAllowlist table created by migration | smoke | `pytest backend/tests/test_db.py -x -q` | ❌ W0 | ⬜ pending |
| 01-extraction-models | models | 1 | EXT-06 | — | All-None instantiation succeeds | unit | `pytest backend/tests/test_extraction_models.py -x -q` | ❌ W0 | ⬜ pending |
| 01-health | health | 2 | INF-01 | — | GET /health returns 200 + allowlist_count | integration | `pytest backend/tests/test_health.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/__init__.py` — package marker
- [ ] `backend/tests/conftest.py` — async engine fixture (test DB or SQLite+aiosqlite)
- [ ] `backend/tests/test_config.py` — covers INF-03 (missing env var raises ValidationError)
- [ ] `backend/tests/test_db.py` — covers INF-01 (allowlist table exists + CRUD)
- [ ] `backend/tests/test_health.py` — covers walking skeleton (GET /health returns 200)
- [ ] `backend/tests/test_extraction_models.py` — covers Pydantic model contract (all-None, UNKNOWN enum)
- [ ] `backend/pyproject.toml` — pytest config with `asyncio_mode = "auto"`
- [ ] Framework install: `pytest pytest-asyncio aiosqlite httpx` in requirements.txt

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `docker compose up` starts all 3 containers without errors | Phase 1 SC-1 | Requires Docker daemon; integration with container runtime | Run `docker compose up`, verify FastAPI on :8000, Vite on :5173, Postgres on :5432 all respond |
| Alembic migrations create all tables on fresh DB | Phase 1 SC-2 | Requires live Postgres container | `docker compose down -v && docker compose up`; connect to DB and run `\dt` — should see invoices, invoice_line_items, sender_allowlist |
| `.env` missing causes app startup failure | INF-03 | Requires container restart | Remove `.env`, run `docker compose up backend`, verify non-zero exit code |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
