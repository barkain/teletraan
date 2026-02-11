"""Macro Scanner agent for autonomous scanning of global macro conditions.

This module provides the MacroScanner class that autonomously scans global
macro conditions affecting US markets without requiring user-provided symbols.
It serves as Phase 1 of the autonomous analysis pipeline, identifying current
macro themes and their market implications.

Data Sources (free via yfinance):
- Treasury yields: ^TNX (10Y), ^TYX (30Y), ^FVX (5Y)
- VIX: ^VIX
- Dollar Index: DX-Y.NYB
- Gold: GC=F
- Oil: CL=F
- Major indices: ^GSPC (S&P500), ^DJI, ^IXIC (Nasdaq), ^RUT (Russell)
- Global indices: ^FTSE, ^GDAXI (DAX), ^N225 (Nikkei), ^HSI (Hang Seng)
- Sector ETFs: XLK, XLF, XLE, XLV, XLI, XLP, XLY, XLU, XLC, XLRE, XLB
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from data.adapters.yahoo import YahooFinanceAdapter, YahooFinanceError  # type: ignore[import-not-found]
from llm.client_pool import pool_query_llm  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)


# =============================================================================
# MACRO SCANNER PROMPT
# =============================================================================

MACRO_SCANNER_PROMPT = """You are a Global Macro Analyst scanning current market conditions.

## Your Role
Autonomously identify macro themes affecting US markets without requiring specific stock symbols.
You scan treasury yields, volatility, currencies, commodities, and global indices to assess the macro environment.

## Current Market Data (20-day trends):
{macro_data_formatted}

## Your Task
Analyze the macro environment and identify:

1. **MARKET REGIME** (1 of: Risk-On, Risk-Off, Transitional, Range-Bound)
   - Key evidence supporting this classification
   - Confidence level in regime assessment

2. **TOP 3 MACRO THEMES** affecting US markets right now:
   For each theme:
   - Theme name (e.g., "Fed Policy Pivot", "China Reopening", "Energy Crisis", "Dollar Strength")
   - Direction of impact (bullish/bearish/mixed)
   - Affected sectors (list of sectors like Technology, Energy, Financials, etc.)
   - Affected assets (specific ETFs or asset classes)
   - Confidence level (high/medium/low)
   - Brief rationale (2-3 sentences)

3. **KEY RISKS** to monitor (2-3 risks)
   - Risk description
   - Probability (high/medium/low)
   - Potential impact

4. **ACTIONABLE IMPLICATIONS** for US equity positioning
   - Sector preferences (overweight/underweight)
   - Risk posture (defensive/neutral/aggressive)
   - Key levels to watch

## Output Format
Return your analysis as valid JSON:
{{
  "scan_timestamp": "2024-01-15T10:30:00Z",
  "market_regime": "Risk-On",
  "regime_confidence": 0.75,
  "regime_evidence": [
    "VIX below 15 indicating complacency",
    "Treasury yields stable indicating no flight to safety",
    "Risk assets outperforming safe havens"
  ],
  "themes": [
    {{
      "name": "Fed Policy Pivot",
      "direction": "bullish",
      "affected_sectors": ["Technology", "Real Estate", "Consumer Discretionary"],
      "affected_assets": ["XLK", "XLRE", "XLY", "TLT"],
      "confidence": "high",
      "rationale": "Fed signaling end of hiking cycle. Market pricing in rate cuts by mid-year. Bonds rallying as yields decline."
    }}
  ],
  "key_risks": [
    {{
      "description": "Sticky services inflation could delay Fed pivot",
      "probability": "medium",
      "impact": "Reversal of recent rally in rate-sensitive sectors"
    }}
  ],
  "actionable_implications": {{
    "sector_preferences": {{
      "overweight": ["Technology", "Consumer Discretionary"],
      "underweight": ["Utilities", "Consumer Staples"],
      "neutral": ["Financials", "Healthcare"]
    }},
    "risk_posture": "neutral",
    "key_levels": [
      "SPY 480 support",
      "VIX 20 resistance",
      "10Y yield 4.0% pivot"
    ]
  }}
}}

## Prediction Market Signals
When prediction market data is available, incorporate market-implied probabilities into your macro assessment:
- Federal Reserve rate expectations (hold/cut/hike probabilities per meeting)
- Recession probability from prediction markets
- Inflation expectations (CPI above/below thresholds)
- GDP growth expectations

These represent real-money bets on macro outcomes and should be weighed alongside traditional indicators.

## Social Sentiment Overview
When Reddit sentiment data is available, note the overall retail investor mood:
- Overall market sentiment score and direction
- Top trending tickers and their sentiment
- Use as a supplementary signal -- high retail bullishness can be contrarian (late-cycle indicator)

## Guidelines
- Be specific with data and percentages
- Focus on actionable insights, not just observations
- Note when signals conflict and how to interpret
- Prioritize themes by their likely market impact
- Consider both US and global factors
"""


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class MacroTheme:
    """Represents a single macro theme affecting markets."""

    name: str
    direction: str  # bullish, bearish, mixed
    affected_sectors: list[str] = field(default_factory=list)
    affected_assets: list[str] = field(default_factory=list)
    confidence: str = "medium"  # high, medium, low
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "name": self.name,
            "direction": self.direction,
            "affected_sectors": self.affected_sectors,
            "affected_assets": self.affected_assets,
            "confidence": self.confidence,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MacroTheme:
        """Create from dictionary."""
        return cls(
            name=data.get("name", "Unknown Theme"),
            direction=data.get("direction", "mixed"),
            affected_sectors=data.get("affected_sectors", []),
            affected_assets=data.get("affected_assets", []),
            confidence=data.get("confidence", "medium"),
            rationale=data.get("rationale", ""),
        )


@dataclass
class MacroRisk:
    """Represents a macro risk to monitor."""

    description: str
    probability: str = "medium"  # high, medium, low
    impact: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "description": self.description,
            "probability": self.probability,
            "impact": self.impact,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MacroRisk:
        """Create from dictionary."""
        return cls(
            description=data.get("description", ""),
            probability=data.get("probability", "medium"),
            impact=data.get("impact", ""),
        )


@dataclass
class SectorPreferences:
    """Represents sector preferences from macro analysis."""

    overweight: list[str] = field(default_factory=list)
    underweight: list[str] = field(default_factory=list)
    neutral: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "overweight": self.overweight,
            "underweight": self.underweight,
            "neutral": self.neutral,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SectorPreferences:
        """Create from dictionary."""
        return cls(
            overweight=data.get("overweight", []),
            underweight=data.get("underweight", []),
            neutral=data.get("neutral", []),
        )


@dataclass
class ActionableImplications:
    """Represents actionable implications from macro analysis."""

    sector_preferences: SectorPreferences = field(default_factory=SectorPreferences)
    risk_posture: str = "neutral"  # defensive, neutral, aggressive
    key_levels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "sector_preferences": self.sector_preferences.to_dict(),
            "risk_posture": self.risk_posture,
            "key_levels": self.key_levels,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActionableImplications:
        """Create from dictionary."""
        sector_prefs_data = data.get("sector_preferences", {})
        return cls(
            sector_preferences=SectorPreferences.from_dict(sector_prefs_data),
            risk_posture=data.get("risk_posture", "neutral"),
            key_levels=data.get("key_levels", []),
        )


@dataclass
class MacroScanResult:
    """Complete result from macro environment scan."""

    scan_timestamp: datetime = field(default_factory=datetime.utcnow)
    market_regime: str = "Range-Bound"  # Risk-On, Risk-Off, Transitional, Range-Bound
    regime_confidence: float = 0.5
    regime_evidence: list[str] = field(default_factory=list)
    themes: list[MacroTheme] = field(default_factory=list)
    key_risks: list[MacroRisk] = field(default_factory=list)
    actionable_implications: ActionableImplications = field(
        default_factory=ActionableImplications
    )
    raw_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary format."""
        return {
            "scan_timestamp": self.scan_timestamp.isoformat(),
            "market_regime": self.market_regime,
            "regime_confidence": round(self.regime_confidence, 4),
            "regime_evidence": self.regime_evidence,
            "themes": [t.to_dict() for t in self.themes],
            "key_risks": [r.to_dict() for r in self.key_risks],
            "actionable_implications": self.actionable_implications.to_dict(),
            "raw_data": self.raw_data,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MacroScanResult:
        """Create from dictionary."""
        # Parse timestamp
        timestamp = data.get("scan_timestamp")
        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.utcnow()
        elif not isinstance(timestamp, datetime):
            timestamp = datetime.utcnow()

        # Parse themes
        themes = []
        for t_data in data.get("themes", []):
            if isinstance(t_data, dict):
                themes.append(MacroTheme.from_dict(t_data))

        # Parse risks
        risks = []
        for r_data in data.get("key_risks", []):
            if isinstance(r_data, dict):
                risks.append(MacroRisk.from_dict(r_data))

        # Parse actionable implications
        implications_data = data.get("actionable_implications", {})
        implications = ActionableImplications.from_dict(implications_data)

        return cls(
            scan_timestamp=timestamp,
            market_regime=data.get("market_regime", "Range-Bound"),
            regime_confidence=float(data.get("regime_confidence", 0.5)),
            regime_evidence=data.get("regime_evidence", []),
            themes=themes,
            key_risks=risks,
            actionable_implications=implications,
            raw_data=data.get("raw_data", {}),
        )


# =============================================================================
# MACRO SCANNER CLASS
# =============================================================================


class MacroScanner:
    """
    Phase 1: Autonomous macro environment scanner.

    Identifies key themes affecting US markets without requiring user input.
    Fetches macro data via yfinance and uses LLM analysis to extract themes.

    Attributes:
        name: Display name of the scanner.
        role: Role description for LLM context.
        data_adapter: Yahoo Finance adapter for data fetching.

    Example:
        ```python
        scanner = MacroScanner(llm_client)
        result = await scanner.scan()

        print(f"Regime: {result.market_regime}")
        for theme in result.themes:
            print(f"Theme: {theme.name} ({theme.direction})")
        ```
    """

    # Macro data symbols organized by category
    TREASURY_SYMBOLS = {
        "^TNX": "10-Year Treasury Yield",
        "^TYX": "30-Year Treasury Yield",
        "^FVX": "5-Year Treasury Yield",
    }

    VOLATILITY_SYMBOLS = {
        "^VIX": "CBOE Volatility Index",
    }

    CURRENCY_SYMBOLS = {
        "DX-Y.NYB": "US Dollar Index",
    }

    COMMODITY_SYMBOLS = {
        "GC=F": "Gold Futures",
        "CL=F": "Crude Oil Futures",
    }

    US_INDEX_SYMBOLS = {
        "^GSPC": "S&P 500",
        "^DJI": "Dow Jones Industrial",
        "^IXIC": "NASDAQ Composite",
        "^RUT": "Russell 2000",
    }

    GLOBAL_INDEX_SYMBOLS = {
        "^FTSE": "FTSE 100 (UK)",
        "^GDAXI": "DAX (Germany)",
        "^N225": "Nikkei 225 (Japan)",
        "^HSI": "Hang Seng (Hong Kong)",
    }

    SECTOR_ETF_SYMBOLS = {
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

    def __init__(
        self,
        llm_client: Any | None = None,
        data_adapter: YahooFinanceAdapter | None = None,
    ) -> None:
        """Initialize the macro scanner.

        Args:
            llm_client: Optional LLM client for analysis. If None, uses
                ClaudeSDKClient when scan() is called.
            data_adapter: Optional Yahoo Finance adapter. If None, creates one.
        """
        self.name = "Macro Scanner"
        self.role = "Global Macro Analyst"
        self.llm_client = llm_client
        self.data_adapter = data_adapter or YahooFinanceAdapter()

    async def scan(self, context: dict[str, Any] | None = None) -> MacroScanResult:
        """
        Scan macro environment and return key themes.

        Performs full macro scan:
        1. Fetches macro data from yfinance
        2. Formats data for LLM analysis
        3. Queries LLM for theme identification
        4. Parses and returns structured result

        Args:
            context: Optional context dict that may contain 'predictions'
                and/or 'sentiment' data from the context builder pipeline.

        Returns:
            MacroScanResult with market regime, themes, risks, and implications.

        Raises:
            Exception: If data fetching or LLM query fails.
        """
        scan_start = datetime.utcnow()
        logger.info("Starting macro environment scan...")

        # Step 1: Fetch macro data
        logger.info("Fetching macro data from yfinance...")
        macro_data = await self._fetch_macro_data()
        logger.info(f"Fetched data for {len(macro_data)} categories")

        # Step 2: Format data for LLM
        formatted_data = self._format_macro_data(macro_data)
        logger.info(f"Formatted macro data: {len(formatted_data)} chars")

        # Step 2b: Append prediction/sentiment context if available
        if context:
            formatted_data = self._append_alternative_data(formatted_data, context)

        # Step 3: Build prompt
        prompt = self._build_scan_prompt(formatted_data)

        # Step 4: Query LLM
        logger.info("Querying LLM for macro analysis...")
        response = await self._query_llm(prompt)
        logger.info(f"Received LLM response: {len(response)} chars")

        # Step 5: Parse response
        result = self._parse_result(response)
        result.raw_data = macro_data  # Store raw data for reference
        result.scan_timestamp = scan_start

        elapsed = (datetime.utcnow() - scan_start).total_seconds()
        logger.info(
            f"Macro scan complete in {elapsed:.1f}s: "
            f"regime={result.market_regime}, themes={len(result.themes)}"
        )

        return result

    async def _fetch_macro_data(self) -> dict[str, Any]:
        """Fetch all macro indicators via yfinance.

        Fetches 20-day historical data for trend analysis across all
        macro indicator categories.

        Returns:
            Dictionary with macro data organized by category.
        """
        macro_data: dict[str, Any] = {
            "treasuries": {},
            "volatility": {},
            "currencies": {},
            "commodities": {},
            "us_indices": {},
            "global_indices": {},
            "sector_etfs": {},
        }

        # Create tasks for parallel fetching
        all_tasks: list[tuple[str, str, str, asyncio.Task[Any]]] = []

        # Treasury yields (20-day history)
        for symbol, name in self.TREASURY_SYMBOLS.items():
            task = asyncio.create_task(self._fetch_ticker_data(symbol, days=20))
            all_tasks.append(("treasuries", symbol, name, task))

        # Volatility (20-day history)
        for symbol, name in self.VOLATILITY_SYMBOLS.items():
            task = asyncio.create_task(self._fetch_ticker_data(symbol, days=20))
            all_tasks.append(("volatility", symbol, name, task))

        # Currencies (20-day history)
        for symbol, name in self.CURRENCY_SYMBOLS.items():
            task = asyncio.create_task(self._fetch_ticker_data(symbol, days=20))
            all_tasks.append(("currencies", symbol, name, task))

        # Commodities (20-day history)
        for symbol, name in self.COMMODITY_SYMBOLS.items():
            task = asyncio.create_task(self._fetch_ticker_data(symbol, days=20))
            all_tasks.append(("commodities", symbol, name, task))

        # US indices (20-day history)
        for symbol, name in self.US_INDEX_SYMBOLS.items():
            task = asyncio.create_task(self._fetch_ticker_data(symbol, days=20))
            all_tasks.append(("us_indices", symbol, name, task))

        # Global indices (5-day history - less critical)
        for symbol, name in self.GLOBAL_INDEX_SYMBOLS.items():
            task = asyncio.create_task(self._fetch_ticker_data(symbol, days=5))
            all_tasks.append(("global_indices", symbol, name, task))

        # Sector ETFs (20-day history)
        for symbol, name in self.SECTOR_ETF_SYMBOLS.items():
            task = asyncio.create_task(self._fetch_ticker_data(symbol, days=20))
            all_tasks.append(("sector_etfs", symbol, name, task))

        # Gather all results
        for category, symbol, name, task in all_tasks:
            try:
                data = await task
                if data:
                    macro_data[category][symbol] = {
                        "name": name,
                        "data": data,
                    }
            except Exception as e:
                logger.warning(f"Failed to fetch {symbol}: {e}")

        return macro_data

    async def _fetch_ticker_data(
        self,
        symbol: str,
        days: int = 20,
    ) -> dict[str, Any] | None:
        """Fetch price data for a single ticker.

        Args:
            symbol: Ticker symbol to fetch.
            days: Number of days of history to fetch.

        Returns:
            Dictionary with price data and computed metrics, or None on failure.
        """
        try:
            # Calculate period based on days (add buffer for weekends)
            if days <= 5:
                period = "5d"
            elif days <= 20:
                period = "1mo"
            else:
                period = "3mo"

            # Fetch price history
            prices = await self.data_adapter.get_price_history(
                symbol=symbol,
                period=period,
            )

            if not prices:
                return None

            # Take last N days
            prices = prices[-days:] if len(prices) > days else prices

            # Calculate metrics
            latest = prices[-1] if prices else None
            oldest = prices[0] if prices else None

            if not latest or not oldest:
                return None

            current_price = latest.get("close", 0)
            start_price = oldest.get("close", 0)
            high_20d = max(p.get("high", 0) for p in prices)
            low_20d = min(p.get("low", float("inf")) for p in prices)

            # Calculate change
            change_pct = 0.0
            if start_price and start_price > 0:
                change_pct = ((current_price - start_price) / start_price) * 100

            # Calculate trend (simple: above/below 10-day average)
            if len(prices) >= 10:
                avg_10d = sum(p.get("close", 0) for p in prices[-10:]) / 10
                trend = "up" if current_price > avg_10d else "down"
            else:
                trend = "flat"

            return {
                "current": round(current_price, 4),
                "change_20d_pct": round(change_pct, 2),
                "high_20d": round(high_20d, 4),
                "low_20d": round(low_20d, 4),
                "trend": trend,
                "data_points": len(prices),
            }

        except YahooFinanceError as e:
            logger.warning(f"Yahoo Finance error for {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching {symbol}: {e}")
            return None

    def _format_macro_data(self, macro_data: dict[str, Any]) -> str:
        """Format macro data as a readable string for the LLM.

        Args:
            macro_data: Raw macro data from _fetch_macro_data.

        Returns:
            Formatted string for inclusion in the prompt.
        """
        sections = []

        # Treasury Yields
        treasuries = macro_data.get("treasuries", {})
        if treasuries:
            lines = ["=== TREASURY YIELDS ==="]
            for symbol, info in treasuries.items():
                data = info.get("data", {})
                name = info.get("name", symbol)
                current = data.get("current", 0)
                change = data.get("change_20d_pct", 0)
                trend = data.get("trend", "flat")
                lines.append(
                    f"{name} ({symbol}): {current:.3f}% | "
                    f"20D Change: {change:+.2f}% | Trend: {trend}"
                )
            sections.append("\n".join(lines))

        # Volatility
        volatility = macro_data.get("volatility", {})
        if volatility:
            lines = ["=== VOLATILITY ==="]
            for symbol, info in volatility.items():
                data = info.get("data", {})
                name = info.get("name", symbol)
                current = data.get("current", 0)
                high = data.get("high_20d", 0)
                low = data.get("low_20d", 0)
                trend = data.get("trend", "flat")
                lines.append(
                    f"{name} ({symbol}): {current:.2f} | "
                    f"20D Range: {low:.2f} - {high:.2f} | Trend: {trend}"
                )
            sections.append("\n".join(lines))

        # Currencies
        currencies = macro_data.get("currencies", {})
        if currencies:
            lines = ["=== CURRENCIES ==="]
            for symbol, info in currencies.items():
                data = info.get("data", {})
                name = info.get("name", symbol)
                current = data.get("current", 0)
                change = data.get("change_20d_pct", 0)
                trend = data.get("trend", "flat")
                lines.append(
                    f"{name} ({symbol}): {current:.2f} | "
                    f"20D Change: {change:+.2f}% | Trend: {trend}"
                )
            sections.append("\n".join(lines))

        # Commodities
        commodities = macro_data.get("commodities", {})
        if commodities:
            lines = ["=== COMMODITIES ==="]
            for symbol, info in commodities.items():
                data = info.get("data", {})
                name = info.get("name", symbol)
                current = data.get("current", 0)
                change = data.get("change_20d_pct", 0)
                trend = data.get("trend", "flat")
                lines.append(
                    f"{name} ({symbol}): ${current:.2f} | "
                    f"20D Change: {change:+.2f}% | Trend: {trend}"
                )
            sections.append("\n".join(lines))

        # US Indices
        us_indices = macro_data.get("us_indices", {})
        if us_indices:
            lines = ["=== US INDICES ==="]
            for symbol, info in us_indices.items():
                data = info.get("data", {})
                name = info.get("name", symbol)
                current = data.get("current", 0)
                change = data.get("change_20d_pct", 0)
                trend = data.get("trend", "flat")
                lines.append(
                    f"{name} ({symbol}): {current:,.2f} | "
                    f"20D Change: {change:+.2f}% | Trend: {trend}"
                )
            sections.append("\n".join(lines))

        # Global Indices
        global_indices = macro_data.get("global_indices", {})
        if global_indices:
            lines = ["=== GLOBAL INDICES ==="]
            for symbol, info in global_indices.items():
                data = info.get("data", {})
                name = info.get("name", symbol)
                current = data.get("current", 0)
                change = data.get("change_20d_pct", 0)
                trend = data.get("trend", "flat")
                lines.append(
                    f"{name} ({symbol}): {current:,.2f} | "
                    f"5D Change: {change:+.2f}% | Trend: {trend}"
                )
            sections.append("\n".join(lines))

        # Sector ETFs
        sector_etfs = macro_data.get("sector_etfs", {})
        if sector_etfs:
            lines = ["=== SECTOR ETF PERFORMANCE ==="]
            # Sort by performance
            sorted_sectors = sorted(
                sector_etfs.items(),
                key=lambda x: x[1].get("data", {}).get("change_20d_pct", 0),
                reverse=True,
            )
            for symbol, info in sorted_sectors:
                data = info.get("data", {})
                name = info.get("name", symbol)
                current = data.get("current", 0)
                change = data.get("change_20d_pct", 0)
                trend = data.get("trend", "flat")
                lines.append(
                    f"{name} ({symbol}): ${current:.2f} | "
                    f"20D Change: {change:+.2f}% | Trend: {trend}"
                )
            sections.append("\n".join(lines))

        return "\n\n".join(sections)

    def _append_alternative_data(
        self, formatted_data: str, context: dict[str, Any]
    ) -> str:
        """Append prediction market and sentiment data to formatted macro data.

        Args:
            formatted_data: Already-formatted macro data string.
            context: Context dict that may contain 'predictions' and/or 'sentiment'.

        Returns:
            Formatted data string with alternative data appended (if available).
        """
        parts = [formatted_data]

        predictions = context.get("predictions")
        if predictions:
            from analysis.context_builder import format_prediction_context  # type: ignore[import-not-found]

            prediction_text = format_prediction_context(predictions)
            if prediction_text:
                parts.append(prediction_text)

        sentiment = context.get("sentiment")
        if sentiment:
            from analysis.context_builder import format_sentiment_context  # type: ignore[import-not-found]

            sentiment_text = format_sentiment_context(sentiment)
            if sentiment_text:
                parts.append(sentiment_text)

        return "\n\n".join(parts)

    def _build_scan_prompt(self, formatted_data: str) -> str:
        """Build the full prompt for LLM analysis.

        Args:
            formatted_data: Formatted macro data string.

        Returns:
            Complete prompt string.
        """
        return MACRO_SCANNER_PROMPT.format(macro_data_formatted=formatted_data)

    async def _query_llm(self, prompt: str) -> str:
        """Query the LLM for macro analysis.

        Args:
            prompt: Complete prompt with macro data.

        Returns:
            LLM response text.
        """
        if self.llm_client:
            # Use provided LLM client
            return await self.llm_client.analyze(prompt)

        return await pool_query_llm(
            system_prompt=f"You are a {self.role}.",
            user_prompt=prompt,
            agent_name=self.name,
        )

    def _parse_result(self, response: str) -> MacroScanResult:
        """Parse LLM response into MacroScanResult.

        Args:
            response: Raw LLM response text.

        Returns:
            Parsed MacroScanResult.
        """
        # Try to extract JSON from response
        json_data = self._extract_json(response)

        if json_data is None:
            logger.warning("Could not extract JSON from macro scanner response")
            return MacroScanResult(
                regime_evidence=[f"Raw response: {response[:500]}..."],
            )

        return MacroScanResult.from_dict(json_data)

    def _extract_json(self, text: str) -> dict[str, Any] | None:
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
            potential_json = text[start_idx : end_idx + 1]
            try:
                return json.loads(potential_json)
            except json.JSONDecodeError:
                pass

        return None


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def format_macro_scan_for_context(scan_result: MacroScanResult) -> str:
    """Format macro scan result for use in downstream analysis context.

    Creates a concise summary suitable for passing to other agents
    like SectorRotator or DeepDive analysts.

    Args:
        scan_result: Completed macro scan result.

    Returns:
        Formatted string for context injection.
    """
    lines = []

    lines.append("=== MACRO ENVIRONMENT SUMMARY ===")
    lines.append(f"Market Regime: {scan_result.market_regime}")
    lines.append(f"Regime Confidence: {scan_result.regime_confidence:.0%}")

    if scan_result.regime_evidence:
        lines.append("\nRegime Evidence:")
        for evidence in scan_result.regime_evidence[:3]:
            lines.append(f"  - {evidence}")

    if scan_result.themes:
        lines.append("\nActive Macro Themes:")
        for theme in scan_result.themes[:3]:
            direction_emoji = {
                "bullish": "+",
                "bearish": "-",
                "mixed": "~",
            }.get(theme.direction, "?")
            lines.append(
                f"  [{direction_emoji}] {theme.name} ({theme.confidence} confidence)"
            )
            if theme.affected_sectors:
                lines.append(f"      Sectors: {', '.join(theme.affected_sectors[:4])}")

    implications = scan_result.actionable_implications
    if implications.sector_preferences.overweight:
        lines.append(
            f"\nOverweight: {', '.join(implications.sector_preferences.overweight)}"
        )
    if implications.sector_preferences.underweight:
        lines.append(
            f"Underweight: {', '.join(implications.sector_preferences.underweight)}"
        )
    lines.append(f"Risk Posture: {implications.risk_posture}")

    if scan_result.key_risks:
        lines.append("\nKey Risks:")
        for risk in scan_result.key_risks[:2]:
            lines.append(f"  - {risk.description} ({risk.probability} probability)")

    return "\n".join(lines)


def get_affected_symbols_from_scan(scan_result: MacroScanResult) -> list[str]:
    """Extract all affected symbols from macro scan for downstream analysis.

    Args:
        scan_result: Completed macro scan result.

    Returns:
        List of unique ticker symbols mentioned in the scan.
    """
    symbols: set[str] = set()

    # Get symbols from themes
    for theme in scan_result.themes:
        for asset in theme.affected_assets:
            # Filter to ticker-like strings (uppercase, 1-5 chars)
            if asset.isupper() and 1 <= len(asset) <= 5:
                symbols.add(asset)

    # Add sector ETFs from preferences
    implications = scan_result.actionable_implications
    sector_to_etf = {
        "Technology": "XLK",
        "Financials": "XLF",
        "Energy": "XLE",
        "Healthcare": "XLV",
        "Industrials": "XLI",
        "Consumer Staples": "XLP",
        "Consumer Discretionary": "XLY",
        "Utilities": "XLU",
        "Communication Services": "XLC",
        "Real Estate": "XLRE",
        "Materials": "XLB",
    }

    for sector in implications.sector_preferences.overweight:
        if sector in sector_to_etf:
            symbols.add(sector_to_etf[sector])

    for sector in implications.sector_preferences.underweight:
        if sector in sector_to_etf:
            symbols.add(sector_to_etf[sector])

    return sorted(symbols)
