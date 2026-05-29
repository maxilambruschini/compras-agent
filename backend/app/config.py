from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Required — no default — app refuses to start if missing (INF-03)
    database_url: str  # postgresql+asyncpg://user:pass@host:5432/db
    openai_api_key: str

    # Meta WhatsApp Cloud API credentials (required when whatsapp_provider="meta"; empty default allows Twilio path)
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""

    # Optional with defaults
    debug: bool = False
    log_level: str = "INFO"
    confidence_threshold: float = 0.85
    storage_path: str = "/data/invoices"

    # Agent selection (D-09 — v2.0 demo isolation)
    # "gastos" = Gastos Bot demo (default for v2.0 milestone)
    # "invoice" = v1.0 invoice extraction demo
    agent_mode: str = "gastos"

    # Conversation timeout in hours (D-08)
    # A conversation row whose updated_at is older than this threshold auto-resets to idle
    # on the next inbound message. Uses the existing updated_at column — no extra column needed.
    conversation_timeout_hours: int = 4

    # WhatsApp provider selection (D-04)
    whatsapp_provider: str = "twilio"  # "twilio" | "meta"

    # Twilio credentials (required when whatsapp_provider="twilio"; empty default allows Meta path)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""  # must include "whatsapp:" prefix, e.g. "whatsapp:+14155238886"

    # Optional: when set, signature validation uses this URL instead of str(request.url).
    # Required when running behind ngrok or a reverse proxy where request.url reflects the
    # internal host rather than the public URL that Twilio signed. (resolves 03-REVIEWS.md
    # Codex MEDIUM concern #3)
    webhook_base_url: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
