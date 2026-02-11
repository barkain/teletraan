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

    # API Keys (optional)
    # Note: ANTHROPIC_API_KEY is no longer needed - the app uses claude-agent-sdk
    # which leverages the user's existing Claude Code subscription
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


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
