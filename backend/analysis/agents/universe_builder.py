"""Dynamic stock/commodity screening universe builder.

Builds a diversified screening universe of 300-500 symbols at runtime by
combining ETF constituent holdings, commodity futures, international ADRs,
and dynamically-fetched top movers. Results are cached with a 1-hour TTL.

All blocking yfinance calls are wrapped with run_in_executor() for async
compatibility. Concurrent yfinance calls are limited by an asyncio.Semaphore.
Per-ETF failures are handled gracefully without failing the entire universe.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import yfinance as yf  # type: ignore[import-untyped]

from analysis.agents.heatmap_fetcher import (  # type: ignore[import-not-found]
    FALLBACK_HOLDINGS,
    SECTOR_ETFS,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Static symbol sets (these rarely change)
# ---------------------------------------------------------------------------

COMMODITY_SYMBOLS: dict[str, list[str]] = {
    "Commodities": [
        "GC=F",   # Gold
        "SI=F",   # Silver
        "CL=F",   # Crude Oil WTI
        "BZ=F",   # Brent Crude
        "NG=F",   # Natural Gas
        "HG=F",   # Copper
        "PL=F",   # Platinum
        "ZW=F",   # Wheat
        "ZC=F",   # Corn
        "ZS=F",   # Soybeans
        "KC=F",   # Coffee
        "CT=F",   # Cotton
        "LBS=F",  # Lumber
    ]
}

INTERNATIONAL_ADRS: dict[str, list[str]] = {
    "International": [
        "TSM", "ASML", "NVO", "BABA", "SAP", "TM", "SONY",
        "SHOP", "SE", "MELI", "NU", "GRAB", "RIVN",
    ]
}

# Additional well-known large/mid-caps to pad the universe when ETF
# holdings fetch returns fewer symbols than expected.
_SUPPLEMENTAL_SYMBOLS: dict[str, list[str]] = {
    "Technology": [
        "INTC", "QCOM", "TXN", "INTU", "NOW", "AMAT", "LRCX", "KLAC",
        "SNPS", "CDNS", "MRVL", "PANW", "FTNT", "CRWD", "ZS",
    ],
    "Financials": [
        "AXP", "SCHW", "ICE", "CME", "CB", "PGR", "MET", "AIG",
        "TFC", "USB",
    ],
    "Healthcare": [
        "ISRG", "GILD", "VRTX", "REGN", "ZTS", "SYK", "BDX", "EW",
        "IDXX", "DXCM",
    ],
    "Consumer Discretionary": [
        "GM", "F", "ABNB", "DASH", "ORLY", "AZO", "ROST", "DHI",
        "LEN", "POOL",
    ],
    "Industrials": [
        "GD", "NOC", "WM", "RSG", "CTAS", "ITW", "EMR", "FDX",
        "CSX", "NSC",
    ],
    "Energy": [
        "WMB", "HAL", "BKR", "FANG", "TRGP", "KMI", "OKE", "HES",
    ],
    "Communication Services": [
        "SPOT", "SNAP", "PINS", "ROKU", "ZM", "MTCH", "EA", "TTWO",
    ],
    "Consumer Staples": [
        "STZ", "SYY", "HSY", "K", "GIS", "TSN", "ADM", "BG",
    ],
    "Materials": [
        "CTVA", "VMC", "MLM", "ALB", "CE", "EMN", "IFF", "FMC",
    ],
    "Utilities": [
        "WEC", "ES", "AEE", "CMS", "DTE", "FE", "PPL", "EVRG",
    ],
    "Real Estate": [
        "VICI", "IRM", "SBAC", "EXR", "MAA", "ESS", "UDR", "CPT",
    ],
}

# Map ETF ticker -> sector name (reverse of SECTOR_ETFS for convenience)
_ETF_TO_SECTOR: dict[str, str] = SECTOR_ETFS  # already etf -> sector

# ---------------------------------------------------------------------------
# Module-level cache (1-hour TTL)
# ---------------------------------------------------------------------------

_universe_cache: dict[str, Any] = {"data": None, "timestamp": 0.0}
_UNIVERSE_TTL = 3600  # 1 hour

# Semaphore to limit concurrent yfinance calls
_yf_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """Lazy-init the semaphore (must be created inside a running event loop)."""
    global _yf_semaphore
    if _yf_semaphore is None:
        _yf_semaphore = asyncio.Semaphore(10)
    return _yf_semaphore


# ---------------------------------------------------------------------------
# ETF holdings fetcher
# ---------------------------------------------------------------------------


def _fetch_etf_holdings_sync(etf_ticker: str, top_n: int = 25) -> list[str]:
    """Synchronously fetch top N holdings for an ETF via yfinance.

    Tries multiple yfinance access patterns since the API evolves across
    versions. Returns an empty list on failure.
    """
    try:
        ticker = yf.Ticker(etf_ticker)

        # Method 1: .holdings property (yfinance >= 0.2.31)
        try:
            holdings_attr: Any = getattr(ticker, "holdings", None)
            if holdings_attr is not None and hasattr(holdings_attr, "index"):
                symbols = holdings_attr.index.tolist()[:top_n]
                if symbols:
                    return [str(s) for s in symbols]
        except Exception as exc:
            logger.debug("Method 1 (holdings attr) failed for %s: %s", etf_ticker, exc)

        # Method 2: .get_holdings() (some yfinance versions)
        try:
            get_holdings = getattr(ticker, "get_holdings", None)
            if callable(get_holdings):
                holdings_result: Any = get_holdings()
                if holdings_result is not None and not holdings_result.empty:
                    # Column may be 'Symbol' or 'Holding Ticker'
                    for col in ["Symbol", "Holding Ticker", "symbol"]:
                        if col in holdings_result.columns:
                            return holdings_result[col].dropna().tolist()[:top_n]
                    # Fallback: use index
                    return holdings_result.index.tolist()[:top_n]
        except Exception as exc:
            logger.debug("Method 2 (get_holdings) failed for %s: %s", etf_ticker, exc)

        # Method 3: ticker.info may contain top holdings tickers
        try:
            info = ticker.info or {}
            holdings = info.get("holdings", [])
            if isinstance(holdings, list) and holdings:
                return [
                    h.get("symbol", h.get("ticker", ""))
                    for h in holdings
                    if isinstance(h, dict)
                ][:top_n]
        except Exception as exc:
            logger.debug("Method 3 (info holdings) failed for %s: %s", etf_ticker, exc)

    except Exception as exc:
        logger.debug("yfinance ETF fetch failed for %s: %s", etf_ticker, exc)

    return []


async def _fetch_single_etf_holdings(
    etf_ticker: str,
    sector_name: str,
    top_n: int = 25,
) -> tuple[str, list[str]]:
    """Fetch holdings for one ETF, respecting the concurrency semaphore.

    Returns (sector_name, list_of_symbols). On failure, returns the
    fallback holdings for that ETF.
    """
    sem = _get_semaphore()
    async with sem:
        loop = asyncio.get_event_loop()
        try:
            symbols = await loop.run_in_executor(
                None, _fetch_etf_holdings_sync, etf_ticker, top_n
            )
            if symbols:
                logger.debug(
                    "Fetched %d holdings for %s (%s)",
                    len(symbols), etf_ticker, sector_name,
                )
                return sector_name, symbols
        except Exception as exc:
            logger.warning(
                "ETF holdings fetch failed for %s: %s — using fallback",
                etf_ticker, exc,
            )

    # Fallback for this specific ETF
    fallback = FALLBACK_HOLDINGS.get(etf_ticker, [])
    if fallback:
        logger.info("Using fallback holdings for %s (%d symbols)", etf_ticker, len(fallback))
    return sector_name, list(fallback)


# ---------------------------------------------------------------------------
# Top movers fetcher
# ---------------------------------------------------------------------------

# Broad universe for screening top movers — major index components
_BROAD_SCREEN_SYMBOLS: list[str] = [
    # S&P 500 additions not covered by sector ETFs
    "BRK-B", "GOOG", "GOOGL", "META", "AMZN", "NVDA", "TSLA",
    "AAPL", "MSFT", "UNH", "LLY", "JPM", "V", "XOM", "MA",
    "JNJ", "PG", "HD", "COST", "ABBV", "MRK", "AVGO", "NFLX",
    "CRM", "PEP", "KO", "ADBE", "AMD", "TMO", "WMT", "CSCO",
    "MCD", "ACN", "ABT", "LIN", "TXN", "ORCL", "DHR", "NKE",
    # High-volatility / popular tickers
    "PLTR", "SOFI", "COIN", "MARA", "SQ", "AFRM", "UPST",
    "ARM", "SMCI", "IONQ", "RKLB", "MSTR",
]


def _fetch_top_movers_sync() -> dict[str, list[str]]:
    """Fetch top daily gainers/losers and volume leaders from a broad list.

    Downloads 5-day history for the broad screen list and identifies:
      - Top 15 gainers (largest positive 1d change)
      - Top 15 losers (largest negative 1d change)
      - Top 10 volume leaders (highest volume ratio vs 5d average)

    Returns dict with keys 'Top Gainers', 'Top Losers', 'Volume Leaders'.
    """
    result: dict[str, list[str]] = {}
    try:
        data = yf.download(
            tickers=_BROAD_SCREEN_SYMBOLS,
            period="5d",
            group_by="ticker",
            threads=False,
            progress=False,
        )
        if data is None or data.empty:
            return result

        changes: list[tuple[str, float]] = []
        volumes: list[tuple[str, float]] = []

        for sym in _BROAD_SCREEN_SYMBOLS:
            try:
                if sym not in data.columns.get_level_values(0):
                    continue
                df = data[sym]
                closes = df["Close"].dropna()
                if len(closes) < 2:
                    continue
                change = ((float(closes.iloc[-1]) / float(closes.iloc[-2])) - 1) * 100
                changes.append((sym, change))

                vols = df["Volume"].dropna()
                if len(vols) >= 2:
                    avg_vol = float(vols.iloc[:-1].mean())
                    if avg_vol > 0:
                        vol_ratio = float(vols.iloc[-1]) / avg_vol
                        volumes.append((sym, vol_ratio))
            except Exception as exc:
                logger.debug("Skipping symbol %s in top movers: %s", sym, exc)
                continue

        # Sort and extract
        changes.sort(key=lambda x: x[1], reverse=True)
        if changes:
            result["Top Gainers"] = [s for s, _ in changes[:15]]
            result["Top Losers"] = [s for s, _ in changes[-15:]]

        volumes.sort(key=lambda x: x[1], reverse=True)
        if volumes:
            result["Volume Leaders"] = [s for s, _ in volumes[:10]]

    except Exception as exc:
        logger.warning("Top movers fetch failed: %s", exc)

    return result


async def _fetch_top_movers() -> dict[str, list[str]]:
    """Async wrapper for top movers fetch."""
    sem = _get_semaphore()
    async with sem:
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, _fetch_top_movers_sync)
        except Exception as exc:
            logger.warning("Top movers async fetch failed: %s", exc)
            return {}


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------


async def get_screening_universe() -> dict[str, list[str]]:
    """Return sector/category -> symbols mapping (300-500 symbols, 1h TTL cache).

    Combines four symbol sources:
        1. Dynamic ETF holdings (top 25 per sector ETF)
        2. Commodity futures (hardcoded)
        3. International ADRs (hardcoded)
        4. Top daily movers (gainers, losers, volume leaders)

    Falls back to FALLBACK_HOLDINGS + static sets if all dynamic fetching fails.
    """
    # Check cache
    if (
        _universe_cache["data"] is not None
        and time.time() - _universe_cache["timestamp"] < _UNIVERSE_TTL
    ):
        logger.debug("Universe cache hit")
        return _universe_cache["data"]

    logger.info("Building screening universe (cache miss or expired)...")

    universe: dict[str, list[str]] = {}
    dynamic_succeeded = False

    # 1. Fetch ETF holdings in parallel
    try:
        etf_tasks = [
            _fetch_single_etf_holdings(etf, sector)
            for etf, sector in _ETF_TO_SECTOR.items()
        ]
        etf_results = await asyncio.gather(*etf_tasks, return_exceptions=True)

        for etf_result in etf_results:
            if isinstance(etf_result, BaseException):
                logger.warning("ETF holdings task failed: %s", etf_result)
                continue
            sector_name, symbols = etf_result
            if symbols:
                dynamic_succeeded = True
                universe[sector_name] = symbols

    except Exception as exc:
        logger.warning("ETF holdings parallel fetch failed entirely: %s", exc)

    # Pad sectors with supplemental symbols if below target
    for sector_name, supplements in _SUPPLEMENTAL_SYMBOLS.items():
        existing = set(universe.get(sector_name, []))
        if len(existing) < 20:
            # Add supplemental symbols not already present
            for sym in supplements:
                if sym not in existing:
                    universe.setdefault(sector_name, []).append(sym)
                    existing.add(sym)

    # 2. Add commodity futures
    universe.update(COMMODITY_SYMBOLS)

    # 3. Add international ADRs
    universe.update(INTERNATIONAL_ADRS)

    # 4. Fetch top movers
    try:
        movers = await _fetch_top_movers()
        if movers:
            dynamic_succeeded = True
            universe.update(movers)
    except Exception as exc:
        logger.warning("Top movers fetch failed: %s", exc)

    # Fallback: if no dynamic data at all, use FALLBACK_HOLDINGS
    if not dynamic_succeeded:
        logger.warning(
            "All dynamic fetching failed — falling back to static holdings"
        )
        # Convert FALLBACK_HOLDINGS (keyed by ETF ticker) to sector names
        fallback_by_sector: dict[str, list[str]] = {}
        for etf, symbols in FALLBACK_HOLDINGS.items():
            sector: str = _ETF_TO_SECTOR[etf] if etf in _ETF_TO_SECTOR else etf
            fallback_by_sector[sector] = list(symbols)
        universe = {**fallback_by_sector, **COMMODITY_SYMBOLS, **INTERNATIONAL_ADRS}

    # Deduplicate symbols within each category
    for key in universe:
        seen: set[str] = set()
        deduped: list[str] = []
        for sym in universe[key]:
            if sym not in seen:
                seen.add(sym)
                deduped.append(sym)
        universe[key] = deduped

    # Log summary
    total = sum(len(v) for v in universe.values())
    logger.info(
        "Screening universe built: %d categories, %d total symbols",
        len(universe), total,
    )
    for cat, syms in sorted(universe.items()):
        logger.debug("  %s: %d symbols", cat, len(syms))

    # Update cache
    _universe_cache["data"] = universe
    _universe_cache["timestamp"] = time.time()

    return universe


def get_all_universe_symbols() -> list[str]:
    """Synchronous: return flat list of all symbols from cache (or fallback).

    If the cache is populated, returns all symbols from it. Otherwise,
    falls back to FALLBACK_HOLDINGS + static sets without making any
    network calls.
    """
    if (
        _universe_cache["data"] is not None
        and time.time() - _universe_cache["timestamp"] < _UNIVERSE_TTL
    ):
        symbols: list[str] = []
        for syms in _universe_cache["data"].values():
            symbols.extend(syms)
        return list(dict.fromkeys(symbols))  # dedupe preserving order

    # Fallback: static holdings + commodities + ADRs
    logger.debug("get_all_universe_symbols: no cache, using fallback")
    symbols = []
    for etf, sector in _ETF_TO_SECTOR.items():
        symbols.extend(FALLBACK_HOLDINGS.get(etf, []))
    for syms in COMMODITY_SYMBOLS.values():
        symbols.extend(syms)
    for syms in INTERNATIONAL_ADRS.values():
        symbols.extend(syms)
    for syms in _SUPPLEMENTAL_SYMBOLS.values():
        symbols.extend(syms)
    return list(dict.fromkeys(symbols))


def get_commodity_symbols() -> list[str]:
    """Return commodity futures symbols."""
    return list(COMMODITY_SYMBOLS["Commodities"])
