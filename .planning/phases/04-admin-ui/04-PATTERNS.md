# Phase 4: Admin UI - Pattern Map

**Mapped:** 2026-05-14
**Files analyzed:** 26 new/modified files
**Analogs found:** 20 / 26 (6 are net-new with no codebase analog — use RESEARCH.md patterns)

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/app/routers/admin.py` | router | request-response (CRUD) | `backend/app/routers/health.py` | role-match |
| `backend/app/main.py` | config | request-response | self (modify) | exact |
| `backend/app/schemas/admin.py` | model | transform | `backend/app/models/extraction.py` | role-match |
| `backend/tests/test_admin.py` | test | request-response | `backend/tests/test_health.py` + `test_invoice_service.py` | role-match |
| `frontend/src/App.tsx` | provider/router | request-response | self (replace skeleton) | exact |
| `frontend/src/main.tsx` | config | — | self (unchanged) | exact |
| `frontend/src/index.css` | config | — | self (extend) | exact |
| `frontend/vite.config.ts` | config | — | self (extend) | exact |
| `frontend/package.json` | config | — | self (extend) | exact |
| `frontend/src/pages/InvoiceListPage.tsx` | component/page | request-response | no analog (net-new) | none |
| `frontend/src/pages/InvoiceDetailPage.tsx` | component/page | request-response | no analog (net-new) | none |
| `frontend/src/hooks/useInvoices.ts` | hook | request-response | no analog (net-new) | none |
| `frontend/src/hooks/useInvoice.ts` | hook | request-response | no analog (net-new) | none |
| `frontend/src/lib/api.ts` | utility | request-response | no analog (net-new) | none |
| `frontend/src/components/FilterToolbar.tsx` | component | event-driven | no analog (net-new) | none |
| `frontend/src/components/InvoiceTable.tsx` | component | CRUD | no analog (net-new) | none |
| `frontend/src/components/StatusBadge.tsx` | component | transform | no analog (net-new) | none |
| `frontend/src/components/Pagination.tsx` | component | event-driven | no analog (net-new) | none |
| `frontend/src/components/DataPanel.tsx` | component | request-response | no analog (net-new) | none |
| `frontend/src/components/ImagePanel.tsx` | component | file-I/O | no analog (net-new) | none |
| `frontend/src/components/InvoiceHeader.tsx` | component | transform | no analog (net-new) | none |
| `frontend/src/components/ActionBar.tsx` | component | event-driven | no analog (net-new) | none |
| `frontend/src/components/LineItemsTable.tsx` | component | CRUD | no analog (net-new) | none |
| `frontend/src/components/EditDocumentModal.tsx` | component | CRUD | no analog (net-new) | none |
| `frontend/src/components/EditLineItemModal.tsx` | component | CRUD | no analog (net-new) | none |
| `frontend/src/components/DeleteConfirmation.tsx` | component | event-driven | no analog (net-new) | none |
| `frontend/src/components/FormField.tsx` | component | transform | no analog (net-new) | none |
| `frontend/src/components/ErrorBanner.tsx` | component | transform | no analog (net-new) | none |
| `frontend/src/components/LoadingSpinner.tsx` | component | transform | no analog (net-new) | none |

---

## Pattern Assignments

### `backend/app/routers/admin.py` (router, request-response CRUD)

**Analog:** `backend/app/routers/health.py` (DB session inject) + `backend/app/routers/extraction.py` (settings inject + HTTPException)

**Imports pattern** (health.py lines 1–8, extraction.py lines 17–23):
```python
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings, get_settings
from app.db.models import Invoice, InvoiceLineItem
from app.db.session import get_db

router = APIRouter()
```

**DB session inject pattern** (health.py lines 12–18):
```python
@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    await db.execute(
        select(func.count()).select_from(SenderAllowlist)
    )
    return {"status": "ok", "db": "connected"}
```
Apply same `db: AsyncSession = Depends(get_db)` to all admin endpoints that touch the DB.

**Settings inject pattern** (extraction.py lines 27–42):
```python
def get_extraction_service(
    settings: Settings = Depends(get_settings),
) -> ExtractionService:
    ...
```
For `/images/{filename}`, inject `settings: Settings = Depends(get_settings)` directly on the endpoint (no wrapper needed since there is no service class for admin).

**HTTPException pattern** (extraction.py lines 58–62):
```python
if len(data) > 10 * 1024 * 1024:
    raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")
```
Use `raise HTTPException(status_code=404, detail="Invoice not found")` for missing invoice lookups; `raise HTTPException(status_code=400, detail="Invalid filename")` for path traversal guard.

**UUID path param pattern** — Invoice.id is UUID (models.py line 38); must convert string path param before querying:
```python
import uuid
# In endpoint body:
try:
    invoice_uuid = uuid.UUID(invoice_id)
except ValueError:
    raise HTTPException(status_code=422, detail="Invalid UUID format")
result = await db.execute(
    select(Invoice).where(Invoice.id == invoice_uuid)
)
invoice = result.scalar_one_or_none()
if invoice is None:
    raise HTTPException(status_code=404, detail="Invoice not found")
```

**selectinload pattern** (RESEARCH.md Anti-Patterns — required for detail endpoint):
```python
from sqlalchemy.orm import selectinload
result = await db.execute(
    select(Invoice)
    .where(Invoice.id == invoice_uuid)
    .options(selectinload(Invoice.line_items))
)
invoice = result.scalar_one_or_none()
```
Never use `session.get(Invoice, id)` for the detail endpoint — it does NOT load `.line_items` in async mode.

**Path traversal guard pattern** (RESEARCH.md Pattern 8):
```python
import pathlib

@router.get("/images/{filename}")
async def serve_image(
    filename: str = Path(..., pattern=r"^[^/\\]+$"),
    settings: Settings = Depends(get_settings),
):
    storage_root = pathlib.Path(settings.storage_path).resolve()
    file_path = (storage_root / filename).resolve()
    if not str(file_path).startswith(str(storage_root)):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(file_path))
```

**Pagination + filter query pattern** (RESEARCH.md Code Examples):
```python
from sqlalchemy import func, or_

@router.get("/invoices")
async def list_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    proveedor: str | None = Query(None),
    fecha_from: str | None = Query(None),
    fecha_to: str | None = Query(None),
    q: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Invoice).order_by(Invoice.created_at.desc())
    if status:
        stmt = stmt.where(Invoice.status == status)
    if proveedor:
        stmt = stmt.where(func.lower(Invoice.proveedor).like(f"%{proveedor.lower()}%"))
    if q:
        search = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Invoice.proveedor).like(search),
                func.lower(Invoice.numero_documento).like(search),
            )
        )
    # Total count — apply same filters before pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()
    # Paginate
    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)
    invoices = (await db.execute(stmt)).scalars().all()
    return {"items": invoices, "total": total, "page": page, "page_size": page_size}
```

---

### `backend/app/main.py` (config, modify existing)

**Analog:** self — lines 35–62 define the `create_app()` factory.

**Current router registration pattern** (main.py lines 43–57):
```python
def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Compras Agent API", lifespan=lifespan, debug=settings.debug)

    # Import router inside factory — avoids circular import at module init time
    from app.routers.health import router as health_router
    app.include_router(health_router)

    if settings.debug:
        from app.routers.extraction import router as extraction_router
        app.include_router(extraction_router, prefix="/extraction", tags=["extraction"])

    from app.routers.whatsapp import router as whatsapp_router
    app.include_router(whatsapp_router, prefix="/whatsapp", tags=["whatsapp"])

    return app
```

**Required additions** — insert in this exact order (CORS MUST come before include_router calls):
```python
def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(...)

    # 1. CORS — must be first middleware, before any include_router (RESEARCH.md Pitfall 5)
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # 2. Existing routers (unchanged)
    from app.routers.health import router as health_router
    app.include_router(health_router)
    ...

    # 3. New admin router — always registered (no debug gate)
    from app.routers.admin import router as admin_router
    app.include_router(admin_router, tags=["admin"])

    return app
```

---

### `backend/app/schemas/admin.py` (model, transform)

**Analog:** `backend/app/models/extraction.py` — Pydantic BaseModel definitions using Optional fields with None defaults.

**Pydantic model pattern** (from models/extraction.py — Pydantic v2 style):
```python
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
import uuid
from pydantic import BaseModel

class LineItemResponse(BaseModel):
    id: int
    invoice_id: uuid.UUID
    descripcion: Optional[str] = None
    codigo_sku: Optional[str] = None
    bultos: Optional[Decimal] = None
    unidades_por_bulto: Optional[Decimal] = None
    precio_unitario_sin_iva: Optional[Decimal] = None
    descuento_pct: Optional[Decimal] = None
    iva_rate: Optional[Decimal] = None
    percepciones_iibb: Optional[Decimal] = None

    model_config = {"from_attributes": True}   # Pydantic v2 ORM mode

class InvoiceListItem(BaseModel):
    id: uuid.UUID
    tipo_comprobante: Optional[str] = None
    numero_documento: Optional[str] = None
    proveedor: Optional[str] = None
    fecha: Optional[date] = None
    status: str
    confidence_score: Optional[Decimal] = None
    created_at: datetime
    model_config = {"from_attributes": True}

class InvoiceDetailResponse(InvoiceListItem):
    cuit_proveedor: Optional[str] = None
    cae: Optional[str] = None
    fecha_vencimiento_cae: Optional[date] = None
    image_path: Optional[str] = None
    updated_at: datetime
    line_items: list[LineItemResponse] = []
    # NOTE: raw_extraction is intentionally excluded (not exposed to frontend)

class InvoiceListResponse(BaseModel):
    items: list[InvoiceListItem]
    total: int
    page: int
    page_size: int

class InvoiceDocumentPatch(BaseModel):
    tipo_comprobante: Optional[str] = None
    numero_documento: Optional[str] = None
    proveedor: Optional[str] = None
    fecha: Optional[date] = None
    cuit_proveedor: Optional[str] = None
    cae: Optional[str] = None
    fecha_vencimiento_cae: Optional[date] = None

class LineItemPatch(BaseModel):
    descripcion: Optional[str] = None
    codigo_sku: Optional[str] = None
    bultos: Optional[Decimal] = None
    unidades_por_bulto: Optional[Decimal] = None
    precio_unitario_sin_iva: Optional[Decimal] = None
    descuento_pct: Optional[Decimal] = None
    iva_rate: Optional[Decimal] = None
    percepciones_iibb: Optional[Decimal] = None

class InvoiceStatusPatch(BaseModel):
    status: str  # "confirmed" | "rejected"
```

**Key field exclusions** (from RESEARCH.md field inventory):
- Do NOT expose: `raw_extraction`, `whatsapp_message_id`, `sender_phone` (internal processing fields)
- Do NOT allow PATCH on: `id`, `confidence_score`, `image_path`, `created_at`, `updated_at`

---

### `backend/tests/test_admin.py` (test, request-response)

**Analog:** `backend/tests/test_health.py` (ASGI client + dependency override) + `backend/tests/test_invoice_service.py` (Invoice seeding helpers)

**ASGI test client fixture pattern** (test_health.py lines 15–28 — copy exactly):
```python
import pytest
import pytest_asyncio
import httpx

from app.db.session import get_db

@pytest_asyncio.fixture
async def client(db_session):
    """Function-scoped ASGI test client wired to the test DB session."""
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    app.dependency_overrides.clear()
```
This fixture is inherited from conftest.py's `db_session` (aiosqlite in-memory). The `env_setup` session-scoped fixture in conftest.py patches all required env vars automatically — no additional patching needed.

**Invoice seeding helper pattern** (test_invoice_service.py lines 82–97):
```python
from app.db.models import Invoice, InvoiceLineItem

def _seed_invoice(
    numero: str = "0001-00000001",
    proveedor: str = "Acme SA",
    status: str = "pending_review",
) -> Invoice:
    return Invoice(
        tipo_comprobante="FACTURA_A",
        numero_documento=numero,
        proveedor=proveedor,
        fecha=date(2026, 5, 10),
        status=status,
        image_path="/tmp/invoices/test.jpg",
    )

def _seed_line_item(invoice_id) -> InvoiceLineItem:
    return InvoiceLineItem(
        invoice_id=invoice_id,
        descripcion="Harina 000",
        codigo_sku="SKU-001",
        bultos=Decimal("10"),
        precio_unitario_sin_iva=Decimal("100.00"),
        iva_rate=Decimal("0.21"),
    )
```

**Test structure pattern** (test_health.py lines 31–51):
```python
@pytest.mark.asyncio
async def test_list_invoices_empty(client):
    """GET /invoices returns empty list when no invoices exist."""
    response = await client.get("/invoices")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0

@pytest.mark.asyncio
async def test_list_invoices_filter_status(client, db_session):
    """GET /invoices?status=pending_review returns only matching rows."""
    db_session.add(_seed_invoice(status="pending_review"))
    db_session.add(_seed_invoice(numero="0001-002", status="confirmed"))
    await db_session.commit()

    response = await client.get("/invoices?status=pending_review")
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["status"] == "pending_review"
```

**Note on aiosqlite UUID behavior:** SQLite stores UUIDs as strings. When seeding, `Invoice.id` auto-generates via `default=uuid.uuid4`. Use `str(invoice.id)` when constructing URL paths in tests: `await client.get(f"/invoices/{invoice.id}")`.

---

### `frontend/src/App.tsx` (provider/router, replace skeleton)

**Analog:** self — current file is 10-line skeleton. Replace entirely per RESEARCH.md Pattern 3.

**Full replacement pattern** (RESEARCH.md Pattern 3):
```tsx
import { BrowserRouter, Routes, Route } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import InvoiceListPage from "./pages/InvoiceListPage";
import InvoiceDetailPage from "./pages/InvoiceDetailPage";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<InvoiceListPage />} />
          <Route path="/invoices/:id" element={<InvoiceDetailPage />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
```
**Critical:** Import from `"react-router"` not `"react-router-dom"` — v7 merged the packages.

---

### `frontend/vite.config.ts` (config, extend)

**Analog:** self — current file (lines 1–19). Extend with tailwindcss plugin + path alias + proxy routes.

**Current file** (vite.config.ts lines 1–19):
```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiTarget = process.env.VITE_API_URL || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': apiTarget,
      '/health': apiTarget,
    },
  },
})
```

**Required additions** (RESEARCH.md Pattern 1):
```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

const apiTarget = process.env.VITE_API_URL || 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),  // required by shadcn
    },
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': apiTarget,
      '/health': apiTarget,
      '/invoices': apiTarget,
      '/images': apiTarget,   // Note: <img src> bypasses proxy; CORS covers images
    },
  },
})
```

---

### `frontend/src/index.css` (config, extend)

**Analog:** self — current file (lines 1–112). Must be restructured in Wave 0.

**Current problematic `#root` block** (index.css lines 53–63 — MUST replace):
```css
#root {
  width: 1126px;        /* ← conflicts with full-width admin table layout */
  max-width: 100%;
  margin: 0 auto;
  text-align: center;   /* ← conflicts with left-aligned data grid */
  border-inline: 1px solid var(--border);
  min-height: 100svh;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}
```

**Existing tokens to keep** (index.css lines 2–30, `--text`, `--bg`, `--border`, `--sans`, `--heading`, `--mono`, dark mode variants). The scaffold purple accent (`--accent: #aa3bff`) is replaced by admin blue.

**Required new structure** (RESEARCH.md Pattern 1 + UI-SPEC color tokens):
```css
@import "tailwindcss";   /* shadcn init writes this; ensure no duplicate */

:root {
  /* --- existing tokens (keep all) --- */
  --text: #6b6375;
  --text-h: #08060d;
  --bg: #fff;
  --border: #e5e4e7;
  --code-bg: #f4f3ec;
  --sans: system-ui, 'Segoe UI', Roboto, sans-serif;
  --heading: system-ui, 'Segoe UI', Roboto, sans-serif;
  --mono: ui-monospace, Consolas, monospace;

  /* --- new admin tokens (D-15, UI-SPEC) --- */
  --accent-admin: #2563eb;
  --accent-admin-bg: rgba(37, 99, 235, 0.08);
  --destructive: #dc2626;
  --destructive-hover: #b91c1c;
  --pending-bg: #fef3c7;
  --pending-badge: #d97706;
  --surface-secondary: #f8f7fa;

  font: 14px/1.5 var(--sans);
  color: var(--text);
  background: var(--bg);
}

/* shadcn init will append @theme inline { ... } block below this — do not edit */

#root {
  min-height: 100svh;
  box-sizing: border-box;
  /* Width and text-align removed — admin layout uses Tailwind classes */
}
```

**Pitfall (RESEARCH.md Pitfall 3):** Let shadcn write `@import "tailwindcss"` during `npx shadcn@latest init`, then add custom tokens manually after. Do not pre-add the import and run shadcn — it may duplicate the import.

---

### `frontend/src/hooks/useInvoices.ts` (hook, request-response)

**No codebase analog** — net-new pattern. Use RESEARCH.md Pattern 4 directly.

**Pattern to implement** (RESEARCH.md Pattern 4):
```typescript
import { useQuery } from "@tanstack/react-query";
import { fetchInvoices } from "../lib/api";
import type { InvoiceListParams } from "../types/invoice";

export function useInvoices(params: InvoiceListParams) {
  return useQuery({
    queryKey: ["invoices", params],
    queryFn: () => fetchInvoices(params),
  });
}
```
`queryKey: ["invoices", params]` — params object included so filter changes trigger re-fetch.

---

### `frontend/src/hooks/useInvoice.ts` (hook, request-response)

**No codebase analog** — net-new pattern. Use RESEARCH.md Pattern 4 directly.

```typescript
import { useQuery } from "@tanstack/react-query";
import { fetchInvoice } from "../lib/api";

export function useInvoice(id: string) {
  return useQuery({
    queryKey: ["invoice", id],
    queryFn: () => fetchInvoice(id),
    enabled: !!id,  // don't fetch if id is empty
  });
}
```

---

### `frontend/src/lib/api.ts` (utility, request-response)

**No codebase analog** — net-new pattern. Use RESEARCH.md Pattern 7 directly.

**Core fetch wrapper** (RESEARCH.md Pattern 7):
```typescript
const BASE_URL = import.meta.env.VITE_API_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}
```

**Image URL note:** `imageUrl` function is NOT a fetch call — it constructs a URL string for `<img src>`:
```typescript
export const imageUrl = (imagePath: string) => {
  // imagePath is a local filesystem path like "/data/invoices/abc.jpg"
  // Extract filename only — backend serves from storage_path root
  const filename = imagePath.split('/').pop() ?? imagePath;
  return `${BASE_URL}/images/${filename}`;
};
```

---

### Frontend Components (all net-new, no codebase analog)

All React components follow these shared patterns from RESEARCH.md and UI-SPEC.md:

**shadcn import pattern:**
```tsx
import { Button } from "@/components/ui/button";
import { Badge } from "@/components//ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Alert, AlertDescription } from "@/components/ui/alert";
```
Note: `@/` resolves to `src/` via the vite.config.ts alias.

**useMutation with dual invalidation** (RESEARCH.md Pattern 4 — all edit/status/delete mutations):
```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query";

const queryClient = useQueryClient();
const mutation = useMutation({
  mutationFn: (data: InvoiceDocumentPatch) => patchInvoice(id, data),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ["invoice", id] });
    queryClient.invalidateQueries({ queryKey: ["invoices"] });
  },
});

// Pending state check — use isPending NOT isLoading (TQ v5 rename)
<Button disabled={mutation.isPending}>
  {mutation.isPending ? <LoadingSpinner /> : "Guardar cambios"}
</Button>
```

**Navigation hooks** (RESEARCH.md Pattern 3):
```tsx
import { useParams, useNavigate, Link } from "react-router";

// In InvoiceDetailPage:
const { id } = useParams<{ id: string }>();
const navigate = useNavigate();

// After delete success:
navigate("/");
```

**`pending_review` amber row** (RESEARCH.md Pitfall 6 — use literal Tailwind class):
```tsx
// In InvoiceTable row:
<TableRow
  key={invoice.id}
  className={invoice.status === "pending_review" ? "bg-amber-50" : ""}
>
```
Do NOT use `"bg-" + color` string concatenation — Tailwind v4 strips dynamic class names in production build.

**Responsive grid pattern** (UI-SPEC Responsive Design Contract):
```tsx
// InvoiceDetailPage layout:
<div className="grid grid-cols-1 md:grid-cols-2 gap-8">
  <DataPanel invoice={invoice} />
  <div className="md:sticky md:top-6">
    <ImagePanel imagePath={invoice.image_path} proveedor={invoice.proveedor} />
  </div>
</div>

// FilterToolbar:
<div className="flex flex-col md:flex-row md:flex-wrap gap-2">
  {/* inputs */}
  <Button className="w-full md:w-auto">Filtrar</Button>
</div>

// ActionBar buttons:
<div className="flex flex-col md:flex-row gap-2 md:gap-3">
  <Button className="w-full md:w-auto">Confirmar</Button>
  <Button variant="outline" className="w-full md:w-auto">Rechazar</Button>
</div>
```

**Mobile table column hiding** (UI-SPEC — only Proveedor, Estado, Total on mobile):
```tsx
<TableHead className="hidden md:table-cell">Tipo</TableHead>
<TableHead className="hidden md:table-cell">Número</TableHead>
<TableHead className="hidden md:table-cell">Fecha</TableHead>

<TableCell className="hidden md:table-cell">{invoice.tipo_comprobante}</TableCell>
```

---

## Shared Patterns

### DB Session Injection
**Source:** `backend/app/routers/health.py` lines 12–18
**Apply to:** All admin router endpoints that read/write the DB
```python
async def endpoint_name(db: AsyncSession = Depends(get_db)):
    # all queries use await
    result = await db.execute(select(Invoice)...)
    await db.commit()  # after mutations only
```

### Settings Injection
**Source:** `backend/app/routers/extraction.py` lines 27–42
**Apply to:** `serve_image` endpoint in admin router (needs `settings.storage_path`)
```python
async def serve_image(
    filename: str = Path(..., pattern=r"^[^/\\]+$"),
    settings: Settings = Depends(get_settings),
):
    ...
```

### Test DB Session Override
**Source:** `backend/tests/test_health.py` lines 15–28 — the `client` fixture
**Apply to:** `backend/tests/test_admin.py` — copy the fixture verbatim; it already wires the aiosqlite in-memory test engine via conftest.py's `db_session`
```python
@pytest_asyncio.fixture
async def client(db_session):
    from app.main import app
    async def override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = override_get_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    app.dependency_overrides.clear()
```

### Invoice ORM Seeding in Tests
**Source:** `backend/tests/test_invoice_service.py` lines 82–97 — `_seed_invoice()`
**Apply to:** All `test_admin.py` test functions that need DB rows
```python
def _seed_invoice(numero="0001-00000001", proveedor="Acme SA", status="pending_review") -> Invoice:
    return Invoice(
        tipo_comprobante="FACTURA_A",
        numero_documento=numero,
        proveedor=proveedor,
        fecha=date(2026, 5, 10),
        status=status,
        image_path="/tmp/invoices/test.jpg",
    )
# Usage:
db_session.add(_seed_invoice())
await db_session.commit()
```

### Pydantic v2 ORM Mode
**Source:** Pattern established by `backend/app/models/extraction.py` (BaseModel + model_config)
**Apply to:** All Pydantic response models in `backend/app/schemas/admin.py`
```python
class InvoiceDetailResponse(BaseModel):
    ...
    model_config = {"from_attributes": True}  # replaces orm_mode=True from v1
```

### TanStack Query Error State
**Apply to:** All page components (`InvoiceListPage`, `InvoiceDetailPage`)
```tsx
const { data, isPending, error } = useInvoices(params);

if (isPending) return <LoadingSpinner />;
if (error) return <ErrorBanner message="No se pudo cargar la lista de facturas." />;
```
Note: for queries, use `isPending` to check first-load state; `isFetching` for background refetch indicator.

### Argentine Locale Formatters
**Source:** RESEARCH.md Code Examples — no codebase analog yet; define in `lib/api.ts` or a `lib/format.ts` utility
```typescript
export const formatCurrency = (value: number | string | null | undefined): string => {
  if (value == null) return "—";
  return "$ " + Number(value).toLocaleString("es-AR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
};

export const formatDate = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
};
```

---

## No Analog Found

All frontend component files are net-new (no existing React components in the codebase). Use RESEARCH.md and UI-SPEC.md patterns as the primary reference for these.

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `frontend/src/pages/InvoiceListPage.tsx` | component/page | request-response | No existing pages — App.tsx is a bare skeleton |
| `frontend/src/pages/InvoiceDetailPage.tsx` | component/page | request-response | No existing pages |
| `frontend/src/components/*.tsx` (all 14) | component | various | No existing components |
| `frontend/src/hooks/useInvoices.ts` | hook | request-response | No existing hooks |
| `frontend/src/hooks/useInvoice.ts` | hook | request-response | No existing hooks |
| `frontend/src/lib/api.ts` | utility | request-response | No existing API client |

**For all net-new frontend files:** follow RESEARCH.md Patterns 3–7 exactly. The shadcn/ui components (`src/components/ui/`) are generated by `npx shadcn@latest add` — do not hand-write them.

---

## Critical Sequencing Notes for Planner

These ordering constraints must be reflected in Wave 0:

1. **CORS before admin router** — `app.add_middleware(CORSMiddleware, ...)` must be the first line after `app = FastAPI(...)` in `create_app()`, before all `app.include_router()` calls.
2. **Tailwind before shadcn** — `npm install tailwindcss @tailwindcss/vite` and vite.config.ts change must happen before `npx shadcn@latest init` (shadcn detects Tailwind version).
3. **shadcn init before shadcn add** — `npx shadcn@latest init` must run before individual `npx shadcn@latest add button` etc.
4. **`#root` CSS fix before component dev** — the constrained `#root { width: 1126px }` block in `index.css` must be replaced before any layout component is built, or all layouts will appear wrong.
5. **`tsconfig.app.json` alias before shadcn** — the `@/*` path alias must be in `tsconfig.app.json` before `npx shadcn@latest init`, which writes `@/components/ui/` imports into generated component files.

---

## Metadata

**Analog search scope:** `backend/app/routers/`, `backend/app/`, `backend/tests/`, `frontend/src/`
**Files scanned:** 12 existing files read directly; directory listings for tests/
**Pattern extraction date:** 2026-05-14
