from datetime import datetime
from pydantic import BaseModel, ConfigDict


class HoldingBase(BaseModel):
    symbol: str
    shares: float
    cost_basis: float
    notes: str | None = None


class HoldingCreate(HoldingBase):
    pass


class HoldingUpdate(BaseModel):
    shares: float | None = None
    cost_basis: float | None = None
    notes: str | None = None


class HoldingResponse(HoldingBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    portfolio_id: int
    current_price: float | None = None
    market_value: float | None = None
    gain_loss: float | None = None
    gain_loss_pct: float | None = None
    allocation_pct: float | None = None
    created_at: datetime
    updated_at: datetime | None = None


class PortfolioBase(BaseModel):
    name: str = "My Portfolio"
    description: str | None = None


class PortfolioCreate(PortfolioBase):
    pass


class PortfolioResponse(PortfolioBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    holdings: list[HoldingResponse] = []
    total_value: float | None = None
    total_cost: float | None = None
    total_gain_loss: float | None = None
    total_gain_loss_pct: float | None = None
    created_at: datetime
    updated_at: datetime | None = None


class PortfolioSummaryResponse(BaseModel):
    total_value: float
    total_cost: float
    total_gain_loss: float
    total_gain_loss_pct: float
    holdings_count: int
    top_holdings: list[HoldingResponse]


class AffectedHolding(BaseModel):
    symbol: str
    allocation_pct: float
    insight_ids: list[int]
    impact_direction: str  # bullish / bearish / neutral


class PortfolioImpactResponse(BaseModel):
    portfolio_value: float
    affected_holdings: list[AffectedHolding]
    overall_bullish_exposure: float
    overall_bearish_exposure: float
    insight_count: int
