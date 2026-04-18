"""Tests for sector relative strength momentum system."""

import pytest

from analysis.agents.heatmap_interfaces import SectorHeatmapEntry
from analysis.sector_momentum import (
    SectorMomentumData,
    SECTOR_ETF_NAMES,
    WEIGHT_1W,
    WEIGHT_1M,
    WEIGHT_3M,
    compute_sector_momentum_from_heatmap,
    format_momentum_table,
    _assign_ranks_and_signals,
)


# =============================================================================
# Helpers
# =============================================================================


def make_sector(etf: str, change_1d=0.0, change_5d=0.0, change_20d=0.0, change_60d=None):
    name = SECTOR_ETF_NAMES.get(etf, etf)
    return SectorHeatmapEntry(
        name=name,
        etf=etf,
        change_1d=change_1d,
        change_5d=change_5d,
        change_20d=change_20d,
        change_60d=change_60d,
    )


def make_spy(change_5d=0.0, change_20d=0.0, change_60d=None):
    entry = SectorHeatmapEntry(name="S&P 500", etf="SPY")
    entry.change_5d = change_5d
    entry.change_20d = change_20d
    entry.change_60d = change_60d
    return entry


# =============================================================================
# compute_sector_momentum_from_heatmap
# =============================================================================


class TestComputeSectorMomentumFromHeatmap:
    def test_returns_all_sectors_with_data(self):
        sectors = [make_spy()] + [make_sector(etf) for etf in SECTOR_ETF_NAMES]
        result = compute_sector_momentum_from_heatmap(sectors)
        assert len(result) == len(SECTOR_ETF_NAMES)

    def test_missing_sectors_skipped(self):
        # Only 3 sectors + SPY
        sectors = [make_spy(), make_sector("XLK"), make_sector("XLF"), make_sector("XLE")]
        result = compute_sector_momentum_from_heatmap(sectors)
        assert len(result) == 3

    def test_relative_strength_computation(self):
        """RS should be sector return minus SPY return."""
        spy = make_spy(change_5d=1.0, change_20d=2.0)
        xlk = make_sector("XLK", change_5d=3.0, change_20d=5.0)
        result = compute_sector_momentum_from_heatmap([spy, xlk])
        assert len(result) == 1
        data = result[0]
        assert data.rs_1w == pytest.approx(2.0)   # 3.0 - 1.0
        assert data.rs_1m == pytest.approx(3.0)   # 5.0 - 2.0

    def test_momentum_score_with_3m(self):
        """Score = 0.2*rs_1w + 0.4*rs_1m + 0.4*rs_3m when 3M available."""
        spy = make_spy(change_5d=1.0, change_20d=2.0, change_60d=3.0)
        xlk = make_sector("XLK", change_5d=3.0, change_20d=6.0, change_60d=9.0)
        result = compute_sector_momentum_from_heatmap([spy, xlk])
        data = result[0]
        expected = WEIGHT_1W * 2.0 + WEIGHT_1M * 4.0 + WEIGHT_3M * 6.0
        assert data.momentum_score == pytest.approx(expected, abs=0.01)

    def test_momentum_score_without_3m(self):
        """When 3M missing, fallback to 1W/1M-only weights."""
        spy = make_spy(change_5d=1.0, change_20d=2.0)
        xlk = make_sector("XLK", change_5d=3.0, change_20d=6.0)
        result = compute_sector_momentum_from_heatmap([spy, xlk])
        data = result[0]
        # Fallback: 0.33*rs_1w + 0.67*rs_1m
        expected = 0.33 * 2.0 + 0.67 * 4.0
        assert data.momentum_score == pytest.approx(expected, abs=0.05)

    def test_sorted_by_score_descending(self):
        spy = make_spy()
        sectors = [
            make_sector("XLU", change_20d=-5.0),
            make_sector("XLK", change_20d=8.0),
            make_sector("XLF", change_20d=2.0),
        ]
        result = compute_sector_momentum_from_heatmap([spy] + sectors)
        scores = [d.momentum_score for d in result]
        assert scores == sorted(scores, reverse=True)

    def test_rank_assignment(self):
        spy = make_spy()
        sectors = [make_sector(etf, change_20d=float(i)) for i, etf in enumerate(["XLK", "XLF", "XLE"])]
        result = compute_sector_momentum_from_heatmap([spy] + sectors)
        ranks = [d.rank for d in result]
        assert sorted(ranks) == [1, 2, 3]

    def test_no_spy_fallback(self):
        """Without SPY, uses sector average as benchmark — still returns data."""
        sectors = [make_sector("XLK", change_20d=5.0), make_sector("XLF", change_20d=-3.0)]
        result = compute_sector_momentum_from_heatmap(sectors)
        assert len(result) == 2

    def test_empty_sectors_returns_empty(self):
        result = compute_sector_momentum_from_heatmap([])
        assert result == []


# =============================================================================
# _assign_ranks_and_signals
# =============================================================================


class TestAssignRanksAndSignals:
    def _make_data(self, scores: list[float]) -> list[SectorMomentumData]:
        etfs = list(SECTOR_ETF_NAMES.keys())
        return [
            SectorMomentumData(
                symbol=etfs[i % len(etfs)],
                sector="Test",
                momentum_score=score,
            )
            for i, score in enumerate(scores)
        ]

    def test_accelerating_signal(self):
        data = self._make_data([3.0])
        result = _assign_ranks_and_signals(data)
        assert result[0].signal == "ACCELERATING"

    def test_steady_signal(self):
        data = self._make_data([1.0])
        result = _assign_ranks_and_signals(data)
        assert result[0].signal == "STEADY"

    def test_decelerating_signal(self):
        data = self._make_data([-0.5])
        result = _assign_ranks_and_signals(data)
        assert result[0].signal == "DECELERATING"

    def test_lagging_signal(self):
        data = self._make_data([-2.5])
        result = _assign_ranks_and_signals(data)
        assert result[0].signal == "LAGGING"

    def test_quartile_top(self):
        scores = [4.0, 2.0, 1.0, 0.0, -1.0, -2.0, -3.0, -4.0]
        data = self._make_data(scores)
        result = _assign_ranks_and_signals(data)
        assert result[0].quartile == 1   # top
        assert result[-1].quartile == 4  # bottom

    def test_rank_one_is_highest_score(self):
        data = self._make_data([1.0, 5.0, 3.0])
        result = _assign_ranks_and_signals(data)
        assert result[0].rank == 1
        assert result[0].momentum_score == pytest.approx(5.0)


# =============================================================================
# format_momentum_table
# =============================================================================


class TestFormatMomentumTable:
    def test_empty_returns_empty_string(self):
        assert format_momentum_table([]) == ""

    def test_header_present(self):
        data = [SectorMomentumData(symbol="XLK", sector="Technology", rank=1, rs_1w=1.0, rs_1m=2.0, momentum_score=1.5, signal="STEADY")]
        table = format_momentum_table(data)
        assert "SECTOR MOMENTUM RANKINGS" in table
        assert "XLK" in table

    def test_rotation_signals_section(self):
        accelerating = SectorMomentumData(
            symbol="XLK", sector="Technology", rank=1,
            rs_1w=3.0, rs_1m=4.0, momentum_score=3.5, signal="ACCELERATING",
        )
        lagging = SectorMomentumData(
            symbol="XLU", sector="Utilities", rank=11,
            rs_1w=-3.0, rs_1m=-4.0, momentum_score=-4.0, signal="LAGGING",
        )
        table = format_momentum_table([accelerating, lagging])
        assert "ROTATION SIGNALS" in table
        assert "XLK" in table
        assert "XLU" in table

    def test_no_rotation_section_when_all_steady(self):
        data = [
            SectorMomentumData(
                symbol="XLK", sector="Technology", rank=1,
                rs_1w=0.5, rs_1m=1.0, momentum_score=0.8, signal="STEADY",
            )
        ]
        table = format_momentum_table(data)
        assert "ROTATION SIGNALS" not in table

    def test_3m_column_present_when_rs_3m_set(self):
        data = [
            SectorMomentumData(
                symbol="XLK", sector="Technology", rank=1,
                rs_1w=1.0, rs_1m=2.0, rs_3m=3.0, momentum_score=2.0, signal="ACCELERATING",
            )
        ]
        table = format_momentum_table(data)
        assert "3M RS" in table

    def test_3m_column_absent_when_no_rs_3m(self):
        data = [
            SectorMomentumData(
                symbol="XLK", sector="Technology", rank=1,
                rs_1w=1.0, rs_1m=2.0, rs_3m=0.0, momentum_score=1.5, signal="STEADY",
            )
        ]
        table = format_momentum_table(data)
        assert "3M RS" not in table


# =============================================================================
# SectorHeatmapEntry change_60d field
# =============================================================================


class TestSectorHeatmapEntryChange60d:
    def test_default_is_none(self):
        entry = SectorHeatmapEntry(name="Technology", etf="XLK")
        assert entry.change_60d is None

    def test_set_and_serialise(self):
        entry = SectorHeatmapEntry(name="Technology", etf="XLK", change_60d=5.5)
        d = entry.to_dict()
        assert "change_60d" in d
        assert d["change_60d"] == pytest.approx(5.5)

    def test_none_not_serialised(self):
        entry = SectorHeatmapEntry(name="Technology", etf="XLK", change_60d=None)
        d = entry.to_dict()
        assert "change_60d" not in d

    def test_from_dict_with_change_60d(self):
        d = {"name": "Technology", "etf": "XLK", "change_60d": 7.25}
        entry = SectorHeatmapEntry.from_dict(d)
        assert entry.change_60d == pytest.approx(7.25)

    def test_from_dict_without_change_60d(self):
        d = {"name": "Technology", "etf": "XLK"}
        entry = SectorHeatmapEntry.from_dict(d)
        assert entry.change_60d is None
