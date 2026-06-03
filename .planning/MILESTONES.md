# Milestones

## v2.0 Gastos Bot (Shipped: 2026-06-03)

**Phases completed:** 4 phases, 12 plans, 20 tasks

**Delivered:** A conversational WhatsApp bot for Argentine restaurant managers to capture cash expenses (gastos) and report twice-daily cash closings (cierres), with a read-only admin web UI.

**Key accomplishments:**

- Hybrid conversation engine (Phase 1): GPT-4o slot extraction + a deterministic FSM owning all transitions, with DB-backed idempotency (`last_message_id`), a per-sender `FOR NO KEY UPDATE` lock, timeout auto-reset, and a no-LLM confirm gate.
- Reactive WhatsApp gasto capture via Twilio (Phase 2): ticket-first flow with GPT-4o vision amount extraction and a "sin ticket" manual-amount fallback; fast-200 + background-task webhook.
- Bearer-protected `POST /gastos/prompt` trigger endpoint (Phase 3) as the demo stand-in for the twice-daily scheduler, plus a caja-closing FSM branch that writes `CajaCierre` rows with ART-derived `hora_cierre` (12:00/17:00) and date.
- Read-only admin UI (Phase 4): new FastAPI read endpoints (`/api/gastos` list+detail, ticket image streaming, `/api/cierres`) with CORS + path-traversal guard, and a React 19 / Vite / React-Query / React-Router frontend with three pages.
- Argentine-specific handling throughout: ARS number parsing (`1.234,56`), `America/Argentina/Buenos_Aires` timezone, Spanish UI copy, and manual ARS money formatting.
- Test discipline: TDD RED→GREEN across all phases; 184 backend tests passing (1 skipped); frontend builds + lints clean.

**Known deferred items at close:** 4 (see STATE.md Deferred Items) — live Twilio sandbox round-trip (Phase 3) and browser UI rendering (Phase 4) are documented manual UAT; advisory UI polish (UI-REVIEW 20/24); admin-endpoint auth deferred to v3 (locked demo decision); one latent `concepto=None` hardening edge case.

---

## v1.0 MVP (Shipped: 2026-05-27)

**Phases completed:** 4 phases, 7 plans, 16 tasks

**Key accomplishments:**

- INF-01:
- One-liner:
- One-liner:
- One-liner:
- One-liner:
- Race-safe invoice persistence with magic-byte validation, duplicate detection (app-level SELECT + IntegrityError re-query), and Spanish summary/duplicate/error replies isolated from reply-send failures.

---
