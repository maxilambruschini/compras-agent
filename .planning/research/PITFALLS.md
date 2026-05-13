# Domain Pitfalls

**Domain:** WhatsApp invoice capture agent (Argentine AFIP invoices, GPT-4o vision, Supabase, FastAPI)
**Researched:** 2026-05-12
**Stack:** Python + FastAPI, OpenAI GPT-4o vision + Pydantic Structured Outputs, Supabase Postgres + Storage, React + Vite, Meta WhatsApp Cloud API or Twilio

---

## Critical Pitfalls

Mistakes that cause rewrites, data loss, security breaches, or silent corruption.

---

### Pitfall 1: Media URL Expires in 5 Minutes — Synchronous Download Will Miss It

**What goes wrong:** The WhatsApp Cloud API webhook payload contains a `media_id`, not a raw file URL. You must make a separate GET call to retrieve the temporary download URL. That URL expires after **5 minutes**. If the webhook handler performs any slow work before downloading — logging, DB writes, GPT-4o calls — the image is gone and extraction never happens.

**Why it happens:** Developers treat the media_id as stable storage. It isn't. The download URL is a short-lived CDN signed URL scoped to that API call.

**Consequences:** Invoices arrive, webhook fires, the handler ACKs 200, but the download call returns 404. No image stored, no extraction triggered, no error surfaced unless you log explicitly. The submitter receives no failure feedback.

**Prevention:**
1. ACK the webhook immediately with `200 OK` (see Pitfall 4).
2. In the background task, retrieve the media URL first — before any other work.
3. Download the raw bytes and upload to Supabase Storage in the same background task, within the first operation.
4. Store the Supabase path (not the WhatsApp URL) in the DB. Never store the ephemeral WhatsApp URL.

**Detection:** Log every media URL retrieval attempt with timestamp delta from webhook receipt. Any delta > 60 seconds risks expiry at peak load.

**Phase:** WhatsApp integration phase (webhook + media pipeline).

---

### Pitfall 2: FastAPI BackgroundTasks Fails Silently in Production

**What goes wrong:** FastAPI's `BackgroundTasks` runs the task after the response is sent. If the task raises an exception, the exception is swallowed — it appears nowhere in the HTTP response, and without explicit try/except + logging inside the task function, it produces zero output. The webhook appears to have succeeded; the invoice is simply never processed.

**Why it happens:** FastAPI's exception handlers do not intercept background task exceptions — the response is already finalized. Known FastAPI issues #2604, #3589, #2505 confirm this behavior.

**Consequences:** At-least-one delivery from WhatsApp + silent task failure = the retry fires again, and if the bug is systematic (e.g., bad Supabase credentials), every invoice silently discards. No dead-letter queue exists by default.

**Prevention:**
1. Wrap every background task body in `try/except Exception as e: logger.error(...)`.
2. Write a failed `invoice_jobs` record to the DB on exception so the UI can surface it.
3. For v1 (< 20 invoices/day), `BackgroundTasks` is acceptable **only if** the above error capture is in place. For anything higher-volume, use ARQ or Celery.

**Detection:** Add a heartbeat log entry at the start of every background task execution. Missing heartbeats on received webhooks = silent failure.

**Phase:** Core extraction pipeline phase.

---

### Pitfall 3: RLS Not Enabled on New Tables — Supabase Default Is Insecure

**What goes wrong:** Every new table created in Supabase has RLS disabled by default. The anon key (which ships in the React frontend) can read and write all rows in any table without RLS policies. In January 2025, 170+ apps built on Supabase were found to have fully exposed databases because developers forgot to enable RLS.

**Why it happens:** The Supabase dashboard shows the table but hides the RLS-off state unless you explicitly navigate to the security panel. Migrations created via `CREATE TABLE` also do not auto-enable RLS.

**Consequences for this project:** Employee names (allowlist), invoice amounts, vendor CUITs, and raw image paths are exposed to anyone who finds the anon key (which is bundled in the compiled React JS). This is a serious data breach for financial data.

**Prevention:**
1. Include `ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;` in every migration that creates a table.
2. RLS policy for invoices: only `authenticated` role (logged-in admins) can SELECT/UPDATE/DELETE.
3. The FastAPI backend uses the `service_role` key (never the anon key) for all DB writes from the webhook pipeline.
4. The React frontend uses anon key + Supabase Auth JWT. RLS policies check `auth.role() = 'authenticated'`.
5. Run Supabase's built-in security advisor (`get_advisors`) before any deployment.

**Detection:** `SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname = 'public';` — any row with `rowsecurity = false` is a live exposure.

**Phase:** Database schema phase. Must be enforced from the first migration.

---

### Pitfall 4: Webhook Response Timeout Triggers Retries → Duplicate Processing

**What goes wrong:** WhatsApp requires a `200 OK` response within approximately 5–10 seconds (varies by BSP; Meta's own guidance says "immediately"). If your handler performs GPT-4o extraction synchronously inside the request-response cycle (typical "fast path" development approach), the 10–30 second GPT-4o call will timeout. WhatsApp retries with the same message, which triggers a second extraction and potentially a duplicate invoice record.

**Why it happens:** In development the GPT-4o call feels fast on good internet. In production with large images or API congestion it regularly exceeds 10 seconds.

**Consequences:** Duplicate invoice records, double send of confirmation message to employee, wasted OpenAI tokens.

**Prevention:**
1. ALWAYS return `200 OK` from the webhook endpoint before any processing.
2. Use `BackgroundTasks` (or equivalent) to run: media download → Supabase upload → GPT-4o → DB write → reply message.
3. Implement idempotency using the WhatsApp `message_id` as a deduplication key. Before processing, check if this `message_id` was already processed (store in a `processed_messages` table or Redis). If already seen, return 200 and skip.

**Detection:** Monitor the time-to-response on the webhook endpoint. Any p99 > 3 seconds is dangerous. The `200 OK` should fire in < 100ms.

**Phase:** WhatsApp integration phase.

---

### Pitfall 5: GPT-4o Hallucinates Fields When Image Is Ambiguous — Schema Forces Fabrication

**What goes wrong:** When using OpenAI Structured Outputs with a Pydantic schema, the model is constrained to always produce values matching the schema. If a field is not nullable and the invoice image is blurry, partially occluded, or the field simply does not exist on that invoice type (e.g., Factura C has no IVA line), GPT-4o will fabricate a plausible-looking value rather than return `null`. CUIT numbers, CAE codes, and monetary amounts are especially vulnerable: the model generates digits that look real but are wrong.

**Why it happens:** Structured Outputs guarantee schema shape, not semantic truthfulness. The official OpenAI docs warn: "the model will always try to adhere to the provided schema, which can result in hallucinations if the input is completely unrelated to the schema."

**Consequences:** Corrupted invoice records that pass schema validation but contain fabricated CUITs or amounts. These are difficult to catch because they look structurally valid.

**Prevention:**
1. All Argentine invoice fields must be `Optional[T]` (mapped as `Union[T, None]` for OpenAI Structured Outputs). Never use required non-nullable fields for extracted values.
2. Add a `confidence` field (0.0–1.0) or per-field `low_confidence` flag to the schema. Prompt the model to return `null` for any field it cannot clearly read.
3. System prompt must explicitly state: "If a field is not visible, illegible, or not applicable to this invoice type, return null. Do NOT guess or infer values."
4. Post-extraction: apply deterministic validation rules (CUIT checksum, CAE is exactly 14 digits, CAE vencimiento is a valid future date) and flag records that fail as `pending_review`.
5. Use image `detail: "high"` for the vision call to maximize character-level accuracy.

**Detection:** Run CUIT mod-11 checksum on every extracted CUIT. Any checksum failure = hallucination or bad read. CAE length != 14 = hallucination.

**Phase:** GPT-4o extraction pipeline phase.

---

### Pitfall 6: Invoice Storage Bucket Made Public — All Invoice Images Accessible Anonymously

**What goes wrong:** Supabase Storage buckets are private by default, which requires signed URLs for access. A common shortcut is to set the bucket to `public`, which makes every object URL permanently accessible to anyone with the URL — bypassing RLS entirely. Invoice images contain sensitive financial and fiscal data (CUITs, amounts, vendor identities).

**Why it happens:** Signed URL generation adds a step. Developers make the bucket public to simplify the frontend image display.

**Consequences:** Anyone who intercepts or guesses a storage path can download all invoice images indefinitely. No access control exists.

**Prevention:**
1. Keep the invoice image bucket **private**.
2. Generate signed URLs server-side (or via Supabase RLS-scoped client) with short TTL (1 hour is appropriate for UI display).
3. Never store the signed URL in the database — store the storage path and generate the signed URL on demand.
4. Storage RLS policy: only `authenticated` role can read objects in the invoices bucket.

**Detection:** Attempt to access a storage object URL without an Authorization header. If it returns 200, the bucket is public.

**Phase:** Database/storage setup phase.

---

## Moderate Pitfalls

---

### Pitfall 7: WhatsApp Status Webhooks Flood the Endpoint With Noise

**What goes wrong:** WhatsApp sends `delivered`, `read`, and `sent` status update events to the same webhook endpoint as incoming messages. For this project, which only cares about inbound image messages, status events are pure noise. Without filtering, every outbound confirmation message triggers 2–3 additional status webhooks, and the handler processes them (or logs errors when it can't parse them as invoices).

**Prevention:** At the top of the webhook handler, check `entry[].changes[].value.statuses` — if this key is present, return `200 OK` immediately without any further processing. Only process events where `entry[].changes[].value.messages` is present and the message type is `image`.

**Detection:** Log the `type` of every incoming webhook event. If status events are not filtered, they will appear at 3–5x the volume of actual image messages.

**Phase:** WhatsApp integration phase.

---

### Pitfall 8: CUIT Format Variations Break Extraction Matching

**What goes wrong:** Argentine CUITs appear on invoices in multiple formats: `20-12345678-9`, `20123456789`, `20 12345678 9`, sometimes with leading zeros omitted. The extraction will return whichever format is printed. If the `proveedores` (vendor) lookup uses exact string match, the same vendor appears as multiple records depending on which invoice format was photographed.

**Why it happens:** AFIP/ARCA has a canonical format (NN-NNNNNNNN-N) but printers and accounting software do not enforce it consistently.

**Prevention:**
1. Normalize all CUITs to raw 11 digits (strip hyphens and spaces) before storing in the DB. Store the normalized form as the canonical key.
2. Add a CUIT validation function: verify mod-11 checksum on the normalized 11-digit string. Reject (flag as `pending_review`) any CUIT that fails checksum.
3. Index on the normalized CUIT column for vendor deduplication queries.

**Phase:** DB schema + extraction validation phase.

---

### Pitfall 9: Supabase Migration History Drift — Local and Production Diverge

**What goes wrong:** Early in development, ad-hoc schema changes made via the Supabase dashboard (adding a column, creating an index) are not captured in migration files. When `supabase db push` is run later, the CLI's migration history mismatches the actual remote schema, causing push failures or silently skipping migrations.

**Prevention:**
1. All schema changes go through `supabase migration new` + SQL file, never the dashboard.
2. Use `supabase db diff` to detect any drift between local and remote before pushing.
3. Enable `supabase link` from day one so the CLI tracks the remote project.
4. Always include `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` and policy creation in the same migration as the `CREATE TABLE`.

**Detection:** Run `supabase db diff` — any non-empty output means the dashboard was used directly.

**Phase:** Database setup phase (first migration).

---

### Pitfall 10: Duplicate Invoice Detection on Invoice Number Alone Misses 30–40% of Duplicates

**What goes wrong:** Using only `(cuit_proveedor, numero_comprobante)` as the uniqueness key fails because: (1) GPT-4o may extract the same number with a leading zero difference, (2) the same physical invoice may be photographed twice with different image orientations producing slightly different extracted values, (3) invoices from different vendors can legally share the same `numero_comprobante` (invoice numbers reset per `punto_de_venta`).

**Prevention:**
1. Composite unique key: `(cuit_proveedor, tipo_comprobante, punto_de_venta, numero_comprobante)`. This is the canonical AFIP identifier for an invoice.
2. Enforce this as a database UNIQUE constraint — let the DB reject duplicates, do not rely on application logic alone.
3. Add a perceptual hash of the invoice image (pHash) as a secondary signal. Same image hash = duplicate regardless of extraction result differences.
4. Add a soft-duplicate warning for `(cuit_proveedor, monto_total)` within a 30-day window — prompts human review but does not auto-reject.
5. The UNIQUE constraint on the composite key is the reliable signal. Image hash is supplementary.

**Detection:** Query for `count(*) > 1 GROUP BY cuit_proveedor, tipo_comprobante, punto_de_venta, numero_comprobante` in existing data. Any count > 1 = dedup is not working.

**Phase:** DB schema phase (UNIQUE constraint must be in initial migration) + extraction pipeline phase (soft-duplicate check).

---

### Pitfall 11: Tipo de Comprobante Ambiguity — Factura vs Remito vs Ticket

**What goes wrong:** GPT-4o may misclassify invoice type because:
- A `Remito` (delivery note) looks visually similar to a `Factura` and may have a CAE.
- `Ticket` (from fiscal printer) uses the same A/B/C classification but lacks a CAE in some configurations.
- The letter type (A/B/C) appears prominently but the document type (Factura vs Nota de Crédito vs Nota de Débito) is in smaller text that OCR/vision may misread.
- Factura M (issued by new monotributistas) can be mistaken for Factura B.

**Prevention:**
1. In the Pydantic schema, `tipo_comprobante` should be an enum with all valid AFIP codes: `FACTURA_A`, `FACTURA_B`, `FACTURA_C`, `FACTURA_M`, `FACTURA_E`, `NOTA_CREDITO_A`, `NOTA_CREDITO_B`, `NOTA_CREDITO_C`, `NOTA_DEBITO_A`, `NOTA_DEBITO_B`, `NOTA_DEBITO_C`, `REMITO`, `TICKET`. Using an enum prevents free-text hallucinations.
2. System prompt must include a brief description of how to distinguish each type. "Factura A shows IVA separately; Factura C does not; Nota de Crédito/Débito says 'NC' or 'ND' in the header."
3. When `tipo_comprobante` is `REMITO` or `TICKET`, skip CAE validation (these may legitimately lack CAE).

**Phase:** GPT-4o prompt engineering phase.

---

### Pitfall 12: OpenAI Vision Cost Runaway on Large Images

**What goes wrong:** GPT-4o vision pricing is tile-based. High-resolution invoice photos (common from modern phones: 3000×4000+ pixels) are processed at `detail: "high"`, which tiles the image into multiple 512×512 chunks and charges per tile. A 12MP phone photo can cost 5–10x more than expected.

**Prevention:**
1. Resize and re-compress images before sending to OpenAI. Target 1500–2000px on the long edge, JPEG quality 85. This is sufficient for invoice text extraction and dramatically reduces tile count.
2. Set a `max_tokens` limit on the completion (invoice extraction output is small — 500 tokens is generous).
3. Configure OpenAI usage alerts at $10 and $50 thresholds.
4. At 20 invoices/day with optimized images: cost is roughly $0.05–0.15/day — negligible. Without optimization: $0.50–1.50/day or more.

**Detection:** Log `usage.prompt_tokens` and `usage.completion_tokens` on every OpenAI call. Any prompt_tokens > 3000 for a single invoice = image was not resized.

**Phase:** Extraction pipeline phase.

---

### Pitfall 13: AFIP/ARCA Branding Change — AFIP Was Replaced by ARCA in October 2024

**What goes wrong:** Documentation written before October 2024 references "AFIP" as the tax authority. Presidential Decree 953/2024 (October 25, 2024) formally dissolved AFIP and replaced it with ARCA (Agencia de Recaudación y Control Aduanero). Invoices printed after this transition may print "ARCA" instead of "AFIP" in the header. Prompts that tell GPT-4o to "look for the AFIP logo" will miss these invoices.

**Prevention:**
1. Prompts and documentation must reference both "AFIP" and "ARCA" as valid issuers.
2. The invoice validation logic and UI should not hardcode "AFIP" as a display label.
3. The underlying CAE structure and CUIT format are unchanged — this is purely a branding change.

**Phase:** GPT-4o prompt engineering phase.

---

### Pitfall 14: Supabase Signed URL for Storage: Wrong Path Prefix Breaks RLS Policy

**What goes wrong:** Supabase Storage RLS policies on `storage.objects` use `foldername()` to extract the first path component and compare it to `auth.uid()` or a role. If the file upload path is `invoices/2024/01/file.jpg`, the `foldername()` function extracts `invoices`, not the user or role identifier. Policies written as `(storage.foldername(name))[1] = auth.uid()` silently reject all operations.

**Prevention:**
1. Design storage paths so the relevant scoping component is the first path level: e.g., `invoices/<year>/<month>/<uuid>.jpg` where the RLS policy uses authenticated role check rather than user-scoped path check.
2. For this project (admin-only access via authenticated role): the storage policy should simply be `(auth.role() = 'authenticated')` — no path-based scoping needed since all admins see all invoices.
3. The FastAPI backend uses `service_role` key for uploads (bypasses RLS entirely — appropriate for server-to-server writes).

**Detection:** Attempt a file upload using the anon client with a logged-in session and watch for `new row violates row-level security policy` errors.

**Phase:** Storage + authentication phase.

---

### Pitfall 15: Sender Allowlist Race Condition — Unknown Sender Gets Stuck Silently

**What goes wrong:** The allowlist check queries the DB on every incoming message. If a sender is not in the allowlist, the intended behavior is to send a rejection message and stop. But if the rejection message send itself fails (Twilio/Meta API error), or if the background task silently crashes (see Pitfall 2), the unknown sender receives no feedback. They send the same invoice again. And again.

**Prevention:**
1. The rejection message send should be fire-and-forget with a logged error — the primary effect (not processing the invoice) is already achieved.
2. Log every rejected sender with their phone number so admins can add them to the allowlist if they were accidentally omitted.
3. The allowlist query must happen inside the background task after ACK, not in the synchronous path, to avoid adding latency to the 200 response.

**Phase:** WhatsApp integration + security phase.

---

## Minor Pitfalls

---

### Pitfall 16: React Auth Session Expiry During Long Admin Sessions

**What goes wrong:** Supabase Auth JWTs expire (default: 1 hour). If an admin has the invoice UI open without interaction for an extended period, their token expires. Subsequent Supabase client calls return `403 Forbidden` from RLS policies. Without proper `onAuthStateChange` handling, the UI shows empty data tables or silent API errors rather than redirecting to login.

**Prevention:**
1. Subscribe to `supabase.auth.onAuthStateChange` globally and redirect to login when `event === 'SIGNED_OUT'` or session is null.
2. Supabase client auto-refreshes tokens when `autoRefreshToken: true` (the default). Do not disable this.
3. Display a visible error state on any 403 response rather than an empty list.

**Phase:** Frontend authentication phase.

---

### Pitfall 17: IVA Rate Assumptions Hardcoded

**What goes wrong:** Argentina has multiple active IVA rates: 21% (standard), 10.5% (reduced — food, construction), 27% (utilities), 0% (exempt). Additionally, percepciones (provincial tax perceptions) appear as separate line items that look like IVA to the model. Hardcoding "IVA = 21%" anywhere in prompts or validation causes misclassification.

**Prevention:**
1. Extract IVA as a raw amount field, not as a calculated percentage. Store `iva_monto` (the dollar amount from the invoice) and optionally `iva_alicuota` (the rate printed).
2. Do not validate IVA amounts by recalculating from the rate — Argentine invoices sometimes have rounding differences.
3. Percepciones should be a separate `percepciones` field in the schema, not lumped into IVA.

**Phase:** Schema definition + extraction pipeline phase.

---

### Pitfall 18: WhatsApp Message Sent to Non-Allowlisted Number Before Reply Window Closes

**What goes wrong:** WhatsApp Cloud API requires that outbound messages to users who initiated conversation use the "reply" API (within 24 hours). If the server tries to send a reply outside this window, or using the wrong endpoint, the message fails silently with error code `131053` (rate limit) or the message is blocked. This affects confirmation and rejection messages.

**Prevention:**
1. Always send replies using the `reply` message type referencing the original `message_id` within the background task.
2. Process webhook events promptly — the 24-hour window is generous for normal operation, but backlogs during outages can cause issues.

**Phase:** WhatsApp integration phase.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| WhatsApp webhook setup | Status event flood, duplicate delivery | Filter status events first; idempotency key on message_id |
| Media download pipeline | 5-minute URL expiry | Download immediately in background task as first operation |
| GPT-4o extraction schema | Hallucinated CUITs/CAE | All fields Optional, explicit null instruction, post-extraction checksum |
| Argentine invoice types | Tipo de comprobante misclassification | Enum schema, ARCA/AFIP dual branding, type-specific CAE logic |
| DB schema creation | RLS off by default | Include ENABLE RLS in every CREATE TABLE migration |
| Storage setup | Public bucket, path-scoped RLS bug | Keep private, authenticated role policy, service_role for writes |
| Duplicate detection | Invoice number alone insufficient | Composite UNIQUE constraint (cuit + tipo + punto_venta + numero) |
| FastAPI background tasks | Silent failures | Explicit try/except + error record in DB |
| React frontend auth | Session expiry → empty tables | onAuthStateChange redirect + autoRefreshToken |
| Cost control | Large images → tile explosion | Resize to ~1500px max before OpenAI call |

---

## Sources

- [Guide to WhatsApp Webhooks: Features and Best Practices — Hookdeck](https://hookdeck.com/webhooks/platforms/guide-to-whatsapp-webhooks-features-and-best-practices)
- [How to Implement Webhook Idempotency — Hookdeck](https://hookdeck.com/webhooks/guides/implement-webhook-idempotency)
- [Downloading Media using WhatsApp Cloud API Webhook — Medium](https://medium.com/@shreyas.sreedhar/downloading-media-using-whatsapps-cloud-api-webhooks-and-uploading-it-to-aws-s3-bucket-via-nodejs-07c5cbae896f)
- [Supabase Security: Exposed Anon Keys, RLS, and Misconfigurations](https://www.stingrai.io/blog/supabase-powerful-but-one-misconfiguration-away-from-disaster)
- [Row Level Security — Supabase Docs](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [Storage Access Control — Supabase Docs](https://supabase.com/docs/guides/storage/security/access-control)
- [Structured Outputs not reliable with GPT-4o-mini and GPT-4o — OpenAI Community](https://community.openai.com/t/structured-outputs-not-reliable-with-gpt-4o-mini-and-gpt-4o/918735)
- [GPT-4o Hallucinating at temp:0 — OpenAI Community](https://community.openai.com/t/gpt-4o-hallucinating-at-temp-0-unusable-in-production/746750)
- [How to Fix OpenAI Structured Outputs Breaking Your Pydantic Models — Medium](https://medium.com/@aviadr1/how-to-fix-openai-structured-outputs-breaking-your-pydantic-models-bdcd896d43bd)
- [BackgroundTasks do not run when request failed — FastAPI Issue #2604](https://github.com/fastapi/fastapi/issues/2604)
- [Exceptions with handlers are replaced in background task — FastAPI Issue #2505](https://github.com/fastapi/fastapi/issues/2505)
- [Managing Background Tasks in FastAPI — DEV Community](https://dev.to/richard_quaicoe_2398278be/managing-background-tasks-in-fastapi-from-basic-to-production-ready-beyond-fire-and-forget-ddm)
- [How to Detect Duplicate Invoices — Klippa](https://www.klippa.com/en/blog/information/how-to-detect-duplicate-invoices/)
- [Duplicate Invoice Detection Methodology — Number7AI](https://number7ai.com/docs/duplicate-detection)
- [Argentina CUIT Tax ID Number — LookupTax](https://lookuptax.com/docs/tax-identification-number/argentina-tax-id-guide)
- [Electronic Invoicing in Argentina — EDICOM](https://edicomgroup.com/blog/electronic-invoice-argentina)
- [Qué es el CAE — mifacturero.ar](https://mifacturero.ar/que-es-el-cae)
- [Tipos de Factura A, B, C y E Argentina — micuil.net](https://micuil.net/factura-a-b-c-y-e/)
- [Database Migrations — Supabase Docs](https://supabase.com/docs/guides/deployment/database-migrations)
- [Migration History Mismatch — Supabase GitHub Discussion](https://github.com/orgs/supabase/discussions/40721)
- [WhatsApp Status Webhooks Eating n8n Executions — n8n Community](https://community.n8n.io/t/how-to-stop-whatsapp-cloud-api-status-webhooks-from-eating-your-n8n-executions-using-a-cloudflare-worker-for-generic-webhook-node-users/294956)
- [Cost of Vision using GPT-4o — OpenAI Community](https://community.openai.com/t/cost-of-vision-using-gpt-4o/775002)
- [User Sessions — Supabase Docs](https://supabase.com/docs/guides/auth/sessions)
- [HIGH: WhatsApp webhook does not verify X-Hub-Signature-256 — GitHub Issue](https://github.com/theonlyhennygod/zeroclaw/issues/51)
