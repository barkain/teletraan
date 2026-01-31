"""Synthesis Lead agent for aggregating multi-analyst findings into actionable insights.

This module provides the LLM prompt and utility functions for the Synthesis Lead agent,
which combines findings from all specialist analysts (technical, macro, sector, risk,
correlation) into unified DeepInsight recommendations with conflict resolution and
confidence weighting.
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
# DATACLASSES
# =============================================================================


@dataclass
class SupportingEvidence:
    """Evidence from an individual analyst supporting an insight."""

    analyst: str  # technical, macro, sector, risk, correlation
    finding: str
    confidence: float
    data_points: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "analyst": self.analyst,
            "finding": self.finding,
            "confidence": round(self.confidence, 4),
            "data_points": self.data_points,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SupportingEvidence:
        """Create from dictionary."""
        return cls(
            analyst=data.get("analyst", "unknown"),
            finding=data.get("finding", ""),
            confidence=float(data.get("confidence", 0.5)),
            data_points=data.get("data_points", []),
        )


@dataclass
class DeepInsightData:
    """Structured data for a single deep insight."""

    insight_type: str  # opportunity, risk, rotation, macro, divergence, correlation
    action: str  # STRONG_BUY, BUY, HOLD, SELL, STRONG_SELL, WATCH
    title: str
    thesis: str
    primary_symbol: str | None = None
    related_symbols: list[str] = field(default_factory=list)
    supporting_evidence: list[SupportingEvidence] = field(default_factory=list)
    confidence: float = 0.5
    time_horizon: str = "medium_term"  # short_term, medium_term, long_term
    risk_factors: list[str] = field(default_factory=list)
    invalidation_trigger: str | None = None
    historical_precedent: str | None = None
    analysts_involved: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "insight_type": self.insight_type,
            "action": self.action,
            "title": self.title,
            "thesis": self.thesis,
            "primary_symbol": self.primary_symbol,
            "related_symbols": self.related_symbols,
            "supporting_evidence": [e.to_dict() for e in self.supporting_evidence],
            "confidence": round(self.confidence, 4),
            "time_horizon": self.time_horizon,
            "risk_factors": self.risk_factors,
            "invalidation_trigger": self.invalidation_trigger,
            "historical_precedent": self.historical_precedent,
            "analysts_involved": self.analysts_involved,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeepInsightData:
        """Create from dictionary."""
        evidence = []
        for e in data.get("supporting_evidence", []):
            if isinstance(e, dict):
                evidence.append(SupportingEvidence.from_dict(e))

        return cls(
            insight_type=data.get("insight_type", "opportunity"),
            action=data.get("action", "HOLD"),
            title=data.get("title", ""),
            thesis=data.get("thesis", ""),
            primary_symbol=data.get("primary_symbol"),
            related_symbols=data.get("related_symbols", []),
            supporting_evidence=evidence,
            confidence=float(data.get("confidence", 0.5)),
            time_horizon=data.get("time_horizon", "medium_term"),
            risk_factors=data.get("risk_factors", []),
            invalidation_trigger=data.get("invalidation_trigger"),
            historical_precedent=data.get("historical_precedent"),
            analysts_involved=data.get("analysts_involved", []),
        )


@dataclass
class SynthesisSummary:
    """Overall summary of the synthesis process."""

    total_analysts: int
    agreeing_analysts: int
    conflicting_signals: list[str] = field(default_factory=list)
    overall_market_bias: str = "neutral"  # bullish, bearish, neutral, mixed
    key_themes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "total_analysts": self.total_analysts,
            "agreeing_analysts": self.agreeing_analysts,
            "conflicting_signals": self.conflicting_signals,
            "overall_market_bias": self.overall_market_bias,
            "key_themes": self.key_themes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SynthesisSummary:
        """Create from dictionary."""
        return cls(
            total_analysts=int(data.get("total_analysts", 0)),
            agreeing_analysts=int(data.get("agreeing_analysts", 0)),
            conflicting_signals=data.get("conflicting_signals", []),
            overall_market_bias=data.get("overall_market_bias", "neutral"),
            key_themes=data.get("key_themes", []),
        )


@dataclass
class SynthesisResult:
    """Complete synthesis result from the Synthesis Lead agent."""

    analyst: str = "synthesis"
    insights: list[DeepInsightData] = field(default_factory=list)
    summary: SynthesisSummary | None = None
    synthesis_timestamp: datetime = field(default_factory=datetime.utcnow)
    raw_analyst_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "analyst": self.analyst,
            "insights": [i.to_dict() for i in self.insights],
            "summary": self.summary.to_dict() if self.summary else None,
            "synthesis_timestamp": self.synthesis_timestamp.isoformat(),
            "raw_analyst_count": self.raw_analyst_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SynthesisResult:
        """Create from dictionary."""
        insights = []
        for i in data.get("insights", []):
            if isinstance(i, dict):
                insights.append(DeepInsightData.from_dict(i))

        summary = None
        if data.get("summary"):
            summary = SynthesisSummary.from_dict(data["summary"])

        timestamp = data.get("synthesis_timestamp")
        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.utcnow()
        elif not isinstance(timestamp, datetime):
            timestamp = datetime.utcnow()

        return cls(
            analyst=data.get("analyst", "synthesis"),
            insights=insights,
            summary=summary,
            synthesis_timestamp=timestamp,
            raw_analyst_count=int(data.get("raw_analyst_count", 0)),
        )


# =============================================================================
# SYNTHESIS LEAD PROMPT
# =============================================================================

SYNTHESIS_LEAD_PROMPT = """You are the Synthesis Lead responsible for aggregating findings from multiple specialist market analysts into unified, actionable investment insights.

## Your Role
You receive analysis from 5 specialist analysts:
1. **Technical Analyst** - Chart patterns, indicators, support/resistance, price action
2. **Macro Economist** - Fed policy, yield curves, economic indicators, inflation/growth
3. **Sector Strategist** - Sector rotation, relative strength, business cycle positioning
4. **Risk Analyst** - Volatility, downside scenarios, position sizing, tail risks
5. **Correlation Detective** - Cross-asset relationships, divergences, historical patterns

## Your Task
Synthesize their findings to produce DeepInsight recommendations:

1. **Identify Convergent Signals** - Where do multiple analysts agree?
2. **Resolve Conflicts** - When analysts disagree, weigh evidence and explain resolution
3. **Generate Actionable Insights** - Create specific, tradeable recommendations
4. **Assess Confidence** - Weight individual analyst confidence into aggregate scores
5. **Highlight Key Risks** - Aggregate and prioritize risk factors

## Conflict Resolution Rules
- Technical + Macro alignment = HIGH confidence
- Technical conflicts with Macro = Favor Macro for >1 month horizons, Technical for <1 month
- Risk warnings override bullish signals if tail risk probability >15%
- Sector rotation > individual stock technical for portfolio positioning
- Correlation breakdowns require investigation before acting

## Output Format
Return JSON:
{
  "analyst": "synthesis",
  "insights": [
    {
      "insight_type": "opportunity",  // opportunity, risk, rotation, macro, divergence, correlation
      "action": "BUY",  // STRONG_BUY, BUY, HOLD, SELL, STRONG_SELL, WATCH
      "title": "Tech Sector Breakout with Macro Tailwinds",
      "thesis": "Technical breakout in XLK confirmed by declining yields and Fed pivot signals...",
      "primary_symbol": "XLK",
      "related_symbols": ["AAPL", "MSFT", "NVDA"],
      "supporting_evidence": [
        {"analyst": "technical", "finding": "Golden cross on daily chart", "confidence": 0.8, "data_points": ["SMA50 crossed SMA200"]},
        {"analyst": "macro", "finding": "Fed signaling rate cuts", "confidence": 0.7, "data_points": ["Dot plot median lower"]}
      ],
      "confidence": 0.75,
      "time_horizon": "medium_term",  // short_term (<1mo), medium_term (1-3mo), long_term (>3mo)
      "risk_factors": ["Earnings season volatility", "Geopolitical tensions"],
      "invalidation_trigger": "Close below 200-day SMA on high volume",
      "historical_precedent": "Similar setup in Oct 2023 led to 15% rally",
      "analysts_involved": ["technical", "macro", "sector"]
    }
  ],
  "summary": {
    "total_analysts": 5,
    "agreeing_analysts": 4,
    "conflicting_signals": ["Technical bullish but risk analyst warns of elevated VIX"],
    "overall_market_bias": "bullish",  // bullish, bearish, neutral, mixed
    "key_themes": ["Fed pivot", "Tech leadership", "Low volatility regime"]
  }
}

## Insight Types
- **opportunity**: Actionable trade setup with clear entry/exit
- **risk**: Warning about potential downside or hazard
- **rotation**: Sector or asset class rotation signal
- **macro**: Broad market theme driven by economic factors
- **divergence**: Unusual relationship breakdown worth monitoring
- **correlation**: Cross-asset relationship insight

## Action Levels
- **STRONG_BUY**: High conviction, multiple confirming signals, favorable risk/reward
- **BUY**: Positive setup with moderate confidence
- **HOLD**: Maintain position, no clear action signal
- **SELL**: Exit or reduce position
- **STRONG_SELL**: High conviction bearish, urgent action recommended
- **WATCH**: Interesting setup but needs confirmation

## Confidence Scoring
- 0.8-1.0: Multiple analysts agree with high individual confidence
- 0.6-0.8: Majority agreement or strong single-analyst signal with corroboration
- 0.4-0.6: Mixed signals, moderate conviction
- 0.2-0.4: Conflicting signals, low conviction
- 0.0-0.2: High uncertainty, insufficient data

## Guidelines
- Generate 3-7 insights per synthesis (quality over quantity)
- Always include at least one risk-focused insight
- Explain your reasoning in the thesis field
- Reference specific data points from analyst findings
- Prioritize actionable insights over observations
- Include clear invalidation triggers for all trade ideas
- Weight recent data more heavily than older signals
"""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def format_synthesis_context(analyst_reports: dict[str, Any]) -> str:
    """Format analyst reports for synthesis lead consumption.

    Takes the outputs from all specialist analysts and formats them into
    a structured string that the synthesis lead can analyze and aggregate.

    Args:
        analyst_reports: Dictionary mapping analyst names to their results.
            Expected keys: 'technical', 'macro', 'sector', 'risk', 'correlation'
            Each value should be a dict with the analyst's output format.

    Returns:
        Formatted string context for the synthesis lead prompt.
    """
    context_parts: list[str] = []
    context_parts.append("=" * 60)
    context_parts.append("MULTI-ANALYST MARKET ANALYSIS REPORT")
    context_parts.append("=" * 60)
    context_parts.append("")

    # Technical Analyst
    if "technical" in analyst_reports:
        context_parts.append(_format_technical_report(analyst_reports["technical"]))

    # Macro Economist
    if "macro" in analyst_reports:
        context_parts.append(_format_macro_report(analyst_reports["macro"]))

    # Sector Strategist
    if "sector" in analyst_reports:
        context_parts.append(_format_sector_report(analyst_reports["sector"]))

    # Risk Analyst
    if "risk" in analyst_reports:
        context_parts.append(_format_risk_report(analyst_reports["risk"]))

    # Correlation Detective
    if "correlation" in analyst_reports:
        context_parts.append(_format_correlation_report(analyst_reports["correlation"]))

    context_parts.append("")
    context_parts.append("=" * 60)
    context_parts.append("END OF ANALYST REPORTS")
    context_parts.append("=" * 60)

    return "\n".join(context_parts)


def _format_technical_report(data: dict[str, Any]) -> str:
    """Format technical analyst report section."""
    parts = [
        "",
        "-" * 40,
        "TECHNICAL ANALYST REPORT",
        "-" * 40,
    ]

    # Market structure
    if "market_structure" in data:
        parts.append(f"Market Structure: {data['market_structure']}")

    # Confidence
    confidence = data.get("confidence", 0)
    parts.append(f"Analyst Confidence: {confidence:.0%}")

    # Key observations
    observations = data.get("key_observations", [])
    if observations:
        parts.append("\nKey Observations:")
        for obs in observations[:5]:
            parts.append(f"  - {obs}")

    # Findings
    findings = data.get("findings", [])
    if findings:
        parts.append("\nTechnical Findings:")
        for f in findings[:5]:
            symbol = f.get("symbol", "N/A")
            signal = f.get("signal", "N/A")
            bias = f.get("action_bias", "NEUTRAL")
            conf = f.get("confidence", 0)
            desc = f.get("description", "")[:100]
            parts.append(f"  [{symbol}] {signal} - {bias} ({conf:.0%})")
            if desc:
                parts.append(f"    {desc}")

            # Key levels
            levels = f.get("key_levels", {})
            if levels.get("support") or levels.get("resistance"):
                support = levels.get("support", "N/A")
                resistance = levels.get("resistance", "N/A")
                parts.append(f"    S: ${support} | R: ${resistance}")

    # Conflicting signals
    conflicts = data.get("conflicting_signals", [])
    if conflicts:
        parts.append("\nConflicting Signals:")
        for c in conflicts[:3]:
            parts.append(f"  ! {c}")

    # Timeframes
    timeframes = data.get("timeframes_analyzed", [])
    if timeframes:
        parts.append(f"\nTimeframes: {', '.join(timeframes)}")

    parts.append("")
    return "\n".join(parts)


def _format_macro_report(data: dict[str, Any]) -> str:
    """Format macro economist report section."""
    parts = [
        "",
        "-" * 40,
        "MACRO ECONOMIST REPORT",
        "-" * 40,
    ]

    # Regime
    regime = data.get("regime", {})
    if regime:
        growth = regime.get("growth", "unknown")
        inflation = regime.get("inflation", "unknown")
        fed_stance = regime.get("fed_stance", "unknown")
        parts.append(f"Regime: Growth={growth}, Inflation={inflation}, Fed={fed_stance}")

    # Confidence
    confidence = data.get("confidence", 0)
    parts.append(f"Analyst Confidence: {confidence:.0%}")

    # Yield curve
    yc = data.get("yield_curve", {})
    if yc:
        shape = yc.get("shape", "unknown")
        signal = yc.get("signal", "unknown")
        spread = yc.get("spread_2y10y", 0)
        parts.append(f"\nYield Curve: {shape} ({signal}), 2Y/10Y spread: {spread:.2f}%")

    # Fed outlook
    fed_outlook = data.get("fed_outlook", "")
    if fed_outlook:
        parts.append(f"\nFed Outlook: {fed_outlook}")

    # Key indicators
    indicators = data.get("key_indicators", [])
    if indicators:
        parts.append("\nKey Indicators:")
        for ind in indicators[:5]:
            name = ind.get("indicator", "N/A")
            value = ind.get("value", "N/A")
            trend = ind.get("trend", "N/A")
            impl = ind.get("implication", "")[:80]
            parts.append(f"  - {name}: {value} ({trend})")
            if impl:
                parts.append(f"    {impl}")

    # Market implications
    implications = data.get("market_implications", [])
    if implications:
        parts.append("\nMarket Implications:")
        for impl in implications[:5]:
            asset = impl.get("asset_class", "N/A")
            bias = impl.get("bias", "N/A")
            rationale = impl.get("rationale", "")[:80]
            parts.append(f"  - {asset}: {bias}")
            if rationale:
                parts.append(f"    {rationale}")

    # Risk factors
    risks = data.get("risk_factors", [])
    if risks:
        parts.append("\nRisk Factors:")
        for r in risks[:3]:
            parts.append(f"  ! {r}")

    parts.append("")
    return "\n".join(parts)


def _format_sector_report(data: dict[str, Any]) -> str:
    """Format sector strategist report section."""
    parts = [
        "",
        "-" * 40,
        "SECTOR STRATEGIST REPORT",
        "-" * 40,
    ]

    # Market phase
    phase = data.get("market_phase", "unknown")
    phase_conf = data.get("phase_confidence", 0)
    parts.append(f"Market Phase: {phase.replace('_', ' ').title()} ({phase_conf:.0%} confidence)")

    # Confidence
    confidence = data.get("confidence", 0)
    parts.append(f"Analyst Confidence: {confidence:.0%}")

    # Sector rankings
    rankings = data.get("sector_rankings", [])
    if rankings:
        parts.append("\nSector Rankings (by Relative Strength):")
        for r in rankings[:8]:
            sector = r.get("sector", "N/A")
            rs = r.get("relative_strength", 1.0)
            trend = r.get("trend", "stable")
            parts.append(f"  - {sector}: RS={rs:.3f} ({trend})")

    # Recommendations
    recs = data.get("recommendations", [])
    if recs:
        parts.append("\nRecommendations:")
        for rec in recs[:5]:
            sector = rec.get("sector", "N/A")
            action = rec.get("action", "NEUTRAL")
            rationale = rec.get("rationale", "")[:80]
            parts.append(f"  - {sector}: {action}")
            if rationale:
                parts.append(f"    {rationale}")

    # Rotation signals
    signals = data.get("rotation_signals", [])
    if signals:
        parts.append("\nRotation Signals:")
        for s in signals[:3]:
            parts.append(f"  > {s}")

    # Key observations
    observations = data.get("key_observations", [])
    if observations:
        parts.append("\nKey Observations:")
        for obs in observations[:3]:
            parts.append(f"  - {obs}")

    parts.append("")
    return "\n".join(parts)


def _format_risk_report(data: dict[str, Any]) -> str:
    """Format risk analyst report section."""
    parts = [
        "",
        "-" * 40,
        "RISK ANALYST REPORT",
        "-" * 40,
    ]

    # Volatility regime
    vol = data.get("volatility_regime", {})
    if vol:
        vix = vol.get("current_vix", 0)
        regime = vol.get("regime", "unknown")
        term = vol.get("term_structure", "unknown")
        impl = vol.get("implication", "")[:80]
        parts.append(f"VIX: {vix:.1f} - Regime: {regime}, Term Structure: {term}")
        if impl:
            parts.append(f"  {impl}")

    # Confidence
    confidence = data.get("confidence", 0)
    parts.append(f"Analyst Confidence: {confidence:.0%}")

    # Risk assessments
    assessments = data.get("risk_assessments", [])
    if assessments:
        parts.append("\nRisk Assessments:")
        for ra in assessments[:5]:
            symbol = ra.get("symbol", "N/A")
            price = ra.get("current_price", 0)
            drawdown = ra.get("max_drawdown_pct", 0)
            rr = ra.get("risk_reward", 0)
            size = ra.get("position_size_suggestion", "N/A")
            stop = ra.get("stop_loss", 0)
            trigger = ra.get("invalidation_trigger", "")[:60]
            parts.append(f"  [{symbol}] @ ${price:.2f}")
            parts.append(f"    Max Drawdown: {drawdown:.1f}%, R/R: {rr:.1f}x")
            parts.append(f"    Position Size: {size}, Stop: ${stop:.2f}")
            if trigger:
                parts.append(f"    Invalidation: {trigger}")

    # Portfolio risks
    portfolio_risks = data.get("portfolio_risks", [])
    if portfolio_risks:
        parts.append("\nPortfolio Risks:")
        for pr in portfolio_risks[:3]:
            parts.append(f"  ! {pr}")

    # Tail risks
    tail_risks = data.get("tail_risks", [])
    if tail_risks:
        parts.append("\nTail Risks:")
        for tr in tail_risks[:3]:
            event = tr.get("event", "N/A")
            prob = tr.get("probability", 0)
            impact = tr.get("impact", "unknown")
            parts.append(f"  - {event}: {prob:.0%} probability, {impact} impact")

    # Key observations
    observations = data.get("key_observations", [])
    if observations:
        parts.append("\nKey Observations:")
        for obs in observations[:3]:
            parts.append(f"  - {obs}")

    parts.append("")
    return "\n".join(parts)


def _format_correlation_report(data: dict[str, Any]) -> str:
    """Format correlation detective report section."""
    parts = [
        "",
        "-" * 40,
        "CORRELATION DETECTIVE REPORT",
        "-" * 40,
    ]

    # Confidence
    confidence = data.get("confidence", 0)
    parts.append(f"Analyst Confidence: {confidence:.0%}")

    # Divergences
    divergences = data.get("divergences", [])
    if divergences:
        parts.append("\nDivergences Detected:")
        for d in divergences[:5]:
            dtype = d.get("type", "unknown")
            primary = d.get("primary", "N/A")
            secondary = d.get("secondary", "N/A")
            obs = d.get("observation", "")[:80]
            impl = d.get("implication", "neutral")
            hist = d.get("historical_significance", "")[:80]
            parts.append(f"  [{dtype}] {primary} vs {secondary}: {impl}")
            if obs:
                parts.append(f"    {obs}")
            if hist:
                parts.append(f"    Historical: {hist}")

    # Lead/lag signals
    lead_lag = data.get("lead_lag_signals", [])
    if lead_lag:
        parts.append("\nLead/Lag Signals:")
        for ll in lead_lag[:3]:
            leader = ll.get("leader", "N/A")
            lagger = ll.get("lagger", "N/A")
            signal = ll.get("signal", "")[:80]
            parts.append(f"  - {leader} leads {lagger}")
            if signal:
                parts.append(f"    {signal}")

    # Historical analogs
    analogs = data.get("historical_analogs", [])
    if analogs:
        parts.append("\nHistorical Analogs:")
        for a in analogs[:3]:
            period = a.get("period", "N/A")
            sim = a.get("similarity", 0)
            outcome = a.get("outcome", "")[:80]
            parts.append(f"  - {period} ({sim:.0%} similarity)")
            if outcome:
                parts.append(f"    Outcome: {outcome}")

    # Anomalies
    anomalies = data.get("anomalies", [])
    if anomalies:
        parts.append("\nAnomalies:")
        for a in anomalies[:3]:
            parts.append(f"  ! {a}")

    # Correlation shifts
    shifts = data.get("correlation_shifts", [])
    if shifts:
        parts.append("\nCorrelation Shifts:")
        for s in shifts[:3]:
            parts.append(f"  ~ {s}")

    # Key observations
    observations = data.get("key_observations", [])
    if observations:
        parts.append("\nKey Observations:")
        for obs in observations[:3]:
            parts.append(f"  - {obs}")

    parts.append("")
    return "\n".join(parts)


def parse_synthesis_response(response: str) -> list[dict[str, Any]]:
    """Parse the synthesis lead's response into a list of DeepInsight-compatible dicts.

    Extracts JSON from the agent's response and converts insights into a format
    suitable for creating DeepInsight database records.

    Args:
        response: Raw response string from the synthesis lead agent.

    Returns:
        List of dictionaries, each representing a DeepInsight record with keys:
        - insight_type, action, title, thesis, primary_symbol, related_symbols
        - supporting_evidence, confidence, time_horizon, risk_factors
        - invalidation_trigger, historical_precedent, analysts_involved
    """
    # Try to extract JSON from the response
    json_data = _extract_json(response)

    if json_data is None:
        logger.warning("Could not extract JSON from synthesis response")
        return []

    # Parse insights from the response
    insights = json_data.get("insights", [])
    result: list[dict[str, Any]] = []

    for insight in insights:
        if not isinstance(insight, dict):
            continue

        # Map to DeepInsight-compatible format
        parsed = {
            "insight_type": insight.get("insight_type", "opportunity"),
            "action": insight.get("action", "HOLD"),
            "title": insight.get("title", "Untitled Insight"),
            "thesis": insight.get("thesis", ""),
            "primary_symbol": insight.get("primary_symbol"),
            "related_symbols": insight.get("related_symbols", []),
            "supporting_evidence": insight.get("supporting_evidence", []),
            "confidence": float(insight.get("confidence", 0.5)),
            "time_horizon": insight.get("time_horizon", "medium_term"),
            "risk_factors": insight.get("risk_factors", []),
            "invalidation_trigger": insight.get("invalidation_trigger"),
            "historical_precedent": insight.get("historical_precedent"),
            "analysts_involved": insight.get("analysts_involved", []),
            "data_sources": _extract_data_sources(insight),
        }

        # Validate required fields
        if parsed["title"] and parsed["thesis"]:
            result.append(parsed)

    return result


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
    # Look for content between first { and last }
    start_idx = text.find("{")
    end_idx = text.rfind("}")

    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        potential_json = text[start_idx : end_idx + 1]
        try:
            return json.loads(potential_json)
        except json.JSONDecodeError:
            pass

    return None


def _extract_data_sources(insight: dict[str, Any]) -> list[str]:
    """Extract data sources from supporting evidence.

    Args:
        insight: Insight dictionary with supporting_evidence.

    Returns:
        List of unique data source identifiers.
    """
    sources: set[str] = set()

    evidence = insight.get("supporting_evidence", [])
    for e in evidence:
        if isinstance(e, dict):
            analyst = e.get("analyst", "")
            if analyst:
                sources.add(f"analyst:{analyst}")

            data_points = e.get("data_points", [])
            for dp in data_points:
                if isinstance(dp, str) and len(dp) < 50:
                    sources.add(f"data:{dp}")

    return sorted(sources)[:10]  # Limit to 10 sources


def aggregate_confidence(
    analyst_reports: dict[str, Any],
    weights: dict[str, float] | None = None,
) -> float:
    """Calculate weighted aggregate confidence from multiple analysts.

    Args:
        analyst_reports: Dictionary mapping analyst names to their results.
        weights: Optional weights for each analyst. Defaults to equal weights.

    Returns:
        Weighted average confidence score between 0.0 and 1.0.
    """
    default_weights = {
        "technical": 0.25,
        "macro": 0.20,
        "sector": 0.20,
        "risk": 0.20,
        "correlation": 0.15,
    }
    weights = weights or default_weights

    total_weight = 0.0
    weighted_sum = 0.0

    for analyst, report in analyst_reports.items():
        if not isinstance(report, dict):
            continue

        confidence = report.get("confidence", 0.5)
        if isinstance(confidence, (int, float)):
            weight = weights.get(analyst, 0.2)
            weighted_sum += confidence * weight
            total_weight += weight

    if total_weight == 0:
        return 0.5

    return min(max(weighted_sum / total_weight, 0.0), 1.0)


def count_agreeing_analysts(analyst_reports: dict[str, Any]) -> tuple[int, int]:
    """Count how many analysts have agreeing signals.

    Args:
        analyst_reports: Dictionary mapping analyst names to their results.

    Returns:
        Tuple of (agreeing_count, total_count).
    """
    total = 0
    bullish = 0
    bearish = 0

    for analyst, report in analyst_reports.items():
        if not isinstance(report, dict):
            continue

        total += 1
        bias = _extract_bias(report, analyst)

        if bias == "bullish":
            bullish += 1
        elif bias == "bearish":
            bearish += 1

    # Agreement is the count of the majority direction
    agreeing = max(bullish, bearish)
    return agreeing, total


def _extract_bias(report: dict[str, Any], analyst: str) -> str:
    """Extract overall bias from an analyst report.

    Args:
        report: Analyst report dictionary.
        analyst: Name of the analyst.

    Returns:
        Bias string: 'bullish', 'bearish', or 'neutral'.
    """
    if analyst == "technical":
        # Look at action_bias in findings
        findings = report.get("findings", [])
        buy_count = sum(
            1 for f in findings if f.get("action_bias") in ("BUY", "STRONG_BUY")
        )
        sell_count = sum(
            1 for f in findings if f.get("action_bias") in ("SELL", "STRONG_SELL")
        )
        if buy_count > sell_count:
            return "bullish"
        elif sell_count > buy_count:
            return "bearish"
        return "neutral"

    elif analyst == "macro":
        # Look at regime and market implications
        implications = report.get("market_implications", [])
        positive = sum(1 for i in implications if i.get("bias") == "positive")
        negative = sum(1 for i in implications if i.get("bias") == "negative")
        if positive > negative:
            return "bullish"
        elif negative > positive:
            return "bearish"
        return "neutral"

    elif analyst == "sector":
        # Look at recommendations
        recs = report.get("recommendations", [])
        overweight = sum(1 for r in recs if r.get("action") == "OVERWEIGHT")
        underweight = sum(1 for r in recs if r.get("action") == "UNDERWEIGHT")
        if overweight > underweight:
            return "bullish"
        elif underweight > overweight:
            return "bearish"
        return "neutral"

    elif analyst == "risk":
        # Risk analyst: high VIX or many tail risks = bearish
        vol = report.get("volatility_regime", {})
        vix = vol.get("current_vix", 20)
        regime = vol.get("regime", "normal")
        if regime in ("elevated", "crisis") or vix > 25:
            return "bearish"
        elif regime == "low_vol" and vix < 15:
            return "bullish"
        return "neutral"

    elif analyst == "correlation":
        # Look at divergence implications
        divergences = report.get("divergences", [])
        bullish = sum(
            1 for d in divergences if d.get("implication") == "bullish_for_primary"
        )
        bearish = sum(
            1 for d in divergences if d.get("implication") == "bearish_for_primary"
        )
        if bullish > bearish:
            return "bullish"
        elif bearish > bullish:
            return "bearish"
        return "neutral"

    return "neutral"
