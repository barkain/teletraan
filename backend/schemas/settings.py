"""Pydantic schemas for settings API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class SettingBase(BaseModel):
    """Base schema for settings."""

    key: str
    value: Any  # Will be JSON serialized/deserialized


class SettingUpdate(BaseModel):
    """Schema for updating a setting."""

    value: Any


class SettingResponse(BaseModel):
    """Schema for a single setting response."""

    model_config = ConfigDict(from_attributes=True)

    key: str
    value: Any
    updated_at: datetime


class AllSettingsResponse(BaseModel):
    """Schema for all settings response."""

    settings: dict[str, Any]


class SettingsResetResponse(BaseModel):
    """Schema for settings reset response."""

    success: bool
    message: str
    settings: dict[str, Any]


class WatchlistSettings(BaseModel):
    """Schema for watchlist settings response."""

    symbols: list[str]
    last_refresh: datetime | None = None


class WatchlistUpdate(BaseModel):
    """Schema for updating watchlist settings."""

    symbols: list[str]

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, v: list[str]) -> list[str]:
        """Validate and normalize symbols."""
        if not v:
            raise ValueError("symbols list cannot be empty")
        validated = []
        for symbol in v:
            if not isinstance(symbol, str) or not symbol.strip():
                raise ValueError("each symbol must be a non-empty string")
            validated.append(symbol.strip().upper())
        return validated


# ============================================
# LLM Provider Settings
# ============================================

class LLMProviderConfig(BaseModel):
    """Schema for LLM provider configuration (PUT request body)."""

    llm_provider: str | None = None  # auto | anthropic_api | bedrock | vertex | azure | proxy | ollama | subscription
    anthropic_api_key: str | None = None
    anthropic_auth_token: str | None = None
    anthropic_base_url: str | None = None
    api_timeout_ms: int | None = None
    anthropic_model: str | None = None
    aws_region: str | None = None
    vertex_project: str | None = None
    vertex_region: str | None = None


class LLMProviderStatus(BaseModel):
    """Schema for GET /settings/llm response."""

    active_provider: str  # The resolved provider name
    active_provider_display: str  # Human-readable display name
    configured_provider: str  # The raw LLM_PROVIDER value (may be "auto")
    model: str
    env_override: bool  # True if .env values are taking priority
    # Masked credential fields (only last 4 chars shown)
    anthropic_api_key: str | None = None
    anthropic_auth_token: str | None = None
    anthropic_base_url: str | None = None
    api_timeout_ms: int | None = None
    aws_region: str | None = None
    vertex_project: str | None = None
    vertex_region: str | None = None


class LLMTestResult(BaseModel):
    """Schema for POST /settings/llm/test response."""

    success: bool
    message: str
    provider: str
    model: str
    response_preview: str | None = None
