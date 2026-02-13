"""Deep Insights API routes."""

import logging
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from database import async_session_factory
from models.deep_insight import DeepInsight
from models.analysis_task import AnalysisTask, AnalysisTaskStatus, PHASE_NAMES
from schemas.deep_insight import DeepInsightResponse, DeepInsightListResponse
from analysis.deep_engine import deep_analysis_engine
from analysis.autonomous_engine import get_autonomous_engine
from api.routes.reports import _build_report_html, _publish_to_ghpages, _REPO_DIR

logger = logging.getLogger(__name__)


class GenerateRequest(BaseModel):
    """Request body for deep insight generation."""
    symbols: list[str] | None = None


class AutonomousAnalysisRequest(BaseModel):
    """Request for autonomous analysis - no symbols required!"""
    max_insights: int = Field(default=5, ge=1, le=20, description="Number of final insights to produce")
    deep_dive_count: int = Field(default=7, ge=1, le=20, description="Number of opportunities to analyze in detail")


class AutonomousAnalysisResponse(BaseModel):
    """Response from autonomous analysis."""
    analysis_id: str
    status: str
    insights_count: int
    elapsed_seconds: float
    discovery_summary: str
    market_regime: str
    top_sectors: list[str]
    phases_completed: list[str]
    errors: list[str] = Field(default_factory=list)


class MoreInsightsRequest(BaseModel):
    """Request for additional insights."""
    offset: int = Field(default=5, ge=0)
    limit: int = Field(default=5, ge=1, le=50)


class MoreInsightsResponse(BaseModel):
    """Response with additional insights."""
    items: list[DeepInsightResponse]
    offset: int
    limit: int
    has_more: bool


class DiscoveryContextResponse(BaseModel):
    """Response with discovery context."""
    analysis_id: str
    context: dict


class AnalysisTaskResponse(BaseModel):
    """Response for analysis task status."""
    id: str
    status: str
    progress: int
    current_phase: str | None = None
    phase_details: str | None = None
    phase_name: str | None = None  # Human-readable phase name
    result_insight_ids: list[int] | None = None
    result_analysis_id: str | None = None
    market_regime: str | None = None
    top_sectors: list[str] | None = None
    discovery_summary: str | None = None
    phases_completed: list[str] | None = None
    error_message: str | None = None
    elapsed_seconds: float | None = None
    started_at: str | None = None
    completed_at: str | None = None


class StartAnalysisResponse(BaseModel):
    """Response when starting background analysis."""
    task_id: str
    status: str
    message: str


router = APIRouter()


@router.get("", response_model=DeepInsightListResponse)
async def list_deep_insights(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0),
    action: str | None = None,
    insight_type: str | None = None,
    symbol: str | None = None,
):
    """List deep insights with filtering."""
    query = select(DeepInsight).order_by(desc(DeepInsight.created_at))

    if action:
        # Group "strong" variants with their base action:
        # BUY includes STRONG_BUY, SELL includes STRONG_SELL
        action_groups = {
            "BUY": ["BUY", "STRONG_BUY"],
            "SELL": ["SELL", "STRONG_SELL"],
        }
        actions = action_groups.get(action, [action])
        query = query.where(DeepInsight.action.in_(actions))
    if insight_type:
        query = query.where(DeepInsight.insight_type == insight_type)
    if symbol:
        query = query.where(
            (DeepInsight.primary_symbol == symbol)
            | (DeepInsight.related_symbols.contains([symbol]))
        )

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    # Apply pagination
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    insights = result.scalars().all()

    return DeepInsightListResponse(
        items=[DeepInsightResponse.model_validate(i) for i in insights],
        total=total or 0,
    )


@router.get("/{insight_id}", response_model=DeepInsightResponse)
async def get_deep_insight(
    insight_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a single deep insight."""
    result = await db.execute(
        select(DeepInsight).where(DeepInsight.id == insight_id)
    )
    insight = result.scalar_one_or_none()
    if not insight:
        raise HTTPException(status_code=404, detail="Deep insight not found")
    return DeepInsightResponse.model_validate(insight)


@router.post("/generate")
async def generate_deep_insights(
    background_tasks: BackgroundTasks,
    request: GenerateRequest | None = None,
):
    """Trigger deep analysis to generate new insights.

    Runs the multi-agent analysis engine in the background to generate
    AI-powered market insights from our analyst team.

    Args:
        request: Optional request body with symbols to analyze.
            If not provided, analyzes all tracked symbols.

    Returns:
        Status message indicating analysis has started.
    """
    symbols = request.symbols if request else None

    # Run analysis in background
    background_tasks.add_task(
        deep_analysis_engine.run_and_store,
        symbols=symbols,
    )

    return {
        "message": "Deep analysis started",
        "symbols": symbols if symbols else "all tracked symbols",
    }


# ===== AUTONOMOUS ANALYSIS ENDPOINTS =====


@router.post("/autonomous", response_model=AutonomousAnalysisResponse)
async def run_autonomous_analysis(
    request: AutonomousAnalysisRequest | None = None,
):
    """Run autonomous market analysis.

    The system will:
    1. Scan macro environment (identify market regime and themes)
    2. Analyze sector rotation (find sector momentum signals)
    3. Discover opportunities (screen for specific stocks)
    4. Deep dive into top candidates (detailed multi-analyst analysis)
    5. Synthesize final insights (rank and produce actionable insights)

    No symbols required - the system finds opportunities autonomously.

    Args:
        request: Optional parameters for max_insights and deep_dive_count.

    Returns:
        AutonomousAnalysisResponse with analysis metadata and summary.
    """
    engine = get_autonomous_engine()

    max_insights = request.max_insights if request else 5
    deep_dive_count = request.deep_dive_count if request else 7

    try:
        result = await engine.run_autonomous_analysis(
            max_insights=max_insights,
            deep_dive_count=deep_dive_count,
        )

        # Extract top sectors from result
        top_sectors: list[str] = []
        if result.sector_result:
            top_sectors = [s.sector_name for s in result.sector_result.top_sectors]
        elif result.heatmap_data and result.heatmap_data.sectors:
            sorted_sectors = sorted(
                result.heatmap_data.sectors,
                key=lambda s: abs(s.change_20d or s.change_5d or s.change_1d or 0),
                reverse=True,
            )
            top_sectors = [
                f"{s.name} {(s.change_20d or s.change_5d or s.change_1d or 0):+.1f}%"
                for s in sorted_sectors[:6]
            ]

        # Get market regime
        market_regime = ""
        if result.macro_result:
            market_regime = result.macro_result.market_regime

        return AutonomousAnalysisResponse(
            analysis_id=result.analysis_id,
            status="complete",
            insights_count=len(result.insights),
            elapsed_seconds=result.elapsed_seconds,
            discovery_summary=result.discovery_summary,
            market_regime=market_regime,
            top_sectors=top_sectors,
            phases_completed=result.phases_completed,
            errors=result.errors,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/autonomous/more", response_model=MoreInsightsResponse)
async def get_more_insights(
    request: MoreInsightsRequest,
    db: AsyncSession = Depends(get_db),
):
    """Get additional insights beyond the initial batch.

    Useful for "Load More" button in frontend to paginate through
    previously generated insights.

    Args:
        request: Pagination parameters (offset and limit).
        db: Database session.

    Returns:
        MoreInsightsResponse with paginated insights.
    """
    # Query insights ordered by creation date (newest first)
    query = (
        select(DeepInsight)
        .order_by(desc(DeepInsight.created_at))
        .offset(request.offset)
        .limit(request.limit + 1)  # Fetch one extra to check has_more
    )

    result = await db.execute(query)
    insights = list(result.scalars().all())

    # Check if there are more results
    has_more = len(insights) > request.limit
    if has_more:
        insights = insights[: request.limit]  # Trim to requested limit

    return MoreInsightsResponse(
        items=[DeepInsightResponse.model_validate(i) for i in insights],
        offset=request.offset,
        limit=request.limit,
        has_more=has_more,
    )


@router.get("/discovery-context/{analysis_id}", response_model=DiscoveryContextResponse)
async def get_discovery_context(
    analysis_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the discovery context for an analysis.

    Shows how opportunities were found including:
    - Macro themes that guided the search
    - Sector rotation signals
    - Screening criteria applied

    Args:
        analysis_id: The analysis ID to fetch context for.
        db: Database session.

    Returns:
        DiscoveryContextResponse with context details.
    """
    # Find insights from this analysis by checking data_sources
    # Autonomous insights have "analysis_type:autonomous_discovery" in data_sources
    query = (
        select(DeepInsight)
        .where(DeepInsight.data_sources.isnot(None))
        .order_by(desc(DeepInsight.created_at))
        .limit(10)
    )

    result = await db.execute(query)
    insights = result.scalars().all()

    # Look for insights with autonomous discovery metadata
    for insight in insights:
        if insight.data_sources:
            sources = insight.data_sources
            if any("autonomous_discovery" in str(s) for s in sources):
                # Extract context from data_sources
                context = {
                    "macro_regime": None,
                    "opportunity_type": None,
                    "analysis_type": None,
                    "data_sources": sources,
                }

                for source in sources:
                    if isinstance(source, str):
                        if source.startswith("macro_regime:"):
                            context["macro_regime"] = source.split(":", 1)[1]
                        elif source.startswith("opportunity_type:"):
                            context["opportunity_type"] = source.split(":", 1)[1]
                        elif source.startswith("analysis_type:"):
                            context["analysis_type"] = source.split(":", 1)[1]

                return DiscoveryContextResponse(
                    analysis_id=analysis_id,
                    context=context,
                )

    raise HTTPException(status_code=404, detail="Discovery context not found")


# ===== BACKGROUND ANALYSIS ENDPOINTS =====


async def _auto_publish_report(task_id: str) -> None:
    """Auto-publish a completed analysis report to GitHub Pages.

    Best-effort: any failure is logged as a warning and never propagated.
    Called after the autonomous pipeline marks a task as completed.

    Args:
        task_id: The completed task ID to publish.
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(AnalysisTask).where(AnalysisTask.id == task_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            logger.warning(f"Auto-publish: task {task_id} not found")
            return

        # Load associated insights for HTML generation
        insights: list[DeepInsight] = []
        if task.result_insight_ids:
            insight_result = await session.execute(
                select(DeepInsight).where(DeepInsight.id.in_(task.result_insight_ids))
            )
            db_insights = insight_result.scalars().all()
            insight_map = {i.id: i for i in db_insights}
            for iid in task.result_insight_ids:
                ins = insight_map.get(iid)
                if ins:
                    insights.append(ins)

        html_content = _build_report_html(task, insights)
        published_url = await _publish_to_ghpages(
            task, html_content, _REPO_DIR, insights,
        )

        # Persist the published URL on the task
        task.published_url = published_url
        await session.commit()
        logger.info(f"Auto-published report {task_id} to {published_url}")


async def _run_background_analysis(task_id: str, max_insights: int, deep_dive_count: int) -> None:
    """Background task to run autonomous analysis with progress updates.

    Args:
        task_id: The task ID for progress tracking.
        max_insights: Number of insights to generate.
        deep_dive_count: Number of opportunities to deep dive.
    """
    try:
        # Update task to started
        async with async_session_factory() as session:
            result = await session.execute(
                select(AnalysisTask).where(AnalysisTask.id == task_id)
            )
            task = result.scalar_one_or_none()
            if task:
                task.status = AnalysisTaskStatus.MACRO_SCAN.value
                task.started_at = datetime.utcnow()
                await session.commit()

        # Run the autonomous analysis
        engine = get_autonomous_engine()
        analysis_result = await engine.run_autonomous_analysis(
            max_insights=max_insights,
            deep_dive_count=deep_dive_count,
            task_id=task_id,
        )

        # Update task with results
        async with async_session_factory() as session:
            result = await session.execute(
                select(AnalysisTask).where(AnalysisTask.id == task_id)
            )
            task = result.scalar_one_or_none()
            if task:
                task.status = AnalysisTaskStatus.COMPLETED.value
                task.progress = 100
                task.current_phase = "completed"
                task.phase_details = f"Generated {len(analysis_result.insights)} insights"
                task.completed_at = datetime.utcnow()
                task.elapsed_seconds = analysis_result.elapsed_seconds
                task.result_analysis_id = analysis_result.analysis_id
                task.result_insight_ids = [i.id for i in analysis_result.insights]
                task.discovery_summary = analysis_result.discovery_summary
                task.phases_completed = analysis_result.phases_completed
                task.phase_summaries = analysis_result.phase_summaries

                # Extract market regime and top sectors
                if analysis_result.macro_result:
                    task.market_regime = analysis_result.macro_result.market_regime
                if analysis_result.sector_result:
                    task.top_sectors = [
                        s.sector_name for s in analysis_result.sector_result.top_sectors
                    ]
                elif analysis_result.heatmap_data and analysis_result.heatmap_data.sectors:
                    sorted_sectors = sorted(
                        analysis_result.heatmap_data.sectors,
                        key=lambda s: abs(s.change_20d or s.change_5d or s.change_1d or 0),
                        reverse=True,
                    )
                    task.top_sectors = [
                        f"{s.name} {(s.change_20d or s.change_5d or s.change_1d or 0):+.1f}%"
                        for s in sorted_sectors[:6]
                    ]

                await session.commit()
                logger.info(f"Background analysis {task_id} completed successfully")

                # Auto-publish to GitHub Pages (best-effort, never breaks pipeline)
                try:
                    await _auto_publish_report(task_id)
                except Exception as pub_err:
                    logger.warning(f"Auto-publish failed for task {task_id} (non-fatal): {pub_err}")

    except Exception as e:
        logger.error(f"Background analysis {task_id} failed: {e}")
        # Update task with error
        try:
            async with async_session_factory() as session:
                result = await session.execute(
                    select(AnalysisTask).where(AnalysisTask.id == task_id)
                )
                task = result.scalar_one_or_none()
                if task:
                    task.status = AnalysisTaskStatus.FAILED.value
                    task.progress = -1
                    task.error_message = str(e)
                    task.completed_at = datetime.utcnow()
                    await session.commit()
        except Exception as update_error:
            logger.error(f"Failed to update task {task_id} with error: {update_error}")


@router.post("/autonomous/start", response_model=StartAnalysisResponse)
async def start_autonomous_analysis(
    background_tasks: BackgroundTasks,
    request: AutonomousAnalysisRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Start background autonomous analysis.

    Starts the analysis in the background and returns immediately with a task ID.
    Use the /autonomous/status/{task_id} endpoint to poll for progress.

    Args:
        background_tasks: FastAPI background tasks.
        request: Optional analysis parameters.
        db: Database session.

    Returns:
        StartAnalysisResponse with task_id for status polling.
    """
    max_insights = request.max_insights if request else 5
    deep_dive_count = request.deep_dive_count if request else 7

    # Create task record
    task_id = str(uuid4())
    task = AnalysisTask(
        id=task_id,
        status=AnalysisTaskStatus.PENDING.value,
        progress=0,
        current_phase="pending",
        phase_details="Initializing analysis...",
        max_insights=max_insights,
        deep_dive_count=deep_dive_count,
    )
    db.add(task)
    await db.commit()

    # Start background task
    background_tasks.add_task(
        _run_background_analysis,
        task_id=task_id,
        max_insights=max_insights,
        deep_dive_count=deep_dive_count,
    )

    return StartAnalysisResponse(
        task_id=task_id,
        status="started",
        message="Autonomous analysis started in background",
    )


@router.get("/autonomous/status/{task_id}", response_model=AnalysisTaskResponse)
async def get_analysis_status(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the status of a background analysis task.

    Poll this endpoint to track progress of a running analysis.

    Args:
        task_id: The task ID returned from /autonomous/start.
        db: Database session.

    Returns:
        AnalysisTaskResponse with current status and progress.
    """
    result = await db.execute(
        select(AnalysisTask).where(AnalysisTask.id == task_id)
    )
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="Analysis task not found")

    # Get human-readable phase name
    phase_name = None
    try:
        status_enum = AnalysisTaskStatus(task.status)
        phase_name = PHASE_NAMES.get(status_enum)
    except ValueError:
        phase_name = task.current_phase

    return AnalysisTaskResponse(
        id=task.id,
        status=task.status,
        progress=task.progress,
        current_phase=task.current_phase,
        phase_details=task.phase_details,
        phase_name=phase_name,
        result_insight_ids=task.result_insight_ids,
        result_analysis_id=task.result_analysis_id,
        market_regime=task.market_regime,
        top_sectors=task.top_sectors,
        discovery_summary=task.discovery_summary,
        phases_completed=task.phases_completed,
        error_message=task.error_message,
        elapsed_seconds=task.elapsed_seconds,
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
    )


@router.get("/autonomous/active", response_model=AnalysisTaskResponse | None)
async def get_active_analysis(
    db: AsyncSession = Depends(get_db),
):
    """Get the currently running analysis task, if any.

    Use this on page load to check if an analysis is already running.

    Args:
        db: Database session.

    Returns:
        AnalysisTaskResponse if an analysis is running, null otherwise.
    """
    # Find most recent non-completed task
    active_statuses = [
        AnalysisTaskStatus.PENDING.value,
        AnalysisTaskStatus.MACRO_SCAN.value,
        AnalysisTaskStatus.SECTOR_ROTATION.value,
        AnalysisTaskStatus.OPPORTUNITY_HUNT.value,
        AnalysisTaskStatus.HEATMAP_FETCH.value,
        AnalysisTaskStatus.HEATMAP_ANALYSIS.value,
        AnalysisTaskStatus.DEEP_DIVE.value,
        AnalysisTaskStatus.COVERAGE_EVALUATION.value,
        AnalysisTaskStatus.SYNTHESIS.value,
    ]

    result = await db.execute(
        select(AnalysisTask)
        .where(AnalysisTask.status.in_(active_statuses))
        .order_by(desc(AnalysisTask.created_at))
        .limit(1)
    )
    task = result.scalar_one_or_none()

    if not task:
        return None

    # Get human-readable phase name
    phase_name = None
    try:
        status_enum = AnalysisTaskStatus(task.status)
        phase_name = PHASE_NAMES.get(status_enum)
    except ValueError:
        phase_name = task.current_phase

    return AnalysisTaskResponse(
        id=task.id,
        status=task.status,
        progress=task.progress,
        current_phase=task.current_phase,
        phase_details=task.phase_details,
        phase_name=phase_name,
        result_insight_ids=task.result_insight_ids,
        result_analysis_id=task.result_analysis_id,
        market_regime=task.market_regime,
        top_sectors=task.top_sectors,
        discovery_summary=task.discovery_summary,
        phases_completed=task.phases_completed,
        error_message=task.error_message,
        elapsed_seconds=task.elapsed_seconds,
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
    )


class CancelAnalysisResponse(BaseModel):
    """Response when cancelling an analysis."""
    task_id: str
    status: str
    message: str


@router.post("/autonomous/cancel/{task_id}", response_model=CancelAnalysisResponse)
async def cancel_analysis(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a running analysis task.

    Sets the task status to 'cancelled' which will stop the analysis
    at the next checkpoint.

    Args:
        task_id: The task ID to cancel.
        db: Database session.

    Returns:
        CancelAnalysisResponse with cancellation status.
    """
    result = await db.execute(
        select(AnalysisTask).where(AnalysisTask.id == task_id)
    )
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="Analysis task not found")

    # Check if task is in a cancellable state
    cancellable_statuses = [
        AnalysisTaskStatus.PENDING.value,
        AnalysisTaskStatus.MACRO_SCAN.value,
        AnalysisTaskStatus.SECTOR_ROTATION.value,
        AnalysisTaskStatus.OPPORTUNITY_HUNT.value,
        AnalysisTaskStatus.HEATMAP_FETCH.value,
        AnalysisTaskStatus.HEATMAP_ANALYSIS.value,
        AnalysisTaskStatus.DEEP_DIVE.value,
        AnalysisTaskStatus.COVERAGE_EVALUATION.value,
        AnalysisTaskStatus.SYNTHESIS.value,
    ]

    if task.status not in cancellable_statuses:
        return CancelAnalysisResponse(
            task_id=task_id,
            status=task.status,
            message=f"Task cannot be cancelled (status: {task.status})",
        )

    # Update task status to cancelled
    task.status = AnalysisTaskStatus.CANCELLED.value
    task.phase_details = "Analysis cancelled by user"
    task.completed_at = datetime.utcnow()
    await db.commit()

    return CancelAnalysisResponse(
        task_id=task_id,
        status="cancelled",
        message="Analysis cancelled successfully",
    )


@router.get("/autonomous/recent", response_model=AnalysisTaskResponse | None)
async def get_recent_completed_analysis(
    db: AsyncSession = Depends(get_db),
):
    """Get the most recently completed analysis task.

    Use this to show results of a completed analysis when returning to the page.

    Args:
        db: Database session.

    Returns:
        AnalysisTaskResponse if a completed analysis exists, null otherwise.
    """
    result = await db.execute(
        select(AnalysisTask)
        .where(AnalysisTask.status == AnalysisTaskStatus.COMPLETED.value)
        .order_by(desc(AnalysisTask.completed_at))
        .limit(1)
    )
    task = result.scalar_one_or_none()

    if not task:
        return None

    return AnalysisTaskResponse(
        id=task.id,
        status=task.status,
        progress=task.progress,
        current_phase=task.current_phase,
        phase_details=task.phase_details,
        phase_name=PHASE_NAMES.get(AnalysisTaskStatus.COMPLETED),
        result_insight_ids=task.result_insight_ids,
        result_analysis_id=task.result_analysis_id,
        market_regime=task.market_regime,
        top_sectors=task.top_sectors,
        discovery_summary=task.discovery_summary,
        phases_completed=task.phases_completed,
        error_message=task.error_message,
        elapsed_seconds=task.elapsed_seconds,
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
    )
