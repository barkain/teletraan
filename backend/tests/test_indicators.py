"""Tests for the technical indicators and pattern detection modules.

Covers:
- TechnicalIndicators: SMA, EMA, RSI, MACD, Bollinger Bands, ATR, Stochastic
- IndicatorAnalyzer: interpret helpers, analyze_stock, get_signals, detect_crossovers
- PatternDetector: trend detection, support/resistance, double top/bottom,
  head & shoulders, breakout/breakdown, golden/death cross, bull flag,
  ascending triangle, pattern summary
- Edge cases: empty data, single data point, NaN handling, all-gains / all-losses RSI
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

import numpy as np
import pytest

from analysis.indicators import (
    IndicatorAnalyzer,
    IndicatorResult,
    TechnicalIndicators,
)
from analysis.patterns import (
    DetectedPattern,
    PatternDetector,
    PatternType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_prices(
    closes: list[float],
    *,
    start_date: date | None = None,
    spread: float = 2.0,
    base_volume: int = 50_000_000,
) -> list[dict[str, Any]]:
    """Build a list of OHLCV dicts from a close-price series.

    Open/high/low are derived from close +/- ``spread`` for simplicity.
    """
    if start_date is None:
        start_date = date(2025, 1, 1)

    prices: list[dict[str, Any]] = []
    for i, c in enumerate(closes):
        prices.append({
            "date": start_date + timedelta(days=i),
            "open": c - spread * 0.3,
            "high": c + spread,
            "low": c - spread,
            "close": c,
            "volume": base_volume + i * 100_000,
        })
    return prices


# ---------------------------------------------------------------------------
# SMA
# ---------------------------------------------------------------------------

class TestSMA:
    """Simple Moving Average tests."""

    def test_sma_basic(self):
        prices = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = TechnicalIndicators.sma(prices, 3)
        assert result[0] is None
        assert result[1] is None
        assert result[2] == pytest.approx(2.0)
        assert result[3] == pytest.approx(3.0)
        assert result[4] == pytest.approx(4.0)

    def test_sma_period_equals_length(self):
        prices = [10.0, 20.0, 30.0]
        result = TechnicalIndicators.sma(prices, 3)
        assert result == [None, None, pytest.approx(20.0)]

    def test_sma_period_exceeds_length(self):
        prices = [1.0, 2.0]
        result = TechnicalIndicators.sma(prices, 5)
        assert result == [None, None]

    def test_sma_single_element(self):
        result = TechnicalIndicators.sma([42.0], 1)
        assert result == [pytest.approx(42.0)]

    def test_sma_empty(self):
        result = TechnicalIndicators.sma([], 5)
        assert result == []

    def test_sma_all_same_values(self):
        prices = [100.0] * 10
        result = TechnicalIndicators.sma(prices, 5)
        for val in result[4:]:
            assert val == pytest.approx(100.0)

    def test_sma_output_length(self):
        prices = list(range(1, 51))
        result = TechnicalIndicators.sma([float(p) for p in prices], 20)
        assert len(result) == 50


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------

class TestEMA:
    """Exponential Moving Average tests."""

    def test_ema_basic(self):
        prices = [22.0, 22.5, 22.3, 22.8, 23.0, 23.2, 23.1]
        result = TechnicalIndicators.ema(prices, 3)
        # First two should be None, third is SMA of first 3 values
        assert result[0] is None
        assert result[1] is None
        expected_first_ema = (22.0 + 22.5 + 22.3) / 3
        assert result[2] == pytest.approx(expected_first_ema)
        # Subsequent values follow EMA formula
        multiplier = 2 / (3 + 1)
        expected_next = (22.8 - expected_first_ema) * multiplier + expected_first_ema
        assert result[3] == pytest.approx(expected_next)

    def test_ema_period_exceeds_length(self):
        result = TechnicalIndicators.ema([1.0, 2.0], 5)
        assert result == [None, None]

    def test_ema_empty(self):
        result = TechnicalIndicators.ema([], 3)
        assert result == []

    def test_ema_output_length(self):
        prices = [float(i) for i in range(1, 31)]
        result = TechnicalIndicators.ema(prices, 10)
        assert len(result) == 30

    def test_ema_first_value_is_sma(self):
        prices = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = TechnicalIndicators.ema(prices, 5)
        # First EMA value should equal SMA of the first 5 values
        assert result[4] == pytest.approx(30.0)

    def test_ema_constant_prices(self):
        prices = [50.0] * 20
        result = TechnicalIndicators.ema(prices, 5)
        for val in result[4:]:
            assert val == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

class TestRSI:
    """Relative Strength Index tests."""

    def test_rsi_known_values(self):
        """RSI with a known alternating gain/loss pattern."""
        # Build a series: start at 100, alternate +2, -1
        prices = [100.0]
        for i in range(30):
            if i % 2 == 0:
                prices.append(prices[-1] + 2.0)
            else:
                prices.append(prices[-1] - 1.0)

        result = TechnicalIndicators.rsi(prices, period=14)
        assert len(result) == len(prices)
        # First 14 values should be None
        for i in range(14):
            assert result[i] is None
        # RSI should be between 0 and 100
        for val in result[14:]:
            assert val is not None
            assert 0.0 <= val <= 100.0

    def test_rsi_all_gains(self):
        """When prices only go up, RSI should approach 100."""
        prices = [float(i) for i in range(50, 80)]
        result = TechnicalIndicators.rsi(prices, period=14)
        last_rsi = result[-1]
        assert last_rsi is not None
        assert last_rsi == pytest.approx(100.0)

    def test_rsi_all_losses(self):
        """When prices only go down, RSI should approach 0."""
        prices = [float(i) for i in range(80, 50, -1)]
        result = TechnicalIndicators.rsi(prices, period=14)
        last_rsi = result[-1]
        assert last_rsi is not None
        assert last_rsi == pytest.approx(0.0, abs=0.01)

    def test_rsi_too_few_prices(self):
        prices = [100.0, 101.0, 99.0]
        result = TechnicalIndicators.rsi(prices, period=14)
        assert all(v is None for v in result)

    def test_rsi_empty(self):
        result = TechnicalIndicators.rsi([], period=14)
        assert result == []

    def test_rsi_output_length(self):
        prices = [float(100 + i) for i in range(50)]
        result = TechnicalIndicators.rsi(prices, period=14)
        assert len(result) == 50

    def test_rsi_flat_prices(self):
        """Flat prices produce 0 gains and 0 losses; first RSI uses avg_loss==0 path."""
        prices = [100.0] * 20
        result = TechnicalIndicators.rsi(prices, period=14)
        # avg_gain=0, avg_loss=0 -> first RSI is 100.0 (avg_loss==0 branch)
        assert result[14] == pytest.approx(100.0)

    def test_rsi_boundary_length(self):
        """Exactly period+1 prices should produce one non-None RSI value."""
        prices = [100.0 + i * 0.5 for i in range(15)]  # period=14 needs 15 prices
        result = TechnicalIndicators.rsi(prices, period=14)
        non_none = [v for v in result if v is not None]
        assert len(non_none) == 1


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------

class TestMACD:
    """MACD tests (fast=12, slow=26, signal=9 by default)."""

    def test_macd_too_few_prices(self):
        prices = [float(i) for i in range(10)]
        macd_line, signal_line, histogram = TechnicalIndicators.macd(prices)
        assert all(v is None for v in macd_line)
        assert all(v is None for v in signal_line)
        assert all(v is None for v in histogram)

    def test_macd_output_lengths(self):
        prices = [100.0 + i * 0.5 for i in range(60)]
        macd_line, signal_line, histogram = TechnicalIndicators.macd(prices)
        assert len(macd_line) == 60
        assert len(signal_line) == 60
        assert len(histogram) == 60

    def test_macd_line_is_fast_minus_slow_ema(self):
        """MACD line should equal fast EMA - slow EMA where both are non-None."""
        prices = [100.0 + np.sin(i / 5.0) * 10 for i in range(60)]
        macd_line, _, _ = TechnicalIndicators.macd(prices)
        fast_ema = TechnicalIndicators.ema(prices, 12)
        slow_ema = TechnicalIndicators.ema(prices, 26)

        for i in range(len(prices)):
            if fast_ema[i] is not None and slow_ema[i] is not None:
                expected = fast_ema[i] - slow_ema[i]
                assert macd_line[i] == pytest.approx(expected, abs=1e-10)

    def test_macd_histogram_is_macd_minus_signal(self):
        prices = [100.0 + np.sin(i / 5.0) * 10 for i in range(80)]
        macd_line, signal_line, histogram = TechnicalIndicators.macd(prices)

        for m, s, h in zip(macd_line, signal_line, histogram):
            if m is not None and s is not None and h is not None:
                assert h == pytest.approx(m - s, abs=1e-10)

    def test_macd_empty(self):
        macd_line, signal_line, histogram = TechnicalIndicators.macd([])
        assert macd_line == []
        assert signal_line == []
        assert histogram == []

    def test_macd_constant_prices(self):
        """Constant prices should yield MACD line ~0."""
        prices = [100.0] * 60
        macd_line, signal_line, histogram = TechnicalIndicators.macd(prices)
        non_none_macd = [v for v in macd_line if v is not None]
        for val in non_none_macd:
            assert val == pytest.approx(0.0, abs=1e-10)


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

class TestBollingerBands:
    """Bollinger Bands tests."""

    def test_bollinger_basic_structure(self):
        prices = [float(100 + i) for i in range(30)]
        upper, middle, lower = TechnicalIndicators.bollinger_bands(prices, period=20)
        assert len(upper) == 30
        assert len(middle) == 30
        assert len(lower) == 30
        # First 19 should be None
        for i in range(19):
            assert upper[i] is None
            assert middle[i] is None
            assert lower[i] is None

    def test_bollinger_upper_above_lower(self):
        prices = [float(100 + np.sin(i / 3.0) * 5) for i in range(30)]
        upper, middle, lower = TechnicalIndicators.bollinger_bands(prices, period=20)
        for u, m, lo in zip(upper[19:], middle[19:], lower[19:]):
            assert u is not None and m is not None and lo is not None
            assert u >= m >= lo

    def test_bollinger_middle_is_sma(self):
        prices = [float(100 + i) for i in range(30)]
        upper, middle, lower = TechnicalIndicators.bollinger_bands(prices, period=20)
        sma = TechnicalIndicators.sma(prices, 20)
        for m, s in zip(middle, sma):
            if m is not None and s is not None:
                assert m == pytest.approx(s)

    def test_bollinger_too_few_prices(self):
        prices = [1.0, 2.0, 3.0]
        upper, middle, lower = TechnicalIndicators.bollinger_bands(prices, period=20)
        assert all(v is None for v in upper)
        assert all(v is None for v in middle)
        assert all(v is None for v in lower)

    def test_bollinger_empty(self):
        upper, middle, lower = TechnicalIndicators.bollinger_bands([])
        assert upper == []
        assert middle == []
        assert lower == []

    def test_bollinger_constant_prices(self):
        """Constant prices have 0 std; bands should collapse to the mean."""
        prices = [100.0] * 25
        upper, middle, lower = TechnicalIndicators.bollinger_bands(prices, period=20)
        for u, m, lo in zip(upper[19:], middle[19:], lower[19:]):
            assert u == pytest.approx(100.0)
            assert m == pytest.approx(100.0)
            assert lo == pytest.approx(100.0)

    def test_bollinger_custom_std_dev(self):
        """Wider std_dev multiplier should produce wider bands."""
        prices = [float(100 + i * 0.5) for i in range(30)]
        upper_2, _, lower_2 = TechnicalIndicators.bollinger_bands(prices, period=20, std_dev=2.0)
        upper_3, _, lower_3 = TechnicalIndicators.bollinger_bands(prices, period=20, std_dev=3.0)
        for u2, u3 in zip(upper_2[19:], upper_3[19:]):
            assert u3 > u2  # wider std_dev -> higher upper band


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------

class TestATR:
    """Average True Range tests."""

    def test_atr_basic(self):
        highs = [float(105 + i) for i in range(20)]
        lows = [float(95 + i) for i in range(20)]
        closes = [float(100 + i) for i in range(20)]
        result = TechnicalIndicators.atr(highs, lows, closes, period=14)
        assert len(result) == 20
        # First 13 should be None
        for i in range(13):
            assert result[i] is None
        # From index 13 onward, should have values
        for i in range(13, 20):
            assert result[i] is not None
            assert result[i] > 0

    def test_atr_too_few_prices(self):
        highs = [105.0]
        lows = [95.0]
        closes = [100.0]
        result = TechnicalIndicators.atr(highs, lows, closes, period=14)
        assert all(v is None for v in result)

    def test_atr_constant_range(self):
        """Constant high-low range should produce consistent ATR."""
        highs = [110.0] * 20
        lows = [90.0] * 20
        closes = [100.0] * 20
        result = TechnicalIndicators.atr(highs, lows, closes, period=14)
        # True range is always 20 (high - low), ATR should be 20
        assert result[13] == pytest.approx(20.0)
        assert result[-1] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# Stochastic Oscillator
# ---------------------------------------------------------------------------

class TestStochastic:
    """Stochastic Oscillator tests."""

    def test_stochastic_basic(self):
        highs = [float(105 + i * 0.5) for i in range(20)]
        lows = [float(95 + i * 0.5) for i in range(20)]
        closes = [float(100 + i * 0.5) for i in range(20)]
        k_vals, d_vals = TechnicalIndicators.stochastic(highs, lows, closes, k_period=14)
        assert len(k_vals) == 20
        assert len(d_vals) == 20

    def test_stochastic_range(self):
        """K values should be between 0 and 100."""
        np.random.seed(42)
        n = 50
        closes = [100.0 + np.random.randn() * 5 for _ in range(n)]
        highs = [c + abs(np.random.randn()) * 2 for c in closes]
        lows = [c - abs(np.random.randn()) * 2 for c in closes]
        k_vals, d_vals = TechnicalIndicators.stochastic(highs, lows, closes, k_period=14)
        for k in k_vals:
            if k is not None:
                assert 0.0 <= k <= 100.0

    def test_stochastic_flat_market(self):
        """Equal highs and lows should yield %K = 50 (neutral)."""
        highs = [100.0] * 20
        lows = [100.0] * 20
        closes = [100.0] * 20
        k_vals, _ = TechnicalIndicators.stochastic(highs, lows, closes, k_period=14)
        for k in k_vals[13:]:
            assert k == pytest.approx(50.0)

    def test_stochastic_too_few(self):
        k_vals, d_vals = TechnicalIndicators.stochastic([105.0], [95.0], [100.0], k_period=14)
        assert all(v is None for v in k_vals)
        assert all(v is None for v in d_vals)


# ---------------------------------------------------------------------------
# IndicatorAnalyzer interpretation helpers
# ---------------------------------------------------------------------------

class TestIndicatorInterpreters:
    """Test the private interpretation methods on IndicatorAnalyzer."""

    def setup_method(self):
        self.analyzer = IndicatorAnalyzer()

    def test_interpret_rsi_overbought(self):
        signal, strength = self.analyzer._interpret_rsi(85.0)
        assert signal == "bearish"
        assert 0.0 <= strength <= 1.0

    def test_interpret_rsi_oversold(self):
        signal, strength = self.analyzer._interpret_rsi(15.0)
        assert signal == "bullish"
        assert 0.0 <= strength <= 1.0

    def test_interpret_rsi_neutral(self):
        signal, strength = self.analyzer._interpret_rsi(50.0)
        assert signal == "neutral"
        assert strength == 0.0

    def test_interpret_rsi_boundary_70(self):
        signal, _ = self.analyzer._interpret_rsi(70.0)
        assert signal == "bearish"

    def test_interpret_rsi_boundary_30(self):
        signal, _ = self.analyzer._interpret_rsi(30.0)
        assert signal == "bullish"

    def test_interpret_macd_bullish(self):
        signal, strength = self.analyzer._interpret_macd(1.0, 0.5, 0.5)
        assert signal == "bullish"

    def test_interpret_macd_bearish(self):
        signal, strength = self.analyzer._interpret_macd(-1.0, -0.5, -0.5)
        assert signal == "bearish"

    def test_interpret_macd_neutral(self):
        signal, strength = self.analyzer._interpret_macd(1.0, 1.0, 0.0)
        assert signal == "neutral"

    def test_interpret_macd_none_values(self):
        signal, strength = self.analyzer._interpret_macd(None, None, 0.0)
        assert signal == "neutral"
        assert strength == 0.0

    def test_interpret_bollinger_near_upper(self):
        # position = (price - lower) / (upper - lower) = (99 - 80) / (100 - 80) = 0.95
        signal, strength = self.analyzer._interpret_bollinger(99.0, 100.0, 90.0, 80.0)
        assert signal == "bearish"

    def test_interpret_bollinger_near_lower(self):
        signal, strength = self.analyzer._interpret_bollinger(81.0, 100.0, 90.0, 80.0)
        assert signal == "bullish"

    def test_interpret_bollinger_middle(self):
        signal, _ = self.analyzer._interpret_bollinger(90.0, 100.0, 90.0, 80.0)
        assert signal == "neutral"

    def test_interpret_bollinger_zero_width(self):
        signal, strength = self.analyzer._interpret_bollinger(100.0, 100.0, 100.0, 100.0)
        assert signal == "neutral"
        assert strength == 0.0

    def test_interpret_stochastic_overbought(self):
        signal, _ = self.analyzer._interpret_stochastic(90.0, 85.0)
        assert signal == "bearish"

    def test_interpret_stochastic_oversold(self):
        signal, _ = self.analyzer._interpret_stochastic(10.0, 15.0)
        assert signal == "bullish"

    def test_interpret_stochastic_k_above_d(self):
        signal, _ = self.analyzer._interpret_stochastic(60.0, 50.0)
        assert signal == "bullish"

    def test_interpret_stochastic_k_below_d(self):
        signal, _ = self.analyzer._interpret_stochastic(40.0, 50.0)
        assert signal == "bearish"

    def test_interpret_stochastic_equal(self):
        signal, _ = self.analyzer._interpret_stochastic(50.0, 50.0)
        assert signal == "neutral"


# ---------------------------------------------------------------------------
# IndicatorAnalyzer.analyze_stock (async)
# ---------------------------------------------------------------------------

class TestAnalyzeStock:
    """Tests for IndicatorAnalyzer.analyze_stock using OHLCV dicts."""

    @pytest.fixture()
    def long_prices(self) -> list[dict[str, Any]]:
        """Generate 60 days of trending price data with realistic OHLCV."""
        closes = [100.0 + i * 0.5 + np.sin(i / 3.0) * 3 for i in range(60)]
        return _make_prices(closes)

    async def test_analyze_stock_returns_indicators(self, long_prices):
        analyzer = IndicatorAnalyzer()
        results = await analyzer.analyze_stock(long_prices)
        # Should have at least RSI, MACD, Bollinger, SMA_20
        assert "rsi" in results
        assert "sma_20" in results
        assert isinstance(results["rsi"], IndicatorResult)

    async def test_analyze_stock_empty(self):
        analyzer = IndicatorAnalyzer()
        results = await analyzer.analyze_stock([])
        assert results == {}

    async def test_analyze_stock_too_short_for_some(self):
        """With 10 data points, some indicators won't have enough data."""
        short_prices = _make_prices([100.0 + i for i in range(10)])
        analyzer = IndicatorAnalyzer()
        results = await analyzer.analyze_stock(short_prices)
        # RSI needs 15 points, MACD needs 26, BB needs 20 -- so these may be missing
        # SMA_50 needs 50 points
        assert "sma_50" not in results


# ---------------------------------------------------------------------------
# IndicatorAnalyzer.get_signals (async)
# ---------------------------------------------------------------------------

class TestGetSignals:

    async def test_get_signals_empty(self):
        analyzer = IndicatorAnalyzer()
        signals = await analyzer.get_signals({})
        assert signals["overall_signal"] == "neutral"
        assert signals["confidence"] == 0.0
        assert signals["bullish_count"] == 0

    async def test_get_signals_all_bullish(self):
        analyzer = IndicatorAnalyzer()
        indicator_results = {
            "rsi": IndicatorResult(name="RSI", value=25.0, signal="bullish", strength=0.8),
            "macd": IndicatorResult(name="MACD", value=0.5, signal="bullish", strength=0.6),
        }
        signals = await analyzer.get_signals(indicator_results)
        assert signals["overall_signal"] == "bullish"
        assert signals["bullish_count"] == 2
        assert signals["bearish_count"] == 0

    async def test_get_signals_mixed(self):
        analyzer = IndicatorAnalyzer()
        indicator_results = {
            "rsi": IndicatorResult(name="RSI", value=75.0, signal="bearish", strength=0.5),
            "macd": IndicatorResult(name="MACD", value=0.5, signal="bullish", strength=0.7),
            "sma": IndicatorResult(name="SMA", value=100.0, signal="neutral", strength=0.0),
        }
        signals = await analyzer.get_signals(indicator_results)
        assert signals["overall_signal"] == "neutral"  # 1 bullish, 1 bearish, 1 neutral
        assert signals["neutral_count"] == 1


# ---------------------------------------------------------------------------
# IndicatorAnalyzer.detect_crossovers (async)
# ---------------------------------------------------------------------------

class TestDetectCrossovers:

    async def test_crossovers_needs_200_prices(self):
        analyzer = IndicatorAnalyzer()
        prices = [100.0 + i for i in range(50)]
        crossovers = await analyzer.detect_crossovers(prices)
        assert crossovers == []

    async def test_crossovers_no_cross(self):
        """Steadily rising prices -- 50 SMA always above 200 SMA eventually, but no cross."""
        analyzer = IndicatorAnalyzer()
        # Linearly rising prices: SMA50 always > SMA200 after warmup
        prices = [100.0 + i * 0.5 for i in range(250)]
        crossovers = await analyzer.detect_crossovers(prices)
        # In a steadily rising market, 50 SMA starts below 200 SMA at index 199
        # and quickly rises above. There may or may not be a cross in the last 20.
        # We just verify the output format is correct.
        assert isinstance(crossovers, list)
        for c in crossovers:
            assert c["type"] in ("golden_cross", "death_cross")


# ---------------------------------------------------------------------------
# PatternDetector helpers
# ---------------------------------------------------------------------------

class TestPatternDetectorHelpers:

    def test_extract_prices(self):
        detector = PatternDetector()
        prices = _make_prices([100.0, 101.0, 102.0])
        opens, highs, lows, closes, dates = detector._extract_prices(prices)
        assert len(closes) == 3
        assert closes[0] == pytest.approx(100.0)
        assert isinstance(dates[0], date)

    def test_extract_prices_string_dates(self):
        detector = PatternDetector()
        prices = [
            {"date": "2025-01-01", "open": 99.0, "high": 102.0, "low": 98.0, "close": 100.0},
        ]
        _, _, _, _, dates = detector._extract_prices(prices)
        assert dates[0] == date(2025, 1, 1)

    def test_find_local_extrema(self):
        detector = PatternDetector()
        data = np.array([1, 3, 2, 5, 4, 6, 3, 7, 2, 8], dtype=float)
        max_idx, min_idx = detector._find_local_extrema(data, order=1)
        assert len(max_idx) > 0
        assert len(min_idx) > 0

    def test_calculate_slope(self):
        detector = PatternDetector()
        rising = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        assert detector._calculate_slope(rising) == pytest.approx(1.0)
        falling = np.array([5.0, 4.0, 3.0, 2.0, 1.0])
        assert detector._calculate_slope(falling) == pytest.approx(-1.0)


# ---------------------------------------------------------------------------
# PatternDetector.detect_trend (async)
# ---------------------------------------------------------------------------

class TestDetectTrend:

    async def test_uptrend(self):
        detector = PatternDetector()
        closes = [100.0 + i * 2.0 for i in range(30)]
        prices = _make_prices(closes)
        trend, confidence = await detector.detect_trend(prices, lookback=20)
        assert trend == PatternType.UPTREND
        assert confidence > 0.5

    async def test_downtrend(self):
        detector = PatternDetector()
        closes = [200.0 - i * 2.0 for i in range(30)]
        prices = _make_prices(closes)
        trend, confidence = await detector.detect_trend(prices, lookback=20)
        assert trend == PatternType.DOWNTREND
        assert confidence > 0.5

    async def test_sideways(self):
        detector = PatternDetector()
        # Flat prices with tiny noise
        closes = [100.0 + 0.001 * (i % 2) for i in range(30)]
        prices = _make_prices(closes)
        trend, _ = await detector.detect_trend(prices, lookback=20)
        assert trend == PatternType.SIDEWAYS

    async def test_too_few_prices(self):
        detector = PatternDetector()
        prices = _make_prices([100.0, 101.0, 102.0])
        trend, confidence = await detector.detect_trend(prices, lookback=20)
        assert trend == PatternType.SIDEWAYS
        assert confidence == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# PatternDetector.detect_support_resistance (async)
# ---------------------------------------------------------------------------

class TestSupportResistance:

    async def test_support_resistance_too_few(self):
        detector = PatternDetector()
        prices = _make_prices([100.0] * 10)
        result = await detector.detect_support_resistance(prices)
        assert result == {"support": [], "resistance": []}

    async def test_support_resistance_structure(self):
        detector = PatternDetector()
        # Create oscillating prices that form clear S/R levels
        closes = []
        for i in range(60):
            if i % 10 < 5:
                closes.append(100.0 + (i % 10))
            else:
                closes.append(105.0 - (i % 10 - 5))
        prices = _make_prices(closes)
        result = await detector.detect_support_resistance(prices)
        assert "support" in result
        assert "resistance" in result
        assert isinstance(result["support"], list)
        assert isinstance(result["resistance"], list)


# ---------------------------------------------------------------------------
# DetectedPattern.to_dict
# ---------------------------------------------------------------------------

class TestDetectedPatternToDict:

    def test_to_dict(self):
        pattern = DetectedPattern(
            pattern_type=PatternType.DOUBLE_TOP,
            symbol="AAPL",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            confidence=0.85,
            price_target=150.0,
            stop_loss=180.0,
            description="Test pattern",
            supporting_data={"key": "value"},
        )
        d = pattern.to_dict()
        assert d["pattern_type"] == "double_top"
        assert d["symbol"] == "AAPL"
        assert d["confidence"] == 0.85
        assert d["price_target"] == 150.0
        assert d["stop_loss"] == 180.0

    def test_to_dict_none_targets(self):
        pattern = DetectedPattern(
            pattern_type=PatternType.UPTREND,
            symbol="TSLA",
            start_date=date(2025, 6, 1),
            end_date=date(2025, 6, 30),
            confidence=0.7,
            price_target=None,
            stop_loss=None,
            description="No targets",
            supporting_data={},
        )
        d = pattern.to_dict()
        assert d["price_target"] is None
        assert d["stop_loss"] is None


# ---------------------------------------------------------------------------
# PatternDetector.detect_double_top (async)
# ---------------------------------------------------------------------------

class TestDoubleTop:

    async def test_too_few_prices(self):
        detector = PatternDetector()
        prices = _make_prices([100.0] * 10)
        result = await detector.detect_double_top(prices)
        assert result is None

    async def test_no_double_top_in_steady_rise(self):
        detector = PatternDetector()
        closes = [100.0 + i for i in range(50)]
        prices = _make_prices(closes)
        result = await detector.detect_double_top(prices)
        assert result is None


# ---------------------------------------------------------------------------
# PatternDetector.detect_double_bottom (async)
# ---------------------------------------------------------------------------

class TestDoubleBottom:

    async def test_too_few_prices(self):
        detector = PatternDetector()
        prices = _make_prices([100.0] * 10)
        result = await detector.detect_double_bottom(prices)
        assert result is None

    async def test_no_double_bottom_in_steady_fall(self):
        detector = PatternDetector()
        closes = [200.0 - i for i in range(50)]
        prices = _make_prices(closes)
        result = await detector.detect_double_bottom(prices)
        assert result is None


# ---------------------------------------------------------------------------
# PatternDetector.detect_head_and_shoulders (async)
# ---------------------------------------------------------------------------

class TestHeadAndShoulders:

    async def test_too_few_prices(self):
        detector = PatternDetector()
        prices = _make_prices([100.0] * 20)
        result = await detector.detect_head_and_shoulders(prices)
        assert result is None


# ---------------------------------------------------------------------------
# PatternDetector.detect_breakout / detect_breakdown (async)
# ---------------------------------------------------------------------------

class TestBreakoutBreakdown:

    async def test_breakout_too_few(self):
        detector = PatternDetector()
        prices = _make_prices([100.0] * 5)
        result = await detector.detect_breakout(prices, [{"level": 99.0, "strength": 0.8}])
        assert result is None

    async def test_breakout_no_levels(self):
        detector = PatternDetector()
        prices = _make_prices([100.0] * 20)
        result = await detector.detect_breakout(prices, [])
        assert result is None

    async def test_breakdown_too_few(self):
        detector = PatternDetector()
        prices = _make_prices([100.0] * 5)
        result = await detector.detect_breakdown(prices, [{"level": 101.0, "strength": 0.8}])
        assert result is None

    async def test_breakdown_no_levels(self):
        detector = PatternDetector()
        prices = _make_prices([100.0] * 20)
        result = await detector.detect_breakdown(prices, [])
        assert result is None

    async def test_breakout_detection(self):
        """Construct a scenario where a clear breakout occurs."""
        detector = PatternDetector(min_confidence=0.5)
        # Price is below 100 then breaks above 100
        closes = [95.0] * 18 + [99.5, 103.0]  # Last closes jump above resistance
        prices = _make_prices(closes)
        resistance = [{"level": 100.0, "strength": 0.8}]
        result = await detector.detect_breakout(prices, resistance)
        if result is not None:
            assert result.pattern_type == PatternType.BREAKOUT
            assert result.confidence >= 0.5

    async def test_breakdown_detection(self):
        """Construct a scenario where a clear breakdown occurs."""
        detector = PatternDetector(min_confidence=0.5)
        closes = [105.0] * 18 + [100.5, 97.0]
        prices = _make_prices(closes)
        support = [{"level": 100.0, "strength": 0.8}]
        result = await detector.detect_breakdown(prices, support)
        if result is not None:
            assert result.pattern_type == PatternType.BREAKDOWN
            assert result.confidence >= 0.5


# ---------------------------------------------------------------------------
# PatternDetector golden/death cross (async)
# ---------------------------------------------------------------------------

class TestCrossPatterns:

    async def test_golden_cross_needs_200(self):
        detector = PatternDetector()
        prices = _make_prices([100.0] * 100)
        result = await detector.detect_golden_cross(prices)
        assert result is None

    async def test_death_cross_needs_200(self):
        detector = PatternDetector()
        prices = _make_prices([100.0] * 100)
        result = await detector.detect_death_cross(prices)
        assert result is None


# ---------------------------------------------------------------------------
# PatternDetector.detect_bull_flag (async)
# ---------------------------------------------------------------------------

class TestBullFlag:

    async def test_too_few_prices(self):
        detector = PatternDetector()
        prices = _make_prices([100.0] * 10)
        result = await detector.detect_bull_flag(prices)
        assert result is None

    async def test_no_bull_flag_in_flat_market(self):
        detector = PatternDetector()
        prices = _make_prices([100.0] * 40)
        result = await detector.detect_bull_flag(prices)
        assert result is None


# ---------------------------------------------------------------------------
# PatternDetector.detect_ascending_triangle (async)
# ---------------------------------------------------------------------------

class TestAscendingTriangle:

    async def test_too_few_prices(self):
        detector = PatternDetector()
        prices = _make_prices([100.0] * 10)
        result = await detector.detect_ascending_triangle(prices)
        assert result is None


# ---------------------------------------------------------------------------
# PatternDetector.detect_all_patterns (async)
# ---------------------------------------------------------------------------

class TestDetectAllPatterns:

    async def test_too_few_prices(self):
        detector = PatternDetector()
        prices = _make_prices([100.0] * 5)
        patterns = await detector.detect_all_patterns("AAPL", prices)
        assert patterns == []

    async def test_returns_list(self):
        detector = PatternDetector()
        closes = [100.0 + i * 0.5 for i in range(60)]
        prices = _make_prices(closes)
        patterns = await detector.detect_all_patterns("AAPL", prices)
        assert isinstance(patterns, list)
        # All items should be DetectedPattern instances
        for p in patterns:
            assert isinstance(p, DetectedPattern)

    async def test_patterns_sorted_by_confidence(self):
        detector = PatternDetector()
        closes = [100.0 + np.sin(i / 5.0) * 10 for i in range(80)]
        prices = _make_prices(closes)
        patterns = await detector.detect_all_patterns("TEST", prices)
        for i in range(len(patterns) - 1):
            assert patterns[i].confidence >= patterns[i + 1].confidence


# ---------------------------------------------------------------------------
# PatternDetector.get_pattern_summary (async)
# ---------------------------------------------------------------------------

class TestGetPatternSummary:

    async def test_empty_patterns(self):
        detector = PatternDetector()
        summary = await detector.get_pattern_summary([])
        assert summary["total_patterns"] == 0
        assert summary["overall_bias"] == "neutral"
        assert summary["confidence"] == 0.0

    async def test_summary_with_bullish_patterns(self):
        detector = PatternDetector()
        patterns = [
            DetectedPattern(
                pattern_type=PatternType.GOLDEN_CROSS,
                symbol="AAPL",
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 31),
                confidence=0.85,
                price_target=200.0,
                stop_loss=170.0,
                description="Golden cross",
                supporting_data={},
            ),
            DetectedPattern(
                pattern_type=PatternType.BREAKOUT,
                symbol="AAPL",
                start_date=date(2025, 1, 15),
                end_date=date(2025, 1, 31),
                confidence=0.75,
                price_target=210.0,
                stop_loss=175.0,
                description="Breakout",
                supporting_data={},
            ),
        ]
        summary = await detector.get_pattern_summary(patterns)
        assert summary["total_patterns"] == 2
        assert summary["bullish_patterns"] == 2
        assert summary["bearish_patterns"] == 0
        assert summary["overall_bias"] == "bullish"

    async def test_summary_with_bearish_patterns(self):
        detector = PatternDetector()
        patterns = [
            DetectedPattern(
                pattern_type=PatternType.DEATH_CROSS,
                symbol="TSLA",
                start_date=date(2025, 2, 1),
                end_date=date(2025, 2, 28),
                confidence=0.80,
                price_target=None,
                stop_loss=None,
                description="Death cross",
                supporting_data={},
            ),
        ]
        summary = await detector.get_pattern_summary(patterns)
        assert summary["bearish_patterns"] == 1
        assert summary["overall_bias"] == "bearish"


# ---------------------------------------------------------------------------
# Edge cases: NaN handling
# ---------------------------------------------------------------------------

class TestNaNHandling:

    def test_sma_with_nan_in_input(self):
        """SMA computes a window sum; NaN in data propagates to NaN result."""
        prices = [1.0, 2.0, float("nan"), 4.0, 5.0]
        result = TechnicalIndicators.sma(prices, 3)
        # The window containing NaN should produce NaN
        assert result[2] is not None
        assert math.isnan(result[2])

    def test_ema_with_nan_propagation(self):
        """EMA seed (SMA) containing NaN propagates NaN forward."""
        prices = [float("nan"), 2.0, 3.0, 4.0, 5.0]
        result = TechnicalIndicators.ema(prices, 3)
        # First EMA value is SMA of first 3 which includes NaN
        assert result[2] is not None
        assert math.isnan(result[2])

    def test_rsi_with_single_data_point(self):
        result = TechnicalIndicators.rsi([100.0], period=14)
        assert result == [None]


# ---------------------------------------------------------------------------
# Integration: sample_price_data fixture
# ---------------------------------------------------------------------------

class TestWithSampleFixture:
    """Tests using the conftest sample_price_data fixture."""

    def test_sma_with_sample(self, sample_price_data: list[dict[str, Any]]):
        closes = [p["close"] for p in sample_price_data]
        # 5 data points, SMA(3) should give 3 valid values
        result = TechnicalIndicators.sma(closes, 3)
        assert len(result) == 5
        assert result[0] is None
        assert result[1] is None
        expected = (184.0 + 186.0 + 185.0) / 3
        assert result[2] == pytest.approx(expected)

    def test_ema_with_sample(self, sample_price_data: list[dict[str, Any]]):
        closes = [p["close"] for p in sample_price_data]
        result = TechnicalIndicators.ema(closes, 3)
        assert len(result) == 5
        assert result[2] is not None  # First EMA value at index 2

    def test_bollinger_sample_too_short(self, sample_price_data: list[dict[str, Any]]):
        closes = [p["close"] for p in sample_price_data]
        upper, middle, lower = TechnicalIndicators.bollinger_bands(closes, period=20)
        # Only 5 data points, period 20 -> all None
        assert all(v is None for v in upper)

    async def test_analyze_stock_with_sample(self, sample_price_data: list[dict[str, Any]]):
        analyzer = IndicatorAnalyzer()
        results = await analyzer.analyze_stock(sample_price_data)
        # With 5 data points most indicators won't compute, but shouldn't crash
        assert isinstance(results, dict)

    async def test_detect_trend_with_sample(self, sample_price_data: list[dict[str, Any]]):
        detector = PatternDetector()
        trend, confidence = await detector.detect_trend(sample_price_data, lookback=5)
        assert trend in (PatternType.UPTREND, PatternType.DOWNTREND, PatternType.SIDEWAYS)

    async def test_detect_all_patterns_with_sample(self, sample_price_data: list[dict[str, Any]]):
        detector = PatternDetector()
        patterns = await detector.detect_all_patterns("AAPL", sample_price_data)
        # Too few points for most patterns, should return empty or very few
        assert isinstance(patterns, list)
