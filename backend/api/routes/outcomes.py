"""Outcome tracking API routes for insight thesis validation."""

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from analysis.outcome_tracker import InsightOutcomeTracker
from models.insight_outcome import InsightOutcome, TrackingStatus
from schemas.outcome import (
    CheckOutcomesResponse,
    InsightOutcomeResponse,
    OutcomeSummaryResponse,
    StartTrackingRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/outcomes", tags=["outcomes"])


def _compute_days_remaining(outcome: InsightOutcome) -> Optional[int]:
    """Calculate days remaining in tracking period."""
    if outcome.tracking_status != TrackingStatus.TRACKING.value:
        return None
    today = date.today()
    if today >= outcome.tracking_end_date:
        return 0
    return (outcome.tracking_end_date - today).days


def _outcome_to_response(outcome: InsightOutcome) -> InsightOutcomeResponse:
    """Convert InsightOutcome model to response schema."""
    return InsightOutcomeResponse(
        id=outcome.id,
        insight_id=outcome.insight_id,
        tracking_status=outcome.tracking_status,
        tracking_start_date=outcome.tracking_start_date,
        tracking_end_date=outcome.tracking_end_date,
        initial_price=outcome.initial_price,
        current_price=outcome.current_price,
        final_price=outcome.final_price,
        actual_return_pct=outcome.actual_return_pct,
        predicted_direction=outcome.predicted_direction,
        thesis_validated=outcome.thesis_validated,
        outcome_category=outcome.outcome_category,
        validation_notes=outcome.validation_notes,
        days_remaining=_compute_days_remaining(outcome),
    )


@router.get("/summary", response_model=OutcomeSummaryResponse)
async def get_outcome_summary(
    db: AsyncSession = Depends(get_db),
    lookback_days: int = Query(default=90, ge=1, le=365),
) -> OutcomeSummaryResponse:
    """Get aggregate statistics for insight outcomes.

    Args:
        db: Database session
        lookback_days: Number of days to look back for statistics (default 90)

    Returns:
        Aggregate statistics including success rates and category breakdowns
    """
    tracker = InsightOutcomeTracker(db)
    summary = await tracker.get_tracking_summary()

    # Get all completed outcomes for detailed stats
    completed_query = select(InsightOutcome).where(
        InsightOutcome.tracking_status == TrackingStatus.COMPLETED.value
    )
    result = await db.execute(completed_query)
    completed = result.scalars().all()

    # Calculate average returns for correct vs wrong predictions
    correct_returns = [
        o.actual_return_pct for o in completed
        if o.thesis_validated and o.actual_return_pct is not None
    ]
    wrong_returns = [
        o.actual_return_pct for o in completed
        if not o.thesis_validated and o.actual_return_pct is not None
    ]

    avg_return_correct = sum(correct_returns) / len(correct_returns) if correct_returns else 0.0
    avg_return_wrong = sum(wrong_returns) / len(wrong_returns) if wrong_returns else 0.0

    # Count by category
    by_category: dict[str, int] = {}
    for o in completed:
        if o.outcome_category:
            by_category[o.outcome_category] = by_category.get(o.outcome_category, 0) + 1

    return OutcomeSummaryResponse(
        total_tracked=sum(summary["status_counts"].values()),
        currently_tracking=summary["status_counts"].get(TrackingStatus.TRACKING.value, 0),
        completed=summary["total_completed"],
        success_rate=summary["success_rate"],
        avg_return_when_correct=avg_return_correct,
        avg_return_when_wrong=avg_return_wrong,
        by_direction=summary["direction_stats"],
        by_category=by_category,
    )


@router.get("/{outcome_id}", response_model=InsightOutcomeResponse)
async def get_outcome(
    outcome_id: str,
    db: AsyncSession = Depends(get_db),
) -> InsightOutcomeResponse:
    """Get a specific insight outcome by ID.

    Args:
        outcome_id: UUID of the outcome to retrieve
        db: Database session

    Returns:
        The requested InsightOutcome

    Raises:
        HTTPException: If outcome not found
    """
    result = await db.execute(
        select(InsightOutcome).where(InsightOutcome.id == outcome_id)
    )
    outcome = result.scalar_one_or_none()
    if not outcome:
        raise HTTPException(status_code=404, detail="Outcome not found")
    return _outcome_to_response(outcome)


@router.get("/insight/{insight_id}", response_model=InsightOutcomeResponse)
async def get_outcome_for_insight(
    insight_id: int,
    db: AsyncSession = Depends(get_db),
) -> InsightOutcomeResponse:
    """Get the outcome for a specific insight.

    Args:
        insight_id: ID of the DeepInsight
        db: Database session

    Returns:
        The InsightOutcome for the specified insight

    Raises:
        HTTPException: If no outcome exists for the insight
    """
    result = await db.execute(
        select(InsightOutcome).where(InsightOutcome.insight_id == insight_id)
    )
    outcome = result.scalar_one_or_none()
    if not outcome:
        raise HTTPException(status_code=404, detail="No outcome found for this insight")
    return _outcome_to_response(outcome)


@router.get("", response_model=list[InsightOutcomeResponse])
async def list_outcomes(
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = Query(default=None, description="Filter by status: 'tracking' or 'completed'"),
    validated: Optional[bool] = Query(default=None, description="Filter by validation result"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[InsightOutcomeResponse]:
    """List insight outcomes with optional filtering.

    Args:
        db: Database session
        status: Filter by tracking status ('tracking' or 'completed')
        validated: Filter by whether thesis was validated
        limit: Maximum number of results (default 50)
        offset: Pagination offset

    Returns:
        List of InsightOutcome responses
    """
    query = select(InsightOutcome).order_by(InsightOutcome.created_at.desc())

    # Apply status filter
    if status:
        status_upper = status.upper()
        if status_upper == "TRACKING":
            query = query.where(InsightOutcome.tracking_status == TrackingStatus.TRACKING.value)
        elif status_upper == "COMPLETED":
            query = query.where(InsightOutcome.tracking_status == TrackingStatus.COMPLETED.value)

    # Apply validated filter
    if validated is not None:
        query = query.where(InsightOutcome.thesis_validated == validated)

    # Apply pagination
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    outcomes = result.scalars().all()

    return [_outcome_to_response(o) for o in outcomes]


@router.post("/start", response_model=InsightOutcomeResponse)
async def start_tracking(
    request: StartTrackingRequest,
    db: AsyncSession = Depends(get_db),
) -> InsightOutcomeResponse:
    """Start tracking an insight's prediction outcome.

    Args:
        request: Tracking configuration including insight_id, symbol, and direction
        db: Database session

    Returns:
        The created InsightOutcome

    Raises:
        HTTPException: If insight not found or tracking fails
    """
    tracker = InsightOutcomeTracker(db)

    try:
        outcome = await tracker.start_tracking(
            insight_id=request.insight_id,
            symbol=request.symbol,
            predicted_direction=request.predicted_direction,
            tracking_days=request.tracking_days,
        )
        logger.info(f"Started tracking insight {request.insight_id} for {request.symbol}")
        return _outcome_to_response(outcome)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to start tracking: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start tracking: {str(e)}")


@router.post("/check", response_model=CheckOutcomesResponse)
async def check_outcomes(
    db: AsyncSession = Depends(get_db),
) -> CheckOutcomesResponse:
    """Trigger a check of all active outcome tracking.

    This endpoint is designed to be called periodically by a scheduler.
    It updates current prices for all tracking outcomes and evaluates
    any that have reached their tracking end date.

    Args:
        db: Database session

    Returns:
        Statistics about the check operation
    """
    tracker = InsightOutcomeTracker(db)

    # Count outcomes before check
    tracking_query = select(func.count()).select_from(
        select(InsightOutcome)
        .where(InsightOutcome.tracking_status == TrackingStatus.TRACKING.value)
        .subquery()
    )
    tracking_before = await db.scalar(tracking_query) or 0

    # Run the check
    updated_outcomes = await tracker.check_outcomes()

    # Count how many completed
    completed_count = sum(
        1 for o in updated_outcomes
        if o.tracking_status == TrackingStatus.COMPLETED.value
    )

    # Update pattern success rates for newly completed outcomes
    if completed_count > 0:
        await tracker.update_pattern_success_rates()

    logger.info(
        f"Outcome check complete: {len(updated_outcomes)} updated, "
        f"{completed_count} completed"
    )

    return CheckOutcomesResponse(
        checked=tracking_before,
        completed=completed_count,
        updated=len(updated_outcomes),
    )
