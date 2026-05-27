---
phase: 1
reviewers: [codex]
reviewed_at: 2026-05-27T17:10:00-03:00
plans_reviewed: [01-01-PLAN.md, 01-02-PLAN.md, 01-03-PLAN.md, 01-04-PLAN.md]
---

# Cross-AI Plan Review — Phase 1: Data + Conversation Core

## Codex Review

## Summary

The plans are directionally solid and cover the right architectural split: schema/config first, slot extraction, persistence, then the deterministic orchestrator. The main risk is that several success criteria are asserted by plan shape rather than actually proven, especially concurrency serialization, idempotency under failure, and timeout behavior tied to `updated_at`. I would not treat this phase as ready until the ordering ambiguity is cleaned up and the tests are strengthened around real transactional behavior rather than spies.

## Strengths

- Clear separation of responsibilities: GPT extracts slots, FSM controls transitions, service writes only after deterministic confirmation.
- Good decision to avoid WhatsApp/network dependencies in Phase 1 tests.
- Explicit Argentine amount parsing requirement is called out, including the `Decimal("1.500")` trap.
- Confirmation step correctly avoids GPT, matching D-05.
- Orchestrator owns transaction boundaries and persistence service does not commit, which is the right layering.
- Draft JSON reassignment is a good practical detail for SQLAlchemy change tracking.
- Duplicate `message_id` handling is explicitly planned.
- `AGENT_MODE` introduced early, reducing accidental invoice/gastos route overlap.

## Concerns

- **HIGH: 01-03 wave/dependency mismatch.** The prose says 01-02 and 01-03 are "Wave 2 parallel," but 01-03 imports `DraftGasto` from 01-02 and its frontmatter says `wave:3`. That is a real ordering dependency, not parallel work. Treating them as parallel risks implementation churn or incompatible DTO/service contracts.

- **HIGH: idempotency may lose messages on mid-turn failure.** 01-04 sets `last_message_id` before dispatch. If the transaction commits despite a later failure, or if sending outside the transaction fails after the DB commit, retrying the same webhook may be ignored. The exact behavior depends on where exceptions are caught and when commit happens. The plan needs an explicit failure model: DB failure should roll back `last_message_id`; provider-send failure after commit is a known at-most-once reply risk.

- **HIGH: row-lock test does not prove success criterion 3.** Spying that `with_for_update(key_share=True)` or similar was passed does not demonstrate two concurrent calls serialize, nor that stale state/write duplication is prevented. SQLite cannot validate row-lock semantics. This only proves the query was constructed with a lock hint.

- **HIGH: `key_share=True` is likely the wrong lock strength.** The requirement says `SELECT ... FOR NO KEY UPDATE`. In SQLAlchemy, that is typically `with_for_update(key_share=False, read=False, nowait=False, of=...)` or dialect-specific emitted SQL must be verified. `key_share=True` maps closer to `FOR KEY SHARE`, which is weaker and not equivalent to `FOR NO KEY UPDATE`.

- **HIGH: RLS enabled without policies may break the app.** In Postgres, enabling row-level security with no policy generally results in default-deny for affected table operations, except for table owners/superusers and depending on `FORCE ROW LEVEL SECURITY`. If the app role is not the owner or policies are absent, inserts/selects can fail in production while SQLite tests pass.

- **MEDIUM: timeout anchor is overloaded.** Using `Conversation.updated_at` for timeout while also updating `last_message_id`, state, and draft means any write refreshes the timeout. That may be intended for "time since last inbound activity," but the plan's sequence matters: if `last_message_id` is written before timeout check, it can advance `updated_at` and mask an expired conversation.

- **MEDIUM: timeout ordering appears wrong.** 01-04 says idempotency first, else set `last_message_id`, then timeout check using `updated_at`. If assigning `last_message_id` triggers `onupdate`, the previous `updated_at` may no longer represent the stale conversation. The timeout check should use the loaded row's prior timestamp before any mutation.

- **MEDIUM: amount parser is underspecified.** The basic `"1.500"` and `"1.234,56"` cases are covered, but common WhatsApp inputs like `"$1.500"`, `"ARS 1.500"`, `"1500 pesos"`, whitespace, negative values, `"-1.500"`, `"1.234.567"`, `"1,234.56"`, and malformed `"1.23.4"` need explicit expected behavior.

- **MEDIUM: `monto Optional[float]` invites precision and format issues.** The plan says float sidesteps the Decimal trap, but float introduces its own trap. `Decimal(str(float))` avoids binary artifacts but still accepts model-normalized values that may not reflect user formatting exactly. For money, prefer string extraction or validate with quantization and bounds before patching.

- **MEDIUM: confirmation correction ambiguity.** The confirm step treats affirmative match as final save, else correction. Inputs like `"sí, pero cambiá el monto a 1500"` or `"si no tiene ticket"` can be misclassified. The plan needs clear precedence: exact affirmative tokens only, not prefix/contains matching.

- **MEDIUM: success criterion 6 only mentions re-prompts for unparseable replies, but failure-count behavior must be per-step.** The plan puts this mostly in `awaiting_monto`. Concepto and ticket failure handling should be explicit if they can receive unparseable input.

- **MEDIUM: stale replay threat is named but not fully solved.** `last_message_id` dedupes only the immediately previous message. If Twilio retries an older webhook after newer messages have advanced the conversation, `last_message_id` no longer matches and the stale message can be processed. If the provider guarantees retry ordering, document it; otherwise use a processed-message table or timestamp/sequence guard.

- **LOW: `date.today()` may use server timezone.** Requirement says fecha=today for Argentine managers. If the server runs UTC, late-night Argentina messages can be assigned the wrong date. Use configured business timezone.

- **LOW: `sender_phone.strip("whatsapp:")` is incorrect.** Python `strip()` removes any of those characters from both ends, not the exact prefix. Use `removeprefix("whatsapp:")`. (Note: 01-03 actually plans `.replace("whatsapp:", "")` which is also imprecise — `removeprefix` is the correct primitive.)

- **LOW: `ConfigDict(use_enum_values=True)` appears unnecessary.** No enum is described in `GastoSlots`/`DraftGasto`. This is harmless but suggests DTOs may have been copied from another pattern.

- **LOW: CajaCierre is created in schema but not exercised by the stated success criteria.** That may be fine for future phases, but the migration/test should not imply conversation core covers cierre behavior yet.

## Suggestions

- Fix the wave plan: make 01-01 Wave 1, 01-02 Wave 2, 01-03 Wave 3, 01-04 Wave 4. Remove the "Wave 2 parallel" claim for 01-03.

- Change the lock plan to explicitly emit and test `FOR NO KEY UPDATE` on Postgres. Keep SQLite unit tests, but add either:
  - a Postgres integration test using two async sessions and synchronization barriers, or
  - a compiled SQL assertion against the Postgres dialect plus a separately marked concurrency test.

- Move timeout evaluation before mutating `last_message_id` or draft. Capture `loaded_updated_at` immediately after row load and compare against that.

- Make idempotency semantics explicit:
  - duplicate before dispatch exits;
  - exceptions inside DB transaction roll back `last_message_id`;
  - provider send happens after commit and may need an outbox/retry if reliable replies matter.

- Consider a `processed_webhook_messages` table if stale replay is in scope. `Conversation.last_message_id` only handles adjacent duplicate retries.

- Do not enable RLS in Phase 1 unless policies and app-role tests are included. If RLS must stay, add policies in the migration and run a Postgres test as the actual app role.

- Make `GastoSlots.monto` a string or constrained decimal-like string from GPT, then run the same `parse_ars_amount()` path as user text. If keeping float, add quantization and precision tests.

- Define `parse_ars_amount()` accepted grammar. At minimum test `$1.500`, `ARS 1.500`, `1.234.567`, `1500,00`, invalid mixed separators, negative values, and trailing words.

- Confirmation should use exact normalized token matching only: e.g. `si`, `sí`, `confirmo`, `ok`, `dale`. Anything with extra semantic content should be treated as correction or ambiguity, not confirmation.

- Use `removeprefix("whatsapp:")` for sender normalization.

- Use a configured Argentina timezone for `fecha`, not raw `date.today()`.

## Success Criteria Fit

1. **Mostly covered**, assuming orchestrator tests truly walk every state and verify messages/writes.
2. **Covered for immediate duplicate only**, but not stale replay.
3. **Not proven as written** because SQLite plus spy does not validate serialization.
4. **At risk** because timeout uses `updated_at` after possible mutation.
5. **Partially covered** for named examples, but parser edge cases remain weak.
6. **Partially covered**; confirm avoids GPT, but failure behavior and correction ambiguity need sharper tests.

## Risk Assessment

**Overall: MEDIUM-HIGH.** The architecture is sound, but the riskiest parts are exactly the distributed/concurrent behaviors: row locking, retries, timeout anchoring, and production Postgres RLS. These are areas where unit tests can easily pass while production behavior is wrong. Clean up the wave ordering and add a small number of Postgres-backed behavioral tests before implementation starts.

---

## Consensus Summary

Single reviewer (Codex) this cycle. The synthesis below prioritizes Codex's findings by blast radius and confidence; the HIGH items are the gating concerns before execution.

### Agreed Strengths

- Sound architectural split — deterministic FSM owns transitions and the write gate; GPT only fills an Optional slot schema (matches D-05, the core anti-hallucination guarantee).
- Correct transaction layering — orchestrator owns the commit; `GastoService` only flushes.
- Network-free Phase 1 testing strategy is appropriate for the phase boundary.
- The `Decimal("1.500")` trap is explicitly identified and blocked.

### Agreed Concerns (highest priority — the 5 HIGHs)

1. **Wave/dependency inconsistency (01-03).** Prose calls 01-02/01-03 "Wave 2 parallel" but 01-03 imports `DraftGasto` from 01-02 and frontmatter says `wave:3`. This is a genuine ordering dependency. This likely IS the "1 Blocker" the earlier plan-verification flagged. Fix: renumber waves 1→2→3→4 strictly, drop the parallel claim. (Low-effort doc fix; HIGH because it can break execution sequencing.)
2. **Lock strength mismatch — `key_share=True` ≠ FOR NO KEY UPDATE.** `with_for_update(key_share=True)` emits `FOR KEY SHARE` (a weaker shared lock), not the required `FOR NO KEY UPDATE`. Success criterion 3 names FOR NO KEY UPDATE specifically. This is a correctness bug in the planned mechanism, not just a test gap. Fix: verify the exact SQLAlchemy kwargs that compile to `FOR NO KEY UPDATE` and assert the compiled SQL against the Postgres dialect.
3. **Row-lock test does not prove serialization (criterion 3).** A spy on the lock arg + SQLite (which ignores row locks) proves the query was *constructed* with a lock, not that two concurrent calls actually serialize. Add a Postgres-backed concurrency test with two async sessions, or at minimum a compiled-SQL assertion plus a separately-marked integration test.
4. **Idempotency failure model is unspecified.** `last_message_id` is set before dispatch; the plan does not define what happens if dispatch raises after the row is mutated, or if the post-commit provider send fails. Needs an explicit model: DB-side failure rolls back `last_message_id`; post-commit send failure is an accepted at-most-once reply risk (documented).
5. **RLS enabled with no policies = likely production default-deny.** `ENABLE ROW LEVEL SECURITY` with zero policies blocks all access for non-owner roles. SQLite tests won't catch it; production inserts/selects could fail. Either add policies + an app-role Postgres test in the migration, or defer RLS out of Phase 1.

### Notable MEDIUMs worth folding into the plan

- **Timeout ordering bug:** if `last_message_id` is assigned before the timeout check, `onupdate=func.now()` may advance `updated_at` and mask an expired conversation. Capture the loaded `updated_at` immediately after row load and compare against that snapshot (affects criterion 4).
- **`monto` as float** reintroduces a precision trap; prefer GPT returning a string routed through `parse_ars_amount()`, or add quantization/bounds tests.
- **Confirm/correct ambiguity:** require exact normalized affirmative-token match (not prefix/contains) so `"sí, pero cambiá el monto"` is treated as a correction, not a save.
- **parse_ars_amount grammar underspecified:** add explicit cases for `$`/`ARS` prefixes, `1.234.567`, mixed separators, negatives, trailing words.

### Divergent Views

None — single reviewer this cycle.

### Quick Wins (low-effort, high-value)

- Renumber waves (concern 1) — pure doc edit.
- Swap `key_share=True` for the correct FOR NO KEY UPDATE kwargs (concern 2).
- `removeprefix("whatsapp:")` instead of `.replace(...)`/`.strip(...)` (LOW).
- Snapshot `updated_at` before mutation (timeout MEDIUM).
