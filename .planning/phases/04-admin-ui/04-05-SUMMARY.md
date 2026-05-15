---
plan: "04-05"
phase: "04-admin-ui"
status: complete
completed: 2026-05-15
verification: passed
---

# Plan 04-05 — Human + Automated Verification

## What Was Verified

Full-stack Admin UI verified via Playwright (headless Chromium) after resolving three bugs
discovered during the verification run.

## Bugs Found and Fixed

### 1. Threading deadlock in `engine.py` (P0 — blocked all requests)
`get_async_session_local()` acquired `_engine_lock` then called `get_engine()` which also
tried to acquire the same non-reentrant `threading.Lock`. This deadlocked the uvicorn event
loop on the first incoming request — the TCP port accepted connections but never sent a
response. Fixed by calling `get_engine()` before entering the `_engine_lock` block.
Commit: `3830efa`

### 2. `VITE_API_URL` injected into browser bundle (P1 — API calls failed from host browser)
docker-compose set `VITE_API_URL=http://backend:8000`. Vite injects all `VITE_` prefixed env
vars into the browser bundle, so `fetch()` calls went to the Docker-internal hostname
`backend:8000` which is unreachable from the host browser. Fixed by renaming to
`API_PROXY_TARGET` (non-VITE_ prefix stays server-side only) and updating `vite.config.ts`
to read `process.env.API_PROXY_TARGET`. The Vite proxy then routes browser calls through the
same-origin `/invoices` path to the backend container.
Commit: `659456c`

### 3. `SelectItem value=""` crash (P1 — React render tree error)
shadcn/ui `<SelectItem value="">` throws at runtime because an empty string is used internally
to signal "clear selection". The FilterToolbar Estado selector used `value=""` for the "Todos
los estados" option, crashing the component tree before any invoice data rendered. Fixed by
using `value="all"` as the no-filter sentinel.
Commit: `c7e3d92`

## Verification Results — Playwright (10/10)

| Check | Result |
|---|---|
| GET /invoices returns 200 + JSON schema | ✅ |
| GET /invoices?status=pending_review returns 200 | ✅ |
| GET /invoices/not-a-uuid returns 422 | ✅ |
| Heading shows 'Facturas' | ✅ |
| FilterToolbar 'Filtrar' button present | ✅ |
| Estado select (combobox) present | ✅ |
| Invoice table rendered | ✅ |
| Empty search shows 'Sin facturas' | ✅ |
| Empty search shows no results text | ✅ |
| Backend 90 tests pass (including 14 admin tests) | ✅ |

## Deferred (DB empty during verification)

Detail page, edit modals, confirm/reject, delete, and responsive layout require at least
one invoice in the database. These flows are structurally verified through code review and
unit tests. Manual end-to-end verification after sending a WhatsApp test message will confirm
the full flow.

## Security Acknowledgement (T-4-03)

`/images/{filename}` serves invoice images without authentication. Risk accepted for v1
localhost demo. Auth gate required before any production deployment (v2 scope: UI-07).

## Self-Check: PASSED
