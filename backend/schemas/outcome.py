"""Pydantic schemas for InsightOutcome API responses."""

from datetime import date
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class InsightOutcomeResponse(BaseModel):
    """Response schema for a single insight outcome."""

    id: UUID = Field(description="Unique identifier for the outcome")
    insight_id: int = Field(description="ID of the tracked DeepInsight")
    tracking_status: str = Field(description="Current tracking status (PENDING, TRACKING, COMPLETED, INVALIDATED)")
    tracking_start_date: date = Field(description="Date tracking began")
    tracking_end_date: date = Field(description="Date tracking will/did end")
    initial_price: float = Field(description="Price when insight was generated")
    current_price: Optional[float] = Field(default=None, description="Latest tracked price")
    final_price: Optional[float] = Field(default=None, description="Price at tracking end")
    actual_return_pct: Optional[float] = Field(default=None, description="Actual return percentage")
    predicted_direction: str = Field(description="Predicted direction: bullish, bearish, or neutral")
    thesis_validated: Optional[bool] = Field(default=None, description="Whether the thesis was validated")
    outcome_category: Optional[str] = Field(default=None, description="Outcome category classification")
    validation_notes: Optional[str] = Field(default=None, description="Notes on validation result")
    days_remaining: Optional[int] = Field(default=None, description="Days remaining in tracking period")

    model_config = {"from_attributes": True}


class OutcomeSummaryResponse(BaseModel):
    """Response schema for aggregate outcome statistics."""

    total_tracked: int = Field(description="Total number of outcomes ever tracked")
    currently_tracking: int = Field(description="Number of outcomes currently being tracked")
    completed: int = Field(description="Number of completed tracking periods")
    success_rate: float = Field(description="Overall thesis validation rate (0.0-1.0)")
    avg_return_when_correct: float = Field(description="Average return when thesis was validated")
    avg_return_when_wrong: float = Field(description="Average return when thesis was not validated")
    by_direction: dict[str, dict] = Field(
        description="Statistics broken down by predicted direction",
        default_factory=dict,
    )
    by_category: dict[str, int] = Field(
        description="Count of outcomes by category",
        default_factory=dict,
    )


class StartTrackingRequest(BaseModel):
    """Request schema for starting insight tracking."""

    insight_id: int = Field(description="ID of the DeepInsight to track")
    symbol: str = Field(description="Stock symbol to track (e.g., 'AAPL')")
    predicted_direction: str = Field(
        description="Predicted price direction: 'bullish', 'bearish', or 'neutral'"
    )
    tracking_days: int = Field(
        default=20,
        ge=1,
        le=252,
        description="Number of trading days to track (default 20, max 252)",
    )


class CheckOutcomesResponse(BaseModel):
    """Response schema for the outcome check endpoint."""

    checked: int = Field(description="Number of outcomes checked")
    completed: int = Field(description="Number of outcomes that completed during this check")
    updated: int = Field(description="Number of outcomes updated with new prices")
