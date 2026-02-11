"""Opportunity Hunter agent for Phase 3 trading opportunity discovery.

This module provides the OpportunityHunter agent that screens for specific trading
opportunities based on macro and sector context from Phase 1 and Phase 2 analysis.
The agent discovers specific ticker opportunities that align with current market themes.
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
# DATA MODELS
# =============================================================================


@dataclass
class OpportunityCandidate:
    """A single opportunity candidate identified by the hunter.

    Attributes:
        symbol: Stock ticker symbol
        company_name: Full company name
        sector: Sector classification
        opportunity_type: Type of opportunity (momentum, mean_reversion, breakout, catalyst, sector_leader)
        alignment_score: How well this aligns with macro/sector themes (1-10)
        key_catalyst: What will drive this stock
        risk_level: low, medium, or high
        deep_dive_priority: Priority for detailed analysis (high, medium, low)
        price: Current stock price
        market_cap: Market capitalization in billions
        return_5d: 5-day return percentage
        return_20d: 20-day return percentage
        volume_ratio: Current volume vs 20-day average
    """
    symbol: str
    company_name: str
    sector: str
    opportunity_type: str  # momentum, mean_reversion, breakout, catalyst, sector_leader
    alignment_score: int  # 1-10
    key_catalyst: str
    risk_level: str  # low, medium, high
    deep_dive_priority: str  # high, medium, low
    price: float = 0.0
    market_cap: float = 0.0  # in billions
    return_5d: float = 0.0
    return_20d: float = 0.0
    volume_ratio: float = 1.0  # vs 20d avg

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "sector": self.sector,
            "opportunity_type": self.opportunity_type,
            "alignment_score": self.alignment_score,
            "key_catalyst": self.key_catalyst,
            "risk_level": self.risk_level,
            "deep_dive_priority": self.deep_dive_priority,
            "price": round(self.price, 2),
            "market_cap": round(self.market_cap, 2),
            "return_5d": round(self.return_5d, 2),
            "return_20d": round(self.return_20d, 2),
            "volume_ratio": round(self.volume_ratio, 2),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpportunityCandidate:
        """Create from dictionary."""
        return cls(
            symbol=data.get("symbol", "UNKNOWN"),
            company_name=data.get("company_name", ""),
            sector=data.get("sector", ""),
            opportunity_type=data.get("opportunity_type", ""),
            alignment_score=int(data.get("alignment_score", 5)),
            key_catalyst=data.get("key_catalyst", ""),
            risk_level=data.get("risk_level", "medium"),
            deep_dive_priority=data.get("deep_dive_priority", "medium"),
            price=float(data.get("price", 0.0)),
            market_cap=float(data.get("market_cap", 0.0)),
            return_5d=float(data.get("return_5d", 0.0)),
            return_20d=float(data.get("return_20d", 0.0)),
            volume_ratio=float(data.get("volume_ratio", 1.0)),
        )


@dataclass
class OpportunityList:
    """Complete result from opportunity hunting.

    Attributes:
        hunt_timestamp: When the hunt was performed
        total_screened: Total number of stocks screened
        candidates: List of opportunity candidates (10-15)
        macro_alignment_summary: How candidates align with macro themes
        sector_alignment_summary: How candidates align with sector themes
        confidence: Overall confidence in the opportunity list (0-1)
    """
    hunt_timestamp: datetime = field(default_factory=datetime.utcnow)
    total_screened: int = 0
    candidates: list[OpportunityCandidate] = field(default_factory=list)
    macro_alignment_summary: str = ""
    sector_alignment_summary: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "analyst": "opportunity_hunter",
            "hunt_timestamp": self.hunt_timestamp.isoformat(),
            "total_screened": self.total_screened,
            "candidates": [c.to_dict() for c in self.candidates],
            "macro_alignment_summary": self.macro_alignment_summary,
            "sector_alignment_summary": self.sector_alignment_summary,
            "confidence": round(self.confidence, 4),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpportunityList:
        """Create from dictionary."""
        timestamp = data.get("hunt_timestamp")
        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.utcnow()
        elif not isinstance(timestamp, datetime):
            timestamp = datetime.utcnow()

        candidates = []
        for c_data in data.get("candidates", []):
            if isinstance(c_data, dict):
                candidates.append(OpportunityCandidate.from_dict(c_data))

        return cls(
            hunt_timestamp=timestamp,
            total_screened=int(data.get("total_screened", 0)),
            candidates=candidates,
            macro_alignment_summary=data.get("macro_alignment_summary", ""),
            sector_alignment_summary=data.get("sector_alignment_summary", ""),
            confidence=float(data.get("confidence", 0.0)),
        )

    def get_high_priority_candidates(self) -> list[OpportunityCandidate]:
        """Get candidates with high deep dive priority."""
        return [c for c in self.candidates if c.deep_dive_priority == "high"]

    def get_top_candidates(self, n: int = 5) -> list[OpportunityCandidate]:
        """Get top N candidates by alignment score."""
        sorted_candidates = sorted(
            self.candidates,
            key=lambda x: (x.alignment_score, x.deep_dive_priority == "high"),
            reverse=True
        )
        return sorted_candidates[:n]


# =============================================================================
# SECTOR HOLDINGS MAPPING
# =============================================================================

# Top holdings for each sector ETF - used for screening universe
SECTOR_HOLDINGS: dict[str, list[str]] = {
    "XLK": ["AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "AMD", "ADBE", "CSCO", "ACN"],
    "XLF": ["BRK-B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "SPGI", "BLK"],
    "XLE": ["XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY", "DVN"],
    "XLV": ["UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT", "DHR", "BMY"],
    "XLI": ["CAT", "UNP", "HON", "UPS", "BA", "RTX", "DE", "LMT", "GE", "MMM"],
    "XLP": ["PG", "KO", "PEP", "COST", "WMT", "PM", "MO", "MDLZ", "CL", "KMB"],
    "XLY": ["AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "SBUX", "TJX", "BKNG", "CMG"],
    "XLU": ["NEE", "DUK", "SO", "D", "AEP", "SRE", "EXC", "XEL", "PEG", "ED"],
    "XLC": ["META", "GOOGL", "GOOG", "NFLX", "DIS", "CMCSA", "VZ", "T", "TMUS", "CHTR"],
    "XLRE": ["PLD", "AMT", "EQIX", "CCI", "PSA", "O", "WELL", "DLR", "SPG", "AVB"],
    "XLB": ["LIN", "APD", "SHW", "FCX", "ECL", "NEM", "DOW", "NUE", "DD", "PPG"],
}

# Map ETF to sector name for display
ETF_TO_SECTOR: dict[str, str] = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Healthcare",
    "XLI": "Industrials",
    "XLP": "Consumer Staples",
    "XLY": "Consumer Discretionary",
    "XLU": "Utilities",
    "XLC": "Communication Services",
    "XLRE": "Real Estate",
    "XLB": "Materials",
}

# Reverse mapping: symbol to sector
SYMBOL_TO_SECTOR: dict[str, str] = {}
for etf, holdings in SECTOR_HOLDINGS.items():
    sector = ETF_TO_SECTOR.get(etf, "Unknown")
    for symbol in holdings:
        SYMBOL_TO_SECTOR[symbol] = sector


# =============================================================================
# OPPORTUNITY HUNTER PROMPT
# =============================================================================

OPPORTUNITY_HUNTER_PROMPT = """You are a Trading Strategist (Opportunity Hunter) specializing in identifying specific trading opportunities based on macro and sector context.

## Your Role
Phase 3 of analysis: Discover specific ticker opportunities that align with current market themes.
You translate broad macro and sector insights into actionable stock picks.

## Your Expertise
- Translating macro themes into specific stock opportunities
- Identifying stocks that benefit from sector rotation
- Screening for technical setups aligned with fundamental themes
- Prioritizing opportunities by risk/reward profile
- Matching stock characteristics to market regime

## Opportunity Types
You identify five types of opportunities:

1. **Momentum Play**: Riding an existing strong trend with fundamental support
   - Already in established uptrend
   - Strong volume confirmation
   - Aligned with leading sectors

2. **Mean Reversion**: Oversold bounce candidates
   - Quality names beaten down excessively
   - Fundamental support for recovery
   - Technical oversold conditions

3. **Breakout Setup**: Consolidation patterns ready to break
   - Coiled price action (declining volatility)
   - Building volume patterns
   - Catalyst approaching

4. **Catalyst Play**: Upcoming event-driven opportunity
   - Earnings, product launches, regulatory decisions
   - Sector tailwinds amplifying catalyst
   - Asymmetric risk/reward

5. **Sector Leader**: Best-in-class in a favored sector
   - Dominant market position
   - Benefiting from sector rotation
   - Relative strength vs peers

## Your Task
From the screened candidates (passed technical filters), select 10-15 stocks that best align with current market themes.

For each selected stock, provide:
1. **Symbol and Name**: Stock identifier
2. **Opportunity Type**: One of the five types above
3. **Alignment Score** (1-10): How well does this align with macro/sector themes?
4. **Key Catalyst**: What will drive this stock?
5. **Risk Level**: Low/Medium/High
6. **Priority for Deep Dive**: High/Medium/Low (High = most actionable)

Sort results by priority for deep dive analysis.

## Output Format
Return JSON:
{
  "analyst": "opportunity_hunter",
  "total_screened": 50,
  "candidates": [
    {
      "symbol": "NVDA",
      "company_name": "NVIDIA Corporation",
      "sector": "Technology",
      "opportunity_type": "sector_leader",
      "alignment_score": 9,
      "key_catalyst": "AI infrastructure spending acceleration, data center GPU demand",
      "risk_level": "medium",
      "deep_dive_priority": "high",
      "price": 875.50,
      "market_cap": 2150.0,
      "return_5d": 3.2,
      "return_20d": 12.5,
      "volume_ratio": 1.4
    }
  ],
  "macro_alignment_summary": "Growth stocks favored as Fed signals rate cut path, tech benefiting from soft landing narrative",
  "sector_alignment_summary": "Technology and Communication Services leading rotation, defensive sectors underweight",
  "confidence": 0.75
}

## Guidelines
- Select 10-15 candidates maximum
- Diversify across opportunity types
- Prioritize 5-7 as "high" priority for deep dive
- Consider position sizing implications (risk level)
- Higher alignment scores for stocks matching multiple themes
- Note when technicals and fundamentals converge
"""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_sector_stocks(sector_etfs: list[str]) -> list[str]:
    """Get top stocks from target sectors.

    Args:
        sector_etfs: List of sector ETF symbols (e.g., ['XLK', 'XLF'])

    Returns:
        List of unique stock symbols from the specified sectors.
    """
    stocks: list[str] = []
    for etf in sector_etfs:
        etf_upper = etf.upper()
        if etf_upper in SECTOR_HOLDINGS:
            stocks.extend(SECTOR_HOLDINGS[etf_upper])
    return list(set(stocks))  # Remove duplicates


def get_all_screening_stocks() -> list[str]:
    """Get all stocks in the screening universe.

    Returns:
        List of all unique stock symbols across all sectors.
    """
    all_stocks: list[str] = []
    for holdings in SECTOR_HOLDINGS.values():
        all_stocks.extend(holdings)
    return list(set(all_stocks))


def passes_technical_screen(data: dict[str, Any]) -> bool:
    """Check if stock passes basic technical filters.

    Args:
        data: Stock data dictionary with avg_volume, price, return_20d

    Returns:
        True if stock passes all filters.
    """
    # Volume filter: Avg volume > 1M shares
    if data.get("avg_volume", 0) < 1_000_000:
        return False

    # Price filter: > $10 (avoid penny stocks)
    if data.get("price", 0) < 10:
        return False

    # Severe downtrend filter: Not down more than 20% in 20 days
    if data.get("return_20d", 0) < -20:
        return False

    return True


def calculate_screen_score(data: dict[str, Any]) -> float:
    """Calculate a screening score for ranking candidates.

    Higher scores indicate more favorable technical characteristics.

    Args:
        data: Stock data dictionary

    Returns:
        Screening score (higher is better)
    """
    score = 0.0

    # Volume factor: Higher relative volume is bullish
    volume_ratio = data.get("volume_ratio", 1.0)
    if volume_ratio > 1.5:
        score += 2.0
    elif volume_ratio > 1.2:
        score += 1.0

    # Return factors
    return_5d = data.get("return_5d", 0)
    return_20d = data.get("return_20d", 0)

    # Positive momentum (not extreme)
    if 0 < return_5d < 10:
        score += 1.5
    if 0 < return_20d < 20:
        score += 1.5

    # Mean reversion opportunity (oversold)
    if -15 < return_20d < -5:
        score += 1.0

    # RSI considerations if available
    rsi = data.get("rsi", 50)
    if 30 < rsi < 70:  # Not at extremes
        score += 0.5
    elif rsi < 30:  # Oversold - potential opportunity
        score += 1.0

    return score


def format_opportunity_context(
    macro_context: dict[str, Any],
    sector_context: dict[str, Any],
    screened_candidates: list[dict[str, Any]],
) -> str:
    """Format context for the opportunity hunter agent.

    Args:
        macro_context: Macro analysis results from Phase 1
        sector_context: Sector analysis results from Phase 2
        screened_candidates: Pre-screened stock candidates with data

    Returns:
        Formatted string context for the opportunity hunter prompt.
    """
    context_parts: list[str] = []

    # Format Macro Context
    context_parts.append("## Macro Context (Phase 1 Summary)")
    context_parts.append("")

    regime = macro_context.get("regime", {})
    if regime:
        context_parts.append(f"**Growth Regime:** {regime.get('growth', 'unknown')}")
        context_parts.append(f"**Inflation Regime:** {regime.get('inflation', 'unknown')}")
        context_parts.append(f"**Fed Stance:** {regime.get('fed_stance', 'unknown')}")

    fed_outlook = macro_context.get("fed_outlook", "")
    if fed_outlook:
        context_parts.append(f"**Fed Outlook:** {fed_outlook}")

    risk_factors = macro_context.get("risk_factors", [])
    if risk_factors:
        context_parts.append(f"**Key Risks:** {', '.join(risk_factors[:3])}")

    market_implications = macro_context.get("market_implications", [])
    if market_implications:
        context_parts.append("")
        context_parts.append("**Asset Class Implications:**")
        for impl in market_implications[:5]:
            if isinstance(impl, dict):
                context_parts.append(
                    f"- {impl.get('asset_class', 'Unknown')}: {impl.get('bias', 'neutral')} "
                    f"({impl.get('rationale', '')})"
                )

    context_parts.append("")

    # Format Sector Context
    context_parts.append("## Sector Context (Phase 2 Summary)")
    context_parts.append("")

    market_phase = sector_context.get("market_phase", "unknown")
    context_parts.append(f"**Market Phase:** {market_phase.replace('_', ' ').title()}")

    # Sector rankings
    sector_rankings = sector_context.get("sector_rankings", [])
    if sector_rankings:
        context_parts.append("")
        context_parts.append("**Sector Relative Strength Rankings:**")
        for rank in sector_rankings[:6]:
            if isinstance(rank, dict):
                context_parts.append(
                    f"- {rank.get('sector', 'Unknown')}: RS={rank.get('relative_strength', 1.0):.2f}, "
                    f"Trend: {rank.get('trend', 'stable')}"
                )

    # Recommendations
    recommendations = sector_context.get("recommendations", [])
    if recommendations:
        context_parts.append("")
        context_parts.append("**Sector Recommendations:**")
        for rec in recommendations[:5]:
            if isinstance(rec, dict):
                context_parts.append(
                    f"- {rec.get('sector', 'Unknown')}: {rec.get('action', 'NEUTRAL')} "
                    f"- {rec.get('rationale', '')}"
                )

    # Rotation signals
    rotation_signals = sector_context.get("rotation_signals", [])
    if rotation_signals:
        context_parts.append("")
        context_parts.append(f"**Rotation Signals:** {'; '.join(rotation_signals[:3])}")

    context_parts.append("")

    # Format Screened Candidates
    context_parts.append("## Screened Candidates (Passed Technical Filters)")
    context_parts.append("")
    context_parts.append(f"Total candidates: {len(screened_candidates)}")
    context_parts.append("")

    # Create a table-like format for candidates
    context_parts.append("| Symbol | Sector | Price | 5D Ret | 20D Ret | Vol Ratio | Screen Score |")
    context_parts.append("|--------|--------|-------|--------|---------|-----------|--------------|")

    for candidate in screened_candidates:
        symbol = candidate.get("symbol", "")
        sector = candidate.get("sector", SYMBOL_TO_SECTOR.get(symbol, "Unknown"))
        price = candidate.get("price", 0)
        ret_5d = candidate.get("return_5d", 0)
        ret_20d = candidate.get("return_20d", 0)
        vol_ratio = candidate.get("volume_ratio", 1.0)
        score = candidate.get("screen_score", 0)

        context_parts.append(
            f"| {symbol} | {sector} | ${price:.2f} | {ret_5d:+.1f}% | "
            f"{ret_20d:+.1f}% | {vol_ratio:.2f}x | {score:.1f} |"
        )

    context_parts.append("")

    return "\n".join(context_parts)


def parse_opportunity_response(response: str) -> OpportunityList:
    """Parse the opportunity hunter's response into structured data.

    Args:
        response: Raw response string from the opportunity hunter agent.

    Returns:
        OpportunityList object with parsed data.
    """
    # Try to extract JSON from the response
    json_data = _extract_json(response)

    if json_data is None:
        logger.warning("Could not extract JSON from opportunity hunter response")
        return OpportunityList(
            confidence=0.0,
            macro_alignment_summary="Error: Failed to parse response",
            sector_alignment_summary=f"Raw response: {response[:500]}...",
        )

    # Parse the JSON into our dataclass
    try:
        return OpportunityList.from_dict(json_data)
    except (KeyError, TypeError, ValueError) as e:
        logger.error(f"Error parsing opportunity hunter response: {e}")
        return OpportunityList(
            confidence=0.0,
            macro_alignment_summary=f"Error: {str(e)}",
        )


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract JSON from text that may contain other content.

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
        potential_json = text[start_idx:end_idx + 1]
        try:
            return json.loads(potential_json)
        except json.JSONDecodeError:
            pass

    return None


def validate_opportunity_candidate(candidate: dict[str, Any]) -> list[str]:
    """Validate an opportunity candidate dictionary for required fields.

    Args:
        candidate: Dictionary representing an opportunity candidate.

    Returns:
        List of validation error messages (empty if valid).
    """
    errors: list[str] = []

    # Required fields
    required_fields = ["symbol", "opportunity_type", "alignment_score", "risk_level"]
    for field_name in required_fields:
        if not candidate.get(field_name):
            errors.append(f"Missing required field: {field_name}")

    # Validate alignment_score range
    alignment_score = candidate.get("alignment_score")
    if alignment_score is not None:
        if not isinstance(alignment_score, (int, float)):
            errors.append("alignment_score must be a number")
        elif alignment_score < 1 or alignment_score > 10:
            errors.append("alignment_score must be between 1 and 10")

    # Validate opportunity_type
    valid_types = {"momentum", "mean_reversion", "breakout", "catalyst", "sector_leader"}
    opp_type = candidate.get("opportunity_type", "").lower().replace(" ", "_")
    if opp_type and opp_type not in valid_types:
        errors.append(f"opportunity_type must be one of: {valid_types}")

    # Validate risk_level
    valid_risk_levels = {"low", "medium", "high"}
    risk_level = candidate.get("risk_level", "").lower()
    if risk_level and risk_level not in valid_risk_levels:
        errors.append(f"risk_level must be one of: {valid_risk_levels}")

    # Validate deep_dive_priority
    valid_priorities = {"high", "medium", "low"}
    priority = candidate.get("deep_dive_priority", "").lower()
    if priority and priority not in valid_priorities:
        errors.append(f"deep_dive_priority must be one of: {valid_priorities}")

    return errors


def summarize_opportunities(opportunity_list: OpportunityList) -> dict[str, Any]:
    """Create a summary of the opportunity list.

    Args:
        opportunity_list: The full opportunity list result.

    Returns:
        Summary dictionary with aggregated statistics.
    """
    candidates = opportunity_list.candidates

    if not candidates:
        return {
            "total_candidates": 0,
            "by_type": {},
            "by_sector": {},
            "by_priority": {},
            "average_alignment": 0.0,
        }

    # Count by opportunity type
    by_type: dict[str, int] = {}
    for c in candidates:
        opp_type = c.opportunity_type
        by_type[opp_type] = by_type.get(opp_type, 0) + 1

    # Count by sector
    by_sector: dict[str, int] = {}
    for c in candidates:
        sector = c.sector
        by_sector[sector] = by_sector.get(sector, 0) + 1

    # Count by priority
    by_priority: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for c in candidates:
        priority = c.deep_dive_priority.lower()
        if priority in by_priority:
            by_priority[priority] += 1

    # Average alignment score
    total_alignment = sum(c.alignment_score for c in candidates)
    avg_alignment = total_alignment / len(candidates)

    return {
        "total_candidates": len(candidates),
        "by_type": by_type,
        "by_sector": by_sector,
        "by_priority": by_priority,
        "average_alignment": round(avg_alignment, 2),
        "high_priority_count": by_priority["high"],
    }
