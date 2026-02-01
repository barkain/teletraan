"""Pydantic schemas for knowledge API endpoints.

This module defines request/response schemas for the knowledge API
including patterns, themes, and track record endpoints.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class KnowledgePatternResponse(BaseModel):
    """Response schema for a validated knowledge pattern."""

    id: UUID
    pattern_name: str = Field(..., description="Human-readable pattern name")
    pattern_type: str = Field(..., description="Classification of pattern type")
    description: str = Field(..., description="Detailed pattern explanation")
    trigger_conditions: dict[str, Any] = Field(
        ..., description="Conditions that activate the pattern"
    )
    expected_outcome: str = Field(..., description="Expected behavior when triggered")
    success_rate: float = Field(
        ..., ge=0.0, le=1.0, description="Validated accuracy (0.0-1.0)"
    )
    occurrences: int = Field(..., ge=0, description="Total times pattern was identified")
    successful_outcomes: int = Field(
        ..., ge=0, description="Times pattern played out correctly"
    )
    avg_return_when_triggered: float | None = Field(
        None, description="Average return when pattern triggers"
    )
    is_active: bool = Field(..., description="Whether pattern is active for detection")
    last_triggered_at: datetime | None = Field(
        None, description="When pattern was last detected"
    )

    model_config = {"from_attributes": True}


class KnowledgePatternListResponse(BaseModel):
    """Response schema for a list of knowledge patterns."""

    items: list[KnowledgePatternResponse]
    total: int = Field(..., ge=0, description="Total count of matching patterns")


class ConversationThemeResponse(BaseModel):
    """Response schema for a conversation theme."""

    id: UUID
    theme_name: str = Field(..., description="Concise theme name")
    theme_type: str = Field(..., description="Classification of theme type")
    description: str = Field(..., description="Theme explanation and implications")
    keywords: list[str] = Field(
        default_factory=list, description="Related terms for matching"
    )
    related_symbols: list[str] = Field(
        default_factory=list, description="Associated ticker symbols"
    )
    related_sectors: list[str] = Field(
        default_factory=list, description="Associated sector names"
    )
    mention_count: int = Field(..., ge=1, description="Total times theme was discussed")
    current_relevance: float = Field(
        ..., ge=0.0, le=1.0, description="Relevance score with time decay"
    )
    first_mentioned_at: datetime = Field(..., description="When theme was first identified")
    last_mentioned_at: datetime = Field(..., description="Most recent mention")

    model_config = {"from_attributes": True}


class ConversationThemeListResponse(BaseModel):
    """Response schema for a list of conversation themes."""

    items: list[ConversationThemeResponse]
    total: int = Field(..., ge=0, description="Total count of matching themes")


class TypeBreakdown(BaseModel):
    """Breakdown statistics for a specific insight or action type."""

    total: int = Field(..., ge=0, description="Total insights of this type")
    successful: int = Field(..., ge=0, description="Successful validations")
    success_rate: float = Field(..., ge=0.0, le=1.0, description="Success rate for type")
    avg_return: float | None = Field(None, description="Average return for this type")


class TrackRecordResponse(BaseModel):
    """Response schema for historical track record."""

    total_insights: int = Field(..., ge=0, description="Total validated insights")
    successful: int = Field(..., ge=0, description="Successfully validated insights")
    success_rate: float = Field(..., ge=0.0, le=1.0, description="Overall success rate")
    by_type: dict[str, TypeBreakdown] = Field(
        default_factory=dict, description="Breakdown by insight type"
    )
    by_action: dict[str, TypeBreakdown] = Field(
        default_factory=dict, description="Breakdown by action type"
    )
    avg_return_successful: float = Field(
        ..., description="Average return for successful insights"
    )
    avg_return_failed: float = Field(
        ..., description="Average return for failed insights"
    )


class MatchingConditions(BaseModel):
    """Query parameters for pattern matching endpoint."""

    symbols: list[str] = Field(default_factory=list, description="Symbols to check")
    rsi: float | None = Field(None, ge=0, le=100, description="Current RSI value")
    vix: float | None = Field(None, ge=0, description="Current VIX level")
    volume_surge_pct: float | None = Field(None, description="Volume surge percentage")
    sector_momentum: float | None = Field(None, description="Sector momentum score")
