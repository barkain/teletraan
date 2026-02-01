"""Sector Strategist agent for sector rotation and relative strength analysis.

This module provides the LLM prompt and helper functions for the Sector Strategist
agent, which specializes in:
- Business cycle sector rotation analysis
- Relative strength assessment (sector vs S&P 500, sector vs sector)
- Money flow detection between sectors
- ETF flow analysis and institutional positioning
"""

import json
import re


SECTOR_STRATEGIST_PROMPT = """You are a Sector Strategist specializing in sector rotation analysis and relative strength assessment.

## Your Expertise
- Business cycle sector rotation (early/mid/late cycle positioning)
- Relative strength analysis (sector vs S&P 500, sector vs sector)
- Money flow between sectors (institutional rotation patterns)
- Sector correlations and divergences
- ETF flow analysis and positioning

## Market Cycle Phases
- Early Expansion: Favor Consumer Discretionary, Financials, Industrials, Tech
- Mid Expansion: Favor Tech, Industrials, Materials
- Late Expansion: Favor Energy, Materials, Staples
- Recession: Favor Utilities, Healthcare, Staples (defensives)

## Your Task
Analyze sector data and identify:
1. **Current market phase** - Where are we in the cycle?
2. **Sector rankings** - Relative strength rankings
3. **Rotation signals** - Money moving between sectors
4. **Overweight/underweight recommendations** - Which sectors to favor
5. **Divergences** - Sectors behaving unexpectedly for the cycle

## Output Format
Return JSON:
{
  "analyst": "sector",
  "market_phase": "early_expansion",
  "phase_confidence": 0.7,
  "sector_rankings": [
    {"sector": "Technology", "relative_strength": 1.15, "trend": "strengthening"},
    {"sector": "Financials", "relative_strength": 1.08, "trend": "stable"}
  ],
  "recommendations": [
    {"sector": "Technology", "action": "OVERWEIGHT", "rationale": "..."},
    {"sector": "Utilities", "action": "UNDERWEIGHT", "rationale": "..."}
  ],
  "rotation_signals": ["Money flowing from defensives to cyclicals"],
  "key_observations": ["..."],
  "confidence": 0.75
}
"""


def format_sector_context(market_data: dict) -> str:
    """Format sector data for strategist consumption.

    Takes raw market data and formats it into a structured context string
    that the sector strategist agent can analyze effectively.

    Args:
        market_data: Dictionary containing sector performance data from context builder:
            - sector_performance: Dict mapping sector ETF symbols to performance metrics
            - price_history: Dict mapping symbols to OHLCV data
            - stocks: List of stock metadata
            - market_summary: Overall market status
            - economic_indicators: List of economic indicator dicts
            Or legacy format with sector_metrics, rotation_analysis, etc.

    Returns:
        Formatted string context for the LLM agent.
    """
    if not market_data:
        return "No sector data available for analysis."

    context_parts = []

    # Check for new context builder format (sector_performance from ETFs)
    sector_performance = market_data.get("sector_performance", {})

    if sector_performance and isinstance(sector_performance, dict):
        context_parts.append("## Sector ETF Performance")
        context_parts.append("")

        # Sort by monthly change descending to show relative strength
        sorted_sectors = sorted(
            sector_performance.items(),
            key=lambda x: x[1].get("monthly_change_pct", 0) if isinstance(x[1], dict) else 0,
            reverse=True
        )

        for symbol, metrics in sorted_sectors:
            if not isinstance(metrics, dict):
                continue
            name = metrics.get("name", symbol)
            sector = metrics.get("sector", "")
            current = metrics.get("current_price", 0)
            daily_pct = metrics.get("daily_change_pct", 0)
            weekly_pct = metrics.get("weekly_change_pct", 0)
            monthly_pct = metrics.get("monthly_change_pct", 0)
            volume = metrics.get("volume", 0)

            context_parts.append(
                f"- **{name}** ({symbol}) - {sector}"
            )
            context_parts.append(
                f"  Price: ${current:.2f}, Daily: {daily_pct:+.2f}%, "
                f"Weekly: {weekly_pct:+.2f}%, Monthly: {monthly_pct:+.2f}%"
            )
            context_parts.append(f"  Volume: {volume:,}")

        context_parts.append("")

        # Calculate relative strength rankings
        context_parts.append("## Relative Strength Rankings (by Monthly Return)")
        context_parts.append("")
        for rank, (symbol, metrics) in enumerate(sorted_sectors, 1):
            if not isinstance(metrics, dict):
                continue
            sector = metrics.get("sector", symbol)
            monthly_pct = metrics.get("monthly_change_pct", 0)
            context_parts.append(f"{rank}. {sector} ({symbol}): {monthly_pct:+.2f}%")
        context_parts.append("")

        # Identify leaders and laggards
        if len(sorted_sectors) >= 4:
            leaders = sorted_sectors[:2]
            laggards = sorted_sectors[-2:]

            context_parts.append("## Rotation Analysis")
            context_parts.append("")
            context_parts.append("Leading Sectors: " + ", ".join(
                f"{m.get('sector', s)} ({m.get('monthly_change_pct', 0):+.2f}%)"
                for s, m in leaders if isinstance(m, dict)
            ))
            context_parts.append("Lagging Sectors: " + ", ".join(
                f"{m.get('sector', s)} ({m.get('monthly_change_pct', 0):+.2f}%)"
                for s, m in laggards if isinstance(m, dict)
            ))
            context_parts.append("")

    # Add individual stock data grouped by sector
    stocks = market_data.get("stocks", [])
    price_history = market_data.get("price_history", {})

    if stocks and price_history:
        # Group stocks by sector
        by_sector: dict[str, list] = {}
        for stock in stocks:
            sector = stock.get("sector") or "Other"  # Handle None values
            if sector not in by_sector:
                by_sector[sector] = []
            by_sector[sector].append(stock)

        context_parts.append("## Individual Stock Performance by Sector")
        context_parts.append("")

        for sector, sector_stocks in sorted(by_sector.items()):
            context_parts.append(f"### {sector}")
            for stock in sector_stocks:
                symbol = stock.get("symbol", "")
                name = stock.get("name", symbol)
                prices = price_history.get(symbol, [])

                if prices and len(prices) >= 2:
                    latest = prices[0]  # Sorted descending
                    prev = prices[1]
                    current = latest.get("close", 0)
                    daily_change = ((current - prev.get("close", current)) / prev.get("close", 1)) * 100 if prev.get("close") else 0
                    volume = latest.get("volume", 0)

                    context_parts.append(
                        f"- {symbol} ({name}): ${current:.2f} ({daily_change:+.2f}%), Vol: {volume:,}"
                    )
            context_parts.append("")

    # Market summary / benchmark
    market_summary = market_data.get("market_summary", {})
    market_index = market_summary.get("market_index", {})
    if market_index:
        context_parts.append("## Benchmark (SPY)")
        context_parts.append("")
        context_parts.append(f"Current: ${market_index.get('current', 0):.2f}")
        context_parts.append(f"Daily Change: {market_index.get('change_pct', 0):+.2f}%")
        context_parts.append(f"Volume: {market_index.get('volume', 0):,}")
        context_parts.append("")

    # Handle legacy format fields
    sector_metrics = market_data.get("sector_metrics", {})
    if sector_metrics and not sector_performance:
        context_parts.append("## Sector Performance Metrics")
        context_parts.append("")

        sorted_sectors = sorted(
            sector_metrics.items(),
            key=lambda x: x[1].get("relative_strength", 0),
            reverse=True
        )

        for symbol, metrics in sorted_sectors:
            name = metrics.get("name", symbol)
            rs = metrics.get("relative_strength", 1.0)
            monthly_ret = metrics.get("monthly_return", 0)
            weekly_ret = metrics.get("weekly_return", 0)
            momentum = metrics.get("momentum_score", 0)
            vol_trend = metrics.get("volume_trend", "stable")

            context_parts.append(
                f"- **{name}** ({symbol}): "
                f"RS={rs:.3f}, Monthly={monthly_ret:+.2f}%, "
                f"Weekly={weekly_ret:+.2f}%, Momentum={momentum:.2f}, "
                f"Volume={vol_trend}"
            )
        context_parts.append("")

    # Rotation analysis (legacy)
    rotation = market_data.get("rotation_analysis", {})
    if rotation:
        context_parts.append("## Rotation Analysis")
        context_parts.append("")

        rotation_type = rotation.get("rotation_type", "unknown")
        context_parts.append(f"Rotation Type: {rotation_type}")

        leading = rotation.get("leading_sectors", [])
        if leading:
            leaders = ", ".join(
                f"{s.get('name', s.get('symbol', 'Unknown'))} ({s.get('momentum', 0):.2f})"
                for s in leading
            )
            context_parts.append(f"Leading Sectors: {leaders}")

        lagging = rotation.get("lagging_sectors", [])
        if lagging:
            laggers = ", ".join(
                f"{s.get('name', s.get('symbol', 'Unknown'))} ({s.get('momentum', 0):.2f})"
                for s in lagging
            )
            context_parts.append(f"Lagging Sectors: {laggers}")
        context_parts.append("")

    # Market phase (legacy)
    market_phase = market_data.get("market_phase", "unknown")
    if market_phase != "unknown":
        context_parts.append("## Current Market Phase")
        context_parts.append("")
        context_parts.append(f"Phase: {market_phase.replace('_', ' ').title()}")
        phase_desc = market_data.get("phase_description", "")
        if phase_desc:
            context_parts.append(f"Description: {phase_desc}")
        expected_leaders = market_data.get("expected_leaders", [])
        if expected_leaders:
            context_parts.append(f"Expected Leaders: {', '.join(expected_leaders)}")
        context_parts.append("")

    # Economic indicators (handle both list and dict formats)
    economic = market_data.get("economic_indicators", [])
    if economic:
        context_parts.append("## Economic Context")
        context_parts.append("")
        if isinstance(economic, list):
            # New format: list of indicator dicts
            for ind in economic:
                if isinstance(ind, dict):
                    name = ind.get("name", ind.get("series_id", "Unknown"))
                    value = ind.get("value", "N/A")
                    unit = ind.get("unit", "")
                    context_parts.append(f"- {name}: {value}{unit}")
        elif isinstance(economic, dict):
            # Legacy format: flat dict
            for indicator, value in economic.items():
                formatted_name = indicator.replace("_", " ").title()
                if isinstance(value, (int, float)):
                    context_parts.append(f"- {formatted_name}: {value:.2f}")
                else:
                    context_parts.append(f"- {formatted_name}: {value}")
        context_parts.append("")

    if not context_parts or context_parts == [""]:
        return "No sector data available for analysis."

    return "\n".join(context_parts)


def parse_sector_response(response: str) -> dict:
    """Parse the sector strategist's response.

    Extracts structured JSON data from the LLM response, handling cases where
    the JSON may be embedded in markdown code blocks or mixed with text.

    Args:
        response: Raw LLM response string that should contain JSON output.

    Returns:
        Parsed dictionary containing the sector analysis results with keys:
            - analyst: str ("sector")
            - market_phase: str
            - phase_confidence: float
            - sector_rankings: list[dict]
            - recommendations: list[dict]
            - rotation_signals: list[str]
            - key_observations: list[str]
            - confidence: float

        Returns a default error response if parsing fails.
    """
    if not response:
        return _default_error_response("Empty response received")

    # Try to find JSON in the response
    json_str = _extract_json(response)

    if not json_str:
        return _default_error_response("No JSON found in response")

    try:
        result = json.loads(json_str)

        # Validate and normalize the response
        return _validate_and_normalize(result)

    except json.JSONDecodeError as e:
        return _default_error_response(f"JSON parse error: {str(e)}")


def _extract_json(response: str) -> str | None:
    """Extract JSON from a response that may contain markdown or text.

    Args:
        response: Raw response string.

    Returns:
        Extracted JSON string or None if not found.
    """
    # Try to find JSON in code blocks first
    code_block_pattern = r"```(?:json)?\s*(\{[\s\S]*?\})\s*```"
    match = re.search(code_block_pattern, response)
    if match:
        return match.group(1)

    # Try to find a JSON object directly
    json_pattern = r"\{[\s\S]*\}"
    match = re.search(json_pattern, response)
    if match:
        # Validate it's actually JSON
        candidate = match.group(0)
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    return None


def _validate_and_normalize(result: dict) -> dict:
    """Validate and normalize the parsed result.

    Args:
        result: Raw parsed JSON dictionary.

    Returns:
        Normalized dictionary with all expected fields.
    """
    # Ensure all expected fields exist with defaults
    normalized = {
        "analyst": result.get("analyst", "sector"),
        "market_phase": result.get("market_phase", "unknown"),
        "phase_confidence": float(result.get("phase_confidence", 0.5)),
        "sector_rankings": result.get("sector_rankings", []),
        "recommendations": result.get("recommendations", []),
        "rotation_signals": result.get("rotation_signals", []),
        "key_observations": result.get("key_observations", []),
        "confidence": float(result.get("confidence", 0.5)),
    }

    # Validate sector_rankings format
    valid_rankings = []
    for ranking in normalized["sector_rankings"]:
        if isinstance(ranking, dict) and "sector" in ranking:
            valid_rankings.append({
                "sector": ranking.get("sector", "Unknown"),
                "relative_strength": float(ranking.get("relative_strength", 1.0)),
                "trend": ranking.get("trend", "stable"),
            })
    normalized["sector_rankings"] = valid_rankings

    # Validate recommendations format
    valid_recs = []
    for rec in normalized["recommendations"]:
        if isinstance(rec, dict) and "sector" in rec:
            action = rec.get("action", "NEUTRAL").upper()
            if action not in ("OVERWEIGHT", "UNDERWEIGHT", "NEUTRAL"):
                action = "NEUTRAL"
            valid_recs.append({
                "sector": rec.get("sector", "Unknown"),
                "action": action,
                "rationale": rec.get("rationale", ""),
            })
    normalized["recommendations"] = valid_recs

    # Ensure lists are actually lists
    if not isinstance(normalized["rotation_signals"], list):
        normalized["rotation_signals"] = [str(normalized["rotation_signals"])]
    if not isinstance(normalized["key_observations"], list):
        normalized["key_observations"] = [str(normalized["key_observations"])]

    # Clamp confidence values to [0, 1]
    normalized["phase_confidence"] = max(0.0, min(1.0, normalized["phase_confidence"]))
    normalized["confidence"] = max(0.0, min(1.0, normalized["confidence"]))

    return normalized


def _default_error_response(error_message: str) -> dict:
    """Create a default error response.

    Args:
        error_message: Description of the error.

    Returns:
        Dictionary with error information and default values.
    """
    return {
        "analyst": "sector",
        "market_phase": "unknown",
        "phase_confidence": 0.0,
        "sector_rankings": [],
        "recommendations": [],
        "rotation_signals": [],
        "key_observations": [f"Error: {error_message}"],
        "confidence": 0.0,
        "error": error_message,
    }
