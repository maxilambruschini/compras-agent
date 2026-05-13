"""Tests for INF-03: pydantic-settings fail-fast on missing required env vars."""
import pytest
from pydantic import ValidationError


def test_missing_env_raises(monkeypatch, tmp_path):
    """INF-03: Settings() raises ValidationError when all required env vars are absent."""
    # Use a temp directory with no .env file to prevent pydantic-settings from
    # loading .env from the repo root.
    monkeypatch.chdir(tmp_path)

    # Remove all required env vars
    for var in [
        "DATABASE_URL",
        "OPENAI_API_KEY",
        "WHATSAPP_TOKEN",
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_VERIFY_TOKEN",
    ]:
        monkeypatch.delenv(var, raising=False)

    from app.config import Settings, get_settings

    get_settings.cache_clear()

    with pytest.raises(ValidationError):
        Settings()

    # Restore cache clear so other tests get a fresh Settings with env vars
    get_settings.cache_clear()


def test_settings_load(monkeypatch):
    """INF-03: Settings() loads correctly when all required env vars are present."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/db")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    monkeypatch.setenv("WHATSAPP_TOKEN", "test-token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "1234567890")
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "verify-token")

    from app.config import Settings, get_settings

    get_settings.cache_clear()
    settings = Settings()

    assert settings.database_url == "postgresql+asyncpg://user:pass@localhost:5432/db"
    assert settings.openai_api_key == "sk-test-key"
    assert settings.whatsapp_token == "test-token"
    assert settings.whatsapp_phone_number_id == "1234567890"
    assert settings.whatsapp_verify_token == "verify-token"
    assert settings.confidence_threshold == 0.85
    assert settings.debug is False
    assert settings.log_level == "INFO"

    get_settings.cache_clear()
