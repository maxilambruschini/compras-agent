---
quick_id: 260606-bvq
slug: fix-admin-ui-cors-stop-leaking-docker-pr
date: 2026-06-06
mode: quick
---

# Quick Task 260606-bvq: Fix admin UI CORS error (proxy-target leak)

## Problem

The admin UI fails to fetch gastos/cierres with a CORS error. Root cause: the
frontend Docker service sets `VITE_API_URL=http://backend:8000`. Because the
`VITE_` prefix is exposed to the browser bundle (`import.meta.env`),
`frontend/src/api/client.ts` computes its fetch base as
`http://backend:8000/api` — a Docker-internal hostname the browser can't reach
and a cross-origin target. The intended design has the browser use the relative
`/api` base and let the Vite dev-server proxy forward to the backend
server-side (same-origin → no CORS). One `VITE_`-prefixed var was doing double
duty (proxy target + browser base), leaking the internal hostname.

## Tasks

1. **`frontend/vite.config.ts`** — read the proxy target from a non-`VITE_` env
   var `API_PROXY_TARGET` (fallback `http://localhost:8000`) so it stays
   server-side only and is never inlined into the browser bundle.
2. **`docker-compose.yml`** (frontend service) — rename the env var
   `VITE_API_URL=http://backend:8000` → `API_PROXY_TARGET=http://backend:8000`.

Backend CORS (`allowed_origins`) is intentionally left unchanged — with the
browser on the relative `/api` proxy path there is no cross-origin request.

## Verification
- `cd frontend && pnpm build` exits 0
- `cd frontend && pnpm lint` exits 0
- `grep VITE_API_URL frontend/vite.config.ts docker-compose.yml` → no matches
- `API_PROXY_TARGET` present in both files

## Out of scope
- Backend CORS changes (not needed).
- Switching the browser to call the backend directly (the proxy is the design).
