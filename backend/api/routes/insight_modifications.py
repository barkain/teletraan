"""Insight Modifications API routes.

This module provides endpoints for managing modifications to DeepInsights
that arise from conversations. It includes listing, creating, approving,
and rejecting modifications with full audit trail support.
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from models.deep_insight import DeepInsight
from models.insight_conversation import (
    InsightModification,
    InsightConversation,
    ModificationStatus,
    ModificationType,
)
from schemas.insight_conversation import (
    InsightModificationResponse,
    InsightModificationListResponse,
    ModificationApproval,
    ModificationRejection,
)

router = APIRouter()


# Field mapping for applying modifications to DeepInsight
MODIFIABLE_FIELDS = {
    "thesis": "thesis",
    "confidence": "confidence",
    "action": "action",
    "time_horizon": "time_horizon",
    "risk_factors": "risk_factors",
    "related_symbols": "related_symbols",
    "invalidation_trigger": "invalidation_trigger",
    "title": "title",
    "supporting_evidence": "supporting_evidence",
}


# --- Request Schema for creating modifications ---
from pydantic import BaseModel, Field
from schemas.insight_conversation import ModificationType as ModificationTypeSchema


class ModificationCreate(BaseModel):
    """Request schema for creating a proposed modification."""

    modification_type: ModificationTypeSchema
    field_modified: str = Field(..., max_length=100)
    new_value: Any
    reason: str = Field(..., min_length=1, max_length=2000)
    conversation_id: int | None = None
    message_id: int | None = None


# --- Insight-scoped endpoints ---


@router.get(
    "/insights/{insight_id}/modifications",
    response_model=InsightModificationListResponse,
)
async def list_insight_modifications(
    insight_id: int,
    db: AsyncSession = Depends(get_db),
    status: ModificationStatus | None = None,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0),
) -> InsightModificationListResponse:
    """List all modifications for a specific insight.

    Args:
        insight_id: The ID of the DeepInsight
        status: Optional filter by modification status (PENDING, APPROVED, REJECTED)
        limit: Maximum number of results to return
        offset: Number of results to skip

    Returns:
        Paginated list of modifications for the insight
    """
    # Verify insight exists
    insight_result = await db.execute(
        select(DeepInsight).where(DeepInsight.id == insight_id)
    )
    if not insight_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Deep insight not found")

    # Build query
    query = (
        select(InsightModification)
        .where(InsightModification.deep_insight_id == insight_id)
        .order_by(desc(InsightModification.created_at))
    )

    if status:
        query = query.where(InsightModification.status == status)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    # Apply pagination
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    modifications = result.scalars().all()

    return InsightModificationListResponse(
        items=[InsightModificationResponse.model_validate(m) for m in modifications],
        total=total,
        has_more=(offset + len(modifications)) < total,
    )


@router.post(
    "/insights/{insight_id}/modifications",
    response_model=InsightModificationResponse,
    status_code=201,
)
async def create_modification(
    insight_id: int,
    modification: ModificationCreate,
    db: AsyncSession = Depends(get_db),
) -> InsightModificationResponse:
    """Create a proposed modification for an insight.

    This creates a new modification in PENDING status. The modification
    must be approved before it will be applied to the insight.

    Args:
        insight_id: The ID of the DeepInsight to modify
        modification: The modification details

    Returns:
        The created modification record

    Raises:
        404: If the insight is not found
        400: If the field is not modifiable or conversation doesn't exist
    """
    # Verify insight exists
    insight_result = await db.execute(
        select(DeepInsight).where(DeepInsight.id == insight_id)
    )
    insight = insight_result.scalar_one_or_none()
    if not insight:
        raise HTTPException(status_code=404, detail="Deep insight not found")

    # Validate field is modifiable
    if modification.field_modified not in MODIFIABLE_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"Field '{modification.field_modified}' is not modifiable. "
            f"Allowed fields: {list(MODIFIABLE_FIELDS.keys())}",
        )

    # Verify conversation exists if provided
    if modification.conversation_id:
        conv_result = await db.execute(
            select(InsightConversation).where(
                InsightConversation.id == modification.conversation_id
            )
        )
        if not conv_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Conversation not found")

    # Get current value for the field
    field_attr = MODIFIABLE_FIELDS[modification.field_modified]
    current_value = getattr(insight, field_attr)

    # Store current value as JSON-serializable
    previous_value = {"value": current_value}
    new_value = {"value": modification.new_value}

    # Create modification record
    db_modification = InsightModification(
        deep_insight_id=insight_id,
        conversation_id=modification.conversation_id,
        message_id=modification.message_id,
        modification_type=ModificationType(modification.modification_type.value),
        field_modified=modification.field_modified,
        previous_value=previous_value,
        new_value=new_value,
        reason=modification.reason,
        status=ModificationStatus.PENDING,
    )

    db.add(db_modification)
    await db.commit()
    await db.refresh(db_modification)

    return InsightModificationResponse.model_validate(db_modification)


# --- Modification-level endpoints ---


@router.get("/modifications/pending", response_model=InsightModificationListResponse)
async def list_pending_modifications(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0),
    insight_id: int | None = None,
) -> InsightModificationListResponse:
    """List all pending modifications across all insights.

    This endpoint provides a queue view of modifications awaiting review.

    Args:
        limit: Maximum number of results to return
        offset: Number of results to skip
        insight_id: Optional filter by insight ID

    Returns:
        Paginated list of pending modifications
    """
    query = (
        select(InsightModification)
        .where(InsightModification.status == ModificationStatus.PENDING)
        .order_by(desc(InsightModification.created_at))
    )

    if insight_id:
        query = query.where(InsightModification.deep_insight_id == insight_id)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    # Apply pagination
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    modifications = result.scalars().all()

    return InsightModificationListResponse(
        items=[InsightModificationResponse.model_validate(m) for m in modifications],
        total=total,
        has_more=(offset + len(modifications)) < total,
    )


@router.get("/modifications/{modification_id}", response_model=InsightModificationResponse)
async def get_modification(
    modification_id: int,
    db: AsyncSession = Depends(get_db),
) -> InsightModificationResponse:
    """Get a single modification by ID.

    Args:
        modification_id: The ID of the modification

    Returns:
        The modification details

    Raises:
        404: If the modification is not found
    """
    result = await db.execute(
        select(InsightModification).where(InsightModification.id == modification_id)
    )
    modification = result.scalar_one_or_none()
    if not modification:
        raise HTTPException(status_code=404, detail="Modification not found")

    return InsightModificationResponse.model_validate(modification)


@router.patch(
    "/modifications/{modification_id}/approve",
    response_model=InsightModificationResponse,
)
async def approve_modification(
    modification_id: int,
    approval: ModificationApproval | None = None,
    db: AsyncSession = Depends(get_db),
) -> InsightModificationResponse:
    """Approve a pending modification and apply it to the insight.

    When approved, the modification will be applied to the DeepInsight
    immediately. The previous value is preserved for audit purposes.

    Args:
        modification_id: The ID of the modification to approve
        approval: Optional approval details with reason

    Returns:
        The updated modification record

    Raises:
        404: If the modification is not found
        400: If the modification is not in PENDING status
        500: If applying the modification fails
    """
    # Get modification with FOR UPDATE lock
    result = await db.execute(
        select(InsightModification).where(InsightModification.id == modification_id)
    )
    modification = result.scalar_one_or_none()
    if not modification:
        raise HTTPException(status_code=404, detail="Modification not found")

    if modification.status != ModificationStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve modification with status {modification.status.value}. "
            "Only PENDING modifications can be approved.",
        )

    # Get the insight to modify
    insight_result = await db.execute(
        select(DeepInsight).where(DeepInsight.id == modification.deep_insight_id)
    )
    insight = insight_result.scalar_one_or_none()
    if not insight:
        raise HTTPException(
            status_code=500,
            detail="Associated insight not found. The insight may have been deleted.",
        )

    # Apply the modification to the insight
    field_attr = MODIFIABLE_FIELDS.get(modification.field_modified)
    if not field_attr:
        raise HTTPException(
            status_code=500,
            detail=f"Field '{modification.field_modified}' mapping not found",
        )

    new_value = modification.new_value.get("value") if modification.new_value else None

    try:
        setattr(insight, field_attr, new_value)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to apply modification: {str(e)}",
        )

    # Update modification status
    modification.status = ModificationStatus.APPROVED
    modification.approved_at = datetime.utcnow()

    await db.commit()
    await db.refresh(modification)

    return InsightModificationResponse.model_validate(modification)


@router.patch(
    "/modifications/{modification_id}/reject",
    response_model=InsightModificationResponse,
)
async def reject_modification(
    modification_id: int,
    rejection: ModificationRejection,
    db: AsyncSession = Depends(get_db),
) -> InsightModificationResponse:
    """Reject a pending modification.

    Rejected modifications are preserved for audit purposes but
    will not be applied to the insight.

    Args:
        modification_id: The ID of the modification to reject
        rejection: Rejection details including required reason

    Returns:
        The updated modification record

    Raises:
        404: If the modification is not found
        400: If the modification is not in PENDING status
    """
    result = await db.execute(
        select(InsightModification).where(InsightModification.id == modification_id)
    )
    modification = result.scalar_one_or_none()
    if not modification:
        raise HTTPException(status_code=404, detail="Modification not found")

    if modification.status != ModificationStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reject modification with status {modification.status.value}. "
            "Only PENDING modifications can be rejected.",
        )

    # Update modification status
    modification.status = ModificationStatus.REJECTED
    modification.rejected_reason = rejection.reason

    await db.commit()
    await db.refresh(modification)

    return InsightModificationResponse.model_validate(modification)


@router.delete("/modifications/{modification_id}", status_code=204)
async def delete_modification(
    modification_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a pending modification.

    Only pending modifications can be deleted. Approved or rejected
    modifications are preserved for audit purposes.

    Args:
        modification_id: The ID of the modification to delete

    Raises:
        404: If the modification is not found
        400: If the modification is not in PENDING status
    """
    result = await db.execute(
        select(InsightModification).where(InsightModification.id == modification_id)
    )
    modification = result.scalar_one_or_none()
    if not modification:
        raise HTTPException(status_code=404, detail="Modification not found")

    if modification.status != ModificationStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete modification with status {modification.status.value}. "
            "Only PENDING modifications can be deleted.",
        )

    await db.delete(modification)
    await db.commit()
