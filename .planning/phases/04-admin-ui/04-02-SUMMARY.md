---
phase: 04-admin-ui
plan: "02"
subsystem: ui
tags: [tailwindcss, shadcn, react-router, tanstack-query, vite, typescript]

requires:
  - phase: 04-admin-ui/04-01
    provides: React + Vite scaffold with walking skeleton

provides:
  - Tailwind CSS v4 via @tailwindcss/vite plugin (zero-config, @import "tailwindcss" CSS entry)
  - 9 shadcn/ui components: button, dialog, badge, input, label, select, table, alert, separator
  - @/* path alias in both vite.config.ts and tsconfig.app.json
  - react-router v7 and @tanstack/react-query v5 installed
  - index.css: single Tailwind import, shadcn @theme inline tokens, full admin token set, clean #root
  - src/lib/utils.ts: cn() helper for shadcn component composition

affects:
  - 04-admin-ui/04-03 (InvoiceListPage uses shadcn components)
  - 04-admin-ui/04-04 (InvoiceDetailPage uses shadcn components)
  - 04-admin-ui/04-05 (any additional pages)

tech-stack:
  added:
    - tailwindcss v4 (via @tailwindcss/vite plugin)
    - "@tailwindcss/vite"
    - react-router v7
    - "@tanstack/react-query v5"
    - shadcn/ui 2.10.0 (new-york style, neutral base)
    - class-variance-authority
    - clsx + tailwind-merge
    - lucide-react
    - radix-ui
  patterns:
    - shadcn components live in src/components/ui/ and are committed to source (auditable)
    - cn() utility (clsx + tailwind-merge) for conditional class merging in all components
    - @/* alias maps to src/ for clean imports across the codebase

key-files:
  created:
    - frontend/src/components/ui/button.tsx
    - frontend/src/components/ui/dialog.tsx
    - frontend/src/components/ui/badge.tsx
    - frontend/src/components/ui/input.tsx
    - frontend/src/components/ui/label.tsx
    - frontend/src/components/ui/select.tsx
    - frontend/src/components/ui/table.tsx
    - frontend/src/components/ui/alert.tsx
    - frontend/src/components/ui/separator.tsx
    - frontend/src/lib/utils.ts
    - frontend/components.json
  modified:
    - frontend/package.json
    - frontend/package-lock.json
    - frontend/pnpm-lock.yaml
    - frontend/vite.config.ts
    - frontend/tsconfig.app.json
    - frontend/tsconfig.json
    - frontend/src/index.css

key-decisions:
  - "Used shadcn@2 (pinned major) instead of shadcn@latest per REVIEWS.md MEDIUM concern on reproducibility"
  - "shadcn init CSS-patching failed (known shadcn@2.10.0 + Tailwind v4 bug); components.json was written correctly and npx shadcn@2 add worked; @theme inline block added manually"
  - "tsconfig.json root-level gets compilerOptions.paths because shadcn CLI reads tsconfig.json, not tsconfig.app.json, for alias detection"
  - "ignoreDeprecations: 6.0 added to tsconfig.app.json because TypeScript 6.0 deprecated baseUrl (required for shadcn paths)"

patterns-established:
  - "shadcn component import pattern: import { Button } from '@/components/ui/button'"
  - "Tailwind v4 entry: @import tailwindcss as first line of index.css (no tailwind.config.js needed)"
  - "cn() for all class merging: import { cn } from '@/lib/utils'"

requirements-completed:
  - UI-01
  - UI-06

duration: 5min
completed: "2026-05-14"
---

# Phase 04 Plan 02: Frontend Toolchain Summary

**Tailwind CSS v4 + shadcn/ui (9 components) + React Router v7 + TanStack Query v5 installed, @/* alias wired in Vite and TypeScript, index.css migrated to admin design tokens with clean #root**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-05-14T23:43:33Z
- **Completed:** 2026-05-14T23:48:00Z
- **Tasks:** 2
- **Files modified:** 16

## Accomplishments

- Installed Tailwind CSS v4 via @tailwindcss/vite plugin and configured it in vite.config.ts
- Installed react-router v7 and @tanstack/react-query v5 as Wave 2 dependencies
- Ran shadcn@2 to generate 9 UI components (button, dialog, badge, input, label, select, table, alert, separator) with new-york style and neutral base color
- Wrote index.css with single @import "tailwindcss", shadcn @theme inline tokens, all admin design tokens, and cleaned #root (removed width/text-align/border-inline constraints)
- Configured @/* path alias in vite.config.ts (resolve.alias) and tsconfig.app.json (paths) + tsconfig.json (for shadcn detection)
- Build passes: npm run build exits 0, 190KB JS bundle

## Task Commits

1. **Task 1: Install packages + configure vite.config.ts + tsconfig.app.json alias** - `b547256` (feat)
2. **Task 2: shadcn init + add 9 components + fix index.css** - `9792ed8` (feat)
3. **Lock file update** - `1dfc267` (chore)

## Files Created/Modified

- `frontend/src/components/ui/button.tsx` - shadcn Button with CVA variants (default/destructive/outline/ghost/link)
- `frontend/src/components/ui/dialog.tsx` - shadcn Dialog (modal overlay component)
- `frontend/src/components/ui/badge.tsx` - shadcn Badge (status/label chips)
- `frontend/src/components/ui/input.tsx` - shadcn Input
- `frontend/src/components/ui/label.tsx` - shadcn Label
- `frontend/src/components/ui/select.tsx` - shadcn Select dropdown
- `frontend/src/components/ui/table.tsx` - shadcn Table (thead/tbody/tr/th/td)
- `frontend/src/components/ui/alert.tsx` - shadcn Alert (info/warning/error banners)
- `frontend/src/components/ui/separator.tsx` - shadcn Separator (horizontal rule)
- `frontend/src/lib/utils.ts` - cn() = clsx + tailwind-merge for component class merging
- `frontend/components.json` - shadcn config (new-york, neutral, @/* aliases)
- `frontend/vite.config.ts` - Added tailwindcss() plugin, @/* alias, /invoices + /images proxy
- `frontend/tsconfig.app.json` - Added baseUrl, @/* paths, ignoreDeprecations "6.0"
- `frontend/tsconfig.json` - Added compilerOptions with @/* paths (for shadcn CLI detection)
- `frontend/src/index.css` - Migrated to: @import tailwindcss, @theme inline, admin tokens, clean #root
- `frontend/package.json` - Added all new dependencies

## Decisions Made

- Pinned `shadcn@2` instead of `shadcn@latest` per REVIEWS.md MEDIUM concern (reproducibility risk)
- Added `ignoreDeprecations: "6.0"` to tsconfig.app.json because TypeScript 6.0 deprecated `baseUrl` but shadcn@2 still requires it
- Added `compilerOptions.paths` to root `tsconfig.json` (not just `tsconfig.app.json`) because shadcn CLI reads the root tsconfig for alias detection
- Manually wrote the shadcn `@theme inline` CSS block because `shadcn@2 init` has a known bug: it writes components.json correctly but fails on the CSS-patching step with "Validation failed: css: Invalid input" when using Tailwind v4 — `npx shadcn@2 add` works fine

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] shadcn@2 init CSS-patching bug — bypassed with manual CSS + direct add**
- **Found during:** Task 2 (shadcn init)
- **Issue:** `npx shadcn@2 init --defaults` fails after writing components.json with "Validation failed: css: Invalid input" — a known shadcn@2.10.0 bug with Tailwind v4 CSS validation in the init command
- **Fix:** components.json was already written correctly; ran `npx shadcn@2 add` directly for all 9 components; manually added the `@theme inline` shadcn token block to index.css
- **Files modified:** frontend/src/index.css, frontend/components.json
- **Verification:** All 9 components created, npm run build exits 0
- **Committed in:** 9792ed8 (Task 2 commit)

**2. [Rule 3 - Blocking] Missing peer dependencies — installed class-variance-authority, clsx, tailwind-merge, lucide-react**
- **Found during:** Task 2 (after shadcn add)
- **Issue:** `npm run build` failed with missing lucide-react and class-variance-authority (shadcn components reference these but shadcn add didn't install them due to the init bug)
- **Fix:** `npm install class-variance-authority clsx tailwind-merge lucide-react`
- **Files modified:** frontend/package.json, frontend/package-lock.json
- **Verification:** Build passes
- **Committed in:** 9792ed8 (Task 2 commit)

**3. [Rule 3 - Blocking] tsconfig.json root-level alias — added for shadcn CLI detection**
- **Found during:** Task 2 (shadcn init alias validation)
- **Issue:** shadcn CLI reads root `tsconfig.json` for alias detection, not `tsconfig.app.json`; init failed with "No import alias found in your tsconfig.json file"
- **Fix:** Added `compilerOptions` with `baseUrl` and `paths` to root `tsconfig.json`
- **Files modified:** frontend/tsconfig.json
- **Verification:** shadcn alias validation passes
- **Committed in:** 9792ed8 (Task 2 commit)

**4. [Rule 1 - Bug] TypeScript 6.0 baseUrl deprecation — added ignoreDeprecations**
- **Found during:** Task 2 (npm run build)
- **Issue:** `tsc -b` exited 2 with "Option 'baseUrl' is deprecated... Specify ignoreDeprecations: '6.0' to silence"
- **Fix:** Added `"ignoreDeprecations": "6.0"` to tsconfig.app.json compilerOptions
- **Files modified:** frontend/tsconfig.app.json
- **Verification:** Build exits 0
- **Committed in:** 9792ed8 (Task 2 commit)

**5. [Rule 2 - Missing Critical] Created src/lib/utils.ts — cn() helper shadcn components require**
- **Found during:** Task 2 (component review + build)
- **Issue:** All shadcn components import `@/lib/utils` but shadcn init didn't create it due to the CSS bug
- **Fix:** Created `frontend/src/lib/utils.ts` with `cn()` using clsx + tailwind-merge
- **Files modified:** frontend/src/lib/utils.ts (new)
- **Verification:** Build passes, all component imports resolve
- **Committed in:** 9792ed8 (Task 2 commit)

---

**Total deviations:** 5 auto-fixed (1 blocking workaround, 2 blocking deps, 1 bug, 1 missing critical)
**Impact on plan:** All auto-fixes necessary. shadcn@2.10.0 init bug is well-documented; the workaround (direct add + manual CSS) produces identical output. No scope creep.

## Issues Encountered

- shadcn@2.10.0 has a known bug where `init` fails at the CSS-patching step when detecting Tailwind v4. The components.json is written correctly and `shadcn@2 add` works. Root cause is a Zod validation schema mismatch in the registry CSS response parser. Workaround: skip the CSS patching step and write the @theme inline block manually.

## Known Stubs

None. This plan installs tooling only — no UI components that render data.

## Next Phase Readiness

- Wave 2 can begin: InvoiceListPage (04-03) and InvoiceDetailPage (04-04) can import from `@/components/ui/*`
- Tailwind v4 classes will compile in dev and build
- react-router and @tanstack/react-query are available for page routing and data fetching
- All 9 required components are available and build correctly

---
*Phase: 04-admin-ui*
*Completed: 2026-05-14*
