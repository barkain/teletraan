"""Backtest API: trigger factor IC backtest and retrieve calibration results."""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import update as sql_update, select

from api.deps import get_db, get_current_user
from database import async_session_factory
from models.deep_insight import DeepInsight
from models.portfolio import Portfolio
from analysis.backtester import (
    run_backtest,
    load_calibration,
    run_strategy_backtest,
    load_strategy_backtest,
    get_today_picks,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/backtest", tags=["backtest"])


async def _load_portfolio_context() -> tuple[dict[str, dict], str]:
    """Return (holdings_dict, formatted_markdown) for the synthesis prompt.

    holdings_dict maps symbol → {shares, cost_basis, total_cost}.
    Returns ({}, "") if no portfolio exists or on any error.
    """
    try:
        async with async_session_factory() as session:
            result = await session.execute(select(Portfolio).limit(1))
            portfolio = result.scalar_one_or_none()
            if not portfolio or not portfolio.holdings:
                return {}, ""
            holdings: dict[str, dict] = {
                h.symbol.upper(): {
                    "shares": h.shares,
                    "cost_basis": h.cost_basis,
                    "total_cost": h.shares * h.cost_basis,
                }
                for h in portfolio.holdings
            }
    except Exception as e:
        logger.warning("Failed to load portfolio (non-fatal): %s", e)
        return {}, ""

    total_cost = sum(h["total_cost"] for h in holdings.values())
    lines = [
        "",
        "## Current Portfolio Holdings",
        "The user holds the following positions. For EACH held symbol that appears "
        "in the analysis, you MUST produce an insight with one of three actions:",
        "  - **BUY_MORE**: thesis is bullish, add to the position",
        "  - **HOLD**: thesis is neutral, keep current size",
        "  - **SELL**: thesis is bearish, reduce or exit",
        "",
        "Also assess how new picks interact with the portfolio: flag sector "
        "concentration risk, correlation with held names, and diversification impact.",
        "",
    ]
    for symbol, info in sorted(holdings.items(), key=lambda x: x[1]["total_cost"], reverse=True):
        alloc = (info["total_cost"] / total_cost * 100) if total_cost > 0 else 0
        lines.append(
            f"- {symbol}: {info['shares']:.1f} shares @ ${info['cost_basis']:.2f} "
            f"cost basis ({alloc:.1f}% of portfolio)"
        )
    lines.append(
        "\nDo NOT use BUY for a stock already in the portfolio — use BUY_MORE instead."
    )
    return holdings, "\n".join(lines)


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


@router.post("/strategy-run")
async def trigger_strategy_backtest(
    background_tasks: BackgroundTasks,
    n_picks: int = 5,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    """Trigger walk-forward strategy simulation in the background.

    Scores all symbols monthly using IC-calibrated signals (volatility dominant),
    picks top n_picks, tracks equal-weight portfolio vs SPY at 20/45/90d horizons.
    Results saved to data/strategy_backtest.json.
    """
    async def _run() -> None:
        try:
            result = await run_strategy_backtest(db, n_picks=n_picks)
            logger.info(
                "Strategy backtest complete: %d snapshots, summary=%s",
                result.get("snapshots_run", 0),
                result.get("summary", {}),
            )
        except Exception:
            logger.exception("Strategy backtest failed")

    background_tasks.add_task(_run)
    return {
        "status": "started",
        "message": f"Strategy backtest running (n_picks={n_picks}). Poll GET /backtest/strategy-results for output.",
    }


@router.get("/strategy-results")
async def get_strategy_results(
    _: str = Depends(get_current_user),
) -> dict:
    """Return the most recent walk-forward strategy backtest results."""
    result = load_strategy_backtest()
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="No strategy backtest available. Run POST /backtest/strategy-run first.",
        )
    return result


@router.get("/today-picks")
async def get_today_picks_endpoint(
    n_picks: int = 15,
    n_candidates: int = 30,
    min_market_cap_m: float = 500,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    """Score all symbols with the IC-calibrated quant scorer, apply a fundamental
    quality gate on the top candidates, and return today's top picks.

    Hybrid approach: Scorer B (volatility/bb_width/vol_ratio IC-weights) ranks
    candidates purely on price signals, then fundamentals from Yahoo Finance
    filter out micro-caps and revenue-declining names.
    """
    return await get_today_picks(
        db,
        n_picks=n_picks,
        n_candidates=n_candidates,
        min_market_cap=min_market_cap_m * 1_000_000,
    )


@router.post("/deep-picks")
async def trigger_deep_picks(
    background_tasks: BackgroundTasks,
    n_candidates: int = 15,
    min_market_cap_m: float = 500,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    """Full hybrid pipeline: IC-calibrated quant scorer nominates candidates,
    DeepAnalysisEngine runs multi-agent analysis on those symbols.

    Step 1 (sync, fast): Scorer B ranks all 200+ symbols → fundamental quality
    gate → top n_candidates survivors.
    Step 2 (background): DeepAnalysisEngine runs 5 specialist analysts in
    parallel on those symbols → synthesises investment theses → stores to DB.

    Poll GET /api/v1/deep-insights for results.
    """
    from analysis.deep_engine import get_deep_analysis_engine

    quant_result = await get_today_picks(
        db,
        n_picks=n_candidates,
        n_candidates=n_candidates * 2,
        min_market_cap=min_market_cap_m * 1_000_000,
    )

    if "error" in quant_result:
        raise HTTPException(status_code=500, detail=quant_result["error"])

    candidate_symbols = [p["symbol"] for p in quant_result.get("picks", [])]
    if not candidate_symbols:
        raise HTTPException(status_code=404, detail="No candidates passed quality gate")

    engine = get_deep_analysis_engine()
    quant_context = quant_result.get("quant_context")
    # Build lookup: symbol → (score, rank) for reconciliation tagging
    quant_scores: dict[str, tuple[float, int]] = {
        p["symbol"]: (p.get("quant_score", 0.0), rank + 1)
        for rank, p in enumerate(quant_result.get("picks", []))
    }

    portfolio_holdings, portfolio_ctx_str = await _load_portfolio_context()
    held_candidates = [s for s in candidate_symbols if s in portfolio_holdings]
    if held_candidates:
        logger.info("Portfolio overlap with candidates: %s", held_candidates)

    async def _run_deep() -> None:
        try:
            insights = await engine.run_and_store(
                symbols=candidate_symbols,
                quant_context=quant_context,
                portfolio_context=portfolio_ctx_str or None,
            )
            logger.info(
                "Deep picks complete: %d insights from candidates %s",
                len(insights),
                candidate_symbols,
            )
            # Tag each insight with discovery source so quant-nominated and
            # agent-discovered picks are distinguishable downstream.
            async with async_session_factory() as session:
                for insight in insights:
                    sym = insight.primary_symbol
                    ctx = dict(insight.discovery_context or {})
                    if sym in quant_scores:
                        score, rank = quant_scores[sym]
                        ctx.update({
                            "discovery_source": "quant_nominated",
                            "quant_score": score,
                            "quant_rank": rank,
                        })
                    else:
                        ctx["discovery_source"] = "agent_discovered"
                    ctx["in_portfolio"] = sym in portfolio_holdings
                    await session.execute(
                        sql_update(DeepInsight)
                        .where(DeepInsight.id == insight.id)
                        .values(discovery_context=ctx)
                    )
                await session.commit()
        except Exception:
            logger.exception("Deep picks analysis failed")

    background_tasks.add_task(_run_deep)

    return {
        "status": "started",
        "regime": quant_result.get("regime"),
        "regime_note": quant_result.get("regime_note"),
        "candidates": quant_result.get("picks", []),
        "n_candidates": len(candidate_symbols),
        "portfolio_overlap": held_candidates,
        "message": (
            f"Deep analysis running on {candidate_symbols}. "
            "Poll GET /api/v1/deep-insights for results."
        ),
    }
