"""Synthesis Lead agent for aggregating multi-analyst findings into actionable insights.

This module provides the LLM prompt and utility functions for the Synthesis Lead agent,
which combines findings from all specialist analysts (technical, macro, sector, risk,
correlation) into unified DeepInsight recommendations with conflict resolution and
confidence weighting.

Also includes the synthesize_autonomous method for handling autonomous analysis flows
with proper entry/stop/target levels.
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

## Alternative Data Alignment Check
When prediction market and/or sentiment data is available, include an alignment assessment:

**Prediction Market Alignment:** Do the prediction market probabilities support or contradict the macro thesis? Flag any significant divergences.

**Social Sentiment Alignment:** Does retail investor sentiment align with the analytical thesis?
- If thesis is bullish AND sentiment is bearish -> potential contrarian opportunity (highlight)
- If thesis is bearish AND sentiment is bullish -> potential risk (crowd may be wrong, or you may be)
- Strong alignment -> higher conviction, but watch for crowded trade risk

Include a brief "Alternative Data Summary" in your synthesis noting the alignment/divergence of these signals.

## Guidelines
- Generate 3-7 insights per synthesis (quality over quantity)
- Always include at least one risk-focused insight
- Explain your reasoning in the thesis field
- Reference specific data points from analyst findings
- Prioritize actionable insights over observations
- Include clear invalidation triggers for all trade ideas
- Weight recent data more heavily than older signals

## Validated Historical Patterns
When synthesizing, consider these historically validated patterns that may apply:

{pattern_context}

Weight your confidence based on:
- Pattern match quality (do current conditions match triggers?)
- Historical success rate
- Number of occurrences (more data = more reliable)

## Historical Track Record
Our previous insights have shown the following accuracy:

{track_record_context}

Adjust your confidence levels accordingly:
- If we've been accurate on similar calls, be more confident
- If track record is weak for this type, be more conservative

## Pattern Identification
If you identify any NEW repeatable patterns in this analysis:
- Describe the pattern clearly
- Specify measurable trigger conditions
- Explain expected outcome
- Estimate confidence based on evidence

These will be added to our pattern library for future reference.

Add any new patterns to the output JSON in a "new_patterns" array:
```json
{{
  "analyst": "synthesis",
  "insights": [...],
  "summary": {{...}},
  "new_patterns": [
    {{
      "pattern_name": "Short descriptive name",
      "pattern_type": "TECHNICAL_SETUP",  // TECHNICAL_SETUP, MACRO_CORRELATION, SECTOR_ROTATION, EARNINGS_PATTERN, SEASONALITY, CROSS_ASSET
      "trigger_conditions": {{
        "condition_key": "measurable_value"
      }},
      "expected_outcome": "What typically happens when triggered",
      "confidence": 0.6,
      "description": "Full description of the pattern"
    }}
  ]
}}
```
"""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert a value to float for formatting.

    Args:
        value: Value to convert (may be int, float, str, or None).
        default: Default value if conversion fails.

    Returns:
        Float value safe for percentage/decimal formatting.
    """
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


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

    # Prediction market data (optional)
    predictions = analyst_reports.get("predictions")
    if predictions:
        from analysis.context_builder import format_prediction_context  # type: ignore[import-not-found]

        prediction_text = format_prediction_context(predictions)
        if prediction_text:
            context_parts.append("")
            context_parts.append(prediction_text)

    # Reddit sentiment data (optional)
    sentiment = analyst_reports.get("sentiment")
    if sentiment:
        from analysis.context_builder import format_sentiment_context  # type: ignore[import-not-found]

        sentiment_text = format_sentiment_context(sentiment)
        if sentiment_text:
            context_parts.append("")
            context_parts.append(sentiment_text)

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
    confidence = _safe_float(data.get("confidence", 0))
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
            conf = _safe_float(f.get("confidence", 0))
            desc = str(f.get("description", ""))[:100]
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
    confidence = _safe_float(data.get("confidence", 0))
    parts.append(f"Analyst Confidence: {confidence:.0%}")

    # Yield curve
    yc = data.get("yield_curve", {})
    if yc:
        shape = yc.get("shape", "unknown")
        signal = yc.get("signal", "unknown")
        spread = _safe_float(yc.get("spread_2y10y", 0))
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
    phase = str(data.get("market_phase", "unknown"))
    phase_conf = _safe_float(data.get("phase_confidence", 0))
    parts.append(f"Market Phase: {phase.replace('_', ' ').title()} ({phase_conf:.0%} confidence)")

    # Confidence
    confidence = _safe_float(data.get("confidence", 0))
    parts.append(f"Analyst Confidence: {confidence:.0%}")

    # Sector rankings
    rankings = data.get("sector_rankings", [])
    if rankings:
        parts.append("\nSector Rankings (by Relative Strength):")
        for r in rankings[:8]:
            sector = r.get("sector", "N/A")
            rs = _safe_float(r.get("relative_strength", 1.0), 1.0)
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
        vix = _safe_float(vol.get("current_vix", 0))
        regime = vol.get("regime", "unknown")
        term = vol.get("term_structure", "unknown")
        impl = str(vol.get("implication", ""))[:80]
        parts.append(f"VIX: {vix:.1f} - Regime: {regime}, Term Structure: {term}")
        if impl:
            parts.append(f"  {impl}")

    # Confidence
    confidence = _safe_float(data.get("confidence", 0))
    parts.append(f"Analyst Confidence: {confidence:.0%}")

    # Risk assessments
    assessments = data.get("risk_assessments", [])
    if assessments:
        parts.append("\nRisk Assessments:")
        for ra in assessments[:5]:
            symbol = ra.get("symbol", "N/A")
            price = _safe_float(ra.get("current_price", 0))
            drawdown = _safe_float(ra.get("max_drawdown_pct", 0))
            rr = _safe_float(ra.get("risk_reward", 0))
            size = ra.get("position_size_suggestion", "N/A")
            stop = _safe_float(ra.get("stop_loss", 0))
            trigger = str(ra.get("invalidation_trigger", ""))[:60]
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
            prob = _safe_float(tr.get("probability", 0))
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
    confidence = _safe_float(data.get("confidence", 0))
    parts.append(f"Analyst Confidence: {confidence:.0%}")

    # Divergences
    divergences = data.get("divergences", [])
    if divergences:
        parts.append("\nDivergences Detected:")
        for d in divergences[:5]:
            dtype = d.get("type", "unknown")
            primary = d.get("primary", "N/A")
            secondary = d.get("secondary", "N/A")
            obs = str(d.get("observation", ""))[:80]
            impl = d.get("implication", "neutral")
            hist = str(d.get("historical_significance", ""))[:80]
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
            signal = str(ll.get("signal", ""))[:80]
            parts.append(f"  - {leader} leads {lagger}")
            if signal:
                parts.append(f"    {signal}")

    # Historical analogs
    analogs = data.get("historical_analogs", [])
    if analogs:
        parts.append("\nHistorical Analogs:")
        for a in analogs[:3]:
            period = a.get("period", "N/A")
            sim = _safe_float(a.get("similarity", 0))
            outcome = str(a.get("outcome", ""))[:80]
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


@dataclass
class SynthesisParseResult:
    """Result of parsing a synthesis response."""

    insights: list[dict[str, Any]] = field(default_factory=list)
    new_patterns: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] | None = None


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
    result = parse_synthesis_response_full(response)
    return result.insights


def parse_synthesis_response_full(response: str) -> SynthesisParseResult:
    """Parse the synthesis lead's response including new patterns.

    Extracts JSON from the agent's response and converts both insights and
    newly identified patterns into structured formats.

    Args:
        response: Raw response string from the synthesis lead agent.

    Returns:
        SynthesisParseResult containing:
        - insights: List of DeepInsight-compatible dictionaries
        - new_patterns: List of pattern dictionaries for PatternExtractor
        - summary: Optional synthesis summary dictionary
    """
    # Try to extract JSON from the response
    json_data = _extract_json(response)

    if json_data is None:
        logger.warning("Could not extract JSON from synthesis response")
        return SynthesisParseResult()

    result = SynthesisParseResult()

    # Parse insights from the response
    insights = json_data.get("insights", [])

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
            result.insights.append(parsed)

    # Parse new patterns if present
    new_patterns = json_data.get("new_patterns", [])
    result.new_patterns = _parse_new_patterns(new_patterns)

    # Parse summary if present
    if json_data.get("summary"):
        result.summary = json_data["summary"]

    logger.info(
        f"Parsed {len(result.insights)} insights and "
        f"{len(result.new_patterns)} new patterns from synthesis response"
    )

    return result


def _parse_new_patterns(patterns_data: list[Any]) -> list[dict[str, Any]]:
    """Parse and validate new patterns from synthesis response.

    Validates that each pattern has required fields and proper structure
    for use with PatternExtractor.

    Args:
        patterns_data: Raw patterns list from JSON response.

    Returns:
        List of validated pattern dictionaries ready for PatternExtractor.
    """
    valid_patterns: list[dict[str, Any]] = []

    valid_pattern_types = {
        "TECHNICAL_SETUP",
        "MACRO_CORRELATION",
        "SECTOR_ROTATION",
        "EARNINGS_PATTERN",
        "SEASONALITY",
        "CROSS_ASSET",
    }

    for pattern in patterns_data:
        if not isinstance(pattern, dict):
            continue

        # Validate required fields
        pattern_name = pattern.get("pattern_name", "").strip()
        if not pattern_name:
            logger.debug("Skipping pattern without name")
            continue

        trigger_conditions = pattern.get("trigger_conditions", {})
        if not trigger_conditions or not isinstance(trigger_conditions, dict):
            logger.debug(f"Skipping pattern '{pattern_name}' without trigger conditions")
            continue

        expected_outcome = pattern.get("expected_outcome", "").strip()
        if not expected_outcome or len(expected_outcome) < 10:
            logger.debug(f"Skipping pattern '{pattern_name}' without valid outcome")
            continue

        # Validate and normalize pattern type
        pattern_type = pattern.get("pattern_type", "TECHNICAL_SETUP").upper()
        if pattern_type not in valid_pattern_types:
            pattern_type = "TECHNICAL_SETUP"

        # Build validated pattern dict
        validated = {
            "pattern_name": pattern_name[:200],
            "pattern_type": pattern_type,
            "trigger_conditions": trigger_conditions,
            "expected_outcome": expected_outcome,
            "confidence": float(pattern.get("confidence", 0.5)),
            "description": pattern.get("description", expected_outcome),
            "success_rate": 0.5,  # Neutral prior for new patterns
            "occurrences": 1,
        }

        valid_patterns.append(validated)
        logger.debug(f"Validated new pattern: {pattern_name}")

    return valid_patterns


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


def build_pattern_context(patterns: list[Any]) -> str:
    """Build pattern context string for inclusion in synthesis prompt.

    Formats a list of KnowledgePattern objects into a readable string
    that provides the synthesis lead with historical pattern information
    to consider when generating insights.

    Args:
        patterns: List of KnowledgePattern objects with validated patterns.

    Returns:
        Formatted string describing patterns, or default message if no patterns.
    """
    if not patterns:
        return "No validated patterns available for current market conditions."

    parts: list[str] = []

    for i, pattern in enumerate(patterns, 1):
        # Handle both dict-like and object access patterns
        if isinstance(pattern, dict):
            name = pattern.get("pattern_name", "Unknown Pattern")
            pattern_type = pattern.get("pattern_type", "UNKNOWN")
            success_rate = pattern.get("success_rate", 0.0)
            occurrences = pattern.get("occurrences", 0)
            trigger_conditions = pattern.get("trigger_conditions", {})
            expected_outcome = pattern.get("expected_outcome", "")
            avg_return = pattern.get("avg_return_when_triggered")
        else:
            name = getattr(pattern, "pattern_name", "Unknown Pattern")
            pattern_type = getattr(pattern, "pattern_type", "UNKNOWN")
            success_rate = getattr(pattern, "success_rate", 0.0)
            occurrences = getattr(pattern, "occurrences", 0)
            trigger_conditions = getattr(pattern, "trigger_conditions", {})
            expected_outcome = getattr(pattern, "expected_outcome", "")
            avg_return = getattr(pattern, "avg_return_when_triggered", None)

        parts.append(f"{i}. **{name}** ({pattern_type})")
        parts.append(f"   - Success Rate: {success_rate:.0%} over {occurrences} occurrences")

        if avg_return is not None:
            parts.append(f"   - Avg Return: {avg_return:+.1f}%")

        # Format trigger conditions
        if trigger_conditions:
            conditions_str = ", ".join(
                f"{k}={v}" for k, v in trigger_conditions.items()
            )
            parts.append(f"   - Triggers: {conditions_str}")

        if expected_outcome:
            outcome_preview = expected_outcome[:100]
            if len(expected_outcome) > 100:
                outcome_preview += "..."
            parts.append(f"   - Expected: {outcome_preview}")

        parts.append("")

    return "\n".join(parts)


def build_track_record_context(track_record: dict[str, Any]) -> str:
    """Build track record context string for inclusion in synthesis prompt.

    Formats insight track record statistics into a readable string
    that helps the synthesis lead calibrate confidence levels.

    Args:
        track_record: Dictionary with track record statistics from
            InstitutionalMemoryService.get_insight_track_record().

    Returns:
        Formatted string describing track record, or default message if empty.
    """
    if not track_record:
        return "No historical track record available yet."

    total = track_record.get("total_insights", 0)
    if total == 0:
        return "No validated insights to establish track record yet."

    parts: list[str] = []

    # Overall stats
    successful = track_record.get("successful", 0)
    success_rate = track_record.get("success_rate", 0.0)

    parts.append(f"**Overall:** {successful}/{total} insights validated successfully ({success_rate:.0%})")
    parts.append("")

    # Breakdown by insight type
    by_type = track_record.get("by_insight_type", {})
    if by_type:
        parts.append("**By Insight Type:**")
        for insight_type, stats in by_type.items():
            type_total = stats.get("total", 0)
            type_rate = stats.get("success_rate", 0.0)
            parts.append(f"  - {insight_type}: {type_rate:.0%} ({type_total} insights)")
        parts.append("")

    # Breakdown by action type
    by_action = track_record.get("by_action_type", {})
    if by_action:
        parts.append("**By Action Type:**")
        for action_type, stats in by_action.items():
            action_total = stats.get("total", 0)
            action_rate = stats.get("success_rate", 0.0)
            parts.append(f"  - {action_type}: {action_rate:.0%} ({action_total} insights)")
        parts.append("")

    return "\n".join(parts)


def format_synthesis_prompt_with_context(
    pattern_context: str | None = None,
    track_record_context: str | None = None,
) -> str:
    """Format the synthesis lead prompt with pattern and track record context.

    Substitutes the placeholders in SYNTHESIS_LEAD_PROMPT with actual
    context from institutional memory.

    Args:
        pattern_context: Formatted pattern context string, or None for default.
        track_record_context: Formatted track record string, or None for default.

    Returns:
        Complete synthesis prompt with context filled in.
    """
    prompt = SYNTHESIS_LEAD_PROMPT

    # Replace pattern context placeholder
    if pattern_context:
        prompt = prompt.replace("{pattern_context}", pattern_context)
    else:
        prompt = prompt.replace(
            "{pattern_context}",
            "No validated patterns available for current market conditions."
        )

    # Replace track record context placeholder
    if track_record_context:
        prompt = prompt.replace("{track_record_context}", track_record_context)
    else:
        prompt = prompt.replace(
            "{track_record_context}",
            "No historical track record available yet."
        )

    return prompt


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


# =============================================================================
# AUTONOMOUS SYNTHESIS FUNCTIONS
# =============================================================================


AUTONOMOUS_SYNTHESIS_PROMPT = """You are the Lead Investment Strategist synthesizing autonomous market analysis.

## Discovery Context

### Market Regime: {market_regime}
Evidence: {regime_evidence}

### Key Macro Themes:
{macro_themes}

### Sector Signals:
Top Sectors: {top_sectors}
Sectors to Avoid: {sectors_to_avoid}
Rotation: {rotation_from} -> {rotation_to}

### Discovered Opportunities:
{candidates}

## Analyst Reports by Symbol:
{analyst_reports}

## Your Task:

Produce {max_insights} HIGH-CONVICTION investment insights. For each:

1. **SYMBOL**: Ticker symbol
2. **ACTION**: BUY / SELL / HOLD / WATCH
3. **TITLE**: Compelling, specific headline (not generic)
4. **THESIS**: 2-3 sentences explaining WHY this is a compelling opportunity NOW
5. **ENTRY ZONE**: Price range for entry (e.g., "$150-155")
6. **TARGET PRICE**: Price target with timeframe (e.g., "$180 within 3 months")
7. **STOP LOSS**: Risk management level (e.g., "$142 (-5%)")
8. **TIMEFRAME**: swing (1-4 weeks) / position (1-3 months) / long-term (3+ months)
9. **CONFIDENCE**: 0.0-1.0 (be calibrated, not overconfident)
10. **KEY RISKS**: Top 2 risks to this thesis
11. **ALIGNMENT SCORE**: How well does this align with macro/sector themes? (1-10)

### Selection Criteria:
- Prioritize opportunities that ALIGN with macro themes and sector rotation
- Favor setups with clear risk/reward (minimum 2:1)
- Include mix of opportunity types if possible
- Higher confidence for sector leaders in hot sectors
- Lower confidence for contrarian plays

### Quality Requirements:
- Entry zone should be specific, not vague
- Target should be achievable within stated timeframe
- Stop loss should be at logical technical level
- Thesis should connect the dots (macro -> sector -> stock)

Respond in JSON format:
{{
    "insights": [
        {{
            "symbol": "NVDA",
            "action": "BUY",
            "title": "AI Capex Cycle Beneficiary as Cloud Giants Accelerate Spend",
            "thesis": "NVIDIA continues to dominate AI training infrastructure...",
            "entry_zone": "$850-880",
            "target_price": "$1000",
            "stop_loss": "$800",
            "timeframe": "position",
            "confidence": 0.78,
            "key_risks": ["Valuation stretched at 35x forward", "China revenue exposure"],
            "alignment_score": 9
        }}
    ],
    "market_summary": "Brief summary of overall market view",
    "top_theme": "The single most important theme driving opportunities"
}}
"""


def build_autonomous_synthesis_prompt(
    analyst_reports: dict[str, dict[str, Any]],
    macro_context: Any,
    sector_context: Any,
    candidates: Any,
    max_insights: int = 5,
) -> str:
    """Build the LLM prompt for autonomous synthesis with entry/stop/target levels.

    Args:
        analyst_reports: Dict mapping symbol -> {analyst_name: report}.
        macro_context: MacroScanResult with market regime and themes.
        sector_context: SectorRotationResult with sector signals.
        candidates: OpportunityList with discovered opportunities.
        max_insights: Maximum insights to produce.

    Returns:
        Formatted prompt string for LLM.
    """
    # Format macro themes
    macro_themes_str = _format_macro_themes_for_autonomous(macro_context)

    # Format sector signals
    top_sectors_list = []
    sectors_to_avoid_list = []

    if hasattr(sector_context, "top_sectors"):
        top_sectors_list = [s.sector_name for s in sector_context.top_sectors]
    if hasattr(sector_context, "sectors_to_avoid"):
        sectors_to_avoid_list = [s.sector_name for s in sector_context.sectors_to_avoid]

    rotation_from = ""
    rotation_to = ""
    if hasattr(sector_context, "rotation_from"):
        rotation_from = ", ".join(sector_context.rotation_from) if sector_context.rotation_from else "N/A"
    if hasattr(sector_context, "rotation_to"):
        rotation_to = ", ".join(sector_context.rotation_to) if sector_context.rotation_to else "N/A"

    # Format candidates
    candidates_str = _format_candidates_for_autonomous(candidates)

    # Format analyst reports
    analyst_reports_str = _format_analyst_reports_for_autonomous(analyst_reports)

    # Get regime evidence
    regime_evidence = ""
    if hasattr(macro_context, "regime_evidence"):
        if isinstance(macro_context.regime_evidence, list):
            regime_evidence = "; ".join(macro_context.regime_evidence[:3])
        else:
            regime_evidence = str(macro_context.regime_evidence)

    market_regime = getattr(macro_context, "market_regime", "unknown")

    return AUTONOMOUS_SYNTHESIS_PROMPT.format(
        market_regime=market_regime,
        regime_evidence=regime_evidence,
        macro_themes=macro_themes_str,
        top_sectors=", ".join(top_sectors_list) if top_sectors_list else "N/A",
        sectors_to_avoid=", ".join(sectors_to_avoid_list) if sectors_to_avoid_list else "N/A",
        rotation_from=rotation_from,
        rotation_to=rotation_to,
        candidates=candidates_str,
        analyst_reports=analyst_reports_str,
        max_insights=max_insights,
    )


def _format_macro_themes_for_autonomous(macro_context: Any) -> str:
    """Format macro themes for autonomous synthesis prompt.

    Args:
        macro_context: MacroScanResult with themes.

    Returns:
        Formatted string of macro themes.
    """
    if not hasattr(macro_context, "themes") or not macro_context.themes:
        return "No macro themes available."

    lines = []
    for theme in macro_context.themes[:5]:
        name = getattr(theme, "name", "Unknown")
        direction = getattr(theme, "direction", "neutral")
        rationale = getattr(theme, "rationale", "")[:150]
        lines.append(f"- {name} ({direction}): {rationale}")

    return "\n".join(lines)


def _format_candidates_for_autonomous(candidates: Any) -> str:
    """Format opportunity candidates for autonomous synthesis prompt.

    Args:
        candidates: OpportunityList with discovered opportunities.

    Returns:
        Formatted string of candidates.
    """
    if not hasattr(candidates, "candidates") or not candidates.candidates:
        return "No candidates discovered."

    lines = []
    for c in candidates.candidates[:15]:
        symbol = getattr(c, "symbol", "N/A")
        opp_type = getattr(c, "opportunity_type", "unknown")
        thesis = getattr(c, "thesis", "")[:100]
        confidence = getattr(c, "confidence", 0.5)
        sector = getattr(c, "sector", "Unknown")

        lines.append(
            f"- {symbol} ({sector}): {opp_type} | Confidence: {confidence:.0%}"
        )
        if thesis:
            lines.append(f"  Thesis: {thesis}...")

    return "\n".join(lines)


def _format_analyst_reports_for_autonomous(
    analyst_reports: dict[str, dict[str, Any]]
) -> str:
    """Format per-symbol analyst reports for autonomous synthesis prompt.

    Args:
        analyst_reports: Dict mapping symbol -> {analyst_name: report}.

    Returns:
        Formatted string of analyst reports by symbol.
    """
    if not analyst_reports:
        return "No analyst reports available."

    lines = []
    for symbol, reports in analyst_reports.items():
        lines.append(f"\n### {symbol}")

        for analyst_name, report in reports.items():
            if "error" in report:
                lines.append(f"  {analyst_name}: Error - {report['error']}")
                continue

            confidence = report.get("confidence", 0.5)
            lines.append(f"  **{analyst_name}** (Confidence: {confidence:.0%})")

            # Extract key findings based on analyst type
            if analyst_name == "technical":
                findings = report.get("findings", [])
                for f in findings[:2]:
                    signal = f.get("signal", "N/A")
                    bias = f.get("action_bias", "NEUTRAL")
                    lines.append(f"    - {signal}: {bias}")

            elif analyst_name == "risk":
                assessments = report.get("risk_assessments", [])
                for a in assessments[:2]:
                    rr = a.get("risk_reward", 0)
                    stop = a.get("stop_loss", 0)
                    lines.append(f"    - R/R: {rr:.1f}x, Stop: ${stop:.2f}")

            elif analyst_name == "macro":
                implications = report.get("market_implications", [])
                for i in implications[:2]:
                    asset = i.get("asset_class", "N/A")
                    bias = i.get("bias", "neutral")
                    lines.append(f"    - {asset}: {bias}")

    return "\n".join(lines)


def parse_autonomous_insights(
    response: str,
    max_insights: int,
) -> list[dict[str, Any]]:
    """Parse LLM response into structured insights with entry/stop/target.

    Args:
        response: Raw LLM response string.
        max_insights: Maximum insights to return.

    Returns:
        List of insight dictionaries with trading levels.
    """
    # Try to extract JSON
    json_data = _extract_json(response)

    if json_data is None:
        logger.warning("Could not extract JSON from autonomous synthesis response")
        return _extract_insights_from_text(response, max_insights)

    insights = json_data.get("insights", [])[:max_insights]

    # Required fields for validation
    required_fields = ["symbol", "action", "title", "thesis", "confidence"]

    validated: list[dict[str, Any]] = []
    for insight in insights:
        if not isinstance(insight, dict):
            continue

        # Check required fields
        if not all(field in insight for field in required_fields):
            logger.debug(f"Skipping insight missing required fields: {insight.get('symbol', 'N/A')}")
            continue

        # Normalize and validate
        parsed = {
            "symbol": insight.get("symbol", "").upper(),
            "action": _normalize_action(insight.get("action", "HOLD")),
            "title": insight.get("title", "Untitled")[:200],
            "thesis": insight.get("thesis", ""),
            "confidence": _clamp_confidence(insight.get("confidence", 0.5)),
            # Trading levels (new fields)
            "entry_zone": insight.get("entry_zone"),
            "target_price": insight.get("target_price"),
            "stop_loss": insight.get("stop_loss"),
            "timeframe": _normalize_timeframe(insight.get("timeframe", "position")),
            # Additional fields
            "key_risks": insight.get("key_risks", [])[:5],
            "alignment_score": _clamp_alignment(insight.get("alignment_score", 5)),
            # Map to standard insight fields
            "insight_type": "opportunity",
            "time_horizon": _timeframe_to_horizon(insight.get("timeframe", "position")),
            "primary_symbol": insight.get("symbol", "").upper(),
            "related_symbols": [],
            "risk_factors": insight.get("key_risks", [])[:5],
            "analysts_involved": ["technical", "macro", "sector", "risk", "correlation"],
        }

        validated.append(parsed)

    # Also extract market summary if available
    market_summary = json_data.get("market_summary", "")
    top_theme = json_data.get("top_theme", "")

    if market_summary or top_theme:
        logger.info(f"Market summary: {market_summary[:100]}...")
        logger.info(f"Top theme: {top_theme}")

    return validated


def _normalize_action(action: str) -> str:
    """Normalize action string to valid InsightAction value.

    Args:
        action: Raw action string.

    Returns:
        Normalized action string.
    """
    action = action.upper().strip()
    valid_actions = {"STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL", "WATCH"}

    if action in valid_actions:
        return action

    # Map common variations
    if action in {"LONG", "BULLISH"}:
        return "BUY"
    elif action in {"SHORT", "BEARISH"}:
        return "SELL"
    elif action in {"MONITOR", "WATCHING"}:
        return "WATCH"

    return "HOLD"


def _normalize_timeframe(timeframe: str) -> str:
    """Normalize timeframe string.

    Args:
        timeframe: Raw timeframe string.

    Returns:
        Normalized timeframe: swing, position, or long-term.
    """
    timeframe = timeframe.lower().strip()
    valid_timeframes = {"swing", "position", "long-term", "long_term"}

    if timeframe in valid_timeframes:
        return timeframe.replace("_", "-")

    # Map common variations
    if "day" in timeframe or "week" in timeframe or "short" in timeframe:
        return "swing"
    elif "month" in timeframe or "medium" in timeframe:
        return "position"
    elif "year" in timeframe or "long" in timeframe:
        return "long-term"

    return "position"


def _timeframe_to_horizon(timeframe: str) -> str:
    """Convert timeframe to time_horizon for DeepInsight model.

    Args:
        timeframe: Timeframe string (swing, position, long-term).

    Returns:
        Time horizon string (short_term, medium_term, long_term).
    """
    mapping = {
        "swing": "short_term",
        "position": "medium_term",
        "long-term": "long_term",
        "long_term": "long_term",
    }
    return mapping.get(timeframe.lower(), "medium_term")


def _clamp_confidence(value: Any) -> float:
    """Clamp confidence value to valid range [0.0, 1.0].

    Args:
        value: Raw confidence value.

    Returns:
        Clamped float between 0.0 and 1.0.
    """
    try:
        conf = float(value)
        return max(0.0, min(1.0, conf))
    except (ValueError, TypeError):
        return 0.5


def _clamp_alignment(value: Any) -> int:
    """Clamp alignment score to valid range [1, 10].

    Args:
        value: Raw alignment score.

    Returns:
        Clamped integer between 1 and 10.
    """
    try:
        score = int(value)
        return max(1, min(10, score))
    except (ValueError, TypeError):
        return 5


def _extract_insights_from_text(response: str, max_insights: int) -> list[dict[str, Any]]:
    """Fallback: Extract insights from unstructured text response.

    Args:
        response: Raw text response.
        max_insights: Maximum insights to extract.

    Returns:
        List of extracted insight dictionaries (may be empty).
    """
    logger.warning("Attempting to extract insights from unstructured text")

    # Basic pattern matching for symbols and actions
    symbol_pattern = r"\b([A-Z]{1,5})\b"
    action_pattern = r"\b(BUY|SELL|HOLD|WATCH|STRONG_BUY|STRONG_SELL)\b"

    symbols = re.findall(symbol_pattern, response)
    actions = re.findall(action_pattern, response, re.IGNORECASE)

    # Filter out common non-symbol words
    excluded = {"THE", "AND", "FOR", "WITH", "THIS", "THAT", "FROM", "WILL", "NOT"}
    symbols = [s for s in symbols if s not in excluded]

    insights: list[dict[str, Any]] = []

    for i, symbol in enumerate(symbols[:max_insights]):
        action = actions[i].upper() if i < len(actions) else "WATCH"
        insights.append({
            "symbol": symbol,
            "action": action,
            "title": f"{action} {symbol} - Extracted from analysis",
            "thesis": "See full analysis for details.",
            "confidence": 0.4,  # Lower confidence for extracted insights
            "insight_type": "opportunity",
            "time_horizon": "medium_term",
            "primary_symbol": symbol,
            "entry_zone": None,
            "target_price": None,
            "stop_loss": None,
            "timeframe": "position",
            "key_risks": [],
            "alignment_score": 5,
            "related_symbols": [],
            "risk_factors": [],
            "analysts_involved": [],
        })

    return insights


@dataclass
class AutonomousInsightData:
    """Structured data for an autonomous synthesis insight with trading levels."""

    symbol: str
    action: str
    title: str
    thesis: str
    confidence: float = 0.5

    # Trading levels
    entry_zone: str | None = None
    target_price: str | None = None
    stop_loss: str | None = None
    timeframe: str = "position"

    # Alignment and risks
    alignment_score: int = 5
    key_risks: list[str] = field(default_factory=list)

    # Standard insight fields
    insight_type: str = "opportunity"
    time_horizon: str = "medium_term"
    related_symbols: list[str] = field(default_factory=list)
    supporting_evidence: list[SupportingEvidence] = field(default_factory=list)
    risk_factors: list[str] = field(default_factory=list)
    invalidation_trigger: str | None = None
    historical_precedent: str | None = None
    analysts_involved: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "symbol": self.symbol,
            "action": self.action,
            "title": self.title,
            "thesis": self.thesis,
            "confidence": round(self.confidence, 4),
            "entry_zone": self.entry_zone,
            "target_price": self.target_price,
            "stop_loss": self.stop_loss,
            "timeframe": self.timeframe,
            "alignment_score": self.alignment_score,
            "key_risks": self.key_risks,
            "insight_type": self.insight_type,
            "time_horizon": self.time_horizon,
            "primary_symbol": self.symbol,
            "related_symbols": self.related_symbols,
            "supporting_evidence": [e.to_dict() for e in self.supporting_evidence],
            "risk_factors": self.risk_factors,
            "invalidation_trigger": self.invalidation_trigger,
            "historical_precedent": self.historical_precedent,
            "analysts_involved": self.analysts_involved,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AutonomousInsightData:
        """Create from dictionary."""
        evidence = []
        for e in data.get("supporting_evidence", []):
            if isinstance(e, dict):
                evidence.append(SupportingEvidence.from_dict(e))

        return cls(
            symbol=data.get("symbol", data.get("primary_symbol", "")),
            action=data.get("action", "HOLD"),
            title=data.get("title", ""),
            thesis=data.get("thesis", ""),
            confidence=float(data.get("confidence", 0.5)),
            entry_zone=data.get("entry_zone"),
            target_price=data.get("target_price"),
            stop_loss=data.get("stop_loss"),
            timeframe=data.get("timeframe", "position"),
            alignment_score=int(data.get("alignment_score", 5)),
            key_risks=data.get("key_risks", []),
            insight_type=data.get("insight_type", "opportunity"),
            time_horizon=data.get("time_horizon", "medium_term"),
            related_symbols=data.get("related_symbols", []),
            supporting_evidence=evidence,
            risk_factors=data.get("risk_factors", data.get("key_risks", [])),
            invalidation_trigger=data.get("invalidation_trigger"),
            historical_precedent=data.get("historical_precedent"),
            analysts_involved=data.get("analysts_involved", []),
        )
