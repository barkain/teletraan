"""ETL orchestrator for market data pipelines using APScheduler.

This module provides scheduled data fetching and storage for stock prices,
economic indicators, and analysis pipelines.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-not-found]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-not-found]
from apscheduler.triggers.date import DateTrigger  # type: ignore[import-not-found]
from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-not-found]
from sqlalchemy import func, select  # type: ignore[import-not-found]
from db_utils import dialect_insert  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from database import async_session_factory, engine  # type: ignore[import-not-found]
from data.adapters.yahoo import yahoo_adapter  # type: ignore[import-not-found]
from data.adapters.fred import fred_adapter  # type: ignore[import-not-found]
from models.stock import Stock  # type: ignore[import-not-found]
from models.price import PriceHistory  # type: ignore[import-not-found]
from models.economic import EconomicIndicator  # type: ignore[import-not-found]
from models.analysis_task import AnalysisTask, AnalysisTaskStatus  # type: ignore[import-not-found]
from analysis.engine import AnalysisEngine  # type: ignore[import-not-found]
from analysis.price_coverage import (  # type: ignore[import-not-found]
    log_coverage_report,
    price_coverage_report,
)
from analysis.price_freshness import (  # type: ignore[import-not-found]
    STALE_AFTER_TRADING_DAYS,
    coerce_date as _coerce_date,
    last_weekday,
    trading_days_between,
)
from analysis.alpha_engine import create_daily_alpha_run  # type: ignore[import-not-found]
from analysis.outcome_tracker import InsightOutcomeTracker  # type: ignore[import-not-found]
from analysis.thematic_outcome_tracker import ThematicOutcomeTracker  # type: ignore[import-not-found]
from analysis.memory_service import InstitutionalMemoryService  # type: ignore[import-not-found]
from analysis.statistical_calculator import StatisticalFeatureCalculator  # type: ignore[import-not-found]
from config import get_settings  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)

#: Days of settled history re-fetched behind a symbol's newest stored bar.
#: yfinance revises recent bars (splits, dividends, late prints), so the daily
#: refresh overlaps rather than appending blindly.
PRICE_REFRESH_OVERLAP_DAYS = 5

#: Lookback used for a symbol that has no stored bars at all.  Wide enough for
#: the 200-day moving averages the technical analysts compute.
PRICE_INITIAL_LOOKBACK_DAYS = 400

#: Ceiling on any single symbol's refresh window.  A symbol frozen for years
#: should not trigger an unbounded download on a nightly job.
PRICE_REFRESH_MAX_LOOKBACK_DAYS = 800

#: Concurrent yfinance fetches.  yfinance is unofficial and rate-limits by IP;
#: six in flight refreshes ~400 symbols in a couple of minutes without tripping
#: it, and each fetch already runs in the shared thread-pool executor.
PRICE_REFRESH_CONCURRENCY = 6

#: How many failed symbols to name in the failure log line.
PRICE_FAILURE_SAMPLE_SIZE = 10

#: Window the catch-up scans for *interior* holes.  Trailing staleness is not
#: the only failure mode: SPY had a bar for yesterday and no bars at all for
#: July, because every past run could only see five days back.  A symbol whose
#: newest bar is current can still be full of holes, so the catch-up measures
#: bar density over this window rather than trusting the newest bar alone.
PRICE_GAP_SCAN_DAYS = 120

#: Fraction of the window's weekdays a symbol must have bars for before its
#: history counts as intact.  Exchange holidays cost roughly 4% of weekdays per
#: quarter, so 0.90 tolerates them without tolerating a real hole.
PRICE_GAP_DENSITY_THRESHOLD = 0.90


def _chunks(items: list[str], size: int) -> list[list[str]]:
    """Split *items* into consecutive lists of at most *size* elements."""
    return [items[i:i + size] for i in range(0, len(items), size)]


@dataclass
class PriceRefreshReport:
    """Structured outcome of a price refresh pass.

    The refresh used to return ``dict[symbol, int]`` and set the count to ``0``
    on exception, which made "this symbol raised" indistinguishable from "this
    symbol had no new bars".  Nothing aggregated it and nothing looked at it,
    so a run in which every single symbol failed logged exactly like a healthy
    one.  This report separates the two and carries the requested-vs-written
    counts a caller needs to tell a partial failure from a success.
    """

    requested: int = 0
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped_current: int = 0
    returned_no_data: int = 0
    bars_written: int = 0
    new_bars: int = 0
    duration_seconds: float = 0.0
    per_symbol: dict[str, int] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    no_data_symbols: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """True when every requested symbol was accounted for without error."""
        return (
            self.failed == 0
            and self.attempted + self.skipped_current == self.requested
        )

    def as_dict(self) -> dict[str, Any]:
        """JSON-serialisable view for API responses and structured logs."""
        return {
            "requested": self.requested,
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped_current": self.skipped_current,
            "returned_no_data": self.returned_no_data,
            "bars_written": self.bars_written,
            "new_bars": self.new_bars,
            "duration_seconds": round(self.duration_seconds, 2),
            "is_complete": self.is_complete,
            "failures": dict(
                sorted(self.failures.items())[:PRICE_FAILURE_SAMPLE_SIZE]
            ),
            "no_data_symbols": sorted(self.no_data_symbols)[
                :PRICE_FAILURE_SAMPLE_SIZE
            ],
        }

    def summary(self) -> str:
        """One-line human-readable rendering."""
        return (
            f"price refresh: {self.succeeded}/{self.requested} symbols ok, "
            f"{self.failed} failed, {self.returned_no_data} returned no data, "
            f"{self.skipped_current} already current, "
            f"{self.new_bars} new bars ({self.bars_written} upserted) "
            f"in {self.duration_seconds:.1f}s"
        )


class ETLOrchestrator:
    """Orchestrates data fetching and storage.

    This class manages scheduled tasks for:
    - Fetching daily stock prices from Yahoo Finance
    - Fetching economic indicators from FRED
    - Running analysis pipelines
    - Backfilling historical data

    Example:
        ```python
        orchestrator = ETLOrchestrator()
        orchestrator.start()

        # Manual fetch
        await orchestrator.fetch_and_store_prices(["AAPL", "MSFT"])

        # Backfill history
        await orchestrator.backfill_history(["AAPL"], days=365)
        ```
    """

    # Default watchlist - major indices + sector ETFs
    DEFAULT_SYMBOLS = [
        "SPY", "QQQ", "DIA", "IWM", "VTI",  # Indices
        "XLK", "XLV", "XLF", "XLE", "XLY",  # Sectors
        "XLI", "XLB", "XLU", "XLRE", "XLC", "XLP",  # More sectors
    ]

    def __init__(self) -> None:
        """Initialize the ETL orchestrator."""
        self.scheduler = AsyncIOScheduler()
        self._is_running = False

    async def _get_or_create_stock(
        self,
        session: AsyncSession,
        symbol: str,
    ) -> Stock:
        """Get existing stock record or create a new one.

        Args:
            session: Database session
            symbol: Stock ticker symbol

        Returns:
            Stock model instance
        """
        # Try to find existing stock
        result = await session.execute(
            select(Stock).where(Stock.symbol == symbol.upper())
        )
        stock = result.scalar_one_or_none()

        if stock:
            return stock

        # Fetch stock info and create new record
        try:
            info = await yahoo_adapter.get_stock_info(symbol)
            stock = Stock(
                symbol=info["symbol"],
                name=info.get("name", symbol),
                sector=info.get("sector"),
                industry=info.get("industry"),
                market_cap=info.get("market_cap"),
                is_active=True,
            )
        except Exception as e:
            logger.warning(f"Could not fetch info for {symbol}: {e}")
            # Create minimal record
            stock = Stock(
                symbol=symbol.upper(),
                name=symbol.upper(),
                is_active=True,
            )

        session.add(stock)
        await session.flush()  # Get the ID without committing
        return stock

    async def _upsert_price(
        self,
        session: AsyncSession,
        stock_id: int,
        price_data: dict[str, Any],
    ) -> None:
        """Insert or update a price record.

        Uses SQLite's INSERT OR REPLACE for upsert behavior.

        Args:
            session: Database session
            stock_id: ID of the stock
            price_data: Price data dict with date, open, high, low, close, volume
        """
        # Skip records with missing required data
        if price_data.get("close") is None or price_data.get("date") is None:
            return

        stmt = dialect_insert(engine)(PriceHistory).values(
            stock_id=stock_id,
            date=price_data["date"],
            open=price_data.get("open", 0),
            high=price_data.get("high", 0),
            low=price_data.get("low", 0),
            close=price_data["close"],
            volume=price_data.get("volume", 0),
            adjusted_close=price_data.get("adjusted_close"),
        )

        # On conflict, update the values
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

        await session.execute(stmt)

    async def _active_symbols(self) -> list[str]:
        """Every active ticker in the DB, unioned with the benchmark set.

        The daily refresh job is registered with no arguments, so ``symbols``
        arrives as ``None`` and used to fall through to ``DEFAULT_SYMBOLS`` --
        sixteen indices and sector ETFs.  The universe-expansion scripts had
        meanwhile grown ``stocks`` to ~400 rows, each seeded once with a
        one-off ``backfill_history`` call and never refreshed again.  Selecting
        from the table is what makes the nightly job cover the universe it is
        supposed to cover.

        ``DEFAULT_SYMBOLS`` stays in the union so the benchmarks are refreshed
        even on a fresh database where ``stocks`` is still empty.
        """
        async with async_session_factory() as session:
            rows = await session.execute(
                select(Stock.symbol).where(Stock.is_active.is_(True))
            )
            db_symbols = [row[0] for row in rows.all() if row[0]]

        merged = {s.upper() for s in db_symbols} | {
            s.upper() for s in self.DEFAULT_SYMBOLS
        }
        return sorted(merged)

    async def _latest_bar_dates(self, symbols: list[str]) -> dict[str, date]:
        """Newest stored bar date per symbol, in one query."""
        if not symbols:
            return {}

        latest: dict[str, date] = {}
        async with async_session_factory() as session:
            # Chunked to stay under SQLite's variable limit on large universes.
            for chunk in _chunks(symbols, 400):
                rows = await session.execute(
                    select(Stock.symbol, func.max(PriceHistory.date))
                    .select_from(Stock)
                    .join(PriceHistory, PriceHistory.stock_id == Stock.id)
                    .where(Stock.symbol.in_(chunk))
                    .group_by(Stock.symbol)
                )
                for symbol, raw in rows.all():
                    coerced = _coerce_date(raw)
                    if coerced is not None:
                        latest[str(symbol).upper()] = coerced
        return latest

    async def _bar_counts_since(
        self,
        symbols: list[str],
        since: date,
    ) -> dict[str, int]:
        """Bars stored per symbol on or after *since*, in one query."""
        if not symbols:
            return {}

        counts: dict[str, int] = {}
        async with async_session_factory() as session:
            for chunk in _chunks(symbols, 400):
                rows = await session.execute(
                    select(Stock.symbol, func.count(PriceHistory.id))
                    .select_from(Stock)
                    .join(PriceHistory, PriceHistory.stock_id == Stock.id)
                    .where(Stock.symbol.in_(chunk))
                    .where(PriceHistory.date >= since)
                    .group_by(Stock.symbol)
                )
                for symbol, count in rows.all():
                    counts[str(symbol).upper()] = int(count or 0)
        return counts

    def _has_interior_gap(self, bars_in_window: int, expected_weekdays: int) -> bool:
        """True when a symbol's recent history is too sparse to be intact.

        A symbol whose *newest* bar is current can still be riddled with holes:
        SPY had a bar for yesterday and none at all for July, because every run
        under the old five-day window wrote only what it could see and left
        everything older permanently unwritten.  Checking the newest bar alone
        calls that symbol healthy, so the catch-up measures density instead.
        """
        if expected_weekdays <= 0:
            return False
        return bars_in_window < expected_weekdays * PRICE_GAP_DENSITY_THRESHOLD

    def _refresh_window(self, last_bar: date | None, today: date) -> date:
        """Start date for a symbol's refresh, derived from what it already has.

        The old job asked yfinance for ``period="5d"`` unconditionally.  That
        window is narrower than any outage longer than a long weekend, so a run
        after a two-week gap wrote the last five days and left the other nine
        permanently unwritten -- which is precisely why the SPY series has no
        July 2026 bars but does have August ones.  Deriving the window from the
        newest stored bar means the first run after any outage closes it.
        """
        if last_bar is None:
            return today - timedelta(days=PRICE_INITIAL_LOOKBACK_DAYS)
        start = last_bar - timedelta(days=PRICE_REFRESH_OVERLAP_DAYS)
        floor = today - timedelta(days=PRICE_REFRESH_MAX_LOOKBACK_DAYS)
        return max(start, floor)

    async def _refresh_one_symbol(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> tuple[int, int]:
        """Fetch and upsert one symbol's bars.

        Each symbol gets its own session so one failure cannot roll back a
        sibling's committed writes.

        Returns:
            ``(bars_upserted, new_bars)`` -- the second counts only dates that
            were not already present, which is the number that tells an
            operator whether a gap actually closed.
        """
        prices = await yahoo_adapter.get_price_history(
            symbol, start_date=start_date, end_date=end_date
        )
        if not prices:
            return 0, 0

        async with async_session_factory() as session:
            stock = await self._get_or_create_stock(session, symbol)

            existing_rows = await session.execute(
                select(PriceHistory.date)
                .where(PriceHistory.stock_id == stock.id)
                .where(PriceHistory.date >= start_date)
            )
            existing = {
                coerced
                for coerced in (_coerce_date(row[0]) for row in existing_rows.all())
                if coerced is not None
            }

            written = 0
            new_bars = 0
            for price in prices:
                if price.get("close") is None or price.get("date") is None:
                    continue
                await self._upsert_price(session, stock.id, price)
                written += 1
                if _coerce_date(price["date"]) not in existing:
                    new_bars += 1

            await session.commit()

        return written, new_bars

    async def fetch_and_store_prices(
        self,
        symbols: list[str] | None = None,
        *,
        stale_only: bool = False,
    ) -> PriceRefreshReport:
        """Refresh daily bars for the active universe and store them.

        Every symbol's fetch window is derived from its own stored history, so
        this single method serves both the nightly refresh and the catch-up
        backfill: a symbol that is current downloads a few overlapping days, a
        symbol three months behind downloads three months, and a symbol that is
        current but full of interior holes downloads the whole scan window.

        Args:
            symbols: Symbols to refresh.  Defaults to every active stock in the
                DB unioned with :attr:`DEFAULT_SYMBOLS`.
            stale_only: Skip symbols whose recent history is both current and
                intact.  Used by the startup catch-up so a warm database costs
                almost nothing.

        Returns:
            A :class:`PriceRefreshReport` counting what was requested, written
            and failed.  Failures are never folded into a zero count.
        """
        started = time.monotonic()
        resolved = (
            [s.upper() for s in symbols]
            if symbols is not None
            else await self._active_symbols()
        )
        report = PriceRefreshReport(requested=len(resolved))
        if not resolved:
            logger.warning("Price refresh requested with no symbols to fetch")
            return report

        today = date.today()
        as_of = last_weekday(today)
        scan_start = today - timedelta(days=PRICE_GAP_SCAN_DAYS)
        latest = await self._latest_bar_dates(resolved)
        bar_counts = await self._bar_counts_since(resolved, scan_start)
        expected_weekdays = trading_days_between(
            scan_start - timedelta(days=1), as_of
        )

        plan: list[tuple[str, date]] = []
        gapped = 0
        for symbol in resolved:
            last_bar = latest.get(symbol)
            has_gap = last_bar is not None and self._has_interior_gap(
                bar_counts.get(symbol, 0), expected_weekdays
            )
            if has_gap:
                gapped += 1
            if stale_only and last_bar is not None and not has_gap:
                if trading_days_between(last_bar, as_of) <= STALE_AFTER_TRADING_DAYS:
                    report.skipped_current += 1
                    continue
            start = self._refresh_window(last_bar, today)
            # An interior hole sits *behind* the newest bar, so the window
            # derived from that bar cannot reach it.  Widen to the scan window.
            if has_gap:
                start = min(start, scan_start)
            plan.append((symbol, start))

        logger.info(
            "Price refresh starting: %d symbols to fetch (%d with interior gaps), "
            "%d already current",
            len(plan),
            gapped,
            report.skipped_current,
        )

        # yfinance rate-limits by IP, so the fan-out is bounded rather than
        # unleashing ~400 concurrent downloads.
        semaphore = asyncio.Semaphore(PRICE_REFRESH_CONCURRENCY)
        # end is exclusive in yfinance's history(); +1 day includes today's bar.
        end_date = today + timedelta(days=1)

        async def _run(symbol: str, start_date: date) -> None:
            async with semaphore:
                try:
                    written, new_bars = await self._refresh_one_symbol(
                        symbol, start_date, end_date
                    )
                except Exception as e:  # noqa: BLE001 -- recorded, not swallowed
                    report.failed += 1
                    report.failures[symbol] = f"{type(e).__name__}: {e}"
                    logger.warning("Price refresh failed for %s: %s", symbol, e)
                    return
                report.succeeded += 1
                report.bars_written += written
                report.new_bars += new_bars
                report.per_symbol[symbol] = new_bars
                # "The request succeeded and returned nothing" is its own
                # outcome -- a delisted or renamed ticker that will never
                # catch up no matter how often the job runs.  Counting it as
                # a plain success is how 19 dead symbols stayed invisible.
                if written == 0:
                    report.returned_no_data += 1
                    report.no_data_symbols.append(symbol)

        report.attempted = len(plan)
        await asyncio.gather(*(_run(symbol, start) for symbol, start in plan))

        report.duration_seconds = time.monotonic() - started

        # A partial failure has to be loud.  The previous implementation logged
        # one line per symbol and nothing in aggregate, so a run in which every
        # symbol raised looked identical to a healthy one in the log.
        if report.failed:
            logger.error(
                "%s -- %d symbols failed: %s",
                report.summary(),
                report.failed,
                ", ".join(
                    sorted(report.failures)[:PRICE_FAILURE_SAMPLE_SIZE]
                ),
            )
        else:
            logger.info(report.summary())

        if report.returned_no_data:
            logger.warning(
                "%d symbols returned no data at all (likely delisted or "
                "renamed): %s",
                report.returned_no_data,
                ", ".join(
                    sorted(report.no_data_symbols)[:PRICE_FAILURE_SAMPLE_SIZE]
                ),
            )

        await self.log_price_coverage()
        return report

    async def catch_up_prices(self) -> PriceRefreshReport:
        """Close any accumulated price gap for symbols that are behind.

        The scheduler only fires while the app is up, so a development or
        single-host deployment that is down over a weekend simply never runs
        that night's job -- there is no catch-up in cron semantics.  This runs
        shortly after startup and refreshes only the symbols whose newest bar
        is stale, which makes a gap self-healing instead of something an
        operator has to notice and backfill by hand.
        """
        logger.info("Price catch-up backfill starting")
        report = await self.fetch_and_store_prices(stale_only=True)
        logger.info("Price catch-up backfill complete -- %s", report.summary())
        return report

    async def log_price_coverage(self) -> dict[str, Any]:
        """Compute and log the table-wide price coverage report."""
        try:
            async with async_session_factory() as session:
                report = await price_coverage_report(session)
            log_coverage_report(report)
            return report
        except Exception as e:  # noqa: BLE001 -- diagnostics must never break ETL
            logger.warning("Price coverage report failed: %s", e)
            return {}

    async def fetch_economic_indicators(self) -> dict[str, int]:
        """Fetch latest economic data from FRED.

        Returns:
            Dict mapping series IDs to number of records stored
        """
        if not fred_adapter.is_available:
            logger.warning("FRED adapter not available (missing API key)")
            return {}

        logger.info("Fetching economic indicators from FRED")
        results: dict[str, int] = {}

        # Get data from the last 90 days
        end_date = date.today()
        start_date = end_date - timedelta(days=90)

        async with async_session_factory() as session:
            for series_id, description in fred_adapter.SERIES.items():
                try:
                    # Fetch series data
                    data = await fred_adapter.get_series(
                        series_id, start_date, end_date
                    )

                    # Get series info for units
                    info = await fred_adapter.get_series_info(series_id)
                    unit = info.get("units", "")

                    # Store each data point
                    for point in data:
                        stmt = dialect_insert(engine)(EconomicIndicator).values(
                            series_id=series_id,
                            name=description,
                            date=point["date"],
                            value=point["value"],
                            unit=unit,
                            description=info.get("notes"),
                        )

                        stmt = stmt.on_conflict_do_update(
                            index_elements=["series_id", "date"],
                            set_={
                                "value": stmt.excluded.value,
                                "name": stmt.excluded.name,
                                "unit": stmt.excluded.unit,
                            },
                        )

                        await session.execute(stmt)

                    await session.commit()
                    results[series_id] = len(data)
                    logger.info(f"Updated {series_id}: {len(data)} records")

                except Exception as e:
                    logger.error(f"Error fetching {series_id}: {e}")
                    await session.rollback()
                    results[series_id] = 0

        return results

    async def run_analysis(
        self,
        symbols: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run analysis pipeline after data refresh.

        This will compute technical indicators and generate insights
        for all active stocks.

        Args:
            symbols: List of symbols to analyze. Uses DEFAULT_SYMBOLS if not provided.

        Returns:
            Dict containing analysis results summary.
        """
        logger.info("Running analysis pipeline")

        engine = AnalysisEngine()
        results = await engine.run_full_analysis(symbols or self.DEFAULT_SYMBOLS)

        logger.info(
            f"Analysis pipeline completed: {results.get('symbols_analyzed', 0)} symbols, "
            f"{results.get('insights_generated', 0)} insights generated"
        )

        return results

    async def backfill_history(
        self,
        symbols: list[str],
        days: int = 365,
    ) -> dict[str, int]:
        """Backfill historical data for symbols.

        Args:
            symbols: List of symbols to backfill
            days: Number of days of history to fetch

        Returns:
            Dict mapping symbols to number of prices stored
        """
        logger.info(f"Backfilling {days} days of history for {len(symbols)} symbols")

        results: dict[str, int] = {}
        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        async with async_session_factory() as session:
            for symbol in symbols:
                try:
                    # Get or create stock record
                    stock = await self._get_or_create_stock(session, symbol)

                    # Fetch historical price data
                    prices = await yahoo_adapter.get_price_history(
                        symbol,
                        start_date=start_date,
                        end_date=end_date,
                    )

                    # Store prices
                    for price in prices:
                        await self._upsert_price(session, stock.id, price)

                    await session.commit()
                    results[symbol] = len(prices)
                    logger.info(f"Backfilled {symbol}: {len(prices)} prices")

                except Exception as e:
                    logger.error(f"Error backfilling {symbol}: {e}")
                    await session.rollback()
                    results[symbol] = 0

        return results

    async def refresh_stock_info(
        self,
        symbols: list[str] | None = None,
    ) -> int:
        """Refresh stock metadata (name, sector, industry, market cap).

        Args:
            symbols: List of symbols to refresh. If None, refreshes all active stocks.

        Returns:
            Number of stocks updated
        """
        logger.info("Refreshing stock metadata")
        updated = 0

        async with async_session_factory() as session:
            if symbols:
                result = await session.execute(
                    select(Stock).where(Stock.symbol.in_([s.upper() for s in symbols]))
                )
            else:
                result = await session.execute(
                    select(Stock).where(Stock.is_active == True)  # noqa: E712
                )

            stocks = result.scalars().all()

            for stock in stocks:
                try:
                    info = await yahoo_adapter.get_stock_info(stock.symbol)

                    stock.name = info.get("name", stock.name)
                    stock.sector = info.get("sector", stock.sector)
                    stock.industry = info.get("industry", stock.industry)
                    stock.market_cap = info.get("market_cap", stock.market_cap)

                    updated += 1
                except Exception as e:
                    logger.warning(f"Could not refresh info for {stock.symbol}: {e}")

            await session.commit()

        logger.info(f"Refreshed {updated} stocks")
        return updated

    async def check_insight_outcomes(self) -> dict[str, Any]:
        """Daily job to check and update insight outcomes.

        Evaluates all actively tracking insight outcomes to see if predictions
        were validated. Updates current prices, evaluates completed tracking
        periods, and updates pattern success rates based on results.

        Returns:
            Dict containing outcomes_checked and patterns_updated counts.
        """
        logger.info("Running insight outcome check job")

        async with async_session_factory() as session:
            tracker = InsightOutcomeTracker(session)

            # Check all tracking outcomes
            updated_outcomes = await tracker.check_outcomes()

            # Update pattern success rates based on completed outcomes
            patterns_updated = await tracker.update_pattern_success_rates()

            logger.info(
                f"Outcome check complete: {len(updated_outcomes)} outcomes updated, "
                f"{patterns_updated} patterns updated"
            )

            return {
                "outcomes_checked": len(updated_outcomes),
                "patterns_updated": patterns_updated,
            }

    async def decay_theme_relevance(self) -> dict[str, Any]:
        """Daily job to decay conversation theme relevance.

        Applies time-based relevance decay to all active themes and
        deactivates themes that fall below the minimum threshold.

        Returns:
            Dict containing themes_processed and deactivated counts.
        """
        logger.info("Running theme relevance decay job")

        async with async_session_factory() as session:
            memory_service = InstitutionalMemoryService(session)

            # Get all active themes - this applies decay internally
            themes = await memory_service.get_active_themes()

            # Deactivate themes below threshold
            deactivated = 0
            for theme in themes:
                if theme.current_relevance < 0.1:
                    theme.is_active = False
                    deactivated += 1

            await session.commit()

            logger.info(
                f"Theme decay complete: {len(themes)} themes processed, "
                f"{deactivated} themes deactivated"
            )

            return {
                "themes_processed": len(themes),
                "deactivated": deactivated,
            }

    async def compute_daily_features(
        self,
        symbols: list[str] | None = None,
    ) -> dict[str, Any]:
        """Daily job to compute statistical features for watchlist.

        Computes momentum, mean-reversion, volatility, seasonality,
        and cross-sectional features for all watchlist symbols plus
        symbols from recent insights (last 30 days).

        Args:
            symbols: List of symbols to compute. Uses DEFAULT_SYMBOLS if not provided.

        Returns:
            Dict containing features_computed and symbols counts.
        """
        base_symbols = symbols or self.DEFAULT_SYMBOLS

        async with async_session_factory() as session:
            # Also include symbols from recent insights (last 30 days)
            insight_symbols: list[str] = []
            try:
                from datetime import datetime as _dt

                from sqlalchemy import distinct as _distinct  # type: ignore[import-not-found]

                from models.deep_insight import DeepInsight  # type: ignore[import-not-found]

                cutoff = _dt.utcnow() - timedelta(days=30)
                result = await session.execute(
                    select(_distinct(DeepInsight.primary_symbol))
                    .where(DeepInsight.primary_symbol.isnot(None))
                    .where(DeepInsight.created_at >= cutoff)
                )
                insight_symbols = [row[0] for row in result.all() if row[0]]
            except Exception as e:
                logger.warning(f"Failed to fetch insight symbols: {e}")

            all_symbols = list(set(base_symbols + insight_symbols))
            logger.info(
                f"Computing daily statistical features for {len(all_symbols)} symbols "
                f"({len(base_symbols)} base + {len(insight_symbols)} from insights)"
            )

            calculator = StatisticalFeatureCalculator(session)

            # Compute all features
            features = await calculator.compute_all_features(all_symbols)

            await session.commit()

            logger.info(
                f"Feature computation complete: {len(features)} features computed "
                f"for {len(all_symbols)} symbols"
            )

            return {
                "features_computed": len(features),
                "symbols": len(all_symbols),
            }

    async def refresh_investor_feeds(self) -> dict[str, Any]:
        """Refresh investor positions and commentary cache.

        Fetches the latest 13F filings and commentary from tracked
        institutional investors so the data is warm when the autonomous
        analysis pipeline runs later in the day.

        Returns:
            Dict containing positions and commentary counts.
        """
        try:
            from data.adapters.investor_feeds import get_investor_feed_adapter  # type: ignore[import-not-found]
            from data.adapters.sec_filings import get_sec_filings_adapter  # type: ignore[import-not-found]

            adapter = get_investor_feed_adapter()
            sec_adapter = get_sec_filings_adapter()
            data = await adapter.get_all_intelligence()
            positions = len(data.get("positions", []))
            commentary = len(data.get("commentary", []))
            sec_signals = await sec_adapter.get_symbol_signals(self.DEFAULT_SYMBOLS)
            sec_filings = sum(
                int(payload.get("recent_filing_count", 0))
                for payload in sec_signals.values()
            )
            logger.info(
                "Investor feeds refreshed: %d positions, %d commentary items, %d SEC filings",
                positions,
                commentary,
                sec_filings,
            )
            return {
                "positions": positions,
                "commentary": commentary,
                "sec_filings": sec_filings,
            }
        except Exception as e:
            logger.warning("Investor feed refresh failed: %s", e)
            return {
                "positions": 0,
                "commentary": 0,
                "sec_filings": 0,
            }

    async def refresh_earnings_calendar(self) -> dict[str, Any]:
        """Daily job to pre-cache earnings calendar data.

        Fetches earnings calendar for all watchlist/portfolio symbols
        and populates the TTL cache so that analysis pipelines have
        fresh data available.

        Returns:
            Dict containing symbols_fetched and events_found counts.
        """
        from data.adapters.earnings import get_earnings_adapter  # type: ignore[import-not-found]

        logger.info("Refreshing earnings calendar")

        # Gather symbols from default watchlist + portfolio
        all_symbols = list(self.DEFAULT_SYMBOLS)

        try:
            from models.portfolio import PortfolioHolding  # type: ignore[import-not-found]

            async with async_session_factory() as session:
                result = await session.execute(
                    select(PortfolioHolding.symbol).distinct()
                )
                portfolio_symbols = [row[0] for row in result.all() if row[0]]
                all_symbols = list(set(all_symbols + portfolio_symbols))
        except Exception as e:
            logger.debug(f"Could not load portfolio symbols: {e}")

        adapter = get_earnings_adapter()
        try:
            calendar = await adapter.get_earnings_calendar(all_symbols)
            with_dates = sum(
                1
                for info in calendar.values()
                if info.next_earnings_date is not None
            )
            logger.info(
                f"Earnings calendar refreshed: {len(calendar)} symbols fetched, "
                f"{with_dates} have upcoming earnings dates"
            )
            return {
                "symbols_fetched": len(calendar),
                "events_found": with_dates,
            }
        except Exception as e:
            logger.warning(f"Earnings calendar refresh failed: {e}")
            return {
                "symbols_fetched": 0,
                "events_found": 0,
            }

    async def check_insight_lifecycles(self) -> dict[str, Any]:
        """Daily job to check insight lifecycle states and apply decay.

        Evaluates all active insights for staleness, applies conviction
        decay, and triggers state transitions when thresholds are exceeded.

        Returns:
            Dict containing insights_checked and transitions counts.
        """
        logger.info("Running insight lifecycle check job")

        async with async_session_factory() as session:
            tracker = InsightOutcomeTracker(session)
            result = await tracker.check_lifecycle_states(session)

            logger.info(
                "Lifecycle check complete: %d insights checked, %d transitions",
                result.get("insights_checked", 0),
                len(result.get("transitions", [])),
            )

            return result

    async def check_thematic_outcomes(self) -> dict[str, Any]:
        """Daily job to check and update thematic outcome tracking.

        Evaluates all actively tracking thematic outcomes, updates basket
        prices, and evaluates completed tracking periods.

        Returns:
            Dict containing outcomes_checked and patterns_updated counts.
        """
        logger.info("Running thematic outcome check job")

        async with async_session_factory() as session:
            tracker = ThematicOutcomeTracker(session)
            updated_outcomes = await tracker.check_outcomes()
            patterns_updated = await tracker.update_pattern_success_rates()

            logger.info(
                "Thematic outcome check complete: %d outcomes updated, "
                "%d patterns updated",
                len(updated_outcomes),
                patterns_updated,
            )

            return {
                "outcomes_checked": len(updated_outcomes),
                "patterns_updated": patterns_updated,
            }

    async def keepalive_ping(self) -> None:
        """Lightweight periodic ping to prevent Neon PostgreSQL from suspending.

        Neon free-tier auto-suspends compute after 5 minutes of inactivity,
        causing 3-5 second cold-start latency on the next query.  This job
        runs a trivial ``SELECT 1`` every 4 minutes to keep the connection
        warm and avoid that penalty.

        The job is only registered when the DATABASE_URL points at a
        PostgreSQL backend (i.e. it is a no-op for local SQLite dev).
        """
        from sqlalchemy import text as _text  # type: ignore[import-not-found]

        try:
            async with async_session_factory() as session:
                await session.execute(_text("SELECT 1"))
            logger.debug("Neon keepalive ping OK")
        except Exception as e:
            logger.warning("Neon keepalive ping failed: %s", e)

    async def check_thematic_lifecycles(self) -> dict[str, Any]:
        """Daily job to check thematic insight lifecycle states.

        Evaluates all active thematic insights for staleness, applies
        conviction decay, and triggers state transitions.

        Returns:
            Dict containing insights_checked and transitions counts.
        """
        logger.info("Running thematic lifecycle check job")

        async with async_session_factory() as session:
            tracker = ThematicOutcomeTracker(session)
            result = await tracker.check_lifecycle_states(session)

            logger.info(
                "Thematic lifecycle check complete: %d insights checked, %d transitions",
                result.get("insights_checked", 0),
                len(result.get("transitions", [])),
            )

            return result

    async def run_scheduled_autonomous_analysis(self) -> None:
        """Scheduled job: run the autonomous analysis pipeline.

        Guards against concurrent runs by checking for any AnalysisTask
        that is still in an active (non-terminal) status.  If one is
        found, the run is skipped with a log message.
        """
        from uuid import uuid4

        from analysis.autonomous_engine import get_autonomous_engine  # type: ignore[import-not-found]
        from analysis.autonomous_runner import run_autonomous_analysis_pipeline  # type: ignore[import-not-found]

        settings = get_settings()

        logger.info("Scheduled autonomous analysis triggered")

        # --- Concurrency guard ---
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

        async with async_session_factory() as session:
            result = await session.execute(
                select(AnalysisTask)
                .where(AnalysisTask.status.in_(active_statuses))
                .limit(1)
            )
            if result.scalar_one_or_none():
                logger.info(
                    "Scheduled autonomous analysis skipped — "
                    "another analysis is already running"
                )
                return

        # --- Create task record ---
        task_id = str(uuid4())
        async with async_session_factory() as session:
            task = AnalysisTask(
                id=task_id,
                status=AnalysisTaskStatus.PENDING.value,
                progress=0,
                current_phase="pending",
                phase_details="Scheduled autonomous analysis initializing...",
                max_insights=settings.SCHEDULED_ANALYSIS_MAX_INSIGHTS,
                deep_dive_count=settings.SCHEDULED_ANALYSIS_DEEP_DIVE_COUNT,
            )
            session.add(task)
            await session.commit()

        # Clear the activity log for this new run
        engine = get_autonomous_engine()
        engine.clear_activity_log(task_id=task_id)

        # --- Run the pipeline ---
        logger.info("Starting scheduled autonomous analysis (task_id=%s)", task_id)
        await run_autonomous_analysis_pipeline(
            task_id=task_id,
            max_insights=settings.SCHEDULED_ANALYSIS_MAX_INSIGHTS,
            deep_dive_count=settings.SCHEDULED_ANALYSIS_DEEP_DIVE_COUNT,
        )
        logger.info("Scheduled autonomous analysis finished (task_id=%s)", task_id)

    async def run_daily_alpha_engine(self) -> dict[str, Any]:
        """Scheduled job: persist the daily v2 alpha preflight snapshot.

        This is the Phase 1 wiring for the daily market-wide alpha engine.
        It creates an AnalysisRun, stores a MarketSnapshot, and captures the
        market universe plus regime label for downstream ranking phases.
        """
        logger.info("Starting daily alpha engine preflight")

        try:
            async with async_session_factory() as session:
                result = await create_daily_alpha_run(session)
                await session.commit()
        except Exception as exc:
            logger.exception("Daily alpha engine preflight failed: %s", exc)
            raise

        logger.info(
            "Daily alpha engine preflight complete: run_id=%s universe=%d regime=%s",
            result["analysis_run_id"],
            result["universe_size"],
            result["regime"]["name"],
        )
        return result

    def start(self) -> None:
        """Start the scheduler with configured jobs."""
        if self._is_running:
            logger.warning("Scheduler is already running")
            return

        settings = get_settings()

        # Daily price refresh at 6:30 PM ET (after market close).  Registered
        # with no arguments, so it refreshes every active stock in the DB.
        self.scheduler.add_job(
            self.fetch_and_store_prices,
            CronTrigger(hour=18, minute=30, timezone="America/New_York"),
            id="daily_price_refresh",
            replace_existing=True,
        )

        # Catch-up backfill shortly after startup.  Cron jobs do not run while
        # the process is down and APScheduler will not fire a missed one, so
        # without this a gap opened by any downtime stays open forever.  It is
        # delayed rather than awaited inline so it never slows app boot, and it
        # only touches symbols that are actually stale.
        if settings.PRICE_CATCHUP_ON_STARTUP:
            self.scheduler.add_job(
                self.catch_up_prices,
                DateTrigger(
                    run_date=datetime.now()
                    + timedelta(seconds=settings.PRICE_CATCHUP_DELAY_SECONDS)
                ),
                id="startup_price_catchup",
                name="Startup price catch-up backfill",
                replace_existing=True,
            )
            logger.info(
                "Startup price catch-up scheduled in %ds",
                settings.PRICE_CATCHUP_DELAY_SECONDS,
            )

        # Weekly economic data refresh (Saturdays at 10 AM)
        self.scheduler.add_job(
            self.fetch_economic_indicators,
            CronTrigger(day_of_week="sat", hour=10, timezone="America/New_York"),
            id="weekly_economic_refresh",
            replace_existing=True,
        )

        # Run analysis after each data refresh (7 PM ET)
        self.scheduler.add_job(
            self.run_analysis,
            CronTrigger(hour=19, minute=0, timezone="America/New_York"),
            id="daily_analysis",
            replace_existing=True,
        )

        # Daily v2 alpha preflight after market close + price refresh (6:45 PM ET)
        self.scheduler.add_job(
            self.run_daily_alpha_engine,
            CronTrigger(day_of_week="mon-fri", hour=18, minute=45, timezone="America/New_York"),
            id="daily_alpha_engine_preflight",
            name="Daily alpha engine preflight",
            replace_existing=True,
        )

        # Weekly stock info refresh (Sundays at 12 PM)
        self.scheduler.add_job(
            self.refresh_stock_info,
            CronTrigger(day_of_week="sun", hour=12, timezone="America/New_York"),
            id="weekly_stock_info_refresh",
            replace_existing=True,
        )

        # Insight outcome check every 4 hours during market hours (9:30 AM, 1:30 PM ET)
        # plus the definitive post-close check at 4:30 PM ET
        self.scheduler.add_job(
            self.check_insight_outcomes,
            CronTrigger(hour="9,13", minute=30, day_of_week="mon-fri",
                        timezone="America/New_York"),
            id="intraday_outcome_check",
            replace_existing=True,
        )

        # Daily definitive outcome check at 4:30 PM ET (after market close)
        self.scheduler.add_job(
            self.check_insight_outcomes,
            CronTrigger(hour=16, minute=30, day_of_week="mon-fri",
                        timezone="America/New_York"),
            id="daily_outcome_check",
            replace_existing=True,
        )

        # Daily theme relevance decay at midnight ET
        self.scheduler.add_job(
            self.decay_theme_relevance,
            CronTrigger(hour=0, minute=0, timezone="America/New_York"),
            id="daily_theme_decay",
            replace_existing=True,
        )

        # Daily statistical feature computation at 7:00 AM ET (before market open)
        self.scheduler.add_job(
            self.compute_daily_features,
            CronTrigger(hour=7, minute=0, timezone="America/New_York"),
            id="daily_feature_computation",
            replace_existing=True,
        )

        # Daily earnings calendar refresh at 7:00 AM ET (before market open)
        self.scheduler.add_job(
            self.refresh_earnings_calendar,
            CronTrigger(
                day_of_week="mon-fri",
                hour=7,
                minute=0,
                timezone="America/New_York",
            ),
            id="daily_earnings_refresh",
            name="Daily earnings calendar refresh",
            replace_existing=True,
        )

        # Daily investor feeds refresh at 7:15 AM ET Mon-Fri
        self.scheduler.add_job(
            self.refresh_investor_feeds,
            CronTrigger(
                hour=7,
                minute=15,
                day_of_week="mon-fri",
                timezone="US/Eastern",
            ),
            id="refresh_investor_feeds",
            name="Refresh investor feeds",
            replace_existing=True,
        )

        # === Insight Lifecycle Jobs ===
        self.scheduler.add_job(
            self.check_insight_lifecycles,
            CronTrigger(day_of_week="mon-fri", hour=8, minute=0,
                        timezone="America/New_York"),
            id="daily_lifecycle_check",
            name="Daily insight lifecycle check",
            replace_existing=True,
        )

        # === Thematic Insight Jobs ===
        # Thematic outcome check at 4:45 PM ET Mon-Fri (after insight outcomes)
        self.scheduler.add_job(
            self.check_thematic_outcomes,
            CronTrigger(day_of_week="mon-fri", hour=16, minute=45,
                        timezone="America/New_York"),
            id="daily_thematic_outcome_check",
            name="Daily thematic outcome check",
            replace_existing=True,
        )

        # Thematic lifecycle check at 8:15 AM ET Mon-Fri
        self.scheduler.add_job(
            self.check_thematic_lifecycles,
            CronTrigger(day_of_week="mon-fri", hour=8, minute=15,
                        timezone="America/New_York"),
            id="daily_thematic_lifecycle_check",
            name="Daily thematic lifecycle check",
            replace_existing=True,
        )

        # Neon PostgreSQL keepalive ping every 4 minutes (prevents free-tier
        # compute suspension after 5 min idle, which causes 3-5s cold starts).
        # Only enabled when using a PostgreSQL backend.
        if settings.DATABASE_URL.startswith("postgresql"):
            self.scheduler.add_job(
                self.keepalive_ping,
                IntervalTrigger(minutes=4),
                id="neon_keepalive_ping",
                name="Neon PostgreSQL keepalive ping",
                replace_existing=True,
            )
            logger.info("Neon keepalive ping enabled (every 4 minutes)")

        # Scheduled autonomous analysis (opt-in, Mon-Fri after market close)
        if settings.SCHEDULED_ANALYSIS_ENABLED:
            self.scheduler.add_job(
                self.run_scheduled_autonomous_analysis,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour=settings.SCHEDULED_ANALYSIS_HOUR,
                    minute=settings.SCHEDULED_ANALYSIS_MINUTE,
                    timezone="America/New_York",
                ),
                id="scheduled_autonomous_analysis",
                name="Scheduled Autonomous Deep Analysis",
                replace_existing=True,
            )
            logger.info(
                "Scheduled autonomous analysis ENABLED "
                "(Mon-Fri %02d:%02d ET, max_insights=%d, deep_dive_count=%d)",
                settings.SCHEDULED_ANALYSIS_HOUR,
                settings.SCHEDULED_ANALYSIS_MINUTE,
                settings.SCHEDULED_ANALYSIS_MAX_INSIGHTS,
                settings.SCHEDULED_ANALYSIS_DEEP_DIVE_COUNT,
            )

        self.scheduler.start()
        self._is_running = True

        job_names = [
            "daily_price_refresh",
            "startup_price_catchup",
            "weekly_economic_refresh",
            "daily_analysis",
            "daily_alpha_engine_preflight",
            "weekly_stock_info_refresh",
            "intraday_outcome_check",
            "daily_outcome_check",
            "daily_theme_decay",
            "daily_feature_computation",
            "daily_earnings_refresh",
            "refresh_investor_feeds",
            "daily_lifecycle_check",
        ]
        if settings.SCHEDULED_ANALYSIS_ENABLED:
            job_names.append("scheduled_autonomous_analysis")
        logger.info("ETL scheduler started with jobs: %s", ", ".join(job_names))

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._is_running:
            self.scheduler.shutdown(wait=False)
            self._is_running = False
            logger.info("ETL scheduler stopped")

    @property
    def is_running(self) -> bool:
        """Check if the scheduler is running."""
        return self._is_running

    def get_job_status(self) -> list[dict[str, Any]]:
        """Get status of all scheduled jobs.

        Returns:
            List of dicts with job information
        """
        if not self._is_running:
            return []

        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
            })

        return jobs


# Singleton instance for application use
etl_orchestrator = ETLOrchestrator()
