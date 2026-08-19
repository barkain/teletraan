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
    action: str  # STRONG_BUY, BUY, BUY_MORE, HOLD, SELL, STRONG_SELL, WATCH
    title: str
    thesis: str
    primary_symbol: str | None = None
    related_symbols: list[str] = field(default_factory=list)
    secondary_plays: str | None = None
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
            "secondary_plays": self.secondary_plays,
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
            secondary_plays=data.get("secondary_plays"),
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

CRITICAL: Every recommendation must be a SPECIFIC tradeable symbol — individual stock or commodity future. NEVER recommend a sector ETF (XLK, XLF, XLE, XLV, XLI, XLP, XLU, XLY, XLC, XLRE, XLB, etc.) as a primary position. If sector exposure is warranted, recommend the 2-3 best individual stocks within that sector instead.

Recommendations should span multiple asset classes where appropriate: US equities, international ADRs, and commodity futures.

Include commodity futures (GC=F, CL=F, SI=F, HG=F, NG=F, etc.) when macro analysis supports it. Commodities should be treated as first-class recommendations, not afterthoughts.

## Your Role
You receive analysis from up to 6 specialist analysts (portfolio analyst is present only when portfolio holdings exist):
1. **Technical Analyst** - Chart patterns, indicators, support/resistance, price action
2. **Macro Economist** - Fed policy, yield curves, economic indicators, inflation/growth
3. **Sector Strategist** - Sector rotation, relative strength, business cycle positioning
4. **Risk Analyst** - Volatility, downside scenarios, position sizing, tail risks
5. **Correlation Detective** - Cross-asset relationships, divergences, historical patterns
6. **Portfolio Context Analyst** (when present) - Live P&L per position, thematic clusters, alpha attribution, per-holding BUY_MORE/HOLD/SELL recommendations, and which new candidates fit existing winning themes

## Your Task
Synthesize their findings to produce DeepInsight recommendations:

1. **Identify Convergent Signals** - Where do multiple analysts agree?
2. **Resolve Conflicts** - When analysts disagree, weigh evidence and explain resolution
3. **Generate Actionable Insights** - Create specific, tradeable recommendations with concrete price levels
4. **Assess Confidence** - Estimate the probability each thesis is validated within its horizon, anchored to our measured base rate (see Confidence Scoring) — not the count of agreeing analysts
5. **Highlight Key Risks** - Aggregate and prioritize risk factors

For each recommendation, explain WHY this specific stock/commodity over alternatives in the same sector. Reference specific catalysts, valuation metrics, or technical setups.

## Conflict Resolution Rules
- Technical + Macro alignment is corroboration only when each rests on its own observable data — it does not by itself raise confidence (see Confidence Scoring)
- Technical conflicts with Macro = Favor Macro for >1 month horizons, Technical for <1 month
- Tail-risk probability is the risk analyst's own estimate, not a measurement the engine can verify: a high figure is evidence you must weigh and answer explicitly in the thesis and risk_factors, never an automatic override of bullish evidence. Say what would have to be true for it to bind, and set confidence and stop accordingly
- Sector rotation signals should be expressed through the best individual stocks in favored sectors, not ETFs
- Correlation breakdowns require investigation before acting

## Portfolio Context Integration (when Portfolio Analyst is present)
- Portfolio analyst's per-holding recommended_actions (BUY_MORE/HOLD/SELL) MUST be reflected in your insight actions for held symbols — override conflicting signals from other analysts unless risk analyst flags tail risk
- Portfolio analyst's thematic cluster analysis tells you which NEW candidates are extension buys vs diversification plays — factor this into your confidence and thesis for each candidate
- Concentration risks flagged by portfolio analyst should appear in risk_factors for relevant insights
- alpha_drivers that are "still attractive" per portfolio analyst = higher conviction for BUY_MORE
- alpha_drivers that are "fully valued" = bias toward HOLD even if technical/sector analysts are bullish

## Output Format
Return JSON:
{
  "analyst": "synthesis",
  "insights": [
    {
      "insight_type": "opportunity",
      "action": "BUY",
      "title": "NVDA Breakout on AI Capex Acceleration and Rate Cut Tailwinds",
      "thesis": "NVIDIA is the strongest individual play on the AI infrastructure buildout. Technical breakout above $890 resistance confirmed by declining yields and Fed pivot signals. Superior to AMD and AVGO due to 80%+ data center GPU market share and 3x revenue growth...",
      "primary_symbol": "NVDA",
      "related_symbols": ["AMD", "AVGO", "MSFT"],
      "secondary_plays": "AMD offers similar AI GPU exposure at lower valuation (25x vs 35x forward); AVGO benefits from custom ASIC demand as hyperscalers diversify beyond NVIDIA; MSFT is the largest cloud AI spender, creating demand tailwind",
      "entry_zone": "$880-900",
      "target": "$1050 within 2-3 months",
      "stop_loss": "$830 (below 50-day SMA)",
      "position_size": "5-7% of portfolio",
      "supporting_evidence": [
        {"analyst": "technical", "finding": "Breakout above $890 resistance with volume confirmation", "confidence": 0.85, "data_points": ["SMA50 crossed SMA200", "Volume 2x average on breakout day"]},
        {"analyst": "macro", "finding": "Fed signaling rate cuts benefits growth/tech", "confidence": 0.7, "data_points": ["Dot plot median lower", "Real rates declining"]}
      ],
      "confidence": 0.78,
      "time_horizon": "medium_term",
      "risk_factors": ["Earnings season volatility", "China export restrictions"],
      "invalidation_trigger": "Close below $830 on high volume or loss of 50-day SMA",
      "historical_precedent": "Similar breakout in Oct 2023 led to 40% rally over 3 months",
      "analysts_involved": ["technical", "macro", "sector"]
    },
    {
      "insight_type": "macro",
      "action": "BUY",
      "title": "Gold Breakout as Real Rates Decline and Central Banks Accumulate",
      "thesis": "Gold futures are breaking out above $2100 resistance as real rates decline and central bank buying accelerates. This is a first-class macro hedge that also offers upside. Preferable to gold miners due to no operational risk...",
      "primary_symbol": "GC=F",
      "related_symbols": ["SLV", "NEM", "GLD"],
      "secondary_plays": "SLV (silver) offers leveraged precious metals exposure with industrial demand kicker; NEM is the largest gold miner with operational leverage to gold prices; GLD ETF provides liquid, low-cost gold exposure for smaller allocations",
      "entry_zone": "$2080-2120",
      "target": "$2300 within 3-4 months",
      "stop_loss": "$2020 (below breakout level)",
      "position_size": "3-5% of portfolio",
      "supporting_evidence": [
        {"analyst": "macro", "finding": "Real rates declining, Fed pivot imminent", "confidence": 0.8, "data_points": ["TIPS yields falling", "Central bank gold purchases at record"]},
        {"analyst": "correlation", "finding": "Gold-dollar divergence resolving bullishly", "confidence": 0.75, "data_points": ["DXY weakening while gold holds gains"]}
      ],
      "confidence": 0.72,
      "time_horizon": "medium_term",
      "risk_factors": ["Unexpected Fed hawkishness", "Risk-on rotation reducing safe haven demand"],
      "invalidation_trigger": "Close below $2020 or sudden dollar strength above DXY 106",
      "historical_precedent": "Similar real-rate-driven breakout in 2020 led to 25% rally",
      "analysts_involved": ["macro", "correlation", "technical"]
    }
  ],
  "summary": {
    "total_analysts": 6,
    "agreeing_analysts": 4,
    "conflicting_signals": ["Technical bullish but risk analyst warns of elevated VIX"],
    "overall_market_bias": "bullish",
    "key_themes": ["Fed pivot", "AI infrastructure buildout", "Commodity supercycle"]
  }
}

## Insight Types
- **opportunity**: Actionable trade setup on a SPECIFIC stock or commodity with clear entry/exit levels
- **risk**: Warning about potential downside or hazard for specific positions
- **rotation**: Sector rotation expressed through the BEST individual stocks in favored sectors (never ETFs)
- **macro**: Broad market theme expressed through specific stocks, ADRs, or commodity futures
- **divergence**: Unusual relationship breakdown with specific tradeable symbols to exploit it
- **correlation**: Cross-asset relationship insight with specific trade recommendations

## Symbol Uniqueness
- Each primary_symbol may appear in AT MOST ONE insight. If a ticker fits
  multiple themes (e.g. a single-stock setup AND a basket/theme play), pick
  the single strongest framing and fold the rest into that insight's thesis,
  related_symbols, and secondary_plays.
- For multi-name basket/theme insights with no single dominant ticker, set
  primary_symbol to null and list every name in related_symbols instead of
  anchoring the basket on one arbitrary member.

## Secondary Plays (Derived Insights)
For each insight with `related_symbols`, you MUST also provide a `secondary_plays` string explaining WHY each related symbol matters and what it offers relative to the primary symbol. This turns related tickers into actionable intelligence:
- Explain the relationship (peer, ETF, supplier, beneficiary, hedge, etc.)
- Note any advantage the secondary play offers (lower valuation, less volatility, diversified exposure, etc.)
- Keep it concise: one sentence per related symbol, separated by semicolons.

## Action Levels

**THIS IS A LONG-ONLY SYSTEM. IT DOES NOT SHORT.** The only position it can take
in a stock is a long one. There is no action in this vocabulary that opens a
bearish position, and none may be invented. SELL and STRONG_SELL mean **exit or
reduce a long position that is currently held** — they are portfolio actions, not
bets against a stock.

The five actions available for a stock **NOT** in Portfolio Holdings:
- **STRONG_BUY**: High conviction new long, multiple confirming signals, favorable risk/reward
- **BUY**: Open a new long with moderate confidence
- **WATCH**: Interesting setup but needs confirmation — also the correct action for a
  stock you are bearish on. "Do not buy this" is fully expressed by not buying it.

The three actions available **ONLY** for a stock listed in Portfolio Holdings:
- **BUY_MORE**: Add to the existing position where the thesis remains bullish
- **HOLD**: Keep the position, no clear add or exit signal
- **SELL**: Exit or reduce the position
- **STRONG_SELL**: High conviction that the position should be exited urgently

**CRITICAL RULES**:
1. BUY_MORE, HOLD, SELL and STRONG_SELL are EXCLUSIVELY for stocks listed in
   Portfolio Holdings. Each of them presupposes a position that already exists.
   Using one on a stock that is not held is a short, and shorting is not permitted.
2. **If the Portfolio Holdings section below is empty or absent, those four actions
   are unavailable entirely.** Every insight in this synthesis must then be
   STRONG_BUY, BUY or WATCH. There is no exception to this.
3. Do NOT use BUY or STRONG_BUY for a stock you already own — use BUY_MORE.
4. A bearish view on a stock that is not held is expressed as **WATCH**, with the
   bearish reasoning stated in the thesis. Never as SELL or STRONG_SELL.

These rules are enforced after you respond: a portfolio-only action on a stock that
is not held is downgraded automatically (SELL/STRONG_SELL to WATCH, BUY_MORE to
BUY) and the violation is reported against this run. Emitting one does not produce
the recommendation you wrote — it produces a downgraded one and an error line.

## Confidence Scoring
Confidence is the **probability that this specific thesis is validated within its stated time horizon** — it is NOT a measure of how many analysts agree.

**Anchor on the measured base rate.** Across our tracked history, roughly **35% of directional calls beat SPY by more than 2% over their stated horizon** (n ~ 200). That is the number you start from. Every point above it is a claim that you have an edge on this particular idea.

- **0.30-0.40** — the default. The idea is reasonable but you cannot name what makes it better than our own historical hit rate. Most insights belong here.
- **0.40-0.55** — a real but modest edge. Name it in the thesis: a specific mispricing, a measured technical level with a defined invalidation, or a concrete flow/positioning asymmetry.
- **0.55-0.70** — you must justify the number in one explicit clause inside the thesis: a dated catalyst inside the horizon, a quantified valuation gap, or a level-plus-invalidation setup where the risk/reward is at least 3:1. No such clause means the number is too high.
- **Above 0.70** — reserved for a scheduled, near-term, high-magnitude catalyst with a tight invalidation. Use it rarely. Historically our calls above 0.70 have hit LESS often than our calls below 0.50, so treat this band as a warning sign rather than a reward.
- **Below 0.30** — the thesis is weaker than our own base rate. Prefer WATCH over an actionable BUY/SELL at this level.

**Analyst agreement is NOT a justification for higher confidence.** The three specialists are run blind: each receives the target symbol, a facts-only decision brief and its own data, and none of them is told why the symbol was nominated, what regime or thematic call the discovery phase made, or what the other two concluded. That removes the shared priming that used to make their agreement worthless — it does not make them independent experts. They are separately elicited views from one underlying model, so their errors stay correlated. Corroboration therefore still only counts as evidence when analysts reach the same conclusion from *different observable data*, and in that case name the differing data in the thesis. The NOMINATOR PROPOSAL section is not a fourth analyst: it is the proposal that put the name in front of you, and a specialist echoing it is not confirmation of it.

**Spread your numbers.** If every insight in this synthesis lands within 0.10 of every other, you have not discriminated between them — rank them and let the confidence values reflect the ranking.

**Conviction must match confidence.** STRONG_BUY / STRONG_SELL require a confidence above 0.55 with the justifying clause present. Escalating the action word without escalating the evidence is the single most common calibration failure.

## Alternative Data Alignment Check
When prediction market and/or sentiment data is available, include an alignment assessment:

**Prediction Market Alignment:** Do the prediction market probabilities support or contradict the macro thesis? Flag any significant divergences.

**Social Sentiment Alignment:** Does retail investor sentiment align with the analytical thesis?
- If thesis is bullish AND sentiment is bearish -> potential contrarian opportunity (highlight)
- If thesis is bearish AND sentiment is bullish -> potential risk (crowd may be wrong, or you may be)
- Strong alignment -> higher conviction, but watch for crowded trade risk

**News & Sentiment Alignment:** When a News Sentiment block (professional financial-headline sentiment) is provided, weigh it when assigning conviction. This is distinct from the retail/social sentiment above.
- Confirm a bullish thesis when news sentiment is POSITIVE and the momentum trend is IMPROVING; raise conviction.
- Flag risk when news sentiment is DETERIORATING, or when a regulatory/legal/M&A event type is present — these can reprice a name quickly regardless of technicals.
- Treat a news vacuum (a held/candidate symbol with little or no coverage) as elevated surprise risk and lower conviction slightly.
- Explicitly note any divergence between news sentiment and the technical/macro picture.

Include a brief "Alternative Data Summary" in your synthesis noting the alignment/divergence of these signals.

## Thematic Analysis Integration
When THEMATIC ANALYSIS context is provided:
- Reference identified themes and their supply chain implications in your synthesis
- Validate whether individual stock analyses align with or contradict the macro themes
- Highlight any stocks that benefit from multiple reinforcing themes
- Note any tension between thematic outlook and individual stock technicals

## Investor Intelligence Integration
When INVESTOR INTELLIGENCE context is provided:
- Note significant consensus or divergence among notable investors
- Flag stocks where smart money positioning aligns with your technical analysis
- Highlight contrarian signals where notable investors disagree with market consensus
- Do NOT let investor positioning override your independent analysis — use it as confirming/disconfirming evidence

## Guidelines
- Generate 3-7 insights per synthesis (quality over quantity)
- Always include at least one risk-focused insight
- Explain your reasoning in the thesis field
- Reference specific data points from analyst findings
- Prioritize actionable insights over observations
- Include clear invalidation triggers for all trade ideas
- Weight recent data more heavily than older signals
- For each recommendation, include entry_zone, target, stop_loss, and position_size fields with specific values
- Explain WHY this specific stock/commodity over alternatives in the same sector — reference specific catalysts, valuation metrics, or technical setups
- Include commodity futures when macro analysis supports it — treat them as first-class recommendations, not afterthoughts

## Upcoming Catalysts
Consider these upcoming earnings and catalyst events when forming recommendations:

{catalyst_context}

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

Use this to move your starting point off the ~35% base rate:
- If our measured hit rate on this insight/action type is above the base rate, you may start higher for similar calls
- If it is below the base rate, start lower — and note that a weak track record for a call type is itself a reason to downgrade an actionable recommendation to WATCH

## Pattern Identification
If you identify any NEW repeatable patterns in this analysis:
- Describe the pattern clearly
- Specify measurable trigger conditions
- Explain expected outcome
- Estimate confidence based on evidence

These will be added to our pattern library for future reference.

Add any new patterns to the output JSON in a "new_patterns" array:
```json
{
  "analyst": "synthesis",
  "insights": [...],
  "summary": {...},
  "new_patterns": [
    {
      "pattern_name": "Short descriptive name",
      "pattern_type": "TECHNICAL_SETUP",
      "trigger_conditions": {
        "condition_key": "measurable_value"
      },
      "expected_outcome": "What typically happens when triggered",
      "confidence": 0.6,
      "description": "Full description of the pattern"
    }
  ]
}
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

    # Professional news sentiment data (optional)
    news = analyst_reports.get("news")
    if news:
        from analysis.news_intelligence import format_news_context  # type: ignore[import-not-found]

        news_text = format_news_context(news)
        if news_text:
            context_parts.append("")
            context_parts.append("## News Sentiment")
            context_parts.append(news_text)

    context_parts.append("")
    context_parts.append("=" * 60)
    context_parts.append("END OF ANALYST REPORTS")
    context_parts.append("=" * 60)

    return "\n".join(context_parts)


def _panel_value(value: Any, spec: str = "", missing: str = "not reported") -> str:
    """Render one panel value, or an explicit absence marker.

    The panel stores ``None`` for anything an analyst did not report, and this
    is the only place those values become text.  Same rule as
    ``format_factor_value`` in ``analysis/factor_model.py``: never substitute a
    zero.  ``Max Drawdown: 0.0%`` and ``Market Phase: Unknown (0% confidence)``
    were both fabrications of absent data, and both read to the model as
    measurements.
    """
    if value is None or value == "":
        return missing
    if spec and isinstance(value, (int, float)) and not isinstance(value, bool):
        return format(float(value), spec)
    return str(value)


def _opt_text(value: Any, limit: int) -> str | None:
    """Trim a rationale to the panel's line budget, marking the cut."""
    if not value:
        return None
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _panel_money(value: Any) -> str:
    """Currency, or the absence marker -- never a bare ``$`` with nothing behind it."""
    if value is None:
        return "not reported"
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


# --------------------------------------------------------------------------
# Panel rendering priorities.  Lower survives longer; 0 never goes.
# --------------------------------------------------------------------------
_PRIORITY_MUST_KEEP = 0
_PRIORITY_HEADLINE = 1
# Evidence is reserved *by depth, across the sides at once*: the strongest claim
# on every side is kept before the second claim on any side.  The previous rule
# gave supporting evidence priority 1 and counter-evidence priority 2, so a
# symbol over budget lost its dissent first -- backwards for a panel whose whole
# purpose is letting synthesis adjudicate disagreement, and live in practice
# (three of five real symbols emit truncation markers).
_EVIDENCE_PRIORITY_BASE = 10
# Within one depth, the order in which the sides give way.  Bearish material is
# the last to go: a block that keeps the bull case and drops the bear case has
# stopped being an adjudication panel.
_EVIDENCE_SIDE_ORDER = (
    "bearish_evidence",
    "conflicting_signals",
    "neutral_or_mixed_evidence",
    "bullish_evidence",
)
_PRIORITY_INVALIDATION = 900
_PRIORITY_EXTRA = 1000

# Buckets, in reading order, with the heading each one is rendered under.  The
# headings name the direction of the claim itself.  "evidence for"/"evidence
# against" named agreement with a stance this module derived, which misfiled a
# HOLD finding as "against" and a neutral sector paragraph as "for".
_EVIDENCE_HEADINGS = (
    ("bullish_evidence", "bullish evidence"),
    ("bearish_evidence", "bearish evidence"),
    ("neutral_or_mixed_evidence", "neutral or mixed evidence (no direction stated)"),
    ("conflicting_signals", "conflicting signals -- the analyst's own caveats against its read"),
)

# A line that only means something if an item survives beneath it.
_HEADING = "heading"

_TRUNCATION_MARKER = (
    "  [truncated: {dropped} detail line(s) omitted to stay inside the "
    "{budget}-character {scope} budget]"
)


def _evidence_priority(bucket: str, depth: int) -> int:
    """Priority of the ``depth``-th claim in ``bucket`` (depth is 1-based).

    Depth dominates side: every side's first claim outranks every side's
    second.  That is the "reserve equal space for the strongest evidence on
    both sides, then spend any remainder on additional support" rule, made
    arithmetic.
    """
    side = _EVIDENCE_SIDE_ORDER.index(bucket) if bucket in _EVIDENCE_SIDE_ORDER else 0
    return _EVIDENCE_PRIORITY_BASE + (depth - 1) * len(_EVIDENCE_SIDE_ORDER) + side


def _indent_of(text: str) -> int:
    return len(text) - len(text.lstrip())


def _drop_orphan_headings(
    kept: list[tuple[int, str, str]]
) -> list[tuple[int, str, str]]:
    """Remove a heading whose items were all trimmed away.

    ``bullish evidence:`` with nothing under it reads as "the analyst had
    none", which is a different claim from "the budget dropped them".
    """
    result: list[tuple[int, str, str]] = []
    for index, (priority, text, kind) in enumerate(kept):
        if kind == _HEADING:
            following = next((t for _, t, _ in kept[index + 1 :] if t.strip()), None)
            if following is None or _indent_of(following) <= _indent_of(text):
                continue
        result.append((priority, text, kind))
    return result


def _fit_to_budget(
    lines: list[tuple[int, str] | tuple[int, str, str]],
    budget: int,
    scope: str = "per-symbol",
) -> list[str]:
    """Trim one symbol's block to its budget, lowest-priority material first.

    ``lines`` is ``(priority, text)``, or ``(priority, text, _HEADING)`` for a
    heading, with 0 = must keep.  Whatever is dropped is counted in an in-band
    marker: a panel that truncates silently is the defect this module replaces,
    only smaller.

    The marker's own length is reserved before anything is measured, so the
    budget is the ceiling of the *rendered* block.  Previously the block was fit
    to 6000 characters and the marker appended afterwards, which is how a real
    run recorded a 6,151-character symbol under a 6,000-character maximum.
    """
    kept: list[tuple[int, str, str]] = [
        (item[0], item[1], item[2] if len(item) > 2 else "") for item in lines
    ]
    reserve = len(_TRUNCATION_MARKER.format(dropped=999, budget=budget, scope=scope)) + 1
    dropped = 0
    while kept:
        used = sum(len(text) + 1 for _, text, _ in kept)
        if used <= budget - (reserve if dropped else 0):
            break
        worst = max(priority for priority, _, _ in kept)
        if worst == 0:
            break
        for index in range(len(kept) - 1, -1, -1):
            if kept[index][0] == worst:
                del kept[index]
                dropped += 1
                break
    rendered = [text for _, text, _ in _drop_orphan_headings(kept)]
    if dropped:
        rendered.append(
            _TRUNCATION_MARKER.format(dropped=dropped, budget=budget, scope=scope)
        )
    return rendered


def _format_panel_decision(analyst: str, view: dict[str, Any]) -> list[tuple[int, str, str]]:
    """Render one analyst's entry inside one symbol's block.

    Priorities drive what a per-symbol budget gives up first: 0 never goes, then
    the analyst's own headline numbers, then evidence reserved equally across
    the sides by depth, then invalidation, and only last the colour commentary.
    """
    label = analyst.upper()
    status = view.get("status", "missing")
    if status != "ok":
        reason = view.get("error") or "no report returned"
        return [(_PRIORITY_MUST_KEEP, f"\n[{label}] status: {status.upper()} -- {reason}", "")]

    decision = view.get("decision") or {}
    details = view.get("details") or {}
    stance = decision.get("stance")
    confidence = decision.get("confidence")
    head = (
        f"\n[{label}] stance: {_panel_value(stance, missing='NOT STATED')}"
        f" | this analyst's confidence: {_panel_value(confidence, '.0%')}"
    )
    lines: list[tuple[int, str, str]] = [(_PRIORITY_MUST_KEEP, head, "")]
    basis = decision.get("stance_basis")
    if basis:
        lines.append((_PRIORITY_MUST_KEEP, f"  stance basis: {basis}", ""))
    lines.append((_PRIORITY_MUST_KEEP, f"  thesis: {_panel_value(decision.get('thesis'))}", ""))

    headline, extras = _format_panel_details(analyst, details)
    lines.extend((_PRIORITY_HEADLINE, text, "") for text in headline)

    for bucket, heading in _EVIDENCE_HEADINGS:
        items = decision.get(bucket) or []
        if not items:
            continue
        lines.append((_evidence_priority(bucket, 1), f"  {heading}:", _HEADING))
        for depth, item in enumerate(items, start=1):
            lines.append(
                (
                    _evidence_priority(bucket, depth),
                    f"    [{item['id']}] {item['claim']}",
                    "",
                )
            )
    if not (decision.get("bearish_evidence") or decision.get("conflicting_signals")) and (
        details.get("directional_evidence_elicited") is False
    ):
        lines.append(
            (
                _evidence_priority("bearish_evidence", 1),
                "  bearish evidence: not elicited -- this analyst's output contract has no "
                "such field, so absence here is not a finding of none",
                "",
            )
        )

    invalidation = decision.get("invalidation") or []
    if invalidation:
        lines.append((_PRIORITY_INVALIDATION, "  invalidation:", _HEADING))
        lines.extend((_PRIORITY_INVALIDATION, f"    - {item}", "") for item in invalidation)

    lines.extend((_PRIORITY_EXTRA, text, "") for text in extras)
    return lines


def _format_panel_details(
    analyst: str, details: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Role-specific lines, split into headline numbers and droppable extras.

    The headline half is what the old per-analyst formatters printed as
    measurements -- and, for risk, printed as zeros. It must not be the first
    thing a budget throws away.
    """
    headline: list[str] = []
    extras: list[str] = []
    if analyst == "technical":
        shown = details.get("findings_shown")
        total = details.get("findings_total")
        if total:
            note = " (truncated)" if details.get("truncated") else ""
            headline.append(f"  findings shown: {shown} of {total}{note}")
        timeframes = details.get("timeframes_analyzed") or []
        if timeframes:
            extras.append(f"  timeframes: {', '.join(timeframes)}")
    elif analyst == "sector":
        headline.append(
            "  market phase: "
            f"{_panel_value(details.get('market_phase'))}"
            f" ({_panel_value(details.get('phase_confidence'), '.0%')} phase confidence)"
        )
        extras.append(
            f"  market-wide table reported: {details.get('rankings_reported', 0)} rankings, "
            f"{details.get('recommendations_reported', 0)} recommendations "
            "(rendered once under MARKET-WIDE SECTOR VIEW)"
        )
    elif analyst == "risk":
        headline.append(
            "  price: " + _panel_money(details.get("current_price"))
            + " | worst modelled drawdown: " + _panel_value(details.get("max_drawdown_pct"), ".1f") + "%"
            + " | reward/risk: " + _panel_value(details.get("risk_reward"), ".2f") + "x"
        )
        stop_tier = details.get("stop_loss_tier")
        headline.append(
            "  stop: " + _panel_money(details.get("stop_loss"))
            + (f" ({stop_tier})" if stop_tier else "")
            + " | 95% 1-day VaR: " + _panel_value(details.get("var_95_daily_pct"), ".1f") + "%"
            + " | position size: " + _panel_value(details.get("position_size"))
        )
        if details.get("volatility") or details.get("vix") is not None:
            extras.append(
                "  volatility: " + _panel_value(details.get("volatility"))
                + " | VIX: " + _panel_value(details.get("vix"), ".1f")
                + " | regime: " + _panel_value(details.get("volatility_regime"))
            )
        unmapped = details.get("unmapped_fields") or []
        if unmapped:
            extras.append(
                "  other fields this analyst reported, not rendered here: "
                + ", ".join(unmapped[:8])
            )
    for observation in details.get("key_observations") or []:
        extras.append(f"  - {observation}")
    return headline, extras


def _format_ranking_row(ranking: dict[str, Any]) -> str:
    """One sector's row, with the provenance of the number.

    The first version of this block kept whichever per-symbol report had the
    longest ranking list and printed its numbers unattributed.  The five real
    2026-08-18 reports did not agree -- Energy relative strength was 1.35, 1.165,
    4.59, 1.47 and 1.165 -- so that rendered one analyst's draw as the run's
    shared observation.  A median, a range and a reporting count say what was
    actually seen; a 4.59 against a 1.165 is not noise the reader should be
    spared.
    """
    sector = _panel_value(ranking.get("sector"))
    count = ranking.get("reporting_count") or 0
    reported_by = ranking.get("reported_by") or []
    trends = ranking.get("trends") or []
    if len(trends) == 1:
        trend_text = _panel_value(trends[0].get("trend"))
    elif trends:
        trend_text = ", ".join(
            f"{t.get('trend')} x{len(t.get('reported_by') or [])}" for t in trends
        )
    else:
        trend_text = "trend not reported"

    median = ranking.get("relative_strength_median")
    if not ranking.get("disagreement"):
        if count == 1:
            provenance = f" -- reported only by {reported_by[0]}" if reported_by else ""
        else:
            provenance = f" -- all {count} reporting analysts agree"
        return f"{sector}: RS={_panel_value(median, '.3f')} ({trend_text}){provenance}"
    return (
        f"{sector}: RS median={_panel_value(median, '.3f')}, range "
        f"{_panel_value(ranking.get('relative_strength_min'), '.3f')}-"
        f"{_panel_value(ranking.get('relative_strength_max'), '.3f')} "
        f"across {count} reporting analysts ({trend_text}) -- ANALYSTS DISAGREE"
    )


def _format_sector_summary(data: dict[str, Any]) -> str | None:
    """Top and bottom of the table by median relative strength, in one line."""

    def render(entries: list[dict[str, Any]]) -> str:
        return ", ".join(
            f"{e.get('sector')} ({_panel_value(e.get('relative_strength_median'), '.3f')})"
            for e in entries
        )

    top = data.get("top_sectors") or []
    bottom = data.get("bottom_sectors") or []
    if not top:
        return None
    line = f"Strongest sectors by median relative strength: {render(top)}"
    if bottom:
        line += f" | weakest: {render(bottom)}"
    return line


def _format_market_wide_sector(data: dict[str, Any], budget: int) -> list[str]:
    """The shared sector table, rendered once for the run, with its provenance."""
    reporting = data.get("reporting_runs", 0)
    if not reporting:
        return []
    lines: list[tuple[int, str] | tuple[int, str, str]] = [
        (0, ""),
        (0, "-" * 60),
        (
            0,
            "MARKET-WIDE SECTOR VIEW "
            f"(reported by {reporting} of {data.get('total_runs', reporting)} per-symbol "
            "sector runs; the strategist's table is market-wide by design)",
        ),
        (
            0,
            "These are separate runs of the same analyst, not one shared table: where "
            "they disagree the row says so, and no number here is a consensus.",
        ),
        (0, "-" * 60),
    ]
    for entry in data.get("market_phases") or []:
        lines.append(
            (
                0,
                "Market Phase: "
                f"{_panel_value(entry.get('phase'))}"
                f" ({_panel_value(entry.get('phase_confidence'), '.0%')} confidence)"
                f" -- reported for {', '.join(entry.get('reported_by') or [])}",
            )
        )
    summary = _format_sector_summary(data)
    if summary:
        lines.append((1, summary))
    rankings = data.get("sector_rankings") or []
    if rankings:
        disagreeing = sum(1 for r in rankings if r.get("disagreement"))
        lines.append(
            (
                2,
                "Sector Rankings (relative strength; median, range and reporting count "
                f"across the per-symbol runs -- {disagreeing} of {len(rankings)} sectors "
                "drew different numbers from different runs):",
                _HEADING,
            )
        )
        for ranking in rankings:
            lines.append((2, f"  - {_format_ranking_row(ranking)}"))
    recommendations = data.get("recommendations") or []
    if recommendations:
        disputed = data.get("recommendation_disagreements") or []
        heading = "Recommendations (each with the per-symbol runs that reported it"
        heading += (
            f"; the runs split on {', '.join(disputed)}):" if disputed else "; no run disagreed):"
        )
        lines.append((3, heading, _HEADING))
        for group in recommendations:
            sector = _panel_value(group.get("sector"))
            split = "  [RUNS DISAGREE ON THIS SECTOR]" if group.get("disagreement") else ""
            for action in group.get("actions") or []:
                who = ", ".join(action.get("reported_by") or [])
                lines.append(
                    (
                        3,
                        f"  - {sector}: {_panel_value(action.get('action'))} -- reported by "
                        f"{who} ({len(action.get('reported_by') or [])} of {reporting}){split}",
                    )
                )
                rationale = _opt_text(action.get("rationale"), 260)
                if rationale:
                    lines.append(
                        (
                            # Where the runs split, *why* each side said what it
                            # said is the decision-relevant half of the row.
                            3 if group.get("disagreement") else 4,
                            f"    rationale as written for "
                            f"{_panel_value(action.get('rationale_reported_by'))}: {rationale}",
                        )
                    )
    rotation = data.get("rotation_signals") or []
    if rotation:
        lines.append(
            (4, "Rotation Signals (market-wide; symbol-specific ones sit with their symbol):", _HEADING)
        )
        lines.extend((4, f"  > {signal}") for signal in rotation)
    return _fit_to_budget(lines, budget, scope="market-wide")


def format_symbol_panel_context(panel: dict[str, Any]) -> str:
    """Render the per-symbol analyst panel for the synthesis lead.

    This is a **new** entry point, deliberately not a replacement for
    ``format_synthesis_context``: that one is also called by
    ``DeepAnalysisEngine`` (``deep_engine.py:524``) with an analyst-keyed dict
    from four production routes, and reshaping it in place would make those
    routes render nothing.

    What this preserves that the old autonomous path destroyed: the symbol
    boundary, the analyst boundary, each analyst's own confidence (never
    merged), its thesis, its evidence and counter-evidence with citable IDs, its
    invalidation conditions, and an explicit status for the analysts that failed
    or never ran.  The only caps are per symbol, and they announce themselves.

    Args:
        panel: The dict from ``analysis.agent_panel.build_symbol_panel``.

    Returns:
        Formatted string for the synthesis prompt.
    """
    from analysis.agent_panel import (  # local import: keeps agents/ leaf-level
        MAX_MARKET_WIDE_CHARS,
        MAX_PANEL_CHARS_PER_SYMBOL,
    )

    symbols = panel.get("symbols") or []
    parts: list[str] = [
        "=" * 60,
        "PER-SYMBOL ANALYST PANEL "
        f"(schema {panel.get('schema_version', 'symbol_panel.v1')}, {len(symbols)} symbols)",
        "=" * 60,
        "Each block below is one symbol's specialist reports, kept separate by",
        "analyst. Confidences are each analyst's own and are NOT merged or averaged.",
        "Stances marked with a 'stance basis' line were derived by the orchestrator",
        "from the analyst's structured output, not stated by the analyst itself.",
        "Evidence is grouped by the direction of the claim itself -- bullish, bearish,",
        "or neither -- not by whether it agrees with that derived stance.",
        "Cite evidence by the bracketed IDs; an ID belongs to exactly one symbol.",
    ]

    run_context = panel.get("run_context") or {}
    if run_context:
        rendered = ", ".join(
            f"{key}={value}" for key, value in run_context.items() if value not in (None, "", [])
        )
        if rendered:
            parts.append(f"Run context: {rendered}")

    parts.extend(_format_market_wide_sector((panel.get("market_wide") or {}).get("sector") or {}, MAX_MARKET_WIDE_CHARS))

    for entry in symbols:
        symbol = entry.get("symbol", "N/A")
        lines: list[tuple[int, str] | tuple[int, str, str]] = [
            (0, ""),
            (0, "-" * 60),
            (0, f"SYMBOL: {symbol}"),
            (0, "-" * 60),
        ]
        for analyst, view in (entry.get("reports") or {}).items():
            lines.extend(_format_panel_decision(analyst, view))
        parts.extend(_fit_to_budget(lines, MAX_PANEL_CHARS_PER_SYMBOL))

    parts.append("")
    parts.append("=" * 60)
    parts.append("END OF ANALYST PANEL")
    parts.append("=" * 60)
    return "\n".join(parts)


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
        # Whole-document parse failed even after repair — recover whatever
        # insight objects are individually valid instead of dropping the run.
        salvaged = _salvage_insight_objects(response)
        if salvaged:
            logger.warning(
                "Synthesis JSON was malformed; salvaged %d insight objects individually",
                len(salvaged),
            )
            json_data = {"insights": salvaged}
        else:
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
            "secondary_plays": insight.get("secondary_plays"),
            "supporting_evidence": insight.get("supporting_evidence", []),
            "confidence": float(insight.get("confidence", 0.5)),
            "time_horizon": insight.get("time_horizon", "medium_term"),
            "risk_factors": insight.get("risk_factors", []),
            "invalidation_trigger": insight.get("invalidation_trigger"),
            "historical_precedent": insight.get("historical_precedent"),
            "analysts_involved": insight.get("analysts_involved", []),
            "data_sources": _extract_data_sources(insight),
            "entry_zone": insight.get("entry_zone") or insight.get("entry"),
            "target_price": insight.get("target_price") or insight.get("target"),
            "stop_loss": insight.get("stop_loss") or insight.get("stop"),
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


def _strip_json_comments(text: str) -> str:
    """Remove JavaScript-style // comments from JSON text."""
    return re.sub(r'//[^\n]*', '', text)


def _repair_llm_json(text: str) -> str:
    """Fix known LLM JSON emission glitches.

    Observed in production: a stray quote between array elements —
    '},"{"key"...' where '},{"key"...' was intended — which makes the whole
    document unparseable and previously dropped every insight in the run.
    """
    return re.sub(r'\}\s*,\s*"\s*\{\s*"', '},{"', text)


def _try_parse_json(text: str) -> dict[str, Any] | None:
    """Try to parse text as JSON, repairing glitches / stripping comments if needed."""
    try:
        result = json.loads(text.strip())
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    # Retry after stripping // comments
    try:
        result = json.loads(_strip_json_comments(text).strip())
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    # Retry after repairing known LLM JSON glitches (combined with comment strip)
    try:
        result = json.loads(_repair_llm_json(_strip_json_comments(text)).strip())
        if isinstance(result, dict):
            logger.warning("Synthesis JSON required glitch repair to parse")
            return result
    except json.JSONDecodeError:
        pass
    return None


def _salvage_insight_objects(text: str) -> list[dict[str, Any]]:
    """Last-resort recovery: parse each insight object independently.

    When a localized glitch makes the synthesis document unparseable as a
    whole even after repair, recover every individually valid insight rather
    than dropping the entire run. Uses raw_decode anchored at each
    '{"insight_type"' occurrence, so a corrupted object only loses itself —
    the scan state cannot desync across objects the way a brace-counting
    walk would after an unbalanced quote.
    """
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    for match in re.finditer(r'\{\s*"insight_type"', text):
        try:
            obj, _ = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            objects.append(obj)
    return objects


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract JSON from text that may contain other content.

    Handles various formats:
    - Pure JSON
    - JSON in code blocks (```json ... ```)
    - JSON embedded in text
    - JSON with JavaScript-style // comments

    Args:
        text: Text that may contain JSON.

    Returns:
        Parsed JSON dictionary or None if not found.
    """
    # First, try to parse the entire text as JSON
    result = _try_parse_json(text)
    if result is not None:
        return result

    # Try to find JSON in code blocks
    code_block_pattern = r"```(?:json)?\s*([\s\S]*?)```"
    matches = re.findall(code_block_pattern, text)

    for match in matches:
        result = _try_parse_json(match)
        if result is not None:
            return result

    # Try to find JSON object in the text
    # Look for content between first { and last }
    start_idx = text.find("{")
    end_idx = text.rfind("}")

    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        potential_json = text[start_idx : end_idx + 1]
        result = _try_parse_json(potential_json)
        if result is not None:
            return result

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
    catalyst_context: str | None = None,
) -> str:
    """Format the synthesis lead prompt with pattern, track record, and catalyst context.

    Substitutes the placeholders in SYNTHESIS_LEAD_PROMPT with actual
    context from institutional memory and catalyst data.

    Args:
        pattern_context: Formatted pattern context string, or None for default.
        track_record_context: Formatted track record string, or None for default.
        catalyst_context: Formatted catalyst/earnings context string, or None for default.

    Returns:
        Complete synthesis prompt with context filled in.
    """
    prompt = SYNTHESIS_LEAD_PROMPT

    # Replace catalyst context placeholder
    if catalyst_context:
        prompt = prompt.replace("{catalyst_context}", catalyst_context)
    else:
        prompt = prompt.replace(
            "{catalyst_context}",
            "No upcoming catalyst data available."
        )

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
