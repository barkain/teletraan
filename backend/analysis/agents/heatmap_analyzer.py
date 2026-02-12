"""Heatmap Analyzer agent for LLM-driven heatmap pattern analysis and stock selection.

This module provides the heatmap analysis phase of the autonomous pipeline.
It receives formatted heatmap data (from heatmap_fetcher) and macro context
(from MacroScanner Phase 1), then uses an LLM to identify patterns, divergences,
and select stocks for deep dive analysis.

Pipeline position:
    MacroScan (Phase 1) -> HeatmapFetch (Phase 2) -> **HeatmapAnalysis (Phase 3)** -> DeepDive -> CoverageEval -> Synthesis

The LLM acts as a market strategist analyzing a sector heatmap treemap where:
    - Size = market capitalization
    - Color = performance (green = positive, red = negative)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from analysis.agents.heatmap_interfaces import (  # type: ignore[import-not-found]
    HeatmapAnalysis,
    HeatmapPattern,
    HeatmapStockSelection,
    VALID_OPPORTUNITY_TYPES,
)

logger = logging.getLogger(__name__)


# =============================================================================
# HEATMAP ANALYZER PROMPT
# =============================================================================

HEATMAP_ANALYZER_PROMPT = """You are a Market Strategist analyzing a sector heatmap treemap of the S&P 500.

## Visual Concept
Imagine a treemap where:
- **Size** of each tile = market capitalization (larger companies = bigger tiles)
- **Color** of each tile = price performance (bright green = strong gains, deep red = heavy losses, gray = flat)
- Tiles are grouped by GICS sector

You are reading this heatmap to identify patterns, divergences, and actionable stock selections.

## Current Heatmap Data
{heatmap_data}

## Macro Context (from Phase 1)
{macro_context}

## Your Task
Analyze the heatmap and produce a structured analysis:

1. **OVERVIEW**: A 2-3 sentence summary of what the heatmap reveals about today's market.

2. **PATTERNS** (identify 3-5 patterns):
   For each pattern:
   - Description: What you observe (e.g., "Technology mega-caps diverging from sector breadth")
   - Sectors involved: Which sectors are part of this pattern
   - Implication: What this pattern suggests for positioning

   Pattern types to look for:
   - **Sector Momentum**: Entire sectors moving in one direction with breadth confirmation
   - **Divergences**: Stocks moving opposite to their sector, or sectors diverging from the market
   - **Outliers**: Individual stocks with outsized moves (statistical outliers in the heatmap)
   - **Rotation Signals**: Capital flowing from one sector group to another
   - **Cross-Sector Themes**: Common patterns across multiple sectors (e.g., all dividend stocks rallying)

3. **STOCK SELECTIONS** (select 10-15 specific individual stocks AND commodity futures for deep dive):
   For each stock:
   - symbol: Ticker symbol (must be a specific individual equity or commodity future)
   - sector: Sector classification (or "Commodities" for futures)
   - reason: WHY this stock is interesting — reference the specific pattern observed
   - opportunity_type: One of: momentum, divergence, breakout, mean_reversion, cross_sector
   - priority: high, medium, or low
   - expected_insight_value: 0.0-1.0, how likely a deep dive will yield actionable insight

   IMPORTANT: Do NOT select sector ETFs (XLK, XLF, XLE, XLV, XLC, XLY, XLP, XLI, XLB, XLRE, XLU, etc.) for deep dive. Every selection must be a specific individual equity (e.g., AAPL, JPM, AMZN) or commodity future (e.g., GC=F for gold, CL=F for oil, SI=F for silver, HG=F for copper, NG=F for natural gas).

   Selection criteria:
   - Prioritize specific companies with clear catalysts over broad sector plays
   - Prioritize **diversity** across opportunity types (don't pick 8 momentum plays)
   - Include at least one divergence play (stock moving against its sector)
   - Include at least one cross-sector theme play
   - Include at least 2 commodity futures if macro themes warrant (e.g., GC=F for gold, CL=F for oil)
   - Favor stocks where the heatmap pattern creates an analytical question worth investigating
   - Higher priority for stocks where multiple signals converge

4. **SECTORS TO WATCH**: List 2-4 sectors showing notable activity worth monitoring.

5. **CONFIDENCE**: 0.0-1.0, your overall confidence in this analysis.
   - Higher (>0.7) when patterns are clear and consistent
   - Lower (<0.5) when signals are mixed or data is thin

## Output Format
Return your analysis as valid JSON:
{{
  "overview": "Today's heatmap shows...",
  "patterns": [
    {{
      "description": "Technology sector showing broad-based strength with 8/10 top holdings green",
      "sectors": ["Technology"],
      "implication": "Risk-on rotation into growth, likely driven by falling rate expectations"
    }},
    {{
      "description": "Energy mega-caps (XOM, CVX) diverging from broader energy weakness",
      "sectors": ["Energy"],
      "implication": "Flight to quality within energy; smaller E&P names under pressure while integrated majors hold"
    }}
  ],
  "selected_stocks": [
    {{
      "symbol": "NVDA",
      "sector": "Technology",
      "reason": "Leading the tech momentum with outsized 1d gain of +3.2%, volume 1.5x average. Mega-cap leadership pattern suggests institutional accumulation.",
      "opportunity_type": "momentum",
      "priority": "high",
      "expected_insight_value": 0.85
    }},
    {{
      "symbol": "DVN",
      "sector": "Energy",
      "reason": "Diverging positively from a weak energy sector — up +1.1% while most energy names are down. Strong free cash flow yield and buyback catalyst.",
      "opportunity_type": "divergence",
      "priority": "high",
      "expected_insight_value": 0.80
    }},
    {{
      "symbol": "GC=F",
      "sector": "Commodities",
      "reason": "Gold futures rallying +1.5% on safe-haven bid, aligning with risk-off macro signals and falling real yields.",
      "opportunity_type": "cross_sector",
      "priority": "medium",
      "expected_insight_value": 0.75
    }}
  ],
  "sectors_to_watch": ["Technology", "Energy", "Financials"],
  "confidence": 0.75
}}

## Guidelines
- Be specific — reference actual data points (prices, changes, volume ratios)
- Explain WHY each stock was selected, linking back to observed patterns
- Don't just pick the biggest movers; look for analytically interesting situations
- Consider macro context alignment when scoring priority
- A stock diverging from its sector is often more interesting than one moving with it
- Volume confirmation (volume_ratio > 1.2) increases confidence in any pattern
- Breadth (what fraction of a sector is moving together) matters for pattern reliability
"""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def format_heatmap_analysis_context(
    heatmap_summary: str,
    macro_context: dict[str, Any],
) -> str:
    """Format heatmap data and macro context into the analysis prompt.

    Takes the formatted heatmap text (from heatmap_fetcher.format_heatmap_for_llm)
    and macro context from Phase 1 MacroScanner, and structures them into
    the HEATMAP_ANALYZER_PROMPT template.

    Args:
        heatmap_summary: Pre-formatted heatmap text from heatmap_fetcher.
            Contains sector-level and stock-level performance data.
        macro_context: Dictionary with macro scan results. Expected keys:
            - market_regime: str (e.g., "Risk-On", "Risk-Off")
            - regime_confidence: float
            - regime_evidence: list[str]
            - themes: list[dict] with name, direction, affected_sectors
            - actionable_implications: dict with sector_preferences, risk_posture
            - key_risks: list[dict]

    Returns:
        Complete prompt string ready for LLM consumption.
    """
    # Format macro context into readable text
    macro_parts: list[str] = []

    regime = macro_context.get("market_regime", "Unknown")
    regime_confidence = macro_context.get("regime_confidence", 0.5)
    macro_parts.append(f"Market Regime: {regime} (confidence: {regime_confidence:.0%})")

    # Regime evidence
    evidence = macro_context.get("regime_evidence", [])
    if evidence:
        macro_parts.append("Evidence:")
        for e in evidence[:3]:
            macro_parts.append(f"  - {e}")

    # Active themes
    themes = macro_context.get("themes", [])
    if themes:
        macro_parts.append("")
        macro_parts.append("Active Macro Themes:")
        for theme in themes[:3]:
            if isinstance(theme, dict):
                direction = theme.get("direction", "mixed")
                name = theme.get("name", "Unknown")
                confidence = theme.get("confidence", "medium")
                macro_parts.append(f"  [{direction}] {name} ({confidence} confidence)")
                affected = theme.get("affected_sectors", [])
                if affected:
                    macro_parts.append(f"    Sectors: {', '.join(affected[:4])}")

    # Sector preferences
    implications = macro_context.get("actionable_implications", {})
    if isinstance(implications, dict):
        sector_prefs = implications.get("sector_preferences", {})
        if isinstance(sector_prefs, dict):
            overweight = sector_prefs.get("overweight", [])
            underweight = sector_prefs.get("underweight", [])
            if overweight:
                macro_parts.append(f"\nOverweight: {', '.join(overweight)}")
            if underweight:
                macro_parts.append(f"Underweight: {', '.join(underweight)}")
        risk_posture = implications.get("risk_posture", "neutral")
        macro_parts.append(f"Risk Posture: {risk_posture}")

    # Key risks
    risks = macro_context.get("key_risks", [])
    if risks:
        macro_parts.append("\nKey Risks:")
        for risk in risks[:2]:
            if isinstance(risk, dict):
                macro_parts.append(
                    f"  - {risk.get('description', 'Unknown')} "
                    f"({risk.get('probability', 'medium')} probability)"
                )

    macro_formatted = "\n".join(macro_parts) if macro_parts else "No macro context available."

    return HEATMAP_ANALYZER_PROMPT.format(
        heatmap_data=heatmap_summary,
        macro_context=macro_formatted,
    )


def parse_heatmap_analysis_response(response: str) -> HeatmapAnalysis:
    """Parse the heatmap analyzer LLM response into a HeatmapAnalysis object.

    Extracts JSON from the LLM response, validates fields, and constructs
    a HeatmapAnalysis dataclass with defaults for any missing optional fields.

    Args:
        response: Raw LLM response text, which may contain JSON in code blocks,
            as raw JSON, or embedded within prose.

    Returns:
        HeatmapAnalysis dataclass instance with parsed data.
        On parse failure, returns a minimal HeatmapAnalysis with the raw
        response captured in the overview field.
    """
    json_data = _extract_json(response)

    if json_data is None:
        logger.warning("Could not extract JSON from heatmap analyzer response")
        return HeatmapAnalysis(
            overview=f"Parse error. Raw response: {response[:500]}...",
            confidence=0.0,
        )

    try:
        # Validate and normalize patterns
        raw_patterns = json_data.get("patterns", [])
        patterns: list[HeatmapPattern] = []
        for p in raw_patterns:
            if isinstance(p, dict):
                patterns.append(HeatmapPattern(
                    description=p.get("description", ""),
                    sectors=p.get("sectors", []),
                    implication=p.get("implication", ""),
                ))

        # Validate and normalize selected stocks
        raw_stocks = json_data.get("selected_stocks", [])
        selected_stocks: list[HeatmapStockSelection] = []
        for s in raw_stocks:
            if isinstance(s, dict):
                # Normalize opportunity_type
                opp_type = s.get("opportunity_type", "").lower().replace(" ", "_")
                if opp_type not in VALID_OPPORTUNITY_TYPES:
                    # Map common alternatives
                    type_map = {
                        "sector_leader": "momentum",
                        "catalyst": "momentum",
                        "cross_sector": "momentum",
                    }
                    opp_type = type_map.get(opp_type, opp_type)

                # Normalize priority
                priority = s.get("priority", "medium").lower()
                if priority not in {"high", "medium", "low"}:
                    priority = "medium"

                # Clamp expected_insight_value
                eiv = float(s.get("expected_insight_value", 0.5))
                eiv = max(0.0, min(1.0, eiv))

                selected_stocks.append(HeatmapStockSelection(
                    symbol=s.get("symbol", "UNKNOWN"),
                    sector=s.get("sector", "Unknown"),
                    reason=s.get("reason", ""),
                    opportunity_type=opp_type,
                    priority=priority,
                    expected_insight_value=eiv,
                ))

        # Clamp confidence
        confidence = float(json_data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        return HeatmapAnalysis(
            overview=json_data.get("overview", ""),
            patterns=patterns,
            selected_stocks=selected_stocks,
            sectors_to_watch=json_data.get("sectors_to_watch", []),
            confidence=confidence,
        )

    except (KeyError, TypeError, ValueError) as e:
        logger.error(f"Error parsing heatmap analyzer response: {e}")
        return HeatmapAnalysis(
            overview=f"Parse error: {e}",
            confidence=0.0,
        )


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract JSON from text that may contain other content.

    Handles various formats:
    - Pure JSON
    - JSON in code blocks (```json ... ```)
    - JSON embedded in prose text

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
