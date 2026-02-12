"""Technical Analyst agent prompt and helper functions.

This module provides the prompt template and utility functions for the Technical
Analyst agent, which specializes in chart pattern recognition, indicator analysis,
and multi-timeframe technical analysis.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """Types of technical signals."""
    BULLISH_DIVERGENCE = "bullish_divergence"
    BEARISH_DIVERGENCE = "bearish_divergence"
    GOLDEN_CROSS = "golden_cross"
    DEATH_CROSS = "death_cross"
    OVERBOUGHT = "overbought"
    OVERSOLD = "oversold"
    BREAKOUT = "breakout"
    BREAKDOWN = "breakdown"
    SUPPORT_TEST = "support_test"
    RESISTANCE_TEST = "resistance_test"
    TREND_REVERSAL = "trend_reversal"
    TREND_CONTINUATION = "trend_continuation"
    VOLUME_SPIKE = "volume_spike"
    VOLATILITY_EXPANSION = "volatility_expansion"
    VOLATILITY_CONTRACTION = "volatility_contraction"
    MACD_CROSSOVER = "macd_crossover"
    RSI_EXTREME = "rsi_extreme"
    BOLLINGER_SQUEEZE = "bollinger_squeeze"
    BOLLINGER_BREAKOUT = "bollinger_breakout"


class ActionBias(Enum):
    """Trading action bias."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    NEUTRAL = "NEUTRAL"


class Timeframe(Enum):
    """Analysis timeframes."""
    INTRADAY = "intraday"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass
class KeyLevels:
    """Support and resistance levels."""
    support: float | None = None
    resistance: float | None = None
    pivot: float | None = None

    def to_dict(self) -> dict[str, float | None]:
        """Convert to dictionary."""
        return {
            "support": self.support,
            "resistance": self.resistance,
            "pivot": self.pivot,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KeyLevels:
        """Create from dictionary."""
        return cls(
            support=data.get("support"),
            resistance=data.get("resistance"),
            pivot=data.get("pivot"),
        )


@dataclass
class TechnicalFinding:
    """A single technical analysis finding."""
    symbol: str
    signal: str
    description: str
    timeframe: str = "daily"
    confidence: float = 0.5
    key_levels: KeyLevels = field(default_factory=KeyLevels)
    action_bias: str = "HOLD"
    indicators_used: list[str] = field(default_factory=list)
    pattern_name: str | None = None
    price_target: float | None = None
    stop_loss: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "symbol": self.symbol,
            "signal": self.signal,
            "description": self.description,
            "timeframe": self.timeframe,
            "confidence": round(self.confidence, 4),
            "key_levels": self.key_levels.to_dict(),
            "action_bias": self.action_bias,
            "indicators_used": self.indicators_used,
            "pattern_name": self.pattern_name,
            "price_target": round(self.price_target, 2) if self.price_target else None,
            "stop_loss": round(self.stop_loss, 2) if self.stop_loss else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TechnicalFinding:
        """Create from dictionary."""
        key_levels_data = data.get("key_levels", {})
        if isinstance(key_levels_data, dict):
            key_levels = KeyLevels.from_dict(key_levels_data)
        else:
            key_levels = KeyLevels()

        return cls(
            symbol=data.get("symbol", "UNKNOWN"),
            signal=data.get("signal", ""),
            description=data.get("description", ""),
            timeframe=data.get("timeframe", "daily"),
            confidence=float(data.get("confidence", 0.5)),
            key_levels=key_levels,
            action_bias=data.get("action_bias", "HOLD"),
            indicators_used=data.get("indicators_used", []),
            pattern_name=data.get("pattern_name"),
            price_target=data.get("price_target"),
            stop_loss=data.get("stop_loss"),
        )


@dataclass
class TechnicalAnalysisResult:
    """Complete technical analysis result from the agent."""
    analyst: str = "technical"
    findings: list[TechnicalFinding] = field(default_factory=list)
    market_structure: str = "unknown"
    key_observations: list[str] = field(default_factory=list)
    confidence: float = 0.5
    analysis_timestamp: datetime = field(default_factory=datetime.utcnow)
    timeframes_analyzed: list[str] = field(default_factory=list)
    conflicting_signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "analyst": self.analyst,
            "findings": [f.to_dict() for f in self.findings],
            "market_structure": self.market_structure,
            "key_observations": self.key_observations,
            "confidence": round(self.confidence, 4),
            "analysis_timestamp": self.analysis_timestamp.isoformat(),
            "timeframes_analyzed": self.timeframes_analyzed,
            "conflicting_signals": self.conflicting_signals,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TechnicalAnalysisResult:
        """Create from dictionary."""
        findings = []
        for f_data in data.get("findings", []):
            if isinstance(f_data, dict):
                findings.append(TechnicalFinding.from_dict(f_data))

        timestamp = data.get("analysis_timestamp")
        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.utcnow()
        elif not isinstance(timestamp, datetime):
            timestamp = datetime.utcnow()

        return cls(
            analyst=data.get("analyst", "technical"),
            findings=findings,
            market_structure=data.get("market_structure", "unknown"),
            key_observations=data.get("key_observations", []),
            confidence=float(data.get("confidence", 0.5)),
            analysis_timestamp=timestamp,
            timeframes_analyzed=data.get("timeframes_analyzed", []),
            conflicting_signals=data.get("conflicting_signals", []),
        )


# =============================================================================
# TECHNICAL ANALYST PROMPT
# =============================================================================

TECHNICAL_ANALYST_PROMPT = """You are an expert Technical Analyst with 20+ years of experience in chart pattern recognition and indicator analysis.

## Your Expertise
- Multi-timeframe analysis (daily, weekly, monthly confluence)
- Classical chart patterns (head & shoulders, double tops/bottoms, triangles, flags)
- Indicator mastery (RSI, MACD, Bollinger Bands, volume analysis, moving averages)
- Support/resistance identification and breakout analysis
- Price-indicator divergences (bullish/bearish divergences)
- Trend strength assessment using ADX, moving average slopes

## Your Task
Analyze the provided market data and identify:
1. **Key technical setups** - Patterns forming or completing
2. **Indicator signals** - Overbought/oversold, divergences, crossovers
3. **Support/resistance levels** - Key price levels to watch
4. **Trend analysis** - Current trend strength and potential reversals
5. **Volume analysis** - Confirmation or divergence from price action

## Output Format
Return JSON:
{
  "analyst": "technical",
  "findings": [
    {
      "symbol": "NVDA",
      "signal": "bullish_divergence",
      "description": "RSI making higher lows while price made lower lows on daily chart",
      "timeframe": "daily",
      "confidence": 0.75,
      "key_levels": {"support": 850, "resistance": 920},
      "action_bias": "BUY",
      "indicators_used": ["RSI", "price_action"],
      "pattern_name": "bullish_divergence",
      "price_target": 920,
      "stop_loss": 840
    }
  ],
  "market_structure": "uptrend with consolidation",
  "key_observations": ["RSI showing bullish divergence", "Volume declining during pullback"],
  "confidence": 0.72,
  "timeframes_analyzed": ["daily", "weekly"],
  "conflicting_signals": ["Weekly MACD still bearish"]
}

## Signal Types
Use these signal types in your findings:
- bullish_divergence / bearish_divergence
- golden_cross / death_cross
- overbought / oversold
- breakout / breakdown
- support_test / resistance_test
- trend_reversal / trend_continuation
- volume_spike
- volatility_expansion / volatility_contraction
- macd_crossover
- rsi_extreme
- bollinger_squeeze / bollinger_breakout

## Action Bias Values
- BUY: Strong bullish setup with favorable risk/reward
- SELL: Strong bearish setup or exit signal
- HOLD: Maintain current position, no clear action
- NEUTRAL: Mixed signals, wait for confirmation

## Rich Technical Analysis Data

When rich technical analysis data is provided below, use it as the PRIMARY source for your technical assessment. This includes:
- Composite technical score (-1.0 to +1.0) with rating and confidence
- Detailed indicator breakdown by category (trend, momentum, volatility, volume)
- Individual indicator signals and values
- Key support/resistance levels
- Multi-timeframe alignment (if available)

Prioritize the composite score and indicator agreement when forming your technical thesis. Note any divergences between indicator categories (e.g., bullish trend but overbought momentum). Highlight key support/resistance levels for entry/exit recommendations.

If rich TA data is NOT provided, fall back to analyzing any basic indicators available in the standard context.

## Guidelines
- Be specific with price levels and percentages
- Note timeframe for each observation
- Distinguish between confirmed patterns and forming patterns
- Consider multiple timeframes before concluding
- Highlight any conflicting signals across timeframes
- Include stop loss and price target when providing action bias
- Use confidence scores between 0.0 and 1.0
- Higher confidence (>0.7) for confirmed patterns with volume
- Lower confidence (<0.5) for forming patterns or mixed signals
"""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def format_technical_context(market_data: dict[str, Any]) -> str:
    """Format market data for technical analyst consumption.

    Takes raw market data from context builder and formats it into a structured
    string that the technical analyst agent can easily parse and analyze.

    Args:
        market_data: Dictionary containing market data from context builder with keys:
            - stocks: List of stock metadata dicts
            - price_history: Dict mapping symbols to list of OHLCV dicts
            - technical_indicators: Dict mapping symbols to indicator values
            - market_summary: Overall market status

    Returns:
        Formatted string context for the technical analyst prompt.
    """
    context_parts: list[str] = []

    # Handle both old-style (per-stock) and new-style (aggregated) data formats
    # New format from context_builder has price_history as dict mapping symbol -> prices
    price_history = market_data.get("price_history", {})
    technical_indicators = market_data.get("technical_indicators", {})
    stocks = market_data.get("stocks", [])

    # If we have the new aggregated format, process each symbol
    if price_history and isinstance(price_history, dict):
        context_parts.append("# Technical Analysis Data\n")

        # Add market summary if available
        market_summary = market_data.get("market_summary", {})
        market_index = market_summary.get("market_index", {})
        if market_index:
            context_parts.append("## Market Overview (SPY)")
            context_parts.append(f"Current: ${market_index.get('current', 0):.2f}")
            change_pct = market_index.get("change_pct", 0)
            context_parts.append(f"Change: {change_pct:+.2f}%")
            context_parts.append(f"Volume: {market_index.get('volume', 0):,}")
            context_parts.append("")

        # Process each stock
        for symbol, prices in price_history.items():
            if not prices:
                continue

            # Find stock metadata
            stock_info = next(
                (s for s in stocks if s.get("symbol") == symbol),
                {"symbol": symbol, "name": symbol}
            )

            context_parts.append(f"## {symbol} - {stock_info.get('name', symbol)}")
            if stock_info.get("sector"):
                context_parts.append(f"Sector: {stock_info.get('sector')}")

            # Current price from most recent data
            current_price: float = 0.0
            if prices:
                latest = prices[0]  # Prices are sorted descending by date
                current_price = float(latest.get("close", 0))
                context_parts.append(f"Current Price: ${current_price:.2f}")
                context_parts.append(f"Volume: {latest.get('volume', 0):,}")

            # Price history summary
            context_parts.append(f"\n### Price History ({len(prices)} periods)")

            # Get recent prices (last 20, remembering they're sorted desc)
            recent_prices = prices[:20]

            # Calculate summary statistics
            closes = [p.get("close", 0) for p in recent_prices if p.get("close")]
            if closes:
                high_20 = max(p.get("high", 0) for p in recent_prices if p.get("high"))
                low_20 = min(p.get("low", float("inf")) for p in recent_prices if p.get("low"))
                avg_volume = sum(p.get("volume", 0) for p in recent_prices) / len(recent_prices)

                context_parts.append(f"20-Period High: ${high_20:.2f}")
                context_parts.append(f"20-Period Low: ${low_20:.2f}")
                context_parts.append(f"Average Volume: {avg_volume:,.0f}")

            # Recent OHLCV data (last 5 periods)
            context_parts.append("\nRecent OHLCV (last 5 periods):")
            for p in recent_prices[:5]:
                date_str = _format_date(p.get("date"))
                context_parts.append(
                    f"  {date_str}: O=${p.get('open', 0):.2f} "
                    f"H=${p.get('high', 0):.2f} L=${p.get('low', 0):.2f} "
                    f"C=${p.get('close', 0):.2f} V={p.get('volume', 0):,}"
                )

            # Technical indicators for this symbol
            indicators = technical_indicators.get(symbol, {})
            if indicators:
                context_parts.append("\n### Technical Indicators")

                for indicator_type, ind_data in indicators.items():
                    if isinstance(ind_data, dict):
                        value = ind_data.get("value")
                        metadata = ind_data.get("metadata", {})

                        if value is not None:
                            # Format based on indicator type
                            if indicator_type.lower() == "rsi":
                                rsi_signal = _interpret_rsi(value)
                                context_parts.append(f"RSI(14): {value:.2f} - {rsi_signal}")
                            elif indicator_type.lower() == "macd":
                                if metadata:
                                    signal_line = metadata.get("signal_line", 0)
                                    histogram = metadata.get("histogram", 0)
                                    macd_signal = "Bullish" if histogram > 0 else "Bearish"
                                    context_parts.append(
                                        f"MACD: Line={value:.4f}, Signal={signal_line:.4f}, "
                                        f"Histogram={histogram:.4f} ({macd_signal})"
                                    )
                                else:
                                    context_parts.append(f"MACD: {value:.4f}")
                            elif "sma" in indicator_type.lower() or "ema" in indicator_type.lower():
                                context_parts.append(f"{indicator_type.upper()}: ${value:.2f}")
                            elif indicator_type.lower() == "atr":
                                if current_price and current_price > 0:
                                    atr_pct = (value / current_price) * 100
                                    context_parts.append(f"ATR(14): ${value:.2f} ({atr_pct:.2f}% of price)")
                                else:
                                    context_parts.append(f"ATR(14): ${value:.2f}")
                            elif indicator_type.lower() == "bollinger_bands":
                                if metadata:
                                    upper = metadata.get("upper", 0)
                                    lower = metadata.get("lower", 0)
                                    middle = value
                                    if middle > 0:
                                        bb_width = ((upper - lower) / middle) * 100
                                        context_parts.append(
                                            f"Bollinger Bands: Upper=${upper:.2f}, "
                                            f"Middle=${middle:.2f}, Lower=${lower:.2f} (Width: {bb_width:.1f}%)"
                                        )
                            else:
                                context_parts.append(f"{indicator_type}: {value:.4f}")

            context_parts.append("")  # Blank line between stocks

    # Fall back to old format handling if no new-style data
    elif market_data.get("symbol") or market_data.get("prices"):
        # Legacy single-stock format
        symbol = market_data.get("symbol", "UNKNOWN")
        context_parts.append(f"## Stock: {symbol}")

        legacy_current_price = market_data.get("current_price")
        if legacy_current_price is not None:
            context_parts.append(f"Current Price: ${float(legacy_current_price):.2f}")

        prices = market_data.get("prices", [])
        if prices:
            context_parts.append(f"\n### Price History ({len(prices)} periods)")

            recent_prices = prices[-20:] if len(prices) > 20 else prices

            closes = [p.get("close", 0) for p in recent_prices if p.get("close")]
            if closes:
                high_20 = max(p.get("high", 0) for p in recent_prices if p.get("high"))
                low_20 = min(p.get("low", float("inf")) for p in recent_prices if p.get("low"))
                avg_volume = sum(p.get("volume", 0) for p in recent_prices) / len(recent_prices)

                context_parts.append(f"20-Period High: ${high_20:.2f}")
                context_parts.append(f"20-Period Low: ${low_20:.2f}")
                context_parts.append(f"Average Volume: {avg_volume:,.0f}")

            context_parts.append("\nRecent OHLCV (last 5 periods):")
            for p in recent_prices[-5:]:
                date_str = _format_date(p.get("date"))
                context_parts.append(
                    f"  {date_str}: O=${p.get('open', 0):.2f} "
                    f"H=${p.get('high', 0):.2f} L=${p.get('low', 0):.2f} "
                    f"C=${p.get('close', 0):.2f} V={p.get('volume', 0):,}"
                )

        indicators = market_data.get("indicators", {})
        if indicators:
            context_parts.append("\n### Technical Indicators")

            rsi = indicators.get("rsi")
            if rsi is not None:
                rsi_signal = _interpret_rsi(rsi)
                context_parts.append(f"RSI(14): {rsi:.2f} - {rsi_signal}")

            macd = indicators.get("macd", {})
            if macd:
                macd_line = macd.get("macd_line")
                signal_line = macd.get("signal_line")
                histogram = macd.get("histogram")
                if all(v is not None for v in [macd_line, signal_line, histogram]):
                    macd_signal = "Bullish" if histogram > 0 else "Bearish"
                    context_parts.append(
                        f"MACD: Line={macd_line:.4f}, Signal={signal_line:.4f}, "
                        f"Histogram={histogram:.4f} ({macd_signal})"
                    )

            bb = indicators.get("bollinger_bands", {})
            if bb:
                upper = bb.get("upper")
                middle = bb.get("middle")
                lower = bb.get("lower")
                if all(v is not None for v in [upper, middle, lower]):
                    bb_width = ((upper - lower) / middle) * 100 if middle else 0
                    context_parts.append(
                        f"Bollinger Bands: Upper=${upper:.2f}, "
                        f"Middle=${middle:.2f}, Lower=${lower:.2f} (Width: {bb_width:.1f}%)"
                    )

            sma_20 = indicators.get("sma_20")
            sma_50 = indicators.get("sma_50")
            sma_200 = indicators.get("sma_200")

            ma_parts = []
            if sma_20 is not None:
                ma_parts.append(f"SMA(20)=${sma_20:.2f}")
            if sma_50 is not None:
                ma_parts.append(f"SMA(50)=${sma_50:.2f}")
            if sma_200 is not None:
                ma_parts.append(f"SMA(200)=${sma_200:.2f}")

            if ma_parts:
                context_parts.append(f"Moving Averages: {', '.join(ma_parts)}")

            atr = indicators.get("atr")
            if atr is not None and legacy_current_price:
                atr_pct = (atr / float(legacy_current_price)) * 100
                context_parts.append(f"ATR(14): ${atr:.2f} ({atr_pct:.2f}% of price)")

            stochastic = indicators.get("stochastic", {})
            if stochastic:
                k = stochastic.get("k")
                d = stochastic.get("d")
                if k is not None and d is not None:
                    stoch_signal = _interpret_stochastic(k, d)
                    context_parts.append(f"Stochastic: %K={k:.2f}, %D={d:.2f} - {stoch_signal}")

    else:
        context_parts.append("No price data available for technical analysis.")

    # Add rich technical analysis if available
    rich_ta = market_data.get("rich_technical")
    if rich_ta:
        formatted_ta = _format_rich_ta_section(rich_ta)
        if formatted_ta:
            context_parts.append("")
            context_parts.append(formatted_ta)

    # Add fundamental data if available (for valuation context)
    fundamentals = market_data.get("fundamentals")
    if fundamentals:
        from analysis.context_builder import format_fundamental_context
        fundamental_text = format_fundamental_context(fundamentals)
        if fundamental_text:
            context_parts.append("")
            context_parts.append(fundamental_text)

    return "\n".join(context_parts)


def parse_technical_response(response: str) -> TechnicalAnalysisResult:
    """Parse the technical analyst's response into structured data.

    Extracts the JSON from the agent's response and converts it into a
    TechnicalAnalysisResult object.

    Args:
        response: Raw response string from the technical analyst agent.

    Returns:
        TechnicalAnalysisResult object with parsed data.

    Raises:
        ValueError: If the response cannot be parsed.
    """
    # Try to extract JSON from the response
    json_data = _extract_json(response)

    if json_data is None:
        logger.warning("Could not extract JSON from technical analyst response")
        # Return a minimal result with the raw response as an observation
        return TechnicalAnalysisResult(
            analyst="technical",
            key_observations=[f"Raw response: {response[:500]}..."],
            confidence=0.0,
        )

    # Parse the JSON into our dataclass
    try:
        return TechnicalAnalysisResult.from_dict(json_data)
    except (KeyError, TypeError, ValueError) as e:
        logger.error(f"Error parsing technical response: {e}")
        raise ValueError(f"Failed to parse technical analyst response: {e}") from e


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
        potential_json = text[start_idx:end_idx + 1]
        try:
            return json.loads(potential_json)
        except json.JSONDecodeError:
            pass

    return None


def _format_rich_ta_section(rich_ta: dict[str, Any]) -> str:
    """Format rich technical analysis data for inclusion in analyst context.

    Converts the per-symbol rich TA dict into a human-readable markdown block.
    Returns an empty string when *rich_ta* is empty.

    Args:
        rich_ta: Dict mapping symbol -> rich TA data dict (as produced by
            ``MarketContextBuilder._get_rich_technical``).  Each value
            contains trend, momentum, volatility, volume dicts and a
            signal_summary with composite_score, rating, confidence,
            breakdown, and key_levels.

    Returns:
        Formatted markdown string, or empty string if no data.
    """
    if not rich_ta:
        return ""

    lines: list[str] = ["## Rich Technical Analysis", ""]

    for symbol, data in sorted(rich_ta.items()):
        summary = data.get("signal_summary", {})
        score = summary.get("composite_score", 0.0)
        rating = summary.get("rating", "N/A")
        confidence = summary.get("confidence", 0.0)
        breakdown = summary.get("breakdown", {})
        key_levels = summary.get("key_levels", {})

        lines.append(
            f"### {symbol} -- Technical Score: {score:.2f} "
            f"({rating}, {confidence:.0%} confidence)"
        )
        lines.append("")

        # -- Trend -------------------------------------------------------------
        trend = data.get("trend", {})
        trend_score = breakdown.get("trend")
        trend_parts: list[str] = []
        for ma in ("sma_20", "sma_50", "sma_200"):
            val = trend.get(ma)
            if val is not None:
                price = data.get("latest_price", 0)
                direction = "above" if price and price > val else "below"
                trend_parts.append(f"Price {direction} {ma.upper()}({val:.1f})")
        macd_data = trend.get("macd", {})
        if isinstance(macd_data, dict) and macd_data.get("histogram") is not None:
            hist = macd_data["histogram"]
            polarity = "positive" if hist > 0 else "negative"
            trend_parts.append(f"MACD histogram {polarity} ({hist:.2f})")
        adx_data = trend.get("adx", {})
        if isinstance(adx_data, dict) and adx_data.get("adx") is not None:
            adx_val = adx_data["adx"]
            plus_di = adx_data.get("plus_di", 0)
            minus_di = adx_data.get("minus_di", 0)
            trend_label = "trending" if adx_val >= 25 else "ranging"
            di_label = "bullish" if (plus_di or 0) > (minus_di or 0) else "bearish"
            trend_parts.append(f"ADX at {adx_val:.1f} ({trend_label}), {di_label}")
        trend_score_str = f" (score: {trend_score:.1f})" if trend_score is not None else ""
        if trend_parts:
            lines.append(f"**Trend{trend_score_str}:** {'. '.join(trend_parts)}.")

        # -- Momentum ----------------------------------------------------------
        momentum = data.get("momentum", {})
        mom_score = breakdown.get("momentum")
        mom_parts: list[str] = []
        rsi = momentum.get("rsi_14")
        if rsi is not None:
            rsi_label = "overbought" if rsi > 70 else ("oversold" if rsi < 30 else "neutral")
            mom_parts.append(f"RSI at {rsi:.1f} ({rsi_label})")
        stoch = momentum.get("stochastic", {})
        if isinstance(stoch, dict) and stoch.get("k") is not None:
            k_val = stoch["k"]
            k_label = "overbought" if k_val > 80 else ("oversold" if k_val < 20 else "neutral")
            mom_parts.append(f"Stochastic %K={k_val:.1f} ({k_label})")
        cci = momentum.get("cci_20")
        if cci is not None:
            cci_label = "overbought" if cci > 100 else ("oversold" if cci < -100 else "neutral")
            mom_parts.append(f"CCI at {cci:.1f} ({cci_label})")
        mfi = momentum.get("mfi_14")
        if mfi is not None:
            mfi_label = "overbought" if mfi > 80 else ("oversold" if mfi < 20 else "neutral")
            mom_parts.append(f"MFI at {mfi:.1f} ({mfi_label})")
        mom_score_str = f" (score: {mom_score:.1f})" if mom_score is not None else ""
        if mom_parts:
            lines.append(f"**Momentum{mom_score_str}:** {'. '.join(mom_parts)}.")

        # -- Volatility --------------------------------------------------------
        vol = data.get("volatility", {})
        vol_parts: list[str] = []
        atr = vol.get("atr_14")
        if atr is not None:
            vol_parts.append(f"ATR={atr:.2f}")
        bb = vol.get("bollinger", {})
        if isinstance(bb, dict):
            pct_b = bb.get("percent_b")
            if pct_b is not None:
                bb_pos = "upper half" if pct_b > 0.5 else "lower half"
                vol_parts.append(f"Bollinger %B={pct_b:.2f} ({bb_pos})")
            bw = bb.get("bandwidth")
            if bw is not None:
                vol_parts.append(f"BB bandwidth={bw:.1f}")
        if vol_parts:
            lines.append(f"**Volatility:** {'. '.join(vol_parts)}.")

        # -- Volume ------------------------------------------------------------
        volume = data.get("volume", {})
        vol_ratio = volume.get("volume_sma_ratio")
        obv = volume.get("obv")
        vol_line_parts: list[str] = []
        if vol_ratio is not None:
            if vol_ratio > 1.2:
                vol_desc = "above average"
            elif vol_ratio < 0.8:
                vol_desc = "below average"
            else:
                vol_desc = "near average"
            vol_line_parts.append(f"Volume/SMA ratio={vol_ratio:.2f} ({vol_desc})")
        if obv is not None:
            vol_line_parts.append(f"OBV={obv:,.0f}")
        if vol_line_parts:
            lines.append(f"**Volume:** {'. '.join(vol_line_parts)}.")

        # -- Key levels --------------------------------------------------------
        support = key_levels.get("support", [])
        resistance = key_levels.get("resistance", [])
        pivot = key_levels.get("pivot")
        level_parts: list[str] = []
        if support:
            level_parts.append(
                f"Support: {', '.join(f'{v:.1f}' for v in support)}"
            )
        if resistance:
            level_parts.append(
                f"Resistance: {', '.join(f'{v:.1f}' for v in resistance)}"
            )
        if pivot is not None:
            level_parts.append(f"Pivot: {pivot:.1f} (SMA50)")
        if level_parts:
            lines.append(f"**Key Levels:** {'. '.join(level_parts)}.")

        lines.append("")

    return "\n".join(lines)


def _format_date(date_value: Any) -> str:
    """Format a date value to string.

    Args:
        date_value: Date as string, datetime, or date object.

    Returns:
        Formatted date string (YYYY-MM-DD).
    """
    if isinstance(date_value, str):
        return date_value[:10]  # Truncate to YYYY-MM-DD
    elif isinstance(date_value, datetime):
        return date_value.strftime("%Y-%m-%d")
    elif isinstance(date_value, date):
        return date_value.isoformat()
    else:
        return "N/A"


def _interpret_rsi(rsi: float) -> str:
    """Interpret RSI value into a signal description.

    Args:
        rsi: RSI value (0-100).

    Returns:
        Signal interpretation string.
    """
    if rsi >= 80:
        return "Extremely Overbought"
    elif rsi >= 70:
        return "Overbought"
    elif rsi <= 20:
        return "Extremely Oversold"
    elif rsi <= 30:
        return "Oversold"
    elif rsi >= 60:
        return "Bullish Momentum"
    elif rsi <= 40:
        return "Bearish Momentum"
    else:
        return "Neutral"


def _interpret_stochastic(k: float, d: float) -> str:
    """Interpret Stochastic oscillator values.

    Args:
        k: %K value (0-100).
        d: %D value (0-100).

    Returns:
        Signal interpretation string.
    """
    if k >= 80 and d >= 80:
        return "Overbought"
    elif k <= 20 and d <= 20:
        return "Oversold"
    elif k > d:
        return "Bullish Crossover" if k - d > 5 else "Bullish"
    elif k < d:
        return "Bearish Crossover" if d - k > 5 else "Bearish"
    else:
        return "Neutral"


def validate_technical_finding(finding: dict[str, Any]) -> list[str]:
    """Validate a technical finding dictionary for required fields.

    Args:
        finding: Dictionary representing a technical finding.

    Returns:
        List of validation error messages (empty if valid).
    """
    errors: list[str] = []

    # Required fields
    if not finding.get("symbol"):
        errors.append("Missing required field: symbol")

    if not finding.get("signal"):
        errors.append("Missing required field: signal")

    if not finding.get("description"):
        errors.append("Missing required field: description")

    # Validate confidence range
    confidence = finding.get("confidence")
    if confidence is not None:
        if not isinstance(confidence, (int, float)):
            errors.append("confidence must be a number")
        elif confidence < 0 or confidence > 1:
            errors.append("confidence must be between 0 and 1")

    # Validate action_bias
    valid_biases = {"BUY", "SELL", "HOLD", "NEUTRAL"}
    action_bias = finding.get("action_bias", "HOLD")
    if action_bias not in valid_biases:
        errors.append(f"action_bias must be one of: {valid_biases}")

    # Validate timeframe
    valid_timeframes = {"intraday", "daily", "weekly", "monthly"}
    timeframe = finding.get("timeframe", "daily")
    if timeframe not in valid_timeframes:
        errors.append(f"timeframe must be one of: {valid_timeframes}")

    return errors


def aggregate_findings(
    findings: list[TechnicalFinding],
) -> dict[str, Any]:
    """Aggregate multiple technical findings into a summary.

    Args:
        findings: List of TechnicalFinding objects.

    Returns:
        Aggregated summary dictionary.
    """
    if not findings:
        return {
            "total_findings": 0,
            "bullish_count": 0,
            "bearish_count": 0,
            "neutral_count": 0,
            "overall_bias": "NEUTRAL",
            "average_confidence": 0.0,
            "symbols_analyzed": [],
        }

    bullish_count = 0
    bearish_count = 0
    neutral_count = 0
    total_confidence = 0.0
    symbols: set[str] = set()

    bullish_signals = {
        "bullish_divergence", "golden_cross", "oversold", "breakout",
        "support_test", "trend_continuation", "bollinger_breakout",
    }

    bearish_signals = {
        "bearish_divergence", "death_cross", "overbought", "breakdown",
        "resistance_test", "trend_reversal",
    }

    for finding in findings:
        symbols.add(finding.symbol)
        total_confidence += finding.confidence

        signal_lower = finding.signal.lower()
        if signal_lower in bullish_signals or finding.action_bias == "BUY":
            bullish_count += 1
        elif signal_lower in bearish_signals or finding.action_bias == "SELL":
            bearish_count += 1
        else:
            neutral_count += 1

    # Determine overall bias
    if bullish_count > bearish_count * 1.5:
        overall_bias = "BUY"
    elif bearish_count > bullish_count * 1.5:
        overall_bias = "SELL"
    elif bullish_count > bearish_count:
        overall_bias = "HOLD"  # Slight bullish lean
    elif bearish_count > bullish_count:
        overall_bias = "HOLD"  # Slight bearish lean
    else:
        overall_bias = "NEUTRAL"

    return {
        "total_findings": len(findings),
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "neutral_count": neutral_count,
        "overall_bias": overall_bias,
        "average_confidence": total_confidence / len(findings),
        "symbols_analyzed": sorted(symbols),
    }
