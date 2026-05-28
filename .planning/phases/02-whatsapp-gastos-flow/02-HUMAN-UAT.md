---
status: partial
phase: 02-whatsapp-gastos-flow
source: [02-VERIFICATION.md]
started: 2026-05-27T22:54:00Z
updated: 2026-05-27T22:54:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. End-to-end gasto capture via Twilio sandbox
expected: From an allowlisted Twilio sandbox number, send "Pago de queso en supermercado". Then send a ticket photo (or reply "sin ticket"). Then send "sí" at the confirm summary. A new `gastos` row is persisted with the correct concepto, monto, manager phone, and (if photo) stored ticket image path. ROADMAP SC-1 and SC-2.
result: [pending]

### 2. Ticket photo path — vision-read amount + stored image
expected: Send a real JPEG of an Argentine ticket. The bot reads the total via GPT-4o vision and presents it in the confirmation summary; on "sí" the `gastos` row stores the local file path and the read amount.
result: [pending]

### 3. Replayed MessageSid (SC-4 full path)
expected: Replay an already-processed MessageSid via the Twilio sandbox retry mechanism or by re-POSTing the same webhook payload. The duplicate is detected via the DB `last_message_id` source-of-truth path (not just the in-memory fast-path) and no second `gastos` row is created.
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
