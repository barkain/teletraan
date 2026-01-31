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

    Takes raw market data and formats it into a structured string that the
    technical analyst agent can easily parse and analyze.

    Args:
        market_data: Dictionary containing market data with potential keys:
            - symbol: Stock symbol
            - prices: List of OHLCV dictionaries
            - indicators: Pre-calculated technical indicators
            - current_price: Latest price
            - volume: Volume data
            - timeframe: Data timeframe

    Returns:
        Formatted string context for the technical analyst prompt.
    """
    context_parts: list[str] = []

    # Symbol and basic info
    symbol = market_data.get("symbol", "UNKNOWN")
    context_parts.append(f"## Stock: {symbol}")

    # Current price information
    current_price = market_data.get("current_price")
    if current_price:
        context_parts.append(f"Current Price: ${current_price:.2f}")

    # Price history
    prices = market_data.get("prices", [])
    if prices:
        context_parts.append(f"\n### Price History ({len(prices)} periods)")

        # Get recent prices (last 20)
        recent_prices = prices[-20:] if len(prices) > 20 else prices

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
        for p in recent_prices[-5:]:
            date_str = _format_date(p.get("date"))
            context_parts.append(
                f"  {date_str}: O=${p.get('open', 0):.2f} "
                f"H=${p.get('high', 0):.2f} L=${p.get('low', 0):.2f} "
                f"C=${p.get('close', 0):.2f} V={p.get('volume', 0):,}"
            )

    # Pre-calculated indicators
    indicators = market_data.get("indicators", {})
    if indicators:
        context_parts.append("\n### Technical Indicators")

        # RSI
        rsi = indicators.get("rsi")
        if rsi is not None:
            rsi_signal = _interpret_rsi(rsi)
            context_parts.append(f"RSI(14): {rsi:.2f} - {rsi_signal}")

        # MACD
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

        # Bollinger Bands
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

        # Moving Averages
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

        # ATR (volatility)
        atr = indicators.get("atr")
        if atr is not None and current_price:
            atr_pct = (atr / current_price) * 100
            context_parts.append(f"ATR(14): ${atr:.2f} ({atr_pct:.2f}% of price)")

        # Stochastic
        stochastic = indicators.get("stochastic", {})
        if stochastic:
            k = stochastic.get("k")
            d = stochastic.get("d")
            if k is not None and d is not None:
                stoch_signal = _interpret_stochastic(k, d)
                context_parts.append(f"Stochastic: %K={k:.2f}, %D={d:.2f} - {stoch_signal}")

    # Support and Resistance levels
    sr_levels = market_data.get("support_resistance", {})
    if sr_levels:
        context_parts.append("\n### Support/Resistance Levels")

        support_levels = sr_levels.get("support", [])
        if support_levels:
            levels_str = ", ".join(f"${s['level']:.2f}" for s in support_levels[:3])
            context_parts.append(f"Support: {levels_str}")

        resistance_levels = sr_levels.get("resistance", [])
        if resistance_levels:
            levels_str = ", ".join(f"${r['level']:.2f}" for r in resistance_levels[:3])
            context_parts.append(f"Resistance: {levels_str}")

    # Detected patterns
    patterns = market_data.get("patterns", [])
    if patterns:
        context_parts.append("\n### Detected Patterns")
        for pattern in patterns[:5]:  # Limit to 5 patterns
            p_type = pattern.get("pattern_type", "unknown")
            confidence = pattern.get("confidence", 0)
            description = pattern.get("description", "")
            context_parts.append(f"- {p_type} (Confidence: {confidence:.0%}): {description}")

    # Volume analysis
    volume_data = market_data.get("volume_analysis", {})
    if volume_data:
        context_parts.append("\n### Volume Analysis")
        avg_vol = volume_data.get("average_volume")
        current_vol = volume_data.get("current_volume")
        if avg_vol and current_vol:
            vol_ratio = current_vol / avg_vol
            vol_signal = "Above average" if vol_ratio > 1.2 else "Below average" if vol_ratio < 0.8 else "Normal"
            context_parts.append(f"Current Volume: {current_vol:,} ({vol_ratio:.1f}x average) - {vol_signal}")

    # Trend information
    trend = market_data.get("trend", {})
    if trend:
        context_parts.append("\n### Trend Analysis")
        trend_dir = trend.get("direction", "unknown")
        trend_strength = trend.get("strength", 0)
        context_parts.append(f"Trend: {trend_dir.upper()} (Strength: {trend_strength:.0%})")

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
