"""
Anomaly detection module for identifying unusual market activity.
Uses statistical methods (z-scores) to detect outliers in market data.
"""

from typing import Any
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
import statistics


class AnomalyType(Enum):
    """Types of market anomalies."""
    VOLUME_SPIKE = "volume_spike"
    PRICE_GAP = "price_gap"
    VOLATILITY_SURGE = "volatility_surge"
    UNUSUAL_PRICE_MOVE = "unusual_price_move"
    CORRELATION_BREAK = "correlation_break"
    SECTOR_DIVERGENCE = "sector_divergence"


@dataclass
class DetectedAnomaly:
    """A detected market anomaly."""
    anomaly_type: AnomalyType
    symbol: str
    detected_at: datetime
    severity: str  # "info", "warning", "alert"
    value: float  # The anomalous value
    expected_range: tuple[float, float]  # Normal range
    z_score: float  # Standard deviations from mean
    description: str


class AnomalyDetector:
    """Detect unusual market activity."""

    # Z-score thresholds for severity
    THRESHOLDS = {
        "info": 2.0,      # 2 std devs
        "warning": 2.5,   # 2.5 std devs
        "alert": 3.0      # 3 std devs
    }

    async def detect_volume_spike(
        self,
        symbol: str,
        volumes: list[int],
        current_volume: int,
        lookback: int = 20
    ) -> DetectedAnomaly | None:
        """
        Detect unusual trading volume.

        Args:
            symbol: Stock ticker symbol
            volumes: Historical volume data
            current_volume: Current trading volume to evaluate
            lookback: Number of periods to use for baseline

        Returns:
            DetectedAnomaly if volume is unusual, None otherwise
        """
        if len(volumes) < lookback:
            return None

        recent = volumes[-lookback:]
        mean = statistics.mean(recent)
        std = statistics.stdev(recent) if len(recent) > 1 else 0

        if std == 0:
            return None

        z_score = (current_volume - mean) / std

        if abs(z_score) >= self.THRESHOLDS["info"]:
            severity = self._get_severity(abs(z_score))
            direction = "above" if z_score > 0 else "below"
            return DetectedAnomaly(
                anomaly_type=AnomalyType.VOLUME_SPIKE,
                symbol=symbol,
                detected_at=datetime.utcnow(),
                severity=severity,
                value=float(current_volume),
                expected_range=(mean - 2*std, mean + 2*std),
                z_score=z_score,
                description=f"Volume {abs(z_score):.1f} std devs {direction} normal ({current_volume:,} vs avg {mean:,.0f})"
            )
        return None

    async def detect_price_gap(
        self,
        symbol: str,
        prev_close: float,
        current_open: float,
        avg_daily_range: float
    ) -> DetectedAnomaly | None:
        """
        Detect gap up/down at open.

        A gap occurs when the opening price differs significantly from
        the previous close. We measure significance relative to the
        average daily range.

        Args:
            symbol: Stock ticker symbol
            prev_close: Previous day's closing price
            current_open: Current day's opening price
            avg_daily_range: Average daily price range (high - low) as percentage

        Returns:
            DetectedAnomaly if gap is significant, None otherwise
        """
        if prev_close <= 0 or avg_daily_range <= 0:
            return None

        gap_pct = ((current_open - prev_close) / prev_close) * 100

        # Calculate z-score: gap relative to average daily movement
        # Gaps larger than 2x the average daily range are unusual
        z_score = abs(gap_pct) / avg_daily_range

        if z_score >= self.THRESHOLDS["info"]:
            severity = self._get_severity(z_score)
            direction = "up" if gap_pct > 0 else "down"
            expected_range = (-avg_daily_range, avg_daily_range)

            return DetectedAnomaly(
                anomaly_type=AnomalyType.PRICE_GAP,
                symbol=symbol,
                detected_at=datetime.utcnow(),
                severity=severity,
                value=gap_pct,
                expected_range=expected_range,
                z_score=z_score,
                description=f"Gap {direction} {abs(gap_pct):.2f}% (avg daily range: {avg_daily_range:.2f}%)"
            )
        return None

    async def detect_volatility_surge(
        self,
        symbol: str,
        prices: list[dict],
        lookback: int = 20
    ) -> DetectedAnomaly | None:
        """
        Detect sudden increase in volatility.

        Calculates the current volatility (using recent returns) and
        compares it to historical volatility.

        Args:
            symbol: Stock ticker symbol
            prices: List of price dicts with 'close' key
            lookback: Number of periods for baseline volatility

        Returns:
            DetectedAnomaly if volatility is unusually high, None otherwise
        """
        if len(prices) < lookback + 5:  # Need extra for comparison
            return None

        # Calculate daily returns
        returns = []
        for i in range(1, len(prices)):
            prev_close = prices[i-1].get('close', 0)
            curr_close = prices[i].get('close', 0)
            if prev_close > 0:
                daily_return = (curr_close - prev_close) / prev_close
                returns.append(daily_return)

        if len(returns) < lookback + 5:
            return None

        # Calculate historical volatility (std of returns)
        historical_vols = []
        for i in range(lookback, len(returns)):
            window = returns[i-lookback:i]
            if len(window) >= 2:
                vol = statistics.stdev(window)
                historical_vols.append(vol)

        if len(historical_vols) < 5:
            return None

        # Current volatility (last 5 days)
        current_vol = statistics.stdev(returns[-5:])

        # Historical volatility stats
        mean_vol = statistics.mean(historical_vols)
        std_vol = statistics.stdev(historical_vols) if len(historical_vols) > 1 else 0

        if std_vol == 0:
            return None

        z_score = (current_vol - mean_vol) / std_vol

        if z_score >= self.THRESHOLDS["info"]:
            severity = self._get_severity(z_score)
            return DetectedAnomaly(
                anomaly_type=AnomalyType.VOLATILITY_SURGE,
                symbol=symbol,
                detected_at=datetime.utcnow(),
                severity=severity,
                value=current_vol * 100,  # As percentage
                expected_range=(max(0, (mean_vol - 2*std_vol) * 100), (mean_vol + 2*std_vol) * 100),
                z_score=z_score,
                description=f"Volatility at {current_vol*100:.2f}% vs historical avg {mean_vol*100:.2f}%"
            )
        return None

    async def detect_unusual_move(
        self,
        symbol: str,
        price_change_pct: float,
        historical_changes: list[float]
    ) -> DetectedAnomaly | None:
        """
        Detect unusually large price move.

        Args:
            symbol: Stock ticker symbol
            price_change_pct: Current price change as percentage
            historical_changes: List of historical daily changes (percentages)

        Returns:
            DetectedAnomaly if move is unusual, None otherwise
        """
        if len(historical_changes) < 10:
            return None

        mean = statistics.mean(historical_changes)
        std = statistics.stdev(historical_changes) if len(historical_changes) > 1 else 0

        if std == 0:
            return None

        z_score = (price_change_pct - mean) / std

        if abs(z_score) >= self.THRESHOLDS["info"]:
            severity = self._get_severity(abs(z_score))
            direction = "up" if price_change_pct > 0 else "down"

            return DetectedAnomaly(
                anomaly_type=AnomalyType.UNUSUAL_PRICE_MOVE,
                symbol=symbol,
                detected_at=datetime.utcnow(),
                severity=severity,
                value=price_change_pct,
                expected_range=(mean - 2*std, mean + 2*std),
                z_score=z_score,
                description=f"Price moved {direction} {abs(price_change_pct):.2f}% ({abs(z_score):.1f} std devs from mean)"
            )
        return None

    async def detect_all_anomalies(
        self,
        symbol: str,
        price_data: list[dict[str, Any]]
    ) -> list[DetectedAnomaly]:
        """
        Run all anomaly detection algorithms on the given price data.

        Args:
            symbol: Stock ticker symbol
            price_data: List of price dicts with keys:
                - date: Date of the data point
                - open: Opening price
                - high: High price
                - low: Low price
                - close: Closing price
                - volume: Trading volume

        Returns:
            List of all detected anomalies
        """
        anomalies = []

        if len(price_data) < 2:
            return anomalies

        # Extract data series
        volumes = [d.get('volume', 0) for d in price_data]
        closes = [d.get('close', 0) for d in price_data]

        # Calculate historical daily changes (percentages)
        historical_changes = []
        for i in range(1, len(closes)):
            if closes[i-1] > 0:
                change = ((closes[i] - closes[i-1]) / closes[i-1]) * 100
                historical_changes.append(change)

        # Calculate average daily range
        daily_ranges = []
        for d in price_data:
            high = d.get('high', 0)
            low = d.get('low', 0)
            close = d.get('close', 0)
            if close > 0:
                range_pct = ((high - low) / close) * 100
                daily_ranges.append(range_pct)

        avg_daily_range = statistics.mean(daily_ranges) if daily_ranges else 0

        # Get current data (most recent)
        current = price_data[-1]
        current_volume = current.get('volume', 0)
        current_open = current.get('open', 0)
        current_close = current.get('close', 0)

        # Previous data
        prev = price_data[-2]
        prev_close = prev.get('close', 0)

        # Current price change
        current_change_pct = 0
        if prev_close > 0:
            current_change_pct = ((current_close - prev_close) / prev_close) * 100

        # Run all detection algorithms

        # 1. Volume spike detection
        volume_anomaly = await self.detect_volume_spike(
            symbol=symbol,
            volumes=volumes[:-1],  # Historical volumes (excluding current)
            current_volume=current_volume
        )
        if volume_anomaly:
            anomalies.append(volume_anomaly)

        # 2. Price gap detection
        gap_anomaly = await self.detect_price_gap(
            symbol=symbol,
            prev_close=prev_close,
            current_open=current_open,
            avg_daily_range=avg_daily_range
        )
        if gap_anomaly:
            anomalies.append(gap_anomaly)

        # 3. Volatility surge detection
        vol_anomaly = await self.detect_volatility_surge(
            symbol=symbol,
            prices=price_data
        )
        if vol_anomaly:
            anomalies.append(vol_anomaly)

        # 4. Unusual price move detection
        move_anomaly = await self.detect_unusual_move(
            symbol=symbol,
            price_change_pct=current_change_pct,
            historical_changes=historical_changes[:-1]  # Exclude current
        )
        if move_anomaly:
            anomalies.append(move_anomaly)

        return anomalies

    def _get_severity(self, z_score: float) -> str:
        """
        Map z-score to severity level.

        Args:
            z_score: Absolute z-score value

        Returns:
            Severity level: "info", "warning", or "alert"
        """
        if z_score >= self.THRESHOLDS["alert"]:
            return "alert"
        elif z_score >= self.THRESHOLDS["warning"]:
            return "warning"
        return "info"


# Module-level singleton instance
anomaly_detector = AnomalyDetector()
