"""Pydantic schemas for InsightResearchContext API responses."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ContextLoadLevel(str, Enum):
    """Levels of context detail for LLM consumption."""

    SUMMARY = "summary"  # ~500 tokens - analysts_summary + key_data_points
    STANDARD = "standard"  # ~2,000 tokens - summaries + synthesis_summary
    DETAILED = "detailed"  # ~4,000 tokens - all reports condensed
    FULL = "full"  # ~6,000 tokens - complete raw context


class ResearchContextSummary(BaseModel):
    """Condensed research context for context window optimization."""

    id: int
    deep_insight_id: int
    analysts_summary: str | None = None
    key_data_points: list[str] = Field(default_factory=list)
    synthesis_summary: dict[str, Any] | None = None
    estimated_token_count: int | None = None
    successful_analysts: list[str] = Field(default_factory=list)

    class Config:
        from_attributes = True


class ResearchContextBase(BaseModel):
    """Base schema for research context."""

    schema_version: str = "1.0"

    # Analyst reports
    technical_report: dict[str, Any] | None = None
    macro_report: dict[str, Any] | None = None
    sector_report: dict[str, Any] | None = None
    risk_report: dict[str, Any] | None = None
    correlation_report: dict[str, Any] | None = None

    # Synthesis
    synthesis_raw_response: str | None = None
    synthesis_summary: dict[str, Any] | None = None

    # Market context
    symbols_analyzed: list[str] = Field(default_factory=list)
    market_summary_snapshot: dict[str, Any] | None = None
    sector_performance_snapshot: dict[str, Any] | None = None
    economic_indicators_snapshot: list[dict[str, Any]] = Field(default_factory=list)

    # Summaries
    analysts_summary: str | None = None
    key_data_points: list[str] = Field(default_factory=list)
    estimated_token_count: int | None = None

    # Metadata
    analysis_duration_seconds: float | None = None
    successful_analysts: list[str] = Field(default_factory=list)
    analyst_errors: dict[str, Any] | None = None


class ResearchContextCreate(ResearchContextBase):
    """Schema for creating a new research context."""

    deep_insight_id: int


class ResearchContextResponse(ResearchContextBase):
    """Full research context response."""

    id: int
    deep_insight_id: int
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class ResearchContextWithInsight(ResearchContextResponse):
    """Research context with embedded insight summary."""

    insight_title: str | None = None
    insight_action: str | None = None
    insight_type: str | None = None


class TieredContextResponse(BaseModel):
    """Response for tiered context loading."""

    load_level: ContextLoadLevel
    deep_insight_id: int
    token_count: int | None = None

    # Always included
    analysts_summary: str | None = None
    key_data_points: list[str] = Field(default_factory=list)

    # Included at STANDARD level and above
    synthesis_summary: dict[str, Any] | None = None
    symbols_analyzed: list[str] = Field(default_factory=list)

    # Included at DETAILED level and above
    technical_report: dict[str, Any] | None = None
    macro_report: dict[str, Any] | None = None
    sector_report: dict[str, Any] | None = None
    risk_report: dict[str, Any] | None = None
    correlation_report: dict[str, Any] | None = None

    # Included only at FULL level
    synthesis_raw_response: str | None = None
    market_summary_snapshot: dict[str, Any] | None = None
    sector_performance_snapshot: dict[str, Any] | None = None
    economic_indicators_snapshot: list[dict[str, Any]] = Field(default_factory=list)

    class Config:
        from_attributes = True
