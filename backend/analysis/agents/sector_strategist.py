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
        market_data: Dictionary containing sector performance data with keys:
            - sector_metrics: Dict mapping sector symbols to performance metrics
            - rotation_analysis: Dict with rotation signals and leading/lagging sectors
            - market_phase: Current identified market phase
            - benchmark_performance: SPY/benchmark returns
            - economic_indicators: Optional economic context

    Returns:
        Formatted string context for the LLM agent.
    """
    if not market_data:
        return "No sector data available for analysis."

    context_parts = []

    # Add sector performance metrics
    sector_metrics = market_data.get("sector_metrics", {})
    if sector_metrics:
        context_parts.append("## Sector Performance Metrics")
        context_parts.append("")

        # Sort by relative strength descending
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

    # Add rotation analysis
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

        signals = rotation.get("signals", [])
        if signals:
            context_parts.append("Signals:")
            for signal in signals:
                sig_type = signal.get("signal", "unknown")
                description = signal.get("description", "")
                strength = signal.get("strength", "moderate")
                context_parts.append(f"  - [{sig_type.upper()}] {description} (strength: {strength})")

        context_parts.append("")

    # Add market phase context
    market_phase = market_data.get("market_phase", "unknown")
    phase_desc = market_data.get("phase_description", "")
    expected_leaders = market_data.get("expected_leaders", [])

    if market_phase != "unknown":
        context_parts.append("## Current Market Phase")
        context_parts.append("")
        context_parts.append(f"Phase: {market_phase.replace('_', ' ').title()}")
        if phase_desc:
            context_parts.append(f"Description: {phase_desc}")
        if expected_leaders:
            context_parts.append(f"Expected Leaders: {', '.join(expected_leaders)}")
        context_parts.append("")

    # Add benchmark performance
    benchmark = market_data.get("benchmark_performance", {})
    if benchmark:
        context_parts.append("## Benchmark (SPY)")
        context_parts.append("")
        context_parts.append(
            f"Daily: {benchmark.get('daily_return', 0):+.2f}%, "
            f"Weekly: {benchmark.get('weekly_return', 0):+.2f}%, "
            f"Monthly: {benchmark.get('monthly_return', 0):+.2f}%"
        )
        context_parts.append("")

    # Add economic indicators if available
    economic = market_data.get("economic_indicators", {})
    if economic:
        context_parts.append("## Economic Context")
        context_parts.append("")
        for indicator, value in economic.items():
            formatted_name = indicator.replace("_", " ").title()
            if isinstance(value, (int, float)):
                context_parts.append(f"- {formatted_name}: {value:.2f}")
            else:
                context_parts.append(f"- {formatted_name}: {value}")
        context_parts.append("")

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
