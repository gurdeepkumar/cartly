from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Cartly"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    ENV: str = "development"
    DEBUG: bool = True

    # Redis Configuration
    REDIS_URL: str = "redis://localhost:6379/0"

    # LLM Settings (LiteLLM)
    OPENAI_API_KEY: Optional[str] = None
    LLM_MODEL: str = "gpt-4o-mini"

    # External Services
    CRM_BASE_URL: str = "http://localhost:8001"
    CATALOG_BASE_URL: str = "http://localhost:8002"

    # Application Limits & Settings
    RATE_LIMIT_PER_MINUTE: int = 60
    SESSION_TTL_SECONDS: int = 86400
    SLIDING_WINDOW_SIZE: int = 20

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
