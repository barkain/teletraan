"""Analysis agents for multi-agent market analysis system."""

from .technical_analyst import (
    TECHNICAL_ANALYST_PROMPT,
    format_technical_context,
    parse_technical_response,
    TechnicalFinding,
    TechnicalAnalysisResult,
)

from .macro_economist import (
    MACRO_ECONOMIST_PROMPT,
    format_macro_context,
    parse_macro_response,
    parse_to_result,
    MacroIndicator,
    MarketImplication,
    MacroRegime,
    YieldCurveAnalysis,
    MacroAnalysisResult,
)

from .sector_strategist import (
    SECTOR_STRATEGIST_PROMPT,
    format_sector_context,
    parse_sector_response,
)

__all__ = [
    # Technical Analyst
    "TECHNICAL_ANALYST_PROMPT",
    "format_technical_context",
    "parse_technical_response",
    "TechnicalFinding",
    "TechnicalAnalysisResult",
    # Macro Economist
    "MACRO_ECONOMIST_PROMPT",
    "format_macro_context",
    "parse_macro_response",
    "parse_to_result",
    "MacroIndicator",
    "MarketImplication",
    "MacroRegime",
    "YieldCurveAnalysis",
    "MacroAnalysisResult",
    # Sector Strategist
    "SECTOR_STRATEGIST_PROMPT",
    "format_sector_context",
    "parse_sector_response",
]
