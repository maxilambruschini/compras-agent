# Requirements: Compras Agent

**Defined:** 2026-05-12
**Core Value:** An employee sends a photo of an invoice over WhatsApp and the data lands correctly in the database — no manual entry, no lost receipts.

---

## v1 Requirements

### WhatsApp Intake

- [x] **WA-01**: Employee can send an invoice photo or PDF via WhatsApp and receive a reply acknowledging receipt
- [x] **WA-02**: System rejects messages from non-allowlisted phone numbers with an explanatory message in Spanish
- [x] **WA-03**: System replies to the sender with a summary of extracted fields after processing completes
- [x] **WA-04**: System notifies sender if the image is unreadable or the file format is not supported

### Extraction

- [ ] **EXT-01**: System extracts line-item fields per product: descripción, SKU/código, bultos, unidades_por_bulto (from description or explicit column), precio_unitario_sin_iva, descuento_%
- [ ] **EXT-02**: System extracts tax fields per line item: IVA rate (0%, 10.5%, or 21%) and percepciones/IIBB amount when present
- [ ] **EXT-03**: System extracts document-level fields used for dedup and display: numero_documento (factura number, remito number, or equivalent), proveedor name, fecha
- [ ] **EXT-04**: System extracts CUIT proveedor and CAE + fecha_vencimiento_cae when visible (nullable — many documents don't have these)
- [ ] **EXT-05**: System handles 3 document types without failing: Factura A (formal, with CUIT/CAE), Remito / Documento no válido (has number but no CAE), Lista informal (no standard fields)
- [ ] **EXT-06**: All extracted fields are nullable — system returns null instead of hallucinating invisible or ambiguous values
- [ ] **EXT-07**: System produces a per-extraction confidence score (derived from proportion of non-null critical fields + cross-field consistency)

### Validation & Storage

- [x] **VAL-01**: System detects duplicate submissions using numero_documento + proveedor; duplicate is flagged and not saved as a new record
- [x] **VAL-02**: Extractions below the confidence threshold are saved with status=pending_review and visually flagged in the admin UI
- [x] **VAL-03**: Extractions above the confidence threshold are saved with status=auto_saved
- [ ] **VAL-04**: Original invoice image or PDF is stored on the local filesystem (via StorageBackend abstraction) and linked to the database record
- [ ] **VAL-05**: Processing errors (download failure, extraction failure, validation failure) are logged with the WhatsApp message ID for diagnosis and retry

### Admin UI

- [ ] **UI-01**: Admin can view a paginated list of invoices filterable by proveedor, fecha range, and status (auto_saved / pending_review / confirmed / rejected)
- [ ] **UI-02**: Admin can search invoices by proveedor name, product description, or document number
- [ ] **UI-03**: Admin can click into an invoice to see the document header fields and all extracted line items on one screen
- [ ] **UI-04**: Admin can edit any extracted field on a document or line item to correct AI errors
- [ ] **UI-05**: Admin can delete an invoice record (removes DB record; original file in Storage is retained)
- [ ] **UI-06**: Pending review invoices are visually distinguished (e.g., highlighted row or badge) in the list view
- ~~**UI-07**~~: *(deferred to v2 — demo build, no auth required)*

### Infrastructure

- [ ] **INF-01**: Allowlisted sender phone numbers are stored in the database; only these numbers can submit invoices
- [x] **INF-02**: WhatsApp webhook HMAC-SHA256 signature is validated on every inbound request
- [ ] **INF-03**: All API keys and secrets are stored in environment variables, never in source code
- [x] **INF-04**: WhatsApp webhook responds within 5 seconds; invoice processing runs as a background task after the response is sent

---

## v2 Requirements

### Auth

- **AUTH-01**: Admin authenticates with email and password via Supabase Auth; unauthenticated users cannot access any data

### Export & Reporting

- **EXP-01**: Admin can export invoice list (with filters applied) as CSV
- **EXP-02**: Admin can export line items for a date range as CSV for accounting reconciliation

### Extraction Enhancements

- **EXT-V2-01**: System decodes AFIP QR code on post-2020 facturas to improve extraction accuracy for key fields
- **EXT-V2-02**: System validates CUIT checksum (mod-11 algorithm) when CUIT is extracted

### Infrastructure

- **INF-V2-01**: Twilio WhatsApp gateway as alternative to Meta Cloud API (pluggable via gateway abstraction)
- **INF-V2-02**: Supplier master table — deduplicate proveedor names and link CUIT to canonical supplier record

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| Document-level totals stored in DB (subtotal, iva_total) | Calculable from line items at query time; storing risks inconsistency |
| Multi-tenant / multi-company support | Single company deployment for v1 |
| AFIP/ARCA electronic invoice verification | Extraction only — not tax validation |
| Real-time push notifications | Polling/refresh sufficient for < 20 invoices/day |
| Mobile app | Web UI only |
| WhatsApp general chatbot behavior | Closed transactional workflow only |
| Factura M support | Rare edge case — flag as unsupported type in v1 |

---

## Calculated Fields (never stored)

These are derived at query/display time:

| Field | Formula |
|-------|---------|
| `unidades_totales` | `bultos × unidades_por_bulto` |
| `precio_unitario_con_iva` | `precio_unitario_sin_iva × (1 + iva_rate)` |
| `precio_final_con_iva` | `bultos × precio_unitario_sin_iva × (1 + iva_rate) × (1 - descuento_pct)` |

---

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INF-01 | Phase 1 | Pending |
| INF-03 | Phase 1 | Pending |
| EXT-01 | Phase 2 | Pending |
| EXT-02 | Phase 2 | Pending |
| EXT-03 | Phase 2 | Pending |
| EXT-04 | Phase 2 | Pending |
| EXT-05 | Phase 2 | Pending |
| EXT-06 | Phase 2 | Pending |
| EXT-07 | Phase 2 | Pending |
| VAL-04 | Phase 2 | Pending |
| VAL-05 | Phase 2 | Pending |
| WA-01 | Phase 3 | Complete |
| WA-02 | Phase 3 | Complete |
| WA-03 | Phase 3 | Complete |
| WA-04 | Phase 3 | Complete |
| VAL-01 | Phase 3 | Complete |
| VAL-02 | Phase 3 | Complete |
| VAL-03 | Phase 3 | Complete |
| INF-02 | Phase 3 | Complete |
| INF-04 | Phase 3 | Complete |
| UI-01 | Phase 4 | Pending |
| UI-02 | Phase 4 | Pending |
| UI-03 | Phase 4 | Pending |
| UI-04 | Phase 4 | Pending |
| UI-05 | Phase 4 | Pending |
| UI-06 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 26 total (UI-07 deferred to v2)
- Mapped to phases: 26
- Unmapped: 0 ✓

---
*Requirements defined: 2026-05-12*
*Last updated: 2026-05-12 — traceability updated after roadmap creation*
