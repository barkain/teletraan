"""ETL orchestrator for market data pipelines using APScheduler.

This module provides scheduled data fetching and storage for stock prices,
economic indicators, and analysis pipelines.
"""

import logging
from datetime import date, timedelta
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session_factory
from data.adapters.yahoo import yahoo_adapter
from data.adapters.fred import fred_adapter
from models.stock import Stock
from models.price import PriceHistory
from models.economic import EconomicIndicator
from analysis.engine import AnalysisEngine
from analysis.outcome_tracker import InsightOutcomeTracker
from analysis.memory_service import InstitutionalMemoryService
from analysis.statistical_calculator import StatisticalFeatureCalculator

logger = logging.getLogger(__name__)


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

        stmt = sqlite_insert(PriceHistory).values(
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

    async def fetch_and_store_prices(
        self,
        symbols: list[str] | None = None,
    ) -> dict[str, int]:
        """Fetch latest prices and store in database.

        Args:
            symbols: List of symbols to fetch. Uses DEFAULT_SYMBOLS if not provided.

        Returns:
            Dict mapping symbols to number of prices stored
        """
        symbols = symbols or self.DEFAULT_SYMBOLS
        logger.info(f"Fetching prices for {len(symbols)} symbols")

        results: dict[str, int] = {}

        async with async_session_factory() as session:
            for symbol in symbols:
                try:
                    # Get or create stock record
                    stock = await self._get_or_create_stock(session, symbol)

                    # Fetch price history (last 5 days to ensure we get latest)
                    prices = await yahoo_adapter.get_price_history(
                        symbol, period="5d"
                    )

                    # Store prices
                    for price in prices:
                        await self._upsert_price(session, stock.id, price)

                    await session.commit()
                    results[symbol] = len(prices)
                    logger.info(f"Updated {symbol}: {len(prices)} prices")

                except Exception as e:
                    logger.error(f"Error fetching {symbol}: {e}")
                    await session.rollback()
                    results[symbol] = 0

        return results

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
                        stmt = sqlite_insert(EconomicIndicator).values(
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
        and cross-sectional features for all watchlist symbols.

        Args:
            symbols: List of symbols to compute. Uses DEFAULT_SYMBOLS if not provided.

        Returns:
            Dict containing features_computed and symbols counts.
        """
        symbols = symbols or self.DEFAULT_SYMBOLS
        logger.info(f"Computing daily statistical features for {len(symbols)} symbols")

        async with async_session_factory() as session:
            calculator = StatisticalFeatureCalculator(session)

            # Compute all features
            features = await calculator.compute_all_features(symbols)

            await session.commit()

            logger.info(
                f"Feature computation complete: {len(features)} features computed "
                f"for {len(symbols)} symbols"
            )

            return {
                "features_computed": len(features),
                "symbols": len(symbols),
            }

    def start(self) -> None:
        """Start the scheduler with configured jobs."""
        if self._is_running:
            logger.warning("Scheduler is already running")
            return

        # Daily price refresh at 6:30 PM ET (after market close)
        self.scheduler.add_job(
            self.fetch_and_store_prices,
            CronTrigger(hour=18, minute=30, timezone="America/New_York"),
            id="daily_price_refresh",
            replace_existing=True,
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

        # Weekly stock info refresh (Sundays at 12 PM)
        self.scheduler.add_job(
            self.refresh_stock_info,
            CronTrigger(day_of_week="sun", hour=12, timezone="America/New_York"),
            id="weekly_stock_info_refresh",
            replace_existing=True,
        )

        # Daily insight outcome check at 4:30 PM ET (after market close)
        self.scheduler.add_job(
            self.check_insight_outcomes,
            CronTrigger(hour=16, minute=30, timezone="America/New_York"),
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

        self.scheduler.start()
        self._is_running = True
        logger.info(
            "ETL scheduler started with jobs: daily_price_refresh, "
            "weekly_economic_refresh, daily_analysis, weekly_stock_info_refresh, "
            "daily_outcome_check, daily_theme_decay, daily_feature_computation"
        )

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
