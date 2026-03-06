"""Investor Sentiment agent for LLM-driven analysis of institutional investor activity.

This module provides the investor sentiment analysis phase for the autonomous pipeline.
It receives formatted investor position data (from investor_feeds adapter) and macro
context (from MacroScanner), then uses an LLM to identify accumulation/distribution
patterns, consensus vs contrarian signals, and alignment with the macro environment.

The LLM acts as an institutional flow analyst identifying:
    - Accumulation patterns (multiple investors building positions in same names)
    - Distribution patterns (notable selling or position reduction)
    - Contrarian signals (superinvestors positioning against consensus)
    - Consensus views (convergent positioning across multiple managers)
    - Macro alignment (whether investor activity confirms or contradicts macro regime)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# DATA MODELS
# =============================================================================

VALID_SIGNAL_TYPES = {"accumulation", "distribution", "contrarian", "consensus"}
VALID_DIRECTIONS = {"bullish", "bearish", "neutral"}
VALID_ALIGNMENTS = {"aligned", "contrarian", "neutral"}


@dataclass
class InvestorSignal:
    """A detected signal from institutional investor activity analysis.

    Represents a pattern identified across one or more investors' positions
    and commentary, such as accumulation in a sector or contrarian positioning.

    Attributes:
        signal_type: Type of signal (accumulation, distribution, contrarian, consensus).
        symbols: Ticker symbols involved in this signal.
        investors: Names of investors contributing to this signal.
        direction: Overall directional bias (bullish, bearish, neutral).
        conviction: Strength of the signal (0.0-1.0).
        rationale: Explanation of why this signal was identified.
        alignment_with_macro: Whether signal aligns with macro regime
            (aligned, contrarian, neutral).
    """

    signal_type: str
    symbols: list[str] = field(default_factory=list)
    investors: list[str] = field(default_factory=list)
    direction: str = "neutral"  # bullish, bearish, neutral
    conviction: float = 0.5  # 0.0-1.0
    rationale: str = ""
    alignment_with_macro: str = "neutral"  # aligned, contrarian, neutral

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "signal_type": self.signal_type,
            "symbols": self.symbols,
            "investors": self.investors,
            "direction": self.direction,
            "conviction": round(self.conviction, 2),
            "rationale": self.rationale,
            "alignment_with_macro": self.alignment_with_macro,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InvestorSignal:
        """Create from dictionary with safe defaults.

        Args:
            data: Dictionary with signal fields.

        Returns:
            InvestorSignal instance with validated fields.
        """
        # Normalize and validate signal_type
        signal_type = data.get("signal_type", "consensus").lower().replace(" ", "_")
        if signal_type not in VALID_SIGNAL_TYPES:
            signal_type = "consensus"

        # Normalize direction
        direction = data.get("direction", "neutral").lower()
        if direction not in VALID_DIRECTIONS:
            direction = "neutral"

        # Clamp conviction
        conviction = float(data.get("conviction", 0.5))
        conviction = max(0.0, min(1.0, conviction))

        # Normalize alignment
        alignment = data.get("alignment_with_macro", "neutral").lower()
        if alignment not in VALID_ALIGNMENTS:
            alignment = "neutral"

        return cls(
            signal_type=signal_type,
            symbols=data.get("symbols", []),
            investors=data.get("investors", []),
            direction=direction,
            conviction=conviction,
            rationale=data.get("rationale", ""),
            alignment_with_macro=alignment,
        )


@dataclass
class InvestorIntelligenceResult:
    """Complete result from LLM-driven investor sentiment analysis.

    Contains the full analysis output including identified signals,
    consensus view, notable divergences, and key themes.

    Attributes:
        signals: List of identified investor signals.
        consensus_view: Summary of the overall consensus among tracked investors.
        notable_divergences: Notable disagreements between investors.
        key_themes: Key investment themes emerging from investor activity.
        confidence: Overall confidence in the analysis (0.0-1.0).
    """

    signals: list[InvestorSignal] = field(default_factory=list)
    consensus_view: str = ""
    notable_divergences: list[str] = field(default_factory=list)
    key_themes: list[str] = field(default_factory=list)
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "signals": [s.to_dict() for s in self.signals],
            "consensus_view": self.consensus_view,
            "notable_divergences": self.notable_divergences,
            "key_themes": self.key_themes,
            "confidence": round(self.confidence, 2),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InvestorIntelligenceResult:
        """Create from dictionary with safe defaults.

        Args:
            data: Dictionary with result fields.

        Returns:
            InvestorIntelligenceResult instance with validated fields.
        """
        signals = [
            InvestorSignal.from_dict(s)
            for s in data.get("signals", [])
            if isinstance(s, dict)
        ]

        # Clamp confidence
        confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        return cls(
            signals=signals,
            consensus_view=data.get("consensus_view", ""),
            notable_divergences=data.get("notable_divergences", []),
            key_themes=data.get("key_themes", []),
            confidence=confidence,
        )


# =============================================================================
# INVESTOR SENTIMENT PROMPT
# =============================================================================

INVESTOR_SENTIMENT_PROMPT = """You are an Institutional Flow Analyst specializing in tracking superinvestor positioning and sentiment.

You are analyzing recent 13F filings, position changes, and public commentary from some of the world's most successful institutional investors to identify actionable signals.

## Investor Positions & Commentary
{investor_context}

## Macro Context
{macro_context}

## Your Task
Analyze the investor data above and produce a structured intelligence report:

1. **SIGNALS** (identify 3-8 signals):
   For each signal:
   - signal_type: One of: accumulation, distribution, contrarian, consensus
   - symbols: Ticker symbols involved
   - investors: Which investors are part of this signal
   - direction: bullish, bearish, or neutral
   - conviction: 0.0-1.0, how strong this signal is
   - rationale: WHY this signal matters -- reference specific positions or commentary
   - alignment_with_macro: aligned, contrarian, or neutral relative to macro context

   Signal types to look for:
   - **Accumulation**: Multiple investors building or increasing positions in the same names
   - **Distribution**: Notable selling, trimming, or exiting positions
   - **Contrarian**: An investor positioning against the market consensus or their peers
   - **Consensus**: Broad agreement among multiple managers on a theme or name

2. **CONSENSUS VIEW**: A 2-4 sentence summary of where the majority of tracked investors are positioned and what that implies.

3. **NOTABLE DIVERGENCES**: List 2-5 specific disagreements (e.g., "Buffett accumulating financials while Burry is short the sector").

4. **KEY THEMES**: List 3-6 investment themes emerging from investor activity (e.g., "AI infrastructure spending", "Energy transition", "Defensive rotation").

5. **CONFIDENCE**: 0.0-1.0, your overall confidence in this analysis.
   - Higher (>0.7) when multiple data points confirm a signal
   - Lower (<0.5) when data is sparse or signals are mixed

## Output Format
Return your analysis as valid JSON:
{{
  "signals": [
    {{
      "signal_type": "accumulation",
      "symbols": ["AAPL", "MSFT", "GOOGL"],
      "investors": ["Warren Buffett", "Chase Coleman"],
      "direction": "bullish",
      "conviction": 0.80,
      "rationale": "Multiple top managers increasing large-cap tech positions in Q4 filings, suggesting institutional conviction in AI beneficiaries despite elevated valuations.",
      "alignment_with_macro": "aligned"
    }},
    {{
      "signal_type": "contrarian",
      "symbols": ["XOM", "CVX"],
      "investors": ["Michael Burry"],
      "direction": "bullish",
      "conviction": 0.65,
      "rationale": "Burry building energy positions while most growth-focused managers are underweight, a classic contrarian setup ahead of potential supply constraints.",
      "alignment_with_macro": "contrarian"
    }}
  ],
  "consensus_view": "The majority of tracked investors are maintaining or increasing technology exposure, particularly in AI-adjacent names. Defensive positioning remains minimal, suggesting institutional confidence in continued economic expansion.",
  "notable_divergences": [
    "Buffett accumulating cash and defensive names while Cathie Wood doubles down on high-growth tech",
    "Dalio hedging with gold exposure while Coleman remains fully risk-on in growth equities"
  ],
  "key_themes": [
    "AI infrastructure and semiconductor buildout",
    "Quality over speculation in tech allocation",
    "Selective energy positioning for supply thesis"
  ],
  "confidence": 0.72
}}

## Guidelines
- Be specific -- reference actual investor names, positions, and filing dates
- Explain WHY each signal matters, linking back to the investor's track record or style
- Contrarian signals from proven investors (Buffett, Burry, Klarman) carry extra weight
- Consider the macro context when assessing alignment -- a bullish tech signal in a risk-off regime is more notable
- Commentary sentiment should be cross-referenced with actual position changes when possible
- If data is sparse for some investors, note this and adjust confidence accordingly
"""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


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


def format_investor_context(
    investor_data: dict[str, Any],
    macro_dict: dict[str, Any],
) -> str:
    """Format investor data and macro context into the analysis prompt.

    Takes the combined intelligence dict (from InvestorFeedAdapter.get_all_intelligence)
    and macro context from MacroScanner, and structures them into the
    INVESTOR_SENTIMENT_PROMPT template.

    Args:
        investor_data: Dictionary with keys: positions, commentary, metadata.
            Produced by InvestorFeedAdapter.get_all_intelligence().
        macro_dict: Dictionary with macro scan results. Expected keys:
            - market_regime: str (e.g., "Risk-On", "Risk-Off")
            - regime_confidence: float
            - regime_evidence: list[str]
            - themes: list[dict] with name, direction, affected_sectors
            - actionable_implications: dict with sector_preferences, risk_posture
            - key_risks: list[dict]

    Returns:
        Complete prompt string ready for LLM consumption.
    """
    # Format investor positions
    investor_parts: list[str] = []

    positions = investor_data.get("positions", [])
    if positions:
        investor_parts.append("### Recent 13F Filings & Position Changes")
        for pos in positions:
            if isinstance(pos, dict):
                name = pos.get("investor_name", "Unknown")
                firm = pos.get("investor_firm", "Unknown")
                symbol = pos.get("symbol", "N/A")
                action = pos.get("action", "unknown")
                date = pos.get("reported_date", "")
                context = pos.get("context", "")
                confidence = pos.get("confidence", "medium")

                investor_parts.append(
                    f"- **{name}** ({firm}): {action.upper()} "
                    f"{symbol if symbol else '[see filing]'} "
                    f"(reported {date}, confidence: {confidence})"
                )
                if context:
                    investor_parts.append(f"  Context: {context}")
    else:
        investor_parts.append("### Recent 13F Filings & Position Changes")
        investor_parts.append("No recent position data available.")

    # Format commentary
    commentary = investor_data.get("commentary", [])
    if commentary:
        investor_parts.append("")
        investor_parts.append("### Investor Commentary & News")
        for comm in commentary:
            if isinstance(comm, dict):
                name = comm.get("investor_name", "Unknown")
                firm = comm.get("investor_firm", "Unknown")
                topic = comm.get("topic", "")
                sentiment = comm.get("sentiment", "neutral")
                date = comm.get("date", "")
                summary = comm.get("summary", "")
                symbols = comm.get("mentioned_symbols", [])

                investor_parts.append(
                    f"- **{name}** ({firm}) [{sentiment}] — {topic}"
                )
                if date:
                    investor_parts.append(f"  Date: {date}")
                if summary:
                    investor_parts.append(
                        f"  Summary: {summary[:300]}"
                    )
                if symbols:
                    investor_parts.append(
                        f"  Mentioned: {', '.join(symbols[:8])}"
                    )
    else:
        investor_parts.append("")
        investor_parts.append("### Investor Commentary & News")
        investor_parts.append("No recent commentary available.")

    # Add metadata
    metadata = investor_data.get("metadata", {})
    if metadata:
        investor_parts.append("")
        investor_parts.append("### Data Summary")
        investor_parts.append(
            f"- Investors tracked: {metadata.get('investor_count', 0)}"
        )
        investor_parts.append(
            f"- Investors with data: {metadata.get('investors_with_data', 0)}"
        )
        investor_parts.append(
            f"- Total positions: {metadata.get('total_positions', 0)}"
        )
        investor_parts.append(
            f"- Total commentary items: {metadata.get('total_commentary', 0)}"
        )
        unique_symbols = metadata.get("unique_symbols", [])
        if unique_symbols:
            investor_parts.append(
                f"- Unique symbols: {', '.join(unique_symbols[:20])}"
            )

    investor_formatted = "\n".join(investor_parts)

    # Format macro context into readable text
    macro_parts: list[str] = []

    regime = macro_dict.get("market_regime", "Unknown")
    regime_confidence = macro_dict.get("regime_confidence", 0.5)
    macro_parts.append(
        f"Market Regime: {regime} (confidence: {regime_confidence:.0%})"
    )

    # Regime evidence
    evidence = macro_dict.get("regime_evidence", [])
    if evidence:
        macro_parts.append("Evidence:")
        for e in evidence[:3]:
            macro_parts.append(f"  - {e}")

    # Active themes
    themes = macro_dict.get("themes", [])
    if themes:
        macro_parts.append("")
        macro_parts.append("Active Macro Themes:")
        for theme in themes[:3]:
            if isinstance(theme, dict):
                direction = theme.get("direction", "mixed")
                name = theme.get("name", "Unknown")
                confidence = theme.get("confidence", "medium")
                macro_parts.append(
                    f"  [{direction}] {name} ({confidence} confidence)"
                )
                affected = theme.get("affected_sectors", [])
                if affected:
                    macro_parts.append(
                        f"    Sectors: {', '.join(affected[:4])}"
                    )

    # Sector preferences
    implications = macro_dict.get("actionable_implications", {})
    if isinstance(implications, dict):
        sector_prefs = implications.get("sector_preferences", {})
        if isinstance(sector_prefs, dict):
            overweight = sector_prefs.get("overweight", [])
            underweight = sector_prefs.get("underweight", [])
            if overweight:
                macro_parts.append(
                    f"\nOverweight: {', '.join(overweight)}"
                )
            if underweight:
                macro_parts.append(
                    f"Underweight: {', '.join(underweight)}"
                )
        risk_posture = implications.get("risk_posture", "neutral")
        macro_parts.append(f"Risk Posture: {risk_posture}")

    # Key risks
    risks = macro_dict.get("key_risks", [])
    if risks:
        macro_parts.append("\nKey Risks:")
        for risk in risks[:2]:
            if isinstance(risk, dict):
                macro_parts.append(
                    f"  - {risk.get('description', 'Unknown')} "
                    f"({risk.get('probability', 'medium')} probability)"
                )

    macro_formatted = (
        "\n".join(macro_parts) if macro_parts
        else "No macro context available."
    )

    return INVESTOR_SENTIMENT_PROMPT.format(
        investor_context=investor_formatted,
        macro_context=macro_formatted,
    )


def parse_investor_response(response: str) -> InvestorIntelligenceResult:
    """Parse the investor sentiment LLM response into an InvestorIntelligenceResult.

    Extracts JSON from the LLM response, validates fields, and constructs
    an InvestorIntelligenceResult dataclass with defaults for any missing
    optional fields.

    Args:
        response: Raw LLM response text, which may contain JSON in code blocks,
            as raw JSON, or embedded within prose.

    Returns:
        InvestorIntelligenceResult dataclass instance with parsed data.
        On parse failure, returns a minimal result with the raw response
        captured in the consensus_view field.
    """
    json_data = _extract_json(response)

    if json_data is None:
        logger.warning("Could not extract JSON from investor sentiment response")
        return InvestorIntelligenceResult(
            consensus_view=f"Parse error. Raw response: {response[:500]}...",
            confidence=0.0,
        )

    try:
        # Validate and normalize signals
        raw_signals = json_data.get("signals", [])
        signals: list[InvestorSignal] = []
        for s in raw_signals:
            if isinstance(s, dict):
                signals.append(InvestorSignal.from_dict(s))

        # Clamp confidence
        confidence = float(json_data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        return InvestorIntelligenceResult(
            signals=signals,
            consensus_view=json_data.get("consensus_view", ""),
            notable_divergences=json_data.get("notable_divergences", []),
            key_themes=json_data.get("key_themes", []),
            confidence=confidence,
        )

    except (KeyError, TypeError, ValueError) as e:
        logger.error("Error parsing investor sentiment response: %s", e)
        return InvestorIntelligenceResult(
            consensus_view=f"Parse error: {e}",
            confidence=0.0,
        )


def format_investor_for_synthesis(result: InvestorIntelligenceResult) -> str:
    """Format investor intelligence result as markdown for synthesis context.

    Produces a readable markdown section summarizing the investor sentiment
    analysis, suitable for inclusion in the synthesis lead's context.

    Args:
        result: InvestorIntelligenceResult from parse_investor_response().

    Returns:
        Markdown-formatted string with investor intelligence summary.
    """
    parts: list[str] = []
    parts.append("## Institutional Investor Intelligence")
    parts.append(f"**Analysis Confidence**: {result.confidence:.0%}")
    parts.append("")

    # Consensus view
    if result.consensus_view:
        parts.append("### Consensus View")
        parts.append(result.consensus_view)
        parts.append("")

    # Key themes
    if result.key_themes:
        parts.append("### Key Investment Themes")
        for theme in result.key_themes:
            parts.append(f"- {theme}")
        parts.append("")

    # Notable divergences
    if result.notable_divergences:
        parts.append("### Notable Divergences")
        for divergence in result.notable_divergences:
            parts.append(f"- {divergence}")
        parts.append("")

    # Top signals
    if result.signals:
        parts.append("### Top Signals")
        # Sort by conviction descending
        sorted_signals = sorted(
            result.signals,
            key=lambda s: s.conviction,
            reverse=True,
        )
        for signal in sorted_signals[:6]:
            direction_icon = {
                "bullish": "UP",
                "bearish": "DOWN",
                "neutral": "FLAT",
            }.get(signal.direction, "FLAT")

            symbols_str = (
                ", ".join(signal.symbols[:5]) if signal.symbols else "N/A"
            )
            investors_str = (
                ", ".join(signal.investors[:3]) if signal.investors else "N/A"
            )

            parts.append(
                f"- **[{signal.signal_type.upper()}] {direction_icon}** "
                f"(conviction: {signal.conviction:.0%}, "
                f"macro: {signal.alignment_with_macro})"
            )
            parts.append(f"  Symbols: {symbols_str}")
            parts.append(f"  Investors: {investors_str}")
            if signal.rationale:
                parts.append(f"  Rationale: {signal.rationale[:200]}")
            parts.append("")

    if not result.signals and not result.consensus_view:
        parts.append("*No investor intelligence data available for this analysis.*")
        parts.append("")

    return "\n".join(parts)
