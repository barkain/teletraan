"""Schemas for the v2 alpha engine."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AnalysisRunSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_type: str
    status: str
    market_date: date
    market_regime: str | None = None
    market_confidence: float | None = None
    universe_size: int
    symbols_scanned: int
    ideas_persisted: int
    portfolio_symbols: list[str] | None = None
    analysis_metadata: dict[str, Any] | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class MarketSnapshotSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    analysis_run_id: str
    market_date: date
    regime_name: str | None = None
    regime_confidence: float | None = None
    benchmark_snapshot: dict[str, Any] | None = None
    sector_snapshot: dict[str, Any] | None = None
    macro_snapshot: dict[str, Any] | None = None
    breadth_snapshot: dict[str, Any] | None = None
    portfolio_snapshot: dict[str, Any] | None = None
    universe_snapshot: dict[str, Any] | None = None
    notes: str | None = None


class SecuritySignalSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    analysis_run_id: str
    symbol: str
    sector: str | None = None
    signal_version: str
    overall_score: float
    technical_score: float
    fundamental_score: float
    valuation_score: float
    flow_score: float
    sentiment_score: float
    macro_score: float
    catalyst_score: float
    liquidity_score: float
    risk_score: float
    data_completeness: float = Field(ge=0.0, le=1.0)
    subscores: dict[str, Any] | None = None
    evidence: dict[str, Any] | None = None


class CandidateIdeaSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    analysis_run_id: str
    symbol: str
    rank: int
    thesis_type: str
    overall_score: float
    confidence: float = Field(ge=0.0, le=1.0)
    expected_horizon_days: int | None = None
    bull_case: str | None = None
    bear_case: str | None = None
    key_drivers: list[str] | None = None
    setup_trigger: str | None = None
    invalidations: list[str] | None = None
    portfolio_relevance: str | None = None
    is_portfolio_holding: bool
    target_price: float | None = None
    stop_price: float | None = None
    evidence: dict[str, Any] | None = None


class InsightOutcomeSchema(BaseModel):
    """Normalized outcome label used by the v2 feedback loop."""

    model_config = ConfigDict(from_attributes=True)

    symbol: str
    horizon_days: int
    entry_price: float
    forward_return_pct: float | None = None
    benchmark_relative_return_pct: float | None = None
    max_favorable_excursion_pct: float | None = None
    max_adverse_excursion_pct: float | None = None
    hit_status: str | None = None
    time_to_hit_days: int | None = None
    time_to_invalid_days: int | None = None
    notes: str | None = None


__all__ = [
    "AnalysisRunSchema",
    "MarketSnapshotSchema",
    "SecuritySignalSchema",
    "CandidateIdeaSchema",
    "InsightOutcomeSchema",
]
