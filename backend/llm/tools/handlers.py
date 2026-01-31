"""Tool handlers for the market analysis LLM agent.

This module implements the handlers for each tool available to the agent.
Each handler fetches data from the appropriate adapter and returns formatted results.
"""

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from analysis.anomalies import anomaly_detector
from analysis.indicators import indicator_analyzer
from analysis.patterns import pattern_detector
from analysis.sectors import sector_analyzer
from data.adapters.fred import fred_adapter
from data.adapters.yahoo import yahoo_adapter

logger = logging.getLogger(__name__)


async def get_stock_data_handler(symbol: str) -> dict[str, Any]:
    """Get current price and company information for a stock.

    Args:
        symbol: Stock ticker symbol.

    Returns:
        Dict with stock info including price, change, volume, sector, market cap.
    """
    try:
        # Get stock info and current price in parallel
        stock_info = await yahoo_adapter.get_stock_info(symbol)
        price_data = await yahoo_adapter.get_current_price(symbol)

        return {
            "symbol": symbol.upper(),
            "name": stock_info.get("name"),
            "sector": stock_info.get("sector"),
            "industry": stock_info.get("industry"),
            "market_cap": stock_info.get("market_cap"),
            "price": price_data.get("price"),
            "previous_close": price_data.get("previous_close"),
            "change": price_data.get("change"),
            "change_percent": price_data.get("change_percent"),
            "day_high": price_data.get("day_high"),
            "day_low": price_data.get("day_low"),
            "volume": price_data.get("volume"),
        }
    except Exception as e:
        logger.error(f"Error getting stock data for {symbol}: {e}")
        return {"error": str(e), "symbol": symbol}


async def get_price_history_handler(
    symbol: str,
    period: str = "3mo"
) -> dict[str, Any]:
    """Get historical price data for a stock.

    Args:
        symbol: Stock ticker symbol.
        period: Time period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y).

    Returns:
        Dict with price history data including dates and OHLCV values.
    """
    try:
        prices = await yahoo_adapter.get_price_history(symbol, period=period)

        if not prices:
            return {"error": f"No price history found for {symbol}", "symbol": symbol}

        # Calculate summary stats
        closes = [p["close"] for p in prices if p.get("close")]
        if closes:
            period_return = ((closes[-1] - closes[0]) / closes[0]) * 100 if closes[0] else 0
            high = max(closes)
            low = min(closes)
        else:
            period_return = 0
            high = 0
            low = 0

        return {
            "symbol": symbol.upper(),
            "period": period,
            "data_points": len(prices),
            "start_date": str(prices[0].get("date")) if prices else None,
            "end_date": str(prices[-1].get("date")) if prices else None,
            "period_return_pct": round(period_return, 2),
            "period_high": round(high, 2),
            "period_low": round(low, 2),
            "latest_close": round(closes[-1], 2) if closes else None,
            "prices": prices[-30:],  # Return last 30 data points for context
        }
    except Exception as e:
        logger.error(f"Error getting price history for {symbol}: {e}")
        return {"error": str(e), "symbol": symbol}


async def analyze_technical_handler(symbol: str) -> dict[str, Any]:
    """Run comprehensive technical analysis on a stock.

    Args:
        symbol: Stock ticker symbol.

    Returns:
        Dict with technical indicators, signals, and overall assessment.
    """
    try:
        # Get price history for analysis (need enough data for indicators)
        prices = await yahoo_adapter.get_price_history(symbol, period="1y")

        if not prices or len(prices) < 50:
            return {
                "error": f"Insufficient price history for technical analysis on {symbol}",
                "symbol": symbol
            }

        # Run indicator analysis
        indicator_results = await indicator_analyzer.analyze_stock(prices)

        # Get aggregated signals
        signals = await indicator_analyzer.get_signals(indicator_results)

        # Detect MA crossovers
        closes = [p["close"] for p in prices if p.get("close")]
        crossovers = await indicator_analyzer.detect_crossovers(closes)

        # Format indicator results
        formatted_indicators = {}
        for name, result in indicator_results.items():
            formatted_indicators[name] = {
                "name": result.name,
                "value": round(result.value, 4),
                "signal": result.signal,
                "strength": round(result.strength, 4),
            }

        return {
            "symbol": symbol.upper(),
            "overall_signal": signals.get("overall_signal"),
            "confidence": signals.get("confidence"),
            "bullish_indicators": signals.get("bullish_count"),
            "bearish_indicators": signals.get("bearish_count"),
            "neutral_indicators": signals.get("neutral_count"),
            "indicators": formatted_indicators,
            "crossovers": crossovers,
            "analysis_period": "1 year",
            "data_points": len(prices),
        }
    except Exception as e:
        logger.error(f"Error in technical analysis for {symbol}: {e}")
        return {"error": str(e), "symbol": symbol}


async def get_sector_performance_handler() -> dict[str, Any]:
    """Get performance data for all market sectors.

    Returns:
        Dict with sector performance data including daily changes.
    """
    try:
        sector_data = await yahoo_adapter.get_sector_performance()

        # Also get index performance for context
        index_data = await yahoo_adapter.get_index_performance()

        # Sort sectors by change percent
        sorted_sectors = sorted(
            [
                {"sector": name, **data}
                for name, data in sector_data.items()
                if "error" not in data
            ],
            key=lambda x: x.get("change_percent", 0) or 0,
            reverse=True
        )

        return {
            "sectors": sorted_sectors,
            "top_performer": sorted_sectors[0] if sorted_sectors else None,
            "worst_performer": sorted_sectors[-1] if sorted_sectors else None,
            "market_indices": index_data,
        }
    except Exception as e:
        logger.error(f"Error getting sector performance: {e}")
        return {"error": str(e)}


async def analyze_sector_rotation_handler() -> dict[str, Any]:
    """Analyze sector rotation patterns and market cycle phase.

    Returns:
        Dict with sector analysis including rotation signals and market phase.
    """
    try:
        # Get sector price history for analysis
        sector_symbols = list(sector_analyzer.sector_names.keys())
        sector_prices: dict[str, list[dict[str, Any]]] = {}

        for symbol in sector_symbols:
            try:
                prices = await yahoo_adapter.get_price_history(symbol, period="3mo")
                if prices:
                    sector_prices[symbol] = prices
            except Exception as e:
                logger.warning(f"Could not get prices for {symbol}: {e}")

        if not sector_prices:
            return {"error": "Could not retrieve sector price data"}

        # Get benchmark (SPY) for relative strength
        benchmark_prices = await yahoo_adapter.get_price_history("SPY", period="3mo")

        # Get economic indicators for phase identification
        economic_data: dict[str, float] = {}
        if fred_adapter.is_available:
            indicators = await fred_adapter.get_key_indicators()
            if indicators.get("GDP"):
                economic_data["gdp_growth"] = indicators["GDP"].get("value", 2.0)
            if indicators.get("CPIAUCSL"):
                economic_data["inflation"] = indicators["CPIAUCSL"].get("value", 2.5)
            if indicators.get("UNRATE"):
                economic_data["unemployment"] = indicators["UNRATE"].get("value", 4.0)
            if indicators.get("T10Y2Y"):
                economic_data["yield_curve"] = indicators["T10Y2Y"].get("value", 0.5)

        # Run full sector analysis
        summary = await sector_analyzer.get_sector_summary(
            sector_prices,
            benchmark_prices,
            economic_data
        )

        return summary
    except Exception as e:
        logger.error(f"Error in sector rotation analysis: {e}")
        return {"error": str(e)}


async def detect_patterns_handler(symbol: str) -> dict[str, Any]:
    """Detect chart patterns for a stock.

    Args:
        symbol: Stock ticker symbol.

    Returns:
        Dict with detected patterns including type, confidence, and price targets.
    """
    try:
        # Get sufficient price history for pattern detection
        prices = await yahoo_adapter.get_price_history(symbol, period="1y")

        if not prices or len(prices) < 30:
            return {
                "error": f"Insufficient price history for pattern detection on {symbol}",
                "symbol": symbol
            }

        # Detect all patterns
        patterns = await pattern_detector.detect_all_patterns(symbol, prices)

        # Get pattern summary
        summary = await pattern_detector.get_pattern_summary(patterns)

        # Get support/resistance levels
        sr_levels = await pattern_detector.detect_support_resistance(prices)

        # Get current trend
        trend_type, trend_confidence = await pattern_detector.detect_trend(prices)

        return {
            "symbol": symbol.upper(),
            "current_trend": trend_type.value,
            "trend_confidence": round(trend_confidence, 4),
            "support_levels": sr_levels.get("support", []),
            "resistance_levels": sr_levels.get("resistance", []),
            "pattern_summary": {
                "total_patterns": summary.get("total_patterns"),
                "bullish_patterns": summary.get("bullish_patterns"),
                "bearish_patterns": summary.get("bearish_patterns"),
                "overall_bias": summary.get("overall_bias"),
                "confidence": summary.get("confidence"),
            },
            "detected_patterns": summary.get("patterns", []),
        }
    except Exception as e:
        logger.error(f"Error detecting patterns for {symbol}: {e}")
        return {"error": str(e), "symbol": symbol}


async def detect_anomalies_handler(symbol: str) -> dict[str, Any]:
    """Detect unusual market activity for a stock.

    Args:
        symbol: Stock ticker symbol.

    Returns:
        Dict with detected anomalies including type, severity, and z-scores.
    """
    try:
        # Get recent price history
        prices = await yahoo_adapter.get_price_history(symbol, period="3mo")

        if not prices or len(prices) < 20:
            return {
                "error": f"Insufficient price history for anomaly detection on {symbol}",
                "symbol": symbol
            }

        # Detect all anomalies
        anomalies = await anomaly_detector.detect_all_anomalies(symbol, prices)

        # Format anomaly results
        formatted_anomalies = []
        for anomaly in anomalies:
            formatted_anomalies.append({
                "type": anomaly.anomaly_type.value,
                "severity": anomaly.severity,
                "value": round(anomaly.value, 4),
                "expected_range": (
                    round(anomaly.expected_range[0], 4),
                    round(anomaly.expected_range[1], 4)
                ),
                "z_score": round(anomaly.z_score, 2),
                "description": anomaly.description,
                "detected_at": anomaly.detected_at.isoformat(),
            })

        # Count by severity
        alert_count = sum(1 for a in anomalies if a.severity == "alert")
        warning_count = sum(1 for a in anomalies if a.severity == "warning")
        info_count = sum(1 for a in anomalies if a.severity == "info")

        return {
            "symbol": symbol.upper(),
            "total_anomalies": len(anomalies),
            "alerts": alert_count,
            "warnings": warning_count,
            "info": info_count,
            "anomalies": formatted_anomalies,
            "has_critical_anomalies": alert_count > 0,
        }
    except Exception as e:
        logger.error(f"Error detecting anomalies for {symbol}: {e}")
        return {"error": str(e), "symbol": symbol}


async def get_economic_indicators_handler() -> dict[str, Any]:
    """Get key economic indicators from FRED.

    Returns:
        Dict with economic indicators including GDP, unemployment, CPI, etc.
    """
    try:
        if not fred_adapter.is_available:
            return {
                "error": "FRED API key not configured. Economic indicators unavailable.",
                "available": False
            }

        indicators = await fred_adapter.get_key_indicators()

        # Check yield curve status
        is_inverted = await fred_adapter.is_yield_curve_inverted()

        return {
            "available": True,
            "indicators": indicators,
            "yield_curve_inverted": is_inverted,
            "summary": {
                "gdp": indicators.get("GDP", {}).get("value"),
                "unemployment": indicators.get("UNRATE", {}).get("value"),
                "inflation_cpi": indicators.get("CPIAUCSL", {}).get("value"),
                "fed_funds_rate": indicators.get("FEDFUNDS", {}).get("value"),
                "vix": indicators.get("VIXCLS", {}).get("value"),
                "consumer_sentiment": indicators.get("UMCSENT", {}).get("value"),
                "yield_spread_10y_2y": indicators.get("T10Y2Y", {}).get("value"),
            }
        }
    except Exception as e:
        logger.error(f"Error getting economic indicators: {e}")
        return {"error": str(e), "available": False}


async def get_yield_curve_handler() -> dict[str, Any]:
    """Get current treasury yields for yield curve analysis.

    Returns:
        Dict with treasury yields at various maturities.
    """
    try:
        if not fred_adapter.is_available:
            return {
                "error": "FRED API key not configured. Yield curve data unavailable.",
                "available": False
            }

        yields = await fred_adapter.get_yield_curve()
        is_inverted = await fred_adapter.is_yield_curve_inverted()

        # Format maturity labels
        maturity_labels = {
            "1": "1 Month",
            "3": "3 Months",
            "6": "6 Months",
            "12": "1 Year",
            "24": "2 Years",
            "60": "5 Years",
            "84": "7 Years",
            "120": "10 Years",
            "240": "20 Years",
            "360": "30 Years",
        }

        formatted_yields = {}
        for maturity, rate in yields.items():
            label = maturity_labels.get(maturity, f"{maturity} Months")
            formatted_yields[label] = rate

        # Calculate spread
        spread_10y_2y = None
        if "120" in yields and "24" in yields:
            spread_10y_2y = yields["120"] - yields["24"]

        return {
            "available": True,
            "yields": formatted_yields,
            "raw_yields": yields,
            "is_inverted": is_inverted,
            "spread_10y_2y": round(spread_10y_2y, 3) if spread_10y_2y else None,
            "interpretation": (
                "Yield curve is INVERTED - historically signals recession risk"
                if is_inverted
                else "Yield curve is normal - longer maturities yield more"
            ) if is_inverted is not None else "Unable to determine yield curve status"
        }
    except Exception as e:
        logger.error(f"Error getting yield curve: {e}")
        return {"error": str(e), "available": False}


async def compare_stocks_handler(symbols: list[str]) -> dict[str, Any]:
    """Compare multiple stocks on key metrics.

    Args:
        symbols: List of stock ticker symbols to compare (max 5).

    Returns:
        Dict with comparison data for each stock.
    """
    try:
        # Limit to 5 symbols
        symbols = symbols[:5]

        comparisons = []
        for symbol in symbols:
            try:
                # Get basic data
                stock_data = await get_stock_data_handler(symbol)

                # Get simple technical signal
                tech_data = await analyze_technical_handler(symbol)

                comparisons.append({
                    "symbol": symbol.upper(),
                    "name": stock_data.get("name"),
                    "sector": stock_data.get("sector"),
                    "price": stock_data.get("price"),
                    "change_percent": stock_data.get("change_percent"),
                    "market_cap": stock_data.get("market_cap"),
                    "volume": stock_data.get("volume"),
                    "technical_signal": tech_data.get("overall_signal"),
                    "technical_confidence": tech_data.get("confidence"),
                    "bullish_indicators": tech_data.get("bullish_indicators"),
                    "bearish_indicators": tech_data.get("bearish_indicators"),
                })
            except Exception as e:
                logger.warning(f"Error comparing {symbol}: {e}")
                comparisons.append({
                    "symbol": symbol.upper(),
                    "error": str(e)
                })

        # Sort by change percent
        valid_comparisons = [c for c in comparisons if "error" not in c]
        sorted_by_change = sorted(
            valid_comparisons,
            key=lambda x: x.get("change_percent") or 0,
            reverse=True
        )

        return {
            "symbols_compared": len(symbols),
            "comparisons": comparisons,
            "best_performer": sorted_by_change[0]["symbol"] if sorted_by_change else None,
            "worst_performer": sorted_by_change[-1]["symbol"] if sorted_by_change else None,
        }
    except Exception as e:
        logger.error(f"Error comparing stocks: {e}")
        return {"error": str(e), "symbols": symbols}


# Registry of tool handlers
tool_handlers: dict[str, Callable[..., Coroutine[Any, Any, dict[str, Any]]]] = {
    "get_stock_data": get_stock_data_handler,
    "get_price_history": get_price_history_handler,
    "analyze_technical": analyze_technical_handler,
    "get_sector_performance": get_sector_performance_handler,
    "analyze_sector_rotation": analyze_sector_rotation_handler,
    "detect_patterns": detect_patterns_handler,
    "detect_anomalies": detect_anomalies_handler,
    "get_economic_indicators": get_economic_indicators_handler,
    "get_yield_curve": get_yield_curve_handler,
    "compare_stocks": compare_stocks_handler,
}
