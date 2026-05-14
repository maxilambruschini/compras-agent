# Phase 3: WhatsApp Pipeline - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-14
**Phase:** 3-WhatsApp-Pipeline
**Areas discussed:** WhatsApp provider, Background task wiring, Reply message copy, Duplicate detection

---

## WhatsApp Provider

| Option | Description | Selected |
|--------|-------------|----------|
| Meta WhatsApp Cloud API (direct) | Free, no middleman. Requires Meta Business Account + Facebook Developer App. Free test phone number for up to 5 contacts. 2–4 hour setup. Business verification needed for production (days/weeks). | |
| Twilio sandbox | Sits on top of Meta's API. 15–30 minute setup, no business verification. Per-message cost overhead. Sandbox requires senders to "join [keyword]" first. | ✓ (demo) |
| 360dialog | Direct Meta BSP, simpler than Twilio for production but no better sandbox story. | |

**User's choice:** Twilio for demo, Meta Cloud API for production later. Build a `WhatsAppProvider` abstraction so swapping is a config/env change.

**Notes:** User is new to WhatsApp API setup. Twilio chosen for speed ("quick demo for now"). User explicitly asked for the abstraction layer to make Meta swap easy. pywa (already pinned in CLAUDE.md) is the target for the Meta implementation.

---

## Background Task Wiring

| Option | Description | Selected |
|--------|-------------|----------|
| asyncio.create_task() | Schedules async coroutine on running event loop. Works naturally with AsyncOpenAI and AsyncSession. | ✓ |
| FastAPI BackgroundTasks | Runs in thread pool. Requires awkward asyncio.run() wrapping for async code. Not recommended. | |
| You decide | Leave mechanism to researcher/planner. | |

**User's choice:** `asyncio.create_task()`

**Notes:** No additional context provided. Recommendation accepted.

---

## Reply Message Copy

### Tone

| Option | Description | Selected |
|--------|-------------|----------|
| Friendly & brief | Short, warm Spanish with emoji. Approachable for employees. | ✓ |
| Formal & professional | Corporate tone, no emoji. | |
| Minimal, no emoji | Plain text, very terse. | |

**User's choice:** Friendly & brief

### Summary fields (WA-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Core 4: proveedor, número, fecha, total | Enough to verify without overwhelming. | ✓ |
| All extracted fields | Full dump including CUIT, CAE, IVA. Too verbose. | |
| Just status + proveedor | Minimal confirmation. | |

**User's choice:** Core 4 fields

### Low-confidence reply

| Option | Description | Selected |
|--------|-------------|----------|
| Fields + review warning | Show extracted fields + "Un revisor lo va a verificar." | (modified) |
| Same summary, no warning | Treat pending_review same as auto_saved. | |
| Just the warning, no fields | No field summary shown. | |

**User's choice:** Fields + review warning, but CTA changed from "Un revisor lo va a verificar" to **"Revisar factura desde la web"** — points to admin UI, not a person.

**Notes:** User preferred directing the sender to the web UI (Phase 4) rather than implying a human reviewer.

---

## Duplicate Detection

### Match strictness

| Option | Description | Selected |
|--------|-------------|----------|
| Exact match, case-insensitive | Normalize to lowercase. Simple and predictable. | ✓ |
| Exact match, case-sensitive | 'VINOS SA' ≠ 'Vinos Sa' — risky. | |
| Fuzzy match on proveedor | String similarity. More accurate, more complex. | |

**User's choice:** Exact match, case-insensitive

### Duplicate reply

| Option | Description | Selected |
|--------|-------------|----------|
| Simple rejection + original date | 🔁 Esta factura ya fue registrada el [fecha]. No se guardó de nuevo. | ✓ |
| Just a rejection, no date | No context to sender. | |
| Rejection + link to review | Consistent with pending_review CTA. | |

**User's choice:** Simple rejection + original date

---

## Claude's Discretion

- `WhatsAppProvider` — Protocol vs ABC (pick `typing.Protocol`)
- `TwilioProvider.validate_signature()` — use official Twilio request validator
- Logging structure — follow existing structlog patterns from Phase 2
- Duplicate detection location — `InvoiceService` vs inline in handler

## Deferred Ideas

- Meta Cloud API full implementation (pywa wiring) — production upgrade path, not this phase
- Fuzzy proveedor matching — v2 (INF-V2-02)
- Queue-based retry for failed extractions — overkill at <20 invoices/day
- Full PDF support — error reply for now, extraction support is v2
