"""Portfolio Context Analyst — live PnL attribution, thematic clustering, opportunity fit.

Runs alongside the 5 specialist analysts when portfolio holdings are present. Computes
live P&L per position using the most recent price in the DB, groups holdings into
investment themes, identifies alpha drivers, flags concentration risk, and maps
candidate symbols to existing winning theses.

Results feed directly into the Synthesis Lead to produce better BUY_MORE/HOLD/SELL
decisions that are informed by actual portfolio context rather than single-stock analysis.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# DATACLASSES
# =============================================================================


@dataclass
class PortfolioAnalysisResult:
    """Structured output from the Portfolio Context Analyst."""

    analyst: str = "portfolio"
    portfolio_summary: str = ""
    total_cost: float = 0.0
    total_value: float = 0.0
    total_pnl_pct: float = 0.0
    themes: list[dict[str, Any]] = field(default_factory=list)
    alpha_drivers: list[dict[str, Any]] = field(default_factory=list)
    concentration_risks: list[str] = field(default_factory=list)
    opportunity_fits: list[dict[str, Any]] = field(default_factory=list)
    recommended_actions: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.75

    def to_dict(self) -> dict[str, Any]:
        return {
            "analyst": self.analyst,
            "portfolio_summary": self.portfolio_summary,
            "total_cost": self.total_cost,
            "total_value": self.total_value,
            "total_pnl_pct": self.total_pnl_pct,
            "themes": self.themes,
            "alpha_drivers": self.alpha_drivers,
            "concentration_risks": self.concentration_risks,
            "opportunity_fits": self.opportunity_fits,
            "recommended_actions": self.recommended_actions,
            "confidence": self.confidence,
        }


# =============================================================================
# PROMPT
# =============================================================================

PORTFOLIO_ANALYST_PROMPT = """You are a Portfolio Context Analyst. Your job is to analyze an existing equity portfolio and produce a structured assessment that will be consumed by the Synthesis Lead to generate better BUY_MORE / HOLD / SELL decisions.

## Your Inputs
You receive:
1. **Portfolio holdings** with current prices and live P&L data computed from DB prices
2. **Candidate symbols** being analyzed by the other analysts today
3. Quant nomination context explaining why each candidate was selected

## Your Task

### 1. Thematic Clusters
Group the portfolio's holdings into 2–5 investment themes (e.g., "Optical Interconnect Supercycle", "AI Compute Infrastructure", "Quantum Computing Speculation", "Grid/Utility Buildout"). For each theme:
- List which holdings belong to it
- Estimate aggregate P&L % for that cluster
- Assess thesis health: intact / stretched / broken
- Estimate what fraction of total portfolio alpha this theme drives

### 2. Alpha Attribution
Identify the 3–5 top alpha drivers — positions that have outperformed SPY the most. For each:
- Note P&L %
- Explain WHY it outperformed: thesis playing out? momentum/sentiment? macro tailwind?
- Assess whether the position is still undervalued, fairly valued, or stretched

### 3. Concentration & Correlation Risk
Flag:
- Theme concentration (>40% of portfolio in one theme is high risk)
- Holdings that will likely move together in a drawdown (high correlation)
- Any single position representing an outsized % of total value

### 4. New Opportunity Fit
From the candidate list, identify up to 5 symbols that either:
- **Extend** a winning theme already in portfolio (complementary addition)
- **Diversify** into an uncorrelated theme currently missing from the portfolio
- Match the portfolio's demonstrated risk appetite (e.g., if portfolio holds quantum names, additional speculative tech is acceptable)

For each opportunity, explain which existing position it complements or which gap it fills.

### 5. Per-Position Action
For EVERY held symbol provide exactly one of:
- **BUY_MORE**: thesis intact, room to run, current allocation is undersized given conviction
- **HOLD**: thesis intact but position is fairly/fully valued, or catalysts are uncertain
- **SELL**: thesis broken, overvalued, or risk/reward has materially deteriorated

## Output Format
Return a single JSON object — no prose before or after, no markdown fences:
{
  "analyst": "portfolio",
  "portfolio_summary": "One paragraph high-level narrative of portfolio health and posture.",
  "total_pnl_pct": <number>,
  "themes": [
    {
      "name": "Optical Interconnect Supercycle",
      "holdings": ["AAOI", "LITE"],
      "pnl_pct": 250.0,
      "thesis_status": "intact",
      "alpha_contribution_pct": 45.0,
      "note": "Datacenter optical demand accelerating beyond consensus estimates."
    }
  ],
  "alpha_drivers": [
    {
      "symbol": "AAOI",
      "pnl_pct": 355.0,
      "reason": "Optical interconnect demand exceeded expectations; direct beneficiary of hyperscaler 400G/800G upgrades.",
      "still_attractive": true
    }
  ],
  "concentration_risks": [
    "AI/optical theme represents ~60% of portfolio — a demand slowdown in data center buildout would simultaneously hit AAOI, LITE, MRVL, and AVGO."
  ],
  "opportunity_fits": [
    {
      "symbol": "AVGO",
      "theme": "AI Infrastructure",
      "rationale": "Extends custom ASIC + networking thesis; complements AAOI optical position with ASIC diversification.",
      "fit_type": "extends_theme"
    }
  ],
  "recommended_actions": {
    "AAOI": {"action": "HOLD", "reasoning": "Up 355%, thesis largely priced in; keep but don't add unless pullback to prior breakout level."},
    "LITE": {"action": "BUY_MORE", "reasoning": "Optical interconnect theme intact, still at reasonable multiple vs forward growth."}
  },
  "confidence": 0.82
}"""


# =============================================================================
# CONTEXT FORMATTER
# =============================================================================


def format_portfolio_context(market_context: dict[str, Any]) -> str:
    """Format portfolio holdings with live PnL data for the analyst.

    Reads _portfolio_holdings (injected by deep_engine) and price_history
    (from context builder) to compute per-position P&L, then formats as text.
    """
    holdings: dict[str, dict] = market_context.get("_portfolio_holdings", {})
    price_history: dict[str, list] = market_context.get("price_history", {})
    analyzed_symbols: list[str] = market_context.get("_analyzed_symbols", [])
    quant_ctx: str | None = market_context.get("_quant_context")

    if not holdings:
        return "No portfolio holdings available. Output minimal JSON: {\"analyst\": \"portfolio\", \"portfolio_summary\": \"No holdings.\", \"total_pnl_pct\": 0, \"themes\": [], \"alpha_drivers\": [], \"concentration_risks\": [], \"opportunity_fits\": [], \"recommended_actions\": {}, \"confidence\": 0.5}"

    # Build latest-price lookup from price_history (most recent close in DB)
    latest_prices: dict[str, float] = {}
    for sym, prices in price_history.items():
        if not prices or not isinstance(prices, list):
            continue
        for p in reversed(prices):
            close = p.get("close") if isinstance(p, dict) else None
            if close and float(close) > 0:
                latest_prices[sym.upper()] = float(close)
                break

    # Compute position-level metrics
    total_cost = sum(h["total_cost"] for h in holdings.values())
    total_value = 0.0
    positions_with_prices = 0
    position_rows: list[str] = []

    for sym, info in sorted(holdings.items(), key=lambda x: x[1]["total_cost"], reverse=True):
        shares = info["shares"]
        cost_basis = info["cost_basis"]
        pos_cost = info["total_cost"]
        alloc_pct = (pos_cost / total_cost * 100) if total_cost > 0 else 0

        current_price = latest_prices.get(sym.upper())
        if current_price:
            current_value = shares * current_price
            pnl_dollars = current_value - pos_cost
            pnl_pct = (pnl_dollars / pos_cost * 100) if pos_cost > 0 else 0
            total_value += current_value
            positions_with_prices += 1
            pnl_str = f"| P&L: {pnl_pct:+.1f}% (${pnl_dollars:+,.0f})"
        else:
            pnl_str = "| P&L: price unavailable"

        position_rows.append(
            f"  {sym}: {shares:.1f} sh @ ${cost_basis:.2f} cost "
            f"({alloc_pct:.1f}% of portfolio) {pnl_str}"
        )

    portfolio_pnl_pct = ((total_value - total_cost) / total_cost * 100) if (total_cost > 0 and total_value > 0) else 0

    lines: list[str] = [
        "## Portfolio Holdings & Live P&L",
        f"Total Cost Basis: ${total_cost:,.0f}",
    ]
    if total_value > 0:
        lines.append(f"Estimated Current Value: ${total_value:,.0f}")
        lines.append(f"Overall P&L: {portfolio_pnl_pct:+.1f}% (${total_value - total_cost:+,.0f})")
    lines.extend([
        f"Price coverage: {positions_with_prices}/{len(holdings)} positions",
        "",
        "### Positions (sorted by allocation):",
    ])
    lines.extend(position_rows)

    if analyzed_symbols:
        lines.extend([
            "",
            "## Candidate Symbols Being Analyzed Today",
            f"{', '.join(analyzed_symbols)}",
            "",
            "Identify which candidates extend existing portfolio themes or fill diversification gaps.",
        ])

    if quant_ctx:
        lines.extend([
            "",
            "## Quant Nomination Context (summary)",
            quant_ctx[:600] + ("..." if len(quant_ctx or "") > 600 else ""),
        ])

    return "\n".join(lines)


# =============================================================================
# RESPONSE PARSER
# =============================================================================


def parse_portfolio_response(response: str) -> PortfolioAnalysisResult:
    """Parse the portfolio analyst's JSON output into a structured result."""
    result = PortfolioAnalysisResult()

    # Store full response for research context
    result_dict = result.to_dict()
    result_dict["_full_response"] = response

    try:
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if not json_match:
            logger.warning("[portfolio] No JSON found in portfolio analyst response")
            result.portfolio_summary = response[:500]
            return result

        data = json.loads(json_match.group())
        result.portfolio_summary = data.get("portfolio_summary", "")
        result.total_pnl_pct = float(data.get("total_pnl_pct", 0))
        result.themes = data.get("themes", [])
        result.alpha_drivers = data.get("alpha_drivers", [])
        result.concentration_risks = data.get("concentration_risks", [])
        result.opportunity_fits = data.get("opportunity_fits", [])
        result.recommended_actions = data.get("recommended_actions", {})
        result.confidence = float(data.get("confidence", 0.75))
    except Exception as e:
        logger.warning("[portfolio] Failed to parse portfolio analyst response: %s", e)
        result.portfolio_summary = response[:500] if response else "Parse error"

    return result
