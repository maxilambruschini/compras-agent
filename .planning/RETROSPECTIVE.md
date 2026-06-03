# Retrospective — Compras Agent

A living retrospective across milestones. Newest milestone first.

## Milestone: v2.0 — Gastos Bot

**Shipped:** 2026-06-03
**Phases:** 4 | **Plans:** 12 | **Tasks:** 20

### What Was Built
A conversational WhatsApp bot for Argentine restaurant managers to capture cash expenses
(gastos) and report twice-daily cash closings (cierres), plus a read-only admin web UI.
Phase 1 built the hybrid conversation engine (GPT-4o slot extraction + deterministic FSM,
DB-backed idempotency, per-sender lock, timeout, confirm gate). Phase 2 wired the Twilio
webhook and ticket-first gasto capture with GPT-4o vision. Phase 3 added the bearer-protected
`POST /gastos/prompt` trigger (demo scheduler stand-in) and the caja-closing FSM branch
writing `CajaCierre` with ART-derived `hora_cierre`. Phase 4 added FastAPI read endpoints +
a React 19 / Vite / React-Query / React-Router read-only UI.

### What Worked
- **TDD RED→GREEN per phase** kept the suite honest — 184 backend tests passing at close.
- **Smart-discuss → research → pattern-map → plan → plan-check** caught a real ordering bug
  (ConvState constants referenced before definition) before any code was written.
- **Adversarial code review + auto-fix loop** caught two genuine regressions: the round-2
  re-review found a `whatsapp:`-prefix send bug introduced by the WR-01 fix itself.
- **Sequential single-plan-wave execution on the milestone branch** (instead of worktrees)
  was the right call when each wave was one plan — zero merge overhead, no benefit lost.

### What Was Inefficient
- **Subagent truncation**: the pattern-mapper (Phase 4) and the verifier (Phase 4) both
  returned mid-thought without writing their files. Worked around by proceeding without
  PATTERNS.md (non-blocking) and writing VERIFICATION.md directly from gathered evidence.
- **Empty SUMMARY frontmatter**: `requirements_completed` was left `[]` across all 12
  summaries, weakening the audit's 3-source cross-reference and producing empty
  "One-liner:" accomplishments from the archival CLI (fixed by hand).
- **Stale traceability**: GASTO-03 stayed "Pending" though Phase 2 delivered it — only
  caught during the milestone audit.

### Patterns Established
- Read API mounted under `/api` prefix (Vite proxy forwards unrewritten); CORS before routers.
- Pydantic v2 serializes Decimal as a string by default — preserve precision end-to-end,
  `parseFloat` only at the display boundary.
- ART timezone via `zoneinfo`; manual ARS formatter over `Intl` for deterministic output.
- Send-after-commit ordering for any "set state then notify" endpoint (Pitfall C).

### Key Lessons
- Re-review after auto-fix is worth it: a fix can introduce a worse regression than it cures.
- When a subagent truncates, verify on the filesystem and finish the mechanical step inline
  rather than blindly re-spawning.
- Reconcile ROADMAP success criteria against the real schema during discuss — the Phase 4
  `lugar`/ticket-JSON mismatch would otherwise have failed verification.

### Cost Observations
- Model mix: planning/orchestration on Opus; researchers/executors/reviewers/checkers on Sonnet.
- Notable: the discuss → research → plan-check chain front-loaded correctness, keeping
  execution deviations small and self-correcting.

---

## Cross-Milestone Trends

| Milestone | Phases | Plans | Shipped | Notable |
|-----------|--------|-------|---------|---------|
| v1.0 MVP | 4 | 7 | 2026-05-27 | WhatsApp invoice capture + GPT-4o extraction + admin UI |
| v2.0 Gastos Bot | 4 | 12 | 2026-06-03 | Conversational gasto/cierre capture + read-only admin UI |
