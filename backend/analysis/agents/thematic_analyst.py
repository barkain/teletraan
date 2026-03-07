"""Thematic Analyst agent for identifying cross-cutting investment themes from macro data.

This module provides thematic analysis that sits between the MacroScanner output
and downstream stock selection. It identifies 3-5 investable thematic threads
that cut across sectors, emphasizing supply chain reasoning, cascade effects,
and specific tradeable symbols.

Pipeline position:
    **MacroScan (Phase 1)** -> ThematicAnalysis -> HeatmapFetch -> HeatmapAnalysis -> DeepDive -> Synthesis

The LLM acts as a thematic investment strategist who:
    - Identifies structural investment themes from macro conditions
    - Maps supply chain linkages and cascade effects
    - Selects specific tradeable symbols for each theme
    - Identifies interactions (reinforcing/conflicting) between themes
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class ThematicThread:
    """A single cross-cutting investment theme identified from macro data.

    Represents a structural investment theme that spans multiple sectors,
    including supply chain linkages and specific tradeable symbols.

    Attributes:
        theme_name: Descriptive name (e.g., "AI Infrastructure Buildout")
        category: Theme category for grouping and filtering
        direction: Directional bias (bullish, bearish, mixed)
        confidence: Confidence in this theme (0.0-1.0)
        affected_sectors: Sectors impacted by this theme
        primary_symbols: Best 3-6 tradeable symbols for this theme
        supply_chain_links: Supply chain linkage descriptions
        catalyst_timeline: When catalysts are expected to materialize
        thesis: Investment thesis (2-3 sentences)
        counter_thesis: Primary risk to the thesis
    """

    theme_name: str
    category: str  # ai_infrastructure, energy_transition, deglobalization, etc.
    direction: str = "mixed"  # bullish, bearish, mixed
    confidence: float = 0.5  # 0.0-1.0
    affected_sectors: list[str] = field(default_factory=list)
    primary_symbols: list[str] = field(default_factory=list)
    supply_chain_links: list[str] = field(default_factory=list)
    catalyst_timeline: str = "medium_term"  # near_term, medium_term, long_term
    thesis: str = ""
    counter_thesis: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "theme_name": self.theme_name,
            "category": self.category,
            "direction": self.direction,
            "confidence": round(self.confidence, 4),
            "affected_sectors": self.affected_sectors,
            "primary_symbols": self.primary_symbols,
            "supply_chain_links": self.supply_chain_links,
            "catalyst_timeline": self.catalyst_timeline,
            "thesis": self.thesis,
            "counter_thesis": self.counter_thesis,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ThematicThread:
        """Create from dictionary, handling missing keys gracefully."""
        confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        return cls(
            theme_name=data.get("theme_name", "Unknown Theme"),
            category=data.get("category", "other"),
            direction=data.get("direction", "mixed"),
            confidence=confidence,
            affected_sectors=data.get("affected_sectors", []),
            primary_symbols=data.get("primary_symbols", []),
            supply_chain_links=data.get("supply_chain_links", []),
            catalyst_timeline=data.get("catalyst_timeline", "medium_term"),
            thesis=data.get("thesis", ""),
            counter_thesis=data.get("counter_thesis", ""),
        )


@dataclass
class ThematicAnalysisResult:
    """Complete result from thematic analysis of macro scan data.

    Contains all identified thematic threads, their interactions,
    and a meta-narrative connecting the themes.

    Attributes:
        threads: List of identified thematic threads (3-5 expected)
        meta_narrative: 2-3 sentences connecting all themes into a coherent view
        theme_interactions: How themes reinforce or conflict with each other
        confidence: Overall confidence in the thematic analysis (0.0-1.0)
        scan_timestamp: When this analysis was performed
    """

    threads: list[ThematicThread] = field(default_factory=list)
    meta_narrative: str = ""
    theme_interactions: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.5
    scan_timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "threads": [t.to_dict() for t in self.threads],
            "meta_narrative": self.meta_narrative,
            "theme_interactions": self.theme_interactions,
            "confidence": round(self.confidence, 4),
            "scan_timestamp": self.scan_timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ThematicAnalysisResult:
        """Create from dictionary, handling missing keys gracefully."""
        # Parse threads
        threads = []
        for t_data in data.get("threads", []):
            if isinstance(t_data, dict):
                threads.append(ThematicThread.from_dict(t_data))

        # Parse theme interactions
        interactions = []
        for i_data in data.get("theme_interactions", []):
            if isinstance(i_data, dict):
                interactions.append({
                    "theme_a": i_data.get("theme_a", ""),
                    "theme_b": i_data.get("theme_b", ""),
                    "interaction": i_data.get("interaction", "reinforcing"),
                    "explanation": i_data.get("explanation", ""),
                })

        confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        scan_timestamp = data.get("scan_timestamp", "")
        if not scan_timestamp:
            scan_timestamp = datetime.utcnow().isoformat()

        return cls(
            threads=threads,
            meta_narrative=data.get("meta_narrative", ""),
            theme_interactions=interactions,
            confidence=confidence,
            scan_timestamp=scan_timestamp,
        )


# =============================================================================
# THEMATIC ANALYST PROMPT
# =============================================================================

THEMATIC_ANALYST_PROMPT = """You are a Thematic Investment Strategist analyzing macro conditions to identify cross-cutting investment themes.

## Your Role
Identify 3-5 structural investment themes that cut across sectors and asset classes. Focus on supply chain reasoning, cascade effects, and specific tradeable symbols. Each theme should represent a multi-month investable narrative, not just a one-day market move.

## Current Macro Context
{macro_context}

## Your Task
Analyze the macro data above and identify cross-cutting investment themes:

1. **THEMATIC THREADS** (identify 3-5 themes):
   For each theme:
   - theme_name: Descriptive name (e.g., "AI Infrastructure Buildout", "Energy Transition Acceleration", "Deglobalization & Reshoring")
   - category: One of: ai_infrastructure, energy_transition, deglobalization, monetary_policy, geopolitical, consumer_shift, commodity_supercycle, financial_stress, healthcare_innovation, climate_adaptation, other
   - direction: bullish, bearish, or mixed
   - confidence: 0.0-1.0
   - affected_sectors: List of GICS sectors impacted
   - primary_symbols: 3-6 specific tradeable symbols (individual stocks or commodity futures, NOT ETFs). These should be the best expressions of the theme.
   - supply_chain_links: List of supply chain linkage strings showing cascade effects (e.g., "TSMC (fab) -> NVDA (GPU design) -> MSFT (cloud deployment) -> CRM (enterprise AI)")
   - catalyst_timeline: near_term (0-3 months), medium_term (3-12 months), or long_term (12+ months)
   - thesis: 2-3 sentence investment thesis explaining why this theme matters now
   - counter_thesis: The main risk or reason this theme could fail

   Theme identification guidelines:
   - Look for themes that connect MULTIPLE sectors (not just a single-sector story)
   - Emphasize supply chain relationships and second/third-order effects
   - Consider both beneficiaries AND losers from each theme
   - Prioritize themes with near-term catalysts over purely structural stories
   - Include at least one contrarian or under-appreciated theme

2. **META-NARRATIVE**: 2-3 sentences connecting all identified themes into a coherent market story. How do these themes interact? What is the overarching market narrative?

3. **THEME INTERACTIONS**: For each pair of themes that interact meaningfully:
   - theme_a: Name of first theme
   - theme_b: Name of second theme
   - interaction: "reinforcing" (themes amplify each other) or "conflicting" (themes work against each other)
   - explanation: Brief explanation of how they interact

4. **CONFIDENCE**: 0.0-1.0 overall confidence in this thematic analysis.
   - Higher (>0.7) when macro signals clearly support identified themes
   - Lower (<0.5) when signals are ambiguous or conflicting

## Output Format
Return your analysis as valid JSON:
{{
  "threads": [
    {{
      "theme_name": "AI Infrastructure Buildout",
      "category": "ai_infrastructure",
      "direction": "bullish",
      "confidence": 0.85,
      "affected_sectors": ["Technology", "Industrials", "Utilities", "Energy"],
      "primary_symbols": ["NVDA", "AVGO", "ANET", "VRT", "EQIX", "CEG"],
      "supply_chain_links": [
        "TSMC (fab) -> NVDA (GPU) -> MSFT (cloud) -> CRM (enterprise AI)",
        "CEG (nuclear power) -> EQIX (data centers) -> AMZN (AWS inference)",
        "VRT (cooling) -> ANET (networking) -> GOOGL (AI training clusters)"
      ],
      "catalyst_timeline": "near_term",
      "thesis": "Hyperscaler capex continues to accelerate with no signs of slowing. Power constraints are becoming the binding constraint, benefiting utilities and infrastructure plays. Networking demand is inflecting as inference workloads scale.",
      "counter_thesis": "AI revenue monetization disappoints, leading to capex cuts and a repeat of the 2000 telecom overbuild cycle."
    }},
    {{
      "theme_name": "Rate Sensitivity Rotation",
      "category": "monetary_policy",
      "direction": "bullish",
      "confidence": 0.70,
      "affected_sectors": ["Real Estate", "Utilities", "Financials", "Consumer Discretionary"],
      "primary_symbols": ["AMT", "O", "HD", "SCHW"],
      "supply_chain_links": [
        "Fed (rate cuts) -> Banks (NIM compression) -> SCHW (sweep revenue)",
        "Lower rates -> Mortgage rates -> HD (housing renovation cycle)",
        "Lower rates -> Cap rate compression -> AMT (tower valuations)"
      ],
      "catalyst_timeline": "medium_term",
      "thesis": "With inflation moderating and labor market softening, rate-sensitive sectors are poised for re-rating. Duration assets benefit from falling yields while housing-adjacent names see demand recovery.",
      "counter_thesis": "Sticky services inflation forces the Fed to hold rates higher for longer, disappointing rate-cut expectations."
    }}
  ],
  "meta_narrative": "The current macro environment is defined by a tension between structural AI-driven capex growth and cyclical monetary policy normalization. These forces create a barbell market where technology infrastructure beneficiaries and rate-sensitive value plays both have merit, while traditional cyclicals face margin pressure from still-elevated input costs.",
  "theme_interactions": [
    {{
      "theme_a": "AI Infrastructure Buildout",
      "theme_b": "Rate Sensitivity Rotation",
      "interaction": "reinforcing",
      "explanation": "Lower rates reduce the discount rate on long-duration AI capex investments, making hyperscaler spending more sustainable and boosting valuations of growth-oriented infrastructure plays."
    }}
  ],
  "confidence": 0.75,
  "scan_timestamp": "2024-01-15T10:30:00Z"
}}

## Guidelines
- Be specific with data references from the macro context provided
- Every primary_symbol must be a specific individual equity or commodity future (NO ETFs like XLK, XLF, etc.)
- Supply chain links should show clear cause-and-effect relationships
- Themes should be actionable, not just academic observations
- Consider second-order effects: who benefits indirectly?
- A good thematic thread connects at least 3 sectors
- Include both consensus and non-consensus themes
"""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def format_thematic_context(macro_result_dict: dict[str, Any]) -> str:
    """Format macro scan result dictionary into context text for the thematic analyst.

    Takes the dictionary output of MacroScanResult.to_dict() and formats it
    into a readable text block for the THEMATIC_ANALYST_PROMPT.

    Args:
        macro_result_dict: Dictionary from MacroScanResult.to_dict(). Expected keys:
            - market_regime: str
            - regime_confidence: float
            - regime_evidence: list[str]
            - themes: list[dict] with name, direction, affected_sectors, etc.
            - key_risks: list[dict] with description, probability, impact
            - actionable_implications: dict with sector_preferences, risk_posture, key_levels
            - raw_data: dict with treasuries, volatility, commodities, etc.

    Returns:
        Formatted context string ready for prompt injection.
    """
    parts: list[str] = []

    # Market regime
    regime = macro_result_dict.get("market_regime", "Unknown")
    regime_confidence = macro_result_dict.get("regime_confidence", 0.5)
    parts.append("=== MARKET REGIME ===")
    parts.append(f"Current Regime: {regime} (confidence: {regime_confidence:.0%})")

    # Regime evidence
    evidence = macro_result_dict.get("regime_evidence", [])
    if evidence:
        parts.append("Evidence:")
        for e in evidence:
            parts.append(f"  - {e}")

    # Macro themes from scanner
    themes = macro_result_dict.get("themes", [])
    if themes:
        parts.append("")
        parts.append("=== MACRO THEMES (from scanner) ===")
        for theme in themes:
            if isinstance(theme, dict):
                name = theme.get("name", "Unknown")
                direction = theme.get("direction", "mixed")
                confidence = theme.get("confidence", "medium")
                rationale = theme.get("rationale", "")
                parts.append(f"[{direction.upper()}] {name} ({confidence} confidence)")
                affected_sectors = theme.get("affected_sectors", [])
                if affected_sectors:
                    parts.append(f"  Sectors: {', '.join(affected_sectors)}")
                affected_assets = theme.get("affected_assets", [])
                if affected_assets:
                    parts.append(f"  Assets: {', '.join(affected_assets)}")
                if rationale:
                    parts.append(f"  Rationale: {rationale}")

    # Key risks
    risks = macro_result_dict.get("key_risks", [])
    if risks:
        parts.append("")
        parts.append("=== KEY RISKS ===")
        for risk in risks:
            if isinstance(risk, dict):
                desc = risk.get("description", "Unknown")
                prob = risk.get("probability", "medium")
                impact = risk.get("impact", "")
                parts.append(f"  - {desc} ({prob} probability)")
                if impact:
                    parts.append(f"    Impact: {impact}")

    # Actionable implications
    implications = macro_result_dict.get("actionable_implications", {})
    if isinstance(implications, dict):
        parts.append("")
        parts.append("=== POSITIONING ===")
        sector_prefs = implications.get("sector_preferences", {})
        if isinstance(sector_prefs, dict):
            overweight = sector_prefs.get("overweight", [])
            underweight = sector_prefs.get("underweight", [])
            neutral = sector_prefs.get("neutral", [])
            if overweight:
                parts.append(f"Overweight: {', '.join(overweight)}")
            if underweight:
                parts.append(f"Underweight: {', '.join(underweight)}")
            if neutral:
                parts.append(f"Neutral: {', '.join(neutral)}")
        risk_posture = implications.get("risk_posture", "neutral")
        parts.append(f"Risk Posture: {risk_posture}")
        key_levels = implications.get("key_levels", [])
        if key_levels:
            parts.append("Key Levels:")
            for level in key_levels:
                parts.append(f"  - {level}")

    # Raw market data summary (if available)
    raw_data = macro_result_dict.get("raw_data", {})
    if raw_data:
        # Treasuries
        treasuries = raw_data.get("treasuries", {})
        if treasuries:
            parts.append("")
            parts.append("=== TREASURY YIELDS ===")
            for symbol, info in treasuries.items():
                if isinstance(info, dict):
                    name = info.get("name", symbol)
                    data = info.get("data", {})
                    current = data.get("current", 0)
                    change = data.get("change_20d_pct", 0)
                    trend = data.get("trend", "flat")
                    parts.append(
                        f"{name} ({symbol}): {current:.3f}% | "
                        f"20D Change: {change:+.2f}% | Trend: {trend}"
                    )

        # Volatility
        volatility = raw_data.get("volatility", {})
        if volatility:
            parts.append("")
            parts.append("=== VOLATILITY ===")
            for symbol, info in volatility.items():
                if isinstance(info, dict):
                    name = info.get("name", symbol)
                    data = info.get("data", {})
                    current = data.get("current", 0)
                    high = data.get("high_20d", 0)
                    low = data.get("low_20d", 0)
                    trend = data.get("trend", "flat")
                    parts.append(
                        f"{name} ({symbol}): {current:.2f} | "
                        f"20D Range: {low:.2f} - {high:.2f} | Trend: {trend}"
                    )

        # Commodities
        commodities = raw_data.get("commodities", {})
        if commodities:
            parts.append("")
            parts.append("=== COMMODITIES ===")
            for symbol, info in commodities.items():
                if isinstance(info, dict):
                    name = info.get("name", symbol)
                    data = info.get("data", {})
                    current = data.get("current", 0)
                    change = data.get("change_20d_pct", 0)
                    trend = data.get("trend", "flat")
                    parts.append(
                        f"{name} ({symbol}): ${current:.2f} | "
                        f"20D Change: {change:+.2f}% | Trend: {trend}"
                    )

        # US Indices
        us_indices = raw_data.get("us_indices", {})
        if us_indices:
            parts.append("")
            parts.append("=== US INDICES ===")
            for symbol, info in us_indices.items():
                if isinstance(info, dict):
                    name = info.get("name", symbol)
                    data = info.get("data", {})
                    current = data.get("current", 0)
                    change = data.get("change_20d_pct", 0)
                    trend = data.get("trend", "flat")
                    parts.append(
                        f"{name} ({symbol}): {current:,.2f} | "
                        f"20D Change: {change:+.2f}% | Trend: {trend}"
                    )

        # Sector ETFs
        sector_etfs = raw_data.get("sector_etfs", {})
        if sector_etfs:
            parts.append("")
            parts.append("=== SECTOR PERFORMANCE ===")
            sorted_sectors = sorted(
                sector_etfs.items(),
                key=lambda x: x[1].get("data", {}).get("change_20d_pct", 0)
                if isinstance(x[1], dict)
                else 0,
                reverse=True,
            )
            for symbol, info in sorted_sectors:
                if isinstance(info, dict):
                    name = info.get("name", symbol)
                    data = info.get("data", {})
                    current = data.get("current", 0)
                    change = data.get("change_20d_pct", 0)
                    trend = data.get("trend", "flat")
                    parts.append(
                        f"{name} ({symbol}): ${current:.2f} | "
                        f"20D Change: {change:+.2f}% | Trend: {trend}"
                    )

    return "\n".join(parts) if parts else "No macro context available."


def parse_thematic_response(response: str) -> ThematicAnalysisResult:
    """Parse the thematic analyst LLM response into a ThematicAnalysisResult.

    Extracts JSON from the LLM response, validates fields, and constructs
    a ThematicAnalysisResult dataclass with defaults for any missing fields.

    Args:
        response: Raw LLM response text, which may contain JSON in code blocks,
            as raw JSON, or embedded within prose.

    Returns:
        ThematicAnalysisResult dataclass instance with parsed data.
        On parse failure, returns a minimal result with the raw response
        captured in the meta_narrative field.
    """
    json_data = _extract_json(response)

    if json_data is None:
        logger.warning("Could not extract JSON from thematic analyst response")
        return ThematicAnalysisResult(
            meta_narrative=f"Parse error. Raw response: {response[:500]}...",
            confidence=0.0,
            scan_timestamp=datetime.utcnow().isoformat(),
        )

    try:
        return ThematicAnalysisResult.from_dict(json_data)
    except (KeyError, TypeError, ValueError) as e:
        logger.warning(f"Error parsing thematic analyst response: {e}")
        return ThematicAnalysisResult(
            meta_narrative=f"Parse error: {e}",
            confidence=0.0,
            scan_timestamp=datetime.utcnow().isoformat(),
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


def format_thematic_for_downstream(result: ThematicAnalysisResult) -> str:
    """Format thematic analysis result as markdown for downstream context injection.

    Creates a structured markdown section suitable for passing to discovery,
    deep dive, and synthesis agents.

    Args:
        result: Completed thematic analysis result.

    Returns:
        Formatted markdown string for context injection.
    """
    lines: list[str] = []

    lines.append("=== THEMATIC ANALYSIS ===")
    lines.append(f"Overall Confidence: {result.confidence:.0%}")
    lines.append("")

    # Meta-narrative
    if result.meta_narrative:
        lines.append("**Meta-Narrative:**")
        lines.append(result.meta_narrative)
        lines.append("")

    # Individual themes
    if result.threads:
        lines.append("**Active Themes:**")
        for i, thread in enumerate(result.threads, 1):
            direction_marker = {
                "bullish": "+",
                "bearish": "-",
                "mixed": "~",
            }.get(thread.direction, "?")

            lines.append(
                f"{i}. [{direction_marker}] {thread.theme_name} "
                f"({thread.category}, {thread.confidence:.0%} confidence, "
                f"{thread.catalyst_timeline})"
            )

            # Thesis
            if thread.thesis:
                lines.append(f"   Thesis: {thread.thesis}")

            # Counter-thesis
            if thread.counter_thesis:
                lines.append(f"   Risk: {thread.counter_thesis}")

            # Primary symbols
            if thread.primary_symbols:
                lines.append(f"   Symbols: {', '.join(thread.primary_symbols)}")

            # Affected sectors
            if thread.affected_sectors:
                lines.append(f"   Sectors: {', '.join(thread.affected_sectors)}")

            # Supply chain links
            if thread.supply_chain_links:
                lines.append("   Supply Chain:")
                for link in thread.supply_chain_links:
                    lines.append(f"     - {link}")

            lines.append("")

    # Theme interactions
    if result.theme_interactions:
        lines.append("**Theme Interactions:**")
        for interaction in result.theme_interactions:
            theme_a = interaction.get("theme_a", "?")
            theme_b = interaction.get("theme_b", "?")
            kind = interaction.get("interaction", "?")
            explanation = interaction.get("explanation", "")
            lines.append(f"  - {theme_a} <-> {theme_b}: {kind}")
            if explanation:
                lines.append(f"    {explanation}")
        lines.append("")

    return "\n".join(lines)
