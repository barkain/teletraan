"""Pydantic schemas for analysis report endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ReportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    elapsed_seconds: float | None = None
    market_regime: str | None = None
    top_sectors: list[str] = []
    discovery_summary: str | None = None
    insights_count: int = 0
    published_url: str | None = None


class ReportListResponse(BaseModel):
    items: list[ReportSummary]
    total: int


class ReportInsight(BaseModel):
    id: int
    insight_type: str | None = None
    action: str | None = None
    title: str
    thesis: str | None = None
    primary_symbol: str | None = None
    related_symbols: list[str] = []
    confidence: float | None = None
    time_horizon: str | None = None
    risk_factors: list[str] = []
    entry_zone: str | None = None
    target_price: str | None = None
    stop_loss: str | None = None
    invalidation_trigger: str | None = None
    supporting_evidence: dict | None = None
    created_at: datetime | None = None


class ReportDetail(ReportSummary):
    insights: list[ReportInsight] = []
    phases_completed: list[str] = []


class PublishResponse(BaseModel):
    published_url: str
    message: str
