"""Health check endpoint."""

from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import text

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
