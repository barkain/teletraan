"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/market-analyzer.db"

    # --- LLM Provider Configuration ---
    # The claude-agent-sdk picks up authentication from environment variables.
    # Set ONE of the following authentication methods:
    #   1. ANTHROPIC_API_KEY          - Direct Anthropic API (recommended for production)
    #   2. CLAUDE_CODE_USE_BEDROCK=1  - Amazon Bedrock (+ AWS credentials)
    #   3. CLAUDE_CODE_USE_VERTEX=1   - Google Vertex AI (+ GCP credentials)
    #   4. CLAUDE_CODE_USE_FOUNDRY=1  - Azure AI Foundry (+ Azure credentials)
    #   5. (none of the above)        - Claude Code subscription (dev only)
    LLM_PROVIDER: str = "auto"  # auto | anthropic_api | bedrock | vertex | azure | proxy | subscription
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"

    # Amazon Bedrock settings
    CLAUDE_CODE_USE_BEDROCK: bool = False
    AWS_REGION: Optional[str] = None

    # Google Vertex AI settings
    CLAUDE_CODE_USE_VERTEX: bool = False
    VERTEX_PROJECT: Optional[str] = None
    VERTEX_REGION: Optional[str] = None

    # Azure AI Foundry settings
    CLAUDE_CODE_USE_FOUNDRY: bool = False

    # z.ai / API Proxy settings
    ANTHROPIC_AUTH_TOKEN: Optional[str] = None  # z.ai or proxy API key
    ANTHROPIC_BASE_URL: Optional[str] = None  # Custom API endpoint (e.g., https://api.z.ai/api/anthropic)
    API_TIMEOUT_MS: Optional[int] = None  # Timeout override in milliseconds

    # API Keys (optional data sources)
    FRED_API_KEY: Optional[str] = None
    FINNHUB_API_KEY: Optional[str] = None

    # Application
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # Data Source Integrations
    PREDICTION_MARKETS_ENABLED: bool = True
    REDDIT_SENTIMENT_ENABLED: bool = True
    POLYMARKET_RATE_LIMIT: int = 30  # Max requests/minute to Polymarket APIs
    KALSHI_RATE_LIMIT: int = 20  # Max requests/minute to Kalshi API

    # --- GitHub Pages Publishing ---
    # Publishing is DISABLED by default for fork safety.
    # If you fork this repo and run discovery, reports will NOT be pushed
    # to the original author's GitHub Pages unless you explicitly opt in.
    GITHUB_PAGES_ENABLED: bool = False
    GITHUB_PAGES_REPO: Optional[str] = None  # e.g., "username/repo" — explicit override
    GITHUB_PAGES_BRANCH: str = "gh-pages"
    GITHUB_PAGES_BASE_URL: Optional[str] = None  # e.g., "https://username.github.io/repo"

    def get_llm_provider(self) -> str:
        """Detect which LLM provider is configured.

        If LLM_PROVIDER is explicitly set (not 'auto'), returns that value.
        Otherwise auto-detects from environment variable flags:
          - ANTHROPIC_API_KEY set   -> 'anthropic_api'
          - CLAUDE_CODE_USE_BEDROCK -> 'bedrock'
          - CLAUDE_CODE_USE_VERTEX  -> 'vertex'
          - CLAUDE_CODE_USE_FOUNDRY -> 'azure'
          - fallback                -> 'subscription'
        """
        if self.LLM_PROVIDER != "auto":
            return self.LLM_PROVIDER

        if self.ANTHROPIC_AUTH_TOKEN:
            return "proxy"
        if self.ANTHROPIC_API_KEY:
            return "anthropic_api"
        if self.CLAUDE_CODE_USE_BEDROCK:
            return "bedrock"
        if self.CLAUDE_CODE_USE_VERTEX:
            return "vertex"
        if self.CLAUDE_CODE_USE_FOUNDRY:
            return "azure"
        return "subscription"

    def _is_ollama(self) -> bool:
        """Check if the proxy target is an Ollama instance."""
        base = (self.ANTHROPIC_BASE_URL or "").lower()
        return "localhost:11434" in base or "ollama" in base

    def get_llm_display_name(self) -> str:
        """Human-readable name for the active LLM provider (for logging)."""
        names = {
            "anthropic_api": "Anthropic API (direct)",
            "bedrock": "Amazon Bedrock",
            "vertex": "Google Vertex AI",
            "azure": "Azure AI Foundry",
            "proxy": "Ollama (local)" if self._is_ollama() else f"API Proxy ({self.ANTHROPIC_BASE_URL})",
            "subscription": "Claude Code subscription",
        }
        return names.get(self.get_llm_provider(), f"Unknown ({self.get_llm_provider()})")


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
