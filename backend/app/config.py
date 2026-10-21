"""Validated configuration; loading settings never mutates process environment."""

from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env", extra="ignore"
    )
    DATABASE_URL: SecretStr = SecretStr("postgresql://localhost/datapilot")
    LLM_PROVIDER: str = "groq"
    LLM_API_KEY: SecretStr = SecretStr("")
    GROQ_API_KEY: SecretStr = SecretStr("")
    GEMINI_API_KEY: SecretStr = SecretStr("")
    ROUTER_MODEL: str = "openai/gpt-oss-120b"
    SQL_MODEL: str = "openai/gpt-oss-120b"
    ANSWER_MODEL: str = "openai/gpt-oss-120b"
    BUSINESS_TIMEZONE: str = "Asia/Kolkata"
    BUSINESS_CURRENCY: str = "INR"
    FRONTEND_URL: str = "http://localhost:3000"
    CORS_ORIGINS: str = ""
    SQL_TIMEOUT_MS: int = Field(5000, ge=100, le=30000)
    MAX_SQL_REPAIRS: int = Field(2, ge=0, le=2)
    QUERY_DEFAULT_ROWS: int = Field(50, ge=1, le=100)
    QUERY_MAX_ROWS: int = Field(100, ge=1, le=100)
    SCHEMA_CACHE_TTL_SECONDS: int = Field(3600, ge=1)
    MODEL_TIMEOUT_SECONDS: float = Field(20, gt=0)
    REQUEST_TIMEOUT_SECONDS: float = Field(90, gt=0)
    BUSINESS_TABLES: str = "customers,orders,order_items,products,categories,payments"
    # Enabled only after the operator maps each metric to the actual schema.
    ENABLED_METRICS: str = ""
    METRIC_SCHEMA_NOTES: str = ""
    CONVERSATION_LIMIT: int = Field(200, ge=1)
    SESSION_SECRET: SecretStr = SecretStr("")
    SESSION_SECURE: bool = False

    @model_validator(mode="after")
    def validate_settings(self):
        ZoneInfo(self.BUSINESS_TIMEZONE)
        if self.QUERY_DEFAULT_ROWS > self.QUERY_MAX_ROWS:
            raise ValueError("QUERY_DEFAULT_ROWS must not exceed QUERY_MAX_ROWS")
        if self.LLM_PROVIDER not in {"groq", "google"}:
            raise ValueError("LLM_PROVIDER must be groq or google")
        from app.business.metrics import METRICS

        if self.metrics - METRICS.keys():
            raise ValueError("ENABLED_METRICS contains unsupported metrics")
        if self.metrics and not self.METRIC_SCHEMA_NOTES.strip():
            raise ValueError("Map enabled metrics in METRIC_SCHEMA_NOTES before use")
        if any(not t.replace("_", "").isalnum() or "." in t for t in self.tables):
            raise ValueError(
                "BUSINESS_TABLES must contain unqualified business table names"
            )
        return self

    @property
    def tables(self) -> frozenset[str]:
        return frozenset(
            t.strip() for t in self.BUSINESS_TABLES.split(",") if t.strip()
        )

    @property
    def metrics(self) -> frozenset[str]:
        return frozenset(
            t.strip() for t in self.ENABLED_METRICS.split(",") if t.strip()
        )
