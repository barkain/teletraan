"""Coverage Evaluator agent for assessing deep dive coverage completeness.

This module provides the coverage evaluation logic that runs AFTER deep dives
to determine whether the current set of analyzed stocks provides sufficient
market coverage. If gaps are found, it recommends additional stocks for
analysis (up to MAX_ITERATIONS=2 rounds).

Pipeline Position:
    MacroScan -> HeatmapFetch -> HeatmapAnalysis -> DeepDive ->
    **CoverageEval (loop max 2x)** -> Synthesis
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from analysis.agents.heatmap_interfaces import (  # type: ignore[import-not-found]
    CoverageEvaluation,
)

logger = logging.getLogger(__name__)


# =============================================================================
# COVERAGE EVALUATOR PROMPT
# =============================================================================

COVERAGE_EVALUATOR_PROMPT = """You are a Research Director evaluating whether the current set of deep dive analyses provides sufficient market coverage.

## Your Role
After the team has completed deep dives on a set of stocks, you review the overall coverage and determine if additional analysis would meaningfully improve the quality and completeness of the research output.

## What You Receive
1. **Analyzed Stocks**: A list of stocks that have already been deeply analyzed, with summaries of each deep dive.
2. **Heatmap Data**: The full market heatmap showing sector performance, outliers, and divergences.
3. **Macro Context**: Current macro environment, themes, and sector preferences.
4. **Iteration Number**: Which coverage evaluation pass this is (1 or 2, max 2).

## Your Task
Evaluate whether the analyzed stocks provide adequate coverage across:

1. **Sector Diversification**: Are all major sectors represented, especially those flagged by macro analysis?
2. **Theme Coverage**: Do the analyzed stocks cover the key macro themes identified?
3. **Risk Balance**: Is there a mix of offensive (growth/momentum) and defensive positions?
4. **Contrarian Views**: Are there any contrarian or mean-reversion opportunities being missed?
5. **Opportunity Types**: Are different opportunity types represented (momentum, breakout, divergence, etc.)?

## Decision Framework
- **SUFFICIENT** (is_sufficient=true): The current coverage is good enough. Set this when:
  - Most sectors of interest are represented
  - Key macro themes have stock-level coverage
  - Adding more stocks would yield diminishing returns
  - This is iteration 2 (hard cap — always mark sufficient on iteration 2)

- **INSUFFICIENT** (is_sufficient=false): Additional stocks needed. Set this when:
  - A sector flagged as "overweight" by macro has zero representation
  - A major theme has no stock-level coverage
  - All analyzed stocks are in the same direction (all bullish or all bearish)
  - Only recommend 2-5 additional stocks that would ADD SIGNIFICANT VALUE

## Output Format
Return valid JSON:
{{
  "is_sufficient": false,
  "gaps": [
    {{
      "description": "No energy sector exposure despite bullish macro signal on rising oil prices",
      "suggested_sectors": ["Energy"],
      "suggested_stocks": ["XOM", "CVX"],
      "importance": "high"
    }},
    {{
      "description": "Missing defensive hedge — all selections are high-beta growth",
      "suggested_sectors": ["Healthcare", "Consumer Staples"],
      "suggested_stocks": ["JNJ"],
      "importance": "medium"
    }}
  ],
  "additional_stocks_recommended": [
    {{
      "symbol": "XOM",
      "sector": "Energy",
      "reason": "Top energy play aligned with rising oil macro theme, strong relative strength",
      "opportunity_type": "sector_leader",
      "priority": "high",
      "expected_insight_value": 0.8
    }},
    {{
      "symbol": "JNJ",
      "sector": "Healthcare",
      "reason": "Defensive hedge with stable dividend, provides portfolio balance",
      "opportunity_type": "mean_reversion",
      "priority": "medium",
      "expected_insight_value": 0.6
    }}
  ],
  "reasoning": "Current coverage is heavily tilted toward technology and growth. Adding energy exposure captures the rising oil theme from macro analysis, and a healthcare name provides defensive balance. These additions meaningfully improve coverage without diluting focus.",
  "iteration_number": 1
}}

## Guidelines
- Be CONSERVATIVE — only recommend additions that genuinely fill coverage gaps
- Maximum 5 additional stocks per iteration
- On iteration 2, you MUST set is_sufficient=true (hard cap)
- Do NOT recommend stocks already analyzed
- Prioritize gaps that align with macro themes
- Consider the marginal value of each additional stock
- Use valid opportunity_type values: momentum, mean_reversion, breakout, catalyst, sector_leader, divergence
"""


# =============================================================================
# CONTEXT FORMATTING
# =============================================================================


def format_coverage_context(
    analyzed_stocks: list[dict[str, Any]],
    heatmap_data: dict[str, Any],
    macro_context: dict[str, Any],
    iteration: int,
) -> str:
    """Format coverage evaluation context for the LLM.

    Takes the list of already-analyzed stocks with their deep dive summaries,
    the heatmap data, macro context, and current iteration number, then
    formats everything into a structured prompt.

    Args:
        analyzed_stocks: List of dicts with keys like 'symbol', 'sector',
            'summary', 'action', 'confidence', etc. from deep dive results.
        heatmap_data: Dictionary from HeatmapData.to_dict() with sector and
            stock-level heatmap information.
        macro_context: Dictionary with macro scan results including regime,
            themes, sector preferences.
        iteration: Current iteration number (1 or 2).

    Returns:
        Formatted string context for the coverage evaluator prompt.
    """
    sections: list[str] = []

    # Header
    sections.append(f"## Coverage Evaluation — Iteration {iteration}")
    sections.append(f"(Max iterations: {CoverageEvaluation.MAX_ITERATIONS})")
    sections.append("")

    # Already analyzed stocks
    sections.append("## Stocks Already Analyzed")
    sections.append("")

    if analyzed_stocks:
        for i, stock in enumerate(analyzed_stocks, 1):
            symbol = stock.get("symbol", "UNKNOWN")
            sector = stock.get("sector", "Unknown")
            summary = stock.get("summary", "No summary available")
            action = stock.get("action", "N/A")
            confidence = stock.get("confidence", 0.0)

            sections.append(f"### {i}. {symbol} ({sector})")
            sections.append(f"Action: {action} | Confidence: {confidence:.0%}")
            sections.append(f"Summary: {summary}")
            sections.append("")

        # Sector coverage summary
        sectors_covered = set()
        for stock in analyzed_stocks:
            sector = stock.get("sector", "")
            if sector:
                sectors_covered.add(sector)

        sections.append(f"**Sectors Covered ({len(sectors_covered)}):** {', '.join(sorted(sectors_covered))}")
        sections.append("")
    else:
        sections.append("No stocks have been analyzed yet.")
        sections.append("")

    # Heatmap data summary
    sections.append("## Market Heatmap Summary")
    sections.append("")

    heatmap_sectors = heatmap_data.get("sectors", [])
    if heatmap_sectors:
        sections.append("| Sector | ETF | 1D Change | 5D Change | 20D Change | Breadth |")
        sections.append("|--------|-----|-----------|-----------|------------|---------|")
        for s in heatmap_sectors:
            if isinstance(s, dict):
                sections.append(
                    f"| {s.get('name', 'N/A')} | {s.get('etf', '')} | "
                    f"{s.get('change_1d', 0):+.2f}% | {s.get('change_5d', 0):+.2f}% | "
                    f"{s.get('change_20d', 0):+.2f}% | {s.get('breadth', 0):.0%} |"
                )
        sections.append("")

    heatmap_stocks = heatmap_data.get("stocks", [])
    if heatmap_stocks:
        # Show notable movers not yet analyzed
        analyzed_symbols = {s.get("symbol", "") for s in analyzed_stocks}
        unanalyzed = [
            s for s in heatmap_stocks
            if isinstance(s, dict) and s.get("symbol", "") not in analyzed_symbols
        ]

        if unanalyzed:
            # Sort by absolute 1d change to show most notable
            unanalyzed.sort(
                key=lambda x: abs(x.get("change_1d", 0)),
                reverse=True,
            )
            top_movers = unanalyzed[:15]

            sections.append("### Notable Unanalyzed Stocks (by magnitude of move)")
            sections.append("| Symbol | Sector | 1D | 5D | 20D | Vol Ratio |")
            sections.append("|--------|--------|----|----|-----|-----------|")
            for s in top_movers:
                sections.append(
                    f"| {s.get('symbol', '')} | {s.get('sector', '')} | "
                    f"{s.get('change_1d', 0):+.2f}% | {s.get('change_5d', 0):+.2f}% | "
                    f"{s.get('change_20d', 0):+.2f}% | {s.get('volume_ratio', 1.0):.1f}x |"
                )
            sections.append("")

    # Macro context
    sections.append("## Macro Context")
    sections.append("")

    regime = macro_context.get("market_regime", "Unknown")
    sections.append(f"**Market Regime:** {regime}")

    themes = macro_context.get("themes", [])
    if themes:
        sections.append("**Active Themes:**")
        for theme in themes:
            if isinstance(theme, dict):
                name = theme.get("name", "Unknown")
                direction = theme.get("direction", "mixed")
                affected = theme.get("affected_sectors", [])
                sections.append(f"  - {name} ({direction}): {', '.join(affected[:4])}")
        sections.append("")

    implications = macro_context.get("actionable_implications", {})
    if isinstance(implications, dict):
        prefs = implications.get("sector_preferences", {})
        if isinstance(prefs, dict):
            overweight = prefs.get("overweight", [])
            underweight = prefs.get("underweight", [])
            if overweight:
                sections.append(f"**Overweight Sectors:** {', '.join(overweight)}")
            if underweight:
                sections.append(f"**Underweight Sectors:** {', '.join(underweight)}")
            sections.append("")

    # Iteration instruction
    if iteration >= CoverageEvaluation.MAX_ITERATIONS:
        sections.append("## IMPORTANT: This is the FINAL iteration (iteration 2).")
        sections.append("You MUST set is_sufficient=true. No further iterations are allowed.")
        sections.append("")

    return "\n".join(sections)


# =============================================================================
# RESPONSE PARSING
# =============================================================================


def parse_coverage_response(response: str) -> CoverageEvaluation:
    """Parse LLM response into a CoverageEvaluation.

    Extracts JSON from the response text and validates it against the
    CoverageEvaluation schema.

    Args:
        response: Raw LLM response text.

    Returns:
        Parsed CoverageEvaluation object.
    """
    json_data = _extract_json(response)

    if json_data is None:
        logger.warning("Could not extract JSON from coverage evaluator response")
        return CoverageEvaluation(
            is_sufficient=True,
            reasoning=f"Failed to parse response, marking as sufficient. Raw: {response[:500]}",
        )

    return CoverageEvaluation.from_dict(json_data)


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract JSON from text that may contain other content.

    Handles various formats:
    - Pure JSON
    - JSON in code blocks (```json ... ```)
    - JSON embedded in text

    Args:
        text: Text that may contain JSON.

    Returns:
        Parsed JSON dictionary or None if not found.
    """
    # First, try to parse the entire text as JSON
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Try to find JSON in code blocks
    code_block_pattern = r"```(?:json)?\s*([\s\S]*?)```"
    matches = re.findall(code_block_pattern, text)

    for match in matches:
        try:
            return json.loads(match.strip())
        except json.JSONDecodeError:
            continue

    # Try to find JSON object in the text
    start_idx = text.find("{")
    end_idx = text.rfind("}")

    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        potential_json = text[start_idx : end_idx + 1]
        try:
            return json.loads(potential_json)
        except json.JSONDecodeError:
            pass

    return None
