"""Shared interfaces and data models for the heatmap-driven stock selection pipeline.

This module defines ALL shared dataclasses and type contracts for the new
autonomous analysis pipeline that replaces the hardcoded 110-stock universe
with dynamic, heatmap-driven stock selection.

Pipeline Flow:
    MacroScan -> HeatmapFetch -> HeatmapAnalysis -> DeepDive -> CoverageEval (loop max 2x) -> Synthesis

Phase descriptions:
    1. MacroScan: Identify market regime and themes (existing, unchanged)
    2. HeatmapFetch: Fetch real-time sector/stock heatmap data from yfinance
       for all S&P 500 constituents and sector ETFs. Produces HeatmapData.
    3. HeatmapAnalysis: LLM-driven analysis of heatmap patterns. Selects
       10-15 stocks for deep dive based on patterns, divergences, and macro
       alignment. Produces HeatmapAnalysis.
    4. DeepDive: Run specialist analysts on selected stocks (existing, reused)
    5. CoverageEval: Evaluate whether selected stocks provide sufficient
       sector/theme coverage. May recommend additional stocks for up to 2
       iterations. Produces CoverageEvaluation.
    6. Synthesis: Aggregate and rank final insights (existing, reused)

Integration with AnalysisTaskStatus:
    New enum values needed: HEATMAP_FETCH, HEATMAP_ANALYSIS, COVERAGE_EVALUATION.
    These slot between existing phases in the status progression:
        PENDING -> MACRO_SCAN -> HEATMAP_FETCH -> HEATMAP_ANALYSIS ->
        DEEP_DIVE -> COVERAGE_EVALUATION -> SYNTHESIS -> COMPLETED

All dataclasses follow existing codebase patterns:
    - to_dict() -> dict method for serialization
    - from_dict(cls, data: dict) -> Self classmethod for deserialization
    - dataclasses.field(default_factory=list) for mutable defaults
    - Full type hints throughout
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# =============================================================================
# 1. HEATMAP DATA MODELS (for heatmap_fetcher.py)
# =============================================================================


@dataclass
class StockHeatmapEntry:
    """Per-stock data point in the market heatmap.

    Represents a single stock's current state including price action,
    volume characteristics, and classification metadata. Fetched from
    yfinance for all S&P 500 constituents.

    Attributes:
        symbol: Ticker symbol (e.g., "AAPL")
        sector: GICS sector name (e.g., "Technology")
        price: Current/last price in USD
        change_1d: 1-day price change percentage
        change_5d: 5-day price change percentage
        change_20d: 20-day price change percentage
        volume_ratio: Current volume / 20-day average volume
        market_cap: Market capitalization in billions USD
    """

    symbol: str
    sector: str
    price: float = 0.0
    change_1d: float = 0.0
    change_5d: float = 0.0
    change_20d: float = 0.0
    volume_ratio: float = 1.0
    market_cap: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "symbol": self.symbol,
            "sector": self.sector,
            "price": round(self.price, 2),
            "change_1d": round(self.change_1d, 2),
            "change_5d": round(self.change_5d, 2),
            "change_20d": round(self.change_20d, 2),
            "volume_ratio": round(self.volume_ratio, 2),
            "market_cap": round(self.market_cap, 2),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StockHeatmapEntry:
        """Create from dictionary."""
        return cls(
            symbol=data.get("symbol", "UNKNOWN"),
            sector=data.get("sector", "Unknown"),
            price=float(data.get("price", 0.0)),
            change_1d=float(data.get("change_1d", 0.0)),
            change_5d=float(data.get("change_5d", 0.0)),
            change_20d=float(data.get("change_20d", 0.0)),
            volume_ratio=float(data.get("volume_ratio", 1.0)),
            market_cap=float(data.get("market_cap", 0.0)),
        )


@dataclass
class SectorHeatmapEntry:
    """Per-sector aggregate data in the market heatmap.

    Aggregates individual stock data to sector level, including breadth
    indicators and notable movers.

    Attributes:
        name: Sector name (e.g., "Technology")
        etf: Sector ETF symbol (e.g., "XLK")
        change_1d: 1-day sector ETF change percentage
        change_5d: 5-day sector ETF change percentage
        change_20d: 20-day sector ETF change percentage
        breadth: Fraction of stocks in sector with positive 1d change (0.0-1.0)
        top_gainers: Symbols of top 3 gainers in sector (by 1d change)
        top_losers: Symbols of top 3 losers in sector (by 1d change)
        stock_count: Number of stocks tracked in this sector
    """

    name: str
    etf: str
    change_1d: float = 0.0
    change_5d: float = 0.0
    change_20d: float = 0.0
    breadth: float = 0.5
    top_gainers: list[str] = field(default_factory=list)
    top_losers: list[str] = field(default_factory=list)
    stock_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "name": self.name,
            "etf": self.etf,
            "change_1d": round(self.change_1d, 2),
            "change_5d": round(self.change_5d, 2),
            "change_20d": round(self.change_20d, 2),
            "breadth": round(self.breadth, 2),
            "top_gainers": self.top_gainers,
            "top_losers": self.top_losers,
            "stock_count": self.stock_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SectorHeatmapEntry:
        """Create from dictionary."""
        return cls(
            name=data.get("name", "Unknown"),
            etf=data.get("etf", ""),
            change_1d=float(data.get("change_1d", 0.0)),
            change_5d=float(data.get("change_5d", 0.0)),
            change_20d=float(data.get("change_20d", 0.0)),
            breadth=float(data.get("breadth", 0.5)),
            top_gainers=data.get("top_gainers", []),
            top_losers=data.get("top_losers", []),
            stock_count=int(data.get("stock_count", 0)),
        )


@dataclass
class HeatmapData:
    """Complete market heatmap snapshot.

    Contains both sector-level and stock-level data, plus metadata about
    when the snapshot was taken and market status.

    The heatmap_fetcher.py module produces this as its output. It is consumed
    by heatmap_analyzer.py for pattern detection and stock selection.

    Attributes:
        sectors: List of sector-level aggregate entries
        stocks: List of individual stock entries
        timestamp: When this heatmap was fetched
        market_status: Current market status (open, closed, pre_market, after_hours)
    """

    sectors: list[SectorHeatmapEntry] = field(default_factory=list)
    stocks: list[StockHeatmapEntry] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    market_status: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "sectors": [s.to_dict() for s in self.sectors],
            "stocks": [s.to_dict() for s in self.stocks],
            "timestamp": self.timestamp.isoformat(),
            "market_status": self.market_status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HeatmapData:
        """Create from dictionary."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.utcnow()
        elif not isinstance(timestamp, datetime):
            timestamp = datetime.utcnow()

        sectors = [
            SectorHeatmapEntry.from_dict(s)
            for s in data.get("sectors", [])
            if isinstance(s, dict)
        ]
        stocks = [
            StockHeatmapEntry.from_dict(s)
            for s in data.get("stocks", [])
            if isinstance(s, dict)
        ]

        return cls(
            sectors=sectors,
            stocks=stocks,
            timestamp=timestamp,
            market_status=data.get("market_status", "unknown"),
        )

    def get_sector_stocks(self, sector_name: str) -> list[StockHeatmapEntry]:
        """Get all stocks belonging to a specific sector.

        Args:
            sector_name: Sector name to filter by (e.g., "Technology").

        Returns:
            List of StockHeatmapEntry objects in the specified sector,
            sorted by market_cap descending.
        """
        sector_stocks = [s for s in self.stocks if s.sector == sector_name]
        sector_stocks.sort(key=lambda s: s.market_cap, reverse=True)
        return sector_stocks

    def get_outliers(
        self,
        change_field: str = "change_1d",
        threshold_std: float = 2.0,
    ) -> list[StockHeatmapEntry]:
        """Get stocks with outsized moves (statistical outliers).

        Identifies stocks whose price change exceeds threshold_std standard
        deviations from the mean, in either direction.

        Args:
            change_field: Which change field to analyze
                (change_1d, change_5d, change_20d).
            threshold_std: Number of standard deviations for outlier threshold.

        Returns:
            List of StockHeatmapEntry objects that are statistical outliers,
            sorted by absolute change descending.
        """
        if not self.stocks:
            return []

        values = [getattr(s, change_field, 0.0) for s in self.stocks]
        if not values:
            return []

        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        std = variance ** 0.5

        if std == 0:
            return []

        outliers = [
            s
            for s in self.stocks
            if abs(getattr(s, change_field, 0.0) - mean) > threshold_std * std
        ]
        outliers.sort(key=lambda s: abs(getattr(s, change_field, 0.0)), reverse=True)
        return outliers

    def get_divergences(self) -> list[tuple[StockHeatmapEntry, SectorHeatmapEntry]]:
        """Get stocks diverging from their sector's direction.

        A stock diverges when its 1d change direction is opposite to its
        sector's 1d change direction by a meaningful margin (>1% difference).

        Returns:
            List of (stock, sector) tuples where the stock diverges from
            its sector, sorted by magnitude of divergence descending.
        """
        sector_map: dict[str, SectorHeatmapEntry] = {
            s.name: s for s in self.sectors
        }

        divergences: list[tuple[StockHeatmapEntry, SectorHeatmapEntry, float]] = []

        for stock in self.stocks:
            sector = sector_map.get(stock.sector)
            if not sector:
                continue

            # Check for directional divergence with meaningful magnitude
            divergence = stock.change_1d - sector.change_1d
            if abs(divergence) > 1.0 and (
                (stock.change_1d > 0 and sector.change_1d < 0)
                or (stock.change_1d < 0 and sector.change_1d > 0)
            ):
                divergences.append((stock, sector, abs(divergence)))

        divergences.sort(key=lambda x: x[2], reverse=True)
        return [(stock, sector) for stock, sector, _ in divergences]


# =============================================================================
# 2. HEATMAP ANALYSIS MODELS (for heatmap_analyzer.py)
# =============================================================================


@dataclass
class HeatmapPattern:
    """An identified pattern in the heatmap data.

    Represents a notable market pattern detected by the LLM analyzer,
    such as sector rotation signals, breadth divergences, or momentum
    clustering.

    Attributes:
        description: Human-readable description of the pattern
        sectors: Sectors involved in this pattern
        implication: What this pattern suggests for trading/positioning
    """

    description: str
    sectors: list[str] = field(default_factory=list)
    implication: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "description": self.description,
            "sectors": self.sectors,
            "implication": self.implication,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HeatmapPattern:
        """Create from dictionary."""
        return cls(
            description=data.get("description", ""),
            sectors=data.get("sectors", []),
            implication=data.get("implication", ""),
        )


@dataclass
class HeatmapStockSelection:
    """A stock selected for deep dive based on heatmap analysis.

    Each selection includes the rationale for why this stock was chosen,
    linking back to observed heatmap patterns and macro alignment.

    Attributes:
        symbol: Stock ticker symbol
        sector: Sector classification
        reason: Why this stock was selected (references patterns/divergences)
        opportunity_type: Type of opportunity
            (momentum, mean_reversion, breakout, divergence, sector_leader)
        priority: Selection priority (high, medium, low)
        expected_insight_value: How likely this stock is to yield an
            actionable insight (0.0-1.0)
    """

    symbol: str
    sector: str
    reason: str = ""
    opportunity_type: str = ""
    priority: str = "medium"
    expected_insight_value: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "symbol": self.symbol,
            "sector": self.sector,
            "reason": self.reason,
            "opportunity_type": self.opportunity_type,
            "priority": self.priority,
            "expected_insight_value": round(self.expected_insight_value, 2),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HeatmapStockSelection:
        """Create from dictionary."""
        return cls(
            symbol=data.get("symbol", "UNKNOWN"),
            sector=data.get("sector", "Unknown"),
            reason=data.get("reason", ""),
            opportunity_type=data.get("opportunity_type", ""),
            priority=data.get("priority", "medium"),
            expected_insight_value=float(data.get("expected_insight_value", 0.5)),
        )


@dataclass
class HeatmapAnalysis:
    """Complete result from LLM-driven heatmap analysis.

    Produced by heatmap_analyzer.py. Contains the analysis overview,
    identified patterns, and the selected stocks for deep dive.

    Attributes:
        overview: High-level summary of heatmap state
        patterns: Identified market patterns in the heatmap
        selected_stocks: Stocks selected for deep dive analysis (10-15)
        sectors_to_watch: Sectors showing notable activity worth monitoring
        confidence: Overall confidence in the analysis (0.0-1.0)
        analysis_timestamp: When this analysis was performed
    """

    overview: str = ""
    patterns: list[HeatmapPattern] = field(default_factory=list)
    selected_stocks: list[HeatmapStockSelection] = field(default_factory=list)
    sectors_to_watch: list[str] = field(default_factory=list)
    confidence: float = 0.5
    analysis_timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "overview": self.overview,
            "patterns": [p.to_dict() for p in self.patterns],
            "selected_stocks": [s.to_dict() for s in self.selected_stocks],
            "sectors_to_watch": self.sectors_to_watch,
            "confidence": round(self.confidence, 2),
            "analysis_timestamp": self.analysis_timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HeatmapAnalysis:
        """Create from dictionary."""
        timestamp = data.get("analysis_timestamp")
        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.utcnow()
        elif not isinstance(timestamp, datetime):
            timestamp = datetime.utcnow()

        patterns = [
            HeatmapPattern.from_dict(p)
            for p in data.get("patterns", [])
            if isinstance(p, dict)
        ]
        selected_stocks = [
            HeatmapStockSelection.from_dict(s)
            for s in data.get("selected_stocks", [])
            if isinstance(s, dict)
        ]

        return cls(
            overview=data.get("overview", ""),
            patterns=patterns,
            selected_stocks=selected_stocks,
            sectors_to_watch=data.get("sectors_to_watch", []),
            confidence=float(data.get("confidence", 0.5)),
            analysis_timestamp=timestamp,
        )

    def get_high_priority_stocks(self) -> list[HeatmapStockSelection]:
        """Get stocks with high deep-dive priority.

        Returns:
            List of HeatmapStockSelection with priority == "high",
            sorted by expected_insight_value descending.
        """
        high = [s for s in self.selected_stocks if s.priority == "high"]
        high.sort(key=lambda s: s.expected_insight_value, reverse=True)
        return high

    def get_stocks_by_type(
        self, opportunity_type: str
    ) -> list[HeatmapStockSelection]:
        """Get selected stocks filtered by opportunity type.

        Args:
            opportunity_type: Type to filter by (e.g., "momentum",
                "mean_reversion", "breakout", "divergence", "sector_leader").

        Returns:
            List of HeatmapStockSelection matching the specified type.
        """
        return [
            s
            for s in self.selected_stocks
            if s.opportunity_type == opportunity_type
        ]


# =============================================================================
# 3. COVERAGE EVALUATION MODELS (for coverage_evaluator.py)
# =============================================================================


@dataclass
class CoverageGap:
    """An identified gap in sector/theme coverage.

    Represents a sector, theme, or opportunity type that is underrepresented
    in the current stock selection, which the coverage evaluator recommends
    filling.

    Attributes:
        description: What coverage is missing (e.g., "No energy sector exposure
            despite bullish macro signal")
        suggested_sectors: Sectors to draw additional stocks from
        suggested_stocks: Specific stocks recommended to fill the gap
        importance: How critical this gap is (high, medium, low)
    """

    description: str
    suggested_sectors: list[str] = field(default_factory=list)
    suggested_stocks: list[str] = field(default_factory=list)
    importance: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "description": self.description,
            "suggested_sectors": self.suggested_sectors,
            "suggested_stocks": self.suggested_stocks,
            "importance": self.importance,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CoverageGap:
        """Create from dictionary."""
        return cls(
            description=data.get("description", ""),
            suggested_sectors=data.get("suggested_sectors", []),
            suggested_stocks=data.get("suggested_stocks", []),
            importance=data.get("importance", "medium"),
        )


@dataclass
class CoverageEvaluation:
    """Result of coverage evaluation for a set of selected stocks.

    Determines whether the current stock selection provides sufficient
    coverage across sectors and macro themes. If not, recommends additional
    stocks. Maximum 2 iterations of coverage expansion are allowed to
    prevent unbounded growth.

    Attributes:
        is_sufficient: Whether current coverage meets quality threshold
        gaps: Identified coverage gaps
        additional_stocks_recommended: Extra stocks to add for better coverage
        reasoning: Explanation of the evaluation decision
        iteration_number: Which iteration this evaluation represents (1 or 2, max 2)
    """

    is_sufficient: bool = True
    gaps: list[CoverageGap] = field(default_factory=list)
    additional_stocks_recommended: list[HeatmapStockSelection] = field(
        default_factory=list
    )
    reasoning: str = ""
    iteration_number: int = 1

    MAX_ITERATIONS: int = 2

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "is_sufficient": self.is_sufficient,
            "gaps": [g.to_dict() for g in self.gaps],
            "additional_stocks_recommended": [
                s.to_dict() for s in self.additional_stocks_recommended
            ],
            "reasoning": self.reasoning,
            "iteration_number": self.iteration_number,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CoverageEvaluation:
        """Create from dictionary."""
        gaps = [
            CoverageGap.from_dict(g)
            for g in data.get("gaps", [])
            if isinstance(g, dict)
        ]
        additional = [
            HeatmapStockSelection.from_dict(s)
            for s in data.get("additional_stocks_recommended", [])
            if isinstance(s, dict)
        ]

        return cls(
            is_sufficient=bool(data.get("is_sufficient", True)),
            gaps=gaps,
            additional_stocks_recommended=additional,
            reasoning=data.get("reasoning", ""),
            iteration_number=int(data.get("iteration_number", 1)),
        )

    @property
    def can_iterate(self) -> bool:
        """Whether another coverage iteration is allowed.

        Returns:
            True if iteration_number < MAX_ITERATIONS and coverage is
            not sufficient, False otherwise.
        """
        return not self.is_sufficient and self.iteration_number < self.MAX_ITERATIONS


# =============================================================================
# 4. NEW PIPELINE PHASE STATUSES
# =============================================================================

# New AnalysisTaskStatus values to add to models/analysis_task.py:
#
#   HEATMAP_FETCH = "heatmap_fetch"
#   HEATMAP_ANALYSIS = "heatmap_analysis"
#   COVERAGE_EVALUATION = "coverage_evaluation"
#
# Updated PHASE_PROGRESS entries:
#   AnalysisTaskStatus.HEATMAP_FETCH: 20
#   AnalysisTaskStatus.HEATMAP_ANALYSIS: 35
#   AnalysisTaskStatus.COVERAGE_EVALUATION: 75
#
# Updated PHASE_NAMES entries:
#   AnalysisTaskStatus.HEATMAP_FETCH: "Fetching market heatmap"
#   AnalysisTaskStatus.HEATMAP_ANALYSIS: "Analyzing heatmap patterns"
#   AnalysisTaskStatus.COVERAGE_EVALUATION: "Evaluating coverage"
#
# Full updated status progression:
#   PENDING(0) -> MACRO_SCAN(10) -> HEATMAP_FETCH(20) -> HEATMAP_ANALYSIS(35)
#   -> DEEP_DIVE(55) -> COVERAGE_EVALUATION(75) -> SYNTHESIS(90) -> COMPLETED(100)
#
# Note: SECTOR_ROTATION and OPPORTUNITY_HUNT are replaced by
# HEATMAP_FETCH + HEATMAP_ANALYSIS in the new pipeline.

HEATMAP_PHASE_PROGRESS: dict[str, int] = {
    "pending": 0,
    "macro_scan": 10,
    "heatmap_fetch": 20,
    "heatmap_analysis": 35,
    "deep_dive": 55,
    "coverage_evaluation": 75,
    "synthesis": 90,
    "completed": 100,
    "failed": -1,
    "cancelled": -1,
}

HEATMAP_PHASE_NAMES: dict[str, str] = {
    "pending": "Initializing...",
    "macro_scan": "Scanning macro environment",
    "heatmap_fetch": "Fetching market heatmap",
    "heatmap_analysis": "Analyzing heatmap patterns",
    "deep_dive": "Running deep analysis",
    "coverage_evaluation": "Evaluating coverage",
    "synthesis": "Synthesizing insights",
    "completed": "Analysis complete",
    "failed": "Analysis failed",
    "cancelled": "Analysis cancelled",
}


# =============================================================================
# 5. VALID OPPORTUNITY TYPES
# =============================================================================

# Extended opportunity types for heatmap-driven selection.
# Original types: momentum, mean_reversion, breakout, catalyst, sector_leader
# New type: divergence (stock diverging from sector trend)
VALID_OPPORTUNITY_TYPES: set[str] = {
    "momentum",
    "mean_reversion",
    "breakout",
    "catalyst",
    "sector_leader",
    "divergence",
}
