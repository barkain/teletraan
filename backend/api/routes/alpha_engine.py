"""Alpha engine v2 API routes."""

import logging
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from database import async_session_factory
from models.alpha_engine import AnalysisRun, AnalysisRunStatus, CandidateIdea, SecuritySignal
from models.analysis_task import AnalysisTask, AnalysisTaskStatus
from schemas.alpha_engine import AnalysisRunSchema, CandidateIdeaSchema, SecuritySignalSchema

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class StartAlphaRunResponse(BaseModel):
    task_id: str
    status: str
    message: str


class AlphaTaskResponse(BaseModel):
    task_id: str
    analysis_run_id: str | None = None
    status: str
    progress: int
    phase_details: str | None = None
    error_message: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    elapsed_seconds: float | None = None
    market_regime: str | None = None
    universe_size: int | None = None
    ideas_persisted: int | None = None


class AlphaRunListResponse(BaseModel):
    items: list[AnalysisRunSchema]
    total: int


class AlphaRunDetailResponse(BaseModel):
    run: AnalysisRunSchema
    candidates: list[CandidateIdeaSchema]
    top_signals: list[SecuritySignalSchema]


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------


async def _run_alpha_engine_background(task_id: str) -> None:
    """Run the full alpha pipeline in a background worker session."""
    from analysis.alpha_engine import create_daily_alpha_run

    async with async_session_factory() as session:
        # Mark running
        task_result = await session.execute(
            select(AnalysisTask).where(AnalysisTask.id == task_id)
        )
        task = task_result.scalar_one_or_none()
        if not task:
            logger.error("Alpha engine task %s not found", task_id)
            return

        task.status = AnalysisTaskStatus.MACRO_SCAN.value
        task.progress = 5
        task.phase_details = "Running alpha pipeline…"
        task.started_at = datetime.utcnow()
        await session.commit()

        try:
            result = await create_daily_alpha_run(session)

            task.status = AnalysisTaskStatus.COMPLETED.value
            task.progress = 100
            task.result_analysis_id = result["analysis_run_id"]
            task.market_regime = result["regime"]["name"]
            task.discovery_summary = result["synthesis"].get("summary")
            task.phase_details = "Alpha analysis complete."
            task.completed_at = datetime.utcnow()
            if task.started_at:
                task.elapsed_seconds = (task.completed_at - task.started_at).total_seconds()

            await session.commit()
            logger.info("Alpha run %s completed (task %s)", result["analysis_run_id"], task_id)

        except Exception as exc:
            logger.exception("Alpha engine failed for task %s", task_id)
            task.status = AnalysisTaskStatus.FAILED.value
            task.error_message = str(exc)
            task.completed_at = datetime.utcnow()
            if task.started_at:
                task.elapsed_seconds = (task.completed_at - task.started_at).total_seconds()
            await session.commit()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/start", response_model=StartAlphaRunResponse)
async def start_alpha_run(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Start a new alpha engine analysis in the background.

    Returns immediately with a task_id to poll via /status/{task_id}.
    """
    task_id = str(uuid4())
    task = AnalysisTask(
        id=task_id,
        status=AnalysisTaskStatus.PENDING.value,
        progress=0,
        current_phase="pending",
        phase_details="Queued — starting alpha engine…",
    )
    db.add(task)
    await db.commit()

    background_tasks.add_task(_run_alpha_engine_background, task_id=task_id)

    return StartAlphaRunResponse(
        task_id=task_id,
        status="started",
        message="Alpha engine analysis started in background",
    )


@router.get("/status/{task_id}", response_model=AlphaTaskResponse)
async def get_alpha_status(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Poll the status of a running or completed alpha run."""
    result = await db.execute(select(AnalysisTask).where(AnalysisTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    run_id = task.result_analysis_id
    universe_size = None
    ideas_persisted = None
    market_regime = task.market_regime

    if run_id:
        run_result = await db.execute(select(AnalysisRun).where(AnalysisRun.id == run_id))
        run = run_result.scalar_one_or_none()
        if run:
            universe_size = run.universe_size
            ideas_persisted = run.ideas_persisted
            market_regime = market_regime or run.market_regime

    return AlphaTaskResponse(
        task_id=task.id,
        analysis_run_id=run_id,
        status=task.status,
        progress=task.progress,
        phase_details=task.phase_details,
        error_message=task.error_message,
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        elapsed_seconds=task.elapsed_seconds,
        market_regime=market_regime,
        universe_size=universe_size,
        ideas_persisted=ideas_persisted,
    )


@router.get("/active", response_model=AlphaTaskResponse | None)
async def get_active_alpha_run(db: AsyncSession = Depends(get_db)):
    """Return the most recent in-progress alpha task, if any.

    Use on page load so the UI can resume polling after a refresh.
    """
    active_statuses = [
        AnalysisTaskStatus.PENDING.value,
        AnalysisTaskStatus.MACRO_SCAN.value,
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

    return AlphaTaskResponse(
        task_id=task.id,
        analysis_run_id=task.result_analysis_id,
        status=task.status,
        progress=task.progress,
        phase_details=task.phase_details,
        error_message=task.error_message,
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        elapsed_seconds=task.elapsed_seconds,
        market_regime=task.market_regime,
        universe_size=None,
        ideas_persisted=None,
    )


@router.get("/runs", response_model=AlphaRunListResponse)
async def list_alpha_runs(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0),
):
    """List past alpha engine runs, newest first."""
    from sqlalchemy import func

    count_result = await db.scalar(select(func.count()).select_from(AnalysisRun))
    total = count_result or 0

    result = await db.execute(
        select(AnalysisRun)
        .order_by(desc(AnalysisRun.created_at))
        .offset(offset)
        .limit(limit)
    )
    runs = result.scalars().all()

    return AlphaRunListResponse(
        items=[AnalysisRunSchema.model_validate(r) for r in runs],
        total=total,
    )


@router.get("/runs/{run_id}", response_model=AlphaRunDetailResponse)
async def get_alpha_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    signal_limit: int = Query(default=30, le=100),
):
    """Get a single alpha run with its top candidates and signals."""
    result = await db.execute(select(AnalysisRun).where(AnalysisRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Alpha run not found")

    candidates_result = await db.execute(
        select(CandidateIdea)
        .where(CandidateIdea.analysis_run_id == run_id)
        .order_by(CandidateIdea.rank.asc())
    )
    candidates = candidates_result.scalars().all()

    signals_result = await db.execute(
        select(SecuritySignal)
        .where(SecuritySignal.analysis_run_id == run_id)
        .order_by(SecuritySignal.overall_score.desc())
        .limit(signal_limit)
    )
    signals = signals_result.scalars().all()

    return AlphaRunDetailResponse(
        run=AnalysisRunSchema.model_validate(run),
        candidates=[CandidateIdeaSchema.model_validate(c) for c in candidates],
        top_signals=[SecuritySignalSchema.model_validate(s) for s in signals],
    )
