"""Sector Rotator agent for sector momentum and rotation analysis.

This module provides the Phase 2 autonomous analysis agent that analyzes
sector momentum and rotation patterns to identify where capital is flowing.
It receives macro context from Phase 1 (MacroScanner) and outputs sector
recommendations for Phase 3 (OpportunityHunter).

Data Sources (Free via yfinance):
- Sector ETFs (SPDR Select Sector): XLK, XLF, XLE, XLV, XLI, XLP, XLY, XLU, XLC, XLRE, XLB
- Benchmark: SPY (S&P 500)
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
# SECTOR ETF MAPPINGS
# =============================================================================

SECTOR_ETFS: dict[str, str] = {
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

# Sector characteristics for rotation analysis
SECTOR_CHARACTERISTICS: dict[str, dict[str, Any]] = {
    "XLK": {
        "cyclicality": "growth",
        "rate_sensitivity": "high",
        "inflation_hedge": False,
        "typical_leaders_in": ["expansion", "risk_on"],
    },
    "XLF": {
        "cyclicality": "cyclical",
        "rate_sensitivity": "high",
        "inflation_hedge": False,
        "typical_leaders_in": ["early_expansion", "rising_rates"],
    },
    "XLE": {
        "cyclicality": "cyclical",
        "rate_sensitivity": "low",
        "inflation_hedge": True,
        "typical_leaders_in": ["late_expansion", "inflation"],
    },
    "XLV": {
        "cyclicality": "defensive",
        "rate_sensitivity": "low",
        "inflation_hedge": False,
        "typical_leaders_in": ["contraction", "risk_off"],
    },
    "XLI": {
        "cyclicality": "cyclical",
        "rate_sensitivity": "medium",
        "inflation_hedge": False,
        "typical_leaders_in": ["mid_expansion", "infrastructure"],
    },
    "XLP": {
        "cyclicality": "defensive",
        "rate_sensitivity": "low",
        "inflation_hedge": False,
        "typical_leaders_in": ["contraction", "risk_off"],
    },
    "XLY": {
        "cyclicality": "cyclical",
        "rate_sensitivity": "medium",
        "inflation_hedge": False,
        "typical_leaders_in": ["early_expansion", "consumer_strength"],
    },
    "XLU": {
        "cyclicality": "defensive",
        "rate_sensitivity": "high",
        "inflation_hedge": False,
        "typical_leaders_in": ["contraction", "falling_rates"],
    },
    "XLC": {
        "cyclicality": "growth",
        "rate_sensitivity": "medium",
        "inflation_hedge": False,
        "typical_leaders_in": ["expansion", "tech_led_growth"],
    },
    "XLRE": {
        "cyclicality": "defensive",
        "rate_sensitivity": "high",
        "inflation_hedge": True,
        "typical_leaders_in": ["falling_rates", "yield_seeking"],
    },
    "XLB": {
        "cyclicality": "cyclical",
        "rate_sensitivity": "medium",
        "inflation_hedge": True,
        "typical_leaders_in": ["late_expansion", "inflation", "infrastructure"],
    },
}


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class SectorData:
    """Raw performance data for a sector ETF."""

    symbol: str
    name: str
    current_price: float = 0.0
    return_1d: float = 0.0
    return_5d: float = 0.0
    return_20d: float = 0.0
    return_60d: float = 0.0
    volume: int = 0
    avg_volume_20d: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "name": self.name,
            "current_price": self.current_price,
            "return_1d": self.return_1d,
            "return_5d": self.return_5d,
            "return_20d": self.return_20d,
            "return_60d": self.return_60d,
            "volume": self.volume,
            "avg_volume_20d": self.avg_volume_20d,
        }


@dataclass
class RelativeStrength:
    """Relative strength metrics vs SPY."""

    symbol: str
    rs_5d: float = 0.0  # 5-day relative strength
    rs_20d: float = 0.0  # 20-day relative strength
    rs_60d: float = 0.0  # 60-day relative strength
    outperforming: bool = False  # Currently outperforming SPY

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "rs_5d": round(self.rs_5d, 2),
            "rs_20d": round(self.rs_20d, 2),
            "rs_60d": round(self.rs_60d, 2),
            "outperforming": self.outperforming,
        }


@dataclass
class MomentumScore:
    """Momentum analysis for a sector."""

    symbol: str
    score: float = 0.0  # Composite momentum score
    trend: str = "neutral"  # up, down, neutral
    strength: str = "weak"  # strong, moderate, weak

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "score": round(self.score, 2),
            "trend": self.trend,
            "strength": self.strength,
        }


@dataclass
class SectorRecommendation:
    """Investment recommendation for a sector."""

    sector_name: str
    etf_symbol: str
    recommendation: str  # overweight, underweight, neutral
    momentum_score: float
    relative_strength_20d: float
    rationale: str
    key_stocks: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "sector_name": self.sector_name,
            "etf_symbol": self.etf_symbol,
            "recommendation": self.recommendation,
            "momentum_score": round(self.momentum_score, 2),
            "relative_strength_20d": round(self.relative_strength_20d, 2),
            "rationale": self.rationale,
            "key_stocks": self.key_stocks,
            "risks": self.risks,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SectorRecommendation:
        """Create from dictionary."""
        return cls(
            sector_name=data.get("sector_name", "Unknown"),
            etf_symbol=data.get("etf_symbol", ""),
            recommendation=data.get("recommendation", "neutral"),
            momentum_score=float(data.get("momentum_score", 0.0)),
            relative_strength_20d=float(data.get("relative_strength_20d", 0.0)),
            rationale=data.get("rationale", ""),
            key_stocks=data.get("key_stocks", []),
            risks=data.get("risks", []),
        )


@dataclass
class SectorRotationResult:
    """Complete result from sector rotation analysis."""

    analysis_timestamp: datetime = field(default_factory=datetime.utcnow)
    analyst: str = "sector_rotator"
    top_sectors: list[SectorRecommendation] = field(default_factory=list)  # Top 3
    sectors_to_avoid: list[SectorRecommendation] = field(default_factory=list)  # Bottom 2
    rotation_active: bool = False
    rotation_from: list[str] = field(default_factory=list)
    rotation_to: list[str] = field(default_factory=list)
    rotation_stage: str = "none"  # early, mid, late, none
    sector_pair_trade: dict[str, Any] | None = None  # {long: str, short: str, rationale: str}
    key_observations: list[str] = field(default_factory=list)
    confidence: float = 0.5
    raw_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "analyst": self.analyst,
            "analysis_timestamp": self.analysis_timestamp.isoformat(),
            "top_sectors": [s.to_dict() for s in self.top_sectors],
            "sectors_to_avoid": [s.to_dict() for s in self.sectors_to_avoid],
            "rotation_active": self.rotation_active,
            "rotation_from": self.rotation_from,
            "rotation_to": self.rotation_to,
            "rotation_stage": self.rotation_stage,
            "sector_pair_trade": self.sector_pair_trade,
            "key_observations": self.key_observations,
            "confidence": round(self.confidence, 2),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SectorRotationResult:
        """Create from dictionary."""
        timestamp = data.get("analysis_timestamp")
        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.utcnow()
        elif not isinstance(timestamp, datetime):
            timestamp = datetime.utcnow()

        top_sectors = [
            SectorRecommendation.from_dict(s) for s in data.get("top_sectors", [])
        ]
        sectors_to_avoid = [
            SectorRecommendation.from_dict(s) for s in data.get("sectors_to_avoid", [])
        ]

        return cls(
            analyst=data.get("analyst", "sector_rotator"),
            analysis_timestamp=timestamp,
            top_sectors=top_sectors,
            sectors_to_avoid=sectors_to_avoid,
            rotation_active=data.get("rotation_active", False),
            rotation_from=data.get("rotation_from", []),
            rotation_to=data.get("rotation_to", []),
            rotation_stage=data.get("rotation_stage", "none"),
            sector_pair_trade=data.get("sector_pair_trade"),
            key_observations=data.get("key_observations", []),
            confidence=float(data.get("confidence", 0.5)),
            raw_data=data.get("raw_data", {}),
        )


# =============================================================================
# SECTOR ROTATOR PROMPT
# =============================================================================

SECTOR_ROTATOR_PROMPT = """You are a Sector Strategist specializing in sector momentum and rotation analysis.

## Your Expertise
- Sector momentum analysis and relative strength ranking
- Capital flow detection between sectors
- Business cycle sector rotation patterns
- Risk-on vs risk-off environment assessment
- Sector correlation and divergence analysis

## Sector ETFs You Track (SPDR Select Sector)
- XLK: Technology
- XLF: Financials
- XLE: Energy
- XLV: Healthcare
- XLI: Industrials
- XLP: Consumer Staples
- XLY: Consumer Discretionary
- XLU: Utilities
- XLC: Communication Services
- XLRE: Real Estate
- XLB: Materials

Benchmark: SPY (S&P 500)

## Business Cycle Sector Leadership
- Early Expansion: Financials, Consumer Discretionary, Technology
- Mid Expansion: Technology, Industrials, Communication Services
- Late Expansion: Energy, Materials, Industrials
- Contraction: Utilities, Healthcare, Consumer Staples (defensives)

## Your Task
Based on the macro context and sector performance data provided, identify:

1. **TOP 3 SECTORS** to focus on:
   For each sector:
   - Sector name and ETF symbol
   - Why it's attractive (momentum + macro alignment)
   - Key stocks to consider in this sector
   - Risk factors to watch

2. **SECTORS TO AVOID** (2 sectors):
   - Why capital is flowing out
   - Headwinds they face

3. **ROTATION SIGNAL**:
   - Is there active rotation happening? (yes/no)
   - From which sectors -> to which sectors?
   - Stage of rotation (early/mid/late)

4. **SECTOR PAIRS TRADE** (optional):
   - Long sector vs Short sector if clear divergence exists
   - Only recommend if high conviction (>70% confidence)

## Output Format
Return JSON:
{
  "analyst": "sector_rotator",
  "top_sectors": [
    {
      "sector_name": "Technology",
      "etf_symbol": "XLK",
      "recommendation": "overweight",
      "momentum_score": 3.5,
      "relative_strength_20d": 2.1,
      "rationale": "Strong momentum aligned with growth-favorable macro environment",
      "key_stocks": ["NVDA", "MSFT", "AAPL"],
      "risks": ["Elevated valuations", "Rate sensitivity"]
    }
  ],
  "sectors_to_avoid": [
    {
      "sector_name": "Utilities",
      "etf_symbol": "XLU",
      "recommendation": "underweight",
      "momentum_score": -2.1,
      "relative_strength_20d": -3.5,
      "rationale": "Rising rates headwind, money rotating to growth",
      "key_stocks": [],
      "risks": []
    }
  ],
  "rotation_active": true,
  "rotation_from": ["Utilities", "Real Estate"],
  "rotation_to": ["Technology", "Industrials"],
  "rotation_stage": "mid",
  "sector_pair_trade": {
    "long": "XLK",
    "short": "XLU",
    "rationale": "Tech vs Utilities spread widening on rate expectations"
  },
  "key_observations": [
    "Risk-on environment with cyclicals outperforming defensives",
    "Technology maintaining leadership with strong relative strength"
  ],
  "confidence": 0.75
}

## Guidelines
- Focus on momentum and relative strength metrics
- Align sector recommendations with macro context from Phase 1
- Be specific about which stocks to watch in each sector
- Identify rotation patterns and their stage
- Only recommend pairs trades when there's clear divergence
- Use confidence scores between 0.0 and 1.0
- Higher confidence (>0.7) for clear rotation signals with volume confirmation
- Lower confidence (<0.5) for mixed or unclear signals
"""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def calculate_relative_strength(
    sector_data: dict[str, SectorData],
    spy_data: SectorData | None,
) -> dict[str, RelativeStrength]:
    """Calculate relative strength vs SPY for each sector.

    Args:
        sector_data: Dictionary mapping ETF symbols to SectorData.
        spy_data: SPY benchmark data.

    Returns:
        Dictionary mapping ETF symbols to RelativeStrength objects.
    """
    if not spy_data:
        # Return neutral relative strength if no benchmark
        return {
            symbol: RelativeStrength(symbol=symbol)
            for symbol in sector_data.keys()
        }

    relative_strength: dict[str, RelativeStrength] = {}

    for symbol, data in sector_data.items():
        rs = RelativeStrength(
            symbol=symbol,
            rs_5d=data.return_5d - spy_data.return_5d,
            rs_20d=data.return_20d - spy_data.return_20d,
            rs_60d=data.return_60d - spy_data.return_60d,
            outperforming=data.return_20d > spy_data.return_20d,
        )
        relative_strength[symbol] = rs

    return relative_strength


def calculate_momentum(sector_data: dict[str, SectorData]) -> dict[str, MomentumScore]:
    """Calculate momentum scores for each sector.

    Momentum score is a weighted average of returns:
    - 40% weight on 5-day return (recent momentum)
    - 60% weight on 20-day return (trend confirmation)

    Args:
        sector_data: Dictionary mapping ETF symbols to SectorData.

    Returns:
        Dictionary mapping ETF symbols to MomentumScore objects.
    """
    momentum: dict[str, MomentumScore] = {}

    for symbol, data in sector_data.items():
        # Weighted momentum score
        score = (data.return_5d * 0.4) + (data.return_20d * 0.6)

        # Determine trend direction
        if score > 0.5:
            trend = "up"
        elif score < -0.5:
            trend = "down"
        else:
            trend = "neutral"

        # Determine strength
        abs_score = abs(score)
        if abs_score > 3:
            strength = "strong"
        elif abs_score > 1:
            strength = "moderate"
        else:
            strength = "weak"

        momentum[symbol] = MomentumScore(
            symbol=symbol,
            score=score,
            trend=trend,
            strength=strength,
        )

    return momentum


def format_sector_rotator_context(
    market_data: dict[str, Any],
    macro_context: dict[str, Any] | None = None,
) -> str:
    """Format market data for sector rotator consumption.

    Takes raw market data from context builder and formats it into a structured
    string that the sector rotator agent can analyze.

    Args:
        market_data: Dictionary containing market data from context builder with keys:
            - sector_performance: Dict mapping sector ETFs to performance metrics
            - price_history: Dict mapping symbols to OHLCV data
            - market_summary: Overall market status
        macro_context: Optional macro analysis results from Phase 1.

    Returns:
        Formatted string context for the sector rotator prompt.
    """
    context_parts: list[str] = []

    # Add macro context from Phase 1 if available
    if macro_context:
        context_parts.append("## Macro Context (from Phase 1)")
        context_parts.append("")

        regime = macro_context.get("regime", {})
        if regime:
            context_parts.append(f"Growth Environment: {regime.get('growth', 'unknown')}")
            context_parts.append(f"Inflation Environment: {regime.get('inflation', 'unknown')}")
            context_parts.append(f"Fed Stance: {regime.get('fed_stance', 'unknown')}")

        fed_outlook = macro_context.get("fed_outlook", "")
        if fed_outlook:
            context_parts.append(f"Fed Outlook: {fed_outlook}")

        market_implications = macro_context.get("market_implications", [])
        if market_implications:
            context_parts.append("Market Implications:")
            for impl in market_implications:
                if isinstance(impl, dict):
                    context_parts.append(
                        f"  - {impl.get('asset_class', 'N/A')}: "
                        f"{impl.get('bias', 'N/A')} - {impl.get('rationale', '')}"
                    )

        context_parts.append("")

    # Sector performance data
    sector_performance = market_data.get("sector_performance", {})
    if sector_performance:
        context_parts.append("## Sector ETF Performance")
        context_parts.append("")
        context_parts.append("| Symbol | Sector | Daily | Weekly | Monthly | Volume |")
        context_parts.append("|--------|--------|-------|--------|---------|--------|")

        # Sort by monthly return for easy ranking
        sorted_sectors = sorted(
            sector_performance.items(),
            key=lambda x: x[1].get("monthly_change_pct", 0) if isinstance(x[1], dict) else 0,
            reverse=True,
        )

        for symbol, metrics in sorted_sectors:
            if not isinstance(metrics, dict):
                continue
            sector = metrics.get("sector", SECTOR_ETFS.get(symbol, ""))
            daily_pct = metrics.get("daily_change_pct", 0)
            weekly_pct = metrics.get("weekly_change_pct", 0)
            monthly_pct = metrics.get("monthly_change_pct", 0)
            volume = metrics.get("volume", 0)

            context_parts.append(
                f"| {symbol} | {sector} | {daily_pct:+.2f}% | "
                f"{weekly_pct:+.2f}% | {monthly_pct:+.2f}% | {volume:,} |"
            )

        context_parts.append("")

        # Calculate and display relative strength vs SPY
        spy_performance = sector_performance.get("SPY", {})
        if spy_performance:
            spy_monthly = spy_performance.get("monthly_change_pct", 0)
            context_parts.append("## Relative Strength vs S&P 500 (20-day)")
            context_parts.append("")
            context_parts.append("| Symbol | Sector | RS vs SPY | Status |")
            context_parts.append("|--------|--------|-----------|--------|")

            for symbol, metrics in sorted_sectors:
                if symbol == "SPY" or not isinstance(metrics, dict):
                    continue
                sector = metrics.get("sector", SECTOR_ETFS.get(symbol, ""))
                monthly_pct = metrics.get("monthly_change_pct", 0)
                rs = monthly_pct - spy_monthly
                status = "Outperforming" if rs > 0 else "Underperforming"

                context_parts.append(
                    f"| {symbol} | {sector} | {rs:+.2f}% | {status} |"
                )

            context_parts.append("")

        # Calculate momentum scores
        context_parts.append("## Momentum Scores")
        context_parts.append("")
        context_parts.append("| Symbol | Sector | Score | Trend | Strength |")
        context_parts.append("|--------|--------|-------|-------|----------|")

        for symbol, metrics in sorted_sectors:
            if symbol == "SPY" or not isinstance(metrics, dict):
                continue
            sector = metrics.get("sector", SECTOR_ETFS.get(symbol, ""))
            daily_pct = metrics.get("daily_change_pct", 0)
            weekly_pct = metrics.get("weekly_change_pct", 0)
            monthly_pct = metrics.get("monthly_change_pct", 0)

            # Simple momentum: weighted average
            score = (weekly_pct * 0.4) + (monthly_pct * 0.6)
            trend = "Up" if score > 0.5 else ("Down" if score < -0.5 else "Neutral")
            strength = "Strong" if abs(score) > 3 else ("Moderate" if abs(score) > 1 else "Weak")

            context_parts.append(
                f"| {symbol} | {sector} | {score:+.2f} | {trend} | {strength} |"
            )

        context_parts.append("")

    # Market benchmark
    market_summary = market_data.get("market_summary", {})
    market_index = market_summary.get("market_index", {})
    if market_index:
        context_parts.append("## Benchmark (SPY)")
        context_parts.append("")
        context_parts.append(f"Current Price: ${market_index.get('current', 0):.2f}")
        context_parts.append(f"Daily Change: {market_index.get('change_pct', 0):+.2f}%")
        context_parts.append(f"Volume: {market_index.get('volume', 0):,}")
        context_parts.append("")

    # Add sector characteristics reference
    context_parts.append("## Sector Characteristics Reference")
    context_parts.append("")
    context_parts.append("| Symbol | Type | Rate Sensitive | Inflation Hedge |")
    context_parts.append("|--------|------|----------------|-----------------|")

    for symbol, chars in SECTOR_CHARACTERISTICS.items():
        cyclicality = chars.get("cyclicality", "unknown")
        rate_sens = chars.get("rate_sensitivity", "medium")
        inflation = "Yes" if chars.get("inflation_hedge", False) else "No"
        context_parts.append(
            f"| {symbol} | {cyclicality.title()} | {rate_sens.title()} | {inflation} |"
        )

    context_parts.append("")

    if not context_parts or context_parts == [""]:
        return "No sector data available for rotation analysis."

    return "\n".join(context_parts)


def parse_sector_rotator_response(response: str) -> SectorRotationResult:
    """Parse the sector rotator's response into structured data.

    Extracts the JSON from the agent's response and converts it into a
    SectorRotationResult object.

    Args:
        response: Raw response string from the sector rotator agent.

    Returns:
        SectorRotationResult object with parsed data.
    """
    # Try to extract JSON from the response
    json_data = _extract_json(response)

    if json_data is None:
        logger.warning("Could not extract JSON from sector rotator response")
        return SectorRotationResult(
            analyst="sector_rotator",
            key_observations=[f"Raw response: {response[:500]}..."],
            confidence=0.0,
        )

    # Parse the JSON into our dataclass
    try:
        return SectorRotationResult.from_dict(json_data)
    except (KeyError, TypeError, ValueError) as e:
        logger.error(f"Error parsing sector rotator response: {e}")
        return SectorRotationResult(
            analyst="sector_rotator",
            key_observations=[f"Parse error: {str(e)}"],
            confidence=0.0,
        )


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


def _default_error_response(error_message: str) -> dict[str, Any]:
    """Create a default error response.

    Args:
        error_message: Description of the error.

    Returns:
        Dictionary with error information and default values.
    """
    return {
        "analyst": "sector_rotator",
        "top_sectors": [],
        "sectors_to_avoid": [],
        "rotation_active": False,
        "rotation_from": [],
        "rotation_to": [],
        "rotation_stage": "none",
        "sector_pair_trade": None,
        "key_observations": [f"Error: {error_message}"],
        "confidence": 0.0,
        "error": error_message,
    }


def get_sector_leaders_for_regime(regime: str) -> list[str]:
    """Get expected sector leaders for a given macro regime.

    Args:
        regime: Macro regime (e.g., 'expansion', 'contraction', 'inflation').

    Returns:
        List of ETF symbols expected to lead in this regime.
    """
    regime_leaders: dict[str, list[str]] = {
        "early_expansion": ["XLF", "XLY", "XLK"],
        "mid_expansion": ["XLK", "XLI", "XLC"],
        "late_expansion": ["XLE", "XLB", "XLI"],
        "contraction": ["XLV", "XLP", "XLU"],
        "expansion": ["XLK", "XLY", "XLI"],
        "inflation": ["XLE", "XLB", "XLRE"],
        "risk_on": ["XLK", "XLY", "XLC"],
        "risk_off": ["XLV", "XLP", "XLU"],
        "rising_rates": ["XLF", "XLE"],
        "falling_rates": ["XLU", "XLRE", "XLK"],
    }

    return regime_leaders.get(regime.lower(), [])


def identify_rotation_pattern(
    relative_strength: dict[str, RelativeStrength],
) -> dict[str, Any]:
    """Identify rotation patterns from relative strength data.

    Args:
        relative_strength: Dictionary mapping symbols to RelativeStrength.

    Returns:
        Dictionary with rotation analysis:
            - rotation_active: bool
            - rotation_from: list of sectors losing strength
            - rotation_to: list of sectors gaining strength
            - rotation_stage: early/mid/late
            - pattern_type: risk_on/risk_off/cyclical/defensive
    """
    # Classify sectors by recent performance
    gaining_strength: list[str] = []
    losing_strength: list[str] = []

    for symbol, rs in relative_strength.items():
        # Compare short-term vs medium-term RS
        # If RS_5d > RS_20d, gaining relative momentum
        if rs.rs_5d > rs.rs_20d + 0.5:
            gaining_strength.append(symbol)
        elif rs.rs_5d < rs.rs_20d - 0.5:
            losing_strength.append(symbol)

    if not gaining_strength and not losing_strength:
        return {
            "rotation_active": False,
            "rotation_from": [],
            "rotation_to": [],
            "rotation_stage": "none",
            "pattern_type": "stable",
        }

    # Determine rotation type
    cyclical_sectors = {"XLF", "XLY", "XLI", "XLE", "XLB"}
    defensive_sectors = {"XLV", "XLP", "XLU", "XLRE"}
    growth_sectors = {"XLK", "XLC"}

    gaining_cyclical = len(set(gaining_strength) & cyclical_sectors)
    gaining_defensive = len(set(gaining_strength) & defensive_sectors)
    gaining_growth = len(set(gaining_strength) & growth_sectors)

    if gaining_cyclical > gaining_defensive:
        pattern_type = "risk_on"
    elif gaining_defensive > gaining_cyclical:
        pattern_type = "risk_off"
    elif gaining_growth >= 1:
        pattern_type = "growth_rotation"
    else:
        pattern_type = "mixed"

    # Determine rotation stage based on breadth
    total_moving = len(gaining_strength) + len(losing_strength)
    if total_moving <= 3:
        stage = "early"
    elif total_moving <= 6:
        stage = "mid"
    else:
        stage = "late"

    return {
        "rotation_active": True,
        "rotation_from": [SECTOR_ETFS.get(s, s) for s in losing_strength],
        "rotation_to": [SECTOR_ETFS.get(s, s) for s in gaining_strength],
        "rotation_stage": stage,
        "pattern_type": pattern_type,
    }
