"""Search-related Pydantic schemas."""

from pydantic import BaseModel, ConfigDict

from schemas.insight import InsightResponse
from schemas.stock import StockResponse


class StockSearchResult(StockResponse):
    """Stock search result with relevance score."""

    relevance_score: float = 0.0


class InsightSearchResult(InsightResponse):
    """Insight search result with relevance score."""

    relevance_score: float = 0.0


class GlobalSearchResponse(BaseModel):
    """Response for global search across stocks and insights."""

    model_config = ConfigDict(from_attributes=True)

    stocks: list[StockSearchResult]
    insights: list[InsightSearchResult]
    total: int
    query: str


class StockSearchResponse(BaseModel):
    """Response for stock-specific search."""

    model_config = ConfigDict(from_attributes=True)

    stocks: list[StockSearchResult]
    total: int
    query: str


class InsightSearchResponse(BaseModel):
    """Response for insight-specific search."""

    model_config = ConfigDict(from_attributes=True)

    insights: list[InsightSearchResult]
    total: int
    query: str


class SearchSuggestion(BaseModel):
    """A single search suggestion for autocomplete."""

    text: str
    type: str  # 'stock' or 'insight'
    symbol: str | None = None
    id: int | None = None


class SearchSuggestionsResponse(BaseModel):
    """Response for search suggestions."""

    suggestions: list[SearchSuggestion]
