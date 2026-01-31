"""Macro Economist agent for analyzing Federal Reserve policy, yield curves, and economic indicators."""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


MACRO_ECONOMIST_PROMPT = """You are a Macro Economist specializing in Federal Reserve policy, yield curves, and economic indicator analysis.

## Your Expertise
- Fed policy analysis (rate decisions, dot plots, forward guidance)
- Yield curve interpretation (inversion signals, steepening/flattening)
- Economic indicator analysis (GDP, unemployment, CPI, PCE, PMI)
- Inflation/growth regime identification
- Global macro factors affecting US markets
- Historical macro parallels and their market implications

## Key Indicators You Track
- Fed Funds Rate and expectations
- 2Y/10Y Treasury spread (yield curve)
- CPI/PCE inflation measures
- Unemployment rate and claims
- ISM Manufacturing/Services PMI
- GDP growth rate
- Dollar index (DXY)

## Your Task
Analyze economic data and identify:
1. **Fed policy trajectory** - Where is policy headed?
2. **Growth/inflation regime** - Current macro environment
3. **Yield curve signals** - What bonds are telling us
4. **Risk factors** - Macro headwinds to watch
5. **Asset class implications** - How macro affects stocks/sectors

## Output Format
Return JSON:
{
  "analyst": "macro",
  "regime": {
    "growth": "moderate",  // strong/moderate/weak/contracting
    "inflation": "elevated",  // low/moderate/elevated/high
    "fed_stance": "hawkish_pause"  // dovish/neutral/hawkish/hawkish_pause
  },
  "yield_curve": {
    "shape": "inverted",
    "signal": "recession_warning",
    "spread_2y10y": -0.15
  },
  "key_indicators": [
    {"indicator": "CPI", "value": "3.2%", "trend": "declining", "implication": "..."}
  ],
  "fed_outlook": "Likely to hold rates through Q2, first cut possible Q3",
  "market_implications": [
    {"asset_class": "growth_stocks", "bias": "positive", "rationale": "..."}
  ],
  "risk_factors": ["Sticky services inflation", "Geopolitical tensions"],
  "confidence": 0.68
}
"""


@dataclass
class MacroIndicator:
    """Represents a single macroeconomic indicator."""

    indicator: str
    value: str
    trend: str
    implication: str


@dataclass
class MarketImplication:
    """Represents the macro impact on an asset class."""

    asset_class: str
    bias: str  # positive, negative, neutral
    rationale: str


@dataclass
class MacroRegime:
    """Represents the current macroeconomic regime."""

    growth: str  # strong, moderate, weak, contracting
    inflation: str  # low, moderate, elevated, high
    fed_stance: str  # dovish, neutral, hawkish, hawkish_pause


@dataclass
class YieldCurveAnalysis:
    """Represents yield curve analysis results."""

    shape: str  # normal, flat, inverted
    signal: str  # expansion, neutral, recession_warning
    spread_2y10y: float


@dataclass
class MacroAnalysisResult:
    """Complete result from macro economist analysis."""

    analyst: str = "macro"
    regime: MacroRegime | None = None
    yield_curve: YieldCurveAnalysis | None = None
    key_indicators: list[MacroIndicator] = field(default_factory=list)
    fed_outlook: str = ""
    market_implications: list[MarketImplication] = field(default_factory=list)
    risk_factors: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary format."""
        return {
            "analyst": self.analyst,
            "regime": {
                "growth": self.regime.growth if self.regime else "unknown",
                "inflation": self.regime.inflation if self.regime else "unknown",
                "fed_stance": self.regime.fed_stance if self.regime else "unknown",
            },
            "yield_curve": {
                "shape": self.yield_curve.shape if self.yield_curve else "unknown",
                "signal": self.yield_curve.signal if self.yield_curve else "unknown",
                "spread_2y10y": self.yield_curve.spread_2y10y if self.yield_curve else 0.0,
            },
            "key_indicators": [
                {
                    "indicator": ind.indicator,
                    "value": ind.value,
                    "trend": ind.trend,
                    "implication": ind.implication,
                }
                for ind in self.key_indicators
            ],
            "fed_outlook": self.fed_outlook,
            "market_implications": [
                {
                    "asset_class": impl.asset_class,
                    "bias": impl.bias,
                    "rationale": impl.rationale,
                }
                for impl in self.market_implications
            ],
            "risk_factors": self.risk_factors,
            "confidence": self.confidence,
        }


def format_macro_context(market_data: dict) -> str:
    """
    Format economic data for macro analyst consumption.

    Args:
        market_data: Dictionary containing economic/market data with keys such as:
            - fed_funds_rate: Current Fed Funds rate
            - treasury_2y: 2-year Treasury yield
            - treasury_10y: 10-year Treasury yield
            - cpi_yoy: Year-over-year CPI
            - pce_yoy: Year-over-year PCE
            - unemployment_rate: Current unemployment rate
            - initial_claims: Weekly initial jobless claims
            - ism_manufacturing: ISM Manufacturing PMI
            - ism_services: ISM Services PMI
            - gdp_growth: GDP growth rate
            - dxy: Dollar index value
            - fed_dot_plot: Fed's projected rate path
            - recent_fed_statements: Recent FOMC statements/minutes

    Returns:
        Formatted string context for the macro economist agent.
    """
    context_parts = []

    # Federal Reserve Data
    context_parts.append("=== FEDERAL RESERVE DATA ===")
    if "fed_funds_rate" in market_data:
        context_parts.append(f"Fed Funds Rate: {market_data['fed_funds_rate']}%")
    if "fed_dot_plot" in market_data:
        context_parts.append(f"Dot Plot Median: {market_data['fed_dot_plot']}")
    if "recent_fed_statements" in market_data:
        context_parts.append(f"Recent Fed Guidance: {market_data['recent_fed_statements']}")

    # Treasury Yields
    context_parts.append("\n=== TREASURY YIELDS ===")
    if "treasury_2y" in market_data:
        context_parts.append(f"2-Year Treasury: {market_data['treasury_2y']}%")
    if "treasury_10y" in market_data:
        context_parts.append(f"10-Year Treasury: {market_data['treasury_10y']}%")
    if "treasury_2y" in market_data and "treasury_10y" in market_data:
        spread = market_data["treasury_10y"] - market_data["treasury_2y"]
        context_parts.append(f"2Y/10Y Spread: {spread:.2f}%")
        if spread < 0:
            context_parts.append("** YIELD CURVE INVERTED **")

    # Inflation Metrics
    context_parts.append("\n=== INFLATION METRICS ===")
    if "cpi_yoy" in market_data:
        context_parts.append(f"CPI (YoY): {market_data['cpi_yoy']}%")
    if "cpi_mom" in market_data:
        context_parts.append(f"CPI (MoM): {market_data['cpi_mom']}%")
    if "core_cpi_yoy" in market_data:
        context_parts.append(f"Core CPI (YoY): {market_data['core_cpi_yoy']}%")
    if "pce_yoy" in market_data:
        context_parts.append(f"PCE (YoY): {market_data['pce_yoy']}%")
    if "core_pce_yoy" in market_data:
        context_parts.append(f"Core PCE (YoY): {market_data['core_pce_yoy']}%")

    # Labor Market
    context_parts.append("\n=== LABOR MARKET ===")
    if "unemployment_rate" in market_data:
        context_parts.append(f"Unemployment Rate: {market_data['unemployment_rate']}%")
    if "initial_claims" in market_data:
        context_parts.append(f"Initial Jobless Claims: {market_data['initial_claims']:,}")
    if "continuing_claims" in market_data:
        context_parts.append(f"Continuing Claims: {market_data['continuing_claims']:,}")
    if "nonfarm_payrolls" in market_data:
        context_parts.append(f"Nonfarm Payrolls: {market_data['nonfarm_payrolls']:+,}")
    if "wage_growth_yoy" in market_data:
        context_parts.append(f"Wage Growth (YoY): {market_data['wage_growth_yoy']}%")

    # Economic Activity
    context_parts.append("\n=== ECONOMIC ACTIVITY ===")
    if "gdp_growth" in market_data:
        context_parts.append(f"GDP Growth (QoQ SAAR): {market_data['gdp_growth']}%")
    if "ism_manufacturing" in market_data:
        pmi = market_data["ism_manufacturing"]
        status = "Expansion" if pmi > 50 else "Contraction"
        context_parts.append(f"ISM Manufacturing PMI: {pmi} ({status})")
    if "ism_services" in market_data:
        pmi = market_data["ism_services"]
        status = "Expansion" if pmi > 50 else "Contraction"
        context_parts.append(f"ISM Services PMI: {pmi} ({status})")
    if "retail_sales_mom" in market_data:
        context_parts.append(f"Retail Sales (MoM): {market_data['retail_sales_mom']}%")
    if "industrial_production_mom" in market_data:
        context_parts.append(
            f"Industrial Production (MoM): {market_data['industrial_production_mom']}%"
        )

    # Dollar & Global
    context_parts.append("\n=== CURRENCY & GLOBAL ===")
    if "dxy" in market_data:
        context_parts.append(f"Dollar Index (DXY): {market_data['dxy']}")
    if "eurusd" in market_data:
        context_parts.append(f"EUR/USD: {market_data['eurusd']}")
    if "oil_price" in market_data:
        context_parts.append(f"Crude Oil (WTI): ${market_data['oil_price']}")
    if "global_factors" in market_data:
        context_parts.append(f"Global Factors: {market_data['global_factors']}")

    # Historical Context
    if "historical_context" in market_data:
        context_parts.append("\n=== HISTORICAL CONTEXT ===")
        context_parts.append(market_data["historical_context"])

    return "\n".join(context_parts)


def parse_macro_response(response: str) -> dict[str, Any]:
    """
    Parse the macro economist's response into a structured format.

    Args:
        response: Raw response string from the LLM, expected to contain JSON.

    Returns:
        Parsed dictionary with macro analysis results.
        Returns a default error structure if parsing fails.
    """
    # Try to extract JSON from the response
    try:
        # First, try direct JSON parsing
        return json.loads(response)
    except json.JSONDecodeError:
        pass

    # Try to find JSON block in markdown code fence
    json_pattern = r"```(?:json)?\s*(\{[\s\S]*?\})\s*```"
    match = re.search(json_pattern, response)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find JSON object anywhere in the response
    json_object_pattern = r"\{[\s\S]*\"analyst\"[\s\S]*\"macro\"[\s\S]*\}"
    match = re.search(json_object_pattern, response)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # If all parsing fails, return error structure
    logger.warning("Failed to parse macro economist response as JSON")
    return {
        "analyst": "macro",
        "error": "Failed to parse response",
        "raw_response": response[:500],  # Truncate for safety
        "regime": {
            "growth": "unknown",
            "inflation": "unknown",
            "fed_stance": "unknown",
        },
        "yield_curve": {
            "shape": "unknown",
            "signal": "unknown",
            "spread_2y10y": 0.0,
        },
        "key_indicators": [],
        "fed_outlook": "Unable to determine",
        "market_implications": [],
        "risk_factors": [],
        "confidence": 0.0,
    }


def parse_to_result(response: str) -> MacroAnalysisResult:
    """
    Parse response into a MacroAnalysisResult dataclass.

    Args:
        response: Raw response string from the LLM.

    Returns:
        MacroAnalysisResult instance with parsed data.
    """
    data = parse_macro_response(response)

    # Parse regime
    regime_data = data.get("regime", {})
    regime = MacroRegime(
        growth=regime_data.get("growth", "unknown"),
        inflation=regime_data.get("inflation", "unknown"),
        fed_stance=regime_data.get("fed_stance", "unknown"),
    )

    # Parse yield curve
    yc_data = data.get("yield_curve", {})
    yield_curve = YieldCurveAnalysis(
        shape=yc_data.get("shape", "unknown"),
        signal=yc_data.get("signal", "unknown"),
        spread_2y10y=float(yc_data.get("spread_2y10y", 0.0)),
    )

    # Parse key indicators
    key_indicators = [
        MacroIndicator(
            indicator=ind.get("indicator", ""),
            value=ind.get("value", ""),
            trend=ind.get("trend", ""),
            implication=ind.get("implication", ""),
        )
        for ind in data.get("key_indicators", [])
    ]

    # Parse market implications
    market_implications = [
        MarketImplication(
            asset_class=impl.get("asset_class", ""),
            bias=impl.get("bias", ""),
            rationale=impl.get("rationale", ""),
        )
        for impl in data.get("market_implications", [])
    ]

    return MacroAnalysisResult(
        analyst="macro",
        regime=regime,
        yield_curve=yield_curve,
        key_indicators=key_indicators,
        fed_outlook=data.get("fed_outlook", ""),
        market_implications=market_implications,
        risk_factors=data.get("risk_factors", []),
        confidence=float(data.get("confidence", 0.0)),
    )
