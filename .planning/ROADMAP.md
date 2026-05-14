# Roadmap: Compras Agent

## Overview

Four phases take the project from zero to a fully working WhatsApp invoice capture system. Phase 1 locks the data contract (schema + Pydantic models + Docker scaffold) that everything else depends on. Phase 2 builds the AI extraction pipeline in isolation so it can be tested without WhatsApp. Phase 3 wires the end-to-end pipeline: WhatsApp receives a photo and the invoice lands in the database with a reply sent back. Phase 4 delivers the React admin UI so managers can review, edit, and manage all captured invoices.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Foundation** - Docker Compose scaffold, Postgres schema, Pydantic models, environment wiring (completed 2026-05-13)
- [ ] **Phase 2: Extraction Pipeline** - GPT-4o vision extraction service, confidence scoring, storage, testable in isolation
- [x] **Phase 3: WhatsApp Pipeline** - End-to-end webhook receive → extract → store → reply (completed 2026-05-14)
- [ ] **Phase 4: Admin UI** - React admin interface for invoice list, detail, edit, search, and delete

## Phase Details

### Phase 1: Foundation
**Goal**: The complete data contract exists — Docker services are running, Postgres schema is migrated, Pydantic extraction models are defined, and the project can be started with `docker compose up`
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: INF-01, INF-03
**Success Criteria** (what must be TRUE):
  1. `docker compose up` starts FastAPI, Postgres, and (stub) frontend containers without errors
  2. All database tables exist with correct columns, constraints, and indexes after migrations run
  3. The allowlist table exists and can be seeded with employee phone numbers
  4. `ExtractedInvoice` Pydantic model and all supporting enums/types can be imported and instantiated without errors
  5. All secrets (OpenAI key, WhatsApp token, DB URL) are loaded from environment variables; the app refuses to start if required vars are missing
**Plans:** 2/2 plans complete
Plans:
- [ ] 01-PLAN-data-contract.md — Pydantic Settings + SQLAlchemy ORM schema + Alembic async scaffold + Wave 0 pytest suite (INF-01 schema, INF-03 fail-fast)
- [ ] 01-PLAN-walking-skeleton.md — FastAPI app + GET /health + Vite/React scaffold + Dockerfiles + docker-compose.yml + human-verified end-to-end smoke

### Phase 2: Extraction Pipeline
**Goal**: A developer can pass an invoice image to the ExtractionService and receive a structured, validated `ExtractedInvoice` with a confidence score — no WhatsApp required
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: EXT-01, EXT-02, EXT-03, EXT-04, EXT-05, EXT-06, EXT-07, VAL-04, VAL-05
**Success Criteria** (what must be TRUE):
  1. Submitting a Factura A image returns all AFIP fields (CUIT, CAE, tipo, número, fecha, IVA, percepciones) with correct values or null — never fabricated data
  2. Submitting a Remito or lista informal image does not crash; nullable fields return null and tipo_comprobante is correctly identified
  3. A confidence score between 0.0 and 1.0 is produced for every extraction, derived from non-null critical fields and cross-field consistency
  4. The original invoice file is saved to the local filesystem via StorageBackend and the stored path is returned
  5. Processing errors (download failure, extraction failure) are captured and logged with the originating message reference
**Plans:** 3 plans
Plans:
**Wave 1**
- [x] 02-01-PLAN.md — Wave 0 tests + StorageBackend + ExtractionService skeleton + debug-gated /extraction/test router

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 02-02-PLAN.md — SYSTEM_PROMPT constant + hardened error semantics + EXT-01..EXT-07 + VAL-04 + VAL-05 mocked tests + integration marker
- [x] 02-03-PLAN.md — calibrate_prompt.py (Claude Opus 4.7 ground truth + GPT-4o diff loop) + fixtures README + D-11 human done-gate

### Phase 3: WhatsApp Pipeline
**Goal**: An allowlisted employee can send an invoice photo on WhatsApp and receive a reply; the invoice data is stored in the database within seconds
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: WA-01, WA-02, WA-03, WA-04, VAL-01, VAL-02, VAL-03, INF-02, INF-04
**Success Criteria** (what must be TRUE):
  1. Sending an invoice photo from an allowlisted number triggers an immediate acknowledgement reply (within 5 seconds) and the invoice is stored in the database after background processing
  2. Sending from a non-allowlisted number returns an explanatory rejection message in Spanish and no database record is created
  3. After extraction completes, the sender receives a reply summarising the extracted fields (proveedor, número, total, status)
  4. Sending an unreadable image or unsupported file format produces an informative error reply to the sender
  5. Submitting a duplicate invoice (same numero_documento + proveedor) does not create a second database record; the sender is notified
  6. Inbound webhook requests with invalid HMAC-SHA256 signatures are rejected with HTTP 401; valid signatures are processed normally
**Plans:** 2/2 plans complete
Plans:
**Wave 1**
- [x] 03-01-PLAN.md — WhatsAppProvider Protocol + TwilioProvider + webhook (signature, allowlist, ack, asyncio.create_task hook) + Alembic UNIQUE migration

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 03-02-PLAN.md — InvoiceService + process_invoice background pipeline (extract, dedup, save, summary/duplicate/error reply) + live Twilio sandbox verification

### Phase 4: Admin UI
**Goal**: A manager or accountant can open a browser, see all captured invoices, search and filter them, inspect details with line items, correct AI errors, and delete records
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: UI-01, UI-02, UI-03, UI-04, UI-05, UI-06
**Success Criteria** (what must be TRUE):
  1. The invoice list loads with pagination; rows can be filtered by proveedor, fecha range, and status (auto_saved / pending_review / confirmed / rejected)
  2. Searching by proveedor name, product description, or document number returns matching invoices
  3. Clicking an invoice shows all document header fields and all extracted line items on one screen, including the original invoice image
  4. Any extracted field (document-level or line-item) can be edited and saved directly in the UI
  5. An invoice record can be deleted from the UI; the original file on disk is retained
  6. Pending review invoices are visually distinguished (highlighted row or badge) in the list view
**Plans:** 5 plans
Plans:
**Wave 1** *(parallel — no shared files)*
- [ ] 04-01-PLAN.md — Wave 0 test stubs + admin.py skeleton + schemas + 7 API endpoints + CORS + pytest suite (UI-01, UI-02, UI-03, UI-04, UI-05)
- [ ] 04-02-PLAN.md — Tailwind v4 install + shadcn init + 9 components + vite.config.ts + index.css + tsconfig alias (UI-01, UI-06)

**Wave 2** *(serial — 04-04 depends on 04-03 stub; blocked on Wave 1)*
- [ ] 04-03-PLAN.md — TypeScript types + API client + hooks + shared components + InvoiceListPage + App router (UI-01, UI-02, UI-06)
- [ ] 04-04-PLAN.md — InvoiceDetailPage + DataPanel + ImagePanel + ActionBar + edit modals + delete flow (UI-03, UI-04, UI-05)

**Wave 3** *(blocked on Wave 2)*
- [ ] 04-05-PLAN.md — Human verification of all 6 UI flows + full backend suite gate (UI-01 through UI-06)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 2/2 | Complete   | 2026-05-13 |
| 2. Extraction Pipeline | 0/TBD | Not started | - |
| 3. WhatsApp Pipeline | 2/2 | Complete    | 2026-05-14 |
| 4. Admin UI | 0/5 | Not started | - |
