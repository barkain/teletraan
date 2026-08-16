"""Coverage report for the local ``price_history`` table.

``price_freshness`` answers "is *this* price current" at read time, one symbol
at a time, inside an analysis run.  Nothing answered the operator-level
question: *is the table as a whole still being fed?*

It went unanswered for three and a half months.  The ETL was refreshing 16
hard-coded benchmark symbols while the other ~380 tickers sat frozen on the day
their universe-expansion backfill seeded them, and no log line, endpoint or
startup check said so.  Every read-time consumer papered over it individually --
the context builder re-quoted stale symbols live, the eval harness topped up
from yfinance -- so the outage looked like slowness rather than a broken feed.

This module supplies the missing table-wide view:

* :func:`price_coverage_report` -- one query pass over ``price_history``,
  classifying every active stock as current / stale / missing, plus an interior
  gap count for the benchmark.
* :func:`format_coverage_report` -- a one-line log rendering.

Staleness uses the same vocabulary as :mod:`analysis.price_freshness` so the
ETL, the analysts and the operator never disagree about what "stale" means.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from analysis.price_freshness import (  # type: ignore[import-not-found]
    STALE_AFTER_TRADING_DAYS,
    last_weekday,
    trading_days_between,
)
from models.price import PriceHistory  # type: ignore[import-not-found]
from models.stock import Stock  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)

#: Benchmark whose interior holes are reported explicitly.  A stale *benchmark*
#: is worse than a stale symbol: everything benchmark-relative in this codebase
#: (alpha, hit rate, relative strength) silently voids its window when the SPY
#: series has a hole, so it gets its own line in the report.
DEFAULT_BENCHMARK = "SPY"

#: How far back to look for interior gaps in the benchmark series.
BENCHMARK_GAP_WINDOW_DAYS = 90

#: A coverage report is unhealthy when this fraction of tracked symbols or more
#: is stale.  One symbol going quiet is a delisting; a tenth of the table going
#: quiet is a broken feed.
UNHEALTHY_STALE_FRACTION = 0.10

#: How many stale symbols to name in the report (the full list is a wall of
#: text when the feed is fully down).
STALE_SAMPLE_SIZE = 10


def _evaluation_date(as_of: date | None) -> date:
    """Normalise an evaluation date back to the preceding weekday.

    A Sunday run must not call Friday's bar stale.
    """
    return last_weekday(
        as_of if as_of is not None else datetime.now(timezone.utc).date()
    )


async def price_coverage_report(
    session: AsyncSession,
    *,
    as_of: date | None = None,
    benchmark: str = DEFAULT_BENCHMARK,
    stale_after_trading_days: int = STALE_AFTER_TRADING_DAYS,
    sample_size: int = STALE_SAMPLE_SIZE,
) -> dict[str, Any]:
    """Summarise how well ``price_history`` covers the active stock universe.

    Args:
        session: Database session.
        as_of: Evaluation date; defaults to today (UTC).
        benchmark: Symbol to report interior gaps for.
        stale_after_trading_days: Trading-day age past which a symbol's latest
            bar counts as stale.
        sample_size: How many stale symbols to name.

    Returns:
        Dict with ``as_of``, ``symbols_tracked``, ``symbols_current``,
        ``symbols_stale``, ``symbols_missing``, ``total_rows``,
        ``latest_bar_date``, ``stale_symbols`` (worst-first sample),
        ``benchmark`` and ``is_healthy``.
    """
    evaluated = _evaluation_date(as_of)

    latest_rows = (
        await session.execute(
            select(Stock.symbol, func.max(PriceHistory.date))
            .select_from(Stock)
            .outerjoin(PriceHistory, PriceHistory.stock_id == Stock.id)
            .where(Stock.is_active.is_(True))
            .group_by(Stock.symbol)
        )
    ).all()

    total_rows = int(
        (await session.execute(select(func.count()).select_from(PriceHistory))).scalar()
        or 0
    )

    current_count = 0
    stale: list[tuple[str, date, int]] = []
    missing: list[str] = []
    latest_bar_date: date | None = None

    for symbol, raw_latest in latest_rows:
        bar_date = _as_date(raw_latest)
        if bar_date is None:
            missing.append(str(symbol))
            continue
        if latest_bar_date is None or bar_date > latest_bar_date:
            latest_bar_date = bar_date
        age = trading_days_between(bar_date, evaluated)
        if age > stale_after_trading_days:
            stale.append((str(symbol), bar_date, age))
        else:
            current_count += 1

    stale.sort(key=lambda item: (-item[2], item[0]))
    tracked = len(latest_rows)
    unhealthy_count = len(stale) + len(missing)
    is_healthy = (
        tracked > 0
        and unhealthy_count < max(1, int(tracked * UNHEALTHY_STALE_FRACTION))
    )

    return {
        "as_of": evaluated.isoformat(),
        "symbols_tracked": tracked,
        "symbols_current": current_count,
        "symbols_stale": len(stale),
        "symbols_missing": len(missing),
        "total_rows": total_rows,
        "latest_bar_date": latest_bar_date.isoformat() if latest_bar_date else None,
        "stale_symbols": [
            {
                "symbol": symbol,
                "latest_bar_date": bar_date.isoformat(),
                "trading_days_behind": age,
            }
            for symbol, bar_date, age in stale[:sample_size]
        ],
        "missing_symbols": sorted(missing)[:sample_size],
        "benchmark": await benchmark_gap_report(
            session, benchmark=benchmark, as_of=evaluated
        ),
        "is_healthy": is_healthy,
    }


async def benchmark_gap_report(
    session: AsyncSession,
    *,
    benchmark: str = DEFAULT_BENCHMARK,
    as_of: date | None = None,
    window_days: int = BENCHMARK_GAP_WINDOW_DAYS,
) -> dict[str, Any]:
    """Count *interior* holes in the benchmark series over a recent window.

    Trailing staleness ("the last bar is old") and interior holes ("there are
    no July bars but there are August ones") have different causes and need
    different fixes, so they are counted separately.  Interior holes are the
    signature of a refresh whose lookback window is shorter than the outage
    that preceded it: each run writes only the few days it can see and leaves
    everything older permanently unwritten.

    Exchange holidays are not modelled, so a handful of missing weekdays per
    quarter is expected; the number is a signal, not an audit.
    """
    evaluated = _evaluation_date(as_of)
    window_start = evaluated - timedelta(days=window_days)

    stock_id = (
        await session.execute(
            select(Stock.id).where(Stock.symbol == benchmark.upper())
        )
    ).scalar_one_or_none()

    if stock_id is None:
        return {
            "symbol": benchmark.upper(),
            "present": False,
            "latest_bar_date": None,
            "bars_in_window": 0,
            "weekdays_in_window": 0,
            "missing_weekdays": 0,
        }

    bar_dates = {
        _as_date(row[0])
        for row in (
            await session.execute(
                select(PriceHistory.date)
                .where(PriceHistory.stock_id == stock_id)
                .where(PriceHistory.date >= window_start)
                .where(PriceHistory.date <= evaluated)
            )
        ).all()
    }
    bar_dates.discard(None)

    latest = (
        await session.execute(
            select(func.max(PriceHistory.date)).where(
                PriceHistory.stock_id == stock_id
            )
        )
    ).scalar()

    weekdays = _weekdays_between(window_start, evaluated)
    return {
        "symbol": benchmark.upper(),
        "present": True,
        "latest_bar_date": _iso(latest),
        "bars_in_window": len(bar_dates),
        "weekdays_in_window": len(weekdays),
        "missing_weekdays": len([d for d in weekdays if d not in bar_dates]),
    }


def format_coverage_report(report: dict[str, Any]) -> str:
    """Render a coverage report as a single log line."""
    bench = report.get("benchmark") or {}
    bench_part = (
        f"{bench.get('symbol', '?')} last={bench.get('latest_bar_date')} "
        f"missing_weekdays={bench.get('missing_weekdays')}/"
        f"{bench.get('weekdays_in_window')}"
    )
    worst = ", ".join(
        f"{item['symbol']}@{item['latest_bar_date']}"
        for item in report.get("stale_symbols", [])[:5]
    )
    return (
        f"price coverage as_of={report.get('as_of')}: "
        f"{report.get('symbols_current')}/{report.get('symbols_tracked')} current, "
        f"{report.get('symbols_stale')} stale, "
        f"{report.get('symbols_missing')} with no bars, "
        f"{report.get('total_rows')} rows, latest={report.get('latest_bar_date')}; "
        f"benchmark {bench_part}"
        + (f"; worst: {worst}" if worst else "")
    )


def log_coverage_report(report: dict[str, Any]) -> None:
    """Log the coverage report at a level that matches its health."""
    line = format_coverage_report(report)
    if report.get("is_healthy"):
        logger.info(line)
    else:
        logger.warning("PRICE COVERAGE DEGRADED -- %s", line)


def _weekdays_between(start: date, end: date) -> list[date]:
    """Every weekday in the inclusive interval ``[start, end]``."""
    days: list[date] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _as_date(value: Any) -> date | None:
    """Coerce a SQLite/PostgreSQL date column value into a ``date``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _iso(value: Any) -> str | None:
    coerced = _as_date(value)
    return coerced.isoformat() if coerced else None
