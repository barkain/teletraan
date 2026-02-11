"""Market Data Context Builder - Prepares data for analyst agents.

This module builds the comprehensive market data context that gets passed to
analyst agents for multi-agent market analysis. It aggregates stock data,
price history, technical indicators, economic indicators, and sector
performance into a structured format suitable for LLM consumption.

Enhanced with statistical signals and institutional memory integration for
richer analyst context including pre-computed features, validated patterns,
and historical track record.

Supports autonomous analysis flow with:
- build_macro_scan_context(): Fetches raw macro indicators for LLM analysis
- build_sector_rotation_context(): Fetches sector ETF performance data
- build_discovery_context(): Combines macro/sector results for symbol analysis
"""

import logging
from datetime import datetime, timedelta, date as date_type
from typing import Any

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import async_session_factory
from models import Stock, PriceHistory, TechnicalIndicator, EconomicIndicator
from models.statistical_feature import StatisticalFeature

from .sectors import SECTOR_ETFS
from .memory_service import InstitutionalMemoryService

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
        self._last_cache_key: tuple | None = None

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
        # Build a cache key from the call parameters so cache hits only occur
        # when the exact same query is repeated within the TTL window.
        normalized_symbols = tuple(sorted(s.upper() for s in symbols)) if symbols else None
        cache_key = (
            normalized_symbols,
            include_price_history,
            include_technical,
            include_economic,
            include_sectors,
            price_history_days,
        )

        # Return cached context if it matches and is still within TTL
        if (
            self._last_context is not None
            and self._last_build_time is not None
            and self._last_cache_key == cache_key
            and datetime.utcnow() - self._last_build_time < self._cache_ttl
        ):
            logger.info("Returning cached context (TTL still valid)")
            return self._last_context

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

        # Debug logging to trace data pipeline
        logger.info(f"Context built: {len(context.get('stocks', []))} stocks")
        logger.info(f"Context built: {len(context.get('price_history', {}))} symbols with price history")
        if context.get('price_history'):
            for sym, prices in list(context.get('price_history', {}).items())[:3]:
                logger.info(f"  {sym}: {len(prices)} price records")
        logger.info(f"Context built: {len(context.get('technical_indicators', {}))} symbols with technical indicators")
        logger.info(f"Context built: {len(context.get('economic_indicators', []))} economic indicators")
        logger.info(f"Context built: {len(context.get('sector_performance', {}))} sectors with performance data")

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

    async def build_statistical_context(
        self,
        symbols: list[str],
    ) -> str:
        """Build markdown context with pre-computed statistical signals.

        Fetches pre-computed statistical features for the given symbols and
        formats them as a markdown table highlighting key quantitative signals.
        Extreme signals (Z-score > 2 or < -2, volatility regime "crisis") are
        highlighted.

        Args:
            symbols: List of stock symbols to include.

        Returns:
            Markdown-formatted string with statistical signals table.
        """
        if not symbols:
            return ""

        async with async_session_factory() as db:
            # Get latest calculation date
            today = date_type.today()

            # Query recent statistical features for the symbols
            query = (
                select(StatisticalFeature)
                .where(
                    and_(
                        StatisticalFeature.symbol.in_([s.upper() for s in symbols]),
                        StatisticalFeature.calculation_date >= today - timedelta(days=7),
                    )
                )
                .order_by(
                    StatisticalFeature.symbol,
                    StatisticalFeature.calculation_date.desc(),
                )
            )

            result = await db.execute(query)
            features = result.scalars().all()

        if not features:
            return "## Pre-Computed Statistical Signals\n\n*No recent statistical features available.*\n"

        # Group by symbol and get latest per feature type
        latest_by_symbol: dict[str, dict[str, StatisticalFeature]] = {}
        for feature in features:
            if feature.symbol not in latest_by_symbol:
                latest_by_symbol[feature.symbol] = {}
            # Only keep the most recent per feature type
            if feature.feature_type not in latest_by_symbol[feature.symbol]:
                latest_by_symbol[feature.symbol][feature.feature_type] = feature

        # Build markdown table
        lines: list[str] = [
            "## Pre-Computed Statistical Signals",
            "",
            "| Symbol | Feature | Value | Signal | Percentile |",
            "|--------|---------|-------|--------|------------|",
        ]

        extreme_signals: list[str] = []

        for symbol in sorted(latest_by_symbol.keys()):
            symbol_features = latest_by_symbol[symbol]
            for feature_type in sorted(symbol_features.keys()):
                feature = symbol_features[feature_type]

                # Format value based on feature type
                if "zscore" in feature_type.lower():
                    value_str = f"{feature.value:+.2f}"
                elif "roc" in feature_type.lower() or "deviation" in feature_type.lower():
                    value_str = f"{feature.value:+.1f}%"
                elif "percentile" in feature_type.lower():
                    value_str = f"{feature.value:.0f}%"
                else:
                    value_str = f"{feature.value:.2f}"

                percentile_str = f"{feature.percentile:.0f}" if feature.percentile else "-"

                lines.append(
                    f"| {symbol} | {feature_type.upper()} | {value_str} | {feature.signal} | {percentile_str} |"
                )

                # Track extreme signals
                if "zscore" in feature_type.lower() and abs(feature.value) > 2:
                    extreme_signals.append(
                        f"- **{symbol}**: Z-score {feature.value:+.2f} ({feature.signal})"
                    )
                elif feature.signal == "crisis":
                    extreme_signals.append(
                        f"- **{symbol}**: Volatility regime is CRISIS (ATR percentile {feature.percentile:.0f}%)"
                    )

        # Add extreme signals section if any
        if extreme_signals:
            lines.append("")
            lines.append("### Extreme Signals Requiring Attention")
            lines.append("")
            lines.extend(extreme_signals)

        lines.append("")
        return "\n".join(lines)

    async def build_pattern_context(
        self,
        symbols: list[str],
        current_conditions: dict[str, Any],
    ) -> str:
        """Build markdown context with validated patterns from institutional memory.

        Queries the InstitutionalMemoryService for patterns matching current
        market conditions and formats them as a markdown section showing
        trigger conditions, success rates, and expected outcomes.

        Args:
            symbols: List of stock symbols to focus on.
            current_conditions: Current market state dict with metrics like:
                - rsi: Current RSI value
                - vix: Current VIX level
                - volume_surge_pct: Volume surge percentage
                etc.

        Returns:
            Markdown-formatted string with validated patterns.
        """
        if not symbols:
            return ""

        async with async_session_factory() as db:
            memory_service = InstitutionalMemoryService(db)
            patterns = await memory_service.get_relevant_patterns(
                symbols=symbols,
                current_conditions=current_conditions,
            )

        if not patterns:
            return "## Validated Patterns (65%+ success rate)\n\n*No patterns match current conditions.*\n"

        # Filter to patterns with 65%+ success rate
        high_success_patterns = [p for p in patterns if p.success_rate >= 0.65]

        if not high_success_patterns:
            return "## Validated Patterns (65%+ success rate)\n\n*No high-confidence patterns match current conditions.*\n"

        lines: list[str] = [
            "## Validated Patterns (65%+ success rate)",
            "",
        ]

        for pattern in high_success_patterns:
            lines.append(f"**{pattern.pattern_name}**")

            # Format trigger conditions
            trigger_parts: list[str] = []
            if pattern.trigger_conditions:
                for key, value in pattern.trigger_conditions.items():
                    if key.endswith("_below"):
                        metric = key.replace("_below", "").upper()
                        trigger_parts.append(f"{metric} < {value}")
                    elif key.endswith("_above"):
                        metric = key.replace("_above", "").upper()
                        trigger_parts.append(f"{metric} > {value}")
                    else:
                        trigger_parts.append(f"{key.upper()} >= {value}")

            if trigger_parts:
                lines.append(f"- Trigger: {' AND '.join(trigger_parts)}")

            # Success rate with occurrences
            success_count = pattern.successful_outcomes
            total_count = pattern.occurrences
            success_pct = pattern.success_rate * 100
            lines.append(f"- Success Rate: {success_pct:.0f}% ({success_count}/{total_count} occurrences)")

            # Expected outcome
            if pattern.expected_outcome:
                lines.append(f"- Expected: {pattern.expected_outcome}")

            # Average return if available
            if pattern.avg_return_when_triggered is not None:
                lines.append(f"- Historical Avg Return: {pattern.avg_return_when_triggered:+.1f}%")

            lines.append("")

        return "\n".join(lines)

    async def build_track_record_context(
        self,
        insight_type: str | None = None,
    ) -> str:
        """Build markdown context with historical insight track record.

        Queries the InstitutionalMemoryService for insight outcome statistics
        and formats them as markdown tables showing success rates by insight
        type and action type.

        Args:
            insight_type: Optional insight type to filter by (e.g., "opportunity").

        Returns:
            Markdown-formatted string with track record tables.
        """
        async with async_session_factory() as db:
            memory_service = InstitutionalMemoryService(db)
            track_record = await memory_service.get_insight_track_record(
                insight_type=insight_type,
            )

        if track_record.get("total_insights", 0) == 0:
            return "## Historical Track Record\n\n*No validated insights available yet.*\n"

        lines: list[str] = [
            "## Historical Track Record",
            "",
        ]

        # Overall stats
        total = track_record["total_insights"]
        successful = track_record["successful"]
        success_rate = track_record["success_rate"] * 100
        lines.append(f"**Overall**: {successful}/{total} validated insights ({success_rate:.0f}% success rate)")
        lines.append("")

        # By insight type breakdown
        by_type = track_record.get("by_insight_type", {})
        if by_type:
            lines.append("### By Insight Type")
            lines.append("| Type | Success Rate | Sample Size |")
            lines.append("|------|--------------|-------------|")

            for itype, stats in sorted(by_type.items()):
                rate = stats["success_rate"] * 100
                lines.append(f"| {itype} | {rate:.0f}% | {stats['total']} |")
            lines.append("")

        # By action type breakdown
        by_action = track_record.get("by_action_type", {})
        if by_action:
            lines.append("### By Action Type")
            lines.append("| Action | Success Rate | Sample Size |")
            lines.append("|--------|--------------|-------------|")

            for action, stats in sorted(by_action.items()):
                rate = stats["success_rate"] * 100
                lines.append(f"| {action} | {rate:.0f}% | {stats['total']} |")
            lines.append("")

        return "\n".join(lines)

    async def build_enriched_analyst_context(
        self,
        agent_type: str,
        symbols: list[str] | None = None,
        current_conditions: dict[str, Any] | None = None,
        include_statistical: bool = True,
        include_patterns: bool = True,
        include_track_record: bool = True,
    ) -> dict[str, Any]:
        """Build enriched context for analyst agents with statistical signals and memory.

        This method extends build_agent_context by prepending statistical signals,
        validated patterns, and historical track record to the context. The
        additional context is provided as a markdown string that should be
        included BEFORE the analyst's data context.

        Args:
            agent_type: Type of agent ('technical', 'macro', 'sector', 'risk', 'correlation').
            symbols: Optional list of symbols to focus on.
            current_conditions: Current market conditions for pattern matching.
            include_statistical: Whether to include statistical signals context.
            include_patterns: Whether to include pattern context.
            include_track_record: Whether to include track record context.

        Returns:
            Agent-specific context dictionary with additional 'enriched_context' key
            containing the markdown-formatted statistical, pattern, and track record data.
        """
        # Get base agent context
        context = await self.build_agent_context(agent_type, symbols)

        enriched_parts: list[str] = []

        # Build enriched context sections
        if include_statistical and symbols:
            statistical_context = await self.build_statistical_context(symbols)
            if statistical_context:
                enriched_parts.append(statistical_context)

        if include_patterns and symbols:
            conditions = current_conditions or {}
            # Extract conditions from technical indicators if available
            if not conditions and context.get("technical_indicators"):
                for symbol in symbols:
                    if symbol in context["technical_indicators"]:
                        indicators = context["technical_indicators"][symbol]
                        if "RSI" in indicators:
                            conditions["rsi"] = indicators["RSI"].get("value")
                        if "VIX" in indicators:
                            conditions["vix"] = indicators["VIX"].get("value")
                        break  # Use first available symbol's indicators

            pattern_context = await self.build_pattern_context(symbols, conditions)
            if pattern_context:
                enriched_parts.append(pattern_context)

        if include_track_record:
            track_record_context = await self.build_track_record_context()
            if track_record_context:
                enriched_parts.append(track_record_context)

        # Combine enriched context
        if enriched_parts:
            context["enriched_context"] = "\n".join(enriched_parts)
        else:
            context["enriched_context"] = ""

        logger.info(
            f"Built enriched context for {agent_type}: "
            f"{len(context.get('enriched_context', ''))} chars of enriched data"
        )

        return context

    # =========================================================================
    # Autonomous Analysis Flow Methods
    # =========================================================================

    async def build_macro_scan_context(self) -> str:
        """Build context for Phase 1: Macro Scanner.

        Fetches raw macro data via yfinance for LLM analysis including:
        - US Treasury yields (2Y, 5Y, 10Y, 30Y)
        - Volatility (VIX)
        - Currency (Dollar Index)
        - Commodities (Gold, Crude Oil)
        - US Indices (S&P 500, Nasdaq, Russell 2000)
        - Global Indices (DAX, Nikkei, FTSE 100)

        Returns:
            Markdown-formatted string with macro indicator data.
        """
        macro_data = await self._fetch_macro_indicators()
        return self._format_macro_context(macro_data)

    async def _fetch_macro_indicators(self) -> dict[str, dict[str, Any]]:
        """Fetch key macro indicators via yfinance.

        Returns:
            Dict mapping ticker symbols to indicator data including
            current price, 1D/5D/20D changes, and 20D high/low.
        """
        import yfinance as yf

        tickers = {
            # US Rates
            "^TNX": "10Y Treasury Yield",
            "^TYX": "30Y Treasury Yield",
            "^FVX": "5Y Treasury Yield",
            # Volatility
            "^VIX": "VIX",
            # Currency
            "DX-Y.NYB": "Dollar Index",
            # Commodities
            "GC=F": "Gold",
            "CL=F": "Crude Oil",
            # US Indices
            "^GSPC": "S&P 500",
            "^IXIC": "Nasdaq",
            "^RUT": "Russell 2000",
            # Global Indices
            "^GDAXI": "DAX",
            "^N225": "Nikkei",
            "^FTSE": "FTSE 100",
        }

        results: dict[str, dict[str, Any]] = {}
        for symbol, name in tickers.items():
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="1mo")
                if not hist.empty and len(hist) >= 2:
                    current = hist["Close"].iloc[-1]
                    prev_day = hist["Close"].iloc[-2]
                    change_1d = ((current / prev_day) - 1) * 100

                    change_5d = None
                    if len(hist) >= 5:
                        change_5d = ((current / hist["Close"].iloc[-5]) - 1) * 100

                    change_20d = ((current / hist["Close"].iloc[0]) - 1) * 100

                    results[symbol] = {
                        "name": name,
                        "current": current,
                        "change_1d": change_1d,
                        "change_5d": change_5d,
                        "change_20d": change_20d,
                        "high_20d": hist["High"].max(),
                        "low_20d": hist["Low"].min(),
                    }
            except Exception as e:
                logger.warning(f"Failed to fetch {symbol}: {e}")
                continue

        return results

    def _format_macro_context(self, macro_data: dict[str, dict[str, Any]]) -> str:
        """Format macro data as readable context for LLM.

        Args:
            macro_data: Dict of ticker -> indicator data from _fetch_macro_indicators.

        Returns:
            Markdown-formatted string organized by category.
        """
        lines = ["## Current Macro Environment\n"]

        categories = {
            "US Rates": ["^TNX", "^TYX", "^FVX"],
            "Volatility": ["^VIX"],
            "Currency": ["DX-Y.NYB"],
            "Commodities": ["GC=F", "CL=F"],
            "US Indices": ["^GSPC", "^IXIC", "^RUT"],
            "Global Indices": ["^GDAXI", "^N225", "^FTSE"],
        }

        for category, symbols in categories.items():
            lines.append(f"\n### {category}")
            for symbol in symbols:
                if symbol in macro_data:
                    d = macro_data[symbol]
                    change_5d_str = f"{d['change_5d']:+.2f}%" if d.get("change_5d") is not None else "N/A"
                    lines.append(
                        f"- {d['name']}: {d['current']:.2f} "
                        f"(1D: {d['change_1d']:+.2f}%, 5D: {change_5d_str}, "
                        f"20D: {d['change_20d']:+.2f}%)"
                    )

        return "\n".join(lines)

    async def build_sector_rotation_context(self) -> str:
        """Build context for Phase 2: Sector Rotator.

        Fetches sector ETF performance data including:
        - All 11 GICS sectors via Select Sector SPDRs
        - SPY as benchmark
        - Relative strength calculations vs SPY

        Returns:
            Markdown-formatted string with sector performance table.
        """
        sector_data = await self._fetch_sector_data()
        return self._format_sector_context(sector_data)

    async def _fetch_sector_data(self) -> dict[str, dict[str, Any]]:
        """Fetch sector ETF performance data via yfinance.

        Returns:
            Dict mapping ETF symbols to performance data including
            price, returns, volume, and relative strength vs SPY.
        """
        import yfinance as yf

        sector_etfs = {
            "SPY": "S&P 500 (Benchmark)",
            "XLK": "Technology",
            "XLF": "Financials",
            "XLE": "Energy",
            "XLV": "Healthcare",
            "XLI": "Industrials",
            "XLP": "Consumer Staples",
            "XLY": "Consumer Discretionary",
            "XLU": "Utilities",
            "XLC": "Communication Services",
            "XLRE": "Real Estate",
            "XLB": "Materials",
        }

        results: dict[str, dict[str, Any]] = {}
        for symbol, name in sector_etfs.items():
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="1mo")
                if not hist.empty and len(hist) >= 2:
                    current = hist["Close"].iloc[-1]
                    prev_day = hist["Close"].iloc[-2]

                    return_5d = 0.0
                    if len(hist) >= 5:
                        return_5d = ((current / hist["Close"].iloc[-5]) - 1) * 100

                    results[symbol] = {
                        "name": name,
                        "price": current,
                        "return_1d": ((current / prev_day) - 1) * 100,
                        "return_5d": return_5d,
                        "return_20d": ((current / hist["Close"].iloc[0]) - 1) * 100,
                        "volume_avg": hist["Volume"].mean(),
                    }
            except Exception as e:
                logger.warning(f"Failed to fetch sector {symbol}: {e}")
                continue

        # Calculate relative strength vs SPY
        if "SPY" in results:
            spy_20d = results["SPY"]["return_20d"]
            for symbol in results:
                if symbol != "SPY":
                    results[symbol]["relative_strength"] = (
                        results[symbol]["return_20d"] - spy_20d
                    )

        return results

    def _format_sector_context(self, sector_data: dict[str, dict[str, Any]]) -> str:
        """Format sector data for LLM analysis.

        Args:
            sector_data: Dict of ETF symbol -> performance data.

        Returns:
            Markdown-formatted string with performance table sorted by
            relative strength.
        """
        lines = ["## Sector Performance (vs S&P 500)\n"]
        lines.append("| Sector | 5D Return | 20D Return | Rel Strength |")
        lines.append("|--------|-----------|------------|--------------|")

        # Sort by relative strength (descending)
        sorted_sectors = sorted(
            [(k, v) for k, v in sector_data.items() if k != "SPY"],
            key=lambda x: x[1].get("relative_strength", 0),
            reverse=True,
        )

        for symbol, data in sorted_sectors:
            rs = data.get("relative_strength", 0)
            # Use text indicators instead of emojis
            if rs > 2:
                rs_indicator = "[STRONG]"
            elif rs < -2:
                rs_indicator = "[WEAK]"
            else:
                rs_indicator = "[NEUTRAL]"
            lines.append(
                f"| {data['name']} ({symbol}) | {data['return_5d']:+.1f}% | "
                f"{data['return_20d']:+.1f}% | {rs:+.1f}% {rs_indicator} |"
            )

        return "\n".join(lines)

    async def build_discovery_context(
        self,
        macro_result: dict[str, Any],
        sector_result: dict[str, Any],
    ) -> str:
        """Build context for Phase 4: Deep Dive analysts.

        Combines macro and sector context from autonomous scan results
        for symbol-level analysis by specialist agents.

        Args:
            macro_result: Dict with macro scan results containing:
                - market_regime: str (e.g., "risk_on", "risk_off")
                - themes: list of theme dicts with name, direction, rationale
            sector_result: Dict with sector rotation results containing:
                - top_sectors: list of sector dicts with sector_name, rationale
                - sectors_to_avoid: list of sector dicts
                - rotation_active: bool
                - rotation_from: str (optional)
                - rotation_to: str (optional)

        Returns:
            Markdown-formatted string combining macro themes and sector signals.
        """
        context_parts = [
            "## Discovery Context (Autonomous Scan Results)\n",
            f"### Market Regime: {macro_result.get('market_regime', 'unknown')}",
            "\n### Key Macro Themes:",
        ]

        themes = macro_result.get("themes", [])
        for theme in themes:
            if isinstance(theme, dict):
                name = theme.get("name", "Unknown")
                direction = theme.get("direction", "neutral")
                rationale = theme.get("rationale", "")
                context_parts.append(f"- **{name}** ({direction}): {rationale}")

        context_parts.append("\n### Sector Signals:")
        context_parts.append("**Top Sectors:**")

        top_sectors = sector_result.get("top_sectors", [])
        for sector in top_sectors:
            if isinstance(sector, dict):
                sector_name = sector.get("sector_name", "Unknown")
                rationale = sector.get("rationale", "")
                context_parts.append(f"- {sector_name}: {rationale}")

        context_parts.append("\n**Sectors to Avoid:**")
        sectors_to_avoid = sector_result.get("sectors_to_avoid", [])
        for sector in sectors_to_avoid:
            if isinstance(sector, dict):
                sector_name = sector.get("sector_name", "Unknown")
                rationale = sector.get("rationale", "")
                context_parts.append(f"- {sector_name}: {rationale}")

        if sector_result.get("rotation_active"):
            rotation_from = sector_result.get("rotation_from", "unknown")
            rotation_to = sector_result.get("rotation_to", "unknown")
            context_parts.append(
                f"\n### Rotation Signal: {rotation_from} -> {rotation_to}"
            )

        return "\n".join(context_parts)

    async def build_analyst_context_with_discovery(
        self,
        agent_type: str,
        symbols: list[str] | None = None,
        discovery_context: str | None = None,
        max_context_chars: int = 50000,
    ) -> dict[str, Any]:
        """Build context for analysts with optional discovery context.

        Extends build_agent_context to optionally include autonomous
        discovery context from macro/sector scans.

        Args:
            agent_type: Type of agent ('technical', 'macro', etc.).
            symbols: Optional list of symbols to focus on.
            discovery_context: Pre-built discovery context string from
                build_discovery_context().
            max_context_chars: Maximum characters for context (summarize if exceeded).

        Returns:
            Agent-specific context dict with 'discovery_context' key if provided.
        """
        # Get base agent context
        context = await self.build_agent_context(agent_type, symbols)

        if discovery_context:
            # Check if context needs summarization
            if len(discovery_context) > max_context_chars:
                # Truncate with indicator
                discovery_context = (
                    discovery_context[: max_context_chars - 100]
                    + "\n\n... [Context truncated for length] ..."
                )

            context["discovery_context"] = discovery_context

        return context

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
