"""Centralized, type-safe settings loaded from .env."""
from functools import lru_cache
import sys
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All app settings. Loaded from .env, validated by Pydantic."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ─── LLM Providers ──────────────────────────────
    google_api_key: str = Field(..., description="Gemini API key")
    gemini_model: str = "gemini-2.5-flash"

    watsonx_api_key: str | None = None
    watsonx_url: str | None = None
    watsonx_project_id: str | None = None

    anthropic_api_key: str | None = None

    # ─── Observability ──────────────────────────────
    langsmith_api_key: str | None = None
    langsmith_project: str = "infra-inspect-ai"
    langchain_tracing_v2: bool = False

    # ─── App Config ─────────────────────────────────
    environment: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    default_llm_provider: Literal["gemini", "watsonx", "anthropic"] = "gemini"
    vision_llm_provider: Literal["gemini", "anthropic"] = "gemini"

    # ---------- MCP server commands (Day 14) ----------
    # Each is a list[str] suitable for subprocess.Popen, sent through MCPClient.
    mcp_filesystem_command: list[str] = Field(
        default_factory=lambda: [sys.executable, "-m", "scripts.run_filesystem_server"]
    )
    mcp_workorder_command: list[str] = Field(
        default_factory=lambda: [sys.executable, "-m", "scripts.run_workorder_server"]
    )
    mcp_notification_command: list[str] = Field(
        default_factory=lambda: [sys.executable, "-m", "scripts.run_notification_server"]
    )

    mcp_enabled: bool = True
    """Set to False to use the legacy direct-call paths instead of MCP servers.
    Useful for debugging or running without MCP infrastructure."""

    # ---------- RAG retrieval thresholds (Day 18) ----------
    min_retrieval_score: float = Field(
        default=0.10,
        ge=0.0,
        le=1.0,
        description="Reranker score floor below which chunks are dropped. "
                    "Empirically calibrated from Day 18 evals: BGE reranker typically "
                    "outputs 0.05-0.20 even for relevant chunks, so 0.10 is the sweet spot. "
                    "Previous value (0.3) rejected 60% of findings.",
    )
    chunks_per_finding: int = Field(
        default=5,
        ge=1,
        le=20,
        description="How many top chunks to feed the LLM per finding.",
    )


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance. Use this everywhere."""
    return Settings()  # type: ignore[call-arg]