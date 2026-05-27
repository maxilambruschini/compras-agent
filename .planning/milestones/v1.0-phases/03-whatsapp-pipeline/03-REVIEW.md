---
phase: 03-whatsapp-pipeline
status: fixed
files_reviewed: 16
depth: standard
findings:
  critical: 1
  warning: 1
  info: 2
  total: 4
reviewed_at: 2026-05-14T17:50:00Z
---

## Code Review — Phase 03: WhatsApp Pipeline

### CR-01 — Critical (FIXED)

**`_compute_total` divides `iva_rate` by 100 but it is already stored as a fraction**

File: `backend/app/routers/whatsapp.py:230`

The `ExtractedInvoice` Pydantic model (Phase 2) stores `iva_rate` as a fraction — `0.21` means 21%. The router's `_compute_total` function applied an additional `/Decimal("100")` division, producing `0.0021` (0.21% IVA) instead of `0.21` (21% IVA). Test fixtures in `test_whatsapp.py` and `test_invoice_service.py` compensated with `Decimal("21")`, masking the error in the test suite but yielding wrong totals in production.

Fixed in commit `4e7d482`: removed the `/Decimal("100")` division; updated all fixtures to `Decimal("0.21")`; confirmed `2 × $100 × 1.21 = $242.00` assertion passes.

---

### WR-01 — Warning

**`asyncio.create_task` background task can be garbage-collected before completion**

File: `backend/app/routers/whatsapp.py` (process_invoice task dispatch)

`asyncio.create_task` without holding a reference to the task object allows the GC to cancel it mid-flight if the event loop has no other reference. Under load, this can silently drop invoice processing.

Documented as a v1 known limitation in the plan and code. Upgrade path: use a task registry (`_background_tasks: set` + `task.add_done_callback(_background_tasks.discard)`) or move to a proper queue (Celery, ARQ). Not blocking for v1 single-company deployment.

---

### IN-01 — Info

**`MetaCloudProvider` is a non-functional stub**

File: `backend/app/providers/meta.py`

All methods raise `NotImplementedError`. Acceptable for v1 (Twilio-only), but the stub should log a warning on instantiation so it surfaces in logs if accidentally wired.

---

### IN-02 — Info

**`docker-compose.yml` exposes Postgres port 5432 to host by default**

File: `docker-compose.yml`

Port 5432 is bound to `0.0.0.0:5432` in the compose file. Fine for local dev; should be removed or changed to `127.0.0.1:5432` before any cloud/staging deployment.

---

## Summary

One critical bug found and fixed (IVA rate unit mismatch). One architectural warning (task durability) already documented as a v1 limitation. Two informational items, neither blocking.

All 76 non-integration tests pass after fix.
