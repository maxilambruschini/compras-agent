---
phase: 1
reviewers: [codex]
reviewed_at: 2026-05-27T17:14:00-03:00
plans_reviewed: [01-01-PLAN.md, 01-02-PLAN.md, 01-03-PLAN.md, 01-04-PLAN.md]
convergence_cycle: 2
---

# Cross-AI Plan Review — Phase 1: Data + Conversation Core (Convergence Cycle 2)

This is convergence cycle 2. The plans were revised to address the 5 HIGH concerns from cycle 1. The review below judges whether each prior HIGH is genuinely resolved and surfaces any new high-severity issues introduced by the revisions.

## Codex Review

**Summary**

The revisions resolve the 5 cycle-1 HIGH concerns as written. Codex independently checked SQLAlchemy locally: `sqlalchemy==2.0.49`, and `with_for_update(key_share=True)` compiles to `FOR NO KEY UPDATE` for PostgreSQL — confirming the cycle-1 claim that this emits `FOR KEY SHARE` was empirically wrong.

However, one NEW HIGH was found: row locking does not serialize concurrent first messages for a sender when the `Conversation` row does not yet exist.

**Per-HIGH Verdict (cycle-1 concerns)**

1. **Wave/dependency mismatch: RESOLVED** — All four plans now state the strict sequence `01-01 → 01-02 → 01-03 → 01-04`, and `01-03` correctly depends on `01-02`.
2. **`key_share=True` lock strength: RESOLVED** — Verified locally against SQLAlchemy 2.0.49: `with_for_update(key_share=True)` emits `FOR NO KEY UPDATE`; the new compiled-SQL contract test (Task 0, test_conversation_lock_sql.py) is the right guard against version drift.
3. **Row-lock test did not prove serialization: RESOLVED** — The plan no longer overclaims SQLite proof; it pins the PostgreSQL SQL mode at the compiled-string level and explicitly defers true cross-session PostgreSQL concurrency verification to verify-phase.
4. **Idempotency failure model unspecified: RESOLVED** — The plan now clearly defines atomic DB mutation rollback (last_message_id reverts), post-commit provider send, retry/reprocessable behavior, and tests both DB rollback (test_idempotency_rollback_on_db_failure) and provider-send failure (test_provider_send_failure_after_commit).
5. **RLS default-deny: RESOLVED** — RLS removed from the Phase 1 migration, with a deferral comment and threat-register entry (T-01-RLS) explaining why no-policy RLS would break production for a non-owner app role.

Timeout-ordering MEDIUM (snapshot `updated_at` before mutation): addressed via the pre-load snapshot + test_timeout_uses_preload_snapshot.

**New Concerns**

- **HIGH: `SELECT ... FOR NO KEY UPDATE` does not protect the "missing row" path.** In 01-04, step 1 selects the `Conversation` row with `FOR NO KEY UPDATE`, then creates and flushes if none exists. If two first messages for the same sender arrive concurrently and no row exists yet, neither transaction locks anything (there is no row to lock). Both can attempt the insert; one hits a primary-key race / IntegrityError instead of being cleanly serialized. This leaves ROADMAP criterion 3 incomplete for **new** senders (first-ever message).

- **MEDIUM: `AGENT_MODE` default may disable existing invoice deployments.** 01-01 sets `agent_mode` default to `"gastos"` while also claiming defaults keep existing invoice deployments unaffected. Unless existing invoice deployments explicitly set `AGENT_MODE=invoice`, the WhatsApp invoice router stops mounting — a behavior change for the v1.0 deployment.

- **LOW: deferred PostgreSQL concurrency test not concretely specified.** The plan defers true cross-session serialization to verify-phase but does not name the exact test artifact/marker and expected behavior.

**Suggestions**

- Add a first-row concurrency strategy to 01-04: an INSERT ... ON CONFLICT DO NOTHING / get-or-create, or catch `IntegrityError` → rollback → re-select with `FOR NO KEY UPDATE` (then the existing row is lockable). Cover it with a two-concurrent-first-messages PostgreSQL test in verify-phase.
- Clarify `AGENT_MODE` rollout: either document that invoice deployments must set `AGENT_MODE=invoice`, or pick a backward-compatible default and set `"gastos"` only in demo/test envs.

**Overall Risk: MEDIUM** — The prior HIGHs are resolved, but the missing-row concurrency gap should be addressed before claiming CONV-03 (criterion 3) is fully satisfied for all senders.

---

## Consensus Summary

Single reviewer (Codex) this cycle.

### Cycle-1 HIGHs — all 5 RESOLVED

All 5 cycle-1 HIGH concerns are confirmed resolved. Notably, Codex independently verified against SQLAlchemy 2.0.49 that `with_for_update(key_share=True)` compiles to `FOR NO KEY UPDATE`, validating the replanning decision to KEEP `key_share=True` (the cycle-1 claim that it emits `FOR KEY SHARE` was empirically disproven). The new compiled-SQL contract test guards against future drift.

### New HIGH this cycle (1)

1. **Missing-row concurrency gap (CONV-03 / criterion 3).** `FOR NO KEY UPDATE` cannot lock a row that does not exist yet, so two concurrent *first* messages from the same sender are not serialized by the planned lock — they race on the `conversations` primary key insert. The row-lock serialization only protects senders whose conversation row already exists. Fix: get-or-create with INSERT ... ON CONFLICT or IntegrityError → rollback → re-select-with-lock, plus a two-concurrent-first-messages Postgres test in verify-phase.

### Notable lower-severity items

- **MEDIUM:** `AGENT_MODE="gastos"` default silently disables the v1.0 invoice router unless existing deployments set `AGENT_MODE=invoice`. Document the rollout requirement or default backward-compatibly.
- **LOW:** Name the deferred Postgres concurrency test artifact/marker explicitly.

### Divergent Views

None — single reviewer this cycle.
