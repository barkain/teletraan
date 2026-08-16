"""Tests for heatmap price-history fetching and metric computation.

Covers the two audited defects in this module:
  1. A one-month fetch made change_60d unreachable and made change_20d a
     first-bar-to-last-bar change rather than a true 20-session lookback.
  2. A batch download that silently dropped symbols was cached as if complete,
     pinning the truncated set for the full 5-minute TTL.

No network access: ``heatmap_fetcher.yf`` is replaced with an inline fake.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.agents import heatmap_fetcher
from analysis.agents.heatmap_fetcher import (
    DEFAULT_HISTORY_PERIOD,
    BatchDownloadResult,
    SectorHeatmapFetcher,
)
from analysis.agents.heatmap_interfaces import StockHeatmapEntry


# =============================================================================
# Helpers
# =============================================================================


def make_frame(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    """OHLCV frame with the given close series."""
    if volumes is None:
        volumes = [1_000_000.0] * len(closes)
    return pd.DataFrame(
        {"Close": closes, "Volume": volumes},
        index=pd.date_range("2026-01-01", periods=len(closes), freq="B"),
    )


class FakeYF:
    """Stand-in for the yfinance module.

    Knows about a fixed set of symbols; anything else is simply absent from
    the returned frame, which is exactly how yfinance drops bad tickers.
    """

    def __init__(self, frames: dict[str, pd.DataFrame]):
        self.frames = frames
        self.calls: list[tuple[str, ...]] = []

    def download(self, tickers, period, group_by=None, threads=None, progress=None):
        self.calls.append(tuple(tickers))
        available = {s: self.frames[s] for s in tickers if s in self.frames}
        if not available:
            return pd.DataFrame()
        if len(tickers) == 1:
            return available[tickers[0]]
        return pd.concat(
            available.values(), axis=1, keys=list(available.keys())
        )

    def calls_for(self, symbol: str, since: int = 0) -> list[tuple[str, ...]]:
        return [c for c in self.calls[since:] if symbol in c]


@pytest.fixture(autouse=True)
def clear_cache():
    heatmap_fetcher._yf_cache.clear()
    yield
    heatmap_fetcher._yf_cache.clear()


@pytest.fixture
def fetcher() -> SectorHeatmapFetcher:
    return SectorHeatmapFetcher()


# =============================================================================
# A. History depth and true lookbacks
# =============================================================================


class TestComputeMetrics:
    def test_change_20d_is_a_true_20_bar_lookback(self, fetcher):
        """With 40 bars, change_20d must compare against the bar 20 sessions
        back — not against the first bar of whatever history was fetched."""
        closes = [50.0] * 19 + [100.0] * 20 + [110.0]
        assert len(closes) == 40
        assert closes[-21] == 100.0
        assert closes[0] == 50.0

        metrics = fetcher._compute_metrics({"AAA": make_frame(closes)}, "AAA")

        assert metrics is not None
        assert metrics["change_20d"] == pytest.approx(10.0)
        # First-bar-to-last-bar would have been +120%.
        assert metrics["change_20d"] != pytest.approx(120.0)

    def test_lookbacks_absent_when_history_too_short(self, fetcher):
        metrics = fetcher._compute_metrics({"AAA": make_frame([10.0] * 10)}, "AAA")

        assert metrics is not None
        assert "change_5d" in metrics
        assert "change_20d" not in metrics
        assert "change_60d" not in metrics
        assert "volatility_20d" not in metrics
        assert "volume_ratio" not in metrics

    def test_change_60d_requires_61_bars(self, fetcher):
        short = fetcher._compute_metrics({"A": make_frame([10.0] * 60)}, "A")
        long = fetcher._compute_metrics({"A": make_frame([10.0] * 61)}, "A")

        assert short is not None and "change_60d" not in short
        assert long is not None and "change_60d" in long

    def test_default_history_period_supports_a_60_bar_lookback(self):
        # ~126 business days in 6 months, comfortably past the 61 bars
        # change_60d needs; "1mo" (~21) could never reach it.
        assert DEFAULT_HISTORY_PERIOD == "6mo"

    def test_rsi_and_volatility_are_computed_and_kept(self, fetcher):
        closes = [100.0 + (i % 7) - 3 for i in range(40)]
        metrics = fetcher._compute_metrics({"A": make_frame(closes)}, "A")

        assert metrics is not None
        assert 0.0 <= metrics["rsi_14"] <= 100.0
        assert metrics["volatility_20d"] > 0.0

    def test_volume_ratio_uses_a_trailing_20_session_average(self, fetcher):
        volumes = [100.0] * 39 + [200.0]
        metrics = fetcher._compute_metrics(
            {"A": make_frame([10.0] * 40, volumes)}, "A"
        )

        assert metrics is not None
        assert metrics["volume_ratio"] == pytest.approx(2.0)

    def test_missing_symbol_returns_none(self, fetcher):
        assert fetcher._compute_metrics({}, "NOPE") is None


# =============================================================================
# B. Computed fields survive into the entry
# =============================================================================


class TestEntryFields:
    def test_new_metrics_round_trip_through_to_dict(self):
        entry = StockHeatmapEntry(
            symbol="AAA",
            sector="Technology",
            price=100.0,
            change_1d=1.0,
            change_5d=2.0,
            change_20d=3.0,
            change_60d=4.0,
            volume_ratio=1.5,
            market_cap=500.0,
            rsi_14=62.5,
            volatility_20d=24.0,
        )

        payload = entry.to_dict()
        assert payload["rsi_14"] == 62.5
        assert payload["volatility_20d"] == 24.0
        assert payload["change_60d"] == 4.0

        restored = StockHeatmapEntry.from_dict(payload)
        assert restored == entry

    def test_from_dict_loads_a_legacy_payload(self):
        """Payloads persisted in AnalysisTask.supplementary_data before these
        fields existed must still load."""
        legacy = {
            "symbol": "AAPL",
            "sector": "Technology",
            "price": 190.0,
            "change_1d": 0.5,
            "change_5d": 1.2,
            "change_20d": 3.4,
            "volume_ratio": 1.1,
            "market_cap": 2900.0,
        }

        entry = StockHeatmapEntry.from_dict(legacy)

        assert entry.symbol == "AAPL"
        assert entry.change_20d == 3.4
        assert entry.rsi_14 is None
        assert entry.volatility_20d is None
        assert entry.change_60d is None

    def test_unmeasured_metrics_are_omitted_not_zeroed(self):
        entry = StockHeatmapEntry(symbol="NEW", sector="Technology", change_1d=1.0)

        payload = entry.to_dict()

        assert "change_20d" not in payload
        assert "volume_ratio" not in payload
        assert "rsi_14" not in payload
        # A consumer defaulting the key still works; the factor model, which
        # uses .get() without a default, correctly sees the factor as missing.
        assert payload.get("change_20d", 0) == 0


# =============================================================================
# D. Batch completeness
# =============================================================================


class TestBatchDownload:
    async def test_incomplete_batch_is_not_cached_as_complete(
        self, fetcher, monkeypatch
    ):
        """A batch that drops a symbol must retry it, report it as missing,
        and never serve the truncated set back as a cache hit."""
        fake = FakeYF({"AAPL": make_frame([10.0] * 40)})
        monkeypatch.setattr(heatmap_fetcher, "yf", fake)
        monkeypatch.setattr(heatmap_fetcher, "_ERROR_TTL", 0)

        first = await fetcher._batch_download(["AAPL", "ZZZZZZZZ"], period="1mo")

        assert set(first.data) == {"AAPL"}
        assert first.missing == ["ZZZZZZZZ"]
        assert first.retried == ["ZZZZZZZZ"]
        assert not first.is_complete
        assert first.coverage == pytest.approx(0.5)
        # The dropped symbol was retried on its own inside the same call.
        assert fake.calls_for("ZZZZZZZZ")[-1] == ("ZZZZZZZZ",)

        calls_after_first = len(fake.calls)
        second = await fetcher._batch_download(["AAPL", "ZZZZZZZZ"], period="1mo")

        # The good symbol comes from the per-symbol cache...
        assert second.from_cache == ["AAPL"]
        assert not fake.calls_for("AAPL", since=calls_after_first)
        # ...while the missing one is attempted again rather than being
        # replayed from a cached, incomplete batch.
        assert fake.calls_for("ZZZZZZZZ", since=calls_after_first)
        assert second.missing == ["ZZZZZZZZ"]

    async def test_failed_symbol_is_negative_cached_for_a_short_ttl(
        self, fetcher, monkeypatch
    ):
        """A transient failure is not retried on every call, but is pinned for
        _ERROR_TTL rather than the full 5-minute data TTL."""
        fake = FakeYF({"AAPL": make_frame([10.0] * 40)})
        monkeypatch.setattr(heatmap_fetcher, "yf", fake)

        await fetcher._batch_download(["AAPL", "BADSYM"], period="1mo")
        calls_after_first = len(fake.calls)

        second = await fetcher._batch_download(["AAPL", "BADSYM"], period="1mo")

        assert second.missing == ["BADSYM"]
        assert not fake.calls_for("BADSYM", since=calls_after_first)
        assert heatmap_fetcher._ERROR_TTL < heatmap_fetcher._CACHE_TTL

    async def test_successful_symbols_are_cached_individually(
        self, fetcher, monkeypatch
    ):
        fake = FakeYF({"AAA": make_frame([10.0] * 40), "BBB": make_frame([20.0] * 40)})
        monkeypatch.setattr(heatmap_fetcher, "yf", fake)

        await fetcher._batch_download(["AAA", "BBB"], period="1mo")
        calls_after_first = len(fake.calls)

        # A different batch overlapping on AAA reuses the cached frame and
        # only asks the network for the new symbol.
        second = await fetcher._batch_download(["AAA", "CCC"], period="1mo")

        assert "AAA" in second.from_cache
        assert not fake.calls_for("AAA", since=calls_after_first)
        assert second.missing == ["CCC"]

    async def test_manifest_reports_full_coverage_when_nothing_dropped(
        self, fetcher, monkeypatch
    ):
        fake = FakeYF({"AAA": make_frame([10.0] * 40), "BBB": make_frame([20.0] * 40)})
        monkeypatch.setattr(heatmap_fetcher, "yf", fake)

        result = await fetcher._batch_download(["AAA", "BBB"], period="1mo")

        assert result.is_complete
        assert result.coverage == 1.0
        assert result.missing == []

    async def test_chunked_download_merges_manifests(self, fetcher, monkeypatch):
        frames = {f"S{i}": make_frame([10.0] * 40) for i in range(5)}
        fake = FakeYF(frames)
        monkeypatch.setattr(heatmap_fetcher, "yf", fake)
        monkeypatch.setattr(heatmap_fetcher, "_ERROR_TTL", 0)

        symbols = [*frames.keys(), "BADSYM"]
        result = await fetcher._batch_download_chunked(
            symbols, period="1mo", chunk_size=2
        )

        assert len(result.data) == 5
        assert result.missing == ["BADSYM"]
        assert len(result.requested) == 6

    def test_empty_batch_result_is_complete(self):
        assert BatchDownloadResult().is_complete
        assert BatchDownloadResult().coverage == 1.0


# =============================================================================
# Sector aggregation
# =============================================================================


class TestSectorAggregation:
    def _stock(self, symbol: str, change_1d: float) -> StockHeatmapEntry:
        return StockHeatmapEntry(
            symbol=symbol, sector="Technology", change_1d=change_1d, change_5d=change_1d
        )

    def test_breadth_from_too_few_constituents_is_flagged_invalid(self, fetcher):
        entry = fetcher._build_sector_entry(
            name="Technology",
            etf="XLK",
            etf_metrics={"change_1d": 1.0, "change_5d": 2.0, "change_20d": 3.0},
            sector_stocks=[self._stock("AAA", 1.0)],
            coverage=0.1,
        )

        assert entry.breadth_valid is False
        assert entry.metrics_valid is True  # the ETF quote itself is real
        assert entry.metrics_source == "etf"

    def test_missing_etf_quote_falls_back_to_constituent_medians(self, fetcher):
        stocks = [self._stock("AAA", 1.0), self._stock("BBB", 3.0), self._stock("CCC", -1.0)]

        entry = fetcher._build_sector_entry(
            name="Technology",
            etf="XLK",
            etf_metrics={},
            sector_stocks=stocks,
            coverage=1.0,
        )

        assert entry.metrics_source == "constituents"
        assert entry.change_1d == pytest.approx(1.0)  # median, not a fabricated 0.0
        assert entry.breadth_valid is True
        assert entry.breadth == pytest.approx(2 / 3)
        assert entry.metrics_valid is True

    def test_thin_sector_without_etf_quote_is_flagged_invalid(self, fetcher):
        entry = fetcher._build_sector_entry(
            name="Technology",
            etf="XLK",
            etf_metrics={},
            sector_stocks=[self._stock("AAA", 1.0)],
            coverage=0.1,
        )

        assert entry.metrics_valid is False
        assert entry.breadth_valid is False

    def test_validity_flags_survive_serialization(self, fetcher):
        from analysis.agents.heatmap_interfaces import SectorHeatmapEntry

        entry = fetcher._build_sector_entry(
            name="Technology",
            etf="XLK",
            etf_metrics={},
            sector_stocks=[self._stock("AAA", 1.0)],
            coverage=0.1,
        )

        restored = SectorHeatmapEntry.from_dict(entry.to_dict())

        assert restored.metrics_valid is False
        assert restored.breadth_valid is False
        assert restored.metrics_source == "constituents"
        assert restored.data_coverage == pytest.approx(0.1)

    def test_legacy_sector_payload_defaults_to_valid(self):
        from analysis.agents.heatmap_interfaces import SectorHeatmapEntry

        legacy = {
            "name": "Technology",
            "etf": "XLK",
            "change_1d": 1.0,
            "change_5d": 2.0,
            "change_20d": 3.0,
            "breadth": 0.7,
            "top_gainers": ["AAPL"],
            "top_losers": ["INTC"],
            "stock_count": 10,
        }

        entry = SectorHeatmapEntry.from_dict(legacy)

        assert entry.metrics_valid is True
        assert entry.breadth_valid is True
        assert entry.data_coverage is None


# =============================================================================
# End-to-end wiring
# =============================================================================


class TestFetchHeatmapData:
    async def test_fetch_requests_the_deep_history_and_records_coverage(
        self, fetcher, monkeypatch
    ):
        captured: dict[str, str] = {}

        async def fake_chunked(symbols, period=DEFAULT_HISTORY_PERIOD, chunk_size=150):
            captured["period"] = period
            frames = {s: make_frame([100.0 + i for i in range(70)]) for s in symbols[:-1]}
            return BatchDownloadResult(
                data=frames,
                requested=list(symbols),
                missing=[symbols[-1]],
            )

        async def fake_caps(symbols):
            return {s: 100.0 for s in symbols}

        monkeypatch.setattr(fetcher, "_batch_download_chunked", fake_chunked)
        monkeypatch.setattr(fetcher, "_fetch_market_caps", fake_caps)

        data = await fetcher.fetch_heatmap_data(
            holdings={"Technology": ["AAA", "BBB", "CCC"]}
        )

        assert captured["period"] == DEFAULT_HISTORY_PERIOD
        assert data.data_coverage is not None and data.data_coverage < 1.0
        assert data.missing_symbols

        # Deep history means the new metrics actually reach the entries.
        entry = next(s for s in data.stocks if s.symbol == "AAA")
        assert entry.change_60d is not None
        assert entry.rsi_14 is not None
        assert entry.volatility_20d is not None
        assert entry.change_20d is not None
