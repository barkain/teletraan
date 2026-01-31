from datetime import date, datetime
from pydantic import BaseModel, ConfigDict


class StockBase(BaseModel):
    symbol: str
    name: str
    sector: str | None = None
    industry: str | None = None


class StockCreate(StockBase):
    pass


class StockResponse(StockBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    market_cap: float | None = None
    is_active: bool
    created_at: datetime


class StockListResponse(BaseModel):
    stocks: list[StockResponse]
    total: int


class PriceHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    adjusted_close: float | None = None
