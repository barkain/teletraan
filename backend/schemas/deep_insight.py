from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum

class InsightAction(str, Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"
    WATCH = "WATCH"

class InsightType(str, Enum):
    OPPORTUNITY = "opportunity"
    RISK = "risk"
    ROTATION = "rotation"
    MACRO = "macro"
    DIVERGENCE = "divergence"
    CORRELATION = "correlation"

class AnalystEvidence(BaseModel):
    analyst: str
    finding: str
    confidence: Optional[float] = None

class DeepInsightBase(BaseModel):
    insight_type: InsightType
    action: InsightAction
    title: str
    thesis: str
    primary_symbol: Optional[str] = None
    related_symbols: list[str] = Field(default_factory=list)
    supporting_evidence: list[AnalystEvidence] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    time_horizon: str
    risk_factors: list[str] = Field(default_factory=list)
    invalidation_trigger: Optional[str] = None
    historical_precedent: Optional[str] = None
    analysts_involved: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)

class DeepInsightCreate(DeepInsightBase):
    pass

class DeepInsightResponse(DeepInsightBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    # Parent insight linking (for follow-up insights derived from conversations)
    parent_insight_id: Optional[int] = None
    source_conversation_id: Optional[int] = None

    # Trading parameters (autonomous discovery)
    entry_zone: Optional[str] = None
    target_price: Optional[str] = None
    stop_loss: Optional[str] = None
    timeframe: Optional[str] = None
    discovery_context: Optional[dict] = None

    class Config:
        from_attributes = True

class DeepInsightListResponse(BaseModel):
    items: list[DeepInsightResponse]
    total: int
