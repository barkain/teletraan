"""Risk Analyst agent for volatility analysis, downside risk assessment, and position sizing."""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

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


def format_risk_context(market_data: dict) -> str:
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
            Or legacy format with vix_data, price_data, portfolio, correlations.

    Returns:
        Formatted string context for the risk analyst prompt.
    """
    context_parts = []

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

            # Current price from most recent data (prices sorted descending)
            latest = prices[0]
            current_price = float(latest.get("close", 0))
            context_parts.append(f"Current Price: ${current_price:.2f}")
            context_parts.append(f"Today's High: ${latest.get('high', 0):.2f}")
            context_parts.append(f"Today's Low: ${latest.get('low', 0):.2f}")
            context_parts.append(f"Volume: {latest.get('volume', 0):,}")

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
                    context_parts.append(f"20-Period Support: ${support:.2f}")
                    context_parts.append(f"20-Period Resistance: ${resistance:.2f}")

            # Technical indicators for this symbol (e.g., ATR)
            indicators = technical_indicators.get(symbol, {})
            if indicators:
                for ind_type, ind_data in indicators.items():
                    if isinstance(ind_data, dict):
                        value = ind_data.get("value")
                        if value is not None:
                            if ind_type.lower() == "atr":
                                if current_price > 0:
                                    atr_pct = (value / current_price) * 100
                                    context_parts.append(f"ATR (14-day): ${value:.2f} ({atr_pct:.1f}% of price)")
                                else:
                                    context_parts.append(f"ATR (14-day): ${value:.2f}")
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
            context_parts.append("\n=== MARKET INDEX (SPY) ===")
            context_parts.append(f"Current: ${market_index.get('current', 0):.2f}")
            context_parts.append(f"Change: {market_index.get('change_pct', 0):+.2f}%")
            context_parts.append(f"High: ${market_index.get('high', 0):.2f}")
            context_parts.append(f"Low: ${market_index.get('low', 0):.2f}")

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
                    context_parts.append(f"Current Price: ${data['current_price']:.2f}")
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
