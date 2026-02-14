"""Runs analytics API routes — list, detail, and aggregate stats for analysis tasks."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from models.analysis_task import AnalysisTask, AnalysisTaskStatus

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# IMPORTANT: /stats must be defined BEFORE /{run_id} to avoid FastAPI
# treating "stats" as a run ID parameter.
# ---------------------------------------------------------------------------


@router.get("/stats")
async def get_runs_stats(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Aggregate statistics across all analysis runs.

    Returns total/completed/failed counts, token usage totals, cost totals,
    and averages for duration and cost (skipping nulls).
    """
    try:
        # Total runs
        total_q = await db.execute(select(func.count(AnalysisTask.id)))
        total_runs = total_q.scalar() or 0

        # Completed runs
        completed_q = await db.execute(
            select(func.count(AnalysisTask.id)).where(
                AnalysisTask.status == AnalysisTaskStatus.COMPLETED.value
            )
        )
        completed_runs = completed_q.scalar() or 0

        # Failed runs
        failed_q = await db.execute(
            select(func.count(AnalysisTask.id)).where(
                AnalysisTask.status == AnalysisTaskStatus.FAILED.value
            )
        )
        failed_runs = failed_q.scalar() or 0

        # Aggregate token usage and cost (sum)
        agg_q = await db.execute(
            select(
                func.sum(AnalysisTask.total_input_tokens),
                func.sum(AnalysisTask.total_output_tokens),
                func.sum(AnalysisTask.total_cost_usd),
            )
        )
        agg_row = agg_q.one()
        total_input_tokens = agg_row[0] or 0
        total_output_tokens = agg_row[1] or 0
        total_cost_usd = agg_row[2] or 0.0

        # Average duration (only non-null elapsed_seconds)
        avg_dur_q = await db.execute(
            select(func.avg(AnalysisTask.elapsed_seconds)).where(
                AnalysisTask.elapsed_seconds.isnot(None)
            )
        )
        avg_duration_seconds = avg_dur_q.scalar()

        # Average cost (only non-null total_cost_usd)
        avg_cost_q = await db.execute(
            select(func.avg(AnalysisTask.total_cost_usd)).where(
                AnalysisTask.total_cost_usd.isnot(None)
            )
        )
        avg_cost_usd = avg_cost_q.scalar()

        return {
            "total_runs": total_runs,
            "completed_runs": completed_runs,
            "failed_runs": failed_runs,
            "total_cost_usd": round(total_cost_usd, 6) if total_cost_usd else 0.0,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "avg_duration_seconds": (
                round(avg_duration_seconds, 2) if avg_duration_seconds is not None else None
            ),
            "avg_cost_usd": (
                round(avg_cost_usd, 6) if avg_cost_usd is not None else None
            ),
        }
    except Exception as e:
        logger.exception("Error computing run stats")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def list_runs(
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(
        default=None,
        description="Filter by status: completed, failed, running, pending",
    ),
    search: Optional[str] = Query(
        default=None,
        description="Text search on the discovery_summary or phase_details fields",
    ),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List past analysis runs with all metrics, paginated.

    Returns runs ordered by created_at DESC (most recent first).
    """
    try:
        # Build base query
        base_filter = []

        # Status filter
        if status:
            status_lower = status.lower()
            if status_lower == "running":
                # "running" encompasses all in-progress statuses
                running_statuses = [
                    s.value
                    for s in AnalysisTaskStatus
                    if s
                    not in (
                        AnalysisTaskStatus.COMPLETED,
                        AnalysisTaskStatus.FAILED,
                        AnalysisTaskStatus.CANCELLED,
                        AnalysisTaskStatus.PENDING,
                    )
                ]
                base_filter.append(AnalysisTask.status.in_(running_statuses))
            elif status_lower == "completed":
                base_filter.append(
                    AnalysisTask.status == AnalysisTaskStatus.COMPLETED.value
                )
            elif status_lower == "failed":
                base_filter.append(
                    AnalysisTask.status == AnalysisTaskStatus.FAILED.value
                )
            elif status_lower == "pending":
                base_filter.append(
                    AnalysisTask.status == AnalysisTaskStatus.PENDING.value
                )

        # Text search filter
        if search:
            search_pattern = f"%{search}%"
            base_filter.append(
                (AnalysisTask.discovery_summary.ilike(search_pattern))
                | (AnalysisTask.phase_details.ilike(search_pattern))
            )

        # Count total matching rows
        count_stmt = select(func.count(AnalysisTask.id))
        for f in base_filter:
            count_stmt = count_stmt.where(f)
        total_result = await db.execute(count_stmt)
        total = total_result.scalar() or 0

        # Fetch paginated results
        offset = (page - 1) * page_size
        query = (
            select(AnalysisTask)
            .order_by(AnalysisTask.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        for f in base_filter:
            query = query.where(f)

        result = await db.execute(query)
        tasks = result.scalars().all()

        return {
            "runs": [task.to_dict() for task in tasks],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.exception("Error listing runs")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{run_id}")
async def get_run_detail(
    run_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get full detail for a single analysis run by ID."""
    result = await db.execute(
        select(AnalysisTask).where(AnalysisTask.id == run_id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return task.to_dict()
