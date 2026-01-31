"""Technical analysis indicators for market data."""
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass
import numpy as np


@dataclass
class IndicatorResult:
    """Result of a technical indicator calculation."""
    name: str
    value: float
    signal: str  # "bullish", "bearish", "neutral"
    strength: float  # 0.0 to 1.0


class TechnicalIndicators:
    """Calculate technical analysis indicators."""

    @staticmethod
    def sma(prices: List[float], period: int) -> List[Optional[float]]:
        """Simple Moving Average."""
        if len(prices) < period:
            return [None] * len(prices)

        result: List[Optional[float]] = [None] * (period - 1)
        for i in range(period - 1, len(prices)):
            result.append(sum(prices[i - period + 1:i + 1]) / period)
        return result

    @staticmethod
    def ema(prices: List[float], period: int) -> List[Optional[float]]:
        """Exponential Moving Average."""
        if len(prices) < period:
            return [None] * len(prices)

        multiplier = 2 / (period + 1)
        result: List[Optional[float]] = [None] * (period - 1)

        # First EMA value is the SMA
        first_ema = sum(prices[:period]) / period
        result.append(first_ema)

        # Calculate remaining EMA values
        for i in range(period, len(prices)):
            prev_ema = result[-1]
            if prev_ema is not None:
                current_ema = (prices[i] - prev_ema) * multiplier + prev_ema
                result.append(current_ema)
            else:
                result.append(None)

        return result

    @staticmethod
    def rsi(prices: List[float], period: int = 14) -> List[Optional[float]]:
        """Relative Strength Index (0-100)."""
        if len(prices) < period + 1:
            return [None] * len(prices)

        # Calculate price changes
        changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

        gains = [max(0, c) for c in changes]
        losses = [abs(min(0, c)) for c in changes]

        result: List[Optional[float]] = [None] * period

        # First RSI: simple average of gains and losses
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100 - (100 / (1 + rs)))

        # Subsequent RSI values use smoothed averages
        for i in range(period, len(changes)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

            if avg_loss == 0:
                result.append(100.0)
            else:
                rs = avg_gain / avg_loss
                result.append(100 - (100 / (1 + rs)))

        return result

    @staticmethod
    def macd(
        prices: List[float],
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
        """MACD: returns (macd_line, signal_line, histogram)."""
        if len(prices) < slow:
            none_list: List[Optional[float]] = [None] * len(prices)
            return (none_list, none_list.copy(), none_list.copy())

        # Calculate EMAs
        fast_ema = TechnicalIndicators.ema(prices, fast)
        slow_ema = TechnicalIndicators.ema(prices, slow)

        # MACD line = fast EMA - slow EMA
        macd_line: List[Optional[float]] = []
        for f, s in zip(fast_ema, slow_ema):
            if f is not None and s is not None:
                macd_line.append(f - s)
            else:
                macd_line.append(None)

        # Signal line = EMA of MACD line
        macd_values = [v for v in macd_line if v is not None]
        if len(macd_values) < signal:
            signal_line: List[Optional[float]] = [None] * len(prices)
            histogram: List[Optional[float]] = [None] * len(prices)
            return (macd_line, signal_line, histogram)

        # Calculate signal line EMA on valid MACD values
        signal_ema = TechnicalIndicators.ema(macd_values, signal)

        # Map signal EMA back to full length
        signal_line = [None] * (len(prices) - len(signal_ema))
        signal_line.extend(signal_ema)

        # Histogram = MACD line - Signal line
        histogram = []
        for m, s in zip(macd_line, signal_line):
            if m is not None and s is not None:
                histogram.append(m - s)
            else:
                histogram.append(None)

        return (macd_line, signal_line, histogram)

    @staticmethod
    def bollinger_bands(
        prices: List[float],
        period: int = 20,
        std_dev: float = 2.0
    ) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
        """Bollinger Bands: returns (upper, middle, lower)."""
        if len(prices) < period:
            none_list: List[Optional[float]] = [None] * len(prices)
            return (none_list, none_list.copy(), none_list.copy())

        middle = TechnicalIndicators.sma(prices, period)

        upper: List[Optional[float]] = [None] * (period - 1)
        lower: List[Optional[float]] = [None] * (period - 1)

        for i in range(period - 1, len(prices)):
            window = prices[i - period + 1:i + 1]
            std = np.std(window, ddof=0)
            mid = middle[i]
            if mid is not None:
                upper.append(mid + std_dev * std)
                lower.append(mid - std_dev * std)
            else:
                upper.append(None)
                lower.append(None)

        return (upper, middle, lower)

    @staticmethod
    def atr(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14
    ) -> List[Optional[float]]:
        """Average True Range - volatility indicator."""
        if len(highs) < 2 or len(highs) < period:
            return [None] * len(highs)

        # Calculate True Range
        true_ranges: List[float] = [highs[0] - lows[0]]  # First TR is just high - low

        for i in range(1, len(highs)):
            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i - 1])
            low_close = abs(lows[i] - closes[i - 1])
            true_ranges.append(max(high_low, high_close, low_close))

        result: List[Optional[float]] = [None] * (period - 1)

        # First ATR is simple average
        first_atr = sum(true_ranges[:period]) / period
        result.append(first_atr)

        # Subsequent ATRs use smoothed average
        for i in range(period, len(true_ranges)):
            prev_atr = result[-1]
            if prev_atr is not None:
                current_atr = (prev_atr * (period - 1) + true_ranges[i]) / period
                result.append(current_atr)
            else:
                result.append(None)

        return result

    @staticmethod
    def stochastic(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        k_period: int = 14,
        d_period: int = 3
    ) -> Tuple[List[Optional[float]], List[Optional[float]]]:
        """Stochastic Oscillator: returns (%K, %D)."""
        if len(closes) < k_period:
            none_list: List[Optional[float]] = [None] * len(closes)
            return (none_list, none_list.copy())

        k_values: List[Optional[float]] = [None] * (k_period - 1)

        # Calculate %K
        for i in range(k_period - 1, len(closes)):
            window_highs = highs[i - k_period + 1:i + 1]
            window_lows = lows[i - k_period + 1:i + 1]

            highest_high = max(window_highs)
            lowest_low = min(window_lows)

            if highest_high == lowest_low:
                k_values.append(50.0)  # Neutral if no range
            else:
                k = ((closes[i] - lowest_low) / (highest_high - lowest_low)) * 100
                k_values.append(k)

        # Calculate %D (SMA of %K)
        valid_k = [v for v in k_values if v is not None]
        if len(valid_k) < d_period:
            d_values: List[Optional[float]] = [None] * len(closes)
            return (k_values, d_values)

        d_sma = TechnicalIndicators.sma(valid_k, d_period)

        # Map %D back to full length
        d_values = [None] * (len(closes) - len(d_sma))
        d_values.extend(d_sma)

        return (k_values, d_values)


class IndicatorAnalyzer:
    """Analyze and interpret technical indicators."""

    def __init__(self) -> None:
        self.indicators = TechnicalIndicators()

    async def analyze_stock(
        self,
        prices: List[Dict[str, Any]]  # OHLCV data
    ) -> Dict[str, IndicatorResult]:
        """Run all indicators on stock data."""
        if not prices:
            return {}

        # Extract price arrays
        closes = [p["close"] for p in prices]
        highs = [p["high"] for p in prices]
        lows = [p["low"] for p in prices]

        results: Dict[str, IndicatorResult] = {}

        # RSI
        rsi_values = self.indicators.rsi(closes)
        if rsi_values and rsi_values[-1] is not None:
            rsi_val = rsi_values[-1]
            rsi_signal, rsi_strength = self._interpret_rsi(rsi_val)
            results["rsi"] = IndicatorResult(
                name="RSI",
                value=rsi_val,
                signal=rsi_signal,
                strength=rsi_strength
            )

        # MACD
        macd_line, signal_line, histogram = self.indicators.macd(closes)
        if histogram and histogram[-1] is not None:
            hist_val = histogram[-1]
            macd_signal, macd_strength = self._interpret_macd(
                macd_line[-1], signal_line[-1], hist_val
            )
            results["macd"] = IndicatorResult(
                name="MACD",
                value=hist_val,
                signal=macd_signal,
                strength=macd_strength
            )

        # Bollinger Bands
        upper, middle, lower = self.indicators.bollinger_bands(closes)
        if upper[-1] is not None and lower[-1] is not None:
            bb_signal, bb_strength = self._interpret_bollinger(
                closes[-1], upper[-1], middle[-1], lower[-1]
            )
            bb_width = (upper[-1] - lower[-1]) / middle[-1] if middle[-1] else 0
            results["bollinger"] = IndicatorResult(
                name="Bollinger Bands",
                value=bb_width,
                signal=bb_signal,
                strength=bb_strength
            )

        # Stochastic
        k_values, d_values = self.indicators.stochastic(highs, lows, closes)
        if k_values[-1] is not None and d_values[-1] is not None:
            stoch_signal, stoch_strength = self._interpret_stochastic(
                k_values[-1], d_values[-1]
            )
            results["stochastic"] = IndicatorResult(
                name="Stochastic",
                value=k_values[-1],
                signal=stoch_signal,
                strength=stoch_strength
            )

        # ATR (volatility)
        atr_values = self.indicators.atr(highs, lows, closes)
        if atr_values[-1] is not None:
            atr_pct = (atr_values[-1] / closes[-1]) * 100 if closes[-1] else 0
            results["atr"] = IndicatorResult(
                name="ATR",
                value=atr_values[-1],
                signal="neutral",
                strength=min(atr_pct / 5, 1.0)  # High ATR = high volatility
            )

        # Moving Averages
        sma_20 = self.indicators.sma(closes, 20)
        sma_50 = self.indicators.sma(closes, 50)
        if sma_20[-1] is not None:
            ma_signal = "bullish" if closes[-1] > sma_20[-1] else "bearish"
            ma_strength = abs(closes[-1] - sma_20[-1]) / sma_20[-1]
            results["sma_20"] = IndicatorResult(
                name="SMA 20",
                value=sma_20[-1],
                signal=ma_signal,
                strength=min(ma_strength, 1.0)
            )

        if sma_50[-1] is not None:
            ma_signal = "bullish" if closes[-1] > sma_50[-1] else "bearish"
            ma_strength = abs(closes[-1] - sma_50[-1]) / sma_50[-1]
            results["sma_50"] = IndicatorResult(
                name="SMA 50",
                value=sma_50[-1],
                signal=ma_signal,
                strength=min(ma_strength, 1.0)
            )

        return results

    def _interpret_rsi(self, rsi: float) -> Tuple[str, float]:
        """Interpret RSI value."""
        if rsi >= 70:
            return ("bearish", (rsi - 70) / 30)  # Overbought
        elif rsi <= 30:
            return ("bullish", (30 - rsi) / 30)  # Oversold
        else:
            return ("neutral", 0.0)

    def _interpret_macd(
        self,
        macd: Optional[float],
        signal: Optional[float],
        histogram: float
    ) -> Tuple[str, float]:
        """Interpret MACD values."""
        if macd is None or signal is None:
            return ("neutral", 0.0)

        if histogram > 0:
            return ("bullish", min(abs(histogram) / abs(macd) if macd else 0, 1.0))
        elif histogram < 0:
            return ("bearish", min(abs(histogram) / abs(macd) if macd else 0, 1.0))
        return ("neutral", 0.0)

    def _interpret_bollinger(
        self,
        price: float,
        upper: float,
        middle: float,
        lower: float
    ) -> Tuple[str, float]:
        """Interpret Bollinger Bands position."""
        band_width = upper - lower
        if band_width == 0:
            return ("neutral", 0.0)

        position = (price - lower) / band_width

        if position >= 0.9:
            return ("bearish", (position - 0.5) * 2)  # Near upper band
        elif position <= 0.1:
            return ("bullish", (0.5 - position) * 2)  # Near lower band
        return ("neutral", abs(0.5 - position))

    def _interpret_stochastic(self, k: float, d: float) -> Tuple[str, float]:
        """Interpret Stochastic Oscillator."""
        if k >= 80 and d >= 80:
            return ("bearish", (k - 80) / 20)  # Overbought
        elif k <= 20 and d <= 20:
            return ("bullish", (20 - k) / 20)  # Oversold
        elif k > d:
            return ("bullish", abs(k - d) / 100)
        elif k < d:
            return ("bearish", abs(d - k) / 100)
        return ("neutral", 0.0)

    async def get_signals(
        self,
        indicator_results: Dict[str, IndicatorResult]
    ) -> Dict[str, Any]:
        """Aggregate signals into overall assessment."""
        if not indicator_results:
            return {
                "overall_signal": "neutral",
                "confidence": 0.0,
                "bullish_count": 0,
                "bearish_count": 0,
                "neutral_count": 0,
                "details": []
            }

        bullish_count = 0
        bearish_count = 0
        neutral_count = 0
        total_strength = 0.0

        details = []

        for name, result in indicator_results.items():
            details.append({
                "indicator": result.name,
                "value": round(result.value, 4),
                "signal": result.signal,
                "strength": round(result.strength, 4)
            })

            if result.signal == "bullish":
                bullish_count += 1
                total_strength += result.strength
            elif result.signal == "bearish":
                bearish_count += 1
                total_strength += result.strength
            else:
                neutral_count += 1

        # Determine overall signal
        if bullish_count > bearish_count:
            overall_signal = "bullish"
        elif bearish_count > bullish_count:
            overall_signal = "bearish"
        else:
            overall_signal = "neutral"

        # Calculate confidence
        total_indicators = len(indicator_results)
        if total_indicators > 0:
            signal_agreement = max(bullish_count, bearish_count) / total_indicators
            avg_strength = total_strength / total_indicators
            confidence = (signal_agreement + avg_strength) / 2
        else:
            confidence = 0.0

        return {
            "overall_signal": overall_signal,
            "confidence": round(confidence, 4),
            "bullish_count": bullish_count,
            "bearish_count": bearish_count,
            "neutral_count": neutral_count,
            "details": details
        }

    async def detect_crossovers(
        self,
        prices: List[float]
    ) -> List[Dict[str, Any]]:
        """Detect MA crossovers (golden cross, death cross)."""
        crossovers: List[Dict[str, Any]] = []

        if len(prices) < 200:
            return crossovers

        sma_50 = self.indicators.sma(prices, 50)
        sma_200 = self.indicators.sma(prices, 200)

        # Look for crossovers in the last 20 periods
        for i in range(max(200, len(prices) - 20), len(prices)):
            curr_50 = sma_50[i]
            curr_200 = sma_200[i]
            prev_50 = sma_50[i - 1]
            prev_200 = sma_200[i - 1]

            if all(v is not None for v in [curr_50, curr_200, prev_50, prev_200]):
                # Golden Cross: 50 SMA crosses above 200 SMA
                if prev_50 <= prev_200 and curr_50 > curr_200:
                    crossovers.append({
                        "type": "golden_cross",
                        "index": i,
                        "price": prices[i],
                        "sma_50": curr_50,
                        "sma_200": curr_200,
                        "signal": "bullish",
                        "description": "50-day SMA crossed above 200-day SMA"
                    })

                # Death Cross: 50 SMA crosses below 200 SMA
                elif prev_50 >= prev_200 and curr_50 < curr_200:
                    crossovers.append({
                        "type": "death_cross",
                        "index": i,
                        "price": prices[i],
                        "sma_50": curr_50,
                        "sma_200": curr_200,
                        "signal": "bearish",
                        "description": "50-day SMA crossed below 200-day SMA"
                    })

        return crossovers


# Global instance
indicator_analyzer = IndicatorAnalyzer()
