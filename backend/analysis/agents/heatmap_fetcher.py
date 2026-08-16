"""Sector heatmap data fetcher for the heatmap-driven stock selection pipeline.

Fetches real-time sector ETF and constituent stock data from yfinance,
computes price changes across multiple timeframes, volume ratios, and
sector-level breadth indicators. Produces a HeatmapData snapshot consumed
by the heatmap analyzer for pattern detection and stock selection.

All blocking yfinance calls are wrapped with run_in_executor() for async
compatibility. Uses batch yf.download() for efficient multi-symbol fetching.
Per-symbol errors are handled gracefully without failing the entire sector.
"""

from __future__ import annotations

import asyncio
import logging
import math
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import yfinance as yf  # type: ignore[import-untyped]

from analysis.agents.heatmap_interfaces import (  # type: ignore[import-not-found]
    HeatmapData,
    SectorHeatmapEntry,
    StockHeatmapEntry,
)
from analysis.sectors import get_sector_etfs

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level yfinance data cache
# ---------------------------------------------------------------------------
# Entries are (expires_at, data). Successful fetches get _CACHE_TTL; download
# failures get the much shorter _ERROR_TTL so a transient outage does not pin
# a symbol as unavailable for a full cache generation.
_yf_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 300  # 5 minutes
_ERROR_TTL = 30  # negative cache for symbols that failed to download

# Sentinel stored in the cache to mark "this symbol failed recently".
_DOWNLOAD_FAILED = object()

# Default history depth. Must cover the deepest lookback we compute
# (change_60d needs 61 closes) with room for holidays; ~6mo ≈ 126 sessions.
DEFAULT_HISTORY_PERIOD = "6mo"

# Upper bound on per-symbol retries triggered by one batch call, so a broad
# outage degrades gracefully instead of turning into 400 serial requests.
MAX_INDIVIDUAL_RETRIES = 40

# Sector-level evidence thresholds.
# Breadth over one or two names is noise, not participation.
MIN_BREADTH_STOCKS = 3
# Below this fraction of a sector's requested constituents, a sector reading
# built from constituents alone is flagged as unreliable.
MIN_SECTOR_COVERAGE = 0.5


def _median_of(entries: list[StockHeatmapEntry], attr: str) -> float | None:
    """Median of *attr* across entries that actually reported it."""
    values = [
        v for v in (getattr(e, attr, None) for e in entries) if v is not None
    ]
    if not values:
        return None
    return float(statistics.median(values))


def _get_cached(key: str) -> Any | None:
    """Get cached data if the entry has not expired."""
    if key in _yf_cache:
        expires_at, data = _yf_cache[key]
        if time.time() < expires_at:
            return data
        del _yf_cache[key]
    return None


def _set_cache(key: str, data: Any, ttl: float = _CACHE_TTL) -> None:
    """Cache data with an explicit TTL (seconds)."""
    _yf_cache[key] = (time.time() + ttl, data)


def _symbol_key(symbol: str, period: str) -> str:
    return f"hist:{period}:{symbol}"


def _error_key(symbol: str, period: str) -> str:
    return f"histerr:{period}:{symbol}"


@dataclass
class BatchDownloadResult:
    """Price history for a symbol batch plus a completeness manifest.

    ``data`` only ever contains symbols that actually resolved. ``missing``
    lists the symbols that were requested and never produced usable data,
    including after individual retries — callers must be able to tell a
    dropped symbol from one that was never asked for.
    """

    data: dict[str, Any] = field(default_factory=dict)
    requested: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    from_cache: list[str] = field(default_factory=list)
    retried: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        """Fraction of requested symbols that resolved (1.0 when none asked)."""
        if not self.requested:
            return 1.0
        return len(self.data) / len(self.requested)

    @property
    def is_complete(self) -> bool:
        return not self.missing

    def merge(self, other: BatchDownloadResult) -> None:
        """Fold *other* into this result in place."""
        self.data.update(other.data)
        self.requested.extend(other.requested)
        self.missing.extend(other.missing)
        self.from_cache.extend(other.from_cache)
        self.retried.extend(other.retried)



# Fallback constituent holdings when yfinance can't provide them.
# Sourced from opportunity_hunter.SECTOR_HOLDINGS.
FALLBACK_HOLDINGS: dict[str, list[str]] = {
    "XLK": ["AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "AMD", "ADBE", "CSCO", "ACN"],
    "XLF": ["BRK-B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "SPGI", "BLK"],
    "XLE": ["XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY", "DVN"],
    "XLV": ["UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT", "DHR", "BMY"],
    "XLI": ["CAT", "UNP", "HON", "UPS", "BA", "RTX", "DE", "LMT", "GE", "MMM"],
    "XLP": ["PG", "KO", "PEP", "COST", "WMT", "PM", "MO", "MDLZ", "CL", "KMB"],
    "XLY": ["AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "SBUX", "TJX", "BKNG", "CMG"],
    "XLU": ["NEE", "DUK", "SO", "D", "AEP", "SRE", "EXC", "XEL", "PEG", "ED"],
    "XLC": ["META", "GOOGL", "GOOG", "NFLX", "DIS", "CMCSA", "VZ", "T", "TMUS", "CHTR"],
    "XLRE": ["PLD", "AMT", "EQIX", "CCI", "PSA", "O", "WELL", "DLR", "SPG", "AVB"],
    "XLB": ["LIN", "APD", "SHW", "FCX", "ECL", "NEM", "DOW", "NUE", "DD", "PPG"],
}


async def get_dynamic_holdings() -> dict[str, list[str]]:
    """Get dynamic stock universe, falling back to FALLBACK_HOLDINGS.

    Attempts to fetch a broad screening universe (300-500 symbols) from
    the universe_builder module. Falls back to the static FALLBACK_HOLDINGS
    if the dynamic fetch fails or returns too few symbols.

    Returns:
        Dict mapping sector/category name -> list of stock symbols.
    """
    try:
        from analysis.agents.universe_builder import get_screening_universe  # type: ignore[import-not-found]
        universe = await get_screening_universe()
        if universe and sum(len(v) for v in universe.values()) > 50:
            return universe
    except Exception as e:
        logger.warning(f"Dynamic universe fetch failed, using fallback: {e}")
    return FALLBACK_HOLDINGS


class SectorHeatmapFetcher:
    """Fetches and computes sector/stock heatmap data from yfinance.

    Main entry point is ``fetch_heatmap_data()`` which returns a complete
    HeatmapData snapshot. Internally uses batch ``yf.download()`` via
    ``run_in_executor`` for efficient parallel data retrieval.
    """

    def __init__(self) -> None:
        self._fallback_holdings = FALLBACK_HOLDINGS

    @property
    def _sector_etfs(self) -> dict[str, str]:
        """Live sector ETF mapping — always reflects the current settings."""
        return get_sector_etfs()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_heatmap_data(
        self,
        holdings: dict[str, list[str]] | None = None,
    ) -> HeatmapData:
        """Fetch a complete market heatmap snapshot.

        Workflow:
            1. Collect all symbols (ETFs + constituents).
            2. Batch-download ``DEFAULT_HISTORY_PERIOD`` of price history via
               ``yf.download()`` — deep enough for a true 60-session lookback.
            3. Compute per-stock metrics (change_1d/5d/20d/60d, volume_ratio,
               rsi_14, volatility_20d, market_cap).
            4. Aggregate per-sector breadth and top movers.
            5. Return HeatmapData, including a coverage manifest.

        Args:
            holdings: Optional sector/category -> symbols mapping from the
                dynamic universe builder. When provided, these symbols are
                used instead of FALLBACK_HOLDINGS. Keys should be sector
                names (not ETF tickers). Falls back to FALLBACK_HOLDINGS
                when None.

        Returns:
            HeatmapData containing sector and stock entries.
        """
        # Build symbol universe
        etf_symbols = list(self._sector_etfs.keys())
        stock_symbols_by_sector: dict[str, list[str]] = {}

        if holdings is not None:
            # Dynamic universe: keys are sector names (or categories like
            # "Commodities", "International", "Top Gainers", etc.)
            sector_names = set(self._sector_etfs.values())
            for key, syms in holdings.items():
                if key in sector_names:
                    stock_symbols_by_sector[key] = syms
                else:
                    # Non-sector categories (commodities, ADRs, movers) —
                    # include them under their own key for heatmap data.
                    stock_symbols_by_sector[key] = syms
            # Ensure every GICS sector has at least fallback symbols
            for etf, sector in self._sector_etfs.items():
                if sector not in stock_symbols_by_sector:
                    stock_symbols_by_sector[sector] = self._fallback_holdings.get(etf, [])
        else:
            for etf, sector in self._sector_etfs.items():
                stock_symbols_by_sector[sector] = self._fallback_holdings.get(etf, [])

        all_stock_symbols: list[str] = []
        for syms in stock_symbols_by_sector.values():
            all_stock_symbols.extend(syms)

        all_symbols = etf_symbols + list(dict.fromkeys(all_stock_symbols))

        # Batch fetch price history (chunked for large universes)
        download = await self._batch_download_chunked(
            all_symbols, period=DEFAULT_HISTORY_PERIOD
        )
        hist_data = download.data

        # Fetch market caps in parallel
        market_caps = await self._fetch_market_caps(all_stock_symbols)

        # Build ETF entries for sector-level metrics
        etf_metrics: dict[str, dict[str, float]] = {}
        for etf in etf_symbols:
            metrics = self._compute_metrics(hist_data, etf)
            if metrics is not None:
                etf_metrics[etf] = metrics

        # Build stock entries
        stocks: list[StockHeatmapEntry] = []
        stocks_by_sector: dict[str, list[StockHeatmapEntry]] = {
            s: [] for s in self._sector_etfs.values()
        }
        # Include non-GICS categories from the dynamic universe
        for key in stock_symbols_by_sector:
            if key not in stocks_by_sector:
                stocks_by_sector[key] = []

        for sector, syms in stock_symbols_by_sector.items():
            for symbol in syms:
                metrics = self._compute_metrics(hist_data, symbol)
                if metrics is None:
                    continue

                entry = StockHeatmapEntry(
                    symbol=symbol,
                    sector=sector,
                    price=metrics.get("price", 0.0),
                    change_1d=metrics.get("change_1d", 0.0),
                    change_5d=metrics.get("change_5d"),
                    change_20d=metrics.get("change_20d"),
                    change_60d=metrics.get("change_60d"),
                    volume_ratio=metrics.get("volume_ratio"),
                    market_cap=market_caps.get(symbol, 0.0),
                    rsi_14=metrics.get("rsi_14"),
                    volatility_20d=metrics.get("volatility_20d"),
                )
                stocks.append(entry)
                stocks_by_sector[sector].append(entry)

        # Build sector entries
        sectors: list[SectorHeatmapEntry] = []
        for etf, sector in self._sector_etfs.items():
            etf_m = etf_metrics.get(etf, {})
            sector_stocks = stocks_by_sector.get(sector, [])
            requested = len(stock_symbols_by_sector.get(sector, []))
            coverage = len(sector_stocks) / requested if requested else 0.0

            if not etf_m and not sector_stocks:
                # No ETF quote and no constituents: every field would be a
                # fabricated zero, so publish nothing for this sector.
                logger.warning("Dropping sector %s (%s): no usable data", sector, etf)
                continue

            entry = self._build_sector_entry(
                name=sector,
                etf=etf,
                etf_metrics=etf_m,
                sector_stocks=sector_stocks,
                coverage=coverage if requested else None,
            )
            sectors.append(entry)

        market_status = self._determine_market_status()

        logger.info(
            "Heatmap fetched: %d sectors, %d stocks, coverage=%.1f%% "
            "(%d symbols missing), market_status=%s",
            len(sectors), len(stocks), download.coverage * 100,
            len(download.missing), market_status,
        )

        return HeatmapData(
            sectors=sectors,
            stocks=stocks,
            timestamp=datetime.utcnow(),
            market_status=market_status,
            data_coverage=download.coverage,
            missing_symbols=download.missing,
        )

    def _build_sector_entry(
        self,
        name: str,
        etf: str,
        etf_metrics: dict[str, float],
        sector_stocks: list[StockHeatmapEntry],
        coverage: float | None,
    ) -> SectorHeatmapEntry:
        """Assemble one sector row, flagging evidence that is too thin to trust.

        When the sector ETF itself returned no data the change_* figures are
        derived from constituent medians instead of being reported as 0%, and
        the source is recorded. Breadth computed from fewer than
        ``MIN_BREADTH_STOCKS`` constituents is marked invalid.
        """
        metrics_source = "etf"
        if etf_metrics:
            change_1d = etf_metrics.get("change_1d", 0.0)
            change_5d = etf_metrics.get("change_5d", 0.0)
            change_20d = etf_metrics.get("change_20d", 0.0)
            change_60d = etf_metrics.get("change_60d")
        else:
            metrics_source = "constituents"
            change_1d = _median_of(sector_stocks, "change_1d") or 0.0
            change_5d = _median_of(sector_stocks, "change_5d") or 0.0
            change_20d = _median_of(sector_stocks, "change_20d") or 0.0
            change_60d = _median_of(sector_stocks, "change_60d")

        breadth_valid = len(sector_stocks) >= MIN_BREADTH_STOCKS
        if breadth_valid:
            positive = sum(1 for s in sector_stocks if s.change_1d > 0)
            breadth = positive / len(sector_stocks)
        else:
            breadth = 0.5  # placeholder; breadth_valid=False says not to trust it

        sorted_by_1d = sorted(sector_stocks, key=lambda s: s.change_1d, reverse=True)
        top_gainers = [s.symbol for s in sorted_by_1d[:3]]
        top_losers = (
            [s.symbol for s in sorted_by_1d[-3:]]
            if len(sorted_by_1d) >= 3
            else [s.symbol for s in reversed(sorted_by_1d)]
        )

        metrics_valid = bool(etf_metrics) or (
            coverage is not None and coverage >= MIN_SECTOR_COVERAGE
        )
        if not metrics_valid:
            logger.warning(
                "Sector %s (%s) metrics flagged invalid: source=%s coverage=%s",
                name, etf, metrics_source,
                "n/a" if coverage is None else f"{coverage:.0%}",
            )

        return SectorHeatmapEntry(
            name=name,
            etf=etf,
            change_1d=change_1d,
            change_5d=change_5d,
            change_20d=change_20d,
            change_60d=change_60d,
            breadth=breadth,
            top_gainers=top_gainers,
            top_losers=top_losers,
            stock_count=len(sector_stocks),
            data_coverage=coverage,
            metrics_valid=metrics_valid,
            breadth_valid=breadth_valid,
            metrics_source=metrics_source,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_frames(
        raw: Any, symbols: list[str]
    ) -> dict[str, Any]:
        """Pull per-symbol frames out of a yf.download() result."""
        result: dict[str, Any] = {}
        if raw is None:
            return result
        # When downloading multiple tickers, columns are MultiIndex (ticker, field).
        # For a single ticker, it's a flat DataFrame.
        if len(symbols) == 1:
            sym = symbols[0]
            try:
                if not raw.empty:
                    result[sym] = raw
            except Exception as e:  # pragma: no cover - defensive
                logger.debug("Could not read single-symbol frame %s: %s", sym, e)
            return result

        for sym in symbols:
            try:
                df = raw[sym] if sym in raw.columns.get_level_values(0) else None
                if df is not None and not df.dropna(how="all").empty:
                    result[sym] = df
            except Exception as e:
                logger.debug(f"Skipping symbol {sym} in batch result: {e}")
                continue
        return result

    async def _batch_download(
        self,
        symbols: list[str],
        period: str = DEFAULT_HISTORY_PERIOD,
    ) -> BatchDownloadResult:
        """Download price history for *symbols*, tracking what was dropped.

        Caching is **per symbol**, never per batch: a batch that silently
        returned only some of its symbols must not be replayed as if it were
        complete. Symbols the batch omits are retried individually (bounded by
        ``MAX_INDIVIDUAL_RETRIES``); ones that still fail are negative-cached
        for ``_ERROR_TTL`` seconds and reported in ``missing``.

        Returns:
            BatchDownloadResult with the resolved frames and a manifest of
            cache hits, retries, and unresolved symbols.
        """
        requested = list(dict.fromkeys(symbols))
        outcome = BatchDownloadResult(requested=requested)
        if not requested:
            return outcome

        # 1. Serve whatever is already cached per symbol.
        to_fetch: list[str] = []
        for sym in requested:
            cached = _get_cached(_symbol_key(sym, period))
            if cached is not None:
                outcome.data[sym] = cached
                outcome.from_cache.append(sym)
            elif _get_cached(_error_key(sym, period)) is _DOWNLOAD_FAILED:
                # Known-bad recently; don't hammer it again this generation.
                outcome.missing.append(sym)
            else:
                to_fetch.append(sym)

        if not to_fetch:
            return outcome

        loop = asyncio.get_running_loop()

        def _download(batch: list[str]) -> Any:
            try:
                return yf.download(
                    tickers=batch,
                    period=period,
                    group_by="ticker",
                    threads=False,
                    progress=False,
                )
            except Exception as e:
                logger.error(f"Batch download failed: {e}")
                return None

        raw = await loop.run_in_executor(None, _download, to_fetch)
        fetched = self._extract_frames(raw, to_fetch)
        for sym, df in fetched.items():
            _set_cache(_symbol_key(sym, period), df)
            outcome.data[sym] = df

        # 2. Retry whatever the batch dropped, one symbol at a time.
        dropped = [s for s in to_fetch if s not in fetched]
        if not dropped:
            return outcome

        retry_targets = dropped[:MAX_INDIVIDUAL_RETRIES]
        if len(dropped) > MAX_INDIVIDUAL_RETRIES:
            logger.warning(
                "Batch dropped %d symbols; retrying only the first %d",
                len(dropped), MAX_INDIVIDUAL_RETRIES,
            )
            outcome.missing.extend(dropped[MAX_INDIVIDUAL_RETRIES:])

        def _retry_single(sym: str) -> tuple[str, Any]:
            try:
                raw_single = yf.download(
                    tickers=[sym],
                    period=period,
                    group_by="ticker",
                    threads=False,
                    progress=False,
                )
            except Exception as e:
                logger.debug("Individual retry failed for %s: %s", sym, e)
                return sym, None
            frames = SectorHeatmapFetcher._extract_frames(raw_single, [sym])
            return sym, frames.get(sym)

        def _retry_all() -> list[tuple[str, Any]]:
            with ThreadPoolExecutor(max_workers=8) as executor:
                return list(executor.map(_retry_single, retry_targets))

        retried = await loop.run_in_executor(None, _retry_all)
        outcome.retried.extend(retry_targets)
        for sym, df in retried:
            if df is not None:
                _set_cache(_symbol_key(sym, period), df)
                outcome.data[sym] = df
            else:
                _set_cache(_error_key(sym, period), _DOWNLOAD_FAILED, ttl=_ERROR_TTL)
                outcome.missing.append(sym)

        if outcome.missing:
            logger.warning(
                "Price history unavailable for %d/%d symbols: %s",
                len(outcome.missing), len(requested),
                ", ".join(outcome.missing[:10]),
            )
        return outcome

    async def _batch_download_chunked(
        self,
        symbols: list[str],
        period: str = DEFAULT_HISTORY_PERIOD,
        chunk_size: int = 150,
    ) -> BatchDownloadResult:
        """Batch download with automatic chunking for large symbol universes.

        When the symbol list exceeds *chunk_size*, splits into chunks and
        downloads them in parallel via ``asyncio.gather()``, then merges
        the results. For small lists (<= chunk_size), delegates directly
        to ``_batch_download()``.

        Args:
            symbols: List of ticker symbols to download.
            period: yfinance period string.
            chunk_size: Maximum symbols per batch download call.

        Returns:
            Merged BatchDownloadResult across all chunks. A chunk that raises
            outright has all of its symbols recorded as missing.
        """
        if len(symbols) <= chunk_size:
            return await self._batch_download(symbols, period=period)

        # Split into chunks
        chunks = [
            symbols[i : i + chunk_size]
            for i in range(0, len(symbols), chunk_size)
        ]
        logger.info(
            "Chunked download: %d symbols in %d chunks of <=%d",
            len(symbols), len(chunks), chunk_size,
        )

        chunk_results = await asyncio.gather(
            *(self._batch_download(chunk, period=period) for chunk in chunks),
            return_exceptions=True,
        )

        merged = BatchDownloadResult()
        for idx, chunk_result in enumerate(chunk_results):
            if isinstance(chunk_result, BaseException):
                logger.warning("Chunk %d download failed: %s", idx, chunk_result)
                merged.requested.extend(chunks[idx])
                merged.missing.extend(chunks[idx])
                continue
            merged.merge(chunk_result)

        return merged

    @staticmethod
    def _lookback_change(closes: Any, bars: int) -> float | None:
        """Percent change over a true *bars*-session lookback.

        Returns None when the history is too short — a shorter window is a
        different measurement, not an approximation of this one.
        """
        if len(closes) < bars + 1:
            return None
        prior = float(closes.iloc[-(bars + 1)])
        if not prior:
            return None
        return ((float(closes.iloc[-1]) / prior) - 1) * 100

    def _compute_metrics(
        self,
        hist_data: dict[str, Any],
        symbol: str,
    ) -> dict[str, float] | None:
        """Compute price change and volume metrics for a single symbol.

        Every lookback is a true N-session lookback; keys for windows the
        history cannot support are omitted entirely rather than filled with a
        shorter window or a neutral value.

        Returns:
            Dict with price and change_1d plus whichever of change_5d,
            change_20d, change_60d, volume_ratio, rsi_14, volatility_20d the
            history supports. None if there is not enough data for any metric.
        """
        df = hist_data.get(symbol)
        if df is None or df.empty:
            return None

        try:
            closes = df["Close"].dropna()
            if len(closes) < 2:
                return None

            current = float(closes.iloc[-1])
            prev_1d = float(closes.iloc[-2])
            change_1d = ((current / prev_1d) - 1) * 100 if prev_1d else 0.0

            result: dict[str, float] = {
                "price": current,
                "change_1d": change_1d,
            }

            for bars, key in ((5, "change_5d"), (20, "change_20d"), (60, "change_60d")):
                change = self._lookback_change(closes, bars)
                if change is not None:
                    result[key] = change

            # Volume ratio: latest volume / trailing 20-session average
            # (excluding the latest bar). Needs 21 bars — averaging over
            # whatever history happens to be loaded makes the ratio depend on
            # the fetch period rather than on the stock.
            volumes = df["Volume"].dropna()
            if len(volumes) >= 21:
                avg_vol = float(volumes.iloc[-21:-1].mean())
                if avg_vol > 0:
                    result["volume_ratio"] = float(volumes.iloc[-1]) / avg_vol

            # 14-period RSI
            if len(closes) >= 15:
                deltas = closes.diff().dropna()
                recent = deltas.iloc[-14:]
                gains = recent.clip(lower=0).mean()
                losses = (-recent.clip(upper=0)).mean()
                if losses > 0:
                    rs = float(gains) / float(losses)
                    result["rsi_14"] = 100 - (100 / (1 + rs))
                else:
                    result["rsi_14"] = 100.0

            # 20-day annualized realized volatility
            if len(closes) >= 21:
                returns = closes.pct_change().dropna().iloc[-20:]
                if len(returns) >= 10:
                    result["volatility_20d"] = (
                        float(returns.std()) * math.sqrt(252) * 100
                    )

            return result
        except Exception as e:
            logger.warning(f"Failed to compute metrics for {symbol}: {e}")
            return None

    async def _fetch_market_caps(
        self,
        symbols: list[str],
    ) -> dict[str, float]:
        """Fetch market caps for symbols via yfinance Ticker.info.

        Uses a ThreadPoolExecutor with up to 20 workers to fetch market caps
        in parallel rather than sequentially. Per-symbol results are cached
        with a 5-minute TTL.

        Returns market cap in billions USD. Symbols that fail are omitted.
        """
        loop = asyncio.get_running_loop()

        def _get_single_cap(sym: str) -> tuple[str, float | None]:
            cached = _get_cached(f"mcap:{sym}")
            if cached is not None:
                return sym, cached
            try:
                info = yf.Ticker(sym).info
                raw_cap = info.get("marketCap")
                if raw_cap:
                    cap_billions = float(raw_cap) / 1_000_000_000
                    _set_cache(f"mcap:{sym}", cap_billions)
                    return sym, cap_billions
                return sym, None
            except Exception:
                return sym, None

        def _get_all_caps() -> list[tuple[str, float | None]]:
            with ThreadPoolExecutor(max_workers=8) as executor:
                return list(executor.map(_get_single_cap, symbols))

        results = await loop.run_in_executor(None, _get_all_caps)
        return {sym: cap for sym, cap in results if cap is not None}

    @staticmethod
    def _determine_market_status() -> str:
        """Determine current US market session status.

        Returns:
            One of: 'pre_market', 'open', 'after_hours', 'closed'.
        """
        now = datetime.utcnow()
        # Approximate ET = UTC - 5 (ignoring DST)
        et_hour = (now.hour - 5) % 24

        if now.weekday() >= 5:
            return "closed"
        if 4 <= et_hour < 9:
            return "pre_market"
        if 9 <= et_hour < 16:
            return "open"
        if 16 <= et_hour < 20:
            return "after_hours"
        return "closed"


def format_heatmap_for_llm(data: HeatmapData) -> str:
    """Format HeatmapData into a concise string for LLM consumption.

    Includes:
        - Sector performance table
        - Top 5 gainers/losers across all sectors
        - Stocks diverging from their sector
        - Breadth indicators per sector

    Args:
        data: HeatmapData snapshot to format.

    Returns:
        Markdown-formatted string suitable for LLM context.
    """
    lines: list[str] = [
        f"## Market Heatmap ({data.timestamp.strftime('%Y-%m-%d %H:%M')} UTC)",
        f"Market Status: {data.market_status}",
        "",
    ]
    if data.data_coverage is not None and data.data_coverage < 1.0:
        lines.append(
            f"Data coverage: {data.data_coverage:.0%} — "
            f"{len(data.missing_symbols)} symbol(s) had no usable price history"
            + (f" ({', '.join(data.missing_symbols[:8])})" if data.missing_symbols else "")
        )
        lines.append("")

    # --- Sector Performance Table ---
    lines.append("### Sector Performance")
    lines.append("| Sector | ETF | 1D | 5D | 20D | Breadth | Stocks |")
    lines.append("|--------|-----|-----|-----|------|---------|--------|")

    sorted_sectors = sorted(data.sectors, key=lambda s: s.change_1d, reverse=True)
    for s in sorted_sectors:
        breadth_pct = f"{s.breadth * 100:.0f}%" if s.breadth_valid else "n/a"
        name = s.name if s.metrics_valid else f"{s.name} (low coverage)"
        lines.append(
            f"| {name} | {s.etf} | {s.change_1d:+.2f}% | {s.change_5d:+.2f}% "
            f"| {s.change_20d:+.2f}% | {breadth_pct} | {s.stock_count} |"
        )
    lines.append("")

    # --- Top 5 Gainers / Losers across all stocks ---
    if data.stocks:
        sorted_stocks = sorted(data.stocks, key=lambda s: s.change_1d, reverse=True)

        def _mover_line(s: StockHeatmapEntry) -> str:
            c5 = f"{s.change_5d:+.2f}%" if s.change_5d is not None else "n/a"
            vr = f"{s.volume_ratio:.1f}x" if s.volume_ratio is not None else "n/a"
            return (
                f"- {s.symbol} ({s.sector}): {s.change_1d:+.2f}% "
                f"| 5D: {c5} | Vol ratio: {vr}"
            )

        lines.append("### Top 5 Gainers (1D)")
        lines.extend(_mover_line(s) for s in sorted_stocks[:5])
        lines.append("")

        lines.append("### Top 5 Losers (1D)")
        lines.extend(_mover_line(s) for s in sorted_stocks[-5:])
        lines.append("")

    # --- Sector Divergences ---
    divergences = data.get_divergences()
    if divergences:
        lines.append("### Notable Divergences (stock vs sector)")
        for stock, sector in divergences[:8]:
            diff = stock.change_1d - sector.change_1d
            lines.append(
                f"- {stock.symbol}: {stock.change_1d:+.2f}% vs {sector.name} "
                f"{sector.change_1d:+.2f}% (divergence: {diff:+.2f}%)"
            )
        lines.append("")

    # --- Outliers ---
    outliers = data.get_outliers(change_field="change_1d", threshold_std=2.0)
    if outliers:
        lines.append("### Statistical Outliers (>2 std from mean)")
        for s in outliers[:6]:
            vr = f"{s.volume_ratio:.1f}x" if s.volume_ratio is not None else "n/a"
            lines.append(
                f"- {s.symbol} ({s.sector}): {s.change_1d:+.2f}% "
                f"| Vol: {vr} | Cap: ${s.market_cap:.1f}B"
            )
        lines.append("")

    # --- Breadth Summary ---
    lines.append("### Breadth Summary")
    for s in sorted_sectors:
        if not s.breadth_valid:
            lines.append(
                f"  {s.name:25s} [insufficient constituents] n/a "
                f"({s.stock_count} stocks)"
            )
            continue
        bar_len = int(s.breadth * 20)
        bar = "#" * bar_len + "." * (20 - bar_len)
        lines.append(f"  {s.name:25s} [{bar}] {s.breadth * 100:.0f}%")
    lines.append("")

    # --- Sector Momentum Rankings ---
    try:
        from analysis.sector_momentum import (  # type: ignore[import-not-found]
            compute_sector_momentum_from_heatmap,
            format_momentum_table,
        )
        momentum_data = compute_sector_momentum_from_heatmap(data.sectors)
        momentum_table = format_momentum_table(momentum_data)
        if momentum_table:
            lines.append("")
            lines.append(momentum_table)
    except Exception as exc:
        logger.debug("sector momentum table skipped: %s", exc)  # Non-fatal: omit if unavailable

    return "\n".join(lines)


# Module singleton
_fetcher: SectorHeatmapFetcher | None = None


def get_heatmap_fetcher() -> SectorHeatmapFetcher:
    """Get or create the singleton SectorHeatmapFetcher instance."""
    global _fetcher
    if _fetcher is None:
        _fetcher = SectorHeatmapFetcher()
    return _fetcher
