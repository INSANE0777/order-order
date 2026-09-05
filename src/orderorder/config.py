"""Runtime settings. Everything comes from environment variables or a .env file; see .env.example."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Storage. Large things live here, off the system drive.
    orderorder_data_dir: Path = Field(default=Path("data"))
    database_url: str = ""

    # Language models as LangChain provider strings ("provider:model").
    llm_primary: str = "google_genai:gemini-2.5-flash"
    llm_fallbacks: str = "groq:openai/gpt-oss-120b,cerebras:gpt-oss-120b,ollama:qwen3.5:4b"
    llm_long_context: str = "google_genai:gemini-2.5-flash"
    llm_sensitive: str = "groq:openai/gpt-oss-120b"
    # An OpenAI-compatible endpoint to send `openai:` provider strings to, instead of OpenAI itself.
    # This is one setting for three cases the project actually has: a router or gateway, a self-hosted
    # SGLang or vLLM server (the production plan in docs/TECH_STACK.md section 5), and any of the
    # providers that speak the OpenAI protocol. Empty means talk to OpenAI.
    llm_base_url: str = ""

    # Indian Kanoon API.
    indiankanoon_token: str | None = None
    indiankanoon_daily_quota: int = 200

    # Local models (later build phases).
    embeddings_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    # Tracing.
    langsmith_tracing: bool = False

    @property
    def data_dir(self) -> Path:
        self.orderorder_data_dir.mkdir(parents=True, exist_ok=True)
        return self.orderorder_data_dir

    @property
    def corpus_dir(self) -> Path:
        d = self.data_dir / "corpus"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def db_url(self) -> str:
        """SQLite inside the data directory unless DATABASE_URL points at Postgres."""
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'orderorder.sqlite3').as_posix()}"

    @property
    def is_postgres(self) -> bool:
        return self.db_url.startswith("postgresql")

    @property
    def fallback_models(self) -> list[str]:
        return [m.strip() for m in self.llm_fallbacks.split(",") if m.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
