---
phase: 1
reviewers: [codex]
reviewed_at: 2026-05-27T17:21:00-03:00
plans_reviewed: [01-01-PLAN.md, 01-02-PLAN.md, 01-03-PLAN.md, 01-04-PLAN.md]
convergence_cycle: 3
---

# Cross-AI Plan Review — Phase 1: Data + Conversation Core (Convergence Cycle 3)

This is convergence cycle 3. The plans were revised to address the single cycle-2 HIGH — the missing-row concurrency gap for brand-new senders. The fix: a get-or-create (`pg_insert(...).on_conflict_do_nothing(index_elements=["sender_phone"])`) materializes the `conversations` row race-safely BEFORE the locking `SELECT ... FOR NO KEY UPDATE`. The review below judges whether that HIGH is genuinely resolved and surfaces any new high-severity issues.

## Codex Review

**Summary**

The cycle-2 HIGH is **genuinely resolved at the plan/design level**. The revised entry sequence — `INSERT ... ON CONFLICT DO NOTHING` before `SELECT ... FOR NO KEY UPDATE` — is the correct fix for the missing-row path. It changes the first-message case from "two transactions both see no row, then race on a bare insert" to "both converge on one materialized row, then serialize on the row lock." The deferred live cross-session PostgreSQL proof is now named as a concrete artifact, which is acceptable at the plan level provided verify-phase actually runs it.

**Per-HIGH Verdict — Cycle-2 missing-row concurrency gap: RESOLVED**

The revised entry sequence is the correct PostgreSQL shape:

```text
INSERT INTO conversations (...) ON CONFLICT (sender_phone) DO NOTHING
SELECT ... FOR NO KEY UPDATE
```

Under concurrent first messages from a brand-new sender:
- One transaction inserts the row.
- The other transaction's conflicting insert no-ops instead of raising `IntegrityError`.
- Both then select the now-existing row with `FOR NO KEY UPDATE`.
- The second transaction waits behind the first row lock and reads committed state afterward.

This closes the specific cycle-2 concern for brand-new senders, including duplicate first webhooks with the same `message_id`. Caveat (not a blocker): the SQLite unit test (`test_get_or_create_first_message`) only proves idempotent convergence / no `IntegrityError`, not real cross-session lock behavior — the plan acknowledges this and names the PostgreSQL integration test (`tests/integration/test_conversation_concurrency_pg.py`, `@pytest.mark.pg_integration`, T-04-RACE) deferred to verify-phase.

**New Concerns**

- **MEDIUM: `AGENT_MODE` backward-compatibility concern remains unresolved.** 01-01 still sets `agent_mode: str = "gastos"` while mounting the invoice/WhatsApp router only when `AGENT_MODE == invoice`, yet claims "defaults keep existing invoice deployments unaffected." Those statements conflict: an existing v1.0 invoice deployment that does not set `AGENT_MODE=invoice` would silently stop mounting its router. Not a Phase 1 orchestrator-correctness issue — a rollout risk.
- **LOW: SQLite claim around `pg_insert` should be verified during implementation.** The plan asserts `pg_insert(...).on_conflict_do_nothing(...)` is unit-testable on SQLite. Likely true, but implementation should confirm the exact statement executes under the project's aiosqlite test engine; if not, use a dialect-specific insert helper (`sqlalchemy.dialects.sqlite.insert` vs `...postgresql.insert`). No change to the production strategy unless tests prove it fails.

**Cycle-2 MEDIUM/LOW status**

- **MEDIUM (`AGENT_MODE` default): UNRESOLVED** — still defaults to `"gastos"` while claiming no impact on invoice deployments. Either default to `"invoice"` for backward compat (set `"gastos"` only in demo/test envs) or document a required deployment migration.
- **LOW (deferred PG concurrency test naming): RESOLVED** — the plan now names `tests/integration/test_conversation_concurrency_pg.py`, marker `@pytest.mark.pg_integration`, with the expected assertion (two concurrent first messages → exactly one row, one serialized turn).

**Suggestions**

- Keep the get-or-create-before-lock design.
- Add an implementation test spy proving the upsert executes BEFORE the locking select (not merely that both exist).
- Resolve the `AGENT_MODE` rollout ambiguity before implementation.
- During implementation, verify `pg_insert(...).on_conflict_do_nothing(...)` executes against the SQLite test engine; if not, add a tiny dialect-specific insert helper.

**Overall Risk: LOW to MEDIUM** — The original HIGH concurrency flaw is fixed in the revised design. Remaining risk is rollout/configuration (`AGENT_MODE`) and ensuring the SQLite unit-test path matches the planned SQLAlchemy insert behavior.

---

## Consensus Summary

Single reviewer (Codex) this cycle.

### Cycle-2 HIGH — RESOLVED

The single cycle-2 HIGH (missing-row concurrency gap for new senders) is confirmed resolved. The get-or-create entry sequence — `pg_insert(...).on_conflict_do_nothing(index_elements=["sender_phone"])` followed by `SELECT ... FOR NO KEY UPDATE` — is the correct PostgreSQL idiom: the losing concurrent insert no-ops instead of raising `IntegrityError`, and both first-message transactions converge on a single row that is then serialized under the row lock. ROADMAP criterion 3 (CONV-03) now holds for new senders as well as existing ones. True cross-session insert serialization is appropriately deferred to a named, marked Postgres integration test (T-04-RACE) in verify-phase.

### New HIGH this cycle (0)

None. No new HIGH-severity issues were introduced by the revision.

### Notable lower-severity items

- **MEDIUM (carried over, UNRESOLVED):** `AGENT_MODE="gastos"` default silently disables the v1.0 invoice router unless existing deployments set `AGENT_MODE=invoice`. Resolve the rollout ambiguity (default backward-compatibly or document a deployment migration).
- **LOW (new):** Confirm `pg_insert(...).on_conflict_do_nothing(...)` compiles/executes on the aiosqlite test engine; add a dialect-specific insert helper if it does not.
- **LOW (cycle-2, RESOLVED):** The deferred Postgres concurrency test is now named concretely.

### Divergent Views

None — single reviewer this cycle.
