"""ETL orchestrator for market data pipelines using APScheduler.

This module provides scheduled data fetching and storage for stock prices,
economic indicators, and analysis pipelines.
"""

import logging
from datetime import date, timedelta
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-not-found]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-not-found]
from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-not-found]
from sqlalchemy import select  # type: ignore[import-not-found]
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
from analysis.alpha_engine import create_daily_alpha_run  # type: ignore[import-not-found]
from analysis.outcome_tracker import InsightOutcomeTracker  # type: ignore[import-not-found]
from analysis.thematic_outcome_tracker import ThematicOutcomeTracker  # type: ignore[import-not-found]
from analysis.memory_service import InstitutionalMemoryService  # type: ignore[import-not-found]
from analysis.statistical_calculator import StatisticalFeatureCalculator  # type: ignore[import-not-found]
from config import get_settings  # type: ignore[import-not-found]

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
        settings = get_settings()
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
