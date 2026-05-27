# Phase 1: Data + Conversation Core - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-27
**Phase:** 1-data-conversation-core
**Areas discussed:** Gasto data shape, Conversation flow, Slot-extraction model, Correct/cancel + timeout, Agent selection

---

## Gasto data shape

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal | concepto + monto (salida) + fecha=today + optional ticket | ✓ |
| Concepto + lugar split | separate qué/dónde fields | |
| Full sheet parity | concepto, lugar, salida, entrada, backdatable fecha, category | |

**User's choice:** Minimal
**Notes:** concepto mirrors the sheet's freeform OBSERVACION column; entrada/category/lugar-split/backdating deferred.

---

## Conversation flow

| Option | Description | Selected |
|--------|-------------|----------|
| Ask only what's missing, one at a time | parse intent, one follow-up per missing slot | ✓ |
| Fixed sequence always | same questions regardless of intent | |
| One combined message | ask all missing fields at once | |

**User's choice:** Ask only what's missing, one at a time
**Notes:** Natural over WhatsApp, least friction.

---

## Slot-extraction model

| Option | Description | Selected |
|--------|-------------|----------|
| gpt-4o-mini | cheaper/faster; enough for short-text slot parsing | ✓ |
| gpt-4o | same as invoice vision; max accuracy, higher cost | |

**User's choice:** gpt-4o-mini
**Notes:** Vision/ticket extraction (Phase 2) still uses gpt-4o.

---

## Correct/cancel + timeout

| Option | Description | Selected |
|--------|-------------|----------|
| Freeform re-state, GPT re-extracts | "no, fueron 1500" re-parsed onto draft; "cancelar" aborts | ✓ |
| Structured field picker | reply a number to edit a field | |

**User's choice:** Freeform re-state, GPT re-extracts
**Notes:** Timeout accepted at default CONVERSATION_TIMEOUT_HOURS = 4.

---

## Agent selection

| Option | Description | Selected |
|--------|-------------|----------|
| AGENT_MODE = invoice \| gastos | one env var; only selected agent's webhook registered; default gastos | ✓ |
| Two separate flags | INVOICE_AGENT_ENABLED / GASTOS_AGENT_ENABLED | |
| Separate webhook paths, both live | both agents always registered | |

**User's choice:** AGENT_MODE = invoice | gastos
**Notes:** User raised this area unprompted. Both agents are demos; one deployment runs one agent. The other agent must be fully blocked, not just hidden.

## Claude's Discretion

- ORM column types/lengths, table/index names, migration structure
- Whether CajaCierre model is created in Phase 1 or Phase 2
- Orchestrator internal layout (match-based recommended)
- Exact Spanish copy strings

## Deferred Ideas

- entrada (money in) capture
- separate lugar/proveedor field
- expense category
- backdating fecha ("ayer")
- structured field-picker correction UX
- cross-check declared monto vs ticket total
