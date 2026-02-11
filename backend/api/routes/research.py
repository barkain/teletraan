"""Follow-up research API routes for managing research spawned from conversations."""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from api.deps import get_db
from analysis.followup_research import (
    ResearchRequest,
    get_followup_research_launcher,
)
from models.deep_insight import DeepInsight
from models.insight_conversation import (
    FollowUpResearch,
    InsightConversation,
    ResearchStatus,
    ResearchType,
)
from schemas.research import (
    ResearchCreateRequest,
    ResearchListResponse,
    ResearchResponse,
    ResearchStatusEnum,
    ResearchTypeEnum,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/research", tags=["research"])


def _research_to_response(
    research: FollowUpResearch,
    parent_insight_title: Optional[str] = None,
    result_insight_title: Optional[str] = None,
) -> ResearchResponse:
    """Convert a FollowUpResearch model to a response schema.

    Args:
        research: The FollowUpResearch ORM instance.
        parent_insight_title: Title of the parent insight (optional join).
        result_insight_title: Title of the result insight (optional join).

    Returns:
        ResearchResponse schema.
    """
    return ResearchResponse(
        id=research.id,
        conversation_id=research.conversation_id,
        research_type=research.research_type.value if isinstance(research.research_type, ResearchType) else str(research.research_type),
        query=research.query,
        parameters=research.parameters,
        status=research.status.value if isinstance(research.status, ResearchStatus) else str(research.status),
        result_insight_id=research.result_insight_id,
        error_message=research.error_message,
        completed_at=research.completed_at,
        created_at=research.created_at,
        updated_at=research.updated_at,
        parent_insight_summary=parent_insight_title,
        result_insight_summary=result_insight_title,
    )


@router.get("", response_model=ResearchListResponse)
async def list_research(
    db: AsyncSession = Depends(get_db),
    status: Optional[ResearchStatusEnum] = Query(
        default=None,
        description="Filter by research status",
    ),
    research_type: Optional[ResearchTypeEnum] = Query(
        default=None,
        description="Filter by research type",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ResearchListResponse:
    """List follow-up research records with pagination and filtering.

    Joins with DeepInsight to provide parent and result insight summaries.

    Args:
        db: Database session.
        status: Optional status filter.
        research_type: Optional research type filter.
        limit: Maximum number of results (default 50).
        offset: Pagination offset.

    Returns:
        Paginated list of research records with total count.
    """
    # Aliases for the two DeepInsight joins (parent vs result)
    ParentInsight = aliased(DeepInsight, name="parent_insight")
    ResultInsight = aliased(DeepInsight, name="result_insight")

    # Main query with optional joins for insight summaries
    query = (
        select(
            FollowUpResearch,
            ParentInsight.title.label("parent_title"),
            ResultInsight.title.label("result_title"),
        )
        .outerjoin(
            ResultInsight,
            FollowUpResearch.result_insight_id == ResultInsight.id,
        )
        .outerjoin(
            ParentInsight,
            ResultInsight.parent_insight_id == ParentInsight.id,
        )
    )

    # Apply filters
    if status is not None:
        query = query.where(FollowUpResearch.status == ResearchStatus(status.value))
    if research_type is not None:
        query = query.where(FollowUpResearch.research_type == ResearchType(research_type.value))

    # Count total matching records (before pagination)
    count_query = select(func.count()).select_from(FollowUpResearch)
    if status is not None:
        count_query = count_query.where(FollowUpResearch.status == ResearchStatus(status.value))
    if research_type is not None:
        count_query = count_query.where(FollowUpResearch.research_type == ResearchType(research_type.value))
    total = await db.scalar(count_query) or 0

    # Apply ordering and pagination
    query = query.order_by(FollowUpResearch.created_at.desc())
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    rows = result.all()

    items = [
        _research_to_response(
            research=row[0],
            parent_insight_title=row[1],
            result_insight_title=row[2],
        )
        for row in rows
    ]

    return ResearchListResponse(items=items, total=total)


@router.get("/{research_id}", response_model=ResearchResponse)
async def get_research(
    research_id: int,
    db: AsyncSession = Depends(get_db),
) -> ResearchResponse:
    """Get a single follow-up research record with full details.

    Args:
        research_id: ID of the research record.
        db: Database session.

    Returns:
        Full research record with insight summaries.

    Raises:
        HTTPException: 404 if research not found.
    """
    ParentInsight = aliased(DeepInsight, name="parent_insight")
    ResultInsight = aliased(DeepInsight, name="result_insight")

    query = (
        select(
            FollowUpResearch,
            ParentInsight.title.label("parent_title"),
            ResultInsight.title.label("result_title"),
        )
        .outerjoin(
            ResultInsight,
            FollowUpResearch.result_insight_id == ResultInsight.id,
        )
        .outerjoin(
            ParentInsight,
            ResultInsight.parent_insight_id == ParentInsight.id,
        )
        .where(FollowUpResearch.id == research_id)
    )

    result = await db.execute(query)
    row = result.one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail="Research not found")

    return _research_to_response(
        research=row[0],
        parent_insight_title=row[1],
        result_insight_title=row[2],
    )


async def _run_research_background(
    research_id: int,
    request: ResearchRequest,
) -> None:
    """Background task to run follow-up research.

    Args:
        research_id: ID of the FollowUpResearch record to update.
        request: The ResearchRequest to execute.
    """
    try:
        launcher = get_followup_research_launcher()
        result = await launcher.launch(request)
        if not result.success:
            logger.error(
                f"Background research {research_id} failed: {result.error_message}"
            )
        else:
            logger.info(
                f"Background research {research_id} completed successfully "
                f"(new insight: {result.new_insight.id if result.new_insight else None})"
            )
    except Exception as e:
        logger.exception(f"Background research {research_id} raised exception: {e}")


@router.post("", response_model=ResearchResponse, status_code=201)
async def create_research(
    body: ResearchCreateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> ResearchResponse:
    """Create and trigger a new follow-up research.

    Creates a FollowUpResearch record with PENDING status, then launches
    the FollowUpResearchLauncher as a background task. Returns immediately
    with the created research record.

    Args:
        body: Research creation parameters.
        background_tasks: FastAPI background tasks.
        db: Database session.

    Returns:
        The created research record (status will be PENDING).

    Raises:
        HTTPException: 400 if parent insight not found or no conversation context.
    """
    # Resolve conversation_id from parent insight if provided
    conversation_id: Optional[int] = None
    parent_insight_title: Optional[str] = None

    if body.parent_insight_id is not None:
        # Look up the parent insight to get conversation context
        insight_result = await db.execute(
            select(DeepInsight).where(DeepInsight.id == body.parent_insight_id)
        )
        parent_insight = insight_result.scalar_one_or_none()
        if not parent_insight:
            raise HTTPException(
                status_code=400,
                detail=f"Parent insight {body.parent_insight_id} not found",
            )
        parent_insight_title = parent_insight.title

        # Try to find an existing conversation for this insight
        conv_result = await db.execute(
            select(InsightConversation.id)
            .where(InsightConversation.insight_id == body.parent_insight_id)
            .order_by(InsightConversation.created_at.desc())
            .limit(1)
        )
        conv_row = conv_result.scalar_one_or_none()
        if conv_row is not None:
            conversation_id = conv_row
        else:
            # Create a minimal conversation to anchor the research
            new_conv = InsightConversation(
                insight_id=body.parent_insight_id,
                title=f"Research: {body.query[:100]}",
            )
            db.add(new_conv)
            await db.flush()
            conversation_id = new_conv.id
    else:
        # No parent insight -- create a standalone conversation
        new_conv = InsightConversation(
            title=f"Research: {body.query[:100]}",
        )
        db.add(new_conv)
        await db.flush()
        conversation_id = new_conv.id

    # Create the FollowUpResearch record with PENDING status
    research_type = ResearchType(body.research_type.value)
    research = FollowUpResearch(
        conversation_id=conversation_id,
        research_type=research_type,
        query=body.query,
        parameters={
            "parent_insight_id": body.parent_insight_id,
            "symbols": body.symbols,
            "questions": body.questions,
        },
        status=ResearchStatus.PENDING,
    )
    db.add(research)
    await db.commit()
    await db.refresh(research)

    # Build the ResearchRequest for the launcher
    launcher_request = ResearchRequest(
        parent_insight_id=body.parent_insight_id or 0,
        conversation_id=conversation_id,
        research_type=research_type,
        query=body.query,
        symbols=body.symbols,
        questions=body.questions,
        parameters={
            "parent_insight_id": body.parent_insight_id,
            "symbols": body.symbols,
            "questions": body.questions,
        },
    )

    # Launch research in background
    background_tasks.add_task(_run_research_background, research.id, launcher_request)

    logger.info(
        f"Created research {research.id} (type={body.research_type.value}, "
        f"conversation={conversation_id}), launching in background"
    )

    return _research_to_response(
        research=research,
        parent_insight_title=parent_insight_title,
        result_insight_title=None,
    )


@router.delete("/{research_id}", response_model=ResearchResponse)
async def cancel_research(
    research_id: int,
    db: AsyncSession = Depends(get_db),
) -> ResearchResponse:
    """Cancel a follow-up research by setting status to CANCELLED.

    Only PENDING or RUNNING research can be cancelled.

    Args:
        research_id: ID of the research to cancel.
        db: Database session.

    Returns:
        The updated research record.

    Raises:
        HTTPException: 404 if not found, 400 if already completed/cancelled.
    """
    result = await db.execute(
        select(FollowUpResearch).where(FollowUpResearch.id == research_id)
    )
    research = result.scalar_one_or_none()

    if not research:
        raise HTTPException(status_code=404, detail="Research not found")

    current_status = (
        research.status.value
        if isinstance(research.status, ResearchStatus)
        else str(research.status)
    )
    if current_status in (ResearchStatus.COMPLETED.value, ResearchStatus.CANCELLED.value):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel research with status '{current_status}'",
        )

    research.status = ResearchStatus.CANCELLED
    research.completed_at = datetime.utcnow()
    await db.commit()
    await db.refresh(research)

    logger.info(f"Cancelled research {research_id}")

    return _research_to_response(research=research)
