"""Pydantic schemas for ThematicInsight and ThematicOutcome API responses."""

from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ThematicInsightResponse(BaseModel):
    """Response schema for a single thematic insight."""

    id: UUID = Field(description="Unique identifier")
    theme_name: str = Field(description="Descriptive name of the theme")
    category: str = Field(description="Theme category (e.g., ai_infrastructure)")
    theme_fingerprint: str = Field(description="Dedup fingerprint")
    direction: str = Field(description="Directional bias: bullish, bearish, or mixed")
    confidence: float = Field(description="Confidence in this theme (0.0-1.0)")
    thesis: str = Field(description="Investment thesis")
    counter_thesis: Optional[str] = Field(default=None, description="Primary risk to thesis")
    meta_narrative: Optional[str] = Field(default=None, description="Connecting narrative")
    primary_symbols: list[str] = Field(description="Best 3-6 tradeable symbols")
    affected_sectors: Optional[list[str]] = Field(default=None, description="Impacted sectors")
    supply_chain_links: Optional[list[str]] = Field(default=None, description="Supply chain linkages")
    catalyst_timeline: str = Field(description="When catalysts expected: near_term/medium_term/long_term")
    theme_interactions: Optional[list[dict[str, Any]]] = Field(default=None, description="Theme interactions")
    lifecycle_state: str = Field(description="Current lifecycle state")
    staleness_score: Optional[float] = Field(default=None, description="Staleness (0.0-1.0)")
    effective_confidence: Optional[float] = Field(default=None, description="Confidence * decay")
    run_count: int = Field(description="Times re-identified across runs")
    analysis_task_id: Optional[str] = Field(default=None, description="Source analysis task")
    created_at: datetime = Field(description="When first identified")
    updated_at: datetime = Field(description="Last updated")

    model_config = {"from_attributes": True}


class ThematicInsightListResponse(BaseModel):
    """Response schema for paginated list of thematic insights."""

    items: list[ThematicInsightResponse] = Field(description="List of thematic insights")
    total: int = Field(description="Total matching count")


class ThematicOutcomeResponse(BaseModel):
    """Response schema for a single thematic outcome."""

    id: UUID = Field(description="Unique identifier")
    thematic_insight_id: UUID = Field(description="ID of the tracked thematic insight")
    tracking_status: str = Field(description="Current tracking status")
    tracking_start_date: date = Field(description="Date tracking began")
    tracking_end_date: date = Field(description="Date tracking will/did end")
    predicted_direction: str = Field(description="Predicted direction")
    symbols_tracked: int = Field(description="Number of symbols in basket")
    basket_avg_return_pct: Optional[float] = Field(default=None, description="Basket average return %")
    direction_agreement_rate: Optional[float] = Field(default=None, description="% of symbols agreeing with direction")
    best_symbol_return_pct: Optional[float] = Field(default=None, description="Best performer return %")
    worst_symbol_return_pct: Optional[float] = Field(default=None, description="Worst performer return %")
    thesis_validated: Optional[bool] = Field(default=None, description="Whether thesis was validated")
    outcome_category: Optional[str] = Field(default=None, description="Outcome classification")
    composite_score: Optional[float] = Field(default=None, description="Weighted composite score")
    validation_notes: Optional[str] = Field(default=None, description="Validation notes")
    symbol_tracking: Optional[dict[str, Any]] = Field(default=None, description="Per-symbol tracking data")
    intermediate_checkpoints: Optional[dict[str, Any]] = Field(default=None, description="Checkpoint data")
    related_insight_outcome_ids: Optional[list[str]] = Field(default=None, description="Related InsightOutcome IDs")
    # Joined fields
    theme_name: Optional[str] = Field(default=None, description="Theme name from linked insight")
    category: Optional[str] = Field(default=None, description="Category from linked insight")
    days_remaining: Optional[int] = Field(default=None, description="Days remaining in tracking")

    model_config = {"from_attributes": True}


class ThematicOutcomeListResponse(BaseModel):
    """Response schema for paginated list of thematic outcomes."""

    items: list[ThematicOutcomeResponse] = Field(description="List of outcomes")
    total: int = Field(description="Total matching count")


class ThematicOutcomeSummaryResponse(BaseModel):
    """Response schema for aggregate thematic outcome statistics."""

    total_tracked: int = Field(description="Total thematic outcomes ever tracked")
    currently_tracking: int = Field(description="Currently active tracking")
    completed: int = Field(description="Completed tracking periods")
    success_rate: float = Field(description="Overall thesis validation rate (0.0-1.0)")
    avg_composite_score: float = Field(description="Average composite score for completed")
    avg_basket_return: float = Field(description="Average basket return for completed")
    avg_direction_agreement: float = Field(description="Average direction agreement rate")
    by_category: dict[str, dict[str, Any]] = Field(
        description="Stats broken down by category",
        default_factory=dict,
    )
    by_direction: dict[str, dict[str, Any]] = Field(
        description="Stats broken down by predicted direction",
        default_factory=dict,
    )


class ThematicTrackRecordResponse(BaseModel):
    """Response schema for thematic track record display."""

    total_themes: int = Field(description="Total themes tracked")
    validated_themes: int = Field(description="Themes with validated thesis")
    success_rate: float = Field(description="Thesis validation rate")
    avg_composite_score: float = Field(description="Average composite score")
    best_theme: Optional[str] = Field(default=None, description="Best performing theme name")
    worst_theme: Optional[str] = Field(default=None, description="Worst performing theme name")
    by_category: dict[str, dict[str, Any]] = Field(
        description="Track record by category",
        default_factory=dict,
    )


class CheckThematicOutcomesResponse(BaseModel):
    """Response schema for the thematic outcome check endpoint."""

    checked: int = Field(description="Number of outcomes checked")
    completed: int = Field(description="Number completed during this check")
    updated: int = Field(description="Number updated with new prices")
