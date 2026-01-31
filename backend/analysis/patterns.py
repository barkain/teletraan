"""Pattern detection engine for chart pattern recognition."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from datetime import date, datetime
from typing import Any

import numpy as np
from scipy import stats
from scipy.signal import argrelextrema


class PatternType(Enum):
    """Types of chart patterns."""
    # Trend patterns
    UPTREND = "uptrend"
    DOWNTREND = "downtrend"
    SIDEWAYS = "sideways"

    # Reversal patterns
    HEAD_AND_SHOULDERS = "head_and_shoulders"
    INVERSE_HEAD_AND_SHOULDERS = "inverse_head_and_shoulders"
    DOUBLE_TOP = "double_top"
    DOUBLE_BOTTOM = "double_bottom"
    TRIPLE_TOP = "triple_top"
    TRIPLE_BOTTOM = "triple_bottom"

    # Continuation patterns
    BULL_FLAG = "bull_flag"
    BEAR_FLAG = "bear_flag"
    ASCENDING_TRIANGLE = "ascending_triangle"
    DESCENDING_TRIANGLE = "descending_triangle"
    SYMMETRICAL_TRIANGLE = "symmetrical_triangle"
    WEDGE_RISING = "wedge_rising"
    WEDGE_FALLING = "wedge_falling"

    # Crossover signals
    GOLDEN_CROSS = "golden_cross"
    DEATH_CROSS = "death_cross"

    # Support/Resistance
    BREAKOUT = "breakout"
    BREAKDOWN = "breakdown"
    SUPPORT_TEST = "support_test"
    RESISTANCE_TEST = "resistance_test"
    SUPPORT_BOUNCE = "support_bounce"
    RESISTANCE_REJECTION = "resistance_rejection"

    # Candlestick patterns
    DOJI = "doji"
    HAMMER = "hammer"
    SHOOTING_STAR = "shooting_star"
    ENGULFING_BULLISH = "engulfing_bullish"
    ENGULFING_BEARISH = "engulfing_bearish"


@dataclass
class DetectedPattern:
    """A detected chart pattern."""
    pattern_type: PatternType
    symbol: str
    start_date: date
    end_date: date
    confidence: float  # 0.0 to 1.0
    price_target: float | None
    stop_loss: float | None
    description: str
    supporting_data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "pattern_type": self.pattern_type.value,
            "symbol": self.symbol,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "confidence": round(self.confidence, 4),
            "price_target": round(self.price_target, 2) if self.price_target else None,
            "stop_loss": round(self.stop_loss, 2) if self.stop_loss else None,
            "description": self.description,
            "supporting_data": self.supporting_data
        }


class PatternDetector:
    """Detect chart patterns in price data."""

    def __init__(self, min_confidence: float = 0.6):
        self.min_confidence = min_confidence

    def _extract_prices(
        self,
        prices: list[dict[str, Any]]
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[date]]:
        """Extract OHLC arrays from price data."""
        opens = np.array([p["open"] for p in prices])
        highs = np.array([p["high"] for p in prices])
        lows = np.array([p["low"] for p in prices])
        closes = np.array([p["close"] for p in prices])

        dates: list[date] = []
        for p in prices:
            d = p.get("date")
            if isinstance(d, str):
                dates.append(datetime.fromisoformat(d.replace("Z", "+00:00")).date())
            elif isinstance(d, datetime):
                dates.append(d.date())
            elif isinstance(d, date):
                dates.append(d)
            else:
                dates.append(date.today())

        return opens, highs, lows, closes, dates

    def _find_local_extrema(
        self,
        data: np.ndarray,
        order: int = 5
    ) -> tuple[np.ndarray, np.ndarray]:
        """Find local maxima and minima in data."""
        local_max_indices = argrelextrema(data, np.greater_equal, order=order)[0]
        local_min_indices = argrelextrema(data, np.less_equal, order=order)[0]
        return local_max_indices, local_min_indices

    def _calculate_slope(self, y_values: np.ndarray) -> float:
        """Calculate the slope of a series using linear regression."""
        x = np.arange(len(y_values))
        slope, _, _, _, _ = stats.linregress(x, y_values)
        return slope

    async def detect_trend(
        self,
        prices: list[dict[str, Any]],
        lookback: int = 20
    ) -> tuple[PatternType, float]:
        """
        Identify current trend direction using linear regression.

        Returns:
            Tuple of (PatternType, confidence score)
        """
        if len(prices) < lookback:
            return PatternType.SIDEWAYS, 0.5

        _, _, _, closes, _ = self._extract_prices(prices[-lookback:])

        # Calculate linear regression
        x = np.arange(len(closes))
        slope, intercept, r_value, p_value, std_err = stats.linregress(x, closes)

        # Normalize slope by price level
        avg_price = np.mean(closes)
        normalized_slope = (slope / avg_price) * 100  # Percentage change per period

        # R-squared as confidence
        r_squared = r_value ** 2

        # Determine trend based on slope and statistical significance
        if abs(normalized_slope) < 0.1:  # Less than 0.1% change per period
            return PatternType.SIDEWAYS, r_squared
        elif normalized_slope > 0 and p_value < 0.1:
            confidence = min(r_squared * (1 + normalized_slope / 2), 1.0)
            return PatternType.UPTREND, confidence
        elif normalized_slope < 0 and p_value < 0.1:
            confidence = min(r_squared * (1 + abs(normalized_slope) / 2), 1.0)
            return PatternType.DOWNTREND, confidence
        else:
            return PatternType.SIDEWAYS, r_squared * 0.5

    async def detect_support_resistance(
        self,
        prices: list[dict[str, Any]],
        tolerance: float = 0.02,
        min_touches: int = 2
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Find support and resistance levels using pivot point analysis.

        Args:
            prices: OHLCV price data
            tolerance: Percentage tolerance for grouping levels (2% default)
            min_touches: Minimum number of touches to confirm a level

        Returns:
            Dict with 'support' and 'resistance' lists containing level info
        """
        if len(prices) < 20:
            return {"support": [], "resistance": []}

        _, highs, lows, closes, dates = self._extract_prices(prices)

        # Find local extrema with different orders for robustness
        all_max_indices: set[int] = set()
        all_min_indices: set[int] = set()

        for order in [3, 5, 7]:
            if len(closes) > order * 2:
                max_idx, min_idx = self._find_local_extrema(closes, order=order)
                all_max_indices.update(max_idx)
                all_min_indices.update(min_idx)

        # Get pivot prices
        resistance_prices = [(i, highs[i]) for i in all_max_indices]
        support_prices = [(i, lows[i]) for i in all_min_indices]

        def cluster_levels(
            price_points: list[tuple[int, float]],
            tol: float
        ) -> list[dict[str, Any]]:
            """Cluster nearby price levels and count touches."""
            if not price_points:
                return []

            # Sort by price
            sorted_points = sorted(price_points, key=lambda x: x[1])

            clusters: list[dict[str, Any]] = []
            current_cluster: list[tuple[int, float]] = [sorted_points[0]]

            for idx, price in sorted_points[1:]:
                cluster_avg = np.mean([p[1] for p in current_cluster])
                if abs(price - cluster_avg) / cluster_avg <= tol:
                    current_cluster.append((idx, price))
                else:
                    if len(current_cluster) >= min_touches:
                        avg_price = np.mean([p[1] for p in current_cluster])
                        clusters.append({
                            "level": float(avg_price),
                            "touches": len(current_cluster),
                            "indices": [p[0] for p in current_cluster],
                            "strength": min(len(current_cluster) / 5.0, 1.0)
                        })
                    current_cluster = [(idx, price)]

            # Don't forget the last cluster
            if len(current_cluster) >= min_touches:
                avg_price = np.mean([p[1] for p in current_cluster])
                clusters.append({
                    "level": float(avg_price),
                    "touches": len(current_cluster),
                    "indices": [p[0] for p in current_cluster],
                    "strength": min(len(current_cluster) / 5.0, 1.0)
                })

            return sorted(clusters, key=lambda x: x["strength"], reverse=True)

        resistance_levels = cluster_levels(resistance_prices, tolerance)
        support_levels = cluster_levels(support_prices, tolerance)

        return {
            "support": support_levels[:5],  # Top 5 levels
            "resistance": resistance_levels[:5]
        }

    async def detect_double_top(
        self,
        prices: list[dict[str, Any]],
        symbol: str = "UNKNOWN"
    ) -> DetectedPattern | None:
        """
        Detect double top reversal pattern.

        A double top forms when price makes two roughly equal highs with a
        moderate decline between them, signaling potential bearish reversal.
        """
        if len(prices) < 30:
            return None

        _, highs, lows, closes, dates = self._extract_prices(prices)

        # Find recent local maxima
        max_indices, _ = self._find_local_extrema(highs, order=5)

        if len(max_indices) < 2:
            return None

        # Get the two most recent significant peaks
        recent_max = sorted(max_indices[-10:], key=lambda i: highs[i], reverse=True)

        if len(recent_max) < 2:
            return None

        # Check the two highest peaks
        peak1_idx, peak2_idx = sorted(recent_max[:2])
        peak1_price = highs[peak1_idx]
        peak2_price = highs[peak2_idx]

        # Validate pattern criteria
        # 1. Peaks should be roughly equal (within 3%)
        price_diff = abs(peak1_price - peak2_price) / max(peak1_price, peak2_price)
        if price_diff > 0.03:
            return None

        # 2. There should be a valley between peaks (at least 3% below peaks)
        valley_slice = lows[peak1_idx:peak2_idx + 1]
        if len(valley_slice) < 3:
            return None

        valley_price = np.min(valley_slice)
        valley_idx = peak1_idx + np.argmin(valley_slice)

        peak_avg = (peak1_price + peak2_price) / 2
        valley_depth = (peak_avg - valley_price) / peak_avg

        if valley_depth < 0.03:  # Valley should be at least 3% below peaks
            return None

        # 3. Pattern should be recent (second peak within last 10 periods)
        if peak2_idx < len(prices) - 15:
            return None

        # 4. Current price should be below both peaks (confirmation)
        current_price = closes[-1]
        if current_price >= peak_avg:
            return None

        # Calculate confidence based on pattern quality
        confidence = 0.5
        confidence += (1 - price_diff) * 0.2  # Better peak alignment = higher confidence
        confidence += min(valley_depth / 0.1, 0.2)  # Deeper valley = higher confidence

        # Bonus if current price broke below neckline (valley)
        if current_price < valley_price:
            confidence += 0.15

        confidence = min(confidence, 0.95)

        # Calculate price target (measured move)
        pattern_height = peak_avg - valley_price
        price_target = valley_price - pattern_height

        # Stop loss above the peaks
        stop_loss = peak_avg * 1.02

        return DetectedPattern(
            pattern_type=PatternType.DOUBLE_TOP,
            symbol=symbol,
            start_date=dates[peak1_idx],
            end_date=dates[-1],
            confidence=confidence,
            price_target=price_target,
            stop_loss=stop_loss,
            description=f"Double top pattern detected with peaks at {peak1_price:.2f} and {peak2_price:.2f}. "
                       f"Neckline at {valley_price:.2f}. Bearish reversal signal.",
            supporting_data={
                "peak1_price": float(peak1_price),
                "peak2_price": float(peak2_price),
                "valley_price": float(valley_price),
                "peak1_idx": int(peak1_idx),
                "peak2_idx": int(peak2_idx),
                "valley_idx": int(valley_idx),
                "pattern_height": float(pattern_height)
            }
        )

    async def detect_double_bottom(
        self,
        prices: list[dict[str, Any]],
        symbol: str = "UNKNOWN"
    ) -> DetectedPattern | None:
        """
        Detect double bottom reversal pattern.

        A double bottom forms when price makes two roughly equal lows with a
        moderate rise between them, signaling potential bullish reversal.
        """
        if len(prices) < 30:
            return None

        _, highs, lows, closes, dates = self._extract_prices(prices)

        # Find recent local minima
        _, min_indices = self._find_local_extrema(lows, order=5)

        if len(min_indices) < 2:
            return None

        # Get the two most recent significant troughs
        recent_min = sorted(min_indices[-10:], key=lambda i: lows[i])

        if len(recent_min) < 2:
            return None

        # Check the two lowest troughs
        trough1_idx, trough2_idx = sorted(recent_min[:2])
        trough1_price = lows[trough1_idx]
        trough2_price = lows[trough2_idx]

        # Validate pattern criteria
        # 1. Troughs should be roughly equal (within 3%)
        price_diff = abs(trough1_price - trough2_price) / max(trough1_price, trough2_price)
        if price_diff > 0.03:
            return None

        # 2. There should be a peak between troughs (at least 3% above troughs)
        peak_slice = highs[trough1_idx:trough2_idx + 1]
        if len(peak_slice) < 3:
            return None

        peak_price = np.max(peak_slice)
        peak_idx = trough1_idx + np.argmax(peak_slice)

        trough_avg = (trough1_price + trough2_price) / 2
        peak_height = (peak_price - trough_avg) / trough_avg

        if peak_height < 0.03:  # Peak should be at least 3% above troughs
            return None

        # 3. Pattern should be recent (second trough within last 10 periods)
        if trough2_idx < len(prices) - 15:
            return None

        # 4. Current price should be above both troughs (confirmation)
        current_price = closes[-1]
        if current_price <= trough_avg:
            return None

        # Calculate confidence based on pattern quality
        confidence = 0.5
        confidence += (1 - price_diff) * 0.2  # Better trough alignment = higher confidence
        confidence += min(peak_height / 0.1, 0.2)  # Higher peak = higher confidence

        # Bonus if current price broke above neckline (peak)
        if current_price > peak_price:
            confidence += 0.15

        confidence = min(confidence, 0.95)

        # Calculate price target (measured move)
        pattern_height = peak_price - trough_avg
        price_target = peak_price + pattern_height

        # Stop loss below the troughs
        stop_loss = trough_avg * 0.98

        return DetectedPattern(
            pattern_type=PatternType.DOUBLE_BOTTOM,
            symbol=symbol,
            start_date=dates[trough1_idx],
            end_date=dates[-1],
            confidence=confidence,
            price_target=price_target,
            stop_loss=stop_loss,
            description=f"Double bottom pattern detected with troughs at {trough1_price:.2f} and {trough2_price:.2f}. "
                       f"Neckline at {peak_price:.2f}. Bullish reversal signal.",
            supporting_data={
                "trough1_price": float(trough1_price),
                "trough2_price": float(trough2_price),
                "peak_price": float(peak_price),
                "trough1_idx": int(trough1_idx),
                "trough2_idx": int(trough2_idx),
                "peak_idx": int(peak_idx),
                "pattern_height": float(pattern_height)
            }
        )

    async def detect_head_and_shoulders(
        self,
        prices: list[dict[str, Any]],
        symbol: str = "UNKNOWN"
    ) -> DetectedPattern | None:
        """
        Detect head and shoulders reversal pattern.

        Classic bearish reversal with three peaks: left shoulder, head (highest), right shoulder.
        """
        if len(prices) < 50:
            return None

        _, highs, lows, closes, dates = self._extract_prices(prices)

        # Find local maxima
        max_indices, _ = self._find_local_extrema(highs, order=5)

        if len(max_indices) < 3:
            return None

        # Look for H&S pattern in recent data
        recent_maxima = max_indices[-15:]  # Last 15 peaks

        if len(recent_maxima) < 3:
            return None

        # Try different combinations to find valid pattern
        for i in range(len(recent_maxima) - 2):
            left_idx = recent_maxima[i]
            head_idx = recent_maxima[i + 1]
            right_idx = recent_maxima[i + 2]

            left_price = highs[left_idx]
            head_price = highs[head_idx]
            right_price = highs[right_idx]

            # Validate H&S criteria
            # 1. Head should be the highest
            if head_price <= left_price or head_price <= right_price:
                continue

            # 2. Shoulders should be roughly equal (within 5%)
            shoulder_diff = abs(left_price - right_price) / max(left_price, right_price)
            if shoulder_diff > 0.05:
                continue

            # 3. Head should be at least 3% above shoulders
            shoulder_avg = (left_price + right_price) / 2
            head_height = (head_price - shoulder_avg) / shoulder_avg
            if head_height < 0.03:
                continue

            # Find neckline (connecting the troughs)
            trough1_slice = lows[left_idx:head_idx]
            trough2_slice = lows[head_idx:right_idx + 1]

            if len(trough1_slice) < 2 or len(trough2_slice) < 2:
                continue

            neckline1 = np.min(trough1_slice)
            neckline2 = np.min(trough2_slice)
            neckline = (neckline1 + neckline2) / 2

            # Pattern should be recent
            if right_idx < len(prices) - 20:
                continue

            # Current price should be near or below neckline for confirmation
            current_price = closes[-1]

            # Calculate confidence
            confidence = 0.5
            confidence += (1 - shoulder_diff) * 0.15
            confidence += min(head_height / 0.1, 0.2)

            if current_price < neckline:
                confidence += 0.2  # Neckline break confirmation

            confidence = min(confidence, 0.95)

            if confidence < self.min_confidence:
                continue

            # Calculate price target
            pattern_height = head_price - neckline
            price_target = neckline - pattern_height
            stop_loss = head_price * 1.02

            return DetectedPattern(
                pattern_type=PatternType.HEAD_AND_SHOULDERS,
                symbol=symbol,
                start_date=dates[left_idx],
                end_date=dates[-1],
                confidence=confidence,
                price_target=price_target,
                stop_loss=stop_loss,
                description=f"Head and shoulders pattern: left shoulder at {left_price:.2f}, "
                           f"head at {head_price:.2f}, right shoulder at {right_price:.2f}. "
                           f"Neckline at {neckline:.2f}. Bearish reversal signal.",
                supporting_data={
                    "left_shoulder": float(left_price),
                    "head": float(head_price),
                    "right_shoulder": float(right_price),
                    "neckline": float(neckline),
                    "pattern_height": float(pattern_height)
                }
            )

        return None

    async def detect_breakout(
        self,
        prices: list[dict[str, Any]],
        resistance_levels: list[dict[str, Any]],
        symbol: str = "UNKNOWN"
    ) -> DetectedPattern | None:
        """
        Detect price breakout above resistance.

        A breakout occurs when price closes above a significant resistance level
        with increased volume (if available).
        """
        if len(prices) < 10 or not resistance_levels:
            return None

        _, highs, lows, closes, dates = self._extract_prices(prices)
        current_price = closes[-1]
        prev_price = closes[-2] if len(closes) > 1 else current_price

        for level_info in resistance_levels:
            level = level_info["level"]
            strength = level_info.get("strength", 0.5)

            # Check if price broke above resistance
            if prev_price <= level and current_price > level:
                # Calculate breakout strength
                breakout_pct = (current_price - level) / level

                # Minimum 0.5% break to avoid noise
                if breakout_pct < 0.005:
                    continue

                confidence = 0.5
                confidence += strength * 0.2  # Stronger level = more significant breakout
                confidence += min(breakout_pct / 0.03, 0.2)  # Larger break = higher confidence

                # Check if we have volume data
                if "volume" in prices[-1]:
                    current_vol = prices[-1]["volume"]
                    avg_vol = np.mean([p["volume"] for p in prices[-20:]])
                    if current_vol > avg_vol * 1.5:
                        confidence += 0.15  # Volume confirmation

                confidence = min(confidence, 0.95)

                if confidence < self.min_confidence:
                    continue

                # Price target: measured from recent swing low to breakout level
                recent_low = np.min(lows[-20:])
                move_size = level - recent_low
                price_target = level + move_size

                # Stop loss just below the broken resistance (now support)
                stop_loss = level * 0.98

                return DetectedPattern(
                    pattern_type=PatternType.BREAKOUT,
                    symbol=symbol,
                    start_date=dates[-10],
                    end_date=dates[-1],
                    confidence=confidence,
                    price_target=price_target,
                    stop_loss=stop_loss,
                    description=f"Breakout above resistance at {level:.2f}. "
                               f"Current price {current_price:.2f} is {breakout_pct*100:.1f}% above level. "
                               f"Bullish continuation signal.",
                    supporting_data={
                        "resistance_level": float(level),
                        "breakout_percentage": float(breakout_pct),
                        "level_strength": float(strength),
                        "current_price": float(current_price)
                    }
                )

        return None

    async def detect_breakdown(
        self,
        prices: list[dict[str, Any]],
        support_levels: list[dict[str, Any]],
        symbol: str = "UNKNOWN"
    ) -> DetectedPattern | None:
        """
        Detect price breakdown below support.
        """
        if len(prices) < 10 or not support_levels:
            return None

        _, highs, lows, closes, dates = self._extract_prices(prices)
        current_price = closes[-1]
        prev_price = closes[-2] if len(closes) > 1 else current_price

        for level_info in support_levels:
            level = level_info["level"]
            strength = level_info.get("strength", 0.5)

            # Check if price broke below support
            if prev_price >= level and current_price < level:
                breakdown_pct = (level - current_price) / level

                if breakdown_pct < 0.005:
                    continue

                confidence = 0.5
                confidence += strength * 0.2
                confidence += min(breakdown_pct / 0.03, 0.2)

                if "volume" in prices[-1]:
                    current_vol = prices[-1]["volume"]
                    avg_vol = np.mean([p["volume"] for p in prices[-20:]])
                    if current_vol > avg_vol * 1.5:
                        confidence += 0.15

                confidence = min(confidence, 0.95)

                if confidence < self.min_confidence:
                    continue

                recent_high = np.max(highs[-20:])
                move_size = recent_high - level
                price_target = level - move_size
                stop_loss = level * 1.02

                return DetectedPattern(
                    pattern_type=PatternType.BREAKDOWN,
                    symbol=symbol,
                    start_date=dates[-10],
                    end_date=dates[-1],
                    confidence=confidence,
                    price_target=price_target,
                    stop_loss=stop_loss,
                    description=f"Breakdown below support at {level:.2f}. "
                               f"Current price {current_price:.2f} is {breakdown_pct*100:.1f}% below level. "
                               f"Bearish continuation signal.",
                    supporting_data={
                        "support_level": float(level),
                        "breakdown_percentage": float(breakdown_pct),
                        "level_strength": float(strength),
                        "current_price": float(current_price)
                    }
                )

        return None

    async def detect_golden_cross(
        self,
        prices: list[dict[str, Any]],
        symbol: str = "UNKNOWN"
    ) -> DetectedPattern | None:
        """
        Detect golden cross (50 SMA crosses above 200 SMA).
        """
        if len(prices) < 200:
            return None

        _, _, _, closes, dates = self._extract_prices(prices)

        # Calculate SMAs
        sma_50 = self._sma(closes, 50)
        sma_200 = self._sma(closes, 200)

        # Check for recent crossover (last 5 periods)
        for i in range(-5, 0):
            if i - 1 < -len(sma_50):
                continue

            curr_50 = sma_50[i]
            curr_200 = sma_200[i]
            prev_50 = sma_50[i - 1]
            prev_200 = sma_200[i - 1]

            if (curr_50 is not None and curr_200 is not None and
                prev_50 is not None and prev_200 is not None):

                # Golden cross: 50 SMA crosses above 200 SMA
                if prev_50 <= prev_200 and curr_50 > curr_200:
                    # Calculate confidence based on the cross margin
                    cross_margin = (curr_50 - curr_200) / curr_200
                    confidence = 0.6 + min(cross_margin * 10, 0.3)

                    # Price target: ~10% above current price
                    current_price = closes[-1]
                    price_target = current_price * 1.10
                    stop_loss = curr_200 * 0.98

                    return DetectedPattern(
                        pattern_type=PatternType.GOLDEN_CROSS,
                        symbol=symbol,
                        start_date=dates[i - 5],
                        end_date=dates[-1],
                        confidence=confidence,
                        price_target=price_target,
                        stop_loss=stop_loss,
                        description=f"Golden cross detected: 50-day SMA ({curr_50:.2f}) "
                                   f"crossed above 200-day SMA ({curr_200:.2f}). "
                                   f"Strong bullish signal.",
                        supporting_data={
                            "sma_50": float(curr_50),
                            "sma_200": float(curr_200),
                            "cross_margin": float(cross_margin),
                            "current_price": float(current_price)
                        }
                    )

        return None

    async def detect_death_cross(
        self,
        prices: list[dict[str, Any]],
        symbol: str = "UNKNOWN"
    ) -> DetectedPattern | None:
        """
        Detect death cross (50 SMA crosses below 200 SMA).
        """
        if len(prices) < 200:
            return None

        _, _, _, closes, dates = self._extract_prices(prices)

        sma_50 = self._sma(closes, 50)
        sma_200 = self._sma(closes, 200)

        for i in range(-5, 0):
            if i - 1 < -len(sma_50):
                continue

            curr_50 = sma_50[i]
            curr_200 = sma_200[i]
            prev_50 = sma_50[i - 1]
            prev_200 = sma_200[i - 1]

            if (curr_50 is not None and curr_200 is not None and
                prev_50 is not None and prev_200 is not None):

                # Death cross: 50 SMA crosses below 200 SMA
                if prev_50 >= prev_200 and curr_50 < curr_200:
                    cross_margin = (curr_200 - curr_50) / curr_200
                    confidence = 0.6 + min(cross_margin * 10, 0.3)

                    current_price = closes[-1]
                    price_target = current_price * 0.90
                    stop_loss = curr_200 * 1.02

                    return DetectedPattern(
                        pattern_type=PatternType.DEATH_CROSS,
                        symbol=symbol,
                        start_date=dates[i - 5],
                        end_date=dates[-1],
                        confidence=confidence,
                        price_target=price_target,
                        stop_loss=stop_loss,
                        description=f"Death cross detected: 50-day SMA ({curr_50:.2f}) "
                                   f"crossed below 200-day SMA ({curr_200:.2f}). "
                                   f"Strong bearish signal.",
                        supporting_data={
                            "sma_50": float(curr_50),
                            "sma_200": float(curr_200),
                            "cross_margin": float(cross_margin),
                            "current_price": float(current_price)
                        }
                    )

        return None

    async def detect_bull_flag(
        self,
        prices: list[dict[str, Any]],
        symbol: str = "UNKNOWN"
    ) -> DetectedPattern | None:
        """
        Detect bull flag continuation pattern.

        A bull flag forms after a strong upward move (pole), followed by
        a slight downward or sideways consolidation (flag).
        """
        if len(prices) < 30:
            return None

        _, highs, lows, closes, dates = self._extract_prices(prices)

        # Look for strong up move (pole) followed by consolidation (flag)
        # Check last 30 periods

        # Find the pole: strong upward move in first ~20 periods
        pole_start = -30
        pole_end = -10
        flag_start = -10

        pole_gain = (closes[pole_end] - closes[pole_start]) / closes[pole_start]

        # Pole should show at least 10% gain
        if pole_gain < 0.10:
            return None

        # Flag should be a slight pullback or consolidation
        flag_prices = closes[flag_start:]
        flag_lows = lows[flag_start:]

        # Calculate flag characteristics
        flag_slope = self._calculate_slope(flag_prices)
        flag_range = (np.max(flag_prices) - np.min(flag_prices)) / np.mean(flag_prices)

        # Flag should be slightly down or sideways (negative or small positive slope)
        # and have a tight range
        if flag_slope > 0.5 or flag_range > 0.08:
            return None

        # The flag pullback should not retrace more than 50% of the pole
        flag_low = np.min(flag_lows)
        pole_high = closes[pole_end]
        pole_low = closes[pole_start]
        retracement = (pole_high - flag_low) / (pole_high - pole_low)

        if retracement > 0.5:
            return None

        # Calculate confidence
        confidence = 0.5
        confidence += min(pole_gain / 0.2, 0.2)  # Stronger pole
        confidence += (0.5 - retracement) * 0.2  # Less retracement
        confidence += (0.08 - flag_range) * 2  # Tighter flag
        confidence = min(confidence, 0.90)

        if confidence < self.min_confidence:
            return None

        # Price target: pole length projected from flag breakout
        pole_length = pole_high - pole_low
        price_target = closes[-1] + pole_length
        stop_loss = flag_low * 0.98

        return DetectedPattern(
            pattern_type=PatternType.BULL_FLAG,
            symbol=symbol,
            start_date=dates[pole_start],
            end_date=dates[-1],
            confidence=confidence,
            price_target=price_target,
            stop_loss=stop_loss,
            description=f"Bull flag pattern: {pole_gain*100:.1f}% pole followed by "
                       f"{retracement*100:.1f}% retracement. Bullish continuation signal.",
            supporting_data={
                "pole_gain": float(pole_gain),
                "retracement": float(retracement),
                "flag_range": float(flag_range),
                "pole_length": float(pole_length)
            }
        )

    async def detect_ascending_triangle(
        self,
        prices: list[dict[str, Any]],
        symbol: str = "UNKNOWN"
    ) -> DetectedPattern | None:
        """
        Detect ascending triangle pattern.

        Ascending triangle has a flat resistance line and rising support (higher lows).
        """
        if len(prices) < 30:
            return None

        _, highs, lows, closes, dates = self._extract_prices(prices[-30:])

        # Find local extrema
        max_indices, min_indices = self._find_local_extrema(closes, order=3)

        if len(max_indices) < 3 or len(min_indices) < 3:
            return None

        # Check for flat resistance (highs should be roughly equal)
        resistance_prices = highs[max_indices]
        resistance_std = np.std(resistance_prices) / np.mean(resistance_prices)

        if resistance_std > 0.02:  # Resistance should be within 2% std dev
            return None

        # Check for rising support (lows should be increasing)
        support_prices = lows[min_indices]
        support_slope = self._calculate_slope(support_prices)

        if support_slope <= 0:  # Support must be rising
            return None

        # Calculate confidence
        confidence = 0.5
        confidence += (0.02 - resistance_std) * 10  # Flatter resistance
        confidence += min(support_slope / np.mean(support_prices) * 100, 0.2)  # Steeper support
        confidence = min(confidence, 0.90)

        if confidence < self.min_confidence:
            return None

        # Price target: pattern height projected from breakout
        resistance_level = np.mean(resistance_prices)
        support_level = np.min(support_prices)
        pattern_height = resistance_level - support_level
        price_target = resistance_level + pattern_height
        stop_loss = closes[-1] * 0.97

        return DetectedPattern(
            pattern_type=PatternType.ASCENDING_TRIANGLE,
            symbol=symbol,
            start_date=dates[0],
            end_date=dates[-1],
            confidence=confidence,
            price_target=price_target,
            stop_loss=stop_loss,
            description=f"Ascending triangle: flat resistance at {resistance_level:.2f} with "
                       f"rising support. Bullish continuation pattern.",
            supporting_data={
                "resistance_level": float(resistance_level),
                "support_level": float(support_level),
                "pattern_height": float(pattern_height),
                "resistance_std": float(resistance_std)
            }
        )

    def _sma(self, prices: np.ndarray, period: int) -> list[float | None]:
        """Calculate Simple Moving Average."""
        if len(prices) < period:
            return [None] * len(prices)

        result: list[float | None] = [None] * (period - 1)
        for i in range(period - 1, len(prices)):
            result.append(float(np.mean(prices[i - period + 1:i + 1])))
        return result

    async def detect_all_patterns(
        self,
        symbol: str,
        prices: list[dict[str, Any]]
    ) -> list[DetectedPattern]:
        """
        Run all pattern detection algorithms.

        Args:
            symbol: Stock symbol
            prices: OHLCV price data (list of dicts with open, high, low, close, volume, date)

        Returns:
            List of detected patterns that meet the minimum confidence threshold
        """
        if len(prices) < 20:
            return []

        patterns: list[DetectedPattern] = []

        # Detect trend
        trend_type, trend_confidence = await self.detect_trend(prices)

        # Find S/R levels
        sr_levels = await self.detect_support_resistance(prices)

        # Check for reversal patterns
        if double_top := await self.detect_double_top(prices, symbol):
            if double_top.confidence >= self.min_confidence:
                patterns.append(double_top)

        if double_bottom := await self.detect_double_bottom(prices, symbol):
            if double_bottom.confidence >= self.min_confidence:
                patterns.append(double_bottom)

        if h_and_s := await self.detect_head_and_shoulders(prices, symbol):
            if h_and_s.confidence >= self.min_confidence:
                patterns.append(h_and_s)

        # Check for breakouts/breakdowns
        if sr_levels["resistance"]:
            if breakout := await self.detect_breakout(prices, sr_levels["resistance"], symbol):
                if breakout.confidence >= self.min_confidence:
                    patterns.append(breakout)

        if sr_levels["support"]:
            if breakdown := await self.detect_breakdown(prices, sr_levels["support"], symbol):
                if breakdown.confidence >= self.min_confidence:
                    patterns.append(breakdown)

        # Check for MA crossovers (need 200+ data points)
        if len(prices) >= 200:
            if golden_cross := await self.detect_golden_cross(prices, symbol):
                if golden_cross.confidence >= self.min_confidence:
                    patterns.append(golden_cross)

            if death_cross := await self.detect_death_cross(prices, symbol):
                if death_cross.confidence >= self.min_confidence:
                    patterns.append(death_cross)

        # Check for continuation patterns
        if bull_flag := await self.detect_bull_flag(prices, symbol):
            if bull_flag.confidence >= self.min_confidence:
                patterns.append(bull_flag)

        if ascending_triangle := await self.detect_ascending_triangle(prices, symbol):
            if ascending_triangle.confidence >= self.min_confidence:
                patterns.append(ascending_triangle)

        # Sort by confidence (highest first)
        patterns.sort(key=lambda p: p.confidence, reverse=True)

        return patterns

    async def get_pattern_summary(
        self,
        patterns: list[DetectedPattern]
    ) -> dict[str, Any]:
        """
        Generate a summary of detected patterns.

        Args:
            patterns: List of detected patterns

        Returns:
            Summary dict with counts, signals, and overall assessment
        """
        if not patterns:
            return {
                "total_patterns": 0,
                "bullish_patterns": 0,
                "bearish_patterns": 0,
                "neutral_patterns": 0,
                "overall_bias": "neutral",
                "confidence": 0.0,
                "patterns": []
            }

        bullish_patterns: list[DetectedPattern] = []
        bearish_patterns: list[DetectedPattern] = []
        neutral_patterns: list[DetectedPattern] = []

        bullish_types = {
            PatternType.UPTREND, PatternType.DOUBLE_BOTTOM,
            PatternType.INVERSE_HEAD_AND_SHOULDERS, PatternType.GOLDEN_CROSS,
            PatternType.BULL_FLAG, PatternType.BREAKOUT,
            PatternType.SUPPORT_BOUNCE, PatternType.ASCENDING_TRIANGLE
        }

        bearish_types = {
            PatternType.DOWNTREND, PatternType.DOUBLE_TOP,
            PatternType.HEAD_AND_SHOULDERS, PatternType.DEATH_CROSS,
            PatternType.BEAR_FLAG, PatternType.BREAKDOWN,
            PatternType.RESISTANCE_REJECTION, PatternType.DESCENDING_TRIANGLE
        }

        for pattern in patterns:
            if pattern.pattern_type in bullish_types:
                bullish_patterns.append(pattern)
            elif pattern.pattern_type in bearish_types:
                bearish_patterns.append(pattern)
            else:
                neutral_patterns.append(pattern)

        # Calculate overall bias
        bullish_score = sum(p.confidence for p in bullish_patterns)
        bearish_score = sum(p.confidence for p in bearish_patterns)

        if bullish_score > bearish_score * 1.2:
            overall_bias = "bullish"
            confidence = bullish_score / (bullish_score + bearish_score + 0.01)
        elif bearish_score > bullish_score * 1.2:
            overall_bias = "bearish"
            confidence = bearish_score / (bullish_score + bearish_score + 0.01)
        else:
            overall_bias = "neutral"
            confidence = 0.5

        return {
            "total_patterns": len(patterns),
            "bullish_patterns": len(bullish_patterns),
            "bearish_patterns": len(bearish_patterns),
            "neutral_patterns": len(neutral_patterns),
            "overall_bias": overall_bias,
            "confidence": round(confidence, 4),
            "patterns": [p.to_dict() for p in patterns]
        }


# Global instance
pattern_detector = PatternDetector()
