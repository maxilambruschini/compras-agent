---
phase: 04-admin-ui
reviewed: 2026-05-31T04:15:00Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - backend/app/routers/admin.py
  - backend/app/main.py
  - frontend/src/api/client.ts
  - frontend/src/pages/GastosListPage.tsx
  - frontend/src/pages/GastoDetailPage.tsx
  - frontend/src/pages/CierresListPage.tsx
  - frontend/src/utils/formatARS.ts
findings:
  critical: 0
  warning: 3
  info: 2
  total: 5
status: issues_found
---

# Phase 4: Code Review Report

**Reviewed:** 2026-05-31T04:15:00Z
**Depth:** standard
**Files Reviewed:** 7
**Status:** issues_found

## Summary

Seven files reviewed: four backend endpoints (`admin.py`, `main.py`) and three frontend pages plus the API client and ARS formatter. The path-traversal guard (`realpath` + `commonpath`) is correctly implemented and blocks all traversal attempts including absolute-path ticket paths and symlink-based escapes. The ilike parameterization is correctly bound (SQLAlchemy passes the pattern as a bind parameter). Decimal serialization from Pydantic v2 arrives as a string on the frontend; `parseFloat` precision is safe for `Numeric(14,2)` (14 significant digits fit within IEEE 754 double's 15-16 digit range). React Query key structure is correct — list and detail keys are distinct and filter changes correctly trigger new fetches. The committed-only boundary is sound by schema design (all rows in `gastos` are committed; no status column to forget).

Three issues require attention before production deployment: unescaped LIKE wildcards in the `q` search parameter produce incorrect results when users type `%` or `_`; `allow_origins` is hardcoded to `localhost:5173` and will silently reject all browser requests in any non-dev deployment; and the admin endpoints carry no authentication, exposing all invoice data to any network-accessible client.

---

## Warnings

### WR-01: ILIKE Wildcards in `q` Pass Through Unescaped — Incorrect Search Results

**File:** `backend/app/routers/admin.py:95`
**Issue:** The `q` filter builds the ILIKE pattern with `f"%{q.strip()}%"` and passes it as a bind parameter — so there is no SQL injection. However, PostgreSQL ILIKE interprets `%` and `_` within the pattern as wildcards. A user searching for `"cafe 25%"` matches any concepto starting with `"cafe 25"` followed by anything, not the literal string `"cafe 25%"`. A search for `"pan_dulce"` matches any single character in place of `_`. This silently produces wrong result sets with no error or warning to the user.

**Fix:**
```python
# In list_gastos, escape LIKE special characters before building the pattern
if q and q.strip():
    escaped = (
        q.strip()
        .replace("\\", "\\\\")   # escape the escape char first
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    stmt = stmt.where(Gasto.concepto.ilike(f"%{escaped}%", escape="\\"))
```

---

### WR-02: `allow_origins` Hardcoded to `localhost:5173` — Production CORS Rejection

**File:** `backend/app/main.py:49`
**Issue:** `CORSMiddleware` is configured with `allow_origins=["http://localhost:5173"]`. In a production deployment (Docker Compose with a real domain, or any host other than the developer's machine), all browser preflight and cross-origin requests will be rejected with a CORS error — the UI goes blank with no useful error message. This requires a code change (not just an env var) to fix after deployment.

**Fix:** Read the allowed origin from settings so it can be injected without touching code:
```python
# config.py — add field
allowed_origins: list[str] = ["http://localhost:5173"]

# main.py — use settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)
```
`ALLOWED_ORIGINS=https://compras.example.com` in the production `.env` is then sufficient to configure it without a redeploy.

---

### WR-03: Admin Endpoints Have No Authentication

**File:** `backend/app/routers/admin.py:72,100,116,160`
**Issue:** All four admin endpoints (`GET /api/gastos`, `GET /api/gastos/{id}`, `GET /api/gastos/{id}/ticket`, `GET /api/cierres`) accept requests without any credential check. Any process that can reach the backend's port — including other containers in the same Docker network, or any internet host if the port is inadvertently exposed — can read all invoice amounts, phone numbers, and ticket images without restriction. The Phase 4 spec intentionally deferred auth, but this is a pre-production blocker that must be resolved before the app receives real company data.

**Fix:** Add a shared-secret bearer token guard (consistent with the `gastos_prompt_token` pattern already used in `routers/prompt.py`):
```python
from fastapi import Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer()

def verify_admin_token(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.admin_token or credentials.credentials != settings.admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")

# Then add to each endpoint:
@router.get("/gastos", response_model=list[GastoOut])
async def list_gastos(
    ...,
    _: None = Depends(verify_admin_token),
) -> list[GastoOut]:
```

---

## Info

### IN-01: `window.open` Without `noopener` on Ticket Image Click

**File:** `frontend/src/pages/GastoDetailPage.tsx:85`
**Issue:** `window.open(ticketUrl, "_blank")` opens the ticket image in a new tab without `rel="noopener noreferrer"`. The opened page gains a reference back to the opener via `window.opener`, which allows the new tab to navigate the original tab (tab-napping). The risk is low because the target URL is the same backend origin, but it is still a best-practice violation that browsers flag in audits.

**Fix:**
```tsx
<img
  src={ticketUrl}
  alt="Ticket de gasto"
  className="ticket-image"
  onClick={() => window.open(ticketUrl, "_blank", "noopener,noreferrer")}
/>
```
Alternatively, wrap in an `<a href={ticketUrl} target="_blank" rel="noopener noreferrer">` and remove the `onClick` handler.

---

### IN-02: 404 on Detail Page Shows Generic Error, Not "Not Found" Message

**File:** `frontend/src/pages/GastoDetailPage.tsx:38-45`
**Issue:** When `GET /api/gastos/{id}` returns 404 (gasto deleted or UUID invalid), the error banner reads _"No se pudo cargar la información / Ocurrió un error al conectar con el servidor"_ — the same message shown for a network outage. A user who bookmarks a gasto ID that gets removed sees misleading messaging suggesting a server connectivity problem rather than a missing record.

**Fix:** Inspect the error message to differentiate 404 from network errors:
```tsx
const isNotFound = error?.message?.includes("404");
// Then in the banner body:
{isNotFound
  ? "Este gasto no existe o fue eliminado."
  : "Ocurrió un error al conectar con el servidor. Recargá la página para reintentar."}
```

---

_Reviewed: 2026-05-31T04:15:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
