---
status: partial
phase: 03-whatsapp-pipeline
source: [03-02-PLAN.md]
started: 2026-05-14T17:37:26Z
updated: 2026-05-14T17:37:26Z
deferred_until: after Phase 4 (Admin UI)
---

## Current Test

[awaiting human testing — deferred until after Phase 4 Admin UI is complete]

## Setup

Before running any scenario:

1. `cd backend && uv sync`
2. `alembic upgrade head`
3. Activate Twilio Sandbox: text "join <keyword>" to Twilio sandbox WhatsApp number
4. Seed your phone: `psql $DATABASE_URL -c "INSERT INTO sender_allowlist (phone_number, display_name, is_active) VALUES ('+<e164-number>', 'Tester', true);"`
5. `docker compose up -d` (or `uvicorn app.main:app --reload`)
6. `ngrok http 8000` → copy https URL
7. Set `WEBHOOK_BASE_URL=https://<ngrok-id>.ngrok-free.app` in env → restart backend
8. In Twilio console → Sandbox → set Webhook URL to `https://<ngrok-id>.ngrok-free.app/whatsapp/webhook` (POST)

## Tests

### 1. Allowlisted happy path (WA-01 + WA-03 + INF-04)
Send a clear photo of a Factura A or Remito from an allowlisted number.
expected: (a) ACK reply arrives within 5s, (b) summary reply with Proveedor/Número/Fecha/Total arrives within ~30s, (c) `SELECT image_path FROM invoices ORDER BY created_at DESC LIMIT 1` points to a real file on disk
result: [pending]

### 2. Pending-review path (VAL-02)
Send a blurry or unclear invoice photo.
expected: Reply starts with `⚠️ Algunos campos no se pudieron leer...`
result: [pending]

### 3. Duplicate detection (VAL-01)
Resend the same invoice from scenario 1.
expected: Reply `🔁 Esta factura ya fue registrada el YYYY-MM-DD. No se guardó de nuevo.` with the original fecha
result: [pending]

### 4. Unsupported media type (WA-04)
Send a PDF from an allowlisted number.
expected: Reply `❌ No pudimos procesar la imagen...`
result: [pending]

### 5. Non-allowlisted sender (WA-02)
Send any image from a phone number NOT in sender_allowlist.
expected: Reply `❌ Este número no está autorizado...`; no DB row created
result: [pending]

### 6. Invalid HMAC signature (INF-02)
```bash
curl -X POST https://<ngrok-id>.ngrok-free.app/whatsapp/webhook \
  -H "X-Twilio-Signature: bogus" \
  -d "From=whatsapp:+1&MessageSid=SMtest&NumMedia=0"
```
expected: HTTP 401
result: [pending]

## Summary

total: 6
passed: 0
issues: 0
pending: 6
skipped: 0
blocked: 0

## Gaps
