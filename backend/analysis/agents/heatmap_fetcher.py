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
import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

import yfinance as yf  # type: ignore[import-untyped]

from analysis.agents.heatmap_interfaces import (  # type: ignore[import-not-found]
    HeatmapData,
    SectorHeatmapEntry,
    StockHeatmapEntry,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level yfinance data cache (5-minute TTL)
# ---------------------------------------------------------------------------
_yf_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 300  # 5 minutes


def _get_cached(key: str) -> Any | None:
    """Get cached data if within TTL."""
    if key in _yf_cache:
        ts, data = _yf_cache[key]
        if time.time() - ts < _CACHE_TTL:
            return data
        del _yf_cache[key]
    return None


def _set_cache(key: str, data: Any) -> None:
    """Cache data with current timestamp."""
    _yf_cache[key] = (time.time(), data)


# 11 GICS Sector SPDR ETFs
SECTOR_ETFS: dict[str, str] = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Healthcare",
    "XLI": "Industrials",
    "XLP": "Consumer Staples",
    "XLY": "Consumer Discretionary",
    "XLU": "Utilities",
    "XLC": "Communication Services",
    "XLRE": "Real Estate",
    "XLB": "Materials",
}

# Fallback constituent holdings when yfinance can't provide them.
# Sourced from opportunity_hunter.SECTOR_HOLDINGS.
FALLBACK_HOLDINGS: dict[str, list[str]] = {
    "XLK": ["AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "AMD", "ADBE", "CSCO", "ACN"],
    "XLF": ["BRK-B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "SPGI", "BLK"],
    "XLE": ["XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PXD", "PSX", "VLO", "OXY"],
    "XLV": ["UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT", "DHR", "BMY"],
    "XLI": ["CAT", "UNP", "HON", "UPS", "BA", "RTX", "DE", "LMT", "GE", "MMM"],
    "XLP": ["PG", "KO", "PEP", "COST", "WMT", "PM", "MO", "MDLZ", "CL", "KMB"],
    "XLY": ["AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "SBUX", "TJX", "BKNG", "CMG"],
    "XLU": ["NEE", "DUK", "SO", "D", "AEP", "SRE", "EXC", "XEL", "PEG", "ED"],
    "XLC": ["META", "GOOGL", "GOOG", "NFLX", "DIS", "CMCSA", "VZ", "T", "TMUS", "CHTR"],
    "XLRE": ["PLD", "AMT", "EQIX", "CCI", "PSA", "O", "WELL", "DLR", "SPG", "AVB"],
    "XLB": ["LIN", "APD", "SHW", "FCX", "ECL", "NEM", "DOW", "NUE", "DD", "PPG"],
}


class SectorHeatmapFetcher:
    """Fetches and computes sector/stock heatmap data from yfinance.

    Main entry point is ``fetch_heatmap_data()`` which returns a complete
    HeatmapData snapshot. Internally uses batch ``yf.download()`` via
    ``run_in_executor`` for efficient parallel data retrieval.
    """

    def __init__(self) -> None:
        self._sector_etfs = SECTOR_ETFS
        self._fallback_holdings = FALLBACK_HOLDINGS

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_heatmap_data(self) -> HeatmapData:
        """Fetch a complete market heatmap snapshot.

        Workflow:
            1. Collect all symbols (ETFs + constituents).
            2. Batch-download 1-month price history via ``yf.download()``.
            3. Compute per-stock metrics (change_1d/5d/20d, volume_ratio, market_cap).
            4. Aggregate per-sector breadth and top movers.
            5. Return HeatmapData.

        Returns:
            HeatmapData containing sector and stock entries.
        """
        # Build symbol universe
        etf_symbols = list(self._sector_etfs.keys())
        stock_symbols_by_sector: dict[str, list[str]] = {}
        for etf, sector in self._sector_etfs.items():
            stock_symbols_by_sector[sector] = self._fallback_holdings.get(etf, [])

        all_stock_symbols: list[str] = []
        for syms in stock_symbols_by_sector.values():
            all_stock_symbols.extend(syms)

        all_symbols = etf_symbols + all_stock_symbols

        # Batch fetch price history
        hist_data = await self._batch_download(all_symbols, period="1mo")

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
                    change_5d=metrics.get("change_5d", 0.0),
                    change_20d=metrics.get("change_20d", 0.0),
                    volume_ratio=metrics.get("volume_ratio", 1.0),
                    market_cap=market_caps.get(symbol, 0.0),
                )
                stocks.append(entry)
                stocks_by_sector[sector].append(entry)

        # Build sector entries
        sectors: list[SectorHeatmapEntry] = []
        for etf, sector in self._sector_etfs.items():
            etf_m = etf_metrics.get(etf, {})
            sector_stocks = stocks_by_sector.get(sector, [])

            # Breadth: fraction with positive 1d change
            positive_count = sum(1 for s in sector_stocks if s.change_1d > 0)
            breadth = positive_count / len(sector_stocks) if sector_stocks else 0.5

            # Top gainers/losers by 1d change
            sorted_by_1d = sorted(sector_stocks, key=lambda s: s.change_1d, reverse=True)
            top_gainers = [s.symbol for s in sorted_by_1d[:3]]
            top_losers = [s.symbol for s in sorted_by_1d[-3:]] if len(sorted_by_1d) >= 3 else [s.symbol for s in reversed(sorted_by_1d)]

            sectors.append(SectorHeatmapEntry(
                name=sector,
                etf=etf,
                change_1d=etf_m.get("change_1d", 0.0),
                change_5d=etf_m.get("change_5d", 0.0),
                change_20d=etf_m.get("change_20d", 0.0),
                breadth=breadth,
                top_gainers=top_gainers,
                top_losers=top_losers,
                stock_count=len(sector_stocks),
            ))

        market_status = self._determine_market_status()

        logger.info(
            f"Heatmap fetched: {len(sectors)} sectors, {len(stocks)} stocks, "
            f"market_status={market_status}"
        )

        return HeatmapData(
            sectors=sectors,
            stocks=stocks,
            timestamp=datetime.utcnow(),
            market_status=market_status,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _batch_download(
        self,
        symbols: list[str],
        period: str = "1mo",
    ) -> dict[str, Any]:
        """Batch download price history using yf.download() in executor.

        Results are cached with a 5-minute TTL keyed on the sorted symbol
        list and period to avoid redundant network calls.

        Returns:
            Dict mapping symbol -> pandas DataFrame of OHLCV data.
            Symbols that failed will be absent from the dict.
        """
        cache_key = "batch:" + hashlib.sha256(
            f"{sorted(symbols)}:{period}".encode()
        ).hexdigest()[:16]

        cached = _get_cached(cache_key)
        if cached is not None:
            logger.debug("Batch download cache hit (%d symbols)", len(symbols))
            return cached

        loop = asyncio.get_event_loop()

        def _download() -> Any:
            try:
                data = yf.download(
                    tickers=symbols,
                    period=period,
                    group_by="ticker",
                    threads=True,
                    progress=False,
                )
                return data
            except Exception as e:
                logger.error(f"Batch download failed: {e}")
                return None

        raw = await loop.run_in_executor(None, _download)
        if raw is None:
            return {}

        result: dict[str, Any] = {}
        # When downloading multiple tickers, columns are MultiIndex (ticker, field).
        # For a single ticker, it's a flat DataFrame.
        if len(symbols) == 1:
            sym = symbols[0]
            if not raw.empty:
                result[sym] = raw
        else:
            for sym in symbols:
                try:
                    df = raw[sym] if sym in raw.columns.get_level_values(0) else None
                    if df is not None and not df.dropna(how="all").empty:
                        result[sym] = df
                except Exception as e:
                    logger.debug(f"Skipping symbol {sym} in batch result: {e}")
                    continue

        _set_cache(cache_key, result)
        return result

    def _compute_metrics(
        self,
        hist_data: dict[str, Any],
        symbol: str,
    ) -> dict[str, float] | None:
        """Compute price change and volume metrics for a single symbol.

        Returns:
            Dict with price, change_1d, change_5d, change_20d, volume_ratio.
            None if data is insufficient.
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

            change_5d = 0.0
            if len(closes) >= 6:
                prev_5d = float(closes.iloc[-6])
                change_5d = ((current / prev_5d) - 1) * 100 if prev_5d else 0.0

            change_20d = 0.0
            if len(closes) >= 2:
                first = float(closes.iloc[0])
                change_20d = ((current / first) - 1) * 100 if first else 0.0

            # Volume ratio: latest volume / 20-day average
            volumes = df["Volume"].dropna()
            volume_ratio = 1.0
            if len(volumes) >= 2:
                avg_vol = float(volumes.iloc[:-1].mean())
                latest_vol = float(volumes.iloc[-1])
                if avg_vol > 0:
                    volume_ratio = latest_vol / avg_vol

            return {
                "price": current,
                "change_1d": change_1d,
                "change_5d": change_5d,
                "change_20d": change_20d,
                "volume_ratio": volume_ratio,
            }
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
        loop = asyncio.get_event_loop()

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
            with ThreadPoolExecutor(max_workers=20) as executor:
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

    # --- Sector Performance Table ---
    lines.append("### Sector Performance")
    lines.append("| Sector | ETF | 1D | 5D | 20D | Breadth | Stocks |")
    lines.append("|--------|-----|-----|-----|------|---------|--------|")

    sorted_sectors = sorted(data.sectors, key=lambda s: s.change_1d, reverse=True)
    for s in sorted_sectors:
        breadth_pct = f"{s.breadth * 100:.0f}%"
        lines.append(
            f"| {s.name} | {s.etf} | {s.change_1d:+.2f}% | {s.change_5d:+.2f}% "
            f"| {s.change_20d:+.2f}% | {breadth_pct} | {s.stock_count} |"
        )
    lines.append("")

    # --- Top 5 Gainers / Losers across all stocks ---
    if data.stocks:
        sorted_stocks = sorted(data.stocks, key=lambda s: s.change_1d, reverse=True)

        lines.append("### Top 5 Gainers (1D)")
        for s in sorted_stocks[:5]:
            lines.append(
                f"- {s.symbol} ({s.sector}): {s.change_1d:+.2f}% "
                f"| 5D: {s.change_5d:+.2f}% | Vol ratio: {s.volume_ratio:.1f}x"
            )
        lines.append("")

        lines.append("### Top 5 Losers (1D)")
        for s in sorted_stocks[-5:]:
            lines.append(
                f"- {s.symbol} ({s.sector}): {s.change_1d:+.2f}% "
                f"| 5D: {s.change_5d:+.2f}% | Vol ratio: {s.volume_ratio:.1f}x"
            )
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
            lines.append(
                f"- {s.symbol} ({s.sector}): {s.change_1d:+.2f}% "
                f"| Vol: {s.volume_ratio:.1f}x | Cap: ${s.market_cap:.1f}B"
            )
        lines.append("")

    # --- Breadth Summary ---
    lines.append("### Breadth Summary")
    for s in sorted_sectors:
        bar_len = int(s.breadth * 20)
        bar = "#" * bar_len + "." * (20 - bar_len)
        lines.append(f"  {s.name:25s} [{bar}] {s.breadth * 100:.0f}%")

    return "\n".join(lines)


# Module singleton
_fetcher: SectorHeatmapFetcher | None = None


def get_heatmap_fetcher() -> SectorHeatmapFetcher:
    """Get or create the singleton SectorHeatmapFetcher instance."""
    global _fetcher
    if _fetcher is None:
        _fetcher = SectorHeatmapFetcher()
    return _fetcher
