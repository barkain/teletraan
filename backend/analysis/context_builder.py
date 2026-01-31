"""Market Data Context Builder - Prepares data for analyst agents.

This module builds the comprehensive market data context that gets passed to
analyst agents for multi-agent market analysis. It aggregates stock data,
price history, technical indicators, economic indicators, and sector
performance into a structured format suitable for LLM consumption.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import async_session_factory
from models import Stock, PriceHistory, TechnicalIndicator, EconomicIndicator

from .sectors import SECTOR_ETFS

logger = logging.getLogger(__name__)


class MarketContextBuilder:
    """Builds comprehensive market context for analyst agents.

    This class aggregates data from multiple sources (stocks, prices,
    indicators) and formats it into a structured dictionary that can
    be consumed by analyst agents for generating market insights.

    The context includes:
    - Current stock metadata and status
    - Historical price data (OHLCV)
    - Technical indicators (RSI, MACD, moving averages, etc.)
    - Economic indicators (GDP, CPI, unemployment, etc.)
    - Sector performance metrics
    - Overall market summary
    """

    def __init__(self) -> None:
        """Initialize the context builder."""
        self._cache_ttl = timedelta(minutes=5)
        self._last_context: dict[str, Any] | None = None
        self._last_build_time: datetime | None = None

    async def build_context(
        self,
        symbols: list[str] | None = None,
        include_price_history: bool = True,
        include_technical: bool = True,
        include_economic: bool = True,
        include_sectors: bool = True,
        price_history_days: int = 60,
    ) -> dict[str, Any]:
        """Build full market context for analysis.

        Args:
            symbols: Optional list of symbols to focus on. If None, uses all
                active stocks.
            include_price_history: Whether to include historical price data.
            include_technical: Whether to include technical indicators.
            include_economic: Whether to include economic indicators.
            include_sectors: Whether to include sector performance analysis.
            price_history_days: Number of days of price history to include.

        Returns:
            Dict with structured market data for all analysts, containing:
            - timestamp: ISO format timestamp of when context was built
            - stocks: List of stock metadata dicts
            - price_history: Dict mapping symbols to OHLCV data
            - technical_indicators: Dict mapping symbols to indicator values
            - economic_indicators: List of economic indicator readings
            - sector_performance: Dict of sector ETF performance metrics
            - market_summary: Overall market status summary
        """
        async with async_session_factory() as db:
            context: dict[str, Any] = {
                "timestamp": datetime.utcnow().isoformat(),
                "stocks": await self._get_stocks_data(db, symbols),
            }

            # Get stock IDs for filtered queries
            stock_ids = await self._get_stock_ids(db, symbols)

            if include_price_history:
                context["price_history"] = await self._get_price_history(
                    db, symbols, stock_ids, days=price_history_days
                )

            if include_technical:
                context["technical_indicators"] = await self._get_technical_indicators(
                    db, symbols, stock_ids
                )

            if include_economic:
                context["economic_indicators"] = await self._get_economic_indicators(db)

            if include_sectors:
                context["sector_performance"] = await self._calculate_sector_performance(db)

            context["market_summary"] = await self._get_market_summary(db)

        self._last_context = context
        self._last_build_time = datetime.utcnow()

        return context

    async def _get_stock_ids(
        self,
        db: AsyncSession,
        symbols: list[str] | None,
    ) -> dict[str, int]:
        """Get mapping of symbols to stock IDs.

        Args:
            db: Database session.
            symbols: Optional list of symbols to filter by.

        Returns:
            Dict mapping symbol strings to stock ID integers.
        """
        query = select(Stock.id, Stock.symbol).where(Stock.is_active == True)  # noqa: E712
        if symbols:
            query = query.where(Stock.symbol.in_([s.upper() for s in symbols]))

        result = await db.execute(query)
        return {row.symbol: row.id for row in result.fetchall()}

    async def _get_stocks_data(
        self,
        db: AsyncSession,
        symbols: list[str] | None,
    ) -> list[dict[str, Any]]:
        """Get current stock data.

        Args:
            db: Database session.
            symbols: Optional list of symbols to filter by.

        Returns:
            List of stock metadata dictionaries.
        """
        query = select(Stock).where(Stock.is_active == True)  # noqa: E712
        if symbols:
            query = query.where(Stock.symbol.in_([s.upper() for s in symbols]))

        result = await db.execute(query)
        stocks = result.scalars().all()

        return [
            {
                "symbol": s.symbol,
                "name": s.name,
                "sector": s.sector,
                "industry": s.industry,
                "market_cap": s.market_cap,
                "is_active": s.is_active,
            }
            for s in stocks
        ]

    async def _get_price_history(
        self,
        db: AsyncSession,
        symbols: list[str] | None,
        stock_ids: dict[str, int],
        days: int = 60,
    ) -> dict[str, list[dict[str, Any]]]:
        """Get price history for analysis.

        Args:
            db: Database session.
            symbols: Optional list of symbols to filter by.
            stock_ids: Mapping of symbols to stock IDs.
            days: Number of days of history to retrieve.

        Returns:
            Dict mapping symbols to lists of OHLCV data dictionaries.
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        cutoff_date = cutoff.date()

        query = (
            select(PriceHistory)
            .options(selectinload(PriceHistory.stock))
            .where(PriceHistory.date >= cutoff_date)
        )

        if symbols and stock_ids:
            query = query.where(PriceHistory.stock_id.in_(stock_ids.values()))

        query = query.order_by(PriceHistory.stock_id, PriceHistory.date.desc())
        result = await db.execute(query)
        history = result.scalars().all()

        # Group by symbol
        by_symbol: dict[str, list[dict[str, Any]]] = {}
        for h in history:
            symbol = h.stock.symbol if h.stock else "UNKNOWN"
            if symbol not in by_symbol:
                by_symbol[symbol] = []
            by_symbol[symbol].append({
                "date": h.date.isoformat(),
                "open": h.open,
                "high": h.high,
                "low": h.low,
                "close": h.close,
                "volume": h.volume,
                "adjusted_close": h.adjusted_close,
            })

        return by_symbol

    async def _get_technical_indicators(
        self,
        db: AsyncSession,
        symbols: list[str] | None,
        stock_ids: dict[str, int],
    ) -> dict[str, dict[str, Any]]:
        """Get latest technical indicators.

        Args:
            db: Database session.
            symbols: Optional list of symbols to filter by.
            stock_ids: Mapping of symbols to stock IDs.

        Returns:
            Dict mapping symbols to dicts of indicator name -> value/date.
        """
        query = (
            select(TechnicalIndicator)
            .options(selectinload(TechnicalIndicator.stock))
        )

        if symbols and stock_ids:
            query = query.where(TechnicalIndicator.stock_id.in_(stock_ids.values()))

        # Order by date desc to get most recent indicators first
        query = query.order_by(TechnicalIndicator.date.desc())

        result = await db.execute(query)
        indicators = result.scalars().all()

        by_symbol: dict[str, dict[str, Any]] = {}
        seen: set[tuple[str, str]] = set()  # Track (symbol, indicator_type) pairs

        for ind in indicators:
            symbol = ind.stock.symbol if ind.stock else "UNKNOWN"
            indicator_key = (symbol, ind.indicator_type)

            # Only keep the most recent value for each indicator type
            if indicator_key in seen:
                continue
            seen.add(indicator_key)

            if symbol not in by_symbol:
                by_symbol[symbol] = {}

            by_symbol[symbol][ind.indicator_type] = {
                "value": ind.value,
                "date": ind.date.isoformat() if ind.date else None,
                "metadata": ind.metadata_json,
            }

        return by_symbol

    async def _get_economic_indicators(
        self,
        db: AsyncSession,
        days: int = 90,
    ) -> list[dict[str, Any]]:
        """Get recent economic indicators.

        Args:
            db: Database session.
            days: Number of days of history to include.

        Returns:
            List of economic indicator dictionaries with latest values
            for each series.
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        cutoff_date = cutoff.date()

        query = (
            select(EconomicIndicator)
            .where(EconomicIndicator.date >= cutoff_date)
            .order_by(EconomicIndicator.series_id, EconomicIndicator.date.desc())
        )

        result = await db.execute(query)
        indicators = result.scalars().all()

        # Group by series and get the most recent value for each
        latest_by_series: dict[str, EconomicIndicator] = {}
        for ind in indicators:
            if ind.series_id not in latest_by_series:
                latest_by_series[ind.series_id] = ind

        return [
            {
                "series_id": i.series_id,
                "name": i.name,
                "value": i.value,
                "unit": i.unit,
                "date": i.date.isoformat(),
                "description": i.description,
            }
            for i in latest_by_series.values()
        ]

    async def _calculate_sector_performance(
        self,
        db: AsyncSession,
    ) -> dict[str, dict[str, Any]]:
        """Calculate sector performance metrics.

        Uses sector ETFs (XLK, XLF, XLE, etc.) to calculate performance
        metrics including daily, weekly, and monthly changes.

        Args:
            db: Database session.

        Returns:
            Dict mapping sector ETF symbols to performance metrics.
        """
        sector_etf_symbols = list(SECTOR_ETFS.keys())

        query = select(Stock).where(Stock.symbol.in_(sector_etf_symbols))
        result = await db.execute(query)
        stocks = result.scalars().all()

        performance: dict[str, dict[str, Any]] = {}

        for stock in stocks:
            # Get recent prices for this sector ETF
            price_query = (
                select(PriceHistory)
                .where(PriceHistory.stock_id == stock.id)
                .order_by(PriceHistory.date.desc())
                .limit(30)
            )

            price_result = await db.execute(price_query)
            prices = price_result.scalars().all()

            if len(prices) >= 2:
                current = prices[0].close
                prev_day = prices[1].close if len(prices) > 1 else current
                prev_week = prices[5].close if len(prices) > 5 else current
                prev_month = prices[-1].close if len(prices) >= 20 else (
                    prices[min(20, len(prices) - 1)].close
                )

                performance[stock.symbol] = {
                    "name": stock.name,
                    "sector": SECTOR_ETFS.get(stock.symbol, stock.sector),
                    "current_price": current,
                    "previous_close": prev_day,
                    "daily_change": current - prev_day,
                    "daily_change_pct": (
                        ((current - prev_day) / prev_day) * 100 if prev_day else 0
                    ),
                    "weekly_change_pct": (
                        ((current - prev_week) / prev_week) * 100 if prev_week else 0
                    ),
                    "monthly_change_pct": (
                        ((current - prev_month) / prev_month) * 100 if prev_month else 0
                    ),
                    "volume": prices[0].volume if prices else 0,
                }

        return performance

    async def _get_market_summary(
        self,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Get overall market summary.

        Uses SPY as a market proxy to provide overall market status.

        Args:
            db: Database session.

        Returns:
            Dict containing market summary data including SPY status.
        """
        # Get SPY as market proxy
        spy_query = select(Stock).where(Stock.symbol == "SPY")
        spy_result = await db.execute(spy_query)
        spy = spy_result.scalar_one_or_none()

        summary: dict[str, Any] = {
            "date": datetime.utcnow().isoformat(),
            "market_index": {},
            "trading_session": self._get_trading_session(),
        }

        if spy:
            price_query = (
                select(PriceHistory)
                .where(PriceHistory.stock_id == spy.id)
                .order_by(PriceHistory.date.desc())
                .limit(5)
            )

            price_result = await db.execute(price_query)
            prices = price_result.scalars().all()

            if prices:
                current = prices[0]
                prev = prices[1] if len(prices) > 1 else current

                summary["market_index"] = {
                    "symbol": "SPY",
                    "name": spy.name,
                    "current": current.close,
                    "previous_close": prev.close,
                    "change": current.close - prev.close,
                    "change_pct": (
                        ((current.close - prev.close) / prev.close) * 100
                        if prev.close else 0
                    ),
                    "volume": current.volume,
                    "high": current.high,
                    "low": current.low,
                    "date": current.date.isoformat(),
                }

        return summary

    def _get_trading_session(self) -> str:
        """Determine current trading session status.

        Returns:
            String indicating trading session: 'pre_market', 'regular',
            'after_hours', or 'closed'.
        """
        now = datetime.utcnow()
        # Convert to ET (UTC-5 or UTC-4 depending on DST)
        # Simplified: assume EST (UTC-5)
        et_hour = (now.hour - 5) % 24

        # Market hours in ET
        if now.weekday() >= 5:  # Saturday or Sunday
            return "closed"
        elif 4 <= et_hour < 9.5:
            return "pre_market"
        elif 9.5 <= et_hour < 16:
            return "regular"
        elif 16 <= et_hour < 20:
            return "after_hours"
        else:
            return "closed"

    async def build_agent_context(
        self,
        agent_type: str,
        symbols: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build context tailored for a specific agent type.

        This method builds a focused context based on the agent's specialty,
        including only the data most relevant to that agent.

        Args:
            agent_type: Type of agent ('technical', 'macro', 'sector',
                'risk', 'correlation').
            symbols: Optional list of symbols to focus on.

        Returns:
            Agent-specific context dictionary.
        """
        if agent_type == "technical":
            return await self.build_context(
                symbols=symbols,
                include_price_history=True,
                include_technical=True,
                include_economic=False,
                include_sectors=False,
                price_history_days=60,
            )
        elif agent_type == "macro":
            return await self.build_context(
                symbols=None,  # Macro doesn't focus on specific stocks
                include_price_history=False,
                include_technical=False,
                include_economic=True,
                include_sectors=True,
                price_history_days=30,
            )
        elif agent_type == "sector":
            # Include sector ETFs in symbols
            sector_symbols = list(SECTOR_ETFS.keys())
            if symbols:
                sector_symbols = list(set(sector_symbols + symbols))
            return await self.build_context(
                symbols=sector_symbols,
                include_price_history=True,
                include_technical=True,
                include_economic=True,
                include_sectors=True,
                price_history_days=90,
            )
        elif agent_type == "risk":
            return await self.build_context(
                symbols=symbols,
                include_price_history=True,
                include_technical=True,
                include_economic=True,
                include_sectors=True,
                price_history_days=90,
            )
        elif agent_type == "correlation":
            return await self.build_context(
                symbols=symbols,
                include_price_history=True,
                include_technical=False,
                include_economic=False,
                include_sectors=True,
                price_history_days=120,
            )
        else:
            # Default: full context
            return await self.build_context(symbols=symbols)

    @property
    def last_build_time(self) -> datetime | None:
        """Get the timestamp of the last context build."""
        return self._last_build_time

    def get_cached_context(self) -> dict[str, Any] | None:
        """Get the last built context if still valid.

        Returns:
            Cached context dict if within TTL, None otherwise.
        """
        if self._last_context and self._last_build_time:
            if datetime.utcnow() - self._last_build_time < self._cache_ttl:
                return self._last_context
        return None


# Singleton instance for easy import
market_context_builder = MarketContextBuilder()
