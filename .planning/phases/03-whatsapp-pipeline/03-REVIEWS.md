---
phase: 3
reviewers: [codex]
reviewed_at: 2026-05-14T15:47:50Z
plans_reviewed: [03-01-PLAN.md, 03-02-PLAN.md]
---

# Cross-AI Plan Review — Phase 3: WhatsApp Pipeline

## Codex Review

## Summary

Both plans are coherent and mostly aligned with Phase 3's goal. Plan 01 correctly isolates provider concerns, webhook validation, allowlist gating, fast acknowledgement, and background scheduling. Plan 02 completes the real value path by connecting media download, extraction, duplicate detection, persistence, and sender replies. The main risks are around provider-specific signature semantics, background task lifecycle reliability, mismatch between Twilio webhook behavior and the stated HMAC-SHA256 requirement, and a few transaction/error-handling details in the real processing path.

## Plan 01 Review

### Strengths

- Clear thin-slice objective: validates inbound request, checks allowlist, replies quickly, schedules background work.
- Good provider abstraction with `WhatsAppProvider`, enabling Twilio now and Meta later.
- Immediate rejection of invalid signatures with HTTP 401 satisfies a core security requirement.
- Allowlist check before acknowledgement is correct.
- SSRF guard on Twilio media download is a good baseline.
- Strong-reference tracking for `asyncio.create_task()` avoids accidental task garbage collection.
- Duplicate unique index is correctly case-insensitive and partial for non-null fields.
- Tests cover provider delegation, signature URL forwarding, allowlist behavior, no-media handling, and background scheduling.

### Concerns

- **HIGH:** Twilio signature validation may not satisfy the stated `HMAC-SHA256` requirement. Twilio's standard `RequestValidator` historically validates `X-Twilio-Signature`, which is HMAC-SHA1-based for many webhook flows. If the project explicitly requires HMAC-SHA256, this needs confirmation or a custom validator.
- **HIGH:** `asyncio.create_task()` inside a web worker is fragile for production. Tasks can be lost on process restart, deploy, worker timeout, or crash. It may be acceptable for v1/local, but this should be explicitly documented as a known limitation.
- **MEDIUM:** Returning HTTP 200 for non-allowlisted senders is operationally reasonable to avoid retries, but the plan should explicitly state that no invoice processing or DB write happens.
- **MEDIUM:** `MetaCloudProvider` stub in the same phase may be unnecessary scope unless provider selection must exist immediately.
- **MEDIUM:** Signature validation using `str(request.url)` can fail behind proxies if public URL differs from internal URL. Twilio signature validation is sensitive to exact URL.
- **LOW:** SSRF guard using `startswith("https://api.twilio.com/")` is better than nothing, but URL parsing via `urllib.parse` would be safer and clearer.
- **LOW:** No mention of idempotency for repeated Twilio webhook retries using `MessageSid`.

### Suggestions

- Verify Twilio signature algorithm against the requirement. If HMAC-SHA256 is mandatory, either use Meta Cloud API validation or implement explicit SHA-256 validation over the agreed canonical payload.
- Add a setting for externally visible webhook base URL, or document proxy requirements so signature validation receives the exact URL Twilio signed.
- Parse media URLs and validate scheme/host instead of relying on string prefix.
- Add an idempotency record or at least plan for `MessageSid` dedupe before scheduling background processing.
- Consider FastAPI `BackgroundTasks` for simple in-process behavior, or document that durable queues are out of scope for v1.
- Keep `MetaCloudProvider` minimal unless tests or config require it now.

### Risk Assessment

**MEDIUM-HIGH.** The webhook shape is sound, but signature semantics and in-process background tasks are important risks. If Twilio's validator does not meet the explicit HMAC-SHA256 requirement, Plan 01 would fail a core success criterion despite passing tests.

---

## Plan 02 Review

### Strengths

- Completes the actual end-to-end pipeline: download, validate, extract, persist, reply.
- Correctly avoids request-scoped DB dependencies inside background processing.
- Duplicate detection is handled at both application and database levels.
- `IntegrityError` race handling is included, which is important under webhook retries or repeated submissions.
- Status mapping to `auto_saved` and `pending_review` directly addresses VAL-02 and VAL-03.
- Error replies for extraction refusal/failure align with unreadable-image criteria.
- Tests cover important behavior: duplicate paths, status-specific replies, extraction failures, unsupported media, and task cleanup.

### Concerns

- **HIGH:** "Content-type guard before download" relies on `MediaContentType0`, which is user/provider metadata. It is useful, but not sufficient. The downloaded bytes should also be validated by magic bytes or image decoding.
- **HIGH:** Duplicate key is `numero_documento + proveedor`, but provider normalization may be weak. Case-insensitive comparison alone may miss whitespace, punctuation, legal suffix, accent, or CUIT-based duplicates.
- **HIGH:** If `send_message` fails after persistence, the invoice is saved but the user receives no completion reply. The plan should define retry/logging behavior.
- **MEDIUM:** The total calculation in `format_summary_reply` may duplicate extraction/business logic and risks mismatch with extracted total. For invoice summaries, prefer the extracted invoice total when available.
- **MEDIUM:** Unsupported file format should likely be checked both before and after download. Some providers may send generic MIME types.
- **MEDIUM:** `IntegrityError` handling with an em dash placeholder for original date is user-visible and less helpful. The process should try to re-query the duplicate after rollback.
- **MEDIUM:** No explicit handling for multiple media attachments in one WhatsApp message. The plan appears to process only `MediaUrl0`.
- **MEDIUM:** No mention of retaining original files for audit, despite project security requirements.
- **LOW:** "Stateless `InvoiceService`" is reasonable, but persistence mapping can grow quickly; keep it narrowly focused.
- **LOW:** Need clarity on whether failed/unreadable submissions create no DB record or a failed audit record.

### Suggestions

- Validate downloaded media using image decoding or magic-byte checks, not only provider MIME type.
- Use extracted `total` for the reply when present; only compute fallback totals if the extraction result lacks a reliable invoice total.
- Normalize duplicate fields consistently before comparison and indexing. At minimum trim whitespace; ideally consider CUIT when available.
- After duplicate `IntegrityError`, rollback and re-query the existing invoice so the duplicate reply can include the real original date.
- Define behavior for multiple attachments: reject with a clear Spanish message, process only the first, or schedule one task per media item.
- Add original file retention to the processing sequence before extraction, with a stable storage path linked to the invoice or message ID.
- Add retry-safe idempotency using WhatsApp/Twilio message ID to avoid duplicate processing on webhook retries.
- Add tests for provider send failure, media download failure, multiple media, invalid image bytes with valid MIME type, and original-file persistence.

### Risk Assessment

**MEDIUM.** The plan is directionally strong and likely achieves most user-facing Phase 3 goals. The main risks are operational reliability, duplicate normalization, media validation depth, and audit-file retention. These are fixable without changing the architecture.

---

## Overall Assessment

The two-wave split is sensible: Plan 01 establishes the inbound WhatsApp boundary, while Plan 02 fills in the business pipeline. The largest gap is that the plans may pass their own tests while still missing two project-level expectations: true HMAC-SHA256 webhook validation and original file retention for audit. Addressing those explicitly would make the phase much stronger.

---

## Consensus Summary

Only one reviewer was invoked (Codex). Consensus is the Codex review itself.

### Agreed Strengths

- Provider abstraction (`WhatsAppProvider` Protocol) is well-designed for extensibility
- Strong-reference task retention pattern (`_background_tasks` set + done_callback) correctly prevents GC
- Two-level duplicate detection (app-level SELECT + DB UNIQUE INDEX race backstop) is thorough
- Test coverage is comprehensive for happy and failure paths

### Agreed Concerns

| Severity | Concern |
|----------|---------|
| HIGH | Twilio `RequestValidator` may use HMAC-SHA1, not HMAC-SHA256 — confirm against requirement INF-02 |
| HIGH | `asyncio.create_task()` in web worker loses tasks on process restart — document v1 limitation |
| HIGH | `MediaContentType0` content-type guard is insufficient without magic-byte validation after download |
| MEDIUM | `str(request.url)` for signature validation breaks behind reverse proxies |
| MEDIUM | `IntegrityError` race duplicate shows em-dash for fecha instead of re-querying the real date |
| MEDIUM | Multiple media attachments (`MediaUrl1+`) not handled — plan processes only `MediaUrl0` |
| MEDIUM | Original file retention for audit not explicitly planned |

### Divergent Views

N/A — single reviewer.

---

*To incorporate this feedback into planning: `/gsd-plan-phase 3 --reviews`*
