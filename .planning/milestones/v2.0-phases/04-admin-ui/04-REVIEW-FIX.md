---
phase: 04-admin-ui
fixed_at: 2026-05-31T04:15:00Z
review_path: .planning/phases/04-admin-ui/04-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 3
skipped: 1
status: partial
---

# Phase 4: Code Review Fix Report

**Fixed at:** 2026-05-31T04:15:00Z
**Source review:** .planning/phases/04-admin-ui/04-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 4 (WR-01, WR-02, WR-03, IN-01)
- Fixed: 3 (WR-01, WR-02, IN-01)
- Skipped: 1 (WR-03 — locked decision, explicitly excluded)

## Fixed Issues

### WR-01: ILIKE Wildcards in `q` Pass Through Unescaped

**Files modified:** `backend/app/routers/admin.py`, `backend/tests/test_admin.py`
**Commit:** `0a53a60`
**Applied fix:** In `list_gastos`, the user-supplied `q` parameter is now escaped before building the ILIKE pattern: `\` is escaped first (to `\\`), then `%` → `\%`, then `_` → `\_`. The `.ilike()` call passes `escape="\\"` so PostgreSQL treats these as literal characters rather than wildcards. A new test `test_list_gastos_search_percent_literal` seeds one concepto with a literal `%` ("Descuento 50%") and one without ("Descuento 500 pesos"), searches for `"50%"`, and asserts only the literal match returns. Test suite: 184 passed, 1 skipped.

### WR-02: `allow_origins` Hardcoded to `localhost:5173`

**Files modified:** `backend/app/config.py`, `backend/app/main.py`
**Commit:** `f90589c`
**Applied fix:** Added `allowed_origins: list[str] = ["http://localhost:5173"]` to `Settings` in `config.py` (with a comment explaining pydantic-settings parses a JSON array from env). Updated `create_app()` in `main.py` to pass `settings.allowed_origins` instead of the hardcoded list. The default value is identical to the previous hardcoded value so `test_cors_header` and the dev workflow continue to pass unchanged. Production deployments can now set `ALLOWED_ORIGINS='["https://compras.example.com"]'` without a code change.

### IN-01: `window.open` Without `noopener` on Ticket Image Click

**Files modified:** `frontend/src/pages/GastoDetailPage.tsx`
**Commit:** `d10c815`
**Applied fix:** Added `"noopener,noreferrer"` as the third argument to `window.open(ticketUrl, "_blank", "noopener,noreferrer")`. This prevents the opened tab from accessing `window.opener` and navigating the parent tab (tab-napping). Frontend build and lint both exit 0.

## Skipped Issues

### WR-03: Admin Endpoints Have No Authentication

**File:** `backend/app/routers/admin.py:72,100,116,160`
**Reason:** Explicitly excluded by project instructions — this is a locked decision. `04-CONTEXT.md` and the project scope specify no authentication for the Phase 4 demo (admin auth deferred to v3). Adding authentication would violate the locked decision. The finding remains documented as a deferred pre-production item.
**Original issue:** All four admin endpoints accept requests without any credential check, exposing invoice data to any network-accessible client.

---

_Fixed: 2026-05-31T04:15:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
