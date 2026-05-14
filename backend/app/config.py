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
    whatsapp_token: str
    whatsapp_phone_number_id: str
    whatsapp_verify_token: str

    # Optional with defaults
    debug: bool = False
    log_level: str = "INFO"
    confidence_threshold: float = 0.85
    storage_path: str = "/data/invoices"


@lru_cache
def get_settings() -> Settings:
    return Settings()
