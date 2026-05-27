# Technology Stack

**Project:** Compras Agent — WhatsApp Invoice Capture System
**Researched:** 2026-05-12
**Confidence:** HIGH (all versions verified against PyPI / npm registries and official docs)

---

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

---

## Key Architectural Decisions and Rationale

### WhatsApp Channel: Meta Cloud API via pywa, not Twilio

**Decision:** Use Meta WhatsApp Cloud API directly with pywa.

**Rationale:**
- Twilio adds per-message cost overhead on top of Meta's conversation pricing — no value for a single-company deployment.
- pywa 3.9.0 abstracts the entire Meta webhook lifecycle: HMAC-SHA256 verification of `X-Hub-Signature-256`, GET token challenge, media URL download, reply sending.
- pywa's FastAPI integration registers its own routes automatically — you pass your `FastAPI()` app instance at client construction. No manual webhook router needed.
- pywa 4.0.0 Beta handles the upcoming BSUID migration; upgrade path exists.

**What NOT to use:** `requests` + manual webhook router. Too much boilerplate and security surface. pywa handles timing-safe HMAC comparison.

### Structured Extraction: `client.chat.completions.parse()` not `response_format={"type": "json_object"}`

**Decision:** Use `openai.chat.completions.parse(response_format=InvoiceExtraction)` where `InvoiceExtraction` is a Pydantic v2 `BaseModel`.

**Rationale:**
- `.parse()` (introduced in openai-python v1.40+, stable in v2.x) auto-converts the Pydantic model to JSON Schema, sends it as a Structured Output constraint, and deserializes the response directly into a typed Python object.
- `message.parsed` is `None` when the model refuses — easy to gate on `message.refusal` without extra parsing logic.
- Use `Optional[str]` fields with `default=None` for every extractable field. Never use `str` without `Optional` — a missing CUIT should be `None`, not hallucinated.
- Model lock: `gpt-4o-2024-08-06` or later is required for guaranteed Structured Output compliance. Avoid `gpt-4o-mini` for invoice extraction — accuracy on dense printed text is lower.

**Pattern:**
```python
from pydantic import BaseModel
from typing import Optional
from openai import OpenAI

client = OpenAI()

class InvoiceExtraction(BaseModel):
    cuit_proveedor: Optional[str] = None
    tipo_comprobante: Optional[str] = None
    punto_de_venta: Optional[str] = None
    numero_comprobante: Optional[str] = None
    cae: Optional[str] = None
    fecha_vencimiento_cae: Optional[str] = None
    fecha_emision: Optional[str] = None
    neto_gravado: Optional[float] = None
    iva: Optional[float] = None
    total: Optional[float] = None
    confidence: float  # 0.0–1.0, model self-reports

completion = client.chat.completions.parse(
    model="gpt-4o-2024-08-06",
    messages=[
        {"role": "system", "content": "Extract Argentine AFIP invoice fields. Return null for any field not clearly visible."},
        {"role": "user", "content": [
            {"type": "text", "text": "Extract all invoice fields from this image."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}}
        ]}
    ],
    response_format=InvoiceExtraction,
)
invoice = completion.choices[0].message.parsed
```

### Supabase Storage vs Google Cloud Storage

**Decision:** Supabase Storage.

**Rationale:**
- GCS requires a separate GCP project, service account key, separate SDK (`google-cloud-storage`), and separate access control logic.
- Supabase Storage is S3-compatible object storage backed by the same Postgres RLS policies as the database. An invoice image's access is controlled by the same policy that controls invoice row access — zero drift.
- The Python client (`supabase.storage.from_("invoices").upload(...)`) returns a path; the file path is stored in the `invoices` table; signed URLs are generated on demand.
- At under 20 invoices/day, Supabase Storage free tier covers the project indefinitely.
- Migration path exists: Supabase Storage is S3-compatible, so switching to S3/GCS later requires only a storage backend swap, not a code rewrite.

**What NOT to use:** Google Cloud Storage for this project size and stack. Over-engineered.

### FastAPI + Supabase Python Client: Sync vs Async

**Decision:** Use synchronous Supabase client (`create_client`) in background tasks; use async client (`acreate_client`) in async route handlers.

**Rationale:**
- FastAPI's `BackgroundTasks` (used for invoice processing after returning 200 to WhatsApp) runs in a thread pool by default, so the sync Supabase client is safe there.
- Direct route handlers (admin API) should use the async client to avoid blocking the event loop.
- pywa's FastAPI integration is async-native — all message handlers are `async def`.

**Pattern for webhook processing:**
```python
from fastapi import BackgroundTasks
from supabase import create_client

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# pywa handler
@wa.on_message(filters.image)
async def handle_invoice_image(client, message):
    # Download media URL (pywa handles token)
    media_url = await message.image.download(in_memory=True)
    # Kick off background processing — returns immediately to WhatsApp
    background_tasks.add_task(process_invoice, media_url, message.from_user.phone)
    await message.reply_text("Recibido, procesando tu factura...")
```

### Frontend: @supabase/supabase-js direct vs REST API calls

**Decision:** Use `@supabase/supabase-js` directly from the React frontend for reads (invoice list, single invoice, line items). Write operations (edit, delete) call the FastAPI backend, which uses the service-role key and enforces business logic.

**Rationale:**
- Frontend client uses the publishable/anon key + JWT from Supabase Auth. RLS policies ensure users can only read their own data.
- Writes go through FastAPI to keep business logic (dedup check, confidence re-evaluation) server-side and auditable.
- This is the standard Supabase + React pattern as of 2026.

**Environment setup:**
```
VITE_SUPABASE_URL=https://xxx.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_xxx
```

---

## Versions Summary (Pin These)

```
# Backend — requirements.txt
fastapi==0.136.1
uvicorn[standard]==0.34.*
pydantic==2.13.4
openai==2.36.0
pywa[fastapi]==3.9.0
supabase==2.30.0
python-dotenv==1.0.*
httpx==0.28.*
structlog==25.*

# Frontend — package.json
"react": "^19.0.0"
"react-dom": "^19.0.0"
"vite": "^8.0.0"
"typescript": "^5.0.0"
"@supabase/supabase-js": "^2.105.4"
"@tanstack/react-query": "^5.90.0"
"react-router-dom": "^7.0.0"
```

---

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

---

## Installation

```bash
# Backend
pip install "fastapi[standard]"==0.136.1 pydantic==2.13.4 openai==2.36.0 \
  "pywa[fastapi]"==3.9.0 supabase==2.30.0 python-dotenv uvicorn[standard] httpx structlog

# Frontend
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install @supabase/supabase-js @tanstack/react-query react-router-dom
```

---

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

---

## v2.0 Gastos Bot — Stack Additions

**Researched:** 2026-05-27
**Scope:** Only the two net-new behaviors added in milestone v2.0. The entire v1.0 stack above is fixed and reused unchanged.

The new behaviors are:
1. In-process scheduler firing twice-daily proactive WhatsApp prompts (12:00 and 17:00 `America/Argentina/Buenos_Aires`)
2. Hybrid conversation engine: LLM slot extraction + deterministic state machine driving required questions and the DB write

### New Core Addition: Scheduler

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| APScheduler | **3.11.2** | In-process twice-daily job scheduler | Single new dep. `AsyncIOScheduler` runs in the existing Uvicorn event loop. `CronTrigger` natively accepts IANA timezone strings in 3.11+ (`"America/Argentina/Buenos_Aires"` — no pytz needed). Integrates cleanly with FastAPI `lifespan`. v4 series is alpha-only and explicitly not production-safe per the maintainer. |

**FastAPI lifespan integration pattern:**

```python
# app/main.py
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = AsyncIOScheduler(timezone="America/Argentina/Buenos_Aires")

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(
        send_midday_prompt,
        CronTrigger(hour=12, minute=0),
        id="midday_prompt",
        replace_existing=True,
    )
    scheduler.add_job(
        send_afternoon_prompt,
        CronTrigger(hour=17, minute=0),
        id="afternoon_prompt",
        replace_existing=True,
    )
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)

app = FastAPI(lifespan=lifespan)
```

**Timezone:** APScheduler 3.11.0 added `zoneinfo` support and deprecated pytz. Pass `timezone="America/Argentina/Buenos_Aires"` as a string — the stdlib `zoneinfo` module resolves it. Do not install `pytz`. On Alpine/minimal Docker images, add `tzdata` to get the IANA database (not needed on Debian/Ubuntu/macOS).

**Jobstore:** Use the default `MemoryJobStore`. The two jobs are statically defined at startup with `replace_existing=True`, so they are re-registered on every process start. Losing them on a restart means a prompt doesn't fire that restart-day — acceptable for a ~2 jobs/day use case at a single restaurant. `SQLAlchemyJobStore` on the existing Postgres instance is available if persistence becomes important, but adds serialization complexity for no practical benefit here.

**Multi-worker caveat:** Single-worker Uvicorn (correct for this volume) means exactly one scheduler instance, no duplicate fires. If Gunicorn multi-worker is ever adopted, the scheduler must move to an external cron or add a leader-election file lock. Document this in `app/services/scheduler.py` as a comment.

### New Core Addition: Conversation Engine

**Decision: hand-rolled state machine + existing OpenAI client. No new library.**

The v2.0 conversation graph has exactly 5 states and 2 flows:

```
idle → awaiting_monto → awaiting_ticket → confirm → idle
idle → awaiting_caja_count → idle  (with optional branch into gasto flow)
```

This is a `match` statement in a 100-line orchestrator. No state machine library adds value at this scale:

- **`transitions` 0.9.3** (July 2025, MIT, Python 3.8–3.13): sound library, but its object-oriented wrapping of `Machine`, `State`, and callbacks is overhead for 5 states expressed more clearly as a plain `match`. Adds a dependency future maintainers must understand.
- **LangGraph**: designed for multi-agent graphs with parallelism, mid-flow checkpointing, and 35+ model backends. Brings LangChain as a transitive dependency. Break-even is roughly 2+ cooperative agents or 3+ branching decisions that produce partial results worth preserving independently. This bot has 1 agent and linear state progression.
- **Rasa / Dialogflow**: full NLU platforms. Out of scope for a closed transactional bot where GPT-4o handles all language understanding.

**Build instead:**

```python
# app/services/conversation.py

from enum import StrEnum

class ConvState(StrEnum):
    IDLE = "idle"
    AWAITING_MONTO = "awaiting_monto"
    AWAITING_TICKET = "awaiting_ticket"
    CONFIRM = "confirm"
    AWAITING_CAJA_COUNT = "awaiting_caja_count"

async def handle_message(
    conv: Conversation,
    text: str | None,
    media_url: str | None,
) -> str:
    match conv.state:
        case ConvState.IDLE:
            slots = await extract_slots(text)  # GPT call, returns GastoSlots
            ...
        case ConvState.AWAITING_MONTO:
            ...
        # etc.
    # always: persist updated conv row, return reply text
```

State survives in the `conversations` table (one row per sender). The orchestrator loads, runs one transition, writes back. GPT is called only for free-text slot extraction — code owns all transitions and the DB write decision. Any unparseable reply re-asks the current slot.

### Slot Extraction: Existing OpenAI Client (no new library)

Add a small Pydantic model alongside the existing extraction schemas:

```python
class GastoSlots(BaseModel):
    concepto: Optional[str] = None
    lugar: Optional[str] = None
    monto: Optional[Decimal] = None
```

Use the existing `client.chat.completions.parse()` pattern. One structured output call on a short Spanish string. Cost: <$0.001 per extraction at current pricing.

### v2.0 Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `apscheduler` | 3.11.2 | In-process cron scheduler | Add to `requirements.txt`. Only new backend dep for v2.0. |
| `tzdata` | latest | IANA timezone database | Add only if deploying on Alpine/minimal Linux containers where `/usr/share/zoneinfo` is absent. Not needed on Debian-based images or macOS. |

No frontend package additions for scheduler or conversation engine. New admin views (gastos list, cierres list) reuse existing TanStack Query + React Router patterns.

### v2.0 Installation Delta

```bash
# requirements.txt — add one line
apscheduler==3.11.2
# Optional — Alpine containers only:
tzdata
```

### Alternatives Considered (v2.0)

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| APScheduler 3.11.2 in-process | External cron → protected HTTP endpoint | Use when: Gunicorn multi-worker is deployed (prevents duplicate fires), team already runs Kubernetes CronJobs, or the deployment environment doesn't allow long-running background threads. For a single-process single-restaurant deployment, in-process is simpler and zero new infra. |
| APScheduler 3.11.2 | Celery + Redis | Celery is warranted for high-volume async task queues with retry logic (thousands/day). For 2 static daily jobs, Celery is 10x the operational overhead and requires a Redis broker. |
| APScheduler 3.11.2 | APScheduler 4.0.0a6 | Use v4 when it reaches stable. The revised API (`AsyncScheduler`, `add_schedule()`, `ConflictPolicy`) is cleaner and more explicitly async. Not production-safe today — maintainer states it "may change in backwards incompatible fashion without any migration pathway." |
| Hand-rolled `match` | `transitions` 0.9.3 | Use `transitions` if the state graph grows beyond ~10 states, needs hierarchy (nested states), or requires diagram generation for documentation. At 5 linear states, it adds a dep with no concrete benefit. |
| Hand-rolled `match` | LangGraph | Use LangGraph if design evolves to multiple cooperative agents, parallel branches, or workflows where partial runs need independent checkpointing. Out of scope for v2.0. |

### What NOT to Add (v2.0)

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Celery | Brings Redis dep, worker process management, serialization config — all to fire 2 cron jobs per day. Zero benefit at this scale. | APScheduler 3.11.2 in-process |
| Redis | No caching or queue requirement exists in v2.0. Would only be added to support Celery. | Postgres already present |
| APScheduler 4.x (alpha) | Maintainer explicitly marks it not production-safe; API may break without migration path. | APScheduler 3.11.2 |
| pytz | Deprecated by APScheduler 3.11+ in favor of `zoneinfo`. Installing it alongside APScheduler 3.11 creates version confusion. | `zoneinfo` stdlib (Python 3.9+, present in 3.12) |
| LangGraph / LangChain | Large dependency graph, own serialization layer, LCEL mental model. Bot has 5 states and 2 linear flows — no benefit. | Hand-rolled `match` in `conversation.py` |
| `transitions` library | Adds a dep for a machine trivially expressed as a `match` block + `StrEnum`. | Native Python `match` + `StrEnum` |
| Rasa / Dialogflow / any NLU platform | Platform-level conversation routing. Comically over-scoped for a closed transactional bot with 2 flows. | GPT-4o slot extraction (already in use) |

### Version Compatibility (v2.0 additions)

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| APScheduler 3.11.2 | Python 3.9–3.13 | Python 3.12 is in use — no issues. |
| APScheduler 3.11.2 | FastAPI 0.136 / Uvicorn | `AsyncIOScheduler` runs in the same asyncio event loop as Uvicorn. `lifespan` is the correct integration point — do not use deprecated `@app.on_event`. |
| APScheduler 3.11.2 | SQLAlchemy 2.x | Compatible if `SQLAlchemyJobStore` is used (not recommended for this deployment). |
| `zoneinfo` (stdlib) | Python 3.9+ | Available in Python 3.12 with no install. Add `tzdata` package on Alpine containers only. |
| APScheduler 3.11.2 | pytz | Do NOT install pytz alongside APScheduler 3.11+. It is deprecated and the version resolution creates confusion. |

### Sources (v2.0)

- APScheduler PyPI: https://pypi.org/project/APScheduler/ (verified 2026-05-27, stable = 3.11.2, alpha = 4.0.0a6)
- APScheduler 3.11.0 release notes: https://github.com/agronholm/apscheduler/releases/tag/3.11.0 (verified: zoneinfo support added, pytz deprecated)
- APScheduler 3.x user guide: https://apscheduler.readthedocs.io/en/3.x/userguide.html (MemoryJobStore default; SQLAlchemyJobStore for persistence)
- Context7 `/agronholm/apscheduler` — FastAPI lifespan integration, CronTrigger API, SQLAlchemy data store patterns (HIGH confidence)
- `transitions` PyPI: https://pypi.org/project/transitions/ (verified 2026-05-27, version 0.9.3, released July 2025)
- LangGraph break-even analysis — community consensus across multiple sources: single-flow bots do not benefit (MEDIUM confidence)
- APScheduler 4.x production guidance — PyPI pre-release warning + maintainer GitHub discussions (HIGH confidence)
