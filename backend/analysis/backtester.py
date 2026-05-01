"""Factor backtester for the alpha engine.

Computes information coefficients (IC) for each technical signal against
forward returns, then derives calibrated factor weights and a historical
return distribution that grounds the synthesis upside estimates.

Usage:
    results = await run_backtest(db)
    # results saved to data/backtest_calibration.json
"""
from __future__ import annotations

import json
import logging
import math
import statistics
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

CALIBRATION_PATH = Path(__file__).parent.parent / "data" / "backtest_calibration.json"

# Minimum rows for a symbol to be included in backtest
MIN_HISTORY_ROWS = 120  # ~6 months trading days
# Monthly snapshot interval (trading days)
SNAPSHOT_INTERVAL_DAYS = 21
# Forward return horizons to evaluate
FORWARD_HORIZONS = [20, 45, 90]
# Minimum observations to report IC as reliable
MIN_IC_OBSERVATIONS = 30


# ---------------------------------------------------------------------------
# Signal computation (mirrors alpha_engine._score_basic_technical logic)
# ---------------------------------------------------------------------------

def _pct(closes: list[float], n: int) -> float | None:
    if len(closes) < n + 1 or closes[-n - 1] == 0:
        return None
    return (closes[-1] / closes[-n - 1] - 1.0) * 100.0


def _vol_ratio(volumes: list[float], n: int = 20) -> float | None:
    if len(volumes) < n + 1:
        return None
    avg = statistics.mean(volumes[-n - 1:-1]) if volumes[-n - 1:-1] else None
    if not avg:
        return None
    return volumes[-1] / avg


def _safe_mean(vals: list[float]) -> float | None:
    finite = [v for v in vals if v is not None and math.isfinite(v)]
    return statistics.mean(finite) if finite else None


def _safe_std(vals: list[float]) -> float | None:
    finite = [v for v in vals if v is not None and math.isfinite(v)]
    return statistics.stdev(finite) if len(finite) >= 2 else None


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def compute_signals(
    closes: list[float],
    volumes: list[float],
    spy_closes: list[float] | None,
) -> dict[str, float] | None:
    """Compute the technical signals used by alpha_engine at a given as-of date.

    Returns None if there is insufficient data.
    """
    if len(closes) < 65:  # need 60 for ret_60 + buffer
        return None

    ret_5 = _pct(closes, 5)
    ret_20 = _pct(closes, 20)
    ret_60 = _pct(closes, 60)
    if ret_20 is None:
        return None

    spy_20 = _pct(spy_closes, 20) if spy_closes and len(spy_closes) >= 21 else 0.0
    spy_5 = _pct(spy_closes, 5) if spy_closes and len(spy_closes) >= 6 else 0.0

    rel_strength = (ret_20 - (spy_20 or 0.0)) * 2.0 + ((ret_5 or 0.0) - (spy_5 or 0.0))
    accel = (ret_5 or 0.0) - ret_20
    vol_r = _vol_ratio(volumes) or 1.0
    avg_20 = _safe_mean(closes[-20:]) or closes[-1]
    avg_50 = _safe_mean(closes[-50:]) or closes[-1]
    above_20 = 1.0 if closes[-1] >= avg_20 else 0.0
    above_50 = 1.0 if closes[-1] >= avg_50 else 0.0
    daily_rets = [
        (closes[i] / closes[i - 1] - 1.0) * 100.0
        for i in range(max(1, len(closes) - 20), len(closes))
        if closes[i - 1]
    ]
    volatility = _safe_std(daily_rets) or 0.0

    # Composite technical score (mirrors alpha_engine formula exactly)
    tech_score = (
        0.30 * _clamp((ret_20 + 25) / 50, 0, 1) * 100
        + 0.25 * _clamp((rel_strength + 35) / 70, 0, 1) * 100
        + 0.10 * _clamp((accel + 20) / 40, 0, 1) * 100
        + 0.10 * _clamp((vol_r - 0.5) / 2.5, 0, 1) * 100
        + 0.10 * (above_20 + above_50) / 2 * 100
        + 0.05 * _clamp((vol_r - 0.5) / 2.5, 0, 1) * 100  # flow_proxy component
    )
    tech_score = _clamp(tech_score, 0, 100)

    return {
        "ret_20": ret_20,
        "ret_60": ret_60 or 0.0,
        "rel_strength": rel_strength,
        "accel": accel,
        "vol_ratio": vol_r,
        "above_ma": (above_20 + above_50) / 2,
        "volatility": volatility,
        "tech_score": tech_score,
    }


# ---------------------------------------------------------------------------
# IC (Spearman rank correlation)
# ---------------------------------------------------------------------------

def _rank(vals: list[float]) -> list[float]:
    """Convert values to ranks (1-based, avg for ties)."""
    indexed = sorted(enumerate(vals), key=lambda x: x[1])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(indexed):
        j = i
        while j < len(indexed) - 1 and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


def spearman_ic(signals: list[float], returns: list[float]) -> float | None:
    """Spearman rank correlation between signals and forward returns."""
    n = len(signals)
    if n < MIN_IC_OBSERVATIONS:
        return None
    rs = _rank(signals)
    rr = _rank(returns)
    cov = sum((rs[i] - (n + 1) / 2) * (rr[i] - (n + 1) / 2) for i in range(n)) / n
    vs = math.sqrt(sum((r - (n + 1) / 2) ** 2 for r in rs) / n)
    vr = math.sqrt(sum((r - (n + 1) / 2) ** 2 for r in rr) / n)
    if vs == 0 or vr == 0:
        return None
    return cov / (vs * vr)


# ---------------------------------------------------------------------------
# Quintile analysis
# ---------------------------------------------------------------------------

def quintile_stats(
    signals: list[float],
    returns: list[float],
    spy_returns: list[float],
) -> dict[str, Any]:
    """Per-quintile average return and excess return vs SPY."""
    n = len(signals)
    if n < 10:
        return {}
    paired = sorted(zip(signals, returns, spy_returns), key=lambda x: x[0])
    q_size = n // 5
    result = {}
    for q in range(5):
        start, end = q * q_size, (q + 1) * q_size if q < 4 else n
        bucket = paired[start:end]
        rets = [r for _, r, _ in bucket]
        spy_r = [s for _, _, s in bucket]
        excess = [r - s for r, s in zip(rets, spy_r)]
        hit_rate = sum(1 for e in excess if e > 0) / len(excess) if excess else 0
        result[f"Q{q + 1}"] = {
            "mean_return": round(_safe_mean(rets) or 0.0, 3),
            "mean_excess": round(_safe_mean(excess) or 0.0, 3),
            "hit_rate": round(hit_rate, 3),
            "n": len(bucket),
        }
    return result


# ---------------------------------------------------------------------------
# Main backtest runner
# ---------------------------------------------------------------------------

async def _load_price_matrix(db: AsyncSession) -> dict[str, dict[str, Any]]:
    """Load all price data keyed by symbol. Returns {symbol: {dates: [], closes: [], volumes: []}}."""
    result = await db.execute(text("""
        SELECT s.symbol, ph.date, ph.close, ph.volume
        FROM stocks s
        JOIN price_history ph ON s.id = ph.stock_id
        WHERE s.is_active = 1
        ORDER BY s.symbol, ph.date
    """))
    rows = result.fetchall()

    matrix: dict[str, dict[str, Any]] = {}
    for symbol, d, close, volume in rows:
        if symbol not in matrix:
            matrix[symbol] = {"dates": [], "closes": [], "volumes": []}
        matrix[symbol]["dates"].append(d)
        matrix[symbol]["closes"].append(float(close or 0))
        matrix[symbol]["volumes"].append(float(volume or 0))

    # Filter to symbols with enough history
    return {sym: data for sym, data in matrix.items() if len(data["closes"]) >= MIN_HISTORY_ROWS}


async def run_backtest(db: AsyncSession) -> dict[str, Any]:
    """Run the full technical factor backtest. Returns and saves calibration data."""
    logger.info("Loading price matrix from DB...")
    matrix = await _load_price_matrix(db)
    logger.info("Loaded %d symbols with sufficient history", len(matrix))

    if "SPY" not in matrix:
        logger.warning("SPY not in price matrix — relative strength will be zero")

    spy_data = matrix.get("SPY", {})

    # Determine the set of snapshot dates (monthly, from 65 days in to leave room for forward returns)
    # Use SPY or the most data-rich symbol to get all trading dates
    ref_symbol = "SPY" if "SPY" in matrix else max(matrix, key=lambda s: len(matrix[s]["closes"]))
    all_dates = matrix[ref_symbol]["dates"]
    total_days = len(all_dates)

    # snapshots: every SNAPSHOT_INTERVAL_DAYS, starting at day 65, ending so max horizon fits
    max_horizon = max(FORWARD_HORIZONS)
    snapshot_indices = list(range(64, total_days - max_horizon, SNAPSHOT_INTERVAL_DAYS))

    if len(snapshot_indices) < 3:
        return {
            "error": f"Insufficient data: only {total_days} trading days available. Need at least {64 + max_horizon + SNAPSHOT_INTERVAL_DAYS}.",
            "symbols": len(matrix),
            "trading_days": total_days,
        }

    logger.info("Running %d snapshots, %d symbols, horizons=%s",
                len(snapshot_indices), len(matrix), FORWARD_HORIZONS)

    # Collect per-horizon observations: {horizon: {signal_name: [(signal_val, fwd_return, spy_return)]}}
    horizon_obs: dict[int, dict[str, list[tuple[float, float, float]]]] = {
        h: defaultdict(list) for h in FORWARD_HORIZONS
    }

    for snap_idx in snapshot_indices:
        snap_date = all_dates[snap_idx]

        # SPY signal and returns at this snapshot
        spy_closes_snap = spy_data.get("closes", [])[:snap_idx + 1] if spy_data else []

        for symbol, data in matrix.items():
            dates = data["dates"]
            closes = data["closes"]
            volumes = data["volumes"]

            # Find the index corresponding to snap_date in this symbol's data
            # (symbol may not have every trading day)
            try:
                sym_snap_idx = dates.index(snap_date)
            except ValueError:
                # Try nearest date within 3 days
                for offset in range(1, 4):
                    candidate = all_dates[snap_idx - offset] if snap_idx >= offset else None
                    if candidate and candidate in dates:
                        sym_snap_idx = dates.index(candidate)
                        break
                else:
                    continue

            if sym_snap_idx < 64:
                continue

            signals = compute_signals(
                closes[:sym_snap_idx + 1],
                volumes[:sym_snap_idx + 1],
                spy_closes_snap,
            )
            if signals is None:
                continue

            for horizon in FORWARD_HORIZONS:
                fwd_idx = sym_snap_idx + horizon
                if fwd_idx >= len(closes):
                    continue
                if closes[sym_snap_idx] == 0:
                    continue
                fwd_return = (closes[fwd_idx] / closes[sym_snap_idx] - 1.0) * 100.0

                # SPY forward return for excess calculation
                spy_fwd_idx = snap_idx + horizon
                spy_snap_close = spy_closes_snap[-1] if spy_closes_snap else 0
                spy_fwd_close = spy_data["closes"][spy_fwd_idx] if spy_data and spy_fwd_idx < len(spy_data["closes"]) else spy_snap_close
                spy_fwd_return = ((spy_fwd_close / spy_snap_close - 1.0) * 100.0
                                  if spy_snap_close else 0.0)

                for sig_name, sig_val in signals.items():
                    horizon_obs[horizon][sig_name].append((sig_val, fwd_return, spy_fwd_return))

    # Compute ICs and quintile stats per horizon
    calibration: dict[str, Any] = {
        "as_of": date.today().isoformat(),
        "symbols_tested": len(matrix),
        "snapshots": len(snapshot_indices),
        "snapshot_dates": [all_dates[i].isoformat() if hasattr(all_dates[i], "isoformat") else str(all_dates[i]) for i in snapshot_indices],
        "trading_days_available": total_days,
        "horizons": {},
    }

    for horizon in FORWARD_HORIZONS:
        sig_data = horizon_obs[horizon]
        horizon_result: dict[str, Any] = {"signal_ics": {}, "quintiles": {}, "observations": 0}

        # Compute per-signal IC
        for sig_name, obs in sig_data.items():
            if len(obs) < MIN_IC_OBSERVATIONS:
                continue
            signals_list = [o[0] for o in obs]
            returns_list = [o[1] for o in obs]
            spy_list = [o[2] for o in obs]
            ic = spearman_ic(signals_list, returns_list)
            if ic is not None:
                horizon_result["signal_ics"][sig_name] = round(ic, 4)
            horizon_result["observations"] = len(obs)

            # Quintile stats for tech_score (the composite)
            if sig_name == "tech_score":
                horizon_result["quintiles"] = quintile_stats(signals_list, returns_list, spy_list)

        # Calibrated weight: IC-proportional (positive ICs only)
        pos_ics = {k: v for k, v in horizon_result["signal_ics"].items() if v > 0}
        total_ic = sum(pos_ics.values())
        if total_ic > 0:
            horizon_result["calibrated_weights"] = {k: round(v / total_ic, 4) for k, v in pos_ics.items()}

        calibration["horizons"][f"{horizon}d"] = horizon_result

    # Summary for synthesis context
    calibration["synthesis_context"] = _build_synthesis_context(calibration)

    # Save to disk
    CALIBRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CALIBRATION_PATH, "w") as f:
        json.dump(calibration, f, indent=2)
    logger.info("Calibration saved to %s", CALIBRATION_PATH)

    return calibration


def _build_synthesis_context(cal: dict[str, Any]) -> dict[str, Any]:
    """Distil calibration into a compact dict for the synthesis LLM prompt."""
    ctx: dict[str, Any] = {}
    for horizon_key, hdata in cal.get("horizons", {}).items():
        q = hdata.get("quintiles", {})
        if not q:
            continue
        q1 = q.get("Q5", {})  # Q5 = highest signal rank (we sort ascending, Q5 is top)
        q5 = q.get("Q1", {})  # Q1 = lowest signal rank
        ic_composite = hdata.get("signal_ics", {}).get("tech_score")
        ctx[horizon_key] = {
            "ic_composite": ic_composite,
            "top_quintile_mean_excess_pct": q1.get("mean_excess"),
            "top_quintile_hit_rate": q1.get("hit_rate"),
            "bottom_quintile_mean_excess_pct": q5.get("mean_excess"),
            "n_observations": hdata.get("observations", 0),
        }
    return ctx


def load_calibration() -> dict[str, Any] | None:
    """Load saved calibration from disk. Returns None if not available."""
    if not CALIBRATION_PATH.exists():
        return None
    try:
        with open(CALIBRATION_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def format_calibration_for_prompt(cal: dict[str, Any] | None) -> str:
    """Format calibration data as a concise block for the synthesis LLM."""
    if not cal:
        return ""
    ctx = cal.get("synthesis_context", {})
    if not ctx:
        return ""

    lines = [
        f"### Historical Signal Calibration (backtested {cal.get('symbols_tested', '?')} symbols, "
        f"{cal.get('snapshots', '?')} monthly snapshots)",
    ]
    for horizon_key, hdata in ctx.items():
        ic = hdata.get("ic_composite")
        top_excess = hdata.get("top_quintile_mean_excess_pct")
        hit_rate = hdata.get("top_quintile_hit_rate")
        n = hdata.get("n_observations", 0)
        if ic is None:
            continue
        lines.append(
            f"- {horizon_key}: IC={ic:+.3f}, top-quintile stocks averaged "
            f"{top_excess:+.1f}% excess vs SPY (hit rate {hit_rate:.0%}), n={n}"
        )

    if len(lines) == 1:
        return ""

    lines.append(
        "Use these empirical ranges — not analyst targets — to anchor upside_pct estimates. "
        "A top-quintile IC>0.10 signal at 45d typically produces 2–5% excess return; "
        "do not invent double-digit upsides unless the thesis has strong asymmetric catalysts."
    )
    return "\n".join(lines)
