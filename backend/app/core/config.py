"""Application configuration loaded from environment variables (12-factor style)."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "RhymePilot AI"
    environment: str = Field(default="development", description="development | production | test")
    log_level: str = "INFO"

    # Security
    secret_key: str = Field(default="change-me-in-production-please-32chars", min_length=16)
    token_encryption_key: str = Field(
        default="",
        description="Fernet key for encrypting OAuth tokens and API keys at rest. Derived from SECRET_KEY if empty.",
    )
    access_token_expire_minutes: int = Field(default=720, ge=5, le=60 * 24 * 14)
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    # Persistence
    database_url: str = "postgresql+psycopg://rhymepilot:rhymepilot@localhost:5432/rhymepilot"
    media_root: Path = Path("./media")
    max_media_file_mb: int = Field(default=512, ge=1)

    # LLM providers (all optional; configure at least one). Model names are never assumed.
    xai_api_key: str = ""
    xai_model: str = ""
    xai_base_url: str = "https://api.x.ai/v1"
    openai_api_key: str = ""
    openai_model: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    gemini_api_key: str = ""
    gemini_model: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    llm_timeout_seconds: float = Field(default=90.0, gt=0)
    llm_max_retries: int = Field(default=3, ge=0, le=8)

    # YouTube / Google
    youtube_api_key: str = Field(default="", description="Optional API key for public research calls")
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:8000/api/v1/youtube/callback"
    frontend_url: str = "http://localhost:5173"
    youtube_http_timeout_seconds: float = 60.0

    # Worker
    worker_poll_interval_seconds: float = Field(default=2.0, gt=0)
    max_concurrent_jobs: int = Field(default=1, ge=1, le=8)
    job_max_attempts: int = Field(default=3, ge=1, le=10)
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    tts_binary: str = Field(default="espeak-ng", description="Local TTS executable; disabled if not installed")

    @field_validator("media_root")
    @classmethod
    def _resolve_media_root(cls, v: Path) -> Path:
        return v.expanduser().resolve()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
