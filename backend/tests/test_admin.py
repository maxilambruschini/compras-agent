"""RED tests for Phase 4 Admin UI — UI-01 and UI-02 requirements.

Tests assert the contract for four read endpoints BEFORE any endpoint code exists.
All tests will FAIL (RED) until Plan 04-02 implements backend/app/routers/admin.py
and mounts it with prefix="/api".

Endpoints under test:
  GET /api/gastos              -> list[GastoOut], newest-first; ?from=&to=&q= filters
  GET /api/gastos/{id}         -> GastoOut; 404 if unknown
  GET /api/gastos/{id}/ticket  -> FileResponse; 404 if no ticket_image_path
  GET /api/cierres             -> list[CierreOut], newest-first

Security gates (from threat model):
  T-04-01 — committed-only boundary: conversations.draft_gasto never surfaces (test_drafts_not_exposed)
  T-04-02 — SQLi-safe ILIKE bind param exercised via test_list_gastos_search
  T-04-03 — CORS allow_origins: http://localhost:5173 (test_cors_header)
  T-04-04 — 404-on-no-ticket path locked (test_get_ticket_no_path)

Fixture pattern mirrors test_prompt_trigger.py::prompt_client EXACTLY:
  monkeypatch AGENT_MODE → get_settings.cache_clear() → create_app() → dependency_overrides
  → httpx.AsyncClient(ASGITransport) → yield → clear overrides → cache_clear()

All app-code imports are deferred to fixture/test bodies so pytest --collect-only
succeeds even before Plan 04-02 creates backend/app/routers/admin.py.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio

from app.config import get_settings

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

TEST_PHONE = "+5491187654321"


# ---------------------------------------------------------------------------
# Fixture: admin_client
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def admin_client(db_session, monkeypatch):
    """ASGI client for admin read endpoints with DB override.

    Mirrors prompt_client in test_prompt_trigger.py EXACTLY, minus the
    WhatsApp provider override (read endpoints need none).

    Yields: (client, app) tuple.
    """
    monkeypatch.setenv("AGENT_MODE", "gastos")
    get_settings.cache_clear()

    from app.db.session import get_db
    from app.main import create_app

    app = create_app()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client, app

    app.dependency_overrides.clear()
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Helper: seed a Gasto row
# ---------------------------------------------------------------------------


def _make_gasto(
    concepto: str = "Carne de cerdo",
    monto: Decimal = Decimal("1500.00"),
    fecha: date | None = None,
    ticket_image_path: str | None = None,
    created_at: datetime | None = None,
) -> "Gasto":  # type: ignore[name-defined]  # noqa: F821
    """Build a Gasto ORM instance.  Import deferred so collection never fails."""
    from app.db.models import Gasto

    kwargs: dict = {
        "id": uuid.uuid4(),
        "fecha": fecha or date(2026, 5, 31),
        "concepto": concepto,
        "monto": monto,
        "sender_phone": TEST_PHONE,
        "ticket_image_path": ticket_image_path,
    }
    if created_at is not None:
        kwargs["created_at"] = created_at
    return Gasto(**kwargs)


def _make_cierre(
    fecha: date | None = None,
    hora_cierre: str = "12:00",
    efectivo_en_caja: Decimal = Decimal("25000.00"),
    created_at: datetime | None = None,
) -> "CajaCierre":  # type: ignore[name-defined]  # noqa: F821
    """Build a CajaCierre ORM instance.  Import deferred so collection never fails."""
    from app.db.models import CajaCierre

    kwargs: dict = {
        "id": uuid.uuid4(),
        "fecha": fecha or date(2026, 5, 31),
        "hora_cierre": hora_cierre,
        "efectivo_en_caja": efectivo_en_caja,
        "sender_phone": TEST_PHONE,
    }
    if created_at is not None:
        kwargs["created_at"] = created_at
    return CajaCierre(**kwargs)


# ---------------------------------------------------------------------------
# UI-01: GET /api/gastos — list tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_gastos_empty(admin_client):
    """GET /api/gastos with no rows → 200, body == []."""
    client, _app = admin_client
    resp = await client.get("/api/gastos")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_gastos_newest_first(admin_client, db_session):
    """Seed 2 gastos with explicit created_at; assert response is newest-first."""
    client, _app = admin_client

    older = _make_gasto(
        concepto="Verduras",
        created_at=datetime(2026, 5, 30, 10, 0, 0, tzinfo=timezone.utc),
    )
    newer = _make_gasto(
        concepto="Carne de vaca",
        created_at=datetime(2026, 5, 31, 9, 0, 0, tzinfo=timezone.utc),
    )
    db_session.add(older)
    db_session.add(newer)
    await db_session.flush()

    resp = await client.get("/api/gastos")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    # Newest created_at must come first
    assert body[0]["concepto"] == "Carne de vaca"
    assert body[1]["concepto"] == "Verduras"


@pytest.mark.asyncio
async def test_list_gastos_date_filter(admin_client, db_session):
    """?from=&to= date filter returns only rows within fecha range."""
    client, _app = admin_client

    in_range = _make_gasto(concepto="En rango", fecha=date(2026, 5, 15))
    out_before = _make_gasto(concepto="Antes del rango", fecha=date(2026, 5, 1))
    out_after = _make_gasto(concepto="Despues del rango", fecha=date(2026, 5, 31))
    db_session.add(in_range)
    db_session.add(out_before)
    db_session.add(out_after)
    await db_session.flush()

    resp = await client.get("/api/gastos", params={"from": "2026-05-10", "to": "2026-05-20"})
    assert resp.status_code == 200
    body = resp.json()
    conceptos = [row["concepto"] for row in body]
    assert "En rango" in conceptos
    assert "Antes del rango" not in conceptos
    assert "Despues del rango" not in conceptos


@pytest.mark.asyncio
async def test_list_gastos_search(admin_client, db_session):
    """?q= case-insensitive ILIKE search on concepto."""
    client, _app = admin_client

    match = _make_gasto(concepto="Pollo Asado")
    no_match = _make_gasto(concepto="Verduras frescas")
    db_session.add(match)
    db_session.add(no_match)
    await db_session.flush()

    # Lowercase query must match mixed-case concepto (ILIKE / case-insensitive)
    resp = await client.get("/api/gastos", params={"q": "pollo"})
    assert resp.status_code == 200
    body = resp.json()
    conceptos = [row["concepto"] for row in body]
    assert "Pollo Asado" in conceptos
    assert "Verduras frescas" not in conceptos


@pytest.mark.asyncio
async def test_list_gastos_search_percent_literal(admin_client, db_session):
    """?q= with a literal '%' must match only the exact substring, not act as ILIKE wildcard.

    WR-01 regression gate: before the fix, searching for '50%' would match any
    concepto containing '50' followed by anything (wildcard). After escaping,
    only the concepto that literally contains '50%' must be returned.
    """
    client, _app = admin_client

    literal_match = _make_gasto(concepto="Descuento 50%")
    no_match = _make_gasto(concepto="Descuento 500 pesos")  # contains '50' but not '50%'
    db_session.add(literal_match)
    db_session.add(no_match)
    await db_session.flush()

    resp = await client.get("/api/gastos", params={"q": "50%"})
    assert resp.status_code == 200
    body = resp.json()
    conceptos = [row["concepto"] for row in body]
    # Only the row with literal '50%' must match
    assert "Descuento 50%" in conceptos
    assert "Descuento 500 pesos" not in conceptos


# ---------------------------------------------------------------------------
# UI-01: GET /api/gastos/{id} — detail + 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_gasto(admin_client, db_session):
    """Seed one Gasto; GET /api/gastos/{id} → 200 with matching fields."""
    client, _app = admin_client

    gasto = _make_gasto(
        concepto="Aceite de oliva",
        monto=Decimal("4500.00"),
        fecha=date(2026, 5, 28),
    )
    db_session.add(gasto)
    await db_session.flush()

    resp = await client.get(f"/api/gastos/{gasto.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert str(gasto.id) == body["id"]
    assert body["concepto"] == "Aceite de oliva"
    assert body["fecha"] == "2026-05-28"
    assert body["sender_phone"] == TEST_PHONE


@pytest.mark.asyncio
async def test_get_gasto_not_found(admin_client):
    """GET /api/gastos/{random uuid} → 404."""
    client, _app = admin_client
    resp = await client.get(f"/api/gastos/{uuid.uuid4()}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# UI-01: GET /api/gastos/{id}/ticket — 404 when no ticket_image_path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_ticket_no_path(admin_client, db_session):
    """Gasto with ticket_image_path=None → GET /ticket returns 404."""
    client, _app = admin_client

    gasto = _make_gasto(ticket_image_path=None)
    db_session.add(gasto)
    await db_session.flush()

    resp = await client.get(f"/api/gastos/{gasto.id}/ticket")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# UI-01: T-04-01 committed-only boundary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drafts_not_exposed(admin_client, db_session):
    """A Conversation row with draft_gasto set must NEVER surface in GET /api/gastos.

    This is the committed-only correctness boundary (T-04-01).
    No committed Gasto row exists — only an in-progress conversation draft.
    Response must be an empty list.
    """
    from app.db.models import Conversation

    draft_json = '{"concepto": "Draft expense", "monto": "999.00", "fecha": "2026-05-31"}'
    conv = Conversation(
        sender_phone=TEST_PHONE,
        state="AWAITING_CONFIRM",
        draft_gasto=draft_json,
    )
    db_session.add(conv)
    await db_session.flush()

    client, _app = admin_client
    resp = await client.get("/api/gastos")
    assert resp.status_code == 200
    # Draft must NOT appear — committed-only boundary
    assert resp.json() == []


# ---------------------------------------------------------------------------
# UI-01: T-04-01/02 Decimal precision gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decimal_serialization(admin_client, db_session):
    """Pydantic v2 must serialize Decimal monto as a STRING, not a float.

    Assert isinstance(body["monto"], str) and exact string value.
    """
    client, _app = admin_client

    gasto = _make_gasto(concepto="Azucar", monto=Decimal("1234567.89"))
    db_session.add(gasto)
    await db_session.flush()

    # Check list endpoint
    resp = await client.get("/api/gastos")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert isinstance(body[0]["monto"], str), (
        f"monto must be serialized as a string, got {type(body[0]['monto'])}"
    )
    assert body[0]["monto"] == "1234567.89"

    # Check detail endpoint
    resp2 = await client.get(f"/api/gastos/{gasto.id}")
    assert resp2.status_code == 200
    detail = resp2.json()
    assert isinstance(detail["monto"], str), (
        f"monto in detail must be a string, got {type(detail['monto'])}"
    )
    assert detail["monto"] == "1234567.89"


# ---------------------------------------------------------------------------
# UI-02: GET /api/cierres — list tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_cierres_empty(admin_client):
    """GET /api/cierres with no rows → 200, body == []."""
    client, _app = admin_client
    resp = await client.get("/api/cierres")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_cierres(admin_client, db_session):
    """Seed 2 CajaCierre rows; GET /api/cierres → newest-first, correct fields."""
    client, _app = admin_client

    older = _make_cierre(
        hora_cierre="12:00",
        efectivo_en_caja=Decimal("10000.00"),
        created_at=datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc),
    )
    newer = _make_cierre(
        hora_cierre="17:00",
        efectivo_en_caja=Decimal("22500.50"),
        created_at=datetime(2026, 5, 31, 17, 0, 0, tzinfo=timezone.utc),
    )
    db_session.add(older)
    db_session.add(newer)
    await db_session.flush()

    resp = await client.get("/api/cierres")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2

    # Newest first
    assert body[0]["hora_cierre"] == "17:00"
    assert body[1]["hora_cierre"] == "12:00"

    # Required fields present
    first = body[0]
    assert "fecha" in first
    assert "hora_cierre" in first
    assert "efectivo_en_caja" in first
    assert "sender_phone" in first

    # Decimal precision as string (T-04-01 precision gate for cierres)
    assert isinstance(first["efectivo_en_caja"], str), (
        f"efectivo_en_caja must be a string, got {type(first['efectivo_en_caja'])}"
    )
    assert first["efectivo_en_caja"] == "22500.50"


# ---------------------------------------------------------------------------
# UI-01/02: T-04-03 CORS gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cors_header(admin_client):
    """Simple GET with Origin: http://localhost:5173 must return CORS allow header.

    CORSMiddleware (Plan 04-02) must echo the allowed origin on simple GET requests.
    This is the T-04-03 CORS mitigation gate.
    """
    client, _app = admin_client
    resp = await client.get(
        "/api/gastos",
        headers={"Origin": "http://localhost:5173"},
    )
    assert resp.status_code == 200
    cors_header = resp.headers.get("access-control-allow-origin")
    assert cors_header == "http://localhost:5173", (
        f"Expected 'access-control-allow-origin: http://localhost:5173', got {cors_header!r}. "
        "CORSMiddleware must be added to create_app() in Plan 04-02."
    )
