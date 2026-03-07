"""Shared runner for autonomous analysis.

Extracted from the API route so both the HTTP endpoint and the ETL
scheduler can execute the full autonomous pipeline (run + persist +
auto-publish) without duplicating logic.
"""

import logging
from datetime import datetime

from sqlalchemy import select  # type: ignore[import-not-found]

from database import async_session_factory  # type: ignore[import-not-found]
from models.analysis_task import AnalysisTask, AnalysisTaskStatus  # type: ignore[import-not-found]
from analysis.autonomous_engine import get_autonomous_engine  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)


async def run_autonomous_analysis_pipeline(
    task_id: str,
    max_insights: int,
    deep_dive_count: int,
) -> None:
    """Execute the autonomous analysis pipeline for a given task.

    This function owns the full lifecycle:
      1. Mark the task as started (MACRO_SCAN).
      2. Run the autonomous engine.
      3. Persist results and LLM metrics on success.
      4. Auto-publish the report (best-effort).
      5. Mark the task as FAILED on any unhandled exception.

    It creates its own DB sessions so it can be called from both the
    FastAPI background-task context and the APScheduler context.

    Args:
        task_id: The AnalysisTask.id to update with progress/results.
        max_insights: Number of final insights to produce.
        deep_dive_count: Number of opportunities to deep-dive.
    """
    try:
        # Mark task as started
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

        # Persist results
        async with async_session_factory() as session:
            result = await session.execute(
                select(AnalysisTask).where(AnalysisTask.id == task_id)
            )
            task = result.scalar_one_or_none()
            if task:
                task.status = AnalysisTaskStatus.COMPLETED.value
                task.progress = 100
                task.current_phase = "completed"
                task.phase_details = (
                    f"Generated {len(analysis_result.insights)} insights"
                )
                task.completed_at = datetime.utcnow()
                task.elapsed_seconds = analysis_result.elapsed_seconds
                task.result_analysis_id = analysis_result.analysis_id
                task.result_insight_ids = [
                    i.id for i in analysis_result.insights
                ]
                task.discovery_summary = analysis_result.discovery_summary
                task.phases_completed = analysis_result.phases_completed
                task.phase_summaries = analysis_result.phase_summaries

                # Persist pipeline errors so they're visible via the API
                if analysis_result.errors:
                    task.error_message = " | ".join(analysis_result.errors)

                # Market regime
                if analysis_result.macro_result:
                    task.market_regime = (
                        analysis_result.macro_result.market_regime
                    )

                # Top sectors
                if analysis_result.sector_result:
                    task.top_sectors = [
                        s.sector_name
                        for s in analysis_result.sector_result.top_sectors
                    ]
                elif (
                    analysis_result.heatmap_data
                    and analysis_result.heatmap_data.sectors
                ):
                    sorted_sectors = sorted(
                        analysis_result.heatmap_data.sectors,
                        key=lambda s: abs(
                            s.change_20d or s.change_5d or s.change_1d or 0
                        ),
                        reverse=True,
                    )
                    task.top_sectors = [
                        f"{s.name} "
                        f"{(s.change_20d or s.change_5d or s.change_1d or 0):+.1f}%"
                        for s in sorted_sectors[:6]
                    ]

                # LLM usage metrics
                if analysis_result.run_metrics:
                    try:
                        metrics_fields = (
                            analysis_result.run_metrics.to_task_fields()
                        )
                        for field_name, value in metrics_fields.items():
                            setattr(task, field_name, value)
                    except Exception as metrics_err:
                        logger.warning(
                            "Failed to persist run metrics for task %s: %s",
                            task_id,
                            metrics_err,
                        )

                # Supplementary data for report generation
                try:
                    import json as _json

                    supp: dict = {}
                    if analysis_result.factor_scores:
                        supp["factor_scores"] = analysis_result.factor_scores
                    if analysis_result.correlation_highlights:
                        supp["correlation_highlights"] = (
                            analysis_result.correlation_highlights
                        )
                    if analysis_result.catalyst_data:
                        supp["catalyst_data"] = analysis_result.catalyst_data
                    if analysis_result.thematic_analysis:
                        supp["thematic_analysis"] = analysis_result.thematic_analysis
                    if analysis_result.investor_intelligence:
                        supp["investor_intelligence"] = analysis_result.investor_intelligence
                    if supp:
                        task.supplementary_data = _json.dumps(supp)
                except Exception as supp_err:
                    logger.warning(
                        "Failed to persist supplementary data for task %s: %s",
                        task_id,
                        supp_err,
                    )

                await session.commit()
                logger.info(
                    "Background analysis %s completed successfully", task_id
                )

                # Auto-publish (best-effort, never breaks pipeline)
                try:
                    from api.routes.deep_insights import _auto_publish_report  # type: ignore[import-not-found]

                    await _auto_publish_report(task_id)
                except Exception as pub_err:
                    logger.warning(
                        "Auto-publish failed for task %s (non-fatal): %s",
                        task_id,
                        pub_err,
                    )

    except Exception as e:
        logger.error("Background analysis %s failed: %s", task_id, e)
        # Mark task as failed
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
            logger.error(
                "Failed to update task %s with error: %s",
                task_id,
                update_error,
            )
