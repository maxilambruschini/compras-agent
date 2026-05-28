# Phase 2: WhatsApp Gastos Flow - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-27
**Phase:** 2-whatsapp-gastos-flow
**Areas discussed:** Ticket photo handling, Caja entry/scope, hora_cierre rule, Off-topic handling, Gasto flow order

---

## Ticket photo handling

| Option | Description | Selected |
|--------|-------------|----------|
| Store image only | Download + save path, no GPT vision | |
| Store + run vision extraction | Also run GPT-4o vision and store extraction JSON | partial |

**User's choice:** Free-text — "If the user provides the ticket, then we run gpt vision to extract the amount. If not, we ask for the amount. Vision is only used to extract the amount spent."
**Notes:** Reframed the ticket step: vision is scoped to the **amount only** (not full invoice JSON), and the ticket becomes the source of the gasto `monto`. This triggered the follow-up about flow ordering.

---

## Gasto flow order (follow-up)

| Option | Description | Selected |
|--------|-------------|----------|
| Ticket-first | intent (concepto) → ticket → [photo: vision→monto] / [sin ticket: ask monto] → confirm | ✓ |
| Keep monto-first | Keep Phase 1 order; vision only as fallback | |

**User's choice:** Ticket-first.
**Notes:** Reorders the Phase 1 FSM (which asked monto before the ticket). Orchestrator states get reworked in Phase 2.

---

## Caja entry / scope

| Option | Description | Selected |
|--------|-------------|----------|
| Keyword trigger | Deterministic keyword enters caja flow | |
| GPT intent classify | Slot extractor classifies gasto vs caja vs off-topic | |
| Amount-only heuristic | Bare number → caja | |
| (follow-up) Move to Phase 3 | Build caja flow in Phase 3 with its trigger | ✓ |

**User's choice:** "lets only wait until that endpoint is in place" → confirmed moving CAJA-01/CAJA-02 and success criterion #6 from Phase 2 to Phase 3.
**Notes:** ROADMAP.md and REQUIREMENTS.md traceability updated accordingly. Phase 2 = gasto capture + ticket only.

---

## hora_cierre rule

| Option | Description | Selected |
|--------|-------------|----------|
| Auto from server time | Cutoff selects 12:00 vs 17:00 | ✓ |
| Ask the manager | Bot asks which closing | |

**User's choice:** Auto from server time.
**Notes:** Captured for Phase 3 (where the caja flow now lives). Exact cutoff = planner discretion.

---

## Off-topic handling

| Option | Description | Selected |
|--------|-------------|----------|
| Fixed deflection reply | Short fixed Spanish message; state stays idle | ✓ |
| Treat as gasto intent | Assume any idle text starts capture | |

**User's choice:** Fixed deflection reply.
**Notes:** Matches REQUIREMENTS "off-topic messages get a fixed deflection." No free-chat.

---

## Claude's Discretion

- Exact `ConvState` names after the reorder and orchestrator module layout.
- Router-level dedupe vs orchestrator-only DB idempotency.
- Ticket amount-extraction prompt/schema (amount-only is the hard requirement).
- All Spanish copy strings.
- `hora_cierre` cutoff time (Phase 3).

## Deferred Ideas

- Caja-closing reactive entry → Phase 3 (with prompt-trigger).
- Cross-check declared vs extracted amount (REQUIREMENTS Future).
- Multi-attachment ticket handling.
