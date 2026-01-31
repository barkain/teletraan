"""Analysis engine that orchestrates all analysis modules."""

from datetime import datetime
from typing import Any
import json
import logging

from analysis.indicators import indicator_analyzer
from analysis.patterns import pattern_detector
from analysis.anomalies import anomaly_detector
from analysis.sectors import sector_analyzer, SECTOR_ETFS

logger = logging.getLogger(__name__)


class AnalysisEngine:
    """Orchestrates all analysis modules for comprehensive market analysis."""

    def __init__(self) -> None:
        """Initialize the analysis engine."""
        self.indicator_analyzer = indicator_analyzer
        self.pattern_detector = pattern_detector
        self.anomaly_detector = anomaly_detector
        self.sector_analyzer = sector_analyzer
        self._last_run: datetime | None = None

    async def run_full_analysis(
        self,
        symbols: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Run complete analysis pipeline for specified symbols.

        This method is designed to be run as a background task.

        Args:
            symbols: List of stock symbols to analyze. If None, analyzes all.

        Returns:
            Dictionary containing analysis results summary.
        """
        from database import async_session_factory
        from models.stock import Stock
        from models.price import PriceHistory
        from models.insight import Insight
        from sqlalchemy import select

        self._last_run = datetime.utcnow()
        results: dict[str, Any] = {
            "started_at": self._last_run.isoformat(),
            "symbols_analyzed": 0,
            "patterns_detected": 0,
            "anomalies_detected": 0,
            "insights_generated": 0,
            "errors": [],
        }

        async with async_session_factory() as db:
            try:
                # 1. Get stocks to analyze
                if symbols:
                    query = select(Stock).where(
                        Stock.symbol.in_([s.upper() for s in symbols])
                    )
                else:
                    query = select(Stock).where(Stock.is_active == True)  # noqa: E712

                stock_result = await db.execute(query)
                stocks = stock_result.scalars().all()

                for stock in stocks:
                    try:
                        # Fetch price data
                        price_query = (
                            select(PriceHistory)
                            .where(PriceHistory.stock_id == stock.id)
                            .order_by(PriceHistory.date.asc())
                            .limit(300)
                        )
                        price_result = await db.execute(price_query)
                        prices = price_result.scalars().all()

                        if not prices:
                            continue

                        price_data = [
                            {
                                "date": p.date,
                                "open": p.open,
                                "high": p.high,
                                "low": p.low,
                                "close": p.close,
                                "volume": p.volume,
                            }
                            for p in prices
                        ]

                        results["symbols_analyzed"] += 1

                        # 2. Run technical indicators
                        indicator_results = await self.indicator_analyzer.analyze_stock(
                            price_data
                        )
                        signals = await self.indicator_analyzer.get_signals(
                            indicator_results
                        )

                        # Generate insight for strong signals
                        if signals.get("confidence", 0) >= 0.7:
                            insight = Insight(
                                stock_id=stock.id,
                                insight_type="technical",
                                title=f"Strong {signals['overall_signal'].title()} Signal",
                                description=(
                                    f"{stock.symbol}: Technical indicators show "
                                    f"{signals['overall_signal']} bias with "
                                    f"{signals['confidence']:.0%} confidence. "
                                    f"Bullish: {signals['bullish_count']}, "
                                    f"Bearish: {signals['bearish_count']}"
                                ),
                                severity="info",
                                confidence=signals.get("confidence", 0),
                                data_json=json.dumps(signals),
                                is_active=True,
                            )
                            db.add(insight)
                            results["insights_generated"] += 1

                        # 3. Detect patterns
                        patterns = await self.pattern_detector.detect_all_patterns(
                            stock.symbol, price_data
                        )

                        for pattern in patterns:
                            results["patterns_detected"] += 1

                            insight = Insight(
                                stock_id=stock.id,
                                insight_type="pattern",
                                title=f"{pattern.pattern_type.value.replace('_', ' ').title()} Pattern",
                                description=pattern.description,
                                severity="warning" if pattern.confidence >= 0.8 else "info",
                                confidence=pattern.confidence,
                                data_json=json.dumps(pattern.to_dict()),
                                is_active=True,
                            )
                            db.add(insight)
                            results["insights_generated"] += 1

                        # 4. Detect anomalies
                        anomalies = await self.anomaly_detector.detect_all_anomalies(
                            stock.symbol, price_data
                        )

                        for anomaly in anomalies:
                            results["anomalies_detected"] += 1

                            insight = Insight(
                                stock_id=stock.id,
                                insight_type="anomaly",
                                title=f"{anomaly.anomaly_type.value.replace('_', ' ').title()}",
                                description=anomaly.description,
                                severity=anomaly.severity,
                                confidence=min(abs(anomaly.z_score) / 5, 1.0),
                                data_json=json.dumps({
                                    "anomaly_type": anomaly.anomaly_type.value,
                                    "value": anomaly.value,
                                    "z_score": anomaly.z_score,
                                    "expected_range": anomaly.expected_range,
                                }),
                                is_active=True,
                            )
                            db.add(insight)
                            results["insights_generated"] += 1

                    except Exception as e:
                        logger.error(f"Error analyzing {stock.symbol}: {e}")
                        results["errors"].append({
                            "symbol": stock.symbol,
                            "error": str(e),
                        })

                # 5. Analyze sectors (if sector ETFs are in the symbols)
                await self._run_sector_analysis(db, results)

                # Commit all insights
                await db.commit()

            except Exception as e:
                logger.error(f"Analysis engine error: {e}")
                results["errors"].append({"error": str(e)})
                await db.rollback()

        results["completed_at"] = datetime.utcnow().isoformat()
        return results

    async def _run_sector_analysis(
        self,
        db: Any,
        results: dict[str, Any],
    ) -> None:
        """Run sector rotation analysis."""
        from models.stock import Stock
        from models.price import PriceHistory
        from models.insight import Insight
        from sqlalchemy import select

        sector_prices: dict[str, list[dict[str, Any]]] = {}
        benchmark_prices: list[dict[str, Any]] = []

        # Fetch sector ETF data
        for etf_symbol in SECTOR_ETFS.keys():
            stock_query = select(Stock).where(Stock.symbol == etf_symbol)
            stock = (await db.execute(stock_query)).scalar_one_or_none()

            if stock:
                price_query = (
                    select(PriceHistory)
                    .where(PriceHistory.stock_id == stock.id)
                    .order_by(PriceHistory.date.desc())
                    .limit(100)
                )
                price_result = await db.execute(price_query)
                prices = price_result.scalars().all()

                sector_prices[etf_symbol] = [
                    {
                        "date": p.date.isoformat(),
                        "open": p.open,
                        "high": p.high,
                        "low": p.low,
                        "close": p.close,
                        "volume": p.volume,
                    }
                    for p in prices
                ]

        # Fetch SPY as benchmark
        spy_query = select(Stock).where(Stock.symbol == "SPY")
        spy_stock = (await db.execute(spy_query)).scalar_one_or_none()

        if spy_stock:
            spy_price_query = (
                select(PriceHistory)
                .where(PriceHistory.stock_id == spy_stock.id)
                .order_by(PriceHistory.date.desc())
                .limit(100)
            )
            spy_result = await db.execute(spy_price_query)
            spy_prices = spy_result.scalars().all()
            benchmark_prices = [
                {
                    "date": p.date.isoformat(),
                    "close": p.close,
                    "volume": p.volume,
                }
                for p in spy_prices
            ]

        if sector_prices:
            try:
                summary = await self.sector_analyzer.get_sector_summary(
                    sector_prices,
                    benchmark_prices,
                    economic_data=None,
                )

                # Create sector insights
                for insight_data in summary.get("insights", []):
                    insight = Insight(
                        stock_id=None,  # Market-wide insight
                        insight_type="sector",
                        title=insight_data.get("title", "Sector Insight"),
                        description=insight_data.get("description", ""),
                        severity=(
                            "alert" if insight_data.get("priority") == "high"
                            else "warning" if insight_data.get("priority") == "medium"
                            else "info"
                        ),
                        confidence=0.7,
                        data_json=json.dumps(insight_data),
                        is_active=True,
                    )
                    db.add(insight)
                    results["insights_generated"] += 1

                # Create market phase insight
                market_phase = summary.get("market_phase", "unknown")
                phase_insight = Insight(
                    stock_id=None,
                    insight_type="sector",
                    title=f"Market Phase: {market_phase.replace('_', ' ').title()}",
                    description=summary.get("phase_description", ""),
                    severity="info",
                    confidence=0.6,
                    data_json=json.dumps({
                        "market_phase": market_phase,
                        "expected_leaders": summary.get("expected_leaders", []),
                        "rotation_analysis": summary.get("rotation_analysis", {}),
                    }),
                    is_active=True,
                )
                db.add(phase_insight)
                results["insights_generated"] += 1

            except Exception as e:
                logger.error(f"Sector analysis error: {e}")
                results["errors"].append({"sector_analysis": str(e)})

    async def generate_insights(
        self,
        analysis_results: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Generate insight records from analysis results.

        Args:
            analysis_results: Results from analysis modules.

        Returns:
            List of insight dictionaries ready for storage.
        """
        insights: list[dict[str, Any]] = []

        # Process technical signals
        if "technical" in analysis_results:
            tech = analysis_results["technical"]
            if tech.get("confidence", 0) >= 0.7:
                insights.append({
                    "type": "technical",
                    "title": f"Strong {tech['overall_signal'].title()} Signal",
                    "description": (
                        f"Technical indicators show {tech['overall_signal']} bias "
                        f"with {tech['confidence']:.0%} confidence"
                    ),
                    "severity": "info",
                    "confidence": tech["confidence"],
                    "data": tech,
                })

        # Process patterns
        if "patterns" in analysis_results:
            for pattern in analysis_results["patterns"]:
                insights.append({
                    "type": "pattern",
                    "title": pattern.get("pattern_type", "Pattern").replace("_", " ").title(),
                    "description": pattern.get("description", ""),
                    "severity": "warning" if pattern.get("confidence", 0) >= 0.8 else "info",
                    "confidence": pattern.get("confidence", 0),
                    "data": pattern,
                })

        # Process anomalies
        if "anomalies" in analysis_results:
            for anomaly in analysis_results["anomalies"]:
                insights.append({
                    "type": "anomaly",
                    "title": anomaly.get("anomaly_type", "Anomaly").replace("_", " ").title(),
                    "description": anomaly.get("description", ""),
                    "severity": anomaly.get("severity", "info"),
                    "confidence": min(abs(anomaly.get("z_score", 0)) / 5, 1.0),
                    "data": anomaly,
                })

        return insights

    @property
    def last_run(self) -> datetime | None:
        """Get the timestamp of the last analysis run."""
        return self._last_run


# Global singleton instance
analysis_engine = AnalysisEngine()
