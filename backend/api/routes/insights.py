"""Insights REST API endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from models.insight import Insight, InsightAnnotation
from models.stock import Stock
from schemas.insight import (
    AnnotationCreate,
    AnnotationResponse,
    AnnotationUpdate,
    InsightListResponse,
    InsightResponse,
)
from services.insight_service import insight_service

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("", response_model=InsightListResponse)
async def list_insights(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    insight_type: str | None = None,
    severity: str | None = None,
    symbol: str | None = None,
    active_only: bool = True,
):
    """List insights with filtering."""
    query = select(Insight)

    if active_only:
        query = query.where(Insight.is_active == True)  # noqa: E712
        query = query.where(
            (Insight.expires_at.is_(None)) | (Insight.expires_at > datetime.now(timezone.utc))
        )

    if insight_type:
        query = query.where(Insight.insight_type == insight_type)
    if severity:
        query = query.where(Insight.severity == severity)
    if symbol:
        # Join with stock to filter by symbol
        query = query.join(Stock).where(Stock.symbol == symbol.upper())

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    # Paginate
    query = query.order_by(Insight.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    insights = result.scalars().all()

    return InsightListResponse(insights=insights, total=total or 0)


@router.get("/types")
async def list_insight_types():
    """Get available insight types."""
    return {"types": ["pattern", "anomaly", "sector", "technical", "economic", "sentiment"]}


@router.get("/severities")
async def list_severities():
    """Get available severity levels."""
    return {"severities": ["info", "warning", "alert"]}


@router.get("/{insight_id}", response_model=InsightResponse)
async def get_insight(insight_id: int, db: AsyncSession = Depends(get_db)):
    """Get insight by ID."""
    query = select(Insight).where(Insight.id == insight_id)
    result = await db.execute(query)
    insight = result.scalar_one_or_none()

    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")

    return insight


@router.get("/{insight_id}/annotations", response_model=list[AnnotationResponse])
async def get_annotations(insight_id: int, db: AsyncSession = Depends(get_db)):
    """Get annotations for an insight."""
    query = (
        select(InsightAnnotation)
        .where(InsightAnnotation.insight_id == insight_id)
        .order_by(InsightAnnotation.created_at.desc())
    )

    result = await db.execute(query)
    return result.scalars().all()


@router.post("/{insight_id}/annotations", response_model=AnnotationResponse)
async def add_annotation(
    insight_id: int,
    data: AnnotationCreate,
    db: AsyncSession = Depends(get_db),
):
    """Add annotation to an insight."""
    try:
        annotation = await insight_service.add_annotation(db, insight_id, data.note)
        return annotation
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{insight_id}/annotations/{annotation_id}", response_model=AnnotationResponse)
async def update_annotation(
    insight_id: int,
    annotation_id: int,
    data: AnnotationUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing annotation."""
    # Verify annotation exists and belongs to the insight
    annotation = await insight_service.get_annotation(db, annotation_id)
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")
    if annotation.insight_id != insight_id:
        raise HTTPException(status_code=404, detail="Annotation not found for this insight")

    try:
        updated = await insight_service.update_annotation(db, annotation_id, data.note)
        return updated
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{insight_id}/annotations/{annotation_id}")
async def delete_annotation(
    insight_id: int,
    annotation_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete an annotation."""
    # Verify annotation exists and belongs to the insight
    annotation = await insight_service.get_annotation(db, annotation_id)
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")
    if annotation.insight_id != insight_id:
        raise HTTPException(status_code=404, detail="Annotation not found for this insight")

    deleted = await insight_service.delete_annotation(db, annotation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Annotation not found")

    return {"message": "Annotation deleted successfully"}
