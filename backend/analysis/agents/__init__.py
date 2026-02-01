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

from .sector_rotator import (
    SECTOR_ROTATOR_PROMPT,
    SECTOR_ETFS as ROTATOR_SECTOR_ETFS,
    SECTOR_CHARACTERISTICS,
    SectorData,
    RelativeStrength,
    MomentumScore,
    SectorRecommendation,
    SectorRotationResult,
    format_sector_rotator_context,
    parse_sector_rotator_response,
    calculate_relative_strength,
    calculate_momentum,
    get_sector_leaders_for_regime,
    identify_rotation_pattern,
)

from .opportunity_hunter import (
    OPPORTUNITY_HUNTER_PROMPT,
    SECTOR_HOLDINGS,
    ETF_TO_SECTOR,
    SYMBOL_TO_SECTOR,
    OpportunityCandidate,
    OpportunityList,
    get_sector_stocks,
    get_all_screening_stocks,
    passes_technical_screen,
    calculate_screen_score,
    format_opportunity_context,
    parse_opportunity_response,
    validate_opportunity_candidate,
    summarize_opportunities,
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
    # Sector Rotator (Phase 2 Autonomous Analysis)
    "SECTOR_ROTATOR_PROMPT",
    "ROTATOR_SECTOR_ETFS",
    "SECTOR_CHARACTERISTICS",
    "SectorData",
    "RelativeStrength",
    "MomentumScore",
    "SectorRecommendation",
    "SectorRotationResult",
    "format_sector_rotator_context",
    "parse_sector_rotator_response",
    "calculate_relative_strength",
    "calculate_momentum",
    "get_sector_leaders_for_regime",
    "identify_rotation_pattern",
    # Opportunity Hunter (Phase 3 Autonomous Analysis)
    "OPPORTUNITY_HUNTER_PROMPT",
    "SECTOR_HOLDINGS",
    "ETF_TO_SECTOR",
    "SYMBOL_TO_SECTOR",
    "OpportunityCandidate",
    "OpportunityList",
    "get_sector_stocks",
    "get_all_screening_stocks",
    "passes_technical_screen",
    "calculate_screen_score",
    "format_opportunity_context",
    "parse_opportunity_response",
    "validate_opportunity_candidate",
    "summarize_opportunities",
]
