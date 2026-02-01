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
        market_data: Dictionary containing economic/market data from context builder:
            - economic_indicators: List of economic indicator dicts with series_id, name, value, unit
            - sector_performance: Dict mapping sector ETFs to performance metrics
            - market_summary: Overall market status
            Or legacy flat format with direct keys like fed_funds_rate, cpi_yoy, etc.

    Returns:
        Formatted string context for the macro economist agent.
    """
    context_parts = []

    # Check if data is in new context builder format (list of economic_indicators)
    economic_indicators = market_data.get("economic_indicators", [])

    if economic_indicators and isinstance(economic_indicators, list):
        # New format: extract from list of indicator dicts
        # Build a lookup dict for easy access
        indicators_by_id: dict[str, dict] = {}
        indicators_by_name: dict[str, dict] = {}
        for ind in economic_indicators:
            if isinstance(ind, dict):
                series_id = ind.get("series_id", "").lower()
                name = ind.get("name", "").lower()
                indicators_by_id[series_id] = ind
                indicators_by_name[name] = ind

        context_parts.append("=== ECONOMIC INDICATORS ===")

        # Group indicators by category
        fed_indicators = []
        inflation_indicators = []
        labor_indicators = []
        activity_indicators = []
        other_indicators = []

        for ind in economic_indicators:
            name = ind.get("name", "").lower()
            series_id = ind.get("series_id", "").lower()

            # Categorize by name/series_id patterns
            if any(x in name or x in series_id for x in ["fed", "funds", "rate", "fomc"]):
                fed_indicators.append(ind)
            elif any(x in name or x in series_id for x in ["cpi", "pce", "inflation", "price"]):
                inflation_indicators.append(ind)
            elif any(x in name or x in series_id for x in ["unemployment", "payroll", "jobs", "claims", "labor", "wage"]):
                labor_indicators.append(ind)
            elif any(x in name or x in series_id for x in ["gdp", "pmi", "ism", "retail", "industrial", "manufacturing"]):
                activity_indicators.append(ind)
            else:
                other_indicators.append(ind)

        # Federal Reserve Data
        if fed_indicators:
            context_parts.append("\n=== FEDERAL RESERVE DATA ===")
            for ind in fed_indicators:
                name = ind.get("name", ind.get("series_id", "Unknown"))
                value = ind.get("value", "N/A")
                unit = ind.get("unit", "")
                date = ind.get("date", "")
                context_parts.append(f"{name}: {value}{unit} (as of {date})")

        # Inflation Metrics
        if inflation_indicators:
            context_parts.append("\n=== INFLATION METRICS ===")
            for ind in inflation_indicators:
                name = ind.get("name", ind.get("series_id", "Unknown"))
                value = ind.get("value", "N/A")
                unit = ind.get("unit", "")
                date = ind.get("date", "")
                context_parts.append(f"{name}: {value}{unit} (as of {date})")

        # Labor Market
        if labor_indicators:
            context_parts.append("\n=== LABOR MARKET ===")
            for ind in labor_indicators:
                name = ind.get("name", ind.get("series_id", "Unknown"))
                value = ind.get("value", "N/A")
                unit = ind.get("unit", "")
                date = ind.get("date", "")
                if isinstance(value, (int, float)) and value > 1000:
                    context_parts.append(f"{name}: {value:,.0f}{unit} (as of {date})")
                else:
                    context_parts.append(f"{name}: {value}{unit} (as of {date})")

        # Economic Activity
        if activity_indicators:
            context_parts.append("\n=== ECONOMIC ACTIVITY ===")
            for ind in activity_indicators:
                name = ind.get("name", ind.get("series_id", "Unknown"))
                value = ind.get("value", "N/A")
                unit = ind.get("unit", "")
                date = ind.get("date", "")
                # Add expansion/contraction status for PMI
                if "pmi" in name.lower() or "ism" in name.lower():
                    try:
                        status = "Expansion" if float(value) > 50 else "Contraction"
                        context_parts.append(f"{name}: {value}{unit} ({status}) (as of {date})")
                    except (ValueError, TypeError):
                        context_parts.append(f"{name}: {value}{unit} (as of {date})")
                else:
                    context_parts.append(f"{name}: {value}{unit} (as of {date})")

        # Other Indicators
        if other_indicators:
            context_parts.append("\n=== OTHER INDICATORS ===")
            for ind in other_indicators:
                name = ind.get("name", ind.get("series_id", "Unknown"))
                value = ind.get("value", "N/A")
                unit = ind.get("unit", "")
                date = ind.get("date", "")
                context_parts.append(f"{name}: {value}{unit} (as of {date})")

        # If no indicators were found, note that
        if not any([fed_indicators, inflation_indicators, labor_indicators, activity_indicators, other_indicators]):
            context_parts.append("No economic indicators available in database.")

    else:
        # Legacy flat format or new format with empty economic_indicators
        # Only output sections that have data

        # Federal Reserve Data
        fed_data = []
        if "fed_funds_rate" in market_data:
            fed_data.append(f"Fed Funds Rate: {market_data['fed_funds_rate']}%")
        if "fed_dot_plot" in market_data:
            fed_data.append(f"Dot Plot Median: {market_data['fed_dot_plot']}")
        if "recent_fed_statements" in market_data:
            fed_data.append(f"Recent Fed Guidance: {market_data['recent_fed_statements']}")
        if fed_data:
            context_parts.append("=== FEDERAL RESERVE DATA ===")
            context_parts.extend(fed_data)

        # Treasury Yields
        treasury_data = []
        if "treasury_2y" in market_data:
            treasury_data.append(f"2-Year Treasury: {market_data['treasury_2y']}%")
        if "treasury_10y" in market_data:
            treasury_data.append(f"10-Year Treasury: {market_data['treasury_10y']}%")
        if "treasury_2y" in market_data and "treasury_10y" in market_data:
            spread = market_data["treasury_10y"] - market_data["treasury_2y"]
            treasury_data.append(f"2Y/10Y Spread: {spread:.2f}%")
            if spread < 0:
                treasury_data.append("** YIELD CURVE INVERTED **")
        if treasury_data:
            context_parts.append("\n=== TREASURY YIELDS ===")
            context_parts.extend(treasury_data)

        # Inflation Metrics
        inflation_data = []
        if "cpi_yoy" in market_data:
            inflation_data.append(f"CPI (YoY): {market_data['cpi_yoy']}%")
        if "cpi_mom" in market_data:
            inflation_data.append(f"CPI (MoM): {market_data['cpi_mom']}%")
        if "core_cpi_yoy" in market_data:
            inflation_data.append(f"Core CPI (YoY): {market_data['core_cpi_yoy']}%")
        if "pce_yoy" in market_data:
            inflation_data.append(f"PCE (YoY): {market_data['pce_yoy']}%")
        if "core_pce_yoy" in market_data:
            inflation_data.append(f"Core PCE (YoY): {market_data['core_pce_yoy']}%")
        if inflation_data:
            context_parts.append("\n=== INFLATION METRICS ===")
            context_parts.extend(inflation_data)

        # Labor Market
        labor_data = []
        if "unemployment_rate" in market_data:
            labor_data.append(f"Unemployment Rate: {market_data['unemployment_rate']}%")
        if "initial_claims" in market_data:
            labor_data.append(f"Initial Jobless Claims: {market_data['initial_claims']:,}")
        if "continuing_claims" in market_data:
            labor_data.append(f"Continuing Claims: {market_data['continuing_claims']:,}")
        if "nonfarm_payrolls" in market_data:
            labor_data.append(f"Nonfarm Payrolls: {market_data['nonfarm_payrolls']:+,}")
        if "wage_growth_yoy" in market_data:
            labor_data.append(f"Wage Growth (YoY): {market_data['wage_growth_yoy']}%")
        if labor_data:
            context_parts.append("\n=== LABOR MARKET ===")
            context_parts.extend(labor_data)

        # Economic Activity
        activity_data = []
        if "gdp_growth" in market_data:
            activity_data.append(f"GDP Growth (QoQ SAAR): {market_data['gdp_growth']}%")
        if "ism_manufacturing" in market_data:
            pmi = market_data["ism_manufacturing"]
            status = "Expansion" if pmi > 50 else "Contraction"
            activity_data.append(f"ISM Manufacturing PMI: {pmi} ({status})")
        if "ism_services" in market_data:
            pmi = market_data["ism_services"]
            status = "Expansion" if pmi > 50 else "Contraction"
            activity_data.append(f"ISM Services PMI: {pmi} ({status})")
        if "retail_sales_mom" in market_data:
            activity_data.append(f"Retail Sales (MoM): {market_data['retail_sales_mom']}%")
        if "industrial_production_mom" in market_data:
            activity_data.append(
                f"Industrial Production (MoM): {market_data['industrial_production_mom']}%"
            )
        if activity_data:
            context_parts.append("\n=== ECONOMIC ACTIVITY ===")
            context_parts.extend(activity_data)

        # Currency & Global
        currency_data = []
        if "dxy" in market_data:
            currency_data.append(f"Dollar Index (DXY): {market_data['dxy']}")
        if "eurusd" in market_data:
            currency_data.append(f"EUR/USD: {market_data['eurusd']}")
        if "oil_price" in market_data:
            currency_data.append(f"Crude Oil (WTI): ${market_data['oil_price']}")
        if "global_factors" in market_data:
            currency_data.append(f"Global Factors: {market_data['global_factors']}")
        if currency_data:
            context_parts.append("\n=== CURRENCY & GLOBAL ===")
            context_parts.extend(currency_data)

        # If no legacy data at all, add a note but proceed with sector/market data
        if not any([fed_data, treasury_data, inflation_data, labor_data, activity_data, currency_data]):
            context_parts.append("=== ECONOMIC INDICATORS ===")
            context_parts.append("Note: No detailed economic indicators available in database.")
            context_parts.append("Analysis based on sector performance and market index data below.")

    # Sector Performance (from context builder)
    sector_performance = market_data.get("sector_performance", {})
    if sector_performance:
        context_parts.append("\n=== SECTOR PERFORMANCE ===")
        for symbol, perf in sector_performance.items():
            if isinstance(perf, dict):
                name = perf.get("name", symbol)
                sector = perf.get("sector", "")
                daily_pct = perf.get("daily_change_pct", 0)
                weekly_pct = perf.get("weekly_change_pct", 0)
                monthly_pct = perf.get("monthly_change_pct", 0)
                context_parts.append(
                    f"{symbol} ({sector}): Daily={daily_pct:+.2f}%, "
                    f"Weekly={weekly_pct:+.2f}%, Monthly={monthly_pct:+.2f}%"
                )

    # Market Summary (from context builder)
    market_summary = market_data.get("market_summary", {})
    if market_summary:
        market_index = market_summary.get("market_index", {})
        if market_index:
            context_parts.append("\n=== MARKET INDEX (SPY) ===")
            context_parts.append(f"Current: ${market_index.get('current', 0):.2f}")
            context_parts.append(f"Change: {market_index.get('change_pct', 0):+.2f}%")
            context_parts.append(f"Volume: {market_index.get('volume', 0):,}")

    # Historical Context (legacy support)
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
