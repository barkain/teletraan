"""Health check endpoints."""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from analysis.price_coverage import price_coverage_report
from api.deps import DbSession
from schemas.health import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check(db: DbSession) -> HealthResponse:
    """Return health status of the API including database connectivity."""
    # Check database connectivity
    db_status = "connected"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "disconnected"

    return HealthResponse(
        status="healthy",
        version="1.0.0",
        database=db_status,
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/health/price-coverage")
async def price_coverage(db: DbSession) -> dict[str, Any]:
    """Report how current the local ``price_history`` table is.

    The price ETL fell three and a half months behind without anything
    surfacing it: read-time consumers each quietly compensated (the context
    builder re-quoted stale symbols live, the eval harness topped up from
    yfinance), so a dead feed presented as ordinary slowness.  This endpoint is
    where an operator -- or a monitor -- can see it directly.

    Returns the full coverage report; ``is_healthy`` is false once a tenth of
    the tracked universe is stale or unpriced.
    """
    return await price_coverage_report(db)
