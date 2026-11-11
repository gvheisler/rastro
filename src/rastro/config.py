from pathlib import Path
from typing import Any, Literal, Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
SQL_DIR = ROOT / "sql"
LOG_DIR = ROOT / "logs"
OLLAMA_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODELS = {"openai": "rastro-sql", "anthropic": "claude-opus-5-5"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_user: str = "rastro"
    postgres_password: str
    postgres_db: str = "rastro"
    postgres_host: str = "localhost"
    postgres_port: int = 5433
    readonly_user: str = "rastro_ro"
    readonly_password: str
    # "openai" is any server that speaks /v1/chat/completions (Ollama, vLLM, OpenAI, ...);
    # "anthropic" is the Claude API.
    llm_provider: Literal["openai", "anthropic"] = "openai"
    llm_base_url: str = OLLAMA_BASE_URL
    llm_model: str = ""
    llm_api_key: str | None = None
    anthropic_api_key: str | None = None
    # Sent with each request by the "openai" provider only.
    llm_extra_body: dict[str, Any] = {"reasoning_effort": "none"}
    llm_temperature: float | None = 0
    # Used by the "anthropic" provider only; unset keeps the model's default.
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    transferegov_base_url: str = "https://api-publica.transferegov.gestao.gov.br/especiais"

    @field_validator(
        "llm_api_key", "anthropic_api_key", "llm_temperature", "llm_effort", mode="before"
    )
    @classmethod
    def _blank_is_unset(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _default_model(self) -> Self:
        if not self.llm_model:
            self.llm_model = DEFAULT_MODELS[self.llm_provider]
        return self

    @property
    def anthropic_key(self) -> str | None:
        """LLM_API_KEY, or ANTHROPIC_API_KEY when only that one is set."""
        return self.llm_api_key or self.anthropic_api_key

    @property
    def anthropic_base_url(self) -> str | None:
        """LLM_BASE_URL when it was changed; the Ollama default does not apply to Claude."""
        return None if self.llm_base_url == OLLAMA_BASE_URL else self.llm_base_url

    def _dsn(self, user: str, password: str) -> str:
        return (
            f"host={self.postgres_host} port={self.postgres_port} dbname={self.postgres_db} "
            f"user={user} password={password}"
        )

    @property
    def dsn(self) -> str:
        return self._dsn(self.postgres_user, self.postgres_password)

    @property
    def readonly_dsn(self) -> str:
        return self._dsn(self.readonly_user, self.readonly_password)


def get_settings() -> Settings:
    return Settings()
