"""Schemas for analysis endpoints."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# Technical Analysis Schemas
class IndicatorDetail(BaseModel):
    """Individual indicator result."""
    indicator: str
    value: float
    signal: str  # "bullish", "bearish", "neutral"
    strength: float = Field(ge=0.0, le=1.0)


class TechnicalAnalysisResponse(BaseModel):
    """Response schema for technical analysis endpoint."""
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    analyzed_at: datetime
    overall_signal: str  # "bullish", "bearish", "neutral"
    confidence: float = Field(ge=0.0, le=1.0)
    bullish_count: int
    bearish_count: int
    neutral_count: int
    indicators: list[IndicatorDetail]
    crossovers: list[dict[str, Any]] = []


# Pattern Detection Schemas
class PatternDetail(BaseModel):
    """Individual detected pattern."""
    pattern_type: str
    start_date: date | None
    end_date: date | None
    confidence: float = Field(ge=0.0, le=1.0)
    price_target: float | None
    stop_loss: float | None
    description: str
    supporting_data: dict[str, Any] = {}


class PatternResponse(BaseModel):
    """Response schema for pattern detection endpoint."""
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    analyzed_at: datetime
    total_patterns: int
    bullish_patterns: int
    bearish_patterns: int
    neutral_patterns: int
    overall_bias: str  # "bullish", "bearish", "neutral"
    confidence: float = Field(ge=0.0, le=1.0)
    patterns: list[PatternDetail]
    support_levels: list[dict[str, Any]] = []
    resistance_levels: list[dict[str, Any]] = []


# Anomaly Detection Schemas
class AnomalyDetail(BaseModel):
    """Individual detected anomaly."""
    anomaly_type: str
    detected_at: datetime
    severity: str  # "info", "warning", "alert"
    value: float
    expected_range: tuple[float, float]
    z_score: float
    description: str


class AnomalyResponse(BaseModel):
    """Response schema for anomaly detection endpoint."""
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    analyzed_at: datetime
    total_anomalies: int
    anomalies_by_severity: dict[str, int]
    anomalies: list[AnomalyDetail]


# Sector Analysis Schemas
class SectorMetricDetail(BaseModel):
    """Metrics for a single sector."""
    name: str
    daily_return: float
    weekly_return: float
    monthly_return: float
    quarterly_return: float
    ytd_return: float
    relative_strength: float
    momentum_score: float
    volatility: float
    volume_trend: str  # "increasing", "decreasing", "stable"


class RotationAnalysis(BaseModel):
    """Sector rotation analysis."""
    rotation_detected: bool
    rotation_type: str | None
    leading_sectors: list[dict[str, Any]]
    lagging_sectors: list[dict[str, Any]]
    signals: list[dict[str, Any]]
    cyclical_vs_defensive: dict[str, float]


class SectorInsight(BaseModel):
    """Individual sector insight."""
    type: str
    priority: str  # "high", "medium", "low"
    title: str
    description: str
    action: str
    sectors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    divergences: list[dict[str, Any]] = []


class SectorAnalysisResponse(BaseModel):
    """Response schema for sector analysis endpoint."""
    model_config = ConfigDict(from_attributes=True)

    timestamp: datetime
    market_phase: str
    phase_description: str
    expected_leaders: list[str]
    sector_metrics: dict[str, SectorMetricDetail]
    rotation_analysis: RotationAnalysis
    insights: list[SectorInsight]


# Analysis Run Schemas
class AnalysisRunRequest(BaseModel):
    """Request to trigger analysis."""
    symbols: list[str] | None = None  # None means all symbols


class AnalysisRunResponse(BaseModel):
    """Response after triggering analysis."""
    status: str
    message: str
    symbols: list[str] | str  # "all" or list of symbols
    started_at: datetime


# Analysis Summary Schemas
class AnalysisSummaryResponse(BaseModel):
    """Summary of latest analysis results."""
    model_config = ConfigDict(from_attributes=True)

    last_run: datetime | None
    stocks_analyzed: int
    patterns_detected: int
    anomalies_detected: int
    insights_generated: int
    patterns_by_type: dict[str, int]
    anomalies_by_severity: dict[str, int]
    insights_by_type: dict[str, int]
