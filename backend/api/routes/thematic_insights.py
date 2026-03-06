"""API routes for thematic insights and their outcome tracking."""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from analysis.thematic_outcome_tracker import ThematicOutcomeTracker
from models.insight_outcome import TrackingStatus
from models.thematic_insight import ThematicInsight
from models.thematic_outcome import ThematicOutcome
from schemas.thematic_insight import (
    CheckThematicOutcomesResponse,
    ThematicInsightListResponse,
    ThematicInsightResponse,
    ThematicOutcomeListResponse,
    ThematicOutcomeResponse,
    ThematicOutcomeSummaryResponse,
    ThematicTrackRecordResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _insight_to_response(insight: ThematicInsight) -> ThematicInsightResponse:
    """Convert a ThematicInsight model to response schema."""
    return ThematicInsightResponse.model_validate(insight)


def _outcome_to_response(
    outcome: ThematicOutcome,
    insight: ThematicInsight | None = None,
) -> ThematicOutcomeResponse:
    """Convert a ThematicOutcome model to response schema."""
    from datetime import date as date_type

    days_remaining = None
    if outcome.tracking_status == TrackingStatus.TRACKING.value:
        delta = outcome.tracking_end_date - date_type.today()
        days_remaining = max(0, delta.days)

    return ThematicOutcomeResponse(
        id=outcome.id,
        thematic_insight_id=outcome.thematic_insight_id,
        tracking_status=outcome.tracking_status,
        tracking_start_date=outcome.tracking_start_date,
        tracking_end_date=outcome.tracking_end_date,
        predicted_direction=outcome.predicted_direction,
        symbols_tracked=outcome.symbols_tracked,
        basket_avg_return_pct=outcome.basket_avg_return_pct,
        direction_agreement_rate=outcome.direction_agreement_rate,
        best_symbol_return_pct=outcome.best_symbol_return_pct,
        worst_symbol_return_pct=outcome.worst_symbol_return_pct,
        thesis_validated=outcome.thesis_validated,
        outcome_category=outcome.outcome_category,
        composite_score=outcome.composite_score,
        validation_notes=outcome.validation_notes,
        symbol_tracking=outcome.symbol_tracking,
        intermediate_checkpoints=outcome.intermediate_checkpoints,
        related_insight_outcome_ids=outcome.related_insight_outcome_ids,
        theme_name=insight.theme_name if insight else None,
        category=insight.category if insight else None,
        days_remaining=days_remaining,
    )


# ---- Thematic Insight endpoints ----


@router.get("", response_model=ThematicInsightListResponse)
async def list_thematic_insights(
    db: AsyncSession = Depends(get_db),
    category: Optional[str] = Query(default=None),
    lifecycle_state: Optional[str] = Query(default=None),
    direction: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ThematicInsightListResponse:
    """List thematic insights with optional filters."""
    base_query = select(ThematicInsight)

    if category:
        base_query = base_query.where(ThematicInsight.category == category)
    if lifecycle_state:
        base_query = base_query.where(ThematicInsight.lifecycle_state == lifecycle_state)
    if direction:
        base_query = base_query.where(ThematicInsight.direction == direction)

    count_query = select(func.count()).select_from(base_query.subquery())
    total = await db.scalar(count_query) or 0

    data_query = (
        base_query
        .order_by(ThematicInsight.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(data_query)
    insights = result.scalars().all()

    return ThematicInsightListResponse(
        items=[_insight_to_response(i) for i in insights],
        total=total,
    )


@router.get("/track-record", response_model=ThematicTrackRecordResponse)
async def get_thematic_track_record(
    db: AsyncSession = Depends(get_db),
    lookback_days: int = Query(default=180, ge=1, le=730),
) -> ThematicTrackRecordResponse:
    """Get thematic track record for confidence display."""
    # Get completed outcomes with insights
    completed_query = (
        select(ThematicOutcome, ThematicInsight)
        .join(ThematicInsight, ThematicOutcome.thematic_insight_id == ThematicInsight.id)
        .where(ThematicOutcome.tracking_status == TrackingStatus.COMPLETED.value)
    )
    result = await db.execute(completed_query)
    rows = result.all()

    total = len(rows)
    validated = sum(1 for r in rows if r[0].thesis_validated)
    success_rate = validated / total if total > 0 else 0.0

    composites = [r[0].composite_score for r in rows if r[0].composite_score is not None]
    avg_composite = sum(composites) / len(composites) if composites else 0.0

    # Find best/worst
    best_theme = None
    worst_theme = None
    if rows:
        best_row = max(rows, key=lambda r: r[0].composite_score or 0)
        worst_row = min(rows, key=lambda r: r[0].composite_score or 1)
        best_theme = best_row[1].theme_name
        worst_theme = worst_row[1].theme_name

    # By category
    by_category: dict = {}
    for outcome, insight in rows:
        cat = insight.category
        if cat not in by_category:
            by_category[cat] = {"total": 0, "validated": 0, "composites": []}
        by_category[cat]["total"] += 1
        if outcome.thesis_validated:
            by_category[cat]["validated"] += 1
        if outcome.composite_score is not None:
            by_category[cat]["composites"].append(outcome.composite_score)

    by_category_clean = {}
    for cat, data in by_category.items():
        comps = data["composites"]
        by_category_clean[cat] = {
            "total": data["total"],
            "validated": data["validated"],
            "success_rate": round(data["validated"] / data["total"], 4) if data["total"] > 0 else 0.0,
            "avg_composite": round(sum(comps) / len(comps), 4) if comps else 0.0,
        }

    return ThematicTrackRecordResponse(
        total_themes=total,
        validated_themes=validated,
        success_rate=round(success_rate, 4),
        avg_composite_score=round(avg_composite, 4),
        best_theme=best_theme,
        worst_theme=worst_theme,
        by_category=by_category_clean,
    )


@router.get("/outcomes/summary", response_model=ThematicOutcomeSummaryResponse)
async def get_thematic_outcome_summary(
    db: AsyncSession = Depends(get_db),
) -> ThematicOutcomeSummaryResponse:
    """Get aggregate thematic outcome statistics."""
    tracker = ThematicOutcomeTracker(db)
    summary = await tracker.get_tracking_summary()

    # Build by_category and by_direction breakdowns
    completed_query = (
        select(ThematicOutcome, ThematicInsight)
        .join(ThematicInsight, ThematicOutcome.thematic_insight_id == ThematicInsight.id)
        .where(ThematicOutcome.tracking_status == TrackingStatus.COMPLETED.value)
    )
    result = await db.execute(completed_query)
    rows = result.all()

    by_category: dict = {}
    by_direction: dict = {}
    for outcome, insight in rows:
        # By category
        cat = insight.category
        if cat not in by_category:
            by_category[cat] = {"total": 0, "validated": 0}
        by_category[cat]["total"] += 1
        if outcome.thesis_validated:
            by_category[cat]["validated"] += 1

        # By direction
        d = outcome.predicted_direction
        if d not in by_direction:
            by_direction[d] = {"total": 0, "validated": 0, "returns": []}
        by_direction[d]["total"] += 1
        if outcome.thesis_validated:
            by_direction[d]["validated"] += 1
        if outcome.basket_avg_return_pct is not None:
            by_direction[d]["returns"].append(outcome.basket_avg_return_pct)

    by_direction_clean = {}
    for d, data in by_direction.items():
        rets = data["returns"]
        by_direction_clean[d] = {
            "total": data["total"],
            "validated": data["validated"],
            "avg_return": round(sum(rets) / len(rets), 4) if rets else 0.0,
        }

    return ThematicOutcomeSummaryResponse(
        total_tracked=summary["total_tracked"],
        currently_tracking=summary["currently_tracking"],
        completed=summary["completed"],
        success_rate=summary["success_rate"],
        avg_composite_score=summary["avg_composite_score"],
        avg_basket_return=summary["avg_basket_return"],
        avg_direction_agreement=summary["avg_direction_agreement"],
        by_category=by_category,
        by_direction=by_direction_clean,
    )


@router.get("/outcomes", response_model=ThematicOutcomeListResponse)
async def list_thematic_outcomes(
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = Query(default=None),
    validated: Optional[bool] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ThematicOutcomeListResponse:
    """List thematic outcomes with optional filters."""
    base_query = select(ThematicOutcome)

    if status:
        base_query = base_query.where(ThematicOutcome.tracking_status == status)
    if validated is not None:
        base_query = base_query.where(ThematicOutcome.thesis_validated == validated)

    count_query = select(func.count()).select_from(base_query.subquery())
    total = await db.scalar(count_query) or 0

    data_query = (
        base_query
        .order_by(ThematicOutcome.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(data_query)
    outcomes = result.scalars().all()

    items = []
    for outcome in outcomes:
        insight = await db.get(ThematicInsight, outcome.thematic_insight_id)
        items.append(_outcome_to_response(outcome, insight))

    return ThematicOutcomeListResponse(items=items, total=total)


@router.post("/outcomes/check", response_model=CheckThematicOutcomesResponse)
async def check_thematic_outcomes(
    db: AsyncSession = Depends(get_db),
) -> CheckThematicOutcomesResponse:
    """Trigger check of all active thematic outcome tracking."""
    tracker = ThematicOutcomeTracker(db)
    updated = await tracker.check_outcomes()

    completed = sum(
        1 for o in updated
        if o.tracking_status == TrackingStatus.COMPLETED.value
    )

    return CheckThematicOutcomesResponse(
        checked=len(updated),
        completed=completed,
        updated=len(updated),
    )


@router.get("/{insight_id}", response_model=ThematicInsightResponse)
async def get_thematic_insight(
    insight_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ThematicInsightResponse:
    """Get a specific thematic insight."""
    insight = await db.get(ThematicInsight, insight_id)
    if not insight:
        raise HTTPException(status_code=404, detail="Thematic insight not found")
    return _insight_to_response(insight)


@router.get("/{insight_id}/outcome", response_model=ThematicOutcomeResponse)
async def get_thematic_insight_outcome(
    insight_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ThematicOutcomeResponse:
    """Get the outcome for a specific thematic insight."""
    insight = await db.get(ThematicInsight, insight_id)
    if not insight:
        raise HTTPException(status_code=404, detail="Thematic insight not found")

    query = select(ThematicOutcome).where(
        ThematicOutcome.thematic_insight_id == insight_id
    )
    result = await db.execute(query)
    outcome = result.scalar_one_or_none()
    if not outcome:
        raise HTTPException(status_code=404, detail="No outcome found for this insight")

    return _outcome_to_response(outcome, insight)
