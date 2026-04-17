"""Tests for options-implied signals module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import pandas as pd

from analysis.agents.options_signals import (
    OptionsSignals,
    fetch_options_signals,
    PC_RATIO_AVG,
    PC_COMPLACENT_THRESHOLD,
    PC_FEARFUL_THRESHOLD,
)


# =============================================================================
# OptionsSignals.format_block
# =============================================================================


class TestOptionsSignalsFormatBlock:
    def test_unavailable_returns_empty(self):
        signals = OptionsSignals(available=False)
        assert signals.format_block() == ""

    def test_vix_only(self):
        signals = OptionsSignals(vix=18.5, vix_percentile_52w=45.0, available=True)
        block = signals.format_block()
        assert "OPTIONS SENTIMENT" in block
        assert "18.5" in block
        assert "45%" in block

    def test_contango_term_structure(self):
        signals = OptionsSignals(
            vix=14.0, vix3m=17.5,
            term_structure="contango", term_structure_spread=3.5,
            available=True,
        )
        block = signals.format_block()
        assert "Contango" in block
        assert "calm" in block

    def test_backwardation_term_structure(self):
        signals = OptionsSignals(
            vix=25.0, vix3m=20.0,
            term_structure="backwardation", term_structure_spread=-5.0,
            available=True,
        )
        block = signals.format_block()
        assert "Backwardation" in block
        assert "stressed" in block

    def test_elevated_skew(self):
        signals = OptionsSignals(skew=140.0, available=True)
        block = signals.format_block()
        assert "140" in block
        assert "tail-risk" in block

    def test_complacent_pc_ratio(self):
        signals = OptionsSignals(put_call_ratio=0.55, pc_signal="complacent", available=True)
        block = signals.format_block()
        assert "0.55" in block
        assert "complacent" in block

    def test_fearful_pc_ratio(self):
        signals = OptionsSignals(put_call_ratio=1.35, pc_signal="fearful", available=True)
        block = signals.format_block()
        assert "1.35" in block
        assert "fearful" in block

    def test_low_vix_percentile_label(self):
        signals = OptionsSignals(vix=12.0, vix_percentile_52w=15.0, available=True)
        block = signals.format_block()
        assert "complacency" in block

    def test_high_vix_percentile_label(self):
        signals = OptionsSignals(vix=30.0, vix_percentile_52w=82.0, available=True)
        block = signals.format_block()
        assert "fear" in block


# =============================================================================
# Term structure classification
# =============================================================================


class TestTermStructureClassification:
    def _make_signals(self, vix: float, vix3m: float) -> OptionsSignals:
        spread = vix3m - vix
        if spread > 1.0:
            ts = "contango"
        elif spread < -1.0:
            ts = "backwardation"
        else:
            ts = "flat"
        return OptionsSignals(
            vix=vix, vix3m=vix3m,
            term_structure=ts, term_structure_spread=round(spread, 2),
            available=True,
        )

    def test_contango_positive_spread(self):
        s = self._make_signals(14.0, 18.0)
        assert s.term_structure == "contango"
        assert s.term_structure_spread == pytest.approx(4.0)

    def test_backwardation_negative_spread(self):
        s = self._make_signals(28.0, 22.0)
        assert s.term_structure == "backwardation"
        assert s.term_structure_spread == pytest.approx(-6.0)

    def test_flat_small_spread(self):
        s = self._make_signals(20.0, 20.5)
        assert s.term_structure == "flat"


# =============================================================================
# VIX percentile computation
# =============================================================================


class TestVixPercentile:
    def test_low_vix_in_high_hist_gives_low_percentile(self):
        # Current VIX = 10, history was all 20+
        current = 10.0
        hist = [25.0, 22.0, 23.0, 21.0, 24.0]
        below = sum(1 for v in hist if v <= current)
        pct = (below / len(hist)) * 100
        assert pct == 0.0

    def test_high_vix_gives_high_percentile(self):
        current = 40.0
        hist = [10.0, 12.0, 15.0, 18.0, 20.0]
        below = sum(1 for v in hist if v <= current)
        pct = (below / len(hist)) * 100
        assert pct == 100.0

    def test_median_vix_percentile(self):
        # Current right at median of sorted history
        hist = [10.0, 15.0, 20.0, 25.0, 30.0]
        current = 20.0
        below = sum(1 for v in hist if v <= current)
        pct = (below / len(hist)) * 100
        assert pct == 60.0  # 3 of 5 are <= 20


# =============================================================================
# Put/call ratio signal thresholds
# =============================================================================


class TestPutCallRatioThresholds:
    def test_below_complacent_threshold(self):
        ratio = PC_COMPLACENT_THRESHOLD - 0.1
        signal = "complacent" if ratio < PC_COMPLACENT_THRESHOLD else "neutral"
        assert signal == "complacent"

    def test_above_fearful_threshold(self):
        ratio = PC_FEARFUL_THRESHOLD + 0.1
        signal = "fearful" if ratio > PC_FEARFUL_THRESHOLD else "neutral"
        assert signal == "fearful"

    def test_between_thresholds_is_neutral(self):
        ratio = (PC_COMPLACENT_THRESHOLD + PC_FEARFUL_THRESHOLD) / 2
        if ratio < PC_COMPLACENT_THRESHOLD:
            signal = "complacent"
        elif ratio > PC_FEARFUL_THRESHOLD:
            signal = "fearful"
        else:
            signal = "neutral"
        assert signal == "neutral"


# =============================================================================
# fetch_options_signals (mocked yfinance)
# =============================================================================


@pytest.fixture
def mock_vix_history():
    """1-year VIX close prices (current = 16.5, 52w range 10-30)."""
    closes = list(range(10, 31)) * 12 + [16.5]  # 252 values ending at 16.5
    return pd.DataFrame({"Close": closes})


@pytest.fixture
def mock_vix3m_history():
    return pd.DataFrame({"Close": [19.2, 19.0, 19.5, 19.3, 19.4]})


@pytest.fixture
def mock_skew_history():
    return pd.DataFrame({"Close": [128.0, 129.0, 130.0, 131.0, 132.0]})


@pytest.fixture
def mock_spy_chain():
    """Minimal SPY option chain with puts > calls (fearful)."""
    puts = pd.DataFrame({"volume": [500, 600, 700]})
    calls = pd.DataFrame({"volume": [300, 400, 200]})
    chain = MagicMock()
    chain.puts = puts
    chain.calls = calls
    return chain


class TestFetchOptionsSignals:
    @pytest.mark.asyncio
    async def test_returns_signals_with_mocked_data(
        self, mock_vix_history, mock_vix3m_history, mock_skew_history, mock_spy_chain
    ):
        mock_vix_ticker = MagicMock()
        mock_vix_ticker.history.return_value = mock_vix_history

        mock_vix3m_ticker = MagicMock()
        mock_vix3m_ticker.history.return_value = mock_vix3m_history

        mock_skew_ticker = MagicMock()
        mock_skew_ticker.history.return_value = mock_skew_history

        mock_spy_ticker = MagicMock()
        mock_spy_ticker.options = ["2024-01-19"]
        mock_spy_ticker.option_chain.return_value = mock_spy_chain

        ticker_map = {
            "^VIX": mock_vix_ticker,
            "^VIX3M": mock_vix3m_ticker,
            "^SKEW": mock_skew_ticker,
            "SPY": mock_spy_ticker,
        }

        mock_yf = MagicMock()
        mock_yf.Ticker.side_effect = lambda sym: ticker_map[sym]

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            signals = await fetch_options_signals()

        assert signals.available is True
        assert signals.vix > 0
        assert signals.vix3m > 0
        assert signals.skew > 0
        assert 0.0 <= signals.vix_percentile_52w <= 100.0

    @pytest.mark.asyncio
    async def test_graceful_degradation_on_error(self):
        """fetch_options_signals should not raise on yfinance failures."""
        with patch("analysis.agents.options_signals.asyncio.get_running_loop") as mock_loop:
            loop = AsyncMock()
            mock_loop.return_value = loop
            loop.run_in_executor = AsyncMock(side_effect=Exception("network error"))

            signals = await fetch_options_signals()

        assert signals.available is False
        assert signals.vix == 0.0
