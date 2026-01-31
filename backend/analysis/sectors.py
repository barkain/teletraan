"""Sector rotation and analysis module.

This module provides sector analysis capabilities including:
- Sector performance metrics calculation
- Relative strength analysis vs benchmark
- Sector rotation detection
- Market cycle phase identification
- Actionable sector insights generation
"""

from typing import Any, Optional
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
import statistics


class SectorPhase(Enum):
    """Market cycle phases for sector rotation.

    The business cycle typically moves through these phases:
    - Early Expansion: Recovery from recession, interest rates low
    - Mid Expansion: Growth accelerating, profits rising
    - Late Expansion: Peak growth, inflation rising
    - Early Contraction: Growth slowing, yields inverting
    - Late Contraction: Recession, defensive positioning
    """
    EARLY_EXPANSION = "early_expansion"
    MID_EXPANSION = "mid_expansion"
    LATE_EXPANSION = "late_expansion"
    EARLY_CONTRACTION = "early_contraction"
    LATE_CONTRACTION = "late_contraction"


@dataclass
class SectorMetrics:
    """Sector performance metrics."""
    symbol: str
    name: str
    daily_return: float
    weekly_return: float
    monthly_return: float
    quarterly_return: float
    ytd_return: float
    relative_strength: float  # vs S&P 500
    volume_trend: str  # "increasing", "decreasing", "stable"
    momentum_score: float = 0.0  # Composite momentum indicator
    volatility: float = 0.0  # Standard deviation of returns


# Sector ETF mappings
SECTOR_ETFS: dict[str, str] = {
    "XLK": "Technology",
    "XLV": "Health Care",
    "XLF": "Financials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLE": "Energy",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}


class SectorAnalyzer:
    """Analyze sector rotation and relative performance.

    This analyzer implements sector rotation analysis based on the
    traditional business cycle model, identifying which sectors
    typically outperform in different economic phases.
    """

    # Sector cycle leadership (which sectors lead in each phase)
    CYCLE_LEADERS: dict[SectorPhase, list[str]] = {
        SectorPhase.EARLY_EXPANSION: ["XLF", "XLY", "XLI"],  # Financials, Consumer Disc, Industrials
        SectorPhase.MID_EXPANSION: ["XLK", "XLC", "XLI"],    # Technology, Comm Services, Industrials
        SectorPhase.LATE_EXPANSION: ["XLE", "XLB", "XLI"],   # Energy, Materials, Industrials
        SectorPhase.EARLY_CONTRACTION: ["XLV", "XLP", "XLU"],  # Health Care, Staples, Utilities
        SectorPhase.LATE_CONTRACTION: ["XLV", "XLP", "XLRE"],  # Health Care, Staples, Real Estate
    }

    # Sector characteristics for rotation analysis
    SECTOR_CHARACTERISTICS: dict[str, dict[str, Any]] = {
        "XLK": {"cyclicality": "growth", "rate_sensitivity": "high", "inflation_hedge": False},
        "XLV": {"cyclicality": "defensive", "rate_sensitivity": "low", "inflation_hedge": False},
        "XLF": {"cyclicality": "cyclical", "rate_sensitivity": "high", "inflation_hedge": False},
        "XLY": {"cyclicality": "cyclical", "rate_sensitivity": "medium", "inflation_hedge": False},
        "XLP": {"cyclicality": "defensive", "rate_sensitivity": "low", "inflation_hedge": False},
        "XLE": {"cyclicality": "cyclical", "rate_sensitivity": "low", "inflation_hedge": True},
        "XLI": {"cyclicality": "cyclical", "rate_sensitivity": "medium", "inflation_hedge": False},
        "XLB": {"cyclicality": "cyclical", "rate_sensitivity": "medium", "inflation_hedge": True},
        "XLU": {"cyclicality": "defensive", "rate_sensitivity": "high", "inflation_hedge": False},
        "XLRE": {"cyclicality": "defensive", "rate_sensitivity": "high", "inflation_hedge": True},
        "XLC": {"cyclicality": "growth", "rate_sensitivity": "medium", "inflation_hedge": False},
    }

    def __init__(self) -> None:
        """Initialize the sector analyzer."""
        self.sector_names = SECTOR_ETFS

    async def calculate_sector_metrics(
        self,
        sector_prices: dict[str, list[dict[str, Any]]]
    ) -> dict[str, SectorMetrics]:
        """Calculate performance metrics for each sector.

        Args:
            sector_prices: Dictionary mapping sector symbols to price history.
                Each price dict should have 'date', 'close', 'volume' keys.

        Returns:
            Dictionary mapping sector symbols to their metrics.
        """
        metrics: dict[str, SectorMetrics] = {}

        for symbol, prices in sector_prices.items():
            if not prices or len(prices) < 2:
                continue

            # Sort by date descending (most recent first)
            sorted_prices = sorted(prices, key=lambda x: x.get('date', ''), reverse=True)

            # Calculate returns for different periods
            daily_return = self._calculate_period_return(sorted_prices, 1)
            weekly_return = self._calculate_period_return(sorted_prices, 5)
            monthly_return = self._calculate_period_return(sorted_prices, 21)
            quarterly_return = self._calculate_period_return(sorted_prices, 63)
            ytd_return = self._calculate_ytd_return(sorted_prices)

            # Calculate volume trend
            volume_trend = self._calculate_volume_trend(sorted_prices)

            # Calculate volatility
            volatility = self._calculate_volatility(sorted_prices, 21)

            # Calculate momentum score (weighted average of returns)
            momentum_score = (
                daily_return * 0.1 +
                weekly_return * 0.2 +
                monthly_return * 0.4 +
                quarterly_return * 0.3
            )

            metrics[symbol] = SectorMetrics(
                symbol=symbol,
                name=self.sector_names.get(symbol, symbol),
                daily_return=daily_return,
                weekly_return=weekly_return,
                monthly_return=monthly_return,
                quarterly_return=quarterly_return,
                ytd_return=ytd_return,
                relative_strength=0.0,  # Will be calculated separately
                volume_trend=volume_trend,
                momentum_score=momentum_score,
                volatility=volatility,
            )

        return metrics

    def _calculate_period_return(
        self,
        prices: list[dict[str, Any]],
        days: int
    ) -> float:
        """Calculate return over a specific period."""
        if len(prices) <= days:
            return 0.0

        current_price = prices[0].get('close', 0)
        past_price = prices[min(days, len(prices) - 1)].get('close', 0)

        if past_price == 0:
            return 0.0

        return ((current_price - past_price) / past_price) * 100

    def _calculate_ytd_return(self, prices: list[dict[str, Any]]) -> float:
        """Calculate year-to-date return."""
        if not prices:
            return 0.0

        current_year = datetime.now().year
        current_price = prices[0].get('close', 0)

        # Find the last price of previous year or first available
        year_start_price = None
        for price in reversed(prices):
            price_date = price.get('date', '')
            if isinstance(price_date, str):
                try:
                    price_year = int(price_date[:4])
                    if price_year < current_year:
                        year_start_price = price.get('close', 0)
                        break
                except (ValueError, IndexError):
                    continue

        if year_start_price is None or year_start_price == 0:
            return 0.0

        return ((current_price - year_start_price) / year_start_price) * 100

    def _calculate_volume_trend(self, prices: list[dict[str, Any]], period: int = 20) -> str:
        """Calculate volume trend over a period."""
        if len(prices) < period:
            return "stable"

        recent_volume = sum(p.get('volume', 0) for p in prices[:period // 2]) / (period // 2)
        earlier_volume = sum(p.get('volume', 0) for p in prices[period // 2:period]) / (period // 2)

        if earlier_volume == 0:
            return "stable"

        change = (recent_volume - earlier_volume) / earlier_volume

        if change > 0.1:
            return "increasing"
        elif change < -0.1:
            return "decreasing"
        return "stable"

    def _calculate_volatility(self, prices: list[dict[str, Any]], period: int = 21) -> float:
        """Calculate volatility (standard deviation of daily returns)."""
        if len(prices) < period + 1:
            return 0.0

        returns: list[float] = []
        for i in range(period):
            if i + 1 < len(prices):
                current = prices[i].get('close', 0)
                previous = prices[i + 1].get('close', 0)
                if previous > 0:
                    returns.append((current - previous) / previous * 100)

        if len(returns) < 2:
            return 0.0

        return statistics.stdev(returns)

    async def calculate_relative_strength(
        self,
        sector_prices: dict[str, list[dict[str, Any]]],
        benchmark_prices: list[dict[str, Any]]
    ) -> dict[str, float]:
        """Calculate relative strength vs benchmark (SPY).

        Relative strength is calculated as the ratio of sector performance
        to benchmark performance over the lookback period.

        Args:
            sector_prices: Dictionary mapping sector symbols to price history.
            benchmark_prices: Price history for the benchmark (SPY).

        Returns:
            Dictionary mapping sector symbols to relative strength values.
            Values > 1 indicate outperformance, < 1 indicate underperformance.
        """
        relative_strength: dict[str, float] = {}

        if not benchmark_prices or len(benchmark_prices) < 21:
            return {symbol: 1.0 for symbol in sector_prices}

        # Sort benchmark prices
        sorted_benchmark = sorted(benchmark_prices, key=lambda x: x.get('date', ''), reverse=True)
        benchmark_return = self._calculate_period_return(sorted_benchmark, 21)

        for symbol, prices in sector_prices.items():
            if not prices or len(prices) < 21:
                relative_strength[symbol] = 1.0
                continue

            sorted_prices = sorted(prices, key=lambda x: x.get('date', ''), reverse=True)
            sector_return = self._calculate_period_return(sorted_prices, 21)

            # Calculate relative strength ratio
            if benchmark_return == 0:
                relative_strength[symbol] = 1.0
            else:
                # Normalized relative strength (1.0 = equal performance)
                relative_strength[symbol] = (1 + sector_return / 100) / (1 + benchmark_return / 100)

        return relative_strength

    async def detect_rotation(
        self,
        sector_metrics: dict[str, SectorMetrics],
        lookback_days: int = 30
    ) -> dict[str, Any]:
        """Detect sector rotation patterns.

        Analyzes recent sector performance to identify rotation patterns
        such as risk-on/risk-off shifts and cyclical rotations.

        Args:
            sector_metrics: Dictionary of sector metrics.
            lookback_days: Number of days to analyze for rotation.

        Returns:
            Dictionary containing rotation analysis results.
        """
        if not sector_metrics:
            return {
                "rotation_detected": False,
                "rotation_type": None,
                "leading_sectors": [],
                "lagging_sectors": [],
                "signals": [],
            }

        # Sort sectors by momentum score
        sorted_sectors = sorted(
            sector_metrics.values(),
            key=lambda x: x.momentum_score,
            reverse=True
        )

        leading_sectors = sorted_sectors[:3]
        lagging_sectors = sorted_sectors[-3:]

        # Analyze rotation type
        rotation_type = self._determine_rotation_type(leading_sectors, lagging_sectors)

        # Generate rotation signals
        signals: list[dict[str, Any]] = []

        # Risk-on vs risk-off signal
        cyclical_strength = sum(
            m.momentum_score for symbol, m in sector_metrics.items()
            if self.SECTOR_CHARACTERISTICS.get(symbol, {}).get('cyclicality') == 'cyclical'
        )
        defensive_strength = sum(
            m.momentum_score for symbol, m in sector_metrics.items()
            if self.SECTOR_CHARACTERISTICS.get(symbol, {}).get('cyclicality') == 'defensive'
        )

        if cyclical_strength > defensive_strength * 1.1:
            signals.append({
                "signal": "risk_on",
                "description": "Cyclical sectors outperforming defensive sectors",
                "strength": "strong" if cyclical_strength > defensive_strength * 1.3 else "moderate"
            })
        elif defensive_strength > cyclical_strength * 1.1:
            signals.append({
                "signal": "risk_off",
                "description": "Defensive sectors outperforming cyclical sectors",
                "strength": "strong" if defensive_strength > cyclical_strength * 1.3 else "moderate"
            })

        # Growth vs value signal
        growth_strength = sum(
            m.momentum_score for symbol, m in sector_metrics.items()
            if self.SECTOR_CHARACTERISTICS.get(symbol, {}).get('cyclicality') == 'growth'
        )

        if growth_strength > cyclical_strength:
            signals.append({
                "signal": "growth_favored",
                "description": "Growth sectors showing relative strength",
                "strength": "moderate"
            })

        return {
            "rotation_detected": len(signals) > 0,
            "rotation_type": rotation_type,
            "leading_sectors": [
                {"symbol": s.symbol, "name": s.name, "momentum": s.momentum_score}
                for s in leading_sectors
            ],
            "lagging_sectors": [
                {"symbol": s.symbol, "name": s.name, "momentum": s.momentum_score}
                for s in lagging_sectors
            ],
            "signals": signals,
            "cyclical_vs_defensive": {
                "cyclical_strength": round(cyclical_strength, 2),
                "defensive_strength": round(defensive_strength, 2),
                "ratio": round(cyclical_strength / defensive_strength, 2) if defensive_strength != 0 else 0
            }
        }

    def _determine_rotation_type(
        self,
        leading: list[SectorMetrics],
        lagging: list[SectorMetrics]
    ) -> str:
        """Determine the type of rotation occurring."""
        leading_symbols = {s.symbol for s in leading}

        # Check for classic defensive rotation
        defensive_sectors = {"XLV", "XLP", "XLU", "XLRE"}
        if len(leading_symbols & defensive_sectors) >= 2:
            return "defensive_rotation"

        # Check for cyclical rotation
        cyclical_sectors = {"XLF", "XLY", "XLI", "XLE", "XLB"}
        if len(leading_symbols & cyclical_sectors) >= 2:
            return "cyclical_rotation"

        # Check for tech/growth rotation
        growth_sectors = {"XLK", "XLC"}
        if len(leading_symbols & growth_sectors) >= 1:
            return "growth_rotation"

        return "mixed_rotation"

    async def identify_market_phase(
        self,
        economic_data: dict[str, float],
        sector_performance: dict[str, SectorMetrics]
    ) -> SectorPhase:
        """Identify current market cycle phase.

        Uses economic indicators and sector performance to determine
        the current phase of the business cycle.

        Args:
            economic_data: Dictionary of economic indicators including:
                - gdp_growth: GDP growth rate (%)
                - inflation: Inflation rate (%)
                - unemployment: Unemployment rate (%)
                - yield_curve: 10Y-2Y spread
                - pmi: Manufacturing PMI
            sector_performance: Dictionary of sector metrics.

        Returns:
            The identified SectorPhase.
        """
        # Default values if not provided
        gdp_growth = economic_data.get('gdp_growth', 2.0)
        inflation = economic_data.get('inflation', 2.5)
        unemployment = economic_data.get('unemployment', 4.0)
        yield_curve = economic_data.get('yield_curve', 0.5)
        pmi = economic_data.get('pmi', 50.0)

        # Score each phase based on economic indicators
        phase_scores: dict[SectorPhase, float] = {phase: 0.0 for phase in SectorPhase}

        # Early expansion: rising GDP, low inflation, falling unemployment
        if 0 < gdp_growth < 3 and inflation < 3 and yield_curve > 0:
            phase_scores[SectorPhase.EARLY_EXPANSION] += 2
        if pmi > 50 and pmi < 55:
            phase_scores[SectorPhase.EARLY_EXPANSION] += 1

        # Mid expansion: strong GDP, moderate inflation
        if gdp_growth > 2.5 and inflation < 4:
            phase_scores[SectorPhase.MID_EXPANSION] += 2
        if pmi > 53:
            phase_scores[SectorPhase.MID_EXPANSION] += 1

        # Late expansion: high GDP, rising inflation
        if gdp_growth > 3 or inflation > 3:
            phase_scores[SectorPhase.LATE_EXPANSION] += 2
        if yield_curve < 0.5 and yield_curve > 0:
            phase_scores[SectorPhase.LATE_EXPANSION] += 1

        # Early contraction: slowing GDP, yield curve inverting
        if gdp_growth < 2 or yield_curve < 0:
            phase_scores[SectorPhase.EARLY_CONTRACTION] += 2
        if pmi < 50:
            phase_scores[SectorPhase.EARLY_CONTRACTION] += 1

        # Late contraction: negative GDP, high unemployment
        if gdp_growth < 0:
            phase_scores[SectorPhase.LATE_CONTRACTION] += 3
        if unemployment > 5:
            phase_scores[SectorPhase.LATE_CONTRACTION] += 1

        # Adjust based on sector performance alignment
        for phase, expected_leaders in self.CYCLE_LEADERS.items():
            alignment_score = 0
            for symbol in expected_leaders:
                if symbol in sector_performance:
                    metrics = sector_performance[symbol]
                    if metrics.relative_strength > 1.05:
                        alignment_score += 1
            phase_scores[phase] += alignment_score * 0.5

        # Return phase with highest score
        return max(phase_scores.keys(), key=lambda p: phase_scores[p])

    async def generate_sector_insights(
        self,
        metrics: dict[str, SectorMetrics],
        phase: SectorPhase
    ) -> list[dict[str, Any]]:
        """Generate actionable sector insights.

        Creates insights based on current sector performance and
        the identified market cycle phase.

        Args:
            metrics: Dictionary of sector metrics.
            phase: Current market cycle phase.

        Returns:
            List of insight dictionaries with actionable recommendations.
        """
        insights: list[dict[str, Any]] = []

        # Get expected leaders for current phase
        expected_leaders = self.CYCLE_LEADERS.get(phase, [])

        # Insight 1: Phase-aligned positioning
        phase_aligned: list[SectorMetrics] = []
        phase_misaligned: list[SectorMetrics] = []
        for symbol in expected_leaders:
            if symbol in metrics:
                m = metrics[symbol]
                if m.relative_strength > 1.0:
                    phase_aligned.append(m)
                else:
                    phase_misaligned.append(m)

        if phase_aligned:
            insights.append({
                "type": "phase_alignment",
                "priority": "high",
                "title": "Phase-Aligned Sector Strength",
                "description": f"The following sectors are outperforming as expected in {phase.value}: "
                              f"{', '.join(s.name for s in phase_aligned)}",
                "action": "Consider maintaining or increasing exposure to phase-aligned outperformers",
                "sectors": [{"symbol": s.symbol, "name": s.name, "rs": s.relative_strength} for s in phase_aligned]
            })

        # Insight 2: Rotation opportunities
        sorted_by_rs = sorted(metrics.values(), key=lambda x: x.relative_strength, reverse=True)
        strongest = sorted_by_rs[:3]

        if strongest and strongest[0].relative_strength > 1.1:
            insights.append({
                "type": "rotation_opportunity",
                "priority": "medium",
                "title": "Strong Relative Performers",
                "description": "Sectors showing significant outperformance vs S&P 500",
                "action": "Review for potential overweight positions",
                "sectors": [
                    {"symbol": s.symbol, "name": s.name, "rs": round(s.relative_strength, 3)}
                    for s in strongest if s.relative_strength > 1.05
                ]
            })

        # Insight 3: Risk warnings
        warnings: list[dict[str, Any]] = []
        for symbol, m in metrics.items():
            # High volatility warning
            if m.volatility > 2.5:
                warnings.append({
                    "sector": m.name,
                    "symbol": symbol,
                    "issue": "elevated_volatility",
                    "detail": f"Volatility at {m.volatility:.1f}%"
                })
            # Divergence from expected performance
            characteristics = self.SECTOR_CHARACTERISTICS.get(symbol, {})
            if characteristics.get('cyclicality') == 'defensive' and m.monthly_return > 5:
                warnings.append({
                    "sector": m.name,
                    "symbol": symbol,
                    "issue": "unusual_strength",
                    "detail": "Defensive sector showing unusual strength - possible risk-off signal"
                })

        if warnings:
            insights.append({
                "type": "risk_warning",
                "priority": "high",
                "title": "Sector Risk Alerts",
                "description": "Notable risk factors detected in sector analysis",
                "action": "Review positions in affected sectors",
                "warnings": warnings
            })

        # Insight 4: Volume confirmation
        volume_divergences: list[dict[str, str]] = []
        for symbol, m in metrics.items():
            if m.monthly_return > 3 and m.volume_trend == "decreasing":
                volume_divergences.append({
                    "sector": m.name,
                    "symbol": symbol,
                    "issue": "Price up on declining volume"
                })
            elif m.monthly_return < -3 and m.volume_trend == "increasing":
                volume_divergences.append({
                    "sector": m.name,
                    "symbol": symbol,
                    "issue": "Price down on increasing volume (capitulation?)"
                })

        if volume_divergences:
            insights.append({
                "type": "volume_analysis",
                "priority": "medium",
                "title": "Volume Divergences",
                "description": "Price/volume divergences may signal trend changes",
                "action": "Monitor for potential reversals",
                "divergences": volume_divergences
            })

        # Insight 5: Phase transition signals
        if phase_misaligned and len(phase_misaligned) >= 2:
            insights.append({
                "type": "phase_transition",
                "priority": "medium",
                "title": "Potential Phase Transition",
                "description": f"Expected phase leaders are underperforming: "
                              f"{', '.join(s.name for s in phase_misaligned)}",
                "action": "Watch for signs of market cycle transition",
                "sectors": [{"symbol": s.symbol, "name": s.name, "rs": s.relative_strength} for s in phase_misaligned]
            })

        # Sort insights by priority
        priority_order = {"high": 0, "medium": 1, "low": 2}
        insights.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 2))

        return insights

    async def get_sector_summary(
        self,
        sector_prices: dict[str, list[dict[str, Any]]],
        benchmark_prices: list[dict[str, Any]],
        economic_data: Optional[dict[str, float]] = None
    ) -> dict[str, Any]:
        """Generate a comprehensive sector analysis summary.

        This is a convenience method that runs the full analysis pipeline.

        Args:
            sector_prices: Dictionary mapping sector symbols to price history.
            benchmark_prices: Price history for the benchmark (SPY).
            economic_data: Optional dictionary of economic indicators.

        Returns:
            Comprehensive sector analysis summary.
        """
        # Calculate metrics
        metrics = await self.calculate_sector_metrics(sector_prices)

        # Calculate relative strength
        relative_strength = await self.calculate_relative_strength(sector_prices, benchmark_prices)

        # Update metrics with relative strength
        for symbol, rs in relative_strength.items():
            if symbol in metrics:
                metrics[symbol].relative_strength = rs

        # Identify market phase
        economic_data = economic_data or {}
        phase = await self.identify_market_phase(economic_data, metrics)

        # Detect rotation
        rotation = await self.detect_rotation(metrics)

        # Generate insights
        insights = await self.generate_sector_insights(metrics, phase)

        return {
            "timestamp": datetime.now().isoformat(),
            "market_phase": phase.value,
            "phase_description": self._get_phase_description(phase),
            "expected_leaders": self.CYCLE_LEADERS.get(phase, []),
            "sector_metrics": {
                symbol: {
                    "name": m.name,
                    "daily_return": round(m.daily_return, 2),
                    "weekly_return": round(m.weekly_return, 2),
                    "monthly_return": round(m.monthly_return, 2),
                    "quarterly_return": round(m.quarterly_return, 2),
                    "ytd_return": round(m.ytd_return, 2),
                    "relative_strength": round(m.relative_strength, 3),
                    "momentum_score": round(m.momentum_score, 2),
                    "volatility": round(m.volatility, 2),
                    "volume_trend": m.volume_trend,
                }
                for symbol, m in metrics.items()
            },
            "rotation_analysis": rotation,
            "insights": insights,
        }

    def _get_phase_description(self, phase: SectorPhase) -> str:
        """Get human-readable description of market phase."""
        descriptions = {
            SectorPhase.EARLY_EXPANSION: "Economy recovering, interest rates low, credit expanding",
            SectorPhase.MID_EXPANSION: "Strong growth phase, corporate profits rising, employment improving",
            SectorPhase.LATE_EXPANSION: "Peak growth, inflation rising, Fed may tighten",
            SectorPhase.EARLY_CONTRACTION: "Growth slowing, yield curve flat/inverted, defensive positioning",
            SectorPhase.LATE_CONTRACTION: "Recessionary conditions, flight to safety, dividend focus",
        }
        return descriptions.get(phase, "Unknown phase")


# Module-level singleton instance
sector_analyzer = SectorAnalyzer()
