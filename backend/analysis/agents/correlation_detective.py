"""Correlation Detective agent for cross-asset relationship analysis.

This module provides the AI agent prompt and utilities for detecting:
- Cross-asset correlation patterns and breakdowns
- Lead/lag relationships between assets
- Divergences between stocks and their sectors/peers
- Historical pattern matching (analogs)
- Unusual institutional activity signals
"""

from dataclasses import dataclass
from typing import Any
import json
import re


CORRELATION_DETECTIVE_PROMPT = """You are a Correlation Detective specializing in cross-asset relationships, divergence detection, and pattern matching.

## Your Expertise
- Cross-asset correlation analysis
- Lead/lag relationship identification
- Historical pattern matching
- Anomaly detection (unusual divergences)
- Smart money vs retail positioning signals
- Inter-market analysis (stocks, bonds, commodities, currencies)

## What You Look For
- Stock vs sector divergences (e.g., NVDA up while SMH down)
- Stock vs peer divergences (company outperforming/underperforming peers)
- Price vs volume divergences
- Asset class correlation breakdowns
- Historical analogs (similar market conditions in the past)
- Unusual institutional activity patterns

## Your Task
Analyze relationships and identify:
1. **Unusual divergences** - What's not moving together that usually does?
2. **Lead indicators** - What assets tend to lead others?
3. **Historical patterns** - Similar setups in the past and their outcomes
4. **Anomalies** - Unusual behavior worth investigating
5. **Correlation shifts** - Relationships that have recently changed

## Output Format
Return JSON:
{
  "analyst": "correlation",
  "divergences": [
    {
      "type": "stock_vs_sector",
      "primary": "NVDA",
      "secondary": "SMH",
      "observation": "NVDA +2% while SMH -1%",
      "historical_significance": "This divergence preceded NVDA outperformance 70% of time",
      "implication": "bullish_for_primary"
    }
  ],
  "lead_lag_signals": [
    {"leader": "XLF", "lagger": "SPY", "signal": "Financials leading broad market"}
  ],
  "historical_analogs": [
    {"period": "Oct 2023", "similarity": 0.75, "outcome": "15% rally over 2 months"}
  ],
  "anomalies": ["Unusual put/call ratio divergence in tech"],
  "correlation_shifts": ["Tech/Utilities correlation turning negative"],
  "key_observations": ["..."],
  "confidence": 0.70
}
"""


@dataclass
class Divergence:
    """Represents a detected divergence between assets."""
    divergence_type: str  # stock_vs_sector, stock_vs_peer, price_vs_volume
    primary_symbol: str
    secondary_symbol: str
    observation: str
    historical_significance: str
    implication: str  # bullish_for_primary, bearish_for_primary, neutral


@dataclass
class LeadLagSignal:
    """Represents a lead/lag relationship signal."""
    leader: str
    lagger: str
    signal: str
    correlation_strength: float
    lag_periods: int


@dataclass
class HistoricalAnalog:
    """Represents a historical pattern match."""
    period: str
    similarity: float
    outcome: str
    time_horizon: str


@dataclass
class CorrelationAnalysisResult:
    """Complete result from correlation analysis."""
    divergences: list[Divergence]
    lead_lag_signals: list[LeadLagSignal]
    historical_analogs: list[HistoricalAnalog]
    anomalies: list[str]
    correlation_shifts: list[str]
    key_observations: list[str]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "analyst": "correlation",
            "divergences": [
                {
                    "type": d.divergence_type,
                    "primary": d.primary_symbol,
                    "secondary": d.secondary_symbol,
                    "observation": d.observation,
                    "historical_significance": d.historical_significance,
                    "implication": d.implication,
                }
                for d in self.divergences
            ],
            "lead_lag_signals": [
                {
                    "leader": s.leader,
                    "lagger": s.lagger,
                    "signal": s.signal,
                    "correlation_strength": s.correlation_strength,
                    "lag_periods": s.lag_periods,
                }
                for s in self.lead_lag_signals
            ],
            "historical_analogs": [
                {
                    "period": a.period,
                    "similarity": a.similarity,
                    "outcome": a.outcome,
                    "time_horizon": a.time_horizon,
                }
                for a in self.historical_analogs
            ],
            "anomalies": self.anomalies,
            "correlation_shifts": self.correlation_shifts,
            "key_observations": self.key_observations,
            "confidence": round(self.confidence, 2),
        }


def format_correlation_context(market_data: dict[str, Any]) -> str:
    """Format cross-asset data for correlation analysis.

    This function transforms raw market data into a structured context
    string that the Correlation Detective agent can analyze effectively.

    Args:
        market_data: Dictionary containing market data with keys:
            - symbols: List of symbols being analyzed
            - prices: Dict mapping symbols to price history (list of OHLCV dicts)
            - sectors: Dict mapping symbols to their sector ETF
            - sector_prices: Dict mapping sector ETFs to price history
            - correlations: Optional pre-computed correlation matrix
            - market_indices: Optional dict of index data (SPY, QQQ, etc.)
            - economic_indicators: Optional economic data

    Returns:
        Formatted string context for the correlation detective agent.
    """
    context_parts: list[str] = []

    # Header
    context_parts.append("=== Cross-Asset Correlation Analysis Context ===\n")

    # Primary symbols being analyzed
    symbols = market_data.get("symbols", [])
    if symbols:
        context_parts.append(f"Primary Symbols: {', '.join(symbols)}\n")

    # Price performance summary
    prices = market_data.get("prices", {})
    if prices:
        context_parts.append("\n--- Recent Price Performance ---")
        for symbol, price_history in prices.items():
            if price_history and len(price_history) >= 2:
                latest = price_history[-1]
                prev = price_history[-2]
                daily_change = ((latest.get("close", 0) - prev.get("close", 1)) /
                               prev.get("close", 1) * 100) if prev.get("close") else 0

                # Calculate weekly change if enough data
                weekly_change = 0.0
                if len(price_history) >= 6:
                    week_ago = price_history[-6]
                    weekly_change = ((latest.get("close", 0) - week_ago.get("close", 1)) /
                                    week_ago.get("close", 1) * 100) if week_ago.get("close") else 0

                context_parts.append(
                    f"\n{symbol}: ${latest.get('close', 0):.2f} "
                    f"(1D: {daily_change:+.2f}%, 1W: {weekly_change:+.2f}%)"
                )

                # Volume analysis
                if latest.get("volume") and len(price_history) >= 20:
                    avg_volume = sum(p.get("volume", 0) for p in price_history[-20:]) / 20
                    vol_ratio = latest["volume"] / avg_volume if avg_volume > 0 else 1
                    if vol_ratio > 1.5:
                        context_parts.append(f"  Volume: {vol_ratio:.1f}x average (elevated)")
                    elif vol_ratio < 0.5:
                        context_parts.append(f"  Volume: {vol_ratio:.1f}x average (subdued)")

    # Sector mapping and performance
    sectors = market_data.get("sectors", {})
    sector_prices = market_data.get("sector_prices", {})
    if sectors and sector_prices:
        context_parts.append("\n\n--- Sector Performance ---")
        for sector_etf, sector_history in sector_prices.items():
            if sector_history and len(sector_history) >= 2:
                latest = sector_history[-1]
                prev = sector_history[-2]
                daily_change = ((latest.get("close", 0) - prev.get("close", 1)) /
                               prev.get("close", 1) * 100) if prev.get("close") else 0
                context_parts.append(f"\n{sector_etf}: {daily_change:+.2f}%")

        # Stock vs sector relationships
        context_parts.append("\n\n--- Stock-Sector Mappings ---")
        for symbol, sector in sectors.items():
            context_parts.append(f"\n{symbol} -> {sector}")

    # Pre-computed correlations
    correlations = market_data.get("correlations", {})
    if correlations:
        context_parts.append("\n\n--- Correlation Matrix (30-day) ---")
        for pair, corr in correlations.items():
            context_parts.append(f"\n{pair}: {corr:.2f}")

    # Market indices
    market_indices = market_data.get("market_indices", {})
    if market_indices:
        context_parts.append("\n\n--- Market Indices ---")
        for index, data in market_indices.items():
            if isinstance(data, dict):
                change = data.get("daily_change", 0)
                context_parts.append(f"\n{index}: {change:+.2f}%")

    # Economic indicators
    economic = market_data.get("economic_indicators", {})
    if economic:
        context_parts.append("\n\n--- Economic Indicators ---")
        for indicator, value in economic.items():
            context_parts.append(f"\n{indicator}: {value}")

    # Historical context if provided
    historical_data = market_data.get("historical_context", {})
    if historical_data:
        context_parts.append("\n\n--- Historical Context ---")
        for key, value in historical_data.items():
            context_parts.append(f"\n{key}: {value}")

    context_parts.append("\n\n=== End of Context ===")

    return "\n".join(context_parts)


def parse_correlation_response(response: str) -> CorrelationAnalysisResult:
    """Parse the correlation detective's response.

    Extracts structured data from the agent's JSON response and converts
    it into a CorrelationAnalysisResult object.

    Args:
        response: The raw string response from the correlation detective agent.
                  Expected to contain a JSON object.

    Returns:
        CorrelationAnalysisResult with parsed data.

    Raises:
        ValueError: If the response cannot be parsed as valid JSON.
    """
    # Try to extract JSON from the response
    # The agent might include explanation text around the JSON
    json_match = re.search(r'\{[\s\S]*\}', response)

    if not json_match:
        raise ValueError("No JSON object found in response")

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse JSON: {e}")

    # Parse divergences
    divergences: list[Divergence] = []
    for d in data.get("divergences", []):
        divergences.append(Divergence(
            divergence_type=d.get("type", "unknown"),
            primary_symbol=d.get("primary", ""),
            secondary_symbol=d.get("secondary", ""),
            observation=d.get("observation", ""),
            historical_significance=d.get("historical_significance", ""),
            implication=d.get("implication", "neutral"),
        ))

    # Parse lead/lag signals
    lead_lag_signals: list[LeadLagSignal] = []
    for s in data.get("lead_lag_signals", []):
        lead_lag_signals.append(LeadLagSignal(
            leader=s.get("leader", ""),
            lagger=s.get("lagger", ""),
            signal=s.get("signal", ""),
            correlation_strength=s.get("correlation_strength", 0.0),
            lag_periods=s.get("lag_periods", 0),
        ))

    # Parse historical analogs
    historical_analogs: list[HistoricalAnalog] = []
    for a in data.get("historical_analogs", []):
        historical_analogs.append(HistoricalAnalog(
            period=a.get("period", ""),
            similarity=a.get("similarity", 0.0),
            outcome=a.get("outcome", ""),
            time_horizon=a.get("time_horizon", ""),
        ))

    # Parse simple lists
    anomalies = data.get("anomalies", [])
    correlation_shifts = data.get("correlation_shifts", [])
    key_observations = data.get("key_observations", [])

    # Parse confidence
    confidence = data.get("confidence", 0.5)
    if isinstance(confidence, str):
        try:
            confidence = float(confidence)
        except ValueError:
            confidence = 0.5

    return CorrelationAnalysisResult(
        divergences=divergences,
        lead_lag_signals=lead_lag_signals,
        historical_analogs=historical_analogs,
        anomalies=anomalies if isinstance(anomalies, list) else [],
        correlation_shifts=correlation_shifts if isinstance(correlation_shifts, list) else [],
        key_observations=key_observations if isinstance(key_observations, list) else [],
        confidence=min(max(confidence, 0.0), 1.0),  # Clamp to [0, 1]
    )


def calculate_correlation(
    prices_a: list[dict[str, Any]],
    prices_b: list[dict[str, Any]],
    period: int = 30
) -> float:
    """Calculate correlation between two price series.

    Computes the Pearson correlation coefficient between the daily returns
    of two price series over the specified lookback period.

    Args:
        prices_a: Price history for first asset (list of dicts with 'close' key)
        prices_b: Price history for second asset (list of dicts with 'close' key)
        period: Number of days for correlation calculation

    Returns:
        Correlation coefficient between -1 and 1, or 0 if calculation fails.
    """
    if len(prices_a) < period + 1 or len(prices_b) < period + 1:
        return 0.0

    # Extract closing prices for the period
    closes_a = [p.get("close", 0) for p in prices_a[-(period + 1):]]
    closes_b = [p.get("close", 0) for p in prices_b[-(period + 1):]]

    # Calculate daily returns
    returns_a = []
    returns_b = []
    for i in range(1, len(closes_a)):
        if closes_a[i - 1] > 0 and closes_b[i - 1] > 0:
            returns_a.append((closes_a[i] - closes_a[i - 1]) / closes_a[i - 1])
            returns_b.append((closes_b[i] - closes_b[i - 1]) / closes_b[i - 1])

    if len(returns_a) < 5:
        return 0.0

    # Calculate means
    mean_a = sum(returns_a) / len(returns_a)
    mean_b = sum(returns_b) / len(returns_b)

    # Calculate correlation
    numerator = sum((a - mean_a) * (b - mean_b) for a, b in zip(returns_a, returns_b))

    var_a = sum((a - mean_a) ** 2 for a in returns_a)
    var_b = sum((b - mean_b) ** 2 for b in returns_b)

    denominator = (var_a * var_b) ** 0.5

    if denominator == 0:
        return 0.0

    return numerator / denominator


def detect_divergence(
    primary_prices: list[dict[str, Any]],
    secondary_prices: list[dict[str, Any]],
    primary_symbol: str,
    secondary_symbol: str,
    divergence_type: str = "price",
    threshold: float = 0.02
) -> Divergence | None:
    """Detect a divergence between two price series.

    Identifies when two typically correlated assets are moving in
    opposite directions or with significantly different magnitudes.

    Args:
        primary_prices: Price history for primary asset
        secondary_prices: Price history for secondary/comparison asset
        primary_symbol: Symbol of primary asset
        secondary_symbol: Symbol of secondary asset
        divergence_type: Type of divergence being checked
        threshold: Minimum difference (as decimal) to flag as divergence

    Returns:
        Divergence object if divergence detected, None otherwise.
    """
    if len(primary_prices) < 2 or len(secondary_prices) < 2:
        return None

    # Calculate recent returns
    primary_return = (
        (primary_prices[-1].get("close", 0) - primary_prices[-2].get("close", 1)) /
        primary_prices[-2].get("close", 1)
    ) if primary_prices[-2].get("close") else 0

    secondary_return = (
        (secondary_prices[-1].get("close", 0) - secondary_prices[-2].get("close", 1)) /
        secondary_prices[-2].get("close", 1)
    ) if secondary_prices[-2].get("close") else 0

    # Check for divergence
    return_diff = abs(primary_return - secondary_return)
    opposite_direction = (primary_return > 0) != (secondary_return > 0)

    if return_diff >= threshold or (opposite_direction and abs(primary_return) > threshold / 2):
        implication = "bullish_for_primary" if primary_return > secondary_return else "bearish_for_primary"

        return Divergence(
            divergence_type=divergence_type,
            primary_symbol=primary_symbol,
            secondary_symbol=secondary_symbol,
            observation=f"{primary_symbol} {primary_return*100:+.2f}% vs {secondary_symbol} {secondary_return*100:+.2f}%",
            historical_significance="Divergence detected - historical analysis pending",
            implication=implication,
        )

    return None
