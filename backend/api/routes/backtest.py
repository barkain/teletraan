"""Backtest API: trigger factor IC backtest and retrieve calibration results."""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, get_current_user
from analysis.backtester import run_backtest, load_calibration

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/backtest", tags=["backtest"])


@router.post("/run")
async def trigger_backtest(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    """Trigger a factor backtest in the background. Results saved to data/backtest_calibration.json."""
    async def _run():
        try:
            result = await run_backtest(db)
            logger.info(
                "Backtest complete: %d symbols, %d snapshots",
                result.get("symbols_tested", 0),
                result.get("snapshots", 0),
            )
        except Exception as exc:
            logger.error("Backtest failed: %s", exc)

    background_tasks.add_task(_run)
    return {"status": "started", "message": "Backtest running in background. Poll /backtest/results for output."}


@router.get("/results")
async def get_backtest_results(
    _: str = Depends(get_current_user),
) -> dict:
    """Return the most recent backtest calibration results."""
    cal = load_calibration()
    if cal is None:
        raise HTTPException(status_code=404, detail="No backtest calibration available. Run POST /backtest/run first.")
    return cal
