"""Sector relative strength momentum system.

Computes quantitative momentum metrics for the 11 GICS sector ETFs relative
to SPY across 1-week, 1-month, and 3-month timeframes. Produces ranked tables
and rotation signals for LLM consumption.

The module operates in two modes:
1. From existing HeatmapData (fast, synchronous, uses change_5d/change_20d/change_60d)
2. Fresh fetch (async, fetches its own 3-month price history)

Integration point: format_heatmap_for_llm() in heatmap_fetcher.py appends the
ranked momentum table to the heatmap context.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from analysis.agents.heatmap_interfaces import SectorHeatmapEntry  # type: ignore[import-not-found]

from analysis.sectors import SECTOR_ETFS as SECTOR_ETF_NAMES  # noqa: F401 (live proxy, not a static copy)

logger = logging.getLogger(__name__)

# Composite score weights
WEIGHT_1W = 0.20
WEIGHT_1M = 0.40
WEIGHT_3M = 0.40


@dataclass
class SectorMomentumData:
    """Quantitative momentum metrics for a single sector ETF."""

    symbol: str
    sector: str
    rs_1w: float = 0.0    # 1-week relative strength vs SPY (%)
    rs_1m: float = 0.0    # 1-month relative strength vs SPY (%)
    rs_3m: float = 0.0    # 3-month relative strength vs SPY (%)
    abs_1w: float = 0.0   # absolute 1-week return (%)
    abs_1m: float = 0.0   # absolute 1-month return (%)
    abs_3m: float = 0.0   # absolute 3-month return (%)
    momentum_score: float = 0.0  # composite: weighted RS across timeframes
    rank: int = 0         # 1 = strongest momentum
    quartile: int = 2     # 1 = top quartile, 4 = bottom quartile
    signal: str = "STEADY"  # ACCELERATING | STEADY | DECELERATING | LAGGING

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "symbol": self.symbol,
            "sector": self.sector,
            "rs_1w": self.rs_1w,
            "rs_1m": self.rs_1m,
            "rs_3m": self.rs_3m,
            "abs_1w": self.abs_1w,
            "abs_1m": self.abs_1m,
            "abs_3m": self.abs_3m,
            "momentum_score": self.momentum_score,
            "rank": self.rank,
            "quartile": self.quartile,
            "signal": self.signal,
        }


def compute_sector_momentum_from_heatmap(
    sectors: list[SectorHeatmapEntry],
) -> list[SectorMomentumData]:
    """Compute momentum rankings from existing HeatmapData sectors.

    Uses change_5d (≈1W), change_20d (≈1M), and change_60d (≈3M, if available)
    that are already fetched by the heatmap pipeline. No additional I/O needed.

    Args:
        sectors: List of SectorHeatmapEntry from HeatmapData.

    Returns:
        List of SectorMomentumData sorted by momentum_score descending.
        Returns empty list if SPY benchmark is missing.
    """
    # Build lookup by ETF symbol
    by_etf: dict[str, SectorHeatmapEntry] = {s.etf: s for s in sectors if s.etf}

    spy = by_etf.get("SPY")
    if not spy:
        # Estimate SPY from sector average as fallback
        all_5d = [s.change_5d for s in sectors if s.etf in SECTOR_ETF_NAMES]
        all_20d = [s.change_20d for s in sectors if s.etf in SECTOR_ETF_NAMES]
        spy_5d = sum(all_5d) / len(all_5d) if all_5d else 0.0
        spy_20d = sum(all_20d) / len(all_20d) if all_20d else 0.0

        class _FakeSPY:
            change_5d = spy_5d
            change_20d = spy_20d
            change_60d: float | None = None

        spy = _FakeSPY()  # type: ignore[assignment]

    spy_1w = getattr(spy, "change_5d", 0.0) or 0.0
    spy_1m = getattr(spy, "change_20d", 0.0) or 0.0
    spy_3m = getattr(spy, "change_60d", None)

    results: list[SectorMomentumData] = []

    for etf, name in SECTOR_ETF_NAMES.items():
        s = by_etf.get(etf)
        if not s:
            continue

        abs_1w = s.change_5d or 0.0
        abs_1m = s.change_20d or 0.0
        abs_3m = getattr(s, "change_60d", None)

        rs_1w = round(abs_1w - spy_1w, 2)
        rs_1m = round(abs_1m - spy_1m, 2)

        # 3M: use if both available, otherwise weight down
        if abs_3m is not None and spy_3m is not None:
            rs_3m = round(abs_3m - spy_3m, 2)
            score = round(WEIGHT_1W * rs_1w + WEIGHT_1M * rs_1m + WEIGHT_3M * rs_3m, 3)
        else:
            rs_3m = 0.0
            # Rebalance weights to 1W + 1M only
            score = round(0.33 * rs_1w + 0.67 * rs_1m, 3)

        results.append(SectorMomentumData(
            symbol=etf,
            sector=name,
            rs_1w=rs_1w,
            rs_1m=rs_1m,
            rs_3m=rs_3m,
            abs_1w=round(abs_1w, 2),
            abs_1m=round(abs_1m, 2),
            abs_3m=round(abs_3m, 2) if abs_3m is not None else 0.0,
            momentum_score=score,
        ))

    return _assign_ranks_and_signals(results)


async def compute_sector_momentum() -> list[SectorMomentumData]:
    """Fetch fresh 3-month price data and compute full momentum rankings.

    Fetches SPY + 11 sector ETFs via yfinance (3mo period) and computes
    1W, 1M, 3M relative strength independently of the heatmap pipeline.
    Intended for standalone use or when heatmap data is not yet available.

    Returns:
        List of SectorMomentumData sorted by momentum_score descending.
    """
    try:
        import yfinance as yf
        loop = asyncio.get_running_loop()

        symbols = ["SPY"] + list(SECTOR_ETF_NAMES.keys())

        async def _fetch(sym: str) -> tuple[str, Any]:
            ticker = yf.Ticker(sym)
            hist = await loop.run_in_executor(
                None, lambda t=ticker: t.history(period="3mo")
            )
            return sym, hist

        raw = await asyncio.gather(*[_fetch(s) for s in symbols], return_exceptions=True)

        price_data: dict[str, dict[str, float]] = {}
        for r in raw:
            if isinstance(r, Exception):
                continue
            sym, hist = r
            if hist is None or hist.empty or len(hist) < 5:
                continue
            closes = hist["Close"]
            cur = float(closes.iloc[-1])

            def _ret(n: int) -> float:
                if len(closes) >= n:
                    ref = float(closes.iloc[-n])
                    return ((cur / ref) - 1) * 100 if ref else 0.0
                return 0.0

            price_data[sym] = {
                "r_1w": round(_ret(5), 2),
                "r_1m": round(_ret(21), 2),
                "r_3m": round(_ret(63), 2),
            }

        spy_d = price_data.get("SPY", {"r_1w": 0.0, "r_1m": 0.0, "r_3m": 0.0})
        results: list[SectorMomentumData] = []

        for etf, name in SECTOR_ETF_NAMES.items():
            d = price_data.get(etf)
            if not d:
                continue
            rs_1w = round(d["r_1w"] - spy_d["r_1w"], 2)
            rs_1m = round(d["r_1m"] - spy_d["r_1m"], 2)
            rs_3m = round(d["r_3m"] - spy_d["r_3m"], 2)
            score = round(WEIGHT_1W * rs_1w + WEIGHT_1M * rs_1m + WEIGHT_3M * rs_3m, 3)

            results.append(SectorMomentumData(
                symbol=etf,
                sector=name,
                rs_1w=rs_1w,
                rs_1m=rs_1m,
                rs_3m=rs_3m,
                abs_1w=d["r_1w"],
                abs_1m=d["r_1m"],
                abs_3m=d["r_3m"],
                momentum_score=score,
            ))

        return _assign_ranks_and_signals(results)

    except Exception as e:
        logger.warning(f"Sector momentum fetch failed: {e}")
        return []


def _assign_ranks_and_signals(data: list[SectorMomentumData]) -> list[SectorMomentumData]:
    """Sort by score, assign rank, quartile, and signal labels."""
    data.sort(key=lambda x: x.momentum_score, reverse=True)
    n = len(data)

    for i, item in enumerate(data):
        item.rank = i + 1
        # Quartile: 1=top 25%, 4=bottom 25%
        rank_pct = i / max(n - 1, 1)
        item.quartile = min(int(rank_pct * 4) + 1, 4)

        # Signal based on composite score magnitude
        if item.momentum_score > 2.0:
            item.signal = "ACCELERATING"
        elif item.momentum_score > 0.3:
            item.signal = "STEADY"
        elif item.momentum_score > -1.5:
            item.signal = "DECELERATING"
        else:
            item.signal = "LAGGING"

    return data


def format_momentum_table(momentum_data: list[SectorMomentumData]) -> str:
    """Format sector momentum rankings as a text table for LLM consumption.

    Args:
        momentum_data: List of SectorMomentumData (sorted by score).

    Returns:
        Formatted string with ranked table and rotation signals section.
        Returns empty string if momentum_data is empty.
    """
    if not momentum_data:
        return ""

    has_3m = any(d.rs_3m != 0.0 for d in momentum_data)

    lines: list[str] = ["=== SECTOR MOMENTUM RANKINGS (Relative to SPY) ==="]

    if has_3m:
        header = f"{'Rank':<5} {'ETF':<6} {'Sector':<22} {'1W RS':>7} {'1M RS':>7} {'3M RS':>7} {'Score':>7}  Signal"
        divider = "-" * 73
    else:
        header = f"{'Rank':<5} {'ETF':<6} {'Sector':<22} {'1W RS':>7} {'1M RS':>7} {'Score':>7}  Signal"
        divider = "-" * 63

    lines += [header, divider]

    for d in momentum_data:
        if has_3m:
            lines.append(
                f"{d.rank:<5} {d.symbol:<6} {d.sector:<22} "
                f"{d.rs_1w:>+6.1f}% {d.rs_1m:>+6.1f}% {d.rs_3m:>+6.1f}% "
                f"{d.momentum_score:>+6.2f}  {d.signal}"
            )
        else:
            lines.append(
                f"{d.rank:<5} {d.symbol:<6} {d.sector:<22} "
                f"{d.rs_1w:>+6.1f}% {d.rs_1m:>+6.1f}% "
                f"{d.momentum_score:>+6.2f}  {d.signal}"
            )

    # Rotation signals summary
    accelerating = [d for d in momentum_data if d.signal == "ACCELERATING"]
    lagging = [d for d in momentum_data if d.signal == "LAGGING"]

    if accelerating or lagging:
        lines.append("")
        lines.append("ROTATION SIGNALS:")
        for d in accelerating[:3]:
            lines.append(f"  + {d.symbol} ({d.sector}): momentum accelerating (score {d.momentum_score:+.2f})")
        for d in lagging[:3]:
            lines.append(f"  - {d.symbol} ({d.sector}): momentum lagging (score {d.momentum_score:+.2f})")

    return "\n".join(lines)
