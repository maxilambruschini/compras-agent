# Feature Landscape

**Domain:** WhatsApp invoice capture agent — Argentine companies
**Researched:** 2026-05-12
**Confidence:** HIGH (Argentine invoice fields from AFIP official docs; UX patterns from established invoice processing industry)

---

## Table Stakes

Features that must exist for the system to work at all. Missing any of these = system is unusable or untrustworthy.

### 1. WhatsApp Conversation Flow

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Image receipt acknowledgement | Employee needs to know the photo arrived and is being processed | Low | Immediate reply: "Recibimos tu factura, procesando..." |
| Allowlist rejection with clear message | Unknown senders must be turned away with a clear reason | Low | "Tu número no está registrado para enviar facturas. Contactá a tu supervisor." |
| Extraction summary sent back to sender | Employee can spot-check the AI's extraction before it lands in DB | Medium | Show key fields: proveedor, total, fecha, tipo comprobante |
| Explicit processing failure notice | If image is unreadable, notify sender to retry with a better photo | Low | "No pudimos leer la factura. Por favor reenviá una foto más clara." |
| Non-image message rejection | Employees sending text, documents, or audio get a clear redirect | Low | "Enviá una foto de la factura. Solo aceptamos imágenes." |

**Rationale on conversation flow simplicity:** This is a closed transactional workflow. The WhatsApp channel is input-only — employees send images, receive confirmations, done. No multi-turn dialogue needed for v1. The extraction summary reply is the only "conversation" required.

### 2. Invoice Extraction — Argentine Fields

These are the AFIP-mandated fields that appear on all valid Argentine electronic invoices. They must be targeted explicitly.

| Field | Argentine Name | Required? | Notes |
|-------|---------------|-----------|-------|
| Supplier CUIT | CUIT del proveedor | YES — critical | 11-digit tax ID, format NN-NNNNNNNN-N, modulo-11 check digit validation possible |
| Invoice type | Tipo de comprobante | YES — critical | Factura A, B, C, M; Remito; Ticket. Drives downstream tax treatment |
| Point of sale | Punto de venta | YES | 4-digit prefix before the invoice number (e.g. 0001) |
| Invoice number | Número de comprobante | YES — critical | Combined with punto de venta forms the unique identifier |
| Electronic authorization code | CAE | YES — critical | AFIP's authorization code; required on all electronic invoices since 2020 |
| CAE expiration date | Fecha de vencimiento CAE | YES | Must not be expired at time of capture |
| Issue date | Fecha de emisión | YES | Date printed on invoice |
| IVA amount | IVA (21%, 10.5%, etc.) | YES for facturas A | Shown separately only on Factura A; absent on B, C |
| Taxable net amount | Neto gravado | YES for facturas A | Base amount before IVA; absent on B, C |
| Total amount | Total | YES — critical | Always present on all invoice types |
| IVA condition | Condición frente al IVA | YES | Responsable inscripto / Monotributista / Exento — determines how IVA is reported |

**Factura type breakdown (critical for downstream accounting):**
- **Factura A**: Issued by responsable inscripto to another responsable inscripto. IVA is discriminated (shown separately). Neto gravado + IVA line required.
- **Factura B**: Issued to monotributistas, consumidores finales, or exentos. IVA is NOT discriminated — total includes it.
- **Factura C**: Issued by monotributistas to any recipient. No IVA at all.
- **Factura M**: Rare special case; buyer must withhold IVA and ganancias.
- **Factura E**: Export invoices. Unlikely for purchasing agent use case.

### 3. Extraction Quality

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Null fields for invisible data | If a field is not visible or not applicable, return null — never hallucinate | Low | Enforced via Pydantic schema with Optional fields |
| Per-field confidence scoring | Required to route to human review | Medium | GPT-4o does not return native confidence; proxy via model response patterns or secondary prompt |
| Confidence threshold routing | Extractions below threshold go to `pending_review`; above go to `auto_approved` | Low | Threshold is configurable; start at 0.85 |
| Original image stored | Audit trail and reprocessing require the original photo | Low | Store in Supabase Storage, linked to invoice record |
| Structured output via Pydantic | Prevents hallucinated field names; enforces types | Low | Already in project plan |

### 4. Sender Allowlist

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Phone number allowlist in DB | Security requirement from project | Low | Table: `allowed_senders` (phone, name, active_flag) |
| Unknown sender rejection | Must reject and reply | Low | |
| Inactive sender rejection | Employee leaves company — deactivate without deleting | Low | `active_flag = false` |

### 5. Human Review Workflow

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| `status` field on every invoice | Core state machine for review workflow | Low | Enum: `pending_review`, `auto_approved`, `approved`, `rejected` |
| Pending review queue in admin UI | Reviewers must see what needs attention | Low | Filter/badge count for pending items |
| Side-by-side review (image + extracted fields) | Reviewer must be able to see original and extracted data simultaneously | Medium | Split-pane or modal with image thumbnail + form fields |
| Inline field editing on any invoice | Reviewer corrects wrong extractions without navigating away | Medium | Editable form, save to DB |
| Approve / mark-reviewed action | Explicit sign-off action | Low | Changes status from `pending_review` → `approved` |

### 6. Admin UI — Core

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Invoice list with pagination | Baseline for any data management UI | Low | |
| Filter by status (pending / approved / rejected) | Without this, review queue is unusable | Low | |
| Filter by date range | Accountants need to find invoices for a month/week | Low | |
| Search by CUIT or invoice number | Point lookup for a specific supplier invoice | Low | |
| Invoice detail view with original image | Required for review and audit | Medium | |
| Edit extracted fields | Human correction of AI errors | Medium | |
| Delete invoice | Admin requirement from project | Low | Soft delete preferred; mark as deleted, not hard delete |
| Auth via Supabase email/password | Required from project | Low | |

### 7. Duplicate Detection

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Dedup on CUIT + tipo + punto_de_venta + número_comprobante | Most reliable dedup key for Argentine invoices — this tuple is legally unique | Low | Unique constraint in DB; check before insert |
| Duplicate submission response to WhatsApp | Employee must know the invoice was already captured | Low | "Esta factura ya fue registrada (CUIT XXX, comprobante YYYY-NNNN)." |

---

## Optional / Differentiating Features

Features that add real value but are not required for the system to function correctly in v1.

### WhatsApp Conversation

| Feature | Value Proposition | Complexity | Recommended Phase |
|---------|-------------------|------------|------------------|
| Confirmation prompt before saving | "¿Confirmás estos datos? Responde SÍ para guardar." | Medium | Phase 2+ — adds friction; not needed at low volume with human review |
| Retry with field correction via WhatsApp | Employee can reply "El total es 15000" to correct a field | High | Out of scope for v1 — adds stateful conversation logic |
| Multiple images per invoice | Some invoices span multiple pages | Medium | Phase 2 — handle multi-image messages |
| PDF invoice support | Some suppliers email PDFs that employees forward | Medium | Phase 2 — needs PDF rendering before OCR |

### Extraction

| Feature | Value Proposition | Complexity | Recommended Phase |
|---------|-------------------|------------|------------------|
| CUIT format validation (modulo-11) | Catch typos in extracted CUIT before save | Low | Phase 1 — easy win, add to validation layer |
| CAE expiry check | Flag invoices where CAE is expired (possible fraud/error) | Low | Phase 1 — easy win |
| QR code parsing | Argentine invoices since 2020 include QR encoding key fields; decode instead of relying on OCR | Medium | Phase 2 — improves accuracy significantly for modern invoices |
| Supplier master matching | Match extracted CUIT to a known supplier table | Medium | Phase 2 — reduces entry errors, enables supplier-level reporting |
| Line item extraction | Extract individual items/services listed on invoice | High | Phase 2+ — not needed for basic accounting capture |

### Admin UI

| Feature | Value Proposition | Complexity | Recommended Phase |
|---------|-------------------|------------|------------------|
| Export to CSV/Excel | Accountants need to import into accounting software | Low | Phase 2 — high demand, low effort |
| Percepciones / retenciones breakdown | Some facturas A include provincial gross income perceptions and national withholdings as separate line items | Medium | Phase 2 — needed for accurate accounting imports |
| Supplier list / CUIT directory | Manage known suppliers; auto-fill supplier name from CUIT | Medium | Phase 2 |
| Per-sender submission history | See all invoices submitted by a specific employee | Low | Phase 2 |
| Bulk approve | Approve multiple pending invoices at once | Low | Phase 2 — useful once volume grows |
| Rejection reason field | When rejecting, require a reason (illegible, wrong supplier, etc.) | Low | Phase 1 or 2 — adds accountability |
| Dashboard / summary stats | Invoice count by status, by month, by supplier | Medium | Phase 3 |

### Audit and Compliance

| Feature | Value Proposition | Complexity | Recommended Phase |
|---------|-------------------|------------|------------------|
| Change log / audit trail | Track who edited what fields and when | Medium | Phase 2 — important for compliance but not required to launch |
| Reprocessing an invoice | Re-run AI extraction on an existing invoice (e.g., with a better prompt) | Medium | Phase 2 |

---

## Anti-Features

Things to deliberately NOT build in v1. Including them wastes time or creates scope creep.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| AFIP/ARCA CAE validation via web service | Out of scope (PROJECT.md), adds significant complexity and AFIP credential management | Trust the CAE is present; visual validation only |
| Multi-turn WhatsApp dialogue for corrections | Stateful conversation management is a large system; this is a transactional intake tool | Human review via admin UI handles corrections |
| Approval routing / multi-level sign-off | Small company workflow — one reviewer is sufficient for v1 | Single "approve" action per invoice |
| Real-time push notifications (websockets/SSE) | Low volume (< 20/day) makes this unnecessary overhead | Poll or manual refresh is fine |
| Mobile-responsive admin UI as first priority | Managers will review on desktop; mobile optimization is a polish task | Build desktop-first, don't let mobile responsiveness block shipping |
| Multi-tenant / multi-company | Out of scope (PROJECT.md) | Hard-code company context for v1 |
| WhatsApp conversation memory / context | Employees don't have conversations; they send invoices | Stateless per-message processing only |
| Accounting software integration (ERP/SAP/Tango) | High integration complexity; different clients use different software | Export to CSV/Excel in Phase 2; let accountants import manually |
| Invoice PDF generation | This system captures vendor invoices — it doesn't generate them | N/A |
| Full-text search across invoice content | Low value at < 20/day volume; complexity not justified | Field-level filters (CUIT, date, number) are sufficient |

---

## Argentine Invoice Specifics — Field Priority Matrix

Based on AFIP documentation and Argentine accounting practice:

| Field | Priority | Factura A | Factura B | Factura C | Notes |
|-------|----------|-----------|-----------|-----------|-------|
| CUIT proveedor | P0 — critical | Yes | Yes | Yes | Uniquely identifies supplier for tax purposes |
| Tipo de comprobante | P0 — critical | Yes | Yes | Yes | Determines IVA treatment downstream |
| Número de comprobante | P0 — critical | Yes | Yes | Yes | Punto de venta + número = legal identifier |
| CAE | P0 — critical | Yes | Yes | Yes | Proves invoice is AFIP-authorized |
| Total | P0 — critical | Yes | Yes | Yes | Always present |
| Fecha de emisión | P1 — required | Yes | Yes | Yes | |
| Neto gravado | P1 — required | Yes | Implicit | N/A | On A: explicit field. On B: can be back-calculated. On C: not applicable |
| IVA amount | P1 — required | Yes | Implicit | N/A | Same as above |
| Fecha venc. CAE | P1 — required | Yes | Yes | Yes | Needed to flag expired CAEs |
| Condición IVA emisor | P1 — required | Yes | Yes | Yes | Determines factura type logic |
| Percepciones | P2 — optional | Sometimes | Rarely | No | Provincial gross income withholdings; common on facturas A from large suppliers |
| Retenciones | P2 — optional | Sometimes | No | No | National/provincial withholdings; rare on supplier invoices |
| Razón social proveedor | P2 — optional | Yes | Yes | Yes | Usually derivable from CUIT if supplier master exists; else extract from image |
| Domicilio fiscal | P3 — low | Sometimes | Sometimes | Rarely | Not needed for basic accounting capture |
| Line items | P3 — low | Sometimes | Sometimes | Sometimes | Useful but complex; defer to Phase 2 |

**Percepciones note:** Common enough in Argentine facturas A that the schema should include an optional `percepciones` array or a single `percepciones_total` numeric field. Percepciones de Ingresos Brutos (IIBB) are applied by large suppliers as collection agents and appear on the invoice as additional line-items increasing the total. Missing this field will cause reconciliation errors for accountants.

---

## Feature Dependencies

```
Allowlist check → (must pass before) → Image download
Image download → (required for) → AI extraction
AI extraction → (produces) → Extracted fields + confidence score
Confidence score → (routes to) → auto_approved OR pending_review
pending_review → (requires) → Human review UI
Human review UI → (requires) → Auth (Supabase)
Human review UI → (requires) → Side-by-side image + fields view
Dedup check → (runs alongside) → AI extraction, before DB insert
WhatsApp confirmation reply → (requires) → Extracted fields summary
```

---

## MVP Recommendation

**Ship in Phase 1 (core pipeline working end-to-end):**

1. Allowlist check + rejection message
2. Image acknowledgement message + extraction summary reply
3. AI extraction of all P0 + P1 fields listed above
4. CUIT format validation (modulo-11) — easy and high value
5. CAE presence check
6. Dedup on CUIT + tipo + punto_de_venta + número_comprobante
7. `pending_review` / `auto_approved` routing by confidence
8. Admin UI: list, filter by status/date, invoice detail with image, edit fields, approve, delete
9. Admin auth via Supabase

**Defer to Phase 2:**
- Percepciones breakdown (schema placeholder in Phase 1 as nullable field)
- QR code decoding (significantly improves extraction accuracy for post-2020 invoices)
- CSV/Excel export
- Supplier master table
- Audit trail / change log
- Multiple image / PDF support

**Defer to Phase 3+:**
- Dashboard stats
- Bulk approve
- Accounting software integration

---

## Sources

- [Electronic Invoicing in Argentina — EDICOM](https://edicomgroup.com/blog/electronic-invoice-argentina)
- [Argentina CAE & AFIP Requirements — Basware](https://www.basware.com/en/compliance-map/argentina)
- [Argentina CUIT Tax ID — LookupTax](https://lookuptax.com/docs/tax-identification-number/argentina-tax-id-guide)
- [AFIP Factura Electrónica official portal](https://www.afip.gob.ar/fe/)
- [Tipos de factura A, B, C — declar.ar](https://declar.ar/blog/factura-a-b-c-diferencias/)
- [SIRCIP percepciones Ingresos Brutos — Contablix](https://contablix.ar/blog/sircip-percepciones-ingresos-brutos-2026)
- [Human-in-the-loop confidence scoring — Iteration Layer](https://iterationlayer.com/blog/ai-data-extraction-confidence-scores)
- [Duplicate invoice detection — Klippa](https://www.klippa.com/en/blog/information/how-to-detect-duplicate-invoices/)
- [Invoice management essential features — Cflow](https://www.cflowapps.com/invoice-management/)
- [WhatsApp Business API media management — SMSGatewayCenter](https://www.smsgatewaycenter.com/blog/whatsapp-business-api-media-management-images-videos-documents/)
