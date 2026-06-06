---
quick_id: 260606-bvq
slug: fix-admin-ui-cors-stop-leaking-docker-pr
date: 2026-06-06
status: complete
---

# Quick Task 260606-bvq — Summary

## What was done

Fixed the admin-UI CORS failure by stopping the Vite dev-proxy target from
leaking into the browser bundle.

- **`frontend/vite.config.ts`**: `apiTarget` now reads `process.env.API_PROXY_TARGET`
  (fallback `http://localhost:8000`) instead of `process.env.VITE_API_URL`. Added a
  comment explaining the `VITE_`-prefix-leaks-to-browser hazard.
- **`docker-compose.yml`** (frontend service): env var renamed
  `VITE_API_URL=http://backend:8000` → `API_PROXY_TARGET=http://backend:8000`.

With `VITE_API_URL` no longer set in the browser environment,
`src/api/client.ts` falls back to its relative `/api` base. The browser now
requests `http://localhost:5173/api/...` (same origin as the page); the Vite
dev server proxies that to `API_PROXY_TARGET` server-side. No cross-origin
request is made, so CORS no longer applies. Backend `allowed_origins` was left
unchanged by design.

## Verification (all green)
- `pnpm build` — exit 0 (tsc -b + vite build)
- `pnpm lint` — exit 0
- `grep VITE_API_URL frontend/vite.config.ts docker-compose.yml` — no matches
- `API_PROXY_TARGET` present in `frontend/vite.config.ts:10` and `docker-compose.yml:50`

## Note for the user
If you were running via Docker, rebuild/restart the frontend so it picks up the
renamed env var: `docker compose up -d --build frontend` (or just restart the
frontend service). For a local `pnpm dev`, make sure `VITE_API_URL` is not set
in your shell (otherwise it would still leak); set `API_PROXY_TARGET` instead if
your backend isn't on `localhost:8000`.
