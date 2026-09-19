"""Runtime settings for the API and services, read from the environment or `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from xray.config import PROJECT_ROOT


class Settings(BaseSettings):
    """Every variable is prefixed with `XRAY_`, see `.env.example`. API keys work unprefixed too."""

    model_config = SettingsConfigDict(env_prefix="XRAY_", env_file=".env", extra="ignore")

    env: str = "local"
    log_level: str = "INFO"
    serving_dir: Path = PROJECT_ROOT / "data" / "serving"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    slack_webhook_url: str | None = None
    tavily_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("XRAY_TAVILY_API_KEY", "TAVILY_API_KEY")
    )
    exa_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("XRAY_EXA_API_KEY", "EXA_API_KEY")
    )
    helmcode_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("XRAY_HELMCODE_API_KEY", "HELMCODE_API_KEY")
    )
    helmcode_base_url: str = "https://api.helmcode.com/v1"
    llm_model: str = "glm5.3"
    context_ttl_days: int = 7


@lru_cache
def get_settings() -> Settings:
    return Settings()
