# Project Research Summary

**Project:** Compras Agent — WhatsApp Invoice Capture System
**Domain:** WhatsApp-to-database transactional intake agent, Argentine AFIP invoices
**Researched:** 2026-05-12
**Confidence:** HIGH

## Executive Summary

Compras Agent is a closed transactional intake system: purchasing employees photograph Argentine AFIP invoices and send them via WhatsApp; a GPT-4o vision pipeline extracts structured data and stores it in Supabase Postgres; accountants and managers review, correct, and approve records through a React admin UI. The domain is well-understood — this is a standard document-capture-with-human-review pattern — but Argentine invoice specifics (AFIP/ARCA fields, factura type logic, CUIT validation, CAE requirements) add domain complexity that must be encoded carefully in both the Pydantic extraction schema and the GPT-4o system prompt.

The recommended approach is a FastAPI backend using pywa 3.9 for WhatsApp Cloud API integration, OpenAI `chat.completions.parse()` with a Pydantic v2 model for structured extraction, Supabase for Postgres + Storage + Auth, and a React 19 / Vite 8 / TanStack Query v5 frontend. The architecture isolates provider-specific webhook logic behind a Python Protocol gateway, runs invoice processing asynchronously via `BackgroundTasks`, and uses a five-state status machine (`extracting -> auto_saved / pending_review -> confirmed / rejected`) to route extractions between automated approval and human review. At under 20 invoices/day no external queue (Celery, ARQ) is needed for v1.

The two highest-priority risks are: (1) WhatsApp media URLs expire in 5 minutes -- the background task must download and re-upload to Supabase Storage as its first operation; and (2) GPT-4o will fabricate plausible-looking CUIT/CAE values when fields are ambiguous if schema fields are not Optional -- every extracted field must be nullable and the system prompt must explicitly instruct the model to return null rather than guess. Secondary risks include FastAPI BackgroundTasks silently swallowing exceptions, Supabase RLS being off by default, and duplicate invoice detection requiring a four-part composite unique constraint.

---

## Key Findings

### Recommended Stack

The backend is Python 3.12 / FastAPI 0.136.1 / Pydantic v2.13.4 / OpenAI Python 2.36.0 / pywa 3.9.0 / supabase-py 2.30.0. The frontend is React 19 / Vite 8 / TypeScript 5 / @supabase/supabase-js 2.105.4 / TanStack Query v5. All versions verified against PyPI and npm on 2026-05-12.

**Core technologies:**
- **pywa 3.9**: WhatsApp Cloud API integration -- handles HMAC verification, webhook challenge, media download, reply sending, and FastAPI route registration; replaces 200+ lines of manual webhook boilerplate
- **openai 2.36 + chat.completions.parse()**: Structured extraction via Pydantic schema -- guarantees schema shape and deserializes directly to typed Python; requires gpt-4o-2024-08-06 or later
- **Supabase (Postgres + Storage + Auth)**: Single SDK covers all persistence; Storage RLS tied to same Postgres policies; signed URLs for image access; no separate GCS/S3 needed
- **TanStack Query v5**: Handles invoice list/detail/edit cycle; useMutation + invalidation avoids hand-rolled useEffect chains
- **FastAPI BackgroundTasks**: Sufficient for <20/day; returns 200 to WhatsApp immediately, processes pipeline asynchronously; upgrade path to ARQ without pipeline code changes

### Expected Features

**Must have (table stakes -- Phase 1):**
- WhatsApp image acknowledgement and extraction summary reply to sender
- Allowlist enforcement with rejection message for unknown senders
- AI extraction of all P0/P1 Argentine AFIP fields: CUIT, tipo de comprobante, punto de venta, numero de comprobante, CAE, fecha vencimiento CAE, fecha emision, condicion IVA, neto gravado, IVA, percepciones (nullable), total
- CUIT mod-11 checksum validation post-extraction
- CAE presence and format check (14 digits)
- Confidence-threshold routing: auto_saved vs pending_review
- Composite dedup key: (cuit_proveedor, tipo_comprobante, punto_de_venta, numero_comprobante) as DB UNIQUE constraint
- Admin UI: invoice list with pagination, status/date/CUIT filters, detail + original image, edit fields, approve, delete
- Admin login via Supabase Auth (email/password)

**Should have (Phase 2):**
- QR code decoding for post-2020 invoices (significantly improves extraction accuracy)
- Percepciones breakdown as separate field
- CSV/Excel export (high accountant demand, low effort)
- Supplier master table (CUIT-to-razon-social mapping)
- Audit trail / change log for field edits
- Multiple image per invoice submission

**Defer to Phase 3+:**
- Dashboard summary stats
- Bulk approve
- Accounting software integration -- CSV export covers this for v1
- Real-time push notifications
- Line item extraction

### Architecture Approach

The system follows a clean three-tier pipeline: an inbound WhatsApp gateway (Protocol abstraction over pywa/Meta or Twilio) hands a normalized InboundMessage to a FastAPI BackgroundTask-backed InvoiceProcessingService that runs allowlist check -> Supabase Storage upload -> DB insert -> GPT-4o extraction -> status update -> reply. A separate set of admin API routes handle CRUD with service_role key. The React frontend reads directly from Supabase JS (anon key + RLS) and POSTs to FastAPI for writes requiring business-rule enforcement. Images are never served from public Storage URLs -- FastAPI generates short-lived signed URLs on demand.

**Major components:**
1. **WhatsApp Gateway (Protocol)** -- encapsulates Meta vs Twilio differences; pipeline never imports provider directly
2. **InvoiceProcessingService** -- orchestrates 7-step pipeline; runs entirely in BackgroundTask
3. **ExtractionService** -- calls GPT-4o vision, parses to ExtractedInvoice Pydantic model, applies post-extraction deterministic validation
4. **Admin API (FastAPI routes)** -- CRUD + status transitions; generates signed storage URLs; uses service_role key
5. **React Admin UI** -- TanStack Query reads via Supabase JS; writes via FastAPI; Supabase Auth with onAuthStateChange
6. **Supabase** -- four tables: purchase_documents, purchase_items, allowed_senders, processing_log

### Critical Pitfalls

1. **WhatsApp media URL expires in 5 minutes** -- download and re-upload to Supabase Storage as absolute first step in background task; never store the ephemeral URL in the DB
2. **GPT-4o hallucinates required fields** -- every extracted field must be Optional[T]; system prompt must say "return null for any field not clearly visible"; apply CUIT mod-11 and CAE length checks post-extraction
3. **FastAPI BackgroundTasks fails silently** -- wrap entire task body in try/except; write failed record to processing_log; log heartbeat at task start
4. **Supabase RLS off by default** -- include ENABLE ROW LEVEL SECURITY in every migration; never use anon key on FastAPI backend; keep Storage bucket private
5. **Duplicate detection on invoice number alone misses 30-40% of duplicates** -- composite UNIQUE constraint at DB level; not application logic
6. **AFIP/ARCA branding change (October 2024)** -- invoices may print ARCA; GPT-4o prompts must accept both; underlying CAE/CUIT structure unchanged

---

## Implications for Roadmap

### Phase 1: Database Schema and Pydantic Models
**Rationale:** Everything else depends on a stable schema. RLS policies, UNIQUE constraints, and the ExtractedInvoice Pydantic model must be locked before any pipeline or UI code is written.
**Delivers:** Supabase migrations for all four tables, RLS policies, private Storage bucket, ExtractedInvoice Pydantic model with all AFIP fields as Optional, CUIT normalization utility, CUIT mod-11 validator, tipo de comprobante enum
**Addresses:** All P0/P1 AFIP field definitions, dedup composite key, allowlist table, status enum
**Avoids:** Pitfall 3 (RLS off), Pitfall 6 (public bucket), Pitfall 9 (migration drift), Pitfall 10 (dedup key), Pitfall 8 (CUIT normalization)

### Phase 2: WhatsApp Gateway and Extraction Service
**Rationale:** Two self-contained services testable in isolation. ExtractionService requires the Pydantic model from Phase 1.
**Delivers:** WhatsApp Gateway Protocol + Meta Cloud API implementation (pywa 3.9); ExtractionService with GPT-4o vision, structured output parsing, confidence scoring, post-extraction validation; image resize before OpenAI call
**Addresses:** Image extraction of all AFIP fields, null-field enforcement, confidence score
**Avoids:** Pitfall 5 (hallucinated fields), Pitfall 11 (tipo enum + prompt), Pitfall 12 (image resize), Pitfall 13 (ARCA/AFIP branding)

### Phase 3: Webhook Pipeline and Invoice Processing
**Rationale:** Wires Phase 1 schema + Phase 2 services into end-to-end flow. Both prior phases must be complete.
**Delivers:** FastAPI webhook endpoint with immediate 200 ACK, BackgroundTask pipeline, idempotency key on raw_message_id, status webhook filtering, error capture with processing_log writes
**Addresses:** Allowlist check + rejection, image acknowledgement, extraction summary reply, duplicate detection, confidence routing
**Avoids:** Pitfall 1 (media URL expiry), Pitfall 2 (silent task failure), Pitfall 4 (webhook timeout), Pitfall 7 (status event flood), Pitfall 15 (allowlist rejection handling)

### Phase 4: Admin API Routes
**Rationale:** Admin CRUD requires the pipeline from Phase 3 to be stable, particularly the status machine.
**Delivers:** GET/PATCH/DELETE /invoices endpoints, POST /invoices/{id}/confirm, GET /invoices/{id}/image-url (signed URL), JWT validation middleware
**Addresses:** All admin CRUD actions, status transition enforcement, image access
**Avoids:** Pitfall 14 (signed URL RLS path bug), anon key on backend

### Phase 5: React Admin UI
**Rationale:** Can be scaffolded in parallel with Phase 4 using mock data and switched to live API on completion.
**Delivers:** Supabase JS client + Auth setup, invoice list with filters, detail view with original image, inline field editing, approve/reject actions, pending review queue, session expiry handling
**Addresses:** All admin UI table stakes from FEATURES.md
**Avoids:** Pitfall 16 (JWT session expiry)

### Phase 6: Hardening and Phase 2 Features
**Rationale:** Core loop validated before adding enhancements.
**Delivers:** QR code decoding, CSV/Excel export, percepciones UI, supplier master, audit trail, stuck-extraction detection, OpenAI cost monitoring, Twilio gateway
**Addresses:** All Phase 2 deferred features
**Uses:** Existing gateway Protocol -- Twilio is a new concrete implementation with zero pipeline changes

### Phase Ordering Rationale

- Schema-first is non-negotiable: the Pydantic model defines the extraction contract; the DB schema defines the dedup key and RLS surface. Building any other component before this creates rework.
- Gateway and Extraction are developed and unit-tested independently before pipeline wiring -- reduces integration risk.
- Admin API must precede React UI for real integration, but UI scaffolding can start in parallel against mock data.
- Phase 6 is separate from Phase 5 because the core loop should be validated in production before adding enhancements.

### Research Flags

**Phases likely needing deeper research during planning:**
- **Phase 2 (WhatsApp Gateway):** pywa 3.9 FastAPI integration requires careful async/sync boundary management; the exact handler registration pattern needs a working proof-of-concept before production wiring
- **Phase 2 (ExtractionService):** GPT-4o system prompt for Argentine invoices requires iterative calibration against real invoice images; confidence threshold needs empirical calibration
- **Phase 6 (QR decoding):** Argentine invoice QR format (AFIP schema since 2020) needs library validation against real samples

**Phases with standard patterns (skip research-phase):**
- **Phase 1 (Schema):** Supabase migration patterns are fully documented; RLS + Storage setup is well-established
- **Phase 4 (Admin API):** Standard FastAPI CRUD with JWT middleware
- **Phase 5 (React UI):** TanStack Query + Supabase JS is a standard stack with ample documentation

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified against PyPI/npm on 2026-05-12; official client libraries with active maintenance |
| Features | HIGH | Argentine invoice fields from AFIP official documentation; industry patterns from invoice processing providers |
| Architecture | HIGH | All major decisions verified against official docs (FastAPI, Supabase, OpenAI); confirmed by multiple authoritative sources |
| Pitfalls | HIGH | Critical pitfalls backed by official docs, known GitHub issues, and post-mortems from real deployments |

**Overall confidence:** HIGH

### Gaps to Address

- **Confidence threshold (0.85):** Starting value based on community consensus; must be calibrated against real invoice images from the client's employees during Phase 3.
- **GPT-4o system prompt:** No single source provides an optimal prompt for Argentine AFIP invoices. Phase 2 should be built for prompt iteration with a test suite of real images.
- **pywa 4.0 migration timeline:** pywa 4.0 Beta handles the upcoming WhatsApp BSUID migration. Monitor releases; upgrade may be needed during Phase 3 or 6.
- **percepciones field scope:** Whether to extract per-type (IIBB, ganancias) or as a single total needs validation with client accountants before Phase 6.

---

## Sources

### Primary (HIGH confidence)
- FastAPI PyPI + official docs (fastapi.tiangolo.com) -- versions, BackgroundTasks, webhook patterns
- OpenAI Python PyPI + Structured Outputs guide (developers.openai.com) -- .parse() pattern, vision, Optional field behavior
- pywa PyPI + readthedocs (pywa.readthedocs.io) -- FastAPI integration, media handling, webhook lifecycle
- Supabase Python PyPI + official docs (supabase.com/docs) -- RLS, Storage, Auth, service_role vs anon key
- @supabase/supabase-js npm + TanStack Query v5 docs -- frontend patterns
- AFIP official portal (afip.gob.ar/fe/) -- Argentine invoice field requirements
- LookupTax CUIT guide -- CUIT format and mod-11 checksum algorithm

### Secondary (MEDIUM confidence)
- Hookdeck WhatsApp webhook guide -- webhook idempotency, 5-minute media expiry
- Klippa / Number7AI duplicate invoice detection -- composite key approach
- EDICOM / Basware Argentina compliance -- CAE requirements, factura type breakdown
- Contablix SIRCIP percepciones guide -- percepciones IIBB field scope
- FastAPI GitHub issues #2604, #2505, #3589 -- BackgroundTasks silent failure behavior confirmed

### Tertiary (LOW confidence, needs validation)
- GPT-4o system prompt calibration for Argentine invoices -- inferred from general structured extraction best practices; must be validated empirically
- Confidence threshold 0.85 -- community consensus starting point; requires calibration against real samples

---
*Research completed: 2026-05-12*
*Ready for roadmap: yes*
