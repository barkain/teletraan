"""Search API endpoints for stocks and insights."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from schemas.search import (
    GlobalSearchResponse,
    InsightSearchResponse,
    StockSearchResponse,
)
from services.search_service import SearchService

router = APIRouter(prefix="/search", tags=["search"])

search_service = SearchService()


@router.get("", response_model=GlobalSearchResponse)
async def global_search(
    q: str = Query(..., min_length=1, description="Search query"),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100, description="Maximum results to return"),
):
    """
    Search across stocks and insights.

    Performs a unified search across:
    - Stocks (by symbol or company name)
    - Insights (by title or description)

    Results are scored by relevance with exact matches ranked higher.
    """
    results = await search_service.global_search(db, q, limit)
    return results


@router.get("/stocks", response_model=StockSearchResponse)
async def search_stocks(
    q: str = Query(..., min_length=1, description="Search query"),
    db: AsyncSession = Depends(get_db),
    sector: str | None = Query(None, description="Filter by sector"),
    active_only: bool = Query(True, description="Only include active stocks"),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Search stocks with optional sector filter.

    Searches by:
    - Stock symbol (exact matches ranked highest)
    - Company name (partial matches)

    Results are ordered by relevance score.
    """
    results = await search_service.search_stocks(
        db, q, sector=sector, active_only=active_only, limit=limit
    )
    return StockSearchResponse(
        stocks=results["stocks"],
        total=results["total"],
        query=q,
    )


@router.get("/insights", response_model=InsightSearchResponse)
async def search_insights(
    q: str = Query(..., min_length=1, description="Search query"),
    db: AsyncSession = Depends(get_db),
    insight_type: str | None = Query(None, description="Filter by insight type"),
    severity: str | None = Query(None, description="Filter by severity level"),
    active_only: bool = Query(True, description="Only include active insights"),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Search insights with filters.

    Searches by:
    - Insight title
    - Insight description

    Can be filtered by type (pattern, anomaly, sector, technical, economic)
    and severity (info, warning, alert).
    """
    results = await search_service.search_insights(
        db,
        q,
        insight_type=insight_type,
        severity=severity,
        active_only=active_only,
        limit=limit,
    )
    return InsightSearchResponse(
        insights=results["insights"],
        total=results["total"],
        query=q,
    )


@router.get("/suggestions")
async def get_search_suggestions(
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(5, ge=1, le=10),
):
    """
    Get quick search suggestions for autocomplete.

    Returns a limited list of matching stock symbols and names
    for use in search autocomplete UI.
    """
    suggestions = await search_service.get_suggestions(db, q, limit)
    return {"suggestions": suggestions}
