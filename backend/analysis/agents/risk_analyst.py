"""Risk Analyst agent for volatility analysis, downside risk assessment, and position sizing."""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from analysis.price_freshness import (
    build_freshness,
    describe,
    is_usable,
    price_line,
    snapshot_price,
    stale_warning,
)
from analysis.symbol_slice import (
    format_peer_comparison,
    slice_context_for_symbol,
    target_banner,
)

logger = logging.getLogger(__name__)


RISK_ANALYST_PROMPT = """You are a Risk Analyst specializing in volatility analysis, downside risk assessment, and position sizing.

## Your Expertise
- Volatility regime analysis (VIX levels and term structure)
- Realized vs implied volatility analysis
- Drawdown risk quantification
- Tail risk assessment
- Position sizing recommendations
- Portfolio correlation risk
- Stop-loss and invalidation trigger identification

## Risk Metrics You Calculate
- Value at Risk (VaR) estimates
- Maximum drawdown scenarios
- Volatility-adjusted returns
- Risk/reward ratios
- Correlation-based portfolio risk

## Your Task
Assess risk for proposed positions and identify:
1. **Volatility regime** - Current vol environment and expectations
2. **Downside scenarios** - What could go wrong and by how much
3. **Position sizing** - Appropriate size given risk
4. **Invalidation triggers** - When to exit if wrong
5. **Portfolio considerations** - Correlation with existing positions

## Volatility Regime Indicators

When rich technical analysis data is provided, pay special attention to the volatility indicators:
- **ATR (Average True Range):** Rising ATR indicates increasing volatility/risk. Compare current ATR to recent average to assess volatility regime.
- **Bollinger Band width/squeeze:** Narrow bandwidth = low volatility (potential breakout setup). Wide bandwidth = high volatility. %B position indicates overbought/oversold.
- **Keltner Channels:** Price outside channels signals momentum breakout. Bollinger squeeze inside Keltner = strong squeeze setup.
- **Volume/SMA ratio:** High volume with volatility expansion confirms the move. Low volume with expansion suggests false breakout risk.

Use these indicators to:
1. Assess current volatility regime (low/normal/high/extreme)
2. Identify squeeze setups (potential for large moves)
3. Evaluate whether current price action is supported by volume
4. Factor volatility into position sizing and risk recommendations

## Tail Risk from Prediction Markets
When prediction market data is available, incorporate tail event probabilities:
- Recession probability as a macro tail risk factor
- Geopolitical event probabilities (if available)
- Market-implied probability of extreme outcomes

## Social Sentiment as Contrarian Signal
When Reddit sentiment data is available:
- Extreme bullish sentiment (>0.7) may indicate complacency -- increase risk assessment
- Extreme bearish sentiment (<-0.7) may indicate capitulation -- potential contrarian buy signal
- Rapid sentiment shifts indicate regime change risk
- High mention velocity for a symbol suggests crowded positioning

## Output Format
Return JSON:
{
  "analyst": "risk",
  "volatility_regime": {
    "current_vix": 15.5,
    "regime": "low_vol",  // low_vol/normal/elevated/crisis
    "term_structure": "contango",
    "implication": "Complacency, potential for vol spike"
  },
  "risk_assessments": [
    {
      "symbol": "NVDA",
      "current_price": 880,
      "downside_target": 800,
      "max_drawdown_pct": 9.1,
      "var_95_daily": 3.2,
      "risk_reward": 2.5,
      "position_size_suggestion": "2-3% of portfolio",
      "stop_loss": 845,
      "invalidation_trigger": "Close below 850 on high volume"
    }
  ],
  "portfolio_risks": [
    "High tech concentration increases correlation risk",
    "Low vol regime suggests hedges are cheap"
  ],
  "tail_risks": [
    {"event": "Fed surprise hike", "probability": 0.05, "impact": "severe"},
    {"event": "Earnings miss", "probability": 0.20, "impact": "moderate"}
  ],
  "key_observations": ["..."],
  "confidence": 0.72
}
"""


@dataclass
class VolatilityRegime:
    """Represents the current volatility regime assessment."""

    current_vix: float
    regime: str  # low_vol, normal, elevated, crisis
    term_structure: str  # contango, backwardation, flat
    implication: str


@dataclass
class RiskAssessment:
    """Risk assessment for a single symbol."""

    symbol: str
    current_price: float
    downside_target: float
    max_drawdown_pct: float
    var_95_daily: float
    risk_reward: float
    position_size_suggestion: str
    stop_loss: float
    invalidation_trigger: str


@dataclass
class TailRisk:
    """Represents a tail risk event."""

    event: str
    probability: float
    impact: str  # mild, moderate, severe, extreme


@dataclass
class RiskAnalysisResult:
    """Complete risk analysis result from the Risk Analyst agent."""

    analyst: str = "risk"
    volatility_regime: VolatilityRegime | None = None
    risk_assessments: list[RiskAssessment] = field(default_factory=list)
    portfolio_risks: list[str] = field(default_factory=list)
    tail_risks: list[TailRisk] = field(default_factory=list)
    key_observations: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary format."""
        return {
            "analyst": self.analyst,
            "volatility_regime": {
                "current_vix": self.volatility_regime.current_vix if self.volatility_regime else 0.0,
                "regime": self.volatility_regime.regime if self.volatility_regime else "unknown",
                "term_structure": self.volatility_regime.term_structure if self.volatility_regime else "unknown",
                "implication": self.volatility_regime.implication if self.volatility_regime else "",
            },
            "risk_assessments": [
                {
                    "symbol": ra.symbol,
                    "current_price": ra.current_price,
                    "downside_target": ra.downside_target,
                    "max_drawdown_pct": ra.max_drawdown_pct,
                    "var_95_daily": ra.var_95_daily,
                    "risk_reward": ra.risk_reward,
                    "position_size_suggestion": ra.position_size_suggestion,
                    "stop_loss": ra.stop_loss,
                    "invalidation_trigger": ra.invalidation_trigger,
                }
                for ra in self.risk_assessments
            ],
            "portfolio_risks": self.portfolio_risks,
            "tail_risks": [
                {
                    "event": tr.event,
                    "probability": tr.probability,
                    "impact": tr.impact,
                }
                for tr in self.tail_risks
            ],
            "key_observations": self.key_observations,
            "confidence": self.confidence,
        }


def _format_volatility_context(rich_ta: dict) -> str:
    """Extract and format volatility-relevant data from rich technical analysis.

    Produces a focused subset of the rich TA data covering only volatility
    and volume indicators that the risk analyst needs for regime assessment,
    squeeze detection, and position sizing guidance.

    Args:
        rich_ta: Dict mapping symbol -> rich TA data dict (as produced by
            ``MarketContextBuilder._get_rich_technical``).  Each symbol entry
            contains 'volatility', 'volume', 'latest_price', and
            'signal_summary' sub-dicts.

    Returns:
        Formatted markdown string with volatility context per symbol.
        Empty string when *rich_ta* is empty or contains no useful data.
    """
    if not rich_ta:
        return ""

    lines: list[str] = ["\n=== RICH VOLATILITY INDICATORS ==="]

    for symbol, data in sorted(rich_ta.items()):
        latest_price = data.get("latest_price", 0)
        # This price comes from yfinance, independently of the stored bars the
        # rest of the prompt uses; date it so the two can be compared.
        price_freshness = build_freshness(
            symbol, data.get("latest_date"), latest_price or None, "yfinance_history",
        )
        vol_data = data.get("volatility", {})
        volume_data = data.get("volume", {})
        signal_summary = data.get("signal_summary", {})
        breakdown = signal_summary.get("breakdown", {})

        section_parts: list[str] = []

        # --- ATR ---
        atr = vol_data.get("atr_14")
        if atr is not None:
            if latest_price and is_usable(price_freshness):
                atr_pct = atr / latest_price * 100
                section_parts.append(
                    f"  ATR (14): ${atr:.2f} ({atr_pct:.1f}% of the "
                    f"{price_freshness.get('latest_bar_date')} price)"
                )
            else:
                section_parts.append(
                    f"  ATR (14): ${atr:.2f} (% of price withheld -- "
                    "no current price to measure against)"
                )

        # --- Bollinger Bands ---
        bb = vol_data.get("bollinger", {})
        if isinstance(bb, dict):
            pct_b = bb.get("percent_b")
            bandwidth = bb.get("bandwidth")
            upper = bb.get("upper")
            lower = bb.get("lower")

            if pct_b is not None:
                if pct_b > 1.0:
                    bb_label = "ABOVE upper band"
                elif pct_b < 0.0:
                    bb_label = "BELOW lower band"
                elif pct_b > 0.8:
                    bb_label = "near upper band"
                elif pct_b < 0.2:
                    bb_label = "near lower band"
                else:
                    bb_label = "mid-range"
                section_parts.append(f"  Bollinger %B: {pct_b:.2f} ({bb_label})")

            if bandwidth is not None:
                # Low bandwidth suggests squeeze
                if bandwidth < 5:
                    bw_label = "TIGHT (squeeze setup)"
                elif bandwidth < 10:
                    bw_label = "narrow"
                elif bandwidth > 25:
                    bw_label = "WIDE (high volatility)"
                else:
                    bw_label = "normal"
                section_parts.append(f"  Bollinger Bandwidth: {bandwidth:.1f} ({bw_label})")

            if upper is not None and lower is not None:
                section_parts.append(f"  Bollinger Bands: ${lower:.2f} - ${upper:.2f}")

        # --- Keltner Channels ---
        kc = vol_data.get("keltner", {})
        if isinstance(kc, dict):
            kc_upper = kc.get("upper")
            kc_lower = kc.get("lower")
            if kc_upper is not None and kc_lower is not None:
                section_parts.append(f"  Keltner Channels: ${kc_lower:.2f} - ${kc_upper:.2f}")
                # Detect Bollinger-inside-Keltner squeeze
                if isinstance(bb, dict) and bb.get("upper") and bb.get("lower"):
                    bb_inside_kc = (
                        bb["upper"] < kc_upper and bb["lower"] > kc_lower
                    )
                    if bb_inside_kc:
                        section_parts.append("  ** SQUEEZE DETECTED: Bollinger inside Keltner **")
                # Price outside Keltner
                if latest_price and kc_upper and kc_lower:
                    if latest_price > kc_upper:
                        section_parts.append("  Price ABOVE Keltner upper (momentum breakout)")
                    elif latest_price < kc_lower:
                        section_parts.append("  Price BELOW Keltner lower (momentum breakdown)")

        # --- Volume ---
        vol_ratio = volume_data.get("volume_sma_ratio")
        if vol_ratio is not None:
            if vol_ratio > 2.0:
                vol_label = "VERY HIGH (confirms move)"
            elif vol_ratio > 1.5:
                vol_label = "elevated"
            elif vol_ratio > 1.2:
                vol_label = "above average"
            elif vol_ratio < 0.5:
                vol_label = "VERY LOW (lack of conviction)"
            elif vol_ratio < 0.8:
                vol_label = "below average"
            else:
                vol_label = "near average"
            section_parts.append(f"  Volume/SMA Ratio: {vol_ratio:.2f} ({vol_label})")

        # --- Composite volatility sub-score ---
        vol_score = breakdown.get("volatility")
        if vol_score is not None:
            section_parts.append(f"  Volatility Sub-Score: {vol_score:.1f}")

        if section_parts:
            lines.append(f"\n--- {symbol} (Price: ${latest_price:.2f} {describe(price_freshness)}) ---")
            lines.extend(section_parts)

    if len(lines) <= 1:
        return ""

    return "\n".join(lines)


def format_risk_context(market_data: dict, target_symbol: str | None = None) -> str:
    """
    Format volatility and risk data for analyst consumption.

    Args:
        market_data: Dictionary containing market data from context builder:
            - price_history: Dict mapping symbols to list of OHLCV dicts
            - technical_indicators: Dict mapping symbols to indicator values (including ATR)
            - stocks: List of stock metadata
            - sector_performance: Dict mapping sector ETFs to performance metrics
            - economic_indicators: List of economic indicator dicts
            - market_summary: Overall market status
            - rich_technical: (optional) Dict mapping symbols to rich TA data
            Or legacy format with vix_data, price_data, portfolio, correlations.
        target_symbol: The one symbol this analysis is about.  When given, the
            price/volatility section covers only that symbol and the others move
            into a labelled comparison block; sector performance and economic
            risk factors stay shared.  When omitted, every symbol is rendered as
            before.

    Returns:
        Formatted string context for the risk analyst prompt.
    """
    context_parts = []

    if target_symbol:
        market_data = slice_context_for_symbol(market_data, target_symbol)
        context_parts.append(target_banner(target_symbol))
        context_parts.append("")

    # Check for new context builder format
    price_history = market_data.get("price_history", {})
    technical_indicators = market_data.get("technical_indicators", {})
    stocks = market_data.get("stocks", [])

    if price_history and isinstance(price_history, dict):
        # New format from context builder

        context_parts.append("=== PRICE AND VOLATILITY DATA ===")

        for symbol, prices in price_history.items():
            if not prices:
                continue

            context_parts.append(f"\n--- {symbol} ---")

            # Get stock metadata
            stock_info = next(
                (s for s in stocks if isinstance(s, dict) and s.get("symbol") == symbol),
                {"symbol": symbol}
            )
            if stock_info.get("sector"):
                context_parts.append(f"Sector: {stock_info.get('sector')}")

            # The reconciled snapshot drives every derived risk metric below.
            # The bar at index 0 is whatever the last ingest stored -- calling
            # its high/low "Today's" was wrong whenever the ETL had lagged.
            latest = prices[0]
            current_price, freshness = snapshot_price(market_data, symbol)
            if not current_price:
                current_price = float(latest.get("close", 0))

            warning = stale_warning(freshness)
            if warning:
                context_parts.append(warning)
            context_parts.append(price_line(freshness, label="Last Close"))

            bar_date = str(latest.get("date", ""))[:10] or "unknown date"
            context_parts.append(f"Session High ({bar_date}): ${latest.get('high', 0):.2f}")
            context_parts.append(f"Session Low ({bar_date}): ${latest.get('low', 0):.2f}")
            context_parts.append(f"Volume ({bar_date}): {latest.get('volume', 0):,}")

            # Calculate historical volatility from price data
            if len(prices) >= 21:
                # 20-day historical volatility
                closes = [p.get("close", 0) for p in prices[:21] if p.get("close")]
                if len(closes) >= 21:
                    daily_returns = []
                    for i in range(1, len(closes)):
                        if closes[i-1] > 0:
                            daily_returns.append((closes[i] - closes[i-1]) / closes[i-1])
                    if daily_returns:
                        import math
                        mean_return = sum(daily_returns) / len(daily_returns)
                        variance = sum((r - mean_return) ** 2 for r in daily_returns) / len(daily_returns)
                        daily_vol = math.sqrt(variance)
                        annual_vol = daily_vol * math.sqrt(252) * 100
                        context_parts.append(f"20-Day Historical Vol: {annual_vol:.1f}%")

            # Calculate max drawdown from available data
            if len(prices) >= 5:
                highs = [p.get("high", 0) for p in prices if p.get("high")]
                lows = [p.get("low", 0) for p in prices if p.get("low")]
                if highs and lows:
                    peak = max(highs)
                    trough = min(lows)
                    if peak > 0:
                        max_dd = ((peak - trough) / peak) * 100
                        context_parts.append(f"Max Drawdown (period): {max_dd:.1f}%")

            # Calculate support/resistance from price data
            if len(prices) >= 20:
                recent_lows = [p.get("low", float("inf")) for p in prices[:20] if p.get("low")]
                recent_highs = [p.get("high", 0) for p in prices[:20] if p.get("high")]
                if recent_lows and recent_highs:
                    support = min(recent_lows)
                    resistance = max(recent_highs)
                    window_start = str(prices[19].get("date", ""))[:10] or "?"
                    window_end = str(prices[0].get("date", ""))[:10] or "?"
                    window = f"window {window_start} to {window_end}"
                    context_parts.append(f"20-Period Support: ${support:.2f} ({window})")
                    context_parts.append(f"20-Period Resistance: ${resistance:.2f} ({window})")

            # Technical indicators for this symbol (e.g., ATR)
            indicators = technical_indicators.get(symbol, {})
            if indicators:
                for ind_type, ind_data in indicators.items():
                    if isinstance(ind_data, dict):
                        value = ind_data.get("value")
                        if value is not None:
                            if ind_type.lower() == "atr":
                                if current_price > 0 and is_usable(freshness):
                                    atr_pct = (value / current_price) * 100
                                    context_parts.append(
                                        f"ATR (14-day): ${value:.2f} ({atr_pct:.1f}% of the "
                                        f"{freshness.get('latest_bar_date')} price)"
                                    )
                                else:
                                    context_parts.append(
                                        f"ATR (14-day): ${value:.2f} (% of price withheld -- "
                                        "no current price to measure against)"
                                    )
                            elif ind_type.lower() == "rsi":
                                context_parts.append(f"RSI: {value:.1f}")
                            elif "bollinger" in ind_type.lower():
                                metadata = ind_data.get("metadata", {})
                                upper = metadata.get("upper", 0)
                                lower = metadata.get("lower", 0)
                                if upper and lower:
                                    bb_width = ((upper - lower) / value) * 100 if value > 0 else 0
                                    context_parts.append(f"Bollinger Band Width: {bb_width:.1f}%")

        # Market summary for overall context
        market_summary = market_data.get("market_summary", {})
        market_index = market_summary.get("market_index", {})
        if market_index:
            index_symbol = market_index.get("symbol", "SPY")
            # The context builder dates and re-quotes the benchmark and attaches
            # the record; derive one only for a hand-built market_data dict.
            index_freshness = market_index.get("freshness") or build_freshness(
                index_symbol,
                market_index.get("date"),
                market_index.get("current"),
                "db_close",
            )
            index_date = index_freshness.get("latest_bar_date") or "unknown date"
            context_parts.append("\n=== MARKET INDEX (SPY) ===")
            context_parts.append(price_line(index_freshness, label="Last Close"))
            context_parts.append(f"Change: {market_index.get('change_pct', 0):+.2f}%")
            context_parts.append(f"Session High ({index_date}): ${market_index.get('high', 0):.2f}")
            context_parts.append(f"Session Low ({index_date}): ${market_index.get('low', 0):.2f}")

        # Sector performance for diversification context
        sector_performance = market_data.get("sector_performance", {})
        if sector_performance:
            context_parts.append("\n=== SECTOR PERFORMANCE (for correlation context) ===")
            for etf, perf in sector_performance.items():
                if isinstance(perf, dict):
                    sector = perf.get("sector", etf)
                    daily_pct = perf.get("daily_change_pct", 0)
                    monthly_pct = perf.get("monthly_change_pct", 0)
                    context_parts.append(f"{etf} ({sector}): 1D={daily_pct:+.2f}%, 1M={monthly_pct:+.2f}%")

        # Economic indicators for macro risk context
        economic = market_data.get("economic_indicators", [])
        if economic:
            context_parts.append("\n=== ECONOMIC RISK FACTORS ===")
            if isinstance(economic, list):
                for ind in economic:
                    if isinstance(ind, dict):
                        name = ind.get("name", ind.get("series_id", "Unknown"))
                        value = ind.get("value", "N/A")
                        unit = ind.get("unit", "")
                        context_parts.append(f"{name}: {value}{unit}")
            elif isinstance(economic, dict):
                for indicator, value in economic.items():
                    context_parts.append(f"{indicator}: {value}")

    else:
        # Legacy format support
        context_parts.append("=== VOLATILITY DATA ===")
        if "vix_data" in market_data:
            vix = market_data["vix_data"]
            if "current_vix" in vix:
                context_parts.append(f"Current VIX: {vix['current_vix']}")
            if "vix_1m" in vix:
                context_parts.append(f"VIX 1-Month: {vix['vix_1m']}")
            if "vix_3m" in vix:
                context_parts.append(f"VIX 3-Month: {vix['vix_3m']}")
            if "vix_6m" in vix:
                context_parts.append(f"VIX 6-Month: {vix['vix_6m']}")
            if "term_structure" in vix:
                context_parts.append(f"Term Structure: {vix['term_structure']}")
            if "vix_percentile_52w" in vix:
                context_parts.append(f"VIX 52-Week Percentile: {vix['vix_percentile_52w']}%")

        if "price_data" in market_data:
            context_parts.append("\n=== PRICE AND VOLATILITY DATA ===")
            for symbol, data in market_data["price_data"].items():
                context_parts.append(f"\n--- {symbol} ---")
                if "current_price" in data:
                    # Legacy payload: date it off whatever the caller supplied
                    # so it still cannot be printed as an undated "current" price.
                    context_parts.append(
                        price_line(
                            build_freshness(
                                symbol,
                                data.get("as_of") or data.get("date"),
                                data["current_price"],
                                "db_close",
                            ),
                            label="Last Close",
                        )
                    )
                if "historical_vol_30d" in data:
                    context_parts.append(f"30-Day Historical Vol: {data['historical_vol_30d']:.1f}%")
                if "historical_vol_90d" in data:
                    context_parts.append(f"90-Day Historical Vol: {data['historical_vol_90d']:.1f}%")
                if "implied_vol" in data:
                    context_parts.append(f"Implied Vol: {data['implied_vol']:.1f}%")
                if "iv_percentile" in data:
                    context_parts.append(f"IV Percentile: {data['iv_percentile']:.0f}%")
                if "beta" in data:
                    context_parts.append(f"Beta: {data['beta']:.2f}")
                if "avg_true_range" in data:
                    context_parts.append(f"ATR (14-day): ${data['avg_true_range']:.2f}")
                if "max_drawdown_52w" in data:
                    context_parts.append(f"Max Drawdown (52W): {data['max_drawdown_52w']:.1f}%")
                if "support_level" in data:
                    context_parts.append(f"Key Support: ${data['support_level']:.2f}")
                if "resistance_level" in data:
                    context_parts.append(f"Key Resistance: ${data['resistance_level']:.2f}")

        if "portfolio" in market_data:
            context_parts.append("\n=== CURRENT PORTFOLIO ===")
            portfolio = market_data["portfolio"]
            if "total_value" in portfolio:
                context_parts.append(f"Total Value: ${portfolio['total_value']:,.2f}")
            if "positions" in portfolio:
                context_parts.append("\nPositions:")
                for pos in portfolio["positions"]:
                    symbol = pos.get("symbol", "N/A")
                    weight = pos.get("weight", 0)
                    value = pos.get("value", 0)
                    context_parts.append(f"  - {symbol}: {weight:.1f}% (${value:,.2f})")
            if "cash_pct" in portfolio:
                context_parts.append(f"Cash: {portfolio['cash_pct']:.1f}%")
            if "sector_exposure" in portfolio:
                context_parts.append("\nSector Exposure:")
                for sector, pct in portfolio["sector_exposure"].items():
                    context_parts.append(f"  - {sector}: {pct:.1f}%")

        if "correlations" in market_data:
            context_parts.append("\n=== CORRELATION MATRIX ===")
            correlations = market_data["correlations"]
            for pair, corr in correlations.items():
                context_parts.append(f"{pair}: {corr:.2f}")

        if "risk_events" in market_data:
            context_parts.append("\n=== UPCOMING RISK EVENTS ===")
            for event in market_data["risk_events"]:
                date = event.get("date", "TBD")
                name = event.get("event", "Unknown")
                impact = event.get("expected_impact", "unknown")
                context_parts.append(f"  - {date}: {name} (Impact: {impact})")

        if "market_context" in market_data:
            context_parts.append("\n=== MARKET CONTEXT ===")
            for item in market_data["market_context"]:
                context_parts.append(f"  - {item}")

    # Append volatility subset from rich TA if available
    rich_ta = market_data.get("rich_technical")
    if rich_ta:
        volatility_context = _format_volatility_context(rich_ta)
        if volatility_context:
            context_parts.append(volatility_context)

    # Prediction market data (optional)
    predictions = market_data.get("predictions")
    if predictions:
        from analysis.context_builder import format_prediction_context  # type: ignore[import-not-found]

        prediction_text = format_prediction_context(predictions)
        if prediction_text:
            context_parts.append("")
            context_parts.append(prediction_text)

    # Reddit sentiment data (optional)
    sentiment = market_data.get("sentiment")
    if sentiment:
        from analysis.context_builder import format_sentiment_context  # type: ignore[import-not-found]

        sentiment_text = format_sentiment_context(sentiment)
        if sentiment_text:
            context_parts.append("")
            context_parts.append(sentiment_text)

    # Peers go last and under their own heading -- everything above this line
    # is the target's own data.
    if target_symbol:
        peer_block = format_peer_comparison(market_data)
        if peer_block:
            context_parts.append("")
            context_parts.append(peer_block)

    return "\n".join(context_parts)


def parse_risk_response(response: str) -> dict[str, Any]:
    """
    Parse the risk analyst's response into a structured format.

    Args:
        response: Raw response string from the LLM, expected to contain JSON.

    Returns:
        Parsed dictionary with risk analysis results.
        Returns a default error structure if parsing fails.
    """
    # Try to extract JSON from the response
    try:
        # First, try direct JSON parsing
        return json.loads(response)
    except json.JSONDecodeError:
        pass

    # Try to find JSON block in markdown code fence
    json_pattern = r"```(?:json)?\s*(\{[\s\S]*?\})\s*```"
    match = re.search(json_pattern, response)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find JSON object anywhere in the response
    json_object_pattern = r"\{[\s\S]*\"analyst\"[\s\S]*\"risk\"[\s\S]*\}"
    match = re.search(json_object_pattern, response)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # If all parsing fails, return error structure
    logger.warning("Failed to parse risk analyst response as JSON")
    return {
        "analyst": "risk",
        "error": "Failed to parse response",
        "raw_response": response[:500],  # Truncate for safety
        "volatility_regime": {
            "current_vix": 0.0,
            "regime": "unknown",
            "term_structure": "unknown",
            "implication": "",
        },
        "risk_assessments": [],
        "portfolio_risks": [],
        "tail_risks": [],
        "key_observations": [],
        "confidence": 0.0,
    }


# =============================================================================
# TOLERANT NORMALISATION OF THE MODEL'S ACTUAL RISK OUTPUT
# =============================================================================
#
# RISK_ANALYST_PROMPT documents ``risk_assessments[]`` entries as flat scalars
# (``max_drawdown_pct``, ``risk_reward``, ``stop_loss``, ...).  The model does
# not comply, and it does not fail in one consistent way: in a single stored
# run ``downside_scenarios`` came back as a *list* of scenario objects for AMD
# and as a *dict* keyed by scenario name for DVN, while the stop level lived
# under ``stop_loss_recommendations`` for one symbol and ``stop_loss_levels``
# for another, sometimes as ``{"level": 42.0}`` and sometimes as the string
# ``"$14.00 (-8.1%, psychological level)"``.
#
# The consumer (``_format_risk_report``) read the documented names, missed all
# of them, and printed the ``0.0`` defaults as if they were measurements.  The
# normaliser below reads the shapes the model really emits and returns ``None``
# for anything genuinely absent, so a missing number can be rendered as missing
# instead of as zero.  Same discipline as ``format_factor_value`` in
# ``analysis/factor_model.py``.

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")

# Nested containers the model has actually used for each documented scalar.
_DOWNSIDE_KEYS = (
    "downside_scenarios",
    "max_drawdown_scenarios",
    "downside_targets",
    "downside_cases",
)
_STOP_KEYS = ("stop_loss_levels", "stop_loss_recommendations", "stop_levels")
_SIZE_KEYS = (
    "position_sizing",
    "position_size_recommendations",
    "position_size_suggestions",
)
_VAR_CONTAINER_KEYS = ("var_estimates", "var_analysis")
_VOL_TEXT_KEYS = (
    "realized_vol_20d",
    "20d_historical_vol",
    "historical_vol_20d",
    "atr_pct_of_price",
)
# Preferred tier when the model reports conservative/moderate/aggressive bands.
_MID_TIER_HINTS = ("moderate", "standard", "base", "medium")


def _first_number(value: Any) -> float | None:
    """Pull the first number out of a scalar the model may have written as prose.

    ``42.0`` -> 42.0, ``"-12.2%"`` -> -12.2, ``"$13.43 (1.5x ATR)"`` -> 13.43,
    ``"7.3% (~$1.11)"`` -> 7.3.  Returns ``None`` — never ``0.0`` — when there
    is no number to read, so absent stays distinguishable from zero.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = _NUMBER_RE.search(value.replace(",", ""))
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
    return None


def _dig(container: Any, *names: str) -> Any:
    """First present, non-empty value among ``names`` in a dict."""
    if not isinstance(container, dict):
        return None
    for name in names:
        if name in container and container[name] not in (None, "", [], {}):
            return container[name]
    return None


def _number_from(container: Any, *names: str) -> float | None:
    """``_first_number`` of the first present name, unwrapping one dict level."""
    value = _dig(container, *names)
    if isinstance(value, dict):
        value = _dig(value, "value", "value_pct", "pct", "level", "price", "target")
    return _first_number(value)


def _tiered_choice(container: Any) -> tuple[str | None, Any]:
    """Pick the middle tier from a conservative/moderate/aggressive band dict.

    Returns ``(tier_label, raw_value)``, or ``(None, None)`` when the container
    is not a tier dict.  The middle tier is the one a reader would quote; the
    label travels with it so the prompt says which band the number came from.
    """
    if not isinstance(container, dict) or not container:
        return None, None
    for key in container:
        if any(hint in str(key).lower() for hint in _MID_TIER_HINTS):
            return str(key), container[key]
    first_key = next(iter(container))
    return str(first_key), container[first_key]


def _text_of(value: Any) -> str | None:
    """Render a scenario/tier payload as one short human-readable string."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for name in ("rationale", "basis", "scenario", "assessment", "trigger",
                     "allocation", "recommendation", "risk", "implication", "note"):
            text = value.get(name)
            if isinstance(text, str) and text.strip():
                return text.strip()
        return None
    if isinstance(value, list):
        parts = [p for p in (_text_of(v) for v in value) if p]
        return "; ".join(parts) or None
    return None


def _normalize_scenarios(raw: Any) -> list[dict[str, Any]]:
    """Normalise both observed ``downside_scenarios`` shapes into one list.

    Accepts the list-of-objects shape (AMD) and the dict-keyed-by-name shape
    (DVN/NU/AVGO), plus the ``downside_targets`` level_1/level_2 variant.
    ``drawdown_pct`` comes back as a positive magnitude regardless of whether
    the model wrote ``17.6``, ``-12.2`` or ``"-12.2%"``.
    """
    items: list[tuple[str | None, Any]] = []
    if isinstance(raw, list):
        items = [(None, entry) for entry in raw]
    elif isinstance(raw, dict):
        items = [(str(name), entry) for name, entry in raw.items()]
    else:
        return []

    scenarios: list[dict[str, Any]] = []
    for name, entry in items:
        if isinstance(entry, dict):
            label = (
                _dig(entry, "scenario", "name", "case", "label")
                if not name
                else name
            )
            target = _number_from(entry, "target", "price", "level", "price_target")
            drawdown = _number_from(
                entry, "drawdown_pct", "pct", "drawdown", "loss_pct", "pct_loss"
            )
            probability = _number_from(entry, "probability", "odds", "likelihood")
            note = _text_of(entry)
        else:
            label = name
            target = _first_number(entry)
            drawdown = None
            probability = None
            note = entry if isinstance(entry, str) else None
        if probability is not None and probability > 1:
            probability = probability / 100.0
        scenarios.append(
            {
                "name": str(label) if label else None,
                "target": target,
                "drawdown_pct": abs(drawdown) if drawdown is not None else None,
                "probability": probability,
                "note": note if isinstance(note, str) else None,
            }
        )
    return scenarios


def normalize_risk_assessment(raw: dict[str, Any]) -> dict[str, Any]:
    """Map one model-emitted risk assessment onto the documented scalar names.

    Every numeric field is ``float | None``.  ``None`` means the model did not
    report it; it is never silently replaced by ``0.0``.  ``unmapped_fields``
    names the keys this normaliser did not consume, so the prompt can say what
    was dropped rather than pretending the report contained nothing else.
    """
    if not isinstance(raw, dict):
        return {}

    consumed: set[str] = set()

    def take(*names: str) -> Any:
        for name in names:
            if name in raw:
                consumed.add(name)
        return _dig(raw, *names)

    symbol = take("symbol", "ticker")
    current_price = _first_number(take("current_price", "price", "last_price"))

    scenarios = _normalize_scenarios(take(*_DOWNSIDE_KEYS))
    max_drawdown = _first_number(take("max_drawdown_pct"))
    if max_drawdown is None:
        modelled = [s["drawdown_pct"] for s in scenarios if s["drawdown_pct"] is not None]
        max_drawdown = max(modelled) if modelled else None
    else:
        max_drawdown = abs(max_drawdown)

    # Risk/reward: flat name first, then the nested analysis block.  AMD split
    # the ratio across risk_reward_ratio_moderate / _support; with no single
    # documented value the worst (smallest) ratio is the honest headline and
    # the full set travels in the note.
    rr = _first_number(take("risk_reward", "risk_reward_ratio"))
    rr_note = None
    rr_analysis = take("risk_reward_analysis", "risk_reward_assessment")
    if isinstance(rr_analysis, dict):
        rr_note = _text_of(rr_analysis)
        if rr is None:
            direct = _first_number(rr_analysis.get("risk_reward_ratio"))
            if direct is not None:
                rr = direct
            else:
                candidates = [
                    value
                    for key, value in rr_analysis.items()
                    if str(key).startswith("risk_reward_ratio")
                    and _first_number(value) is not None
                ]
                numbers = [_first_number(c) for c in candidates]
                numbers = [n for n in numbers if n is not None]
                if numbers:
                    rr = min(numbers)

    var_95 = _number_from(raw, "var_95_daily", "var_95_daily_pct")
    if "var_95_daily" in raw or "var_95_daily_pct" in raw:
        consumed.update({"var_95_daily", "var_95_daily_pct"})
    if var_95 is None:
        container = take(*_VAR_CONTAINER_KEYS)
        var_95 = _number_from(
            container, "var_95_daily_pct", "daily_var_95", "var_95_daily", "var_95"
        )

    stop_loss = _first_number(take("stop_loss"))
    stop_note = None
    if stop_loss is None:
        tier_label, tier_value = _tiered_choice(take(*_STOP_KEYS))
        if tier_value is not None:
            stop_loss = (
                _number_from(tier_value, "level", "price", "stop", "target")
                if isinstance(tier_value, dict)
                else _first_number(tier_value)
            )
            stop_note = tier_label

    position_size = take("position_size_suggestion", "position_size")
    position_size = position_size if isinstance(position_size, str) else None
    if position_size is None:
        tier_label, tier_value = _tiered_choice(take(*_SIZE_KEYS))
        text = (
            _dig(tier_value, "allocation", "size", "recommendation")
            if isinstance(tier_value, dict)
            else tier_value
        )
        if isinstance(text, str) and text.strip():
            position_size = f"{tier_label}: {text.strip()}" if tier_label else text.strip()

    invalidation_raw = take("invalidation_triggers", "invalidation_trigger", "invalidation")
    if isinstance(invalidation_raw, str):
        invalidation = [invalidation_raw]
    elif isinstance(invalidation_raw, list):
        invalidation = [str(item) for item in invalidation_raw if item]
    else:
        invalidation = []

    volatility = take(*_VOL_TEXT_KEYS)
    volatility = str(volatility) if volatility not in (None, "") else None

    unmapped = sorted(
        key
        for key in raw
        if key not in consumed and not str(key).startswith("_")
    )

    return {
        "symbol": str(symbol) if symbol else None,
        "current_price": current_price,
        "max_drawdown_pct": max_drawdown,
        "risk_reward": rr,
        "risk_reward_note": rr_note,
        "var_95_daily_pct": var_95,
        "stop_loss": stop_loss,
        "stop_loss_tier": stop_note,
        "position_size": position_size,
        "volatility": volatility,
        "downside_scenarios": scenarios,
        "invalidation": invalidation,
        "unmapped_fields": unmapped,
    }


def normalize_risk_report(report: dict[str, Any]) -> dict[str, Any]:
    """Normalise a whole parsed risk report for downstream rendering.

    ``parse_risk_response`` is a bare ``json.loads`` passthrough, so this is the
    first point at which the risk analyst's output has a predictable shape.
    Report-level lists are passed through; only ``risk_assessments`` entries are
    rewritten, by :func:`normalize_risk_assessment`.
    """
    if not isinstance(report, dict):
        return {}

    assessments = report.get("risk_assessments")
    normalized = [
        normalize_risk_assessment(entry)
        for entry in (assessments or [])
        if isinstance(entry, dict)
    ]

    vol_regime = report.get("volatility_regime")
    volatility_regime: dict[str, Any] | None = None
    if isinstance(vol_regime, dict) and vol_regime:
        volatility_regime = {
            "current_vix": _first_number(
                _dig(vol_regime, "current_vix", "vix", "vix_level")
            ),
            "regime": _dig(vol_regime, "regime", "name", "state"),
            "term_structure": _dig(vol_regime, "term_structure", "structure"),
            "implication": _dig(vol_regime, "implication", "interpretation", "note"),
        }

    tail_risks: list[dict[str, Any]] = []
    for entry in report.get("tail_risks") or []:
        if isinstance(entry, dict):
            probability = _number_from(entry, "probability", "odds")
            if probability is not None and probability > 1:
                probability = probability / 100.0
            tail_risks.append(
                {
                    "event": _dig(entry, "event", "risk", "scenario", "name"),
                    "probability": probability,
                    "impact": _dig(entry, "impact", "severity"),
                }
            )
        elif isinstance(entry, str) and entry.strip():
            tail_risks.append({"event": entry.strip(), "probability": None, "impact": None})

    return {
        "analyst": "risk",
        "volatility_regime": volatility_regime,
        "risk_assessments": normalized,
        "portfolio_risks": [str(r) for r in (report.get("portfolio_risks") or []) if r],
        "tail_risks": tail_risks,
        "key_observations": [
            str(o) for o in (report.get("key_observations") or []) if o
        ],
        "confidence": _first_number(report.get("confidence")),
    }


def parse_to_result(response: str) -> RiskAnalysisResult:
    """
    Parse response into a RiskAnalysisResult dataclass.

    Args:
        response: Raw response string from the LLM.

    Returns:
        RiskAnalysisResult instance with parsed data.
    """
    data = parse_risk_response(response)

    # Parse volatility regime
    vol_data = data.get("volatility_regime", {})
    volatility_regime = VolatilityRegime(
        current_vix=float(vol_data.get("current_vix", 0.0)),
        regime=vol_data.get("regime", "unknown"),
        term_structure=vol_data.get("term_structure", "unknown"),
        implication=vol_data.get("implication", ""),
    )

    # Parse risk assessments
    risk_assessments = [
        RiskAssessment(
            symbol=ra.get("symbol", ""),
            current_price=float(ra.get("current_price", 0.0)),
            downside_target=float(ra.get("downside_target", 0.0)),
            max_drawdown_pct=float(ra.get("max_drawdown_pct", 0.0)),
            var_95_daily=float(ra.get("var_95_daily", 0.0)),
            risk_reward=float(ra.get("risk_reward", 0.0)),
            position_size_suggestion=ra.get("position_size_suggestion", ""),
            stop_loss=float(ra.get("stop_loss", 0.0)),
            invalidation_trigger=ra.get("invalidation_trigger", ""),
        )
        for ra in data.get("risk_assessments", [])
    ]

    # Parse tail risks
    tail_risks = [
        TailRisk(
            event=tr.get("event", ""),
            probability=float(tr.get("probability", 0.0)),
            impact=tr.get("impact", "unknown"),
        )
        for tr in data.get("tail_risks", [])
    ]

    return RiskAnalysisResult(
        analyst="risk",
        volatility_regime=volatility_regime,
        risk_assessments=risk_assessments,
        portfolio_risks=data.get("portfolio_risks", []),
        tail_risks=tail_risks,
        key_observations=data.get("key_observations", []),
        confidence=float(data.get("confidence", 0.0)),
    )
