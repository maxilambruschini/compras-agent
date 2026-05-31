---
phase: 4
slug: admin-ui
status: advisory
score: 20/24
audited: 2026-05-31
baseline: 04-UI-SPEC.md (approved)
screenshots: not captured (dev server at :5173 detected but no Playwright available; code-only audit)
per_pillar:
  copywriting: 4
  visuals: 3
  color: 3
  typography: 3
  spacing: 3
  experience_design: 4
---

# Phase 4 — UI Review

**Audited:** 2026-05-31
**Baseline:** 04-UI-SPEC.md (approved 2026-05-31)
**Screenshots:** Not captured — code-only audit (dev server live at :5173 but no Playwright CLI available in session)

---

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 4/4 | All Spanish copy matches spec exactly; document title present |
| 2. Visuals | 3/4 | Filter bar remains visible during loading (spec says content hidden); no per-route document.title |
| 3. Color | 3/4 | Error banner dark-mode alpha not overridden; error body text uses --text instead of error red |
| 4. Typography | 3/4 | 12px ticket badge is a 5th font size outside the declared 4-size scale |
| 5. Spacing | 3/4 | Three off-scale 20px values; page-content horizontal padding is 24px not the spec's xl=32px |
| 6. Experience Design | 4/4 | All four states covered; read-only enforced; formatARS correct for domain; react-query keys per spec |

**Overall: 20/24**

---

## Top 3 Priority Fixes

1. **Error banner dark-mode background not overridden** — In dark mode the error banner shows `rgba(239,68,68,0.08)` (light-mode alpha) instead of the spec's `rgba(239,68,68,0.12)`. Impact: error surface is visually lighter than intended in dark mode, reducing legibility of the severity signal. Fix: add a `@media (prefers-color-scheme: dark)` block in `admin.css` that sets `.error-banner { background: rgba(239,68,68,0.12); }`.

2. **Three off-scale 20px spacing values** — `.page-title { margin: 0 0 20px 0 }`, `.detail-back-link { margin-bottom: 20px }`, and `.page-content { padding: 24px }` (horizontal) depart from the declared 8-point grid. 20px is on the 4px grid but is not a named token in the spec (scale: 4/8/16/24/32/48). Impact: inconsistent rhythm across pages; the detail back-link gap and page title gap are each 4px tighter than the next scale step. Fix: change both 20px margins to `16px` (md) or `24px` (lg) based on desired breathing room; change `.page-content` left/right padding to `32px` (xl) as spec states, retaining `24px` top/bottom.

3. **Filter bar visible during loading state** — The spec states "table/content hidden" while the spinner is shown. GastosListPage renders the filter bar unconditionally before the loading conditional, so the filter controls appear above the spinner. Impact: users can interact with filters while the initial fetch is in flight, potentially triggering a second query before data arrives. Fix: wrap the filter bar in `{!isPending && <div className="filter-bar">...</div>}` or disable all inputs during `isPending`.

---

## Detailed Findings

### Pillar 1: Copywriting (4/4)

PASS — Contract fully honored.

Verified against every entry in the Copywriting Contract table:

- Nav tabs: "Gastos" / "Cierres de Caja" — exact match (`NavTabs.tsx:18,24`)
- Page titles: "Gastos" / "Cierres de Caja" / "Detalle de Gasto" — exact match
- Table column headers: Fecha, Concepto, Monto, Ticket, Registrado por, Cierre, Efectivo en caja — all present and exact (`GastosListPage.tsx:134-139`, `CierresListPage.tsx:51-55`)
- Filter labels: "Desde" / "Hasta" / "Buscar" / placeholder "Buscar concepto..." / button "Limpiar" — exact match (`GastosListPage.tsx:47-89`)
- Ticket badge: "con ticket" / "—" — exact match (`GastosListPage.tsx:153-156`)
- Detail ticket image absent: "Sin ticket adjunto" — exact match (`GastoDetailPage.tsx:89`)
- Back link: "← Volver a gastos" — exact match (`GastoDetailPage.tsx:28`)
- Empty states (all three variants): copy matches spec word-for-word (`GastosListPage.tsx:113-126`, `CierresListPage.tsx:40-44`)
- Loading: "Cargando..." — exact match (`Spinner.tsx:10`)
- Error heading/body: exact match (`GastosListPage.tsx:101-104`)
- Document title: "Compras Agent" — present in `frontend/index.html`

Minor non-blocking note: `.filter-clear:hover` adds `color: var(--text-h)` in addition to underline. The spec says "underline on hover" only, not a color change. This is an enhancement that does not conflict with the contract and is left as-is since it improves affordance.

---

### Pillar 2: Visuals (3/4)

Two findings, neither a blocker.

**WARNING — Filter bar visible during loading (`GastosListPage.tsx:41-96`):**
The spec's Interaction State table states: "Page — loading: Spinner centered in content area, table/content hidden." The filter bar renders unconditionally at the top of the return JSX. During `isPending`, the spinner appears below a fully interactive filter bar. The content area is not replaced — it is appended. This is a layout deviation from the spec's mental model of a full-page loading replacement.

**WARNING — No per-route document.title update:**
The spec lists "Compras Agent" as the browser tab title. No `useEffect` or equivalent updates `document.title` when navigating between routes (e.g., "Detalle de Gasto | Compras Agent"). The static title is correct but the spec is silent on dynamic updates, so this is informational rather than a failure. The single "Compras Agent" title matches the declared contract value.

Passing findings: Visual hierarchy is correctly established (20px/500 page title, 14px/400 table headers, 16px/400 body). Nav tab active indicator (2px accent bottom border + text-h color) is implemented in `admin.css:47-49`. Ticket badge pill with accent colors provides a correct focal point for the "has ticket" state. Clickable rows have `cursor: pointer` via `.data-table.clickable-rows`; non-clickable rows use `cursor: default` via `.data-table.static-rows`. Row hover (`var(--secondary-surface)` background) applied to both tables. Detail page back link uses `var(--accent)` as spec requires. Ticket image `cursor: pointer` is applied (`admin.css:383`). Read-only enforced: no edit/delete controls anywhere in the codebase.

---

### Pillar 3: Color (3/4)

Two findings.

**WARNING — Error banner dark-mode alpha gap (`admin.css:295-300`):**
`admin.css` contains zero `@media (prefers-color-scheme: dark)` blocks. The error banner background is hard-coded as `rgba(239, 68, 68, 0.08)`. The spec requires `rgba(239,68,68,0.12)` in dark mode. In dark mode the error surface is rendered at the lighter 0.08 alpha against a dark `--bg`, making it visually less prominent than designed. Fix: add dark-mode override in `admin.css`.

**WARNING — Error banner body text color (`admin.css:312`):**
`.error-banner-body` uses `color: var(--text)` (secondary gray). The spec's Color section defines "Error text: `#dc2626`" and the error banner section implies error-colored text. The heading correctly uses `#dc2626` (`admin.css:306`), but the body copy falls back to the neutral secondary text. This reduces the visual urgency of the error body. Fix: change `.error-banner-body { color: #dc2626; }` (or a CSS variable if one is introduced for error text). Note: for a long body string this may be a readability trade-off — flag as advisory.

**PASS — `App.css` accent leak:** `App.css` references `var(--accent)` in three places but is NOT imported anywhere in the codebase (`grep` confirms zero imports). It is an orphaned scaffold file from the Vite template. It has zero runtime impact and does not inflate accent usage on live pages.

**PASS — 60/30/10 distribution:** `--bg` (white/dark) covers page background and table rows (dominant). `--secondary-surface` covers table headers, filter bar, row hover (secondary). `--accent` is used only on: active nav tab border (`admin.css:49`), ticket badge (`admin.css:222` via `var(--accent)`), spinner border-top (`admin.css:244`), filter focus outline (`admin.css:110`), and detail back link (`admin.css:324`). All are documented permitted uses. No decorative accent overuse detected.

**PASS — `--secondary-surface` token:** Verified present in `index.css:4` (light: `#f7f6f9`) and `index.css:38` (dark: `#1e1f28`) as specified. Token is consumed correctly in `admin.css` at thead, filter-bar, and row-hover.

**PASS — Hardcoded colors:** `#dc2626` appears at `admin.css:297` and `admin.css:306` (error banner). The spec explicitly states `#dc2626` as the error text color and the error banner border color. These are sanctioned hardcodes, not violations.

---

### Pillar 4: Typography (3/4)

One finding.

**WARNING — 12px ticket badge is a 5th font size (`admin.css:223`):**
The declared type scale is: 16px body, 14px label, 20px heading, 28px display (unused). The ticket badge uses `font-size: 12px`, which is not in the declared scale. The spec's Ticket Indicator component contract explicitly states `font 12px` for the badge — this is a spec-mandated value that was correctly implemented. However, the Typography section's declared scale does not list 12px. This is an internal inconsistency in the spec itself, not an implementation error. Score penalized for the inconsistency that the implementation surfaces, not for the implementation choice.

**PASS — Font weights:** Only `400` and `500` used in `admin.css`. No `700` (bold) or `600` (semibold) introduced. Weights appear exactly where specified: 500 at `.page-title` (line 63), `.empty-state-heading` (line 278), `.error-banner-heading` (line 305). All other text is `400`.

**PASS — h1 specificity:** `index.css` defines `h1 { font-size: 56px }`. The page title is rendered as `<h1 className="page-title">`. The class selector `.page-title` (specificity 0,1,0) correctly overrides the element selector `h1` (0,0,1), so the 20px heading size wins. Verified by specificity rule.

**PASS — Line heights:** `.page-title` uses `line-height: 1.2` (spec: heading 1.2). Table cells inherit 1.5 from the `body` base. The spec's body line-height is 1.5 — consistent.

**PASS — Font stack:** All components use `font-family: var(--sans)` which resolves to `system-ui, 'Segoe UI', Roboto, sans-serif` as specified.

---

### Pillar 5: Spacing (3/4)

Three off-scale values; no arbitrary `[*px]` values; all spacing is token-consistent otherwise.

**WARNING — `.page-title { margin: 0 0 20px 0 }` (`admin.css:66`) off declared scale:**
The spec's spacing scale jumps from md=16px to lg=24px. 20px is a 4px-grid value but not a named token. The bottom margin of the page title (the gap between the page title and the filter bar or table) is 20px — 4px less than lg but 4px more than md. Neither fits the declared scale cleanly. Fix: use `16px` (md) for a tighter title-to-content gap, or `24px` (lg) for more breathing room.

**WARNING — `.detail-back-link { margin-bottom: 20px }` (`admin.css:326`) off declared scale:**
Same issue — gap between back link and page title on the detail page is 20px. Should be 16px (md) or 24px (lg).

**WARNING — `.page-content { padding: 24px }` vs spec xl=32px (`admin.css:57`):**
The spec states "xl = 32px: Page-level horizontal padding, between major sections." The page-content wrapper uses `padding: 24px` uniformly on all sides. The horizontal padding is 8px narrower than specified. Impact: content sits closer to the edge than the design intended, making the 1126px max-width feel slightly cramped. Fix: change to `padding: 24px 32px` (24px top/bottom, 32px left/right).

**PASS — All other spacing values are on scale:**
- Nav bar padding: `0 24px` (lg) — correct
- Filter bar padding: `12px 16px` — 12px is the tbody cell padding used in the spec's Table component contract (tbody td: padding 12px 16px); consistent
- Filter gap: `16px` (md) — correct
- Filter input padding: `8px 12px` — sm + md blend matching spec's input spec
- Table thead padding: `8px 16px` — exact spec match
- Table tbody padding: `12px 16px` — exact spec match
- Detail dl gap: `12px 0` — matches spec "Gap between rows: 12px"
- Detail dl dt padding-right: `16px` — matches spec
- Ticket section padding-top: `24px` (lg) — matches spec's "24px gap"
- Ticket section margin-top: `8px` — this is the additional visual gap before the border-top; the spec says "separated by 24px gap + 1px border-top." The `detail-dl` has `margin-bottom: 24px`, so the dl-to-border-top distance is 24px (dl margin) + 8px (section margin) = 32px, then 24px inside. The total gap before ticket content is larger than spec intended (32px to border, then 24px inside = 56px total). The 8px margin-top is surplus — fix: change to `margin-top: 0`.
- No arbitrary `[*px]` values anywhere in JSX or CSS.

---

### Pillar 6: Experience Design (4/4)

PASS — Contract fully honored.

**Loading:** Spinner component implemented, shown during `isPending`, with "Cargando..." label (`Spinner.tsx`). `aria-label="Cargando"` on the ring element. All three pages handle loading state.

**Error:** Error banner with `role="alert"` used on all three pages during error state. Heading and body copy match spec exactly.

**Empty:** Both empty state variants (with filter / without filter) correctly differentiated in `GastosListPage.tsx:111-126`. Cierres empty state implemented. All copy matches spec.

**Populated:** Table renders with correct columns, newest-first ordering delegated to backend (per `04-CONTEXT.md` contract). Clickable rows on Gastos list, static rows on Cierres list. Correct cursor classes applied.

**Read-only enforced:** No edit/delete controls anywhere. The `CierresListPage.tsx` comment explicitly notes "No edit/delete controls" and the implementation contains none.

**`formatARS`:** Manual string formatter, no `Intl.NumberFormat` or `toLocaleString`. Correctly produces `$1.234,56` format. The regex `\B(?=(\d{3})+(?!\d))` correctly inserts dots as thousands separators. `parseFloat` handles both string and number input. `isNaN` guard returns `"—"` for invalid input. For the domain (all montos are positive Numeric(14,2) values), behavior is correct. The theoretical negative edge case (`$-1.234,56` vs `-$1.234,56`) is academic.

**`formatDate`:** Splits on `"T"` before parsing to avoid UTC timezone shift (correct and noted in comment). Produces `"31 may 2026"` format with Spanish month abbreviations. `formatDateTime` appends `", HH:MM"` for the "Creado" field.

**React Query:** `staleTime: 30_000` set at QueryClient level and redundantly at each query (acceptable). Keys: `["gastos", { from, to, q }]` for list, `["gastos", id]` for detail, `["cierres"]` for cierres list — matches spec contract.

**API client:** Typed `GastoOut` / `CierreOut` interfaces with `monto`/`efectivo_en_caja` as `string` (Decimal precision preserved). `ticketUrl` constructs the streaming endpoint URL correctly. `VITE_API_URL` env var fallback to `/api` for dev proxy. Query string construction filters out undefined/empty values.

**Registry audit:** shadcn not initialized (`components.json` absent). No third-party component registries. No registry safety section required.

---

## Files Audited

- `/Users/maximolambruschini/NewCombin/compras_agent/.planning/phases/04-admin-ui/04-UI-SPEC.md`
- `/Users/maximolambruschini/NewCombin/compras_agent/.planning/phases/04-admin-ui/04-CONTEXT.md`
- `/Users/maximolambruschini/NewCombin/compras_agent/frontend/src/index.css`
- `/Users/maximolambruschini/NewCombin/compras_agent/frontend/src/admin.css`
- `/Users/maximolambruschini/NewCombin/compras_agent/frontend/src/App.tsx`
- `/Users/maximolambruschini/NewCombin/compras_agent/frontend/src/main.tsx`
- `/Users/maximolambruschini/NewCombin/compras_agent/frontend/src/components/NavTabs.tsx`
- `/Users/maximolambruschini/NewCombin/compras_agent/frontend/src/components/Spinner.tsx`
- `/Users/maximolambruschini/NewCombin/compras_agent/frontend/src/pages/GastosListPage.tsx`
- `/Users/maximolambruschini/NewCombin/compras_agent/frontend/src/pages/GastoDetailPage.tsx`
- `/Users/maximolambruschini/NewCombin/compras_agent/frontend/src/pages/CierresListPage.tsx`
- `/Users/maximolambruschini/NewCombin/compras_agent/frontend/src/utils/formatARS.ts`
- `/Users/maximolambruschini/NewCombin/compras_agent/frontend/src/utils/formatDate.ts`
- `/Users/maximolambruschini/NewCombin/compras_agent/frontend/src/api/client.ts`
- `/Users/maximolambruschini/NewCombin/compras_agent/frontend/index.html`
- `/Users/maximolambruschini/NewCombin/compras_agent/frontend/src/App.css` (orphaned — not imported)
