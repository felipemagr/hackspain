"""Runtime settings for the API and services, read from the environment or `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from xray.config import PROJECT_ROOT


class Settings(BaseSettings):
    """Every variable is prefixed with `XRAY_`, see `.env.example`."""

    model_config = SettingsConfigDict(env_prefix="XRAY_", env_file=".env", extra="ignore")

    env: str = "local"
    log_level: str = "INFO"
    serving_dir: Path = PROJECT_ROOT / "data" / "serving"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    slack_webhook_url: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
