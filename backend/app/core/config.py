"""Application settings, loaded from environment variables and backend/.env."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "AI Chatbot"
    environment: Literal["development", "production", "test"] = "development"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:4200"]
    )

    # --- Auth (single user for phase 1) ---
    app_username: str = "admin"
    app_display_name: str = "Admin"
    app_password_hash: str = ""
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 720
    # Premium models: how long a password re-check stays valid.
    premium_unlock_minutes: int = 30
    # Wrong passwords allowed (login + re-check) before a short lockout.
    max_password_attempts: int = 5
    password_lockout_minutes: int = 5

    # --- Storage ---
    storage_backend: Literal["json", "memory"] = "json"
    data_dir: Path = BACKEND_DIR / "data"

    # --- Models ---
    models_config_path: Path = BACKEND_DIR / "config" / "models.yaml"

    # --- External APIs ---
    openai_api_key: str = ""
    tavily_api_key: str = ""

    # --- Assistant / LLM ---
    assistant_name: str = "AI Chatbot"
    # Cheap model for background jobs (chat titles; later router fallback, memory).
    utility_model: str = "gpt-6-luna"
    moderation_model: str = "omni-moderation-latest"
    # Older messages beyond this (approximate) size are not sent to the model.
    # The context meter still shows real usage; there is no UI limit.
    history_max_tokens: int = 60_000
    llm_timeout_seconds: float = 60
    # Router: use the utility model when the quick rules can't decide.
    router_use_llm: bool = True

    # --- Web search (Tavily) ---
    # Per query. Up to 2 queries run per question; duplicates are merged.
    search_max_results: int = 6
    # "advanced" gives better passages (2 credits per query); "basic" is 1 credit.
    search_depth: Literal["basic", "advanced"] = "advanced"
    search_max_queries: int = 2
    # Most results passed to the evidence check and the answer writer.
    search_max_sources: int = 8
    # Compare all results with the utility model before answering (more trustworthy).
    search_verify: bool = True

    # --- Uploads ---
    max_upload_mb: int = 10
    max_files_per_chat: int = 3
    # Longest document text sent to the model per file (characters, ~4 chars/token).
    max_document_chars: int = 60_000

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("data_dir", "models_config_path", mode="after")
    @classmethod
    def _resolve_relative(cls, value: Path) -> Path:
        return value if value.is_absolute() else (BACKEND_DIR / value).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
