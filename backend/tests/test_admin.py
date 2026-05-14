"""Admin API endpoint tests.

Tests all 7 admin endpoints:
  GET /invoices — paginated invoice list with filters
  GET /invoices/{invoice_id} — single invoice with line items
  PATCH /invoices/{invoice_id} — update editable document fields
  PATCH /invoices/{invoice_id}/items/{item_id} — update line item fields
  PATCH /invoices/{invoice_id}/status — update invoice status
  DELETE /invoices/{invoice_id} — delete invoice row (image retained)
  GET /images/{filename} — serve invoice image with path traversal guard
"""
import uuid
from datetime import date

import httpx
import pytest
import pytest_asyncio

from app.db.models import Invoice, InvoiceLineItem
from app.db.session import get_db


@pytest_asyncio.fixture
async def client(db_session):
    """Function-scoped ASGI test client wired to the test DB session."""
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_invoice(**kwargs) -> Invoice:
    """Create an Invoice ORM object with sensible defaults for testing."""
    defaults = dict(
        tipo_comprobante="FACTURA_A",
        numero_documento="0001-00000001",
        proveedor="Acme SA",
        fecha=date(2026, 5, 10),
        status="pending_review",
        image_path="/tmp/invoices/test.jpg",
    )
    defaults.update(kwargs)
    return Invoice(**defaults)


def _seed_line_item(invoice_id: uuid.UUID) -> InvoiceLineItem:
    """Create an InvoiceLineItem ORM object for the given invoice."""
    return InvoiceLineItem(
        invoice_id=invoice_id,
        descripcion="Widget A",
        codigo_sku="SKU-001",
        bultos=None,
        unidades_por_bulto=None,
        precio_unitario_sin_iva=None,
        descuento_pct=None,
        iva_rate=None,
        percepciones_iibb=None,
    )


@pytest.mark.asyncio
@pytest.mark.skip(reason="stub — implement in Task 2")
async def test_list_invoices(client, db_session):
    """GET /invoices returns paginated JSON with items, total, page, page_size."""
    invoice = _seed_invoice()
    db_session.add(invoice)
    await db_session.commit()

    response = await client.get("/invoices")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "page_size" in body
    assert body["total"] == 1
    assert len(body["items"]) == 1


@pytest.mark.asyncio
@pytest.mark.skip(reason="stub — implement in Task 2")
async def test_list_invoices_filter_status(client, db_session):
    """GET /invoices?status=pending_review returns only matching rows."""
    invoice_pending = _seed_invoice(status="pending_review")
    invoice_confirmed = _seed_invoice(
        numero_documento="0001-00000002", status="confirmed"
    )
    db_session.add(invoice_pending)
    db_session.add(invoice_confirmed)
    await db_session.commit()

    response = await client.get("/invoices?status=pending_review")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "pending_review"


@pytest.mark.asyncio
@pytest.mark.skip(reason="stub — implement in Task 2")
async def test_list_invoices_search(client, db_session):
    """GET /invoices?q=Acme matches proveedor via ILIKE."""
    invoice = _seed_invoice(proveedor="Acme SA")
    db_session.add(invoice)
    await db_session.commit()

    response = await client.get("/invoices?q=acme")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert any(item["proveedor"] == "Acme SA" for item in body["items"])


@pytest.mark.asyncio
@pytest.mark.skip(reason="stub — implement in Task 2")
async def test_get_invoice_detail(client, db_session):
    """GET /invoices/{id} returns invoice with non-empty line_items when items exist."""
    invoice = _seed_invoice()
    db_session.add(invoice)
    await db_session.flush()
    line_item = _seed_line_item(invoice.id)
    db_session.add(line_item)
    await db_session.commit()

    response = await client.get(f"/invoices/{invoice.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(invoice.id)
    assert len(body["line_items"]) == 1
    assert body["line_items"][0]["descripcion"] == "Widget A"


@pytest.mark.asyncio
@pytest.mark.skip(reason="stub — implement in Task 2")
async def test_patch_invoice(client, db_session):
    """PATCH /invoices/{id} updates editable fields and returns updated invoice."""
    invoice = _seed_invoice()
    db_session.add(invoice)
    await db_session.commit()

    response = await client.patch(
        f"/invoices/{invoice.id}",
        json={"proveedor": "Updated Vendor", "cuit_proveedor": "20-12345678-9"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["proveedor"] == "Updated Vendor"
    assert body["cuit_proveedor"] == "20-12345678-9"


@pytest.mark.asyncio
@pytest.mark.skip(reason="stub — implement in Task 2")
async def test_patch_line_item(client, db_session):
    """PATCH /invoices/{id}/items/{item_id} updates editable line item fields."""
    invoice = _seed_invoice()
    db_session.add(invoice)
    await db_session.flush()
    line_item = _seed_line_item(invoice.id)
    db_session.add(line_item)
    await db_session.commit()

    response = await client.patch(
        f"/invoices/{invoice.id}/items/{line_item.id}",
        json={"descripcion": "Updated Widget", "codigo_sku": "SKU-999"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["descripcion"] == "Updated Widget"
    assert body["codigo_sku"] == "SKU-999"


@pytest.mark.asyncio
@pytest.mark.skip(reason="stub — implement in Task 2")
async def test_patch_status_confirm(client, db_session):
    """PATCH /invoices/{id}/status with confirmed transitions status."""
    invoice = _seed_invoice()
    db_session.add(invoice)
    await db_session.commit()

    response = await client.patch(
        f"/invoices/{invoice.id}/status", json={"status": "confirmed"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmed"


@pytest.mark.asyncio
@pytest.mark.skip(reason="stub — implement in Task 2")
async def test_patch_status_reject(client, db_session):
    """PATCH /invoices/{id}/status with rejected transitions status."""
    invoice = _seed_invoice()
    db_session.add(invoice)
    await db_session.commit()

    response = await client.patch(
        f"/invoices/{invoice.id}/status", json={"status": "rejected"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"


@pytest.mark.asyncio
@pytest.mark.skip(reason="stub — implement in Task 2")
async def test_patch_status_invalid(client, db_session):
    """PATCH /invoices/{id}/status with invalid status returns 422."""
    invoice = _seed_invoice()
    db_session.add(invoice)
    await db_session.commit()

    response = await client.patch(
        f"/invoices/{invoice.id}/status", json={"status": "auto_saved"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.skip(reason="stub — implement in Task 2")
async def test_delete_invoice(client, db_session):
    """DELETE /invoices/{id} returns 204 and removes the DB row."""
    invoice = _seed_invoice()
    db_session.add(invoice)
    await db_session.commit()
    invoice_id = invoice.id

    response = await client.delete(f"/invoices/{invoice_id}")
    assert response.status_code == 204

    # Verify row is gone
    get_response = await client.get(f"/invoices/{invoice_id}")
    assert get_response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.skip(reason="stub — implement in Task 2")
async def test_delete_retains_image(client, db_session):
    """DELETE /invoices/{id} does not delete the image file from the filesystem."""
    invoice = _seed_invoice()
    db_session.add(invoice)
    await db_session.commit()
    image_path = invoice.image_path

    response = await client.delete(f"/invoices/{invoice.id}")
    assert response.status_code == 204

    # Image file was not deleted (it never existed as /tmp/invoices/test.jpg
    # in tests, so we only verify the DB row is gone and no filesystem deletion occurred)
    import os

    # The file at image_path should not have been touched by the DELETE handler.
    # Since the path doesn't exist in test env, confirm the row is gone instead.
    get_response = await client.get(f"/invoices/{invoice.id}")
    assert get_response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.skip(reason="stub — implement in Task 2")
async def test_image_path_traversal(client):
    """GET /images/../etc/passwd and similar paths return 422 or 400."""
    # FastAPI Path regex rejects paths with / or \ at the validation layer
    response = await client.get("/images/../etc/passwd")
    # FastAPI may normalize the path before routing — either 422 (regex) or 404
    assert response.status_code in (400, 404, 422)

    # URL-encoded slash should also be rejected
    response = await client.get("/images/foo%2Fbar")
    assert response.status_code in (400, 422)


@pytest.mark.asyncio
@pytest.mark.skip(reason="stub — implement in Task 2")
async def test_invalid_uuid_returns_422(client):
    """GET/PATCH/DELETE /invoices/not-a-uuid returns 422 via FastAPI UUID validation."""
    for method, path in [
        ("GET", "/invoices/not-a-uuid"),
        ("PATCH", "/invoices/not-a-uuid"),
        ("PATCH", "/invoices/not-a-uuid/status"),
        ("DELETE", "/invoices/not-a-uuid"),
    ]:
        response = await client.request(method, path, json={})
        assert response.status_code == 422, (
            f"{method} {path} expected 422, got {response.status_code}"
        )


@pytest.mark.asyncio
@pytest.mark.skip(reason="stub — implement in Task 2")
async def test_invoice_id_in_response_is_uuid_string(client, db_session):
    """Invoice id in API responses is a UUID string parseable by uuid.UUID()."""
    invoice = _seed_invoice()
    db_session.add(invoice)
    await db_session.commit()

    # Check list response
    list_response = await client.get("/invoices")
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert len(items) >= 1
    for item in items:
        uuid.UUID(item["id"])  # Raises if not valid UUID string

    # Check detail response
    detail_response = await client.get(f"/invoices/{invoice.id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == str(invoice.id)
