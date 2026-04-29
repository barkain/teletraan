"""Zero-paid-keys smoke test for the v2 alpha engine.

This script runs the deterministic scoring path only:
- builds the market universe
- detects the current market regime
- runs factor scoring and portfolio overlay logic
- prints the top ranked candidates

It intentionally skips the synthesis / LLM step so it can be used as a
no-cost smoke test even when FRED_API_KEY and FINNHUB_API_KEY are unset.

Usage:
    cd backend && uv run python scripts/smoke_alpha_zero_keys.py
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

# Add backend directory to path for imports
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Use a temp DB so the smoke test never touches the production database
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./data/smoke_test.db")

from config import get_settings  # type: ignore[import-not-found]
from database import async_session_factory, init_db  # type: ignore[import-not-found]
from analysis.alpha_engine import (  # type: ignore[import-not-found]
    build_market_universe,
    detect_market_regime,
    run_daily_factor_scoring,
)
from models.alpha_engine import AnalysisRun, AnalysisRunStatus  # type: ignore[import-not-found]


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
NY_TZ = ZoneInfo("America/New_York")


def _format_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, (int, bool)):
        return str(value)
    return str(value)


def _print_candidates(candidates: list[dict[str, Any]], top_n: int) -> None:
    print("\nTop candidates")
    print("=" * 120)
    header = f"{'#':>3}  {'Symbol':<8} {'Score':>7} {'Conf':>6} {'Thesis':<14} {'Holding':<8} {'Drivers'}"
    print(header)
    print("-" * 120)
    for candidate in candidates[:top_n]:
        drivers = ", ".join(candidate.get("key_drivers", [])[:6])
        print(
            f"{_format_value(candidate.get('rank')):>3}  "
            f"{_format_value(candidate.get('symbol')):<8} "
            f"{_format_value(candidate.get('score')):>7} "
            f"{_format_value(candidate.get('confidence')):>6} "
            f"{_format_value(candidate.get('thesis_type')):<14} "
            f"{str(bool(candidate.get('is_portfolio_holding'))):<8} "
            f"{drivers}"
        )


def _print_overlay(overlay: dict[str, Any]) -> None:
    print("\nPortfolio overlay")
    print("=" * 120)
    print(f"Concentration risk: {_format_value(overlay.get('concentration_risk'))}")
    top_sector = overlay.get("top_sector") or {}
    if top_sector:
        print(
            f"Top sector: {top_sector.get('sector', '-')}"
            f" ({_format_value(top_sector.get('weight'))})"
        )
    suggestions = overlay.get("suggestions", []) or []
    if not suggestions:
        print("Suggestions: none")
        return
    print("\nSuggestions")
    print("-" * 120)
    for suggestion in suggestions[:10]:
        print(
            f"- {suggestion.get('symbol', '-')}: {suggestion.get('action', '-')}"
            f" | score={_format_value(suggestion.get('score'))}"
            f" | conf={_format_value(suggestion.get('confidence'))}"
        )
        reason = suggestion.get("reason")
        if reason:
            print(f"  reason: {reason}")


async def _run(top_n: int) -> None:
    settings = get_settings()
    logger.info("Database: %s", settings.DATABASE_URL)
    logger.info("SEC user agent: %s", settings.SEC_USER_AGENT)
    logger.info("FRED_API_KEY set: %s", bool(settings.FRED_API_KEY))
    logger.info("FINNHUB_API_KEY set: %s", bool(settings.FINNHUB_API_KEY))

    await init_db()

    async with async_session_factory() as db:
        run = AnalysisRun(
            run_type="smoke_zero_keys",
            status=AnalysisRunStatus.RUNNING.value,
            market_date=datetime.now(NY_TZ).date(),
        )
        db.add(run)
        await db.flush()

        universe = await build_market_universe(db)
        regime = await detect_market_regime()
        scoring = await run_daily_factor_scoring(db, run, universe, regime)

        run.status = AnalysisRunStatus.COMPLETED.value
        await db.commit()

    print("\nZero-paid-keys alpha smoke test")
    print("=" * 120)
    print(f"Analysis run id: {run.id}")
    print(f"Market date: {run.market_date}")
    print(f"Universe size: {len(universe.all_symbols)}")
    print(f"Regime: {regime.name} (confidence {regime.confidence:.2f})")
    if regime.evidence:
        print("Regime evidence:")
        for item in regime.evidence[:6]:
            print(f"  - {item}")

    _print_overlay(scoring["portfolio_overlay"])
    candidate_rows = [
        {
            "rank": candidate.rank,
            "symbol": candidate.symbol,
            "score": candidate.overall_score,
            "confidence": candidate.confidence,
            "thesis_type": candidate.thesis_type,
            "is_portfolio_holding": candidate.is_portfolio_holding,
            "key_drivers": candidate.key_drivers,
        }
        for candidate in scoring["candidate_rows"]
    ]
    _print_candidates(candidate_rows, top_n=top_n)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the deterministic v2 alpha smoke test.")
    parser.add_argument("--top-n", type=int, default=10, help="How many ranked candidates to print.")
    args = parser.parse_args()
    asyncio.run(_run(top_n=max(1, args.top_n)))


if __name__ == "__main__":
    main()
