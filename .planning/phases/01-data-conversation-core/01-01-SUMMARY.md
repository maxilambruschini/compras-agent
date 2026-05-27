---
phase: 01-data-conversation-core
plan: "01"
subsystem: backend/db
tags: [orm, alembic, config, gastos-bot, data-foundation]
dependency_graph:
  requires: []
  provides:
    - Gasto ORM model (backend/app/db/models.py)
    - Conversation ORM model (backend/app/db/models.py)
    - CajaCierre ORM model (backend/app/db/models.py)
    - Alembic migration c3d4e5f6a7b8 (conversations + gastos + caja_cierres tables)
    - agent_mode + conversation_timeout_hours config settings
    - Conditional invoice router seam in main.py (D-09)
    - AGENT_MODE env wiring in conftest.py
  affects:
    - backend/app/db/models.py (extended)
    - backend/app/config.py (extended)
    - backend/app/main.py (modified: conditional router)
    - backend/tests/conftest.py (env_setup extended)
tech_stack:
  added: []
  patterns:
    - SQLAlchemy 2.0 typed mapping (Mapped/mapped_column) extended with three new models
    - dialect-agnostic sqlalchemy.Uuid for aiosqlite test parity
    - server_default=func.now() + onupdate=func.now() for D-08 timeout anchor
    - Pydantic Settings optional-with-defaults pattern for agent_mode/conversation_timeout_hours
    - Conditional router registration on agent_mode (D-09 demo isolation seam)
key_files:
  created:
    - path: backend/alembic/versions/c3d4e5f6a7b8_add_gastos_tables.py
      purpose: Single reversible migration creating conversations, gastos, caja_cierres tables; down_revision=b1c2d3e4f5a6
    - path: backend/tests/test_gastos_models.py
      purpose: 4 async smoke tests proving CONV-01 persistence round-trips for all three models
  modified:
    - path: backend/app/db/models.py
      change: Added Conversation, Gasto, CajaCierre ORM classes
    - path: backend/app/config.py
      change: Added agent_mode (default "gastos") and conversation_timeout_hours (default 4)
    - path: backend/app/main.py
      change: Whatsapp router now registered only when agent_mode=="invoice" (D-09 seam)
    - path: backend/tests/conftest.py
      change: env_setup sets AGENT_MODE=gastos before get_settings.cache_clear()
decisions:
  - CajaCierre created in Phase 1 alongside gastos/conversations — one migration, no schema debt, no Phase 2 hard dependency
  - RLS intentionally deferred (review concern 5): no policies + non-owner app role = prod default-deny; single-company v1 has no per-row tenancy; tracked for a hardening phase
  - Gasto.monto uses Numeric(14,2) (ARS pesos, 2dp sufficient for salida); RESEARCH Pattern 4 used Numeric(14,4) for line items but the plan spec says 14,2 for gastos
  - No lugar/proveedor/entrada/category on Gasto per D-01 — enforced by smoke test assertion
metrics:
  duration: "~8 minutes"
  completed: "2026-05-27"
  tasks_completed: 3
  tasks_total: 3
  files_created: 2
  files_modified: 4
---

# Phase 01 Plan 01: Data Foundation (ORM Models, Migration, Config) Summary

**One-liner:** Three dialect-agnostic ORM models (Conversation, Gasto, CajaCierre) with single reversible Alembic migration, AGENT_MODE/CONVERSATION_TIMEOUT_HOURS config, and conditional invoice-router seam as the D-09 demo isolation gate.

## What Was Built

### Task 1 — Gasto, Conversation, CajaCierre ORM models

Three new classes appended to `backend/app/db/models.py`, all subclassing the existing `Base` (not a new one):

- **Conversation** (`conversations`): `sender_phone` String(30) PK, `state` String(30) not null default "idle", `draft_gasto` Text nullable (JSON dump of DraftGasto), `last_message_id` String(100) nullable (CONV-02 idempotency key), `updated_at` DateTime(timezone=True) with both `server_default=func.now()` AND `onupdate=func.now()` (the D-08 timeout anchor). Index on sender_phone.

- **Gasto** (`gastos`): `id` Uuid PK, `fecha` Date not null, `concepto` Text not null, `monto` Numeric(14,2) not null, `ticket_image_path` Text nullable, `sender_phone` String(30) not null, `created_at` DateTime. D-01 compliance: no lugar/proveedor/entrada/category columns. Indexes ix_gastos_fecha and ix_gastos_sender_phone.

- **CajaCierre** (`caja_cierres`): `id` Uuid PK, `fecha` Date not null, `hora_cierre` String(5) not null, `efectivo_en_caja` Numeric(14,2) not null, `sender_phone` String(30) not null, `created_at` DateTime. Index ix_caja_cierres_fecha.

All UUID columns use `sqlalchemy.Uuid` (dialect-agnostic) for aiosqlite test compatibility.

### Task 2 — Config settings + conditional router + conftest env

- **config.py**: `agent_mode: str = "gastos"` and `conversation_timeout_hours: int = 4` added to the optional-with-defaults block. No validator — defaults keep existing invoice deployments unaffected when not set.
- **main.py**: Invoice/whatsapp router registration wrapped in `if settings.agent_mode == "invoice":`. Comment marks the Phase 2 gastos webhook seam. T-01-04 threat mitigation documented in code: agent_mode read once at app construction, no runtime flip path, default "gastos" fails closed.
- **conftest.py**: `mp.setenv("AGENT_MODE", "gastos")` added to env_setup before `get_settings.cache_clear()` (Pitfall G prevention).

### Task 3 — Alembic migration + models smoke test

- **Migration c3d4e5f6a7b8**: `down_revision = 'b1c2d3e4f5a6'` (linear chain). Creates all three tables with columns matching models.py exactly. Creates all four indexes. `downgrade()` drops indexes then tables in reverse order. RLS intentionally omitted per review concern 5 (comment included).
- **test_gastos_models.py**: 4 async pytest tests using the conftest `db_session` fixture: round-trip for Conversation, round-trip for Gasto (asserts D-01 field compliance — no lugar/proveedor/entrada/category), round-trip for CajaCierre, multiple gastos per sender.

## Deviations from Plan

None — plan executed exactly as written.

The one note: RESEARCH Pattern 4 shows `Numeric(14, 4)` for money (matching line items), but the PLAN spec explicitly says `Numeric(14, 2)` for gastos (ARS pesos — 2 decimal places is correct for peso amounts). Used 14,2 per the plan spec. This is consistent with the plan's acceptance criteria.

## Test Results

```
6 passed in 0.09s  (tests/test_gastos_models.py + tests/test_config.py)
```

## Known Stubs

None — this plan creates data models only. No UI rendering, no data wiring.

## Threat Flags

T-01-04 (Elevation of Privilege, AGENT_MODE) — mitigated: agent_mode gated at `create_app()` construction; no runtime flip; default "gastos" fails closed. Documented in code comment.

T-01-RLS (Information Disclosure, new tables) — deferred: RLS with zero policies causes Postgres default-deny for non-owner app role. Single-company v1, no per-row tenancy benefit. Migration comment documents deferral. Tracked for a hardening phase: ENABLE RLS + explicit per-role policies + Postgres app-role integration test.

## Self-Check: PASSED

| Item | Status |
|------|--------|
| backend/app/db/models.py | FOUND |
| backend/alembic/versions/c3d4e5f6a7b8_add_gastos_tables.py | FOUND |
| backend/tests/test_gastos_models.py | FOUND |
| .planning/phases/01-data-conversation-core/01-01-SUMMARY.md | FOUND |
| Commit 6d021d7 (Task 1 ORM models) | FOUND |
| Commit 01be034 (Task 2 config + main + conftest) | FOUND |
| Commit ae389f4 (Task 3 migration + smoke test) | FOUND |
| Alembic head: single linear (c3d4e5f6a7b8) | PASSED |
| 6 tests pass (test_gastos_models + test_config) | PASSED |
