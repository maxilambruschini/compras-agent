# Compras Agent

## What This Is

A WhatsApp-to-database invoice capture system for Argentine companies. Purchasing employees photograph invoices and send them via WhatsApp; an AI agent extracts structured data from the image and stores it in a database. Managers and accountants access a React web UI to review, edit, query, and manage all captured invoices.

## Core Value

An employee sends a photo of an invoice over WhatsApp and the data lands correctly in the database — no manual entry, no lost receipts.

## Requirements

### Validated

- [x] Only allowlisted phone numbers can submit invoices — `sender_allowlist` table defined, CRUD tested (INF-01, Phase 1)
- [x] App refuses to start when required env vars are missing — Pydantic Settings fail-fast with ValidationError (INF-03, Phase 1)

### Active

- [ ] Employee sends invoice photo via WhatsApp and receives confirmation
- [ ] Only allowlisted phone numbers can submit invoices
- [ ] AI extracts Argentine invoice fields (CUIT, CAE, tipo de comprobante, IVA, items) from image
- [ ] Extracted data is validated before being written to the database
- [ ] Low-confidence extractions are flagged for human review
- [ ] Original invoice images are stored alongside extracted data
- [ ] Admin UI: list, search, filter, and view all invoices
- [ ] Admin UI: edit extracted fields on any invoice
- [ ] Admin UI: delete invoices
- [ ] Admin UI: view per-invoice line items
- [ ] Admins log in with email/password (Supabase Auth)
- [ ] Duplicate invoice detection prevents double entries

### Out of Scope

- Google Sheets integration — using a real database + custom UI instead
- General-purpose WhatsApp chatbot — this is a closed transactional workflow only
- Multiple company / multi-tenant support — single company for v1
- Mobile app — web UI only
- AFIP/ARCA electronic invoice verification — extraction only, not tax validation
- Real-time notifications — polling or manual refresh is fine for low volume

## Context

- **Client**: Argentine company standardizing internal purchasing processes
- **Invoice types**: Primarily Argentine AFIP-format invoices (facturas A/B/C, remitos, tickets)
- **Argentine fields to extract**: CUIT proveedor, tipo de comprobante, punto de venta, número de comprobante, CAE, fecha de vencimiento CAE, fecha de emisión, condición IVA, neto gravado, IVA, percepciones, total
- **Volume**: Low — under 20 invoices/day. No heavy async infrastructure needed for v1.
- **WhatsApp channel**: To be decided (Meta WhatsApp Cloud API or Twilio). The processing pipeline is built as WhatsApp-agnostic; WhatsApp integration is a pluggable layer.
- **Sender security**: Only pre-registered employee phone numbers (allowlist in DB) can submit invoices. Unknown senders receive a rejection message.
- **Extraction model**: OpenAI GPT-4o vision with Pydantic Structured Outputs. Return `null` for invisible fields, never hallucinate.
- **Human review flow**: Extractions below confidence threshold are written to DB with `status=pending_review` and flagged in the UI. The WhatsApp sender receives a summary and is asked to confirm or flag for correction.

## Constraints

- **Tech Stack**: Python + FastAPI (backend), React + Vite (frontend), Postgres in Docker, local filesystem storage via FastAPI (`StorageBackend` abstraction), OpenAI GPT-4o vision
- **WhatsApp**: Must use official Meta Cloud API or an official BSP (Twilio, 360dialog) — no unofficial scraping libraries
- **Security**: Secrets in environment variables. Webhook signatures validated. Original files retained for audit.
- **Argentine compliance**: Invoice fields follow AFIP schema conventions. No tax advice generated — extraction only.
- **Scope**: Single-company deployment for v1. No multi-tenancy.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Postgres (local Docker) instead of Google Sheets | Real DB needed for querying, editing, audit trail, and dedup. Sheets lacks integrity. | ✓ Schema live — invoices, invoice_line_items, sender_allowlist tables migrated (Phase 1) |
| React + Vite frontend | Lightweight custom UI gives full control over invoice review UX. | ✓ Vite/React scaffold running at :5173 via Docker Compose (Phase 1) |
| WhatsApp integration abstracted | Build core pipeline first; plug in Cloud API or Twilio once extraction is validated. | — Phase 3 |
| OpenAI GPT-4o vision + Pydantic Structured Outputs | Handles varied Argentine invoice layouts, multilingual labels, normalization in one pass. | — Phase 2 |
| Admin-only UI (no auth for demo) | Only managers/accountants need the web UI. Auth deferred — this is a demo build. | — Phase 4 |
| Local Docker stack instead of Supabase | Demo only — no external services, no accounts, runs offline. `docker compose up` starts everything. StorageBackend abstraction keeps production path open. | ✓ docker compose up → all containers healthy; alembic runs on boot (Phase 1) |
| Sender allowlist in DB | Security requirement — only registered employees can submit invoices. | ✓ sender_allowlist table + CRUD tests green; /health reports count (Phase 1) |
| Argentine invoice fields in schema | Client issues AFIP-format invoices. CUIT, CAE, tipo de comprobante are required fields. | ✓ Invoice + InvoiceLineItem ORM models with full AFIP column set; TipoComprobante enum (Phase 1) |
| sqlalchemy.Uuid (dialect-agnostic) for UUID columns | aiosqlite test backend cannot bind postgresql.UUID; dialect-agnostic Uuid works on both backends. | ✓ Applied in models.py — tests pass on SQLite, migration produces native Postgres UUID DDL (Phase 1) |
| Lazy engine factory (get_settings() inside function) | pytest env_setup fixture must patch env vars before any engine is created. | ✓ engine.py uses lazy initialization — no module-level Settings() call (Phase 1) |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-13 — Phase 1 (Foundation) complete*
