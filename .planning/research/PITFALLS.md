# Pitfalls Research

**Domain:** Conversational WhatsApp expense bot with proactive scheduling (v2.0 Gastos Bot) — multi-turn DB-backed state machine, proactive outbound via Meta Cloud API / Twilio, hybrid LLM-intent + deterministic control, money recording in Argentine Spanish
**Researched:** 2026-05-27
**Confidence:** HIGH (WhatsApp platform constraints verified against official Meta and Twilio docs; APScheduler behavior verified against official docs and GitHub issues; DB concurrency patterns verified against PostgreSQL official docs)

---

> **Note on scope:** Pitfalls 1–18 below are the **v1.0 baseline** (invoice capture system). Pitfalls 19–32 are the **v2.0 Gastos Bot additions** (conversational state machine, proactive scheduling, money recording). Roadmappers: phase references in pitfalls 19–32 use the v2.0 phase numbering from the approved design (Phase 1 = data + conversation core, Phase 2 = WhatsApp gastos flow, Phase 3 = proactive scheduler, Phase 4 = admin UI).

---

## Critical Pitfalls

### Pitfall 1: Media URL Expires in 5 Minutes — Synchronous Download Will Miss It

**What goes wrong:**
The WhatsApp Cloud API webhook payload contains a `media_id`, not a raw file URL. You must make a separate GET call to retrieve the temporary download URL. That URL expires after **5 minutes**. If the webhook handler performs any slow work before downloading — logging, DB writes, GPT-4o calls — the image is gone and extraction never happens.

**Why it happens:**
Developers treat the media_id as stable storage. It isn't. The download URL is a short-lived CDN signed URL scoped to that API call.

**How to avoid:**
1. ACK the webhook immediately with `200 OK` (see Pitfall 4).
2. In the background task, retrieve the media URL first — before any other work.
3. Download the raw bytes and upload to local storage in the same background task, within the first operation.
4. Store the local path (not the WhatsApp URL) in the DB. Never store the ephemeral WhatsApp URL.

**Warning signs:**
Log every media URL retrieval attempt with timestamp delta from webhook receipt. Any delta > 60 seconds risks expiry at peak load.

**Phase to address:** v1.0 Phase 3 — WhatsApp integration (already addressed). v2.0 Phase 2 — same pattern applies to ticket photo steps in the gastos flow.

---

### Pitfall 2: FastAPI BackgroundTasks Fails Silently in Production

**What goes wrong:**
FastAPI's `BackgroundTasks` runs the task after the response is sent. If the task raises an exception, the exception is swallowed — it appears nowhere in the HTTP response, and without explicit try/except + logging inside the task function, it produces zero output. The webhook appears to have succeeded; the invoice is simply never processed.

**Why it happens:**
FastAPI's exception handlers do not intercept background task exceptions — the response is already finalized. Known FastAPI issues #2604, #3589, #2505 confirm this behavior.

**How to avoid:**
1. Wrap every background task body in `try/except Exception as e: logger.error(...)`.
2. Write a failed record to the DB on exception so the UI can surface it.
3. For v1 (< 20 invoices/day), `BackgroundTasks` is acceptable **only if** the above error capture is in place.

**Warning signs:**
Add a heartbeat log entry at the start of every background task execution. Missing heartbeats on received webhooks = silent failure.

**Phase to address:** v1.0 Phase 3 (already addressed). v2.0: the conversation orchestrator runs synchronously inside the request, not in a background task — this removes the risk for the conversational path, but ticket photo processing still uses the async pattern.

---

### Pitfall 3: RLS Not Enabled on New Tables — Postgres Default Is Insecure

**What goes wrong:**
Every new table created in Postgres with Supabase/direct Postgres has RLS disabled by default. If an anon key or frontend client can reach the DB directly, all rows in any table without RLS policies are exposed.

**How to avoid:**
Include `ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;` in every migration that creates a table. For this project's local Docker Postgres, the risk is lower (no public network exposure), but the pattern must be correct from the start for production.

**Warning signs:**
`SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname = 'public';` — any row with `rowsecurity = false` is a potential exposure.

**Phase to address:** v1.0 Phase 1 (already addressed for invoices tables). v2.0 Phase 1 — new tables `gastos`, `caja_cierres`, `conversations` must also include `ENABLE ROW LEVEL SECURITY` in their migration.

---

### Pitfall 4: Webhook Response Timeout Triggers Retries → Duplicate Processing

**What goes wrong:**
WhatsApp requires a `200 OK` response within approximately 5 seconds (Meta) or 10 seconds (Twilio). If the handler performs synchronous work inside the request-response cycle, timeouts trigger retries with the same message, causing duplicate processing.

**How to avoid:**
1. ALWAYS return `200 OK` from the webhook endpoint before any processing.
2. Implement idempotency using the WhatsApp message ID as a deduplication key.
3. For the gastos flow, the conversation state update must be transactional — the idempotency key check and state update must happen atomically.

**Warning signs:**
Monitor time-to-response on the webhook endpoint. Any p99 > 3 seconds is dangerous.

**Phase to address:** v1.0 Phase 3 (already addressed). v2.0 Phase 2 — the conversational flow adds DB reads (load conversation row) before returning 200; keep these under 200ms.

---

### Pitfall 5: GPT-4o Hallucinates Fields When Image Is Ambiguous

**What goes wrong:**
When using OpenAI Structured Outputs with a Pydantic schema, the model is constrained to always produce values matching the schema. If a field is not nullable and the image is blurry, GPT-4o will fabricate plausible-looking values rather than return `null`. CUIT numbers, CAE codes, and monetary amounts are especially vulnerable.

**How to avoid:**
1. All extracted fields must be `Optional[T]`. Never use required non-nullable fields for extracted values.
2. System prompt must explicitly state: "If a field is not visible, return null. Do NOT guess."
3. Apply deterministic post-extraction validation (CUIT mod-11 checksum, CAE is exactly 14 digits).

**Warning signs:**
CUIT checksum failures on extracted data = hallucination is occurring.

**Phase to address:** v1.0 Phase 2 (already addressed). v2.0 Phase 2 — the ticket photo flows through the same extraction pipeline; the same rules apply. For the free-text monto extraction (slot_extraction.py), see Pitfall 25.

---

### Pitfall 6: Invoice Storage Bucket Made Public

**What goes wrong:**
Making the storage bucket public bypasses RLS entirely. Invoice and ticket images contain sensitive financial data (CUITs, amounts, vendor identities).

**How to avoid:**
Keep the image bucket private. Generate signed URLs server-side with short TTL (1 hour). Never store the signed URL in the database.

**Phase to address:** v1.0 Phase 1 (already addressed). v2.0 Phase 2 — ticket images for gastos use the same `LocalStorageBackend`; no new risk introduced.

---

### Pitfall 7: WhatsApp Status Webhooks Flood the Endpoint With Noise

**What goes wrong:**
WhatsApp sends `delivered`, `read`, and `sent` status update events to the same webhook endpoint as incoming messages. Without filtering, every outbound message triggers 2–3 additional status webhooks.

**How to avoid:**
At the top of the webhook handler, check for status events and return `200 OK` immediately without processing. v2.0 gastos webhook handler must also implement this filter — proactive prompts will generate status events at 2× per manager per firing (12:00 and 17:00).

**Phase to address:** v1.0 Phase 3 (already addressed). v2.0 Phase 2 — verify the new `gastos_whatsapp.py` handler also filters status events.

---

### Pitfall 8–18: (v1.0 pitfalls — CUIT normalization, Supabase migration drift, duplicate invoice detection, tipo de comprobante ambiguity, OpenAI cost runaway, ARCA/AFIP branding, storage RLS path prefix, sender allowlist race, React auth session expiry, IVA rate assumptions, reply window for non-allowlisted senders)

These are documented in the v1.0 research and remain valid. They are not repeated here to keep focus on v2.0 additions. The v2.0 roadmap should treat them as addressed constraints unless a phase explicitly touches those subsystems.

---

## v2.0 Critical Pitfalls — Conversational Bot + Proactive Scheduling

---

### Pitfall 19: PROACTIVE MESSAGES REQUIRE PRE-APPROVED TEMPLATES — FREE-FORM TEXT IS BLOCKED OUTSIDE THE 24-HOUR WINDOW

**This is the single most important constraint for v2.0. It will block the scheduler phase entirely if not addressed before implementation.**

**What goes wrong:**
The design calls for proactive prompts at 12:00 and 17:00 Buenos Aires time. If a manager has not sent the bot any message in the last 24 hours, Meta and Twilio both reject any attempt to send them a free-form message. The API call returns an error (Meta: `131026` "Message undeliverable"; Twilio: `Error 63016` "Outside messaging window"). The prompt is silently dropped. The manager receives nothing.

This is not an edge case. At 12:00, the last inbound message from a manager is almost certainly from the previous day's 17:00 prompt response — well outside 24 hours. Every morning prompt **will** hit this wall on typical days without prior activity.

**Why it happens:**
WhatsApp's Business Messaging Policy requires that all business-initiated conversations (where the business sends first after 24+ hours of inactivity) use a pre-approved Message Template. This is enforced at the API level — the SDK call does not provide a way to bypass it. The 24-hour customer service window opens only when the user sends a message to the business, and resets each time the user replies. Proactive scheduled messages sent after the window closes are, by definition, business-initiated and require a template.

Meta error reference: [https://developers.facebook.com/documentation/business-messaging/whatsapp/reference/errors#131026](https://developers.facebook.com/documentation/business-messaging/whatsapp/reference/errors#131026)
Twilio error reference: [https://www.twilio.com/docs/api/errors/63016](https://www.twilio.com/docs/api/errors/63016)

**How to avoid:**
1. **Create and pre-approve a WhatsApp Message Template** for the proactive prompt before building the scheduler. Template approval can take up to 24 hours. Without an approved template, Phase 3 (scheduler) cannot go to production.
2. The template must be in the **Utility** category (not Marketing), since it is a transactional reminder about a pending business task. Utility templates cost less per conversation than Marketing templates and are less likely to be rejected.
3. The template content must be static or use only approved variable placeholders (e.g., `{{1}}` for the manager's name or the date). A typical template:
   - English submission: "Hi {{1}}, it's time for your midday cash register report. Please reply with the current cash on hand."
   - Meta reviews templates in Spanish — submit the Spanish text as the template body: "Hola {{1}}, es hora del cierre del mediodía. ¿Cuánto efectivo queda en caja?"
4. When sending via Twilio: use `content_sid` (the approved template's Content SID) instead of `body`. When sending via Meta Cloud API: use the `template` object in the messages API payload with the approved template name and language code.
5. **Do NOT attempt to send a free-form message and fall back on failure.** The failure is silent at the end user level — they receive nothing. The scheduler must always use the template path for outbound-initiated messages.
6. Log every outbound prompt with the API response status. A response with `error_code: 131026` or Twilio `63016` is a template configuration failure, not a transient error — alerting is required.
7. **Opt-in documentation**: Meta requires that users have opted in to receive proactive messages from the business. For this single-company internal deployment, document that all managers in the allowlist have explicitly consented (this is the "opt-in" that satisfies Meta's policy).

**Warning signs:**
- Scheduler fires at 12:00 and 17:00 but managers report receiving no prompts.
- API responses contain `131026` (Meta) or `63016` (Twilio) error codes.
- The bot works fine when tested manually (because the tester just sent a message, opening the 24-hour window) but fails in production (where managers haven't messaged since the previous day).

**Phase to address:** Phase 3 (proactive scheduler). However, template creation and approval must happen during Phase 1 or 2 — approval can take 24 hours and blocks Phase 3 from going to production. Add "WhatsApp template created and approved" as a Phase 2 exit criterion.

---

### Pitfall 20: Webhook Retry Delivering Duplicate Inbound Messages → Double-Recorded Gastos

**What goes wrong:**
WhatsApp delivers webhooks with at-least-once semantics. A manager sends "pagué $500 en verdulería" and the bot receives the webhook, processes it, updates the conversation state to `awaiting_monto` — but the API response is delayed by 2 seconds under load, causing Twilio/Meta to retry. The second webhook delivery finds the conversation in `awaiting_monto` (already transitioned), misidentifies the repeated message as a monto response, and interprets "pagué $500 en verdulería" as the amount response, recording `monto = null` (parse failure) or corrupting the draft gasto.

The existing v1.0 `_processed_message_sids` in-memory set handles this for the invoice flow, but this set is **cleared on restart** and is not shared across multiple workers (if Gunicorn is ever added). For a conversational flow where state matters more, this in-memory approach is insufficient.

**Why it happens:**
At-least-once delivery is documented behavior for both Meta Cloud API and Twilio. The retry interval is typically 5–30 seconds. Any processing that takes > 5 seconds increases the retry probability significantly.

**How to avoid:**
1. Store processed message IDs in the `conversations` table (or a separate `processed_messages` table) using the WhatsApp `message_id` (the unique ID from the webhook payload, not the Twilio `MessageSid` which can differ on retry). Insert with `ON CONFLICT DO NOTHING` — the atomic check-and-claim prevents the race.
2. The idempotency check must be the **first DB operation** in the handler, before loading conversation state. If the message ID is already recorded, return 200 immediately.
3. Set a TTL on processed message IDs (48 hours is sufficient — retries stop within minutes). Clean up via a scheduled job or Postgres `updated_at + DELETE WHERE updated_at < NOW() - INTERVAL '48 hours'`.
4. The `conversations` row update must use `SELECT FOR UPDATE SKIP LOCKED` to prevent two concurrent webhook deliveries from both loading the same conversation state and both writing back.

**Warning signs:**
- Conversation state machine enters an unexpected state after a retry period.
- The same `message_id` appears twice in logs.
- A gasto is created with a `concepto` that looks like an amount string (e.g., "pagué $500 en verdulería" stored as the concepto because the duplicate webhook was processed in `awaiting_concepto` state).

**Phase to address:** Phase 1 (data model — include `message_id` column in `conversations` with a unique index) and Phase 2 (webhook handler — implement the idempotency check before state load).

---

### Pitfall 21: Concurrent Messages From Same Sender Racing on the Conversation Row

**What goes wrong:**
WhatsApp can deliver multiple webhook events for the same sender nearly simultaneously: for example, a manager sends a voice note then immediately sends a text message, or the WhatsApp client splits a long message into two. Both webhooks arrive within milliseconds and both load the same `conversations` row concurrently. Both read the same state, both compute the next action, and both write back — the second write overwrites the first, producing a corrupted state (e.g., `draft_gasto` has only the slots from one of the two messages).

**Why it happens:**
`asyncio.create_task` and FastAPI's async handler both allow concurrent execution. Without explicit row locking, two concurrent handlers both execute `SELECT * FROM conversations WHERE sender_phone = $1` and get the same row, then both `UPDATE` it.

**How to avoid:**
1. Use `SELECT ... FOR UPDATE` (or `FOR NO KEY UPDATE` which is less restrictive) on the `conversations` row at the start of conversation processing. This serializes concurrent handlers for the same sender — the second one blocks until the first commits.
2. Keep the transaction short: load row → compute next action → update row → commit → then send the WhatsApp reply outside the transaction. Sending the reply inside the transaction holds the lock for the entire network round-trip.
3. Use `NOWAIT` or a short lock timeout to detect if the lock cannot be acquired immediately. If it can't, this is likely a retry of the same message — check idempotency and return early.

**Warning signs:**
- Conversation state jumps unexpectedly (e.g., from `idle` directly to `confirm` skipping intermediate states).
- `draft_gasto` JSON is missing fields that the manager clearly provided.
- Postgres logs show high lock wait times for the `conversations` table.

**Phase to address:** Phase 1 (data model — `conversations` table design) and Phase 2 (orchestrator — `SELECT FOR UPDATE` in `conversation.py`).

---

### Pitfall 22: Stuck / Abandoned Conversations Never Reset — State Machine Gets Permanently Corrupted

**What goes wrong:**
A manager starts recording a gasto (state transitions to `awaiting_monto`), then gets distracted and never responds. The conversation row stays in `awaiting_monto` indefinitely. Days later, the manager sends an unrelated message ("Hola, ¿todo bien?") or tries to start a new gasto. The orchestrator reads the stale state and continues prompting for the amount from the previous session, confusing the manager. Worse, if the manager sends "25000" thinking they are starting a new record, the bot interprets this as the monto from the old session and creates a gasto the manager never intended.

**Why it happens:**
DB-backed conversation state has no built-in expiry. Unlike in-memory sessions that are cleared on restart, the DB row persists indefinitely.

**How to avoid:**
1. Add a `timeout_at` column to `conversations` (or use `updated_at` with a configurable threshold). Before processing any message, check if `now() > timeout_at` (or `updated_at < now() - interval '4 hours'`). If timed out, reset state to `idle`, clear `draft_gasto`, and treat the incoming message as a fresh start.
2. A reasonable timeout for a cash expense recording session is 2–4 hours. Longer than that means the manager has moved on.
3. When resetting due to timeout: log the abandoned draft gasto so admins can review it if needed. Send the manager a message explaining the session was reset: "Tu registro anterior no fue completado y fue cancelado. Podés empezar uno nuevo."
4. Run a periodic cleanup job (APScheduler, same scheduler as the 12:00/17:00 prompts) that resets all stale conversation rows once per hour.

**Warning signs:**
- Managers complain the bot "asks for the wrong thing."
- The bot asks "¿Cuánto pagaste?" when the manager sends a greeting or a new intent.
- `conversations` rows have `updated_at` timestamps from multiple days ago with non-`idle` states.

**Phase to address:** Phase 1 (data model — `timeout_at` column or `updated_at`-based logic) and Phase 2 (orchestrator — timeout check at entry point of `process_message`).

---

### Pitfall 23: Scheduler Missed Fires on Process Restart — Prompt Never Delivered

**What goes wrong:**
APScheduler with the default `MemoryJobStore` loses all scheduled job state when the Uvicorn process restarts. If the process was down at 12:00 (e.g., a Docker container restart), the job is simply not executed — there is no durable record that the fire time was missed. The manager receives no midday prompt. With `misfire_grace_time` set too small, even a brief slowdown during job execution (e.g., sending WhatsApp messages to 3 managers) causes APScheduler to skip the job as "misfired."

**Why it happens:**
APScheduler's in-process `AsyncIOScheduler` stores all job state in memory. A restart wipes it. The `MemoryJobStore` (default) has no persistence. The `misfire_grace_time` default is 1 second — any execution latency beyond 1 second is treated as a misfire and skipped.

**How to avoid:**
1. Set `misfire_grace_time` to at least 600 seconds (10 minutes) for the 12:00 and 17:00 jobs. A missed prompt is not catastrophic, but a prompt delivered up to 10 minutes late is acceptable.
2. Use `coalesce=True` on the cron jobs. If the process was down for a long period (spanning multiple fire times), APScheduler will execute the job exactly once when it comes back up rather than running it N times for all missed fires.
3. Set `replace_existing=True` when calling `add_job()` inside the FastAPI lifespan handler. Without this, every restart registers a duplicate job alongside the existing one (if using a persistent job store), resulting in double-fires.
4. For a single-company deployment with ~2 managers, the in-process `MemoryJobStore` is acceptable **if** the process is managed by a process supervisor (Docker restart policy `unless-stopped`). Document this as a known gap: if the Docker host is down at noon, the prompt is lost.
5. Upgrade path: replace `MemoryJobStore` with `SQLAlchemyJobStore` pointed at the existing Postgres DB. This survives restarts and tracks missed fires durably. This is a Phase 3 decision — start with memory, upgrade if missed fires become a real problem.

**Warning signs:**
- Managers do not receive the 12:00 or 17:00 prompts after a server restart.
- APScheduler logs show `misfire` events.
- Logs show the scheduler starting but no job execution logs at the expected fire times.

**Phase to address:** Phase 3 (scheduler implementation). Set `misfire_grace_time=600` and `coalesce=True` from the start.

---

### Pitfall 24: Double Fires When Running Multiple Workers — APScheduler Runs In Every Worker

**What goes wrong:**
If Uvicorn is run under Gunicorn with `--workers 2` (or more), each worker process starts its own `AsyncIOScheduler` instance. Both schedulers fire the 12:00 job simultaneously. Both iterate through the manager allowlist. Both send the WhatsApp prompt to each manager. Each manager receives 2 prompts. At best this is confusing; at worst, if the conversation flow also runs simultaneously, two conversation rows are created for the same sender.

**Why it happens:**
APScheduler's in-process scheduler is per-process. There is no cross-process coordination with `MemoryJobStore`. This is a documented limitation in the APScheduler GitHub discussions (#1088).

**How to avoid:**
1. For v2.0 at low volume (2–3 managers, 2 fires/day): run Uvicorn as a single worker (`--workers 1`). The throughput for this use case is well within a single async worker's capacity.
2. If multi-worker is required later: use `SQLAlchemyJobStore` with Postgres as the backing store — APScheduler's data store architecture ensures only one worker executes each job. This requires APScheduler 4.x.
3. Alternative: use an external cron job (Docker cron, system cron) that calls a protected internal endpoint `POST /internal/scheduler/fire-prompt`. Only one cron fires; the endpoint runs the job. This is the most operationally robust approach and eliminates all in-process scheduler risks.

**Warning signs:**
- Managers receive duplicate prompts.
- Logs show the same job execution log line appearing twice within milliseconds from different process IDs.

**Phase to address:** Phase 3. Document the single-worker constraint in the scheduler implementation. Add a health-check log at startup that logs worker count.

---

### Pitfall 25: LLM Mis-Extracts Monto — Amount Is Recorded Without Deterministic Validation

**What goes wrong:**
The slot extraction step (`slot_extraction.py`) uses GPT to parse a free-form Spanish message into `{concepto, lugar, monto}`. For a message like "pagué como mil quinientos pesos en el chino de la esquina," the model should return `monto: 1500`. But under prompt ambiguity or with non-standard phrasing, it may return `monto: "mil quinientos"` (a string), `monto: null` (unparsed), `monto: 1500.00` (fine), or — the dangerous case — `monto: 150000` (misplaced decimal). Money amounts are the most critical field in the gasto record. A wrong amount corrupts the cash reconciliation.

**Why it happens:**
LLMs are probabilistic. Even GPT-4o makes numeric extraction errors on informal Spanish phrases with spelled-out numbers, shorthand (k for mil, pesos vs. AR$), or ambiguous phrasing. The model may also hallucinate a plausible amount when none is stated.

**How to avoid:**
1. The Pydantic schema for slot extraction must type `monto` as `Optional[Decimal]` (or `Optional[float]`), not `Optional[str]`. With Structured Outputs, the model is constrained to produce a number or null — string values are rejected by the schema.
2. After extraction, apply deterministic guards before accepting the monto:
   - `monto > 0` (no negative amounts, no zero)
   - `monto < 500_000` (hard upper limit — an expense above $500,000 ARS for a single cash purchase at a restaurant is implausible; flag for confirmation)
   - Round to 2 decimal places using `Decimal` arithmetic (not float)
3. **Always show the extracted monto to the manager in the confirmation step** before writing to the DB. The confirmation message must include: "Registro: [concepto] · [lugar] · $[monto formateado]. ¿Confirmás?" The manager's explicit "sí" is the final guard. Code owns the write; LLM output is always provisional.
4. If `monto` is null after extraction, the orchestrator stays in `awaiting_monto` and re-prompts: "No entendí el monto. ¿Cuánto pagaste? (Ej: 1500)" — deterministic re-ask, no LLM involvement in the retry path.
5. The confirmation step is non-optional and cannot be skipped by the engine even if all slots are filled. This is the primary defense for money recording correctness.

**Warning signs:**
- Gastos records with `salida` of 0, negative, or implausibly large values.
- Manager complains "el bot registró mal el monto."
- Structured Output parse errors on the `monto` field (model returned a string despite schema).

**Phase to address:** Phase 1 (slot extraction Pydantic schema — `Optional[Decimal]` for monto) and Phase 2 (orchestrator — confirmation step non-skippable, deterministic bounds validation).

---

### Pitfall 26: Argentine Number Format Parsing — "1.234,56" Misread as 1.234 or Parse Error

**What goes wrong:**
In Argentina, the decimal separator is a comma (`,`) and the thousands separator is a dot (`.`). A manager types "1.500" meaning one thousand five hundred pesos. Python's `float("1.500")` correctly parses to 1.5 — catastrophically wrong. `Decimal("1.500")` also gives `Decimal('1.500')` = 1.5. The amount recorded is $1.50 instead of $1,500.

Similarly, "1.234,56" cannot be parsed at all by `float()` or `Decimal()` without preprocessing. The bot would either crash (unhandled parse error) or record `null` monto and re-ask.

**Why it happens:**
Python's standard library numeric parsers are locale-unaware and default to US formatting (dot = decimal, comma = thousands). Argentine users naturally type numbers in their locale format. GPT-4o with Structured Outputs will produce the number as a JSON number (no locale ambiguity), but if the monto comes from free-form text and is passed through as a string, the parsing step must handle Argentine format.

**How to avoid:**
1. The primary defense is using GPT Structured Outputs with `monto` typed as `Optional[float]` in the JSON schema — GPT will normalize locale-specific number text into a standard JSON number (e.g., "mil quinientos" → 1500, "1.500" in Argentine context → 1500). JSON numbers are always dot-decimal, so `Decimal(str(json_number))` is safe.
2. If any code path accepts monto as raw user text (e.g., a fallback parser or a direct text parse without LLM), implement Argentine format normalization:
   ```python
   def parse_ars_amount(text: str) -> Decimal:
       # Remove thousands separator (dot), replace decimal separator (comma) with dot
       cleaned = text.strip().replace('.', '').replace(',', '.')
       return Decimal(cleaned)
   ```
   This handles: "1.500" → "1500" → Decimal(1500), "1.234,56" → "1234.56" → Decimal(1234.56).
3. Apply the sanity bounds check from Pitfall 25 after parsing.
4. **Never use Python's `locale` module** for this — `locale.setlocale()` is a global mutable operation that affects all threads and can cause non-deterministic behavior in an async server.

**Warning signs:**
- Gastos with monto values that are exactly 1000× smaller than reported by the manager (1.500 parsed as 1.5).
- Parse exceptions in the slot extraction layer when manager uses comma-decimal format.

**Phase to address:** Phase 1 (slot extraction service — implement `parse_ars_amount` utility) and Phase 2 (test with Argentine-formatted inputs).

---

### Pitfall 27: Timezone / DST Misconfiguration — 12:00 Prompt Fires at Wrong Time

**What goes wrong:**
The scheduler is configured to fire at 12:00 and 17:00 Buenos Aires time. If the timezone is set to UTC (the server default) or if the wrong timezone identifier is used, the prompts fire at 15:00 and 20:00 local time (UTC-3 offset), or at a fluctuating time if a DST-observing timezone is accidentally used.

**Why it happens:**
`America/Argentina/Buenos_Aires` does **not** observe Daylight Saving Time — Argentina stopped DST in 2008 and is fixed at UTC-3 year-round. This is the correct timezone identifier. However, if a developer uses `America/Buenos_Aires` (an alias that exists in some tz databases but is less reliable across libraries), or inadvertently uses a European or US timezone, the offset is wrong. APScheduler's cron trigger also has documented DST bugs for certain timezone/time combinations when the timezone observes DST transitions (GitHub issues #370, #115) — this is not a risk for Argentina, but confirms that timezone selection is critical.

**How to avoid:**
1. Always use the full IANA identifier: `America/Argentina/Buenos_Aires`. This is fixed UTC-3, no DST.
2. Set it in `app/config.py` as a typed constant: `SCHEDULER_TIMEZONE: str = "America/Argentina/Buenos_Aires"`.
3. Pass it to APScheduler's `AsyncIOScheduler(timezone=...)` constructor, not as a string to the cron trigger — the scheduler-level timezone setting is authoritative.
4. After deploying, verify by logging the first scheduled fire time: `next_run_time = scheduler.get_jobs()[0].next_run_time`. Convert to Buenos Aires local time and verify it shows 12:00 or 17:00.
5. The Docker container's system timezone does not affect APScheduler when the timezone is passed programmatically — but set the container `TZ=America/Argentina/Buenos_Aires` anyway for consistency in log timestamps.

**Warning signs:**
- Managers receive prompts at unexpected times (e.g., 9:00 AM or 3:00 PM instead of noon).
- `scheduler.get_jobs()[0].next_run_time` shows a UTC time that does not correspond to 12:00 Buenos Aires.

**Phase to address:** Phase 3 (scheduler implementation). Add a startup log line that prints the next scheduled fire time in Buenos Aires local time.

---

### Pitfall 28: In-Process Scheduler Dying Silently With the Worker — No Alerting

**What goes wrong:**
APScheduler's `AsyncIOScheduler` runs inside the Uvicorn event loop. If the scheduler's background thread (or async task) raises an unhandled exception during a job execution (e.g., the WhatsApp provider call raises `ConnectionError`), APScheduler catches the exception internally and logs it — but the job is marked as failed and **not automatically retried**. The scheduler continues running but the 12:00 prompt is lost. There is no alerting unless the logs are actively monitored.

Similarly, if the FastAPI lifespan `shutdown` hook is not properly awaited (e.g., due to a `SIGKILL`), the scheduler is not gracefully shut down, and in-flight job tasks may be abandoned.

**How to avoid:**
1. Wrap the job function body in `try/except` and log failures with structlog at `error` level with a structured `event="scheduler.job_failed"` key that can be alerted on.
2. Add a job event listener to the scheduler:
   ```python
   from apscheduler.events import EVENT_JOB_ERROR
   scheduler.add_listener(on_job_error, EVENT_JOB_ERROR)
   ```
   The `on_job_error` callback logs the exception with full context (job_id, scheduled_run_time, sender count).
3. Send the WhatsApp replies outside the scheduler job's database transaction — network failures should not roll back DB state.
4. Add a liveness check: a `GET /health` endpoint that includes `scheduler_running: scheduler.running` in the response. Include this in Docker's `HEALTHCHECK`. If the scheduler is not running, the health check fails and Docker restarts the container.

**Warning signs:**
- 12:00 or 17:00 prompts stop arriving without any obvious server downtime.
- APScheduler logs show `Job execution missed` or `Error in job` without downstream alerting.

**Phase to address:** Phase 3 (scheduler implementation). Health check extension can be Phase 3 exit criterion.

---

### Pitfall 29: Image-vs-Text Branching Mistakes in the Gastos Webhook Handler

**What goes wrong:**
The gastos flow has two fundamentally different message types: text (for all conversational turns) and media (for the ticket photo in `awaiting_ticket` state). The webhook handler must branch correctly. Failure modes:

- **Text message arrives in `awaiting_ticket` state**: Bot must accept it as either a skip signal ("sin ticket") or an error if it's not the expected text. If the handler routes all text messages to the slot extractor without state awareness, it will try to extract slots from "sin ticket" and fail.
- **Image arrives in `idle` state**: This is a v1.0 invoice (handled by the existing webhook). If both webhook handlers (`whatsapp.py` and `gastos_whatsapp.py`) are mounted, an image might be processed by both, causing duplicate processing.
- **Image arrives in `awaiting_monto` state**: Manager sent a photo when the bot expected a text amount. The orchestrator must reject it gracefully ("Por favor respondé con el monto en texto, no con una foto").

**Why it happens:**
The design correctly separates the two webhook paths (separate router for gastos), but the internal orchestrator must be state-aware about media vs. text acceptance at each step. Simple "if NumMedia > 0: handle as image; else: handle as text" branching is not sufficient — the state must gate what is accepted.

**How to avoid:**
1. The orchestrator's `process_message(state, message_type, content)` must validate `message_type` against what the current state expects. Each state declares its expected input type(s):
   - `idle` → text (intent)
   - `awaiting_monto` → text (amount)
   - `awaiting_ticket` → text ("sin ticket") OR media (photo)
   - `confirm` → text ("sí", "no", correction)
2. Any unexpected type for the current state gets a deterministic re-prompt: "Necesito una [respuesta de texto / foto del ticket]."
3. Route separation: use the existing `whatsapp.py` for v1.0 invoice photos (media, no conversation state). Use `gastos_whatsapp.py` for all gastos-related messages. Do not mount both on the same path — use distinct webhook URLs or route by presence of conversation state.
4. If no active conversation row exists for a sender AND the message is an image (not text): route to the invoice pipeline (v1.0 behavior). If conversation exists and state is `awaiting_ticket`: route to the ticket handler.

**Warning signs:**
- "sin ticket" causes a slot extraction error.
- Ticket photos are processed by the invoice pipeline when the manager is in a gastos flow.
- Bot responds "Necesito el monto" when the manager sent an image (type mismatch not handled gracefully).

**Phase to address:** Phase 2 (webhook routing and orchestrator). This is a core design decision that must be settled in Phase 1's architecture.

---

### Pitfall 30: Cost and Manager Experience — Proactive Nudges Becoming Spam

**What goes wrong:**
The scheduler sends prompts at 12:00 and 17:00 every day, including weekends and holidays. For a restaurant that closes on Sundays or during Argentine holidays (there are approximately 19 national holidays per year), the manager receives a prompt for a shift that does not exist. They ignore it, and the conversation row is left in `awaiting_caja_count` state, which then needs the session timeout (Pitfall 22) to clean it up. Additionally, if the manager does not respond to the 17:00 prompt, the next morning's session opens in a stale state.

Additionally, Meta's Utility template messages are not free — each proactive message that opens a new conversation session is billed at the Utility conversation rate for Argentina. With 2 managers × 2 fires/day = 4 messages/day × ~$0.005 USD per utility conversation = ~$0.60/month. This is negligible, but the cost scales with manager count.

**How to avoid:**
1. Add a `scheduler_days` config field (default: Monday–Sunday) and `scheduler_enabled` flag per sender or globally. Allow suppression for weekends or specific dates via config without code changes.
2. The session timeout (Pitfall 22) must handle the case where a scheduler-initiated conversation is abandoned — this is expected on holidays, not a bug.
3. Log each outbound prompt with its API call cost response metadata (Twilio provides message price in the API response) for cost tracking.
4. For v2.0 with 2–3 managers: the cost is immaterial. Document the scaling formula for when the team grows.

**Warning signs:**
- Managers complain about receiving prompts on days the restaurant is closed.
- High number of abandoned `awaiting_caja_count` sessions on weekends.

**Phase to address:** Phase 3 (scheduler). Add day-of-week filter from the start. Weekend suppression is a one-line APScheduler cron config (`day_of_week='mon-fri'` if applicable).

---

### Pitfall 31: Confirmation Step Bypassed — "Sí" Ambiguity in Free-Form Text

**What goes wrong:**
The confirmation step sends "¿Confirmás?" and waits for the manager's response. The orchestrator must parse the confirmation response as affirmative ("sí", "si", "dale", "ok", "confirmo", "yes") or negative ("no", "no está bien", "cambiar"). If the LLM is used to parse the confirmation response (to handle informal affirmations), it may misclassify "no sé" ("I don't know") as affirmative (because it starts with "sí" phonetically) or classify "si, pero el monto es 1500" as a correction rather than confirmation.

More critically: if the confirmation parser is permissive and accepts any message that is not an explicit "no" as affirmative, a manager who replies "Hola" by mistake after the confirmation prompt will trigger a gasto write.

**Why it happens:**
Natural language confirmation is inherently ambiguous. LLMs are not reliable for binary yes/no classification on informal Argentine Spanish.

**How to avoid:**
1. Use a **deterministic string match** for confirmations, not LLM classification. The set of affirmative tokens is small and well-defined in Argentine Spanish: `{"sí", "si", "dale", "ok", "confirmo", "listo", "va", "yes", "bueno", "claro"}`. Any response not in this set is treated as a correction/denial.
2. If the response is not in the affirmative set and not clearly a denial, re-prompt with: "¿Confirmás el registro? Respondé 'sí' para guardar o 'no' para corregir."
3. Do not use LLM on the confirmation step at all. This is the one step where deterministic code is mandatory — money is written to the DB on a "sí".
4. Log all confirmation responses with the full manager text and the parsed result for audit review.

**Warning signs:**
- Gastos created with incorrect amounts or concepts that the manager did not intend to confirm.
- Manager complains "el bot guardó un gasto que no quise confirmar."

**Phase to address:** Phase 2 (orchestrator — confirmation state handler). Unit test with: "sí", "Si", "SI", "si dale", "no", "no está bien", "no sé", "Hola", "" (empty), "1500" (random number).

---

### Pitfall 32: Conversation State Row Schema Too Rigid — Draft Gasto JSON Breaks on Schema Evolution

**What goes wrong:**
The `conversations.draft_gasto` column stores the partial gasto being assembled as a JSON blob. If, after the system is in production, a new required slot is added to the gasto flow (e.g., adding a `categoria` field to categorize expenses), existing in-flight conversations have `draft_gasto` JSON without the `categoria` key. The orchestrator tries to load the JSON into the `DraftGasto` Pydantic model and raises a `ValidationError`. Every conversation that was in progress before the schema change is now stuck.

**Why it happens:**
Postgres JSON columns have no schema enforcement. The Pydantic model that reads the JSON is versioned in Python code, but the stored JSON is not. A code deploy that adds a required field to `DraftGasto` immediately breaks all existing rows.

**How to avoid:**
1. All fields in the `DraftGasto` schema must be `Optional` with defaults. Required fields are enforced by the orchestrator logic (re-prompting until filled), not by the Pydantic model's field requirement.
2. Use `model_validate(json_data, strict=False)` with a try/except. On `ValidationError`, reset the conversation to `idle` and log the corrupt draft for admin review. Losing an in-progress draft is far better than a stuck conversation.
3. Store a `draft_version` field alongside `draft_gasto` JSON. When loading, check the version — if it mismatches the current schema version, treat as corrupted and reset.
4. Add a DB migration when the draft schema changes that updates all `conversations` rows where state is not `idle`: set state to `idle` and clear `draft_gasto`.

**Warning signs:**
- Pydantic `ValidationError` exceptions in `conversation.py` on message processing after a deployment.
- Conversations stuck in non-idle states after code deploy.

**Phase to address:** Phase 1 (data model design — all `DraftGasto` fields Optional) and addressed proactively in any future schema-changing migration.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| `MemoryJobStore` for APScheduler | Zero setup | Missed fires on restart; jobs lost on crash | Acceptable for v2.0 at 2 managers, must document and monitor |
| In-memory `_processed_message_sids` for idempotency | Zero setup | Lost on restart; not shared across workers | Never acceptable for gastos flow — DB idempotency required |
| Deterministic string match for all LLM output | Simple code | Brittle on varied phrasing | Acceptable only for the confirmation step; slot extraction needs LLM |
| Single Uvicorn worker to avoid double-scheduler fires | No concurrency bugs | Throughput ceiling | Acceptable for v2.0 low volume; must document |
| Free-form message as proactive prompt (no template) | No Meta approval delay | API rejection (`131026`); manager receives nothing | Never — always use pre-approved template for proactive outbound |
| `draft_gasto` with required fields in Pydantic | Catches incomplete drafts early | Breaks on schema evolution | Never — all draft fields must be Optional |

---

## Integration Gotchas

Common mistakes when connecting to external services.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Meta WhatsApp Cloud API (proactive) | Send free-form `body` text to manager who hasn't messaged in > 24h | Use approved Utility template with `template` object in API payload |
| Twilio WhatsApp (proactive) | Send `body` parameter outside session | Use `content_sid` (approved template Content SID) and `content_variables` |
| APScheduler + FastAPI lifespan | Call `scheduler.start()` outside lifespan context | Start in `@asynccontextmanager` lifespan, `scheduler.shutdown()` in finally block |
| APScheduler + multiple workers | Default in-process scheduler | Single worker, or APScheduler 4.x with shared Postgres data store |
| Meta Cloud API error codes | Ignore API response body on success-adjacent errors | Log full response body; `131026` and `63016` are silent user-facing failures |
| Argentine number parsing | `float("1.500")` or `Decimal("1.500")` for Argentine thousands | Strip dots, replace comma with dot before parsing; rely on GPT JSON number output |

---

## Performance Traps

Patterns that work at small scale but fail as usage grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| `SELECT * FROM conversations WHERE sender_phone = $1` without index | Slow conversation load as table grows | Index on `sender_phone` (likely already unique, so auto-indexed) | > 10k rows (not a real concern at this scale) |
| Sending WhatsApp replies inside the DB transaction | Lock held during network round-trip | Commit DB transaction, then send reply | Any network latency > 50ms causes lock contention |
| GPT-4o call inside webhook request cycle | > 5s response, Twilio retries | Ticket photo extraction must be async background task | Every single GPT call |
| APScheduler cron job iterating all managers synchronously | 12:00 prompt blocks if first manager's WhatsApp call hangs | `asyncio.gather()` for concurrent sends with timeout | > 5 managers |

---

## Security Mistakes

Domain-specific security issues beyond general web security.

| Mistake | Risk | Prevention |
|---------|------|------------|
| Storing WhatsApp template message content in code with variable values hardcoded | Template variable mismatch causes API rejection | Template variables come from config/DB; content reviewed before submission to Meta |
| Allowlist bypass via phone number format variations | Unauthorized sender records gastos | Normalize phone number (strip `whatsapp:` prefix, normalize to E.164) before allowlist check — already done in v1.0, must be applied to gastos handler too |
| `draft_gasto` JSON accessible via admin UI before confirmation | Premature exposure of unconfirmed financial data | Admin UI only shows committed `gastos` rows, not conversation state |
| Scheduler endpoint (`/internal/scheduler/fire-prompt`) without auth | External actor triggers prompt flood | If implementing the external-cron pattern, protect with shared secret or network-level restriction |

---

## UX Pitfalls

Common user experience mistakes in this domain.

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Bot re-asks for monto with no explanation when parse fails | Manager confused: "I already told it" | Re-ask with example: "No entendí el monto. ¿Cuánto pagaste? (Ej: 1500 o 1.500,00)" |
| Confirmation message too long to read on mobile | Manager taps "sí" without reading | Keep confirmation to 2 lines: "Registro: [concepto] · [lugar] · $[monto]. ¿Confirmás?" |
| Bot continues in Spanish when manager sends English or writes informally | Confusion | Prompts are always in Spanish; LLM slot extraction handles informal input |
| Proactive prompt arrives while manager is in a conversation flow | State conflict: 17:00 prompt arrives while manager is in awaiting_ticket | If sender already has active non-idle conversation when scheduler fires, skip the proactive prompt for that sender |

---

## "Looks Done But Isn't" Checklist

- [ ] **WhatsApp template:** Template submitted to Meta AND approved — not just created. Check approval status before Phase 3 demo.
- [ ] **Proactive prompts:** Tested at actual 12:00 and 17:00 Buenos Aires times, not just manually triggered. Verify timezone by inspecting `next_run_time`.
- [ ] **Idempotency:** Webhook retry simulation tested — send same `message_id` twice and verify only one state transition occurs.
- [ ] **Concurrent messages:** Test by firing two simultaneous HTTP requests with the same sender phone to the webhook. Verify conversation state is consistent after both complete.
- [ ] **Session timeout:** Manually set `updated_at` to 5 hours ago in a non-idle conversation row and verify the next message resets to idle.
- [ ] **Confirmation gate:** Verify that "no sé", "Hola", and empty string do not trigger a gasto write in the `confirm` state.
- [ ] **Argentine number parsing:** Test slot extraction with "1.500", "1.234,56", "mil quinientos", "$1500", "1500 pesos".
- [ ] **Scheduler failure alerting:** Kill the scheduler job's WhatsApp send and verify the error appears in logs with `event="scheduler.job_failed"`.

---

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Template not approved, Phase 3 blocked | MEDIUM | Submit template immediately; use manual WhatsApp message to managers during approval wait; template approval takes up to 24h |
| Double-recorded gastos from webhook retry | MEDIUM | Admin UI soft-delete of duplicate; add message_id idempotency to prevent recurrence; audit `gastos` table for `created_at` clustering |
| Conversation stuck in non-idle state after crash | LOW | `UPDATE conversations SET state='idle', draft_gasto=NULL WHERE state != 'idle' AND updated_at < NOW() - INTERVAL '1 hour'` |
| Wrong monto recorded (manager confirmed bad amount) | LOW | Admin UI edit on `gastos` row; log correction for audit trail |
| Scheduler double-fires from multi-worker deploy | MEDIUM | Set `--workers 1`; delete duplicate gastos/cierres created in the double-fire window; add startup log of worker count |
| Draft schema breaks on code deploy | MEDIUM | Run migration: `UPDATE conversations SET state='idle', draft_gasto=NULL WHERE state != 'idle'`; redeploy |

---

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| WhatsApp 24h window / template required for proactive (P19) | Phase 2 exit criterion (template approved) + Phase 3 implementation | Template status confirmed in Meta Business Manager before Phase 3 begins |
| Webhook duplicate delivery / double gastos (P20) | Phase 1 (message_id column) + Phase 2 (idempotency check) | Replay same message_id twice; verify single state transition |
| Concurrent message race on conversation row (P21) | Phase 1 (data model) + Phase 2 (SELECT FOR UPDATE in orchestrator) | Concurrent HTTP test with same sender |
| Stuck/abandoned conversations (P22) | Phase 1 (timeout_at column) + Phase 2 (timeout check in orchestrator) | Manually age a conversation row; verify reset on next message |
| Scheduler missed fires on restart (P23) | Phase 3 (misfire_grace_time=600, coalesce=True) | Restart process at scheduled time; verify prompt still fires |
| Double fires from multiple workers (P24) | Phase 3 (single-worker constraint documented) | Deploy with 2 workers; verify only one set of prompts sent |
| LLM monto mis-extraction (P25) | Phase 1 (Pydantic schema) + Phase 2 (bounds validation + non-skippable confirmation) | Unit tests with edge case amounts; integration test: confirm wrong amount |
| Argentine number format parsing (P26) | Phase 1 (parse_ars_amount utility) + Phase 2 (integration tests) | Test with "1.500", "1.234,56", "mil quinientos" |
| Timezone misconfiguration (P27) | Phase 3 (SCHEDULER_TIMEZONE constant, startup log) | Verify next_run_time in Buenos Aires local time at startup |
| Scheduler dying silently (P28) | Phase 3 (job error listener, health check) | Kill WhatsApp send in job; verify error log and health check failure |
| Image-vs-text branching mistakes (P29) | Phase 2 (orchestrator state-aware routing) | Integration test: send image in awaiting_monto state; send text in awaiting_ticket |
| Proactive nudge on closed days (P30) | Phase 3 (day_of_week config) | Configure weekend suppression from day one |
| Confirmation ambiguity / bypass (P31) | Phase 2 (deterministic string match) | Unit test confirmation parser with edge cases |
| Draft gasto schema evolution (P32) | Phase 1 (all DraftGasto fields Optional) | Deploy with new optional field; verify existing in-progress conversations survive |

---

## Sources

**WhatsApp Platform Constraints:**
- [Twilio Error 63016 — Outside Messaging Window](https://www.twilio.com/docs/api/errors/63016) — confirmed: free-form messages blocked outside 24h window; template + ContentSid required
- [Meta WhatsApp Pricing — template conversation billing](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing) — Utility category costs less than Marketing
- [WhatsApp Business Platform 24-Hour Rule — Enchant](https://www.enchant.com/whatsapp-business-platform-24-hour-rule) — window resets on user reply; template required for business-initiated
- [Twilio: Send WhatsApp Notification Messages with Templates](https://www.twilio.com/docs/whatsapp/tutorial/send-whatsapp-notification-messages-templates)
- [Rules and Best Practices for WhatsApp Messaging on Twilio](https://support.twilio.com/hc/en-us/articles/360017773294-Rules-and-Best-Practices-for-WhatsApp-Messaging-on-Twilio)
- [WhatsApp Business Messaging Policy](https://business.whatsapp.com/policy)

**Webhook Idempotency and Concurrency:**
- [At-Least-Once vs. Exactly-Once Webhook Delivery Guarantees — Hookdeck](https://hookdeck.com/webhooks/guides/webhook-delivery-guarantees)
- [Guide to WhatsApp Webhooks — Hookdeck](https://hookdeck.com/webhooks/platforms/guide-to-whatsapp-webhooks-features-and-best-practices)
- [WhatsApp race condition on concurrent image messages — Chatwoot Issue #14058](https://github.com/chatwoot/chatwoot/issues/14058)
- [Handling Concurrency with Row Level Locking in PostgreSQL — DEV](https://dev.to/nickcosmo/handling-concurrency-with-row-level-locking-in-postgresql-1p3)
- [SELECT FOR UPDATE in PostgreSQL — CYBERTEC](https://www.cybertec-postgresql.com/en/select-for-update-considered-harmful-postgresql/)

**APScheduler:**
- [APScheduler 3.x User Guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html) — misfire_grace_time, coalesce, replace_existing
- [APScheduler DST bug — GitHub Issue #370](https://github.com/agronholm/apscheduler/issues/370)
- [APScheduler + Gunicorn multi-worker — GitHub Discussion #1088](https://github.com/agronholm/apscheduler/discussions/1088)

**Argentine Number Format:**
- [How to deal with international data formats in Python — herrmann.tech](https://herrmann.tech/en/blog/2021/02/05/how-to-deal-with-international-data-formats-in-python.html)
- [Convert String with Dot or Comma to Float — javathinking.com](https://www.javathinking.com/blog/convert-string-with-dot-or-comma-to-float-number/)

**Timezone:**
- [America/Argentina/Buenos_Aires — fixed UTC-3, no DST](https://github.com/stub42/pytz/blob/master/tz/southamerica) — Argentina discontinued DST in 2008

**v1.0 pitfalls (baseline):**
- [Guide to WhatsApp Webhooks: Features and Best Practices — Hookdeck](https://hookdeck.com/webhooks/platforms/guide-to-whatsapp-webhooks-features-and-best-practices)
- [FastAPI BackgroundTasks silent failure — Issue #2604](https://github.com/fastapi/fastapi/issues/2604)
- [OpenAI Structured Outputs hallucination risk](https://community.openai.com/t/structured-outputs-not-reliable-with-gpt-4o-mini-and-gpt-4o/918735)

---
*Pitfalls research for: Compras Agent v2.0 Gastos Bot — conversational WhatsApp expense recording*
*Researched: 2026-05-27*
