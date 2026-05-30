"""RED tests for Phase 3 TRIG-01 and TRIG-02 requirements.

Tests:
  TRIG-01 (auth)  — valid token → 200 + send; missing/wrong token → 401
  TRIG-01 (skip)  — non-idle recipient → 200 skipped, no send
  TRIG-01 (state) — successful send sets AWAITING_CIERRE state
  TRIG-02         — prompt text reaches provider.send_message with correct substrings
  Security        — empty configured token → fail-closed (T-03-A2)
  Lock            — SELECT ... FOR NO KEY UPDATE issued in trigger endpoint

Wave 0 RED phase: tests will fail/error until Plans 02-03 implement the endpoint
(app.routers.prompt and the AWAITING_CIERRE state). All imports of not-yet-existing
symbols (verify_token, ConvState.AWAITING_CIERRE) are deferred to test bodies / fixtures
so that pytest --collect-only succeeds without ImportError.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio

from app.config import get_settings
from app.db.models import Conversation
from app.routers.gastos import get_whatsapp_provider


# ---------------------------------------------------------------------------
# Helpers (mirroring test_gastos_webhook.py)
# ---------------------------------------------------------------------------

TEST_PHONE = "+5491112345678"
TEST_TOKEN = "test-prompt-token"
AUTH_HEADER = {"Authorization": f"Bearer {TEST_TOKEN}"}


def make_mock_provider() -> MagicMock:
    """Build a mock WhatsApp provider for prompt endpoint tests."""
    from app.providers.base import WhatsAppProvider

    mock = MagicMock(spec=WhatsAppProvider)
    mock.validate_signature = MagicMock(return_value=True)
    mock.send_message = AsyncMock()
    mock.download_media = AsyncMock(return_value=b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def prompt_client(db_session, monkeypatch):
    """ASGI client for the prompt endpoint with mocked provider and DB.

    Mirrors webhook_client fixture in test_gastos_webhook.py. Sets
    GASTOS_PROMPT_TOKEN so happy-path tests can authenticate. The session-scoped
    env_setup already sets it, but we re-set it here to make the fixture
    self-contained and to allow monkeypatch overrides in individual tests.
    """
    monkeypatch.setenv("AGENT_MODE", "gastos")
    monkeypatch.setenv("GASTOS_PROMPT_TOKEN", TEST_TOKEN)
    get_settings.cache_clear()

    from app.db.session import get_db
    from app.main import create_app

    app = create_app()
    mock_provider = make_mock_provider()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_whatsapp_provider] = lambda: mock_provider
    app.dependency_overrides[get_db] = override_get_db

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client, mock_provider, app

    app.dependency_overrides.clear()
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# TRIG-01: Authentication tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_token_sends(prompt_client):
    """Valid bearer token → 200 + send_message awaited once."""
    client, mock_provider, app = prompt_client
    resp = await client.post(
        "/gastos/prompt",
        json={"phone_number": TEST_PHONE},
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "sent"
    mock_provider.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_token_401(prompt_client):
    """Missing Authorization header → 401, send_message NOT awaited."""
    client, mock_provider, app = prompt_client
    resp = await client.post(
        "/gastos/prompt",
        json={"phone_number": TEST_PHONE},
        # No Authorization header
    )
    assert resp.status_code == 401
    mock_provider.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_token_401(prompt_client):
    """Wrong bearer token → 401, send_message NOT awaited."""
    client, mock_provider, app = prompt_client
    resp = await client.post(
        "/gastos/prompt",
        json={"phone_number": TEST_PHONE},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401
    mock_provider.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_configured_token_denies(db_session, monkeypatch):
    """Fail-closed: when GASTOS_PROMPT_TOKEN="" any request → 401 (T-03-A2).

    Builds a separate app instance with an empty token to verify that the
    verify_token dependency denies all requests regardless of the presented
    credential — including an empty Bearer credential that would otherwise
    match via compare_digest("", "").
    """
    monkeypatch.setenv("AGENT_MODE", "gastos")
    monkeypatch.setenv("GASTOS_PROMPT_TOKEN", "")  # empty — fail-closed
    get_settings.cache_clear()

    from app.db.session import get_db
    from app.main import create_app

    app = create_app()
    mock_provider = make_mock_provider()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_whatsapp_provider] = lambda: mock_provider
    app.dependency_overrides[get_db] = override_get_db

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # Any non-empty token → 401
        resp = await client.post(
            "/gastos/prompt",
            json={"phone_number": TEST_PHONE},
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        assert resp.status_code == 401, f"Expected 401 but got {resp.status_code}"

        # Empty credential (compare_digest("","") edge case) → still 401
        resp2 = await client.post(
            "/gastos/prompt",
            json={"phone_number": TEST_PHONE},
            headers={"Authorization": "Bearer "},
        )
        assert resp2.status_code == 401, f"Expected 401 but got {resp2.status_code}"

    app.dependency_overrides.clear()
    get_settings.cache_clear()
    mock_provider.send_message.assert_not_awaited()


# ---------------------------------------------------------------------------
# TRIG-01: Active conversation skip + state mutation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_conversation_skipped(prompt_client, db_session):
    """Non-idle conversation → 200 skipped, no send, state unchanged."""
    from app.services.conversation import ConvState

    client, mock_provider, app = prompt_client

    # Seed a conversation in a non-idle state
    conv = Conversation(sender_phone=TEST_PHONE, state=ConvState.AWAITING_MONTO)
    db_session.add(conv)
    await db_session.flush()

    resp = await client.post(
        "/gastos/prompt",
        json={"phone_number": TEST_PHONE},
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "skipped"
    assert data.get("reason") == "active_conversation"
    mock_provider.send_message.assert_not_awaited()

    await db_session.refresh(conv)
    assert conv.state == ConvState.AWAITING_MONTO, "State must not be changed on skip"


@pytest.mark.asyncio
async def test_state_set_to_awaiting_cierre(prompt_client, db_session):
    """Successful trigger → Conversation row state == AWAITING_CIERRE after request."""
    client, mock_provider, app = prompt_client

    resp = await client.post(
        "/gastos/prompt",
        json={"phone_number": TEST_PHONE},
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 200

    # Import AWAITING_CIERRE here (not at module top) so collection works
    # even before Plan 02 adds the constant to ConvState.
    from app.services.conversation import ConvState

    from sqlalchemy import select as sa_select

    result = await db_session.execute(
        sa_select(Conversation).where(Conversation.sender_phone == TEST_PHONE)
    )
    conv = result.scalar_one_or_none()
    assert conv is not None, "No Conversation row found for the test phone"
    assert conv.state == ConvState.AWAITING_CIERRE, (
        f"Expected AWAITING_CIERRE, got {conv.state!r}"
    )


# ---------------------------------------------------------------------------
# TRIG-02: Prompt text content test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prompt_text_sent(prompt_client):
    """Prompt message includes efectivo and otra compra nudge substrings."""
    client, mock_provider, app = prompt_client

    resp = await client.post(
        "/gastos/prompt",
        json={"phone_number": TEST_PHONE},
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 200

    mock_provider.send_message.assert_awaited_once()
    call_kwargs = mock_provider.send_message.call_args
    # Recipient must carry the Twilio "whatsapp:" prefix (DB key is prefix-free).
    sent_to = call_kwargs.kwargs.get("to")
    if sent_to is None and call_kwargs.args:
        sent_to = call_kwargs.args[0]
    assert sent_to.startswith("whatsapp:"), (
        f"Send recipient must carry the 'whatsapp:' prefix for Twilio. Got: {sent_to!r}"
    )
    # Accept both positional and keyword invocations for the text body
    if call_kwargs.kwargs.get("text"):
        sent_text = call_kwargs.kwargs["text"]
    else:
        # text may be the second positional arg (to, text)
        sent_text = call_kwargs.args[1] if len(call_kwargs.args) > 1 else call_kwargs.args[0]

    sent_text_lower = sent_text.lower()
    assert "efectivo" in sent_text_lower, (
        f"Prompt must mention 'efectivo'. Got:\n{sent_text}"
    )
    assert "otra compra" in sent_text_lower, (
        f"Prompt must contain 'otra compra' nudge. Got:\n{sent_text}"
    )


# ---------------------------------------------------------------------------
# Lock assertion: SELECT ... FOR NO KEY UPDATE in trigger endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_row_lock_issued(prompt_client, db_session):
    """Trigger endpoint issues SELECT ... FOR NO KEY UPDATE on the conversations row.

    Strategy mirrors test_conversation.py::test_row_lock_issued: spy on
    db_session.execute, capture Select statements, assert the lock hint is
    attached and compiles to FOR NO KEY UPDATE in Postgres dialect.
    """
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.sql.selectable import Select as SASelect

    client, mock_provider, app = prompt_client

    captured_selects: list = []
    original_execute = db_session.execute

    async def spy_execute(stmt, *args, **kwargs):
        if isinstance(stmt, SASelect):
            captured_selects.append(stmt)
        return await original_execute(stmt, *args, **kwargs)

    db_session.execute = spy_execute  # type: ignore[method-assign]

    await client.post(
        "/gastos/prompt",
        json={"phone_number": TEST_PHONE},
        headers=AUTH_HEADER,
    )

    # Restore
    db_session.execute = original_execute  # type: ignore[method-assign]

    assert len(captured_selects) >= 1, "No SELECT statements captured"

    locked_stmts = [
        s for s in captured_selects
        if getattr(s, "_for_update_arg", None) is not None
    ]
    assert locked_stmts, (
        "No SELECT with .with_for_update() was captured — "
        "trigger endpoint must issue SELECT ... FOR NO KEY UPDATE on conversations row."
    )

    compiled_sql = str(locked_stmts[0].compile(dialect=postgresql.dialect()))
    assert "FOR NO KEY UPDATE" in compiled_sql, (
        f"Lock statement compiled to:\n{compiled_sql}\n"
        "Expected 'FOR NO KEY UPDATE' (key_share=True) not found."
    )
