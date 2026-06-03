---
phase: 4
slug: admin-ui
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-31
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `04-RESEARCH.md` §Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio (`asyncio_mode = "auto"`) |
| **Config file** | `backend/pyproject.toml` → `[tool.pytest.ini_options]` |
| **Quick run command** | `cd backend && python -m pytest tests/test_admin.py -x -q` |
| **Full suite command** | `cd backend && python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~10s (quick) / ~60s (full) |
| **Frontend tests** | NONE — no vitest/jest/testing-library; adding a frontend toolchain is out of scope for the demo. Frontend correctness is validated by manual UAT (browser). |

---

## Sampling Rate

- **After every task commit:** `cd backend && python -m pytest tests/test_admin.py -x -q`
- **After every plan wave:** `cd backend && python -m pytest tests/ -x -q` (full suite — no regressions)
- **Before `/gsd:verify-work`:** Full backend suite green
- **Max feedback latency:** 60 seconds (backend). Frontend behaviors are manual-only.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | 01 | 0 | UI-01 | — | unit | `pytest tests/test_admin.py::test_list_gastos_empty -x` | ❌ W0 | ⬜ pending |
| TBD | 01 | 0 | UI-01 | — | unit | `pytest tests/test_admin.py::test_list_gastos_date_filter -x` | ❌ W0 | ⬜ pending |
| TBD | 01 | 0 | UI-01 | SQLi-safe ILIKE bind param | unit | `pytest tests/test_admin.py::test_list_gastos_search -x` | ❌ W0 | ⬜ pending |
| TBD | 01 | 0 | UI-01 | — | unit | `pytest tests/test_admin.py::test_get_gasto -x` | ❌ W0 | ⬜ pending |
| TBD | 01 | 0 | UI-01 | input validation | unit | `pytest tests/test_admin.py::test_get_gasto_not_found -x` | ❌ W0 | ⬜ pending |
| TBD | 01 | 0 | UI-01 | path-traversal-safe | unit | `pytest tests/test_admin.py::test_get_ticket_no_path -x` | ❌ W0 | ⬜ pending |
| TBD | 01 | 0 | UI-01 | committed-only boundary | unit | `pytest tests/test_admin.py::test_drafts_not_exposed -x` | ❌ W0 | ⬜ pending |
| TBD | 01 | 0 | UI-01 | Decimal precision | unit | `pytest tests/test_admin.py::test_decimal_serialization -x` | ❌ W0 | ⬜ pending |
| TBD | 01 | 0 | UI-02 | — | unit | `pytest tests/test_admin.py::test_list_cierres -x` | ❌ W0 | ⬜ pending |
| TBD | 01 | 0 | UI-01/02 | CORS allow_origins | unit | `pytest tests/test_admin.py::test_cors_header -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky. Task IDs finalized by the planner.*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_admin.py` — RED tests covering all UI-01 + UI-02 read-endpoint behaviors above (list, date filter, search, detail, 404, ticket-404, drafts-not-exposed, Decimal serialization, cierres list, CORS header)
- [ ] No new conftest fixtures needed — existing `db_session` + `env_setup` are sufficient

**Test fixture pattern (from `test_prompt_trigger.py`):** `httpx.AsyncClient` over `ASGITransport(app=create_app())`; seed `Gasto`/`CajaCierre` rows via `db_session.add()` + `flush()`; override `get_db`.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| GastosListPage renders the table | UI-01 | No frontend test infra | Browser → http://localhost:5173/gastos — list renders newest-first |
| Filter bar sends correct query params | UI-01 | DOM interaction | Enter date range + search text → list updates accordingly |
| GastoDetailPage shows the ticket image | UI-01 | Image load over network | Click a gasto row that has a ticket → detail page shows image inline; opens full in new tab |
| CierresListPage renders cierres (read-only) | UI-02 | No frontend test infra | Click "Cierres de Caja" tab → list renders; confirm NO edit/delete controls |
| Empty / loading / error states | UI-01/02 | Visual states | Verify spinner on load, "no records" empty state, inline error on backend down |

---

## Validation Sign-Off

- [ ] All backend tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive backend tasks without automated verify
- [ ] Wave 0 covers all MISSING references (test_admin.py)
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s (backend)
- [ ] Frontend behaviors captured as manual UAT items (above)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
