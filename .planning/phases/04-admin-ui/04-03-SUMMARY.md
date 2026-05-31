---
phase: 04-admin-ui
plan: 03
subsystem: frontend
tags: [frontend, react, react-router, tanstack-query, admin-ui, wave-2]
dependency_graph:
  requires: [04-02]
  provides:
    - frontend/src/pages/GastosListPage.tsx
    - frontend/src/pages/GastoDetailPage.tsx
    - frontend/src/pages/CierresListPage.tsx
    - frontend/src/api/client.ts
    - frontend/src/utils/formatARS.ts
    - frontend/src/utils/formatDate.ts
    - frontend/src/components/NavTabs.tsx
    - frontend/src/components/Spinner.tsx
    - frontend/src/admin.css
  affects: [04-VALIDATION.md, UAT gate]
tech_stack:
  added:
    - react-router 7.16.0
    - "@tanstack/react-query 5.100.14"
  patterns:
    - createBrowserRouter + RouterProvider + layout route (NavTabs + Outlet)
    - QueryClientProvider with staleTime 30_000 default
    - useQuery (v5 isPending) for reads; no mutations (read-only)
    - Typed fetch client reading import.meta.env.VITE_API_URL with /api fallback
    - Manual formatARS (no Intl/toLocaleString) producing $1.234,56
    - Spanish month abbreviations [ene..dic] for formatDate/formatDateTime
    - Vanilla CSS custom properties (admin.css extending index.css tokens)
key_files:
  created:
    - frontend/src/admin.css
    - frontend/src/api/client.ts
    - frontend/src/utils/formatARS.ts
    - frontend/src/utils/formatDate.ts
    - frontend/src/components/Spinner.tsx
    - frontend/src/components/NavTabs.tsx
    - frontend/src/pages/GastosListPage.tsx
    - frontend/src/pages/GastoDetailPage.tsx
    - frontend/src/pages/CierresListPage.tsx
  modified:
    - frontend/package.json
    - frontend/pnpm-lock.yaml
    - frontend/src/index.css
    - frontend/src/App.tsx
    - frontend/src/main.tsx
    - frontend/index.html
decisions:
  - "react-router v7 imported from 'react-router' (not 'react-router-dom') — Pitfall 5 avoided"
  - "Layout route wraps NavTabs + Outlet so nav persists across all three routes"
  - "formatDate parses ISO date by splitting on '-' to avoid UTC timezone shift"
  - "formatARS comment reworded to not contain 'toLocaleString' string (grep gate)"
  - "toLocaleString removed from formatARS comment to pass grep acceptance gate cleanly"
metrics:
  duration: 25m
  completed: 2026-05-31
  tasks_completed: 3
  files_created: 9
---

# Phase 04 Plan 03: React Admin UI (Gastos + Cierres) — Summary

**One-liner:** Three read-only React pages (Gastos filterable list, Gasto detail with ticket image, Cierres list) wired via react-router v7 + TanStack Query v5 against the Plan 02 /api endpoints, with manual Argentine money/date formatters and vanilla CSS token system — building and linting clean.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Install deps + wire router/query/CSS + API client + utils + nav shell | a9fdad4 | 12 files (package.json, pnpm-lock.yaml, index.css, App.tsx, main.tsx, index.html, admin.css, client.ts, NavTabs.tsx, Spinner.tsx, formatARS.ts, formatDate.ts) |
| 2 | GastosListPage + GastoDetailPage | 8d0ec41 | frontend/src/pages/GastosListPage.tsx, GastoDetailPage.tsx |
| 3 | CierresListPage + build + lint gate | 9e95861 | frontend/src/pages/CierresListPage.tsx |

## Verification Results

### Build Gate

```
pnpm build → tsc -b && vite build
✓ 78 modules transformed
dist/assets/index-WR1e8pPW.css   6.51 kB
dist/assets/index-DrJUHud7.js  326.65 kB
✓ built in 500ms
EXIT 0
```

### Lint Gate

```
pnpm lint → eslint .
(no output — clean)
EXIT 0
```

### Source Assertion Gates

| Gate | Result |
|------|--------|
| `grep -c "react-router-dom" frontend/package.json` | 0 (PASS) |
| `grep -c 'import.meta.env.VITE_API_URL' src/api/client.ts` | 3 (PASS — present) |
| `grep -c "toLocaleString" src/utils/formatARS.ts` | 0 (PASS) |
| `grep -c "navigate\|to=\|onClick" src/pages/CierresListPage.tsx` | 0 (PASS — not clickable) |
| `grep -ci "delete\|eliminar\|editar\|onSubmit" GastosListPage.tsx GastoDetailPage.tsx` | 0 (PASS) |

### Backend Suite (No Regressions)

```
pytest tests/ -q
183 passed, 1 skipped in 6.06s
```

No backend files were modified. Suite confirms no regressions.

## UAT Prerequisites (Manual Gate)

**Docker users must rebuild the frontend container before running in-container UAT:**

```bash
docker compose build frontend
docker compose up frontend
```

The Docker frontend container mounts `./frontend/src` and `./frontend/public` as bind volumes,
but `node_modules` is an **anonymous volume** (`/app/node_modules`) frozen at image build time.
Running `pnpm add` on the host updates `package.json` + `pnpm-lock.yaml` but does NOT install
inside the running container. `docker compose build frontend` rebuilds the image with the new
`react-router` and `@tanstack/react-query` packages baked in.

For local dev (outside Docker): `cd frontend && pnpm install` is sufficient.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] formatARS comment contained 'toLocaleString' triggering grep gate**
- **Found during:** Task 1 acceptance verification
- **Issue:** The comment `* Does NOT use Intl.NumberFormat or toLocaleString (inconsistent mobile support)` contained the literal string `toLocaleString`, causing `grep -c "toLocaleString" src/utils/formatARS.ts` to return 1 (must be 0 per plan).
- **Fix:** Rewrote comment to `* Does NOT use Intl.NumberFormat or locale string APIs (inconsistent mobile support)` — semantically equivalent, no false positive.
- **Files modified:** frontend/src/utils/formatARS.ts
- **Commit:** a9fdad4 (same task commit — caught during pre-commit verification)

## Known Stubs

None. All three pages fetch from live API endpoints (listGastos, getGasto, listCierres) and render real data. No placeholder text or hardcoded mock data.

## Threat Flags

None. All surfaces introduced match the plan's threat model:
- T-04-03: Same-origin /api/* via Vite proxy in dev; CORS enforced server-side (Plan 02). Client sends no credentials.
- T-04-06: Ticket image at /api/gastos/{id}/ticket — UUID constructed client-side; path traversal guard lives server-side.
- T-04-07: Read-only verified by grep gates — 0 edit/delete/mutation controls on all three pages.
- T-04-SC: Both packages (react-router, @tanstack/react-query) are ASSUMED-OK per RESEARCH package legitimacy audit.

## Self-Check: PASSED

- [x] `frontend/src/pages/GastosListPage.tsx` exists
- [x] `frontend/src/pages/GastoDetailPage.tsx` exists
- [x] `frontend/src/pages/CierresListPage.tsx` exists
- [x] `frontend/src/api/client.ts` exists
- [x] `frontend/src/utils/formatARS.ts` exists
- [x] `frontend/src/utils/formatDate.ts` exists
- [x] `frontend/src/components/NavTabs.tsx` exists
- [x] `frontend/src/components/Spinner.tsx` exists
- [x] `frontend/src/admin.css` exists
- [x] Commit `a9fdad4` verified (Task 1)
- [x] Commit `8d0ec41` verified (Task 2)
- [x] Commit `9e95861` verified (Task 3)
- [x] `pnpm build` → EXIT 0
- [x] `pnpm lint` → EXIT 0
- [x] `pytest tests/ -q` → 183 passed, 1 skipped
- [x] `grep -c "react-router-dom" package.json` → 0
- [x] `grep -c "toLocaleString" src/utils/formatARS.ts` → 0
- [x] `grep -c "navigate|to=|onClick" CierresListPage.tsx` → 0
