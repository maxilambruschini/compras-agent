<!-- GSD:project-start source:PROJECT.md -->
## Project

**Compras Agent**

A WhatsApp-to-database invoice capture system for Argentine companies. Purchasing employees photograph invoices and send them via WhatsApp; an AI agent extracts structured data from the image and stores it in a database. Managers and accountants access a React web UI to review, edit, query, and manage all captured invoices.

**Core Value:** An employee sends a photo of an invoice over WhatsApp and the data lands correctly in the database — no manual entry, no lost receipts.

### Constraints

- **Tech Stack**: Python + FastAPI (backend), React + Vite (frontend), Postgres in Docker, local filesystem storage via FastAPI (`StorageBackend` abstraction), OpenAI GPT-4o vision
- **WhatsApp**: Must use official Meta Cloud API or an official BSP (Twilio, 360dialog) — no unofficial scraping libraries
- **Security**: Secrets in environment variables. Webhook signatures validated. Original files retained for audit.
- **Argentine compliance**: Invoice fields follow AFIP schema conventions. No tax advice generated — extraction only.
- **Scope**: Single-company deployment for v1. No multi-tenancy.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Recommended Stack
### Backend Core
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Python | 3.12 | Runtime | Stable, full typing, compatible with all libs below. 3.13 is out but ecosystem support for 3.12 is wider in mid-2026. |
| FastAPI | 0.136.1 | HTTP framework + webhook host | Native async, Pydantic v2 integration built-in, best Python ergonomics for webhook endpoints. |
| Uvicorn | latest (^0.34) | ASGI server | Standard production server for FastAPI; use `uvicorn.workers.UvicornWorker` under Gunicorn for multi-core. |
| Pydantic | 2.13.4 | Data validation + structured output schemas | v2 is required by FastAPI 0.13x; Rust-based, 5-50x faster than v1. Mandatory for OpenAI `.parse()` pattern. |
### AI / Extraction
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| openai (Python) | 2.36.0 | GPT-4o vision + Structured Outputs | Official client; v2 ships the `responses` API and the stable `.parse()` method for Pydantic-typed extraction. |
| Model | `gpt-4o` (latest) | Invoice image extraction | Best vision-to-text for varied printed layouts; Argentine invoices mix fonts, stamps, handwriting margins. |
### WhatsApp Integration
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| pywa | 3.9.0 | WhatsApp Cloud API wrapper | Best Python library for Meta Cloud API in 2026. Native FastAPI integration via `WhatsApp(server=fastapi_app, ...)`. Handles webhook verification, HMAC signature, GET challenge, media download. Async-first. |
| Meta WhatsApp Cloud API | v22+ | Messaging channel | Official Meta API (free tier, pay-per-conversation). Avoid Twilio for greenfield — Meta Cloud API is cheaper and has no intermediary. |
### Data Layer
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| supabase (Python) | 2.30.0 | Postgres client + Auth + Storage | Single SDK covers all three. Works synchronously or async (use `AsyncClient` in FastAPI routes). |
| Supabase Postgres | managed | Invoice records, line items, allowlist, audit trail | Full Postgres — JSON columns, CTEs, window functions for dedup queries. RLS enforces row-level security from day one. |
| Supabase Storage | managed | Raw invoice image files | Tightly integrated with Postgres RLS. No second service to manage. Generates signed URLs for frontend display. S3-compatible if ever migrated. |
| Supabase Auth | managed | Admin email/password login | Built into Supabase; JWT tokens accepted by both the Python client (`set_session`) and the JS client. No separate auth service. |
### Frontend
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| React | 19 | UI component tree | Stable, large ecosystem, team familiarity assumed from PROJECT.md choice. |
| Vite | 8.x | Build tool + dev server | Current major (v8 released 2026). Fastest HMR for React; native TS support; VITE_ env prefix for secrets. |
| TypeScript | 5.x | Type safety | Non-negotiable for maintainable Supabase query code; catches schema drift at compile time. |
| @supabase/supabase-js | 2.105.4 | DB + Auth + Storage from browser | Official JS client v2. Use `VITE_SUPABASE_URL` + new publishable key (`sb_publishable_xxx`) — old anon key works but Meta is phasing it out by end of 2026. |
| @tanstack/react-query | 5.90.x | Server state + async data fetching | Standard pattern for invoice list/edit/filter: `useQuery` for reads, `useMutation` for writes, automatic stale invalidation. Avoids hand-rolled `useEffect` chains. |
| React Router | 7.x | Client-side routing | Invoice list ↔ detail ↔ edit views. |
### Supporting Libraries (Backend)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-dotenv | ^1.0 | Load `.env` in dev | Dev only; production secrets via Supabase Vault or environment injection. |
| httpx | ^0.28 | Async HTTP client | Use for any outbound calls not covered by pywa/openai SDK (e.g., AFIP lookup if added later). |
| structlog | ^25.x | Structured JSON logging | Use from Phase 1; makes log querying trivial in production. Better than stdlib `logging` for JSON output. |
| pytest + pytest-asyncio | latest | Test suite | Async endpoint testing without friction. |
## Key Architectural Decisions and Rationale
### WhatsApp Channel: Meta Cloud API via pywa, not Twilio
- Twilio adds per-message cost overhead on top of Meta's conversation pricing — no value for a single-company deployment.
- pywa 3.9.0 abstracts the entire Meta webhook lifecycle: HMAC-SHA256 verification of `X-Hub-Signature-256`, GET token challenge, media URL download, reply sending.
- pywa's FastAPI integration registers its own routes automatically — you pass your `FastAPI()` app instance at client construction. No manual webhook router needed.
- pywa 4.0.0 Beta handles the upcoming BSUID migration; upgrade path exists.
### Structured Extraction: `client.chat.completions.parse()` not `response_format={"type": "json_object"}`
- `.parse()` (introduced in openai-python v1.40+, stable in v2.x) auto-converts the Pydantic model to JSON Schema, sends it as a Structured Output constraint, and deserializes the response directly into a typed Python object.
- `message.parsed` is `None` when the model refuses — easy to gate on `message.refusal` without extra parsing logic.
- Use `Optional[str]` fields with `default=None` for every extractable field. Never use `str` without `Optional` — a missing CUIT should be `None`, not hallucinated.
- Model lock: `gpt-4o-2024-08-06` or later is required for guaranteed Structured Output compliance. Avoid `gpt-4o-mini` for invoice extraction — accuracy on dense printed text is lower.
### Supabase Storage vs Google Cloud Storage
- GCS requires a separate GCP project, service account key, separate SDK (`google-cloud-storage`), and separate access control logic.
- Supabase Storage is S3-compatible object storage backed by the same Postgres RLS policies as the database. An invoice image's access is controlled by the same policy that controls invoice row access — zero drift.
- The Python client (`supabase.storage.from_("invoices").upload(...)`) returns a path; the file path is stored in the `invoices` table; signed URLs are generated on demand.
- At under 20 invoices/day, Supabase Storage free tier covers the project indefinitely.
- Migration path exists: Supabase Storage is S3-compatible, so switching to S3/GCS later requires only a storage backend swap, not a code rewrite.
### FastAPI + Supabase Python Client: Sync vs Async
- FastAPI's `BackgroundTasks` (used for invoice processing after returning 200 to WhatsApp) runs in a thread pool by default, so the sync Supabase client is safe there.
- Direct route handlers (admin API) should use the async client to avoid blocking the event loop.
- pywa's FastAPI integration is async-native — all message handlers are `async def`.
# pywa handler
### Frontend: @supabase/supabase-js direct vs REST API calls
- Frontend client uses the publishable/anon key + JWT from Supabase Auth. RLS policies ensure users can only read their own data.
- Writes go through FastAPI to keep business logic (dedup check, confidence re-evaluation) server-side and auditable.
- This is the standard Supabase + React pattern as of 2026.
## Versions Summary (Pin These)
# Backend — requirements.txt
# Frontend — package.json
## Alternatives Considered
| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| WhatsApp wrapper | pywa 3.9 | Raw Meta API + manual webhook | Manual HMAC verification, media download, reply logic — 200+ lines pywa handles for free |
| WhatsApp wrapper | pywa 3.9 | Twilio WhatsApp | Extra cost layer, no added value for single-company deployment |
| Extraction method | `client.chat.completions.parse()` | Function calling + manual JSON parse | `.parse()` is the current idiomatic approach; same Structured Outputs guarantees, less code |
| AI model | `gpt-4o` | `gpt-4o-mini` | mini accuracy on dense Argentine invoice layouts is materially worse |
| Storage | Supabase Storage | Google Cloud Storage | Separate SDK, separate IAM, no native RLS integration; overkill |
| Storage | Supabase Storage | Cloudinary | Media transformation not needed for invoices; adds cost |
| DB client | supabase-py 2.30 | psycopg2 / SQLAlchemy direct | Supabase client bundles Auth + Storage + RLS JWT propagation; using SQLAlchemy directly breaks RLS session context |
| Frontend state | TanStack Query v5 | SWR | TanStack Query has better mutation/invalidation ergonomics for the invoice edit workflow |
| Server | Uvicorn + Gunicorn | Uvicorn standalone | At <20 invoices/day, standalone Uvicorn is fine; Gunicorn adds resilience for production |
## Installation
# Backend
# Frontend
## Sources
- FastAPI PyPI: https://pypi.org/project/fastapi/ (verified 2026-05-12, latest 0.136.1)
- OpenAI Python PyPI: https://pypi.org/project/openai/ (verified 2026-05-12, latest 2.36.0)
- Pydantic PyPI: https://pypi.org/project/pydantic/ (verified 2026-05-12, latest 2.13.4)
- supabase-py PyPI: https://pypi.org/project/supabase/ / GitHub releases (verified 2026-05-12, latest 2.30.0)
- pywa PyPI: https://pypi.org/project/pywa/ + https://pywa.readthedocs.io/en/latest/ (verified 2026-05-12, latest 3.9.0)
- @supabase/supabase-js npm: https://www.npmjs.com/package/@supabase/supabase-js (verified 2026-05-12, latest 2.105.4)
- OpenAI Structured Outputs: https://developers.openai.com/api/docs/guides/structured-outputs
- OpenAI Python `.parse()` pattern: Context7 /openai/openai-python + https://github.com/openai/openai-python/blob/main/helpers.md
- Supabase Python Storage: Context7 /supabase/supabase-py
- WhatsApp webhook signature: https://hookdeck.com/webhooks/guides/how-to-implement-sha256-webhook-signature-verification
- Supabase key migration (publishable keys): Supabase docs search result, 2026
- TanStack Query v5: Context7 /tanstack/query
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
