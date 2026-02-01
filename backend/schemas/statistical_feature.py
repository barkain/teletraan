"""Pydantic schemas for statistical features API."""

from datetime import date as date_type
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StatisticalFeatureResponse(BaseModel):
    """Response schema for a single statistical feature."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    symbol: str
    feature_type: str
    value: float
    signal: str
    percentile: float | None = None
    calculation_date: date_type
    metadata: dict[str, Any] | None = Field(default=None, alias="metadata_json")


class StatisticalFeaturesListResponse(BaseModel):
    """Response schema for all features of a symbol."""

    symbol: str
    features: list[StatisticalFeatureResponse]
    calculation_date: date_type


class ActiveSignalResponse(BaseModel):
    """Response schema for an active trading signal."""

    symbol: str
    feature_type: str
    signal: str
    value: float
    strength: str = Field(description="Signal strength: 'strong', 'moderate', or 'weak'")


class ActiveSignalsResponse(BaseModel):
    """Response schema for active signals across the watchlist."""

    signals: list[ActiveSignalResponse]
    count: int
    as_of: datetime


class ComputeFeaturesRequest(BaseModel):
    """Request schema for triggering feature computation."""

    symbols: list[str] = Field(
        description="List of stock symbols to compute features for",
        examples=[["AAPL", "MSFT", "GOOGL"]],
    )


class ComputeFeaturesResponse(BaseModel):
    """Response schema for feature computation trigger."""

    status: str
    symbols: list[str]
    message: str | None = None
