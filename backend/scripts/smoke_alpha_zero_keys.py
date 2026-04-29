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

db_path = backend_dir.parent / "data" / "market-analyzer.db"
if db_path.exists():
    os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
else:
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from config import get_settings  # type: ignore[import-not-found]
from database import async_session_factory, engine, init_db  # type: ignore[import-not-found]
from db_utils import dialect_insert  # type: ignore[import-not-found]
from analysis.context_builder import MarketContextBuilder  # type: ignore[import-not-found]
from analysis.alpha_engine import (  # type: ignore[import-not-found]
    MarketUniverse,
    detect_market_regime,
    run_daily_factor_scoring,
)
from models.alpha_engine import AnalysisRun, AnalysisRunStatus  # type: ignore[import-not-found]
from models.price import PriceHistory  # type: ignore[import-not-found]
from models.stock import Stock  # type: ignore[import-not-found]
from data.adapters.yahoo import YahooFinanceAdapter  # type: ignore[import-not-found]
from sqlalchemy import select  # type: ignore[import-not-found]


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
NY_TZ = ZoneInfo("America/New_York")
SMOKE_SEED_SYMBOLS = [
    "SPY",
    "QQQ",
    "IWM",
    "XLK",
    "XLF",
    "XLE",
    "XLV",
    "XLY",
    "XLI",
    "XLP",
    "XLU",
    "XLC",
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "META",
    "JPM",
    "UNH",
    "XOM",
]


_ORIGINAL_BUILD_CONTEXT = MarketContextBuilder.build_context


async def _deterministic_build_context(self, *args, **kwargs):
    """Force the no-paid-keys smoke path to stay on free/deterministic inputs."""
    kwargs["include_rich_technical"] = False
    kwargs["include_predictions"] = False
    kwargs["include_sentiment"] = False
    kwargs["include_fundamentals"] = False
    kwargs["include_options_flow"] = False
    kwargs["include_short_interest"] = False
    kwargs["include_analyst_revisions"] = False
    return await _ORIGINAL_BUILD_CONTEXT(self, *args, **kwargs)


async def _seed_smoke_data(db) -> int:
    """Seed price history for all smoke symbols so scoring produces real candidates.

    Always re-seeds price history (upsert) regardless of existing stock count,
    because the DB may have stocks from a previous full run without price records.
    """
    adapter = YahooFinanceAdapter()
    seeded = 0
    for symbol in SMOKE_SEED_SYMBOLS:
        try:
            info = await adapter.get_stock_info(symbol)
            stmt = dialect_insert(engine)(Stock).values(
                symbol=info["symbol"],
                name=info.get("name", symbol),
                sector=info.get("sector"),
                industry=info.get("industry"),
                market_cap=info.get("market_cap"),
                is_active=True,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol"],
                set_={
                    "name": stmt.excluded.name,
                    "sector": stmt.excluded.sector,
                    "industry": stmt.excluded.industry,
                    "market_cap": stmt.excluded.market_cap,
                    "is_active": True,
                },
            )
            await db.execute(stmt)

            stock_result = await db.execute(select(Stock).where(Stock.symbol == symbol.upper()))
            stock = stock_result.scalar_one()

            prices = await adapter.get_price_history(symbol, period="3mo")
            for price_data in prices:
                if price_data.get("close") is None or price_data.get("date") is None:
                    continue
                stmt = dialect_insert(engine)(PriceHistory).values(
                    stock_id=stock.id,
                    date=price_data["date"],
                    open=price_data.get("open", 0),
                    high=price_data.get("high", 0),
                    low=price_data.get("low", 0),
                    close=price_data["close"],
                    volume=price_data.get("volume", 0),
                    adjusted_close=price_data.get("adjusted_close"),
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["stock_id", "date"],
                    set_={
                        "open": stmt.excluded.open,
                        "high": stmt.excluded.high,
                        "low": stmt.excluded.low,
                        "close": stmt.excluded.close,
                        "volume": stmt.excluded.volume,
                        "adjusted_close": stmt.excluded.adjusted_close,
                    },
                )
                await db.execute(stmt)
            seeded += 1
        except Exception as exc:
            logger.warning("Smoke seed failed for %s: %s", symbol, exc)
    await db.flush()
    return seeded


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

    MarketContextBuilder.build_context = _deterministic_build_context  # type: ignore[assignment]
    await init_db()

    async with async_session_factory() as seed_db:
        seeded = await _seed_smoke_data(seed_db)
        await seed_db.commit()
        logger.info("Seeded %d smoke symbols", seeded)

    async with async_session_factory() as db:
        run = AnalysisRun(
            run_type="smoke_zero_keys",
            status=AnalysisRunStatus.RUNNING.value,
            market_date=datetime.now(NY_TZ).date(),
        )
        db.add(run)
        await db.flush()

        # Use only the seeded symbols so scoring has price history for all of them.
        # build_market_universe() would return the full DB (264+ stocks) most of
        # which have no PriceHistory rows, causing the scorer to skip them all.
        universe = MarketUniverse(
            as_of=datetime.now(NY_TZ),
            all_symbols=list(SMOKE_SEED_SYMBOLS),
            categories={"smoke": list(SMOKE_SEED_SYMBOLS)},
            portfolio_symbols=[],
            active_stock_symbols=list(SMOKE_SEED_SYMBOLS),
        )
        regime = await detect_market_regime()
        scoring = await run_daily_factor_scoring(db, run, universe, regime)

        run.status = AnalysisRunStatus.COMPLETED.value
        await db.flush()

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
