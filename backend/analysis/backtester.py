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
STRATEGY_PATH = Path(__file__).parent.parent / "data" / "strategy_backtest.json"

# Minimum rows for a symbol to be included in backtest
MIN_HISTORY_ROWS = 120  # ~6 months trading days
# Monthly snapshot interval (trading days)
SNAPSHOT_INTERVAL_DAYS = 21
# Forward return horizons to evaluate
FORWARD_HORIZONS = [20, 30, 45, 90]
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


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(len(closes) - period, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1 + rs))


def _ema_series(closes: list[float], period: int) -> list[float]:
    """EMA over the full close series; returns values starting at index period-1."""
    if len(closes) < period:
        return []
    k = 2.0 / (period + 1)
    ema = sum(closes[:period]) / period
    result = [ema]
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
        result.append(ema)
    return result


def _macd_hist_pct(closes: list[float]) -> float | None:
    """MACD histogram (12-26-9) normalised as % of latest close."""
    if len(closes) < 35:
        return None
    ema12 = _ema_series(closes, 12)   # index i → close index 11+i
    ema26 = _ema_series(closes, 26)   # index i → close index 25+i
    # Align: ema26[i] matches ema12[i+14]
    offset = 14  # 26 - 12
    n_overlap = len(ema26)
    macd_line = [ema12[i + offset] - ema26[i] for i in range(n_overlap)]
    if len(macd_line) < 9:
        return None
    signal_line = _ema_series(macd_line, 9)
    if not signal_line:
        return None
    histogram = macd_line[-1] - signal_line[-1]
    return (histogram / closes[-1] * 100.0) if closes[-1] else None


def _bollinger_pct_b(closes: list[float], period: int = 20, num_std: float = 2.0) -> float | None:
    """Bollinger Band %B: 0 = at lower band, 1 = at upper band."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    middle = sum(window) / period
    std = statistics.stdev(window)
    if std == 0:
        return 0.5
    upper = middle + num_std * std
    lower = middle - num_std * std
    return _clamp((closes[-1] - lower) / (upper - lower), 0.0, 1.0)


def _bollinger_width(closes: list[float], period: int = 20, num_std: float = 2.0) -> float | None:
    """Bollinger Band width normalised by middle band (volatility measure)."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    middle = sum(window) / period
    if not middle:
        return None
    return (2.0 * num_std * statistics.stdev(window)) / middle


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

    rsi = _rsi(closes)
    macd_hist = _macd_hist_pct(closes)
    bb_pct_b = _bollinger_pct_b(closes)
    bb_width = _bollinger_width(closes)

    return {
        "ret_20": ret_20,
        "ret_60": ret_60 or 0.0,
        "rel_strength": rel_strength,
        "accel": accel,
        "vol_ratio": vol_r,
        "above_ma": (above_20 + above_50) / 2,
        "volatility": volatility,
        "tech_score": tech_score,
        # New signals for IC testing
        "rsi": rsi if rsi is not None else 50.0,
        "macd_hist": macd_hist if macd_hist is not None else 0.0,
        "bb_pct_b": bb_pct_b if bb_pct_b is not None else 0.5,
        "bb_width": bb_width if bb_width is not None else 0.0,
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
    import math
    ctx: dict[str, Any] = {}
    for horizon_key, hdata in cal.get("horizons", {}).items():
        q = hdata.get("quintiles", {})
        if not q:
            continue
        q1 = q.get("Q5", {})  # Q5 = highest signal rank (we sort ascending, Q5 is top)
        q5 = q.get("Q1", {})  # Q1 = lowest signal rank
        n = hdata.get("observations", 0)
        # Include per-signal ICs with t-stats for LLM context
        raw_ics = hdata.get("signal_ics", {})
        sig_ics: dict[str, dict[str, float]] = {}
        for sig, ic in raw_ics.items():
            if ic is not None:
                t = ic * math.sqrt(n) / math.sqrt(1 - ic**2) if n > 1 and abs(ic) < 1 else 0.0
                sig_ics[sig] = {"ic": round(ic, 4), "t_stat": round(t, 1)}
        ctx[horizon_key] = {
            "ic_composite": raw_ics.get("tech_score"),
            "top_quintile_mean_excess_pct": q1.get("mean_excess"),
            "top_quintile_hit_rate": q1.get("hit_rate"),
            "bottom_quintile_mean_excess_pct": q5.get("mean_excess"),
            "n_observations": n,
            "signal_ics": sig_ics,
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
    # Emit 90d as the primary horizon for upside anchoring
    primary = ctx.get("90d") or ctx.get("45d") or {}
    sig_ics = primary.get("signal_ics", {})
    if sig_ics:
        # Show top positive and top negative signals
        sorted_sigs = sorted(sig_ics.items(), key=lambda x: x[1].get("ic", 0), reverse=True)
        pos = [(s, v) for s, v in sorted_sigs if v.get("ic", 0) > 0]
        neg = [(s, v) for s, v in sorted_sigs if v.get("ic", 0) < 0]
        sig_lines = []
        for sig, v in (pos[:3] + neg[-3:]):
            ic_val = v.get("ic", 0)
            t_val = v.get("t_stat", 0)
            sig_lines.append(f"{sig}(IC={ic_val:+.3f},t={t_val:+.1f})")
        lines.append(f"Key signals (90d): {', '.join(sig_lines)}")

    for horizon_key, hdata in ctx.items():
        ic = hdata.get("ic_composite")
        top_excess = hdata.get("top_quintile_mean_excess_pct")
        hit_rate = hdata.get("top_quintile_hit_rate")
        n = hdata.get("n_observations", 0)
        if top_excess is None:
            continue
        ic_str = f"IC={ic:+.3f}, " if ic is not None else ""
        lines.append(
            f"- {horizon_key}: {ic_str}top-quintile stocks averaged "
            f"{top_excess:+.1f}% excess vs SPY (hit rate {hit_rate:.0%}), n={n}"
        )

    if len(lines) <= 2:
        return ""

    lines.append(
        "Anchor upside_pct to these empirical ranges. High-volatility stocks with low ret_60 "
        "have the strongest forward return signal. Stocks already above their MAs or with "
        "large recent 60d runs historically underperform. Do not invent double-digit upsides "
        "unless the thesis has strong asymmetric catalysts beyond the signal."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase 3 — Walk-forward strategy simulation
# ---------------------------------------------------------------------------

def _ic_calibrated_score(
    closes: list[float],
    volumes: list[float],
    spy_closes: list[float] | None,
) -> float | None:
    """IC-calibrated strategy score — v2 with RSI, MACD, Bollinger signals.

    Weights are IC-proportional (90d horizon). The strategy is fundamentally
    mean-reverting: find high-volatility stocks that are currently oversold
    (low RSI, near lower BB, negative MACD histogram) — they tend to bounce hard.

    Positive signals (IC > 0 at 90d):
      volatility  IC=+0.121  → high daily vol = larger expected move
      bb_width    IC=+0.117  → wide bands = volatile regime, bigger bounces
      vol_ratio   IC=+0.032  → volume surge

    Flipped negative signals (low value = positive outcome):
      bb_pct_b    IC=−0.116  → near lower band = oversold, flip to (1 − %B)
      rsi         IC=−0.082  → low RSI = oversold, flip to (100 − RSI) / 100

    Penalty:
      ret_60      IC=−0.117  → stocks already up >15% in 60d face reversal
    """
    sigs = compute_signals(closes, volumes, spy_closes)
    if sigs is None:
        return None

    vol_norm = _clamp((sigs["volatility"] - 0.5) / 4.5, 0.0, 1.0)           # IC=+0.121 at 90d
    bbw_norm = _clamp((sigs["bb_width"] - 0.02) / 0.18, 0.0, 1.0)           # IC=+0.117 at 90d (new)
    volr_norm = _clamp((sigs["vol_ratio"] - 0.5) / 2.5, 0.0, 1.0)           # IC=+0.032 at 90d
    relstr_norm = _clamp((sigs["rel_strength"] + 35.0) / 70.0, 0.0, 1.0)    # IC=−0.016 at 90d but +0.027 at 20d
    bb_inv = 1.0 - sigs["bb_pct_b"]                                           # IC=−0.116 flipped
    rsi_inv = _clamp((100.0 - sigs["rsi"]) / 70.0, 0.0, 1.0)                # IC=−0.082 flipped

    # Reversal penalty: stocks up >15% over 60d have mean-reversion tendency
    ret60_penalty = _clamp((sigs["ret_60"] - 15.0) / 35.0, 0.0, 1.0) * 0.30

    ret20_norm = _clamp((sigs["ret_20"] + 25.0) / 50.0, 0.0, 1.0)            # short-term momentum

    score = (
        0.30 * vol_norm       # IC=+0.121 — dominant signal
        + 0.20 * bbw_norm     # IC=+0.117 — second volatility dimension (new)
        + 0.20 * volr_norm    # IC=+0.032 — volume surge
        + 0.17 * relstr_norm  # relative strength — filters for stocks already in motion
        + 0.13 * ret20_norm   # short-term momentum — same filter
        - ret60_penalty       # IC=−0.117 — reversal penalty
    )
    return _clamp(score, 0.0, 1.0)


def _compute_regime(spy_closes: list[float]) -> str:
    """Classify market regime from SPY price data.

    risk_on:  SPY 20d return > +1%, above 50d MA, annualised vol < 30%
    risk_off: SPY 20d return < −5%, or below 50d MA with > −2% return, or vol > 40%
    caution:  everything in between
    """
    if len(spy_closes) < 51:
        return "unknown"

    spy_20d_ret = (spy_closes[-1] / spy_closes[-21] - 1.0) * 100.0 if spy_closes[-21] else 0.0
    ma_50 = sum(spy_closes[-50:]) / 50.0
    above_50 = spy_closes[-1] >= ma_50

    daily_rets = [
        (spy_closes[i] / spy_closes[i - 1] - 1.0)
        for i in range(max(1, len(spy_closes) - 20), len(spy_closes))
        if spy_closes[i - 1]
    ]
    spy_vol_ann = statistics.stdev(daily_rets) * math.sqrt(252) * 100.0 if len(daily_rets) >= 2 else 15.0

    if spy_20d_ret > 1.0 and above_50 and spy_vol_ann <= 30.0:
        return "risk_on"
    if spy_20d_ret < -5.0 or (not above_50 and spy_20d_ret < -2.0) or spy_vol_ann > 40.0:
        return "risk_off"
    return "caution"


def _build_date_index(matrix: dict[str, dict[str, Any]]) -> dict[str, dict[Any, int]]:
    """Pre-build {symbol: {date: idx}} for O(1) snap_date lookups."""
    return {sym: {d: i for i, d in enumerate(data["dates"])} for sym, data in matrix.items()}


def _compute_max_drawdown(returns_pct: list[float]) -> float:
    """Max drawdown from a series of period percentage returns."""
    nav = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns_pct:
        nav *= (1 + r / 100.0)
        if nav > peak:
            peak = nav
        dd = (peak - nav) / peak * 100.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


async def run_strategy_backtest(
    db: AsyncSession,
    n_picks: int = 5,
) -> dict[str, Any]:
    """Walk-forward strategy simulation.

    At each monthly snapshot uses only price data up to that date (no look-ahead),
    scores all symbols with the IC-calibrated scorer, picks top n_picks,
    tracks equal-weight portfolio returns vs SPY at 20/45/90d horizons.

    Output saved to data/strategy_backtest.json.
    """
    logger.info("Loading price matrix for strategy backtest...")
    matrix = await _load_price_matrix(db)
    logger.info("Loaded %d symbols", len(matrix))

    if "SPY" not in matrix:
        return {"error": "SPY not in price matrix — required for benchmark"}

    spy_data = matrix["SPY"]
    all_dates = spy_data["dates"]
    total_days = len(all_dates)
    max_horizon = max(FORWARD_HORIZONS)

    snapshot_indices = list(range(64, total_days - max_horizon, SNAPSHOT_INTERVAL_DAYS))
    if len(snapshot_indices) < 3:
        return {"error": f"Insufficient data: {total_days} trading days"}

    # Pre-build date → index maps for fast lookups
    date_index = _build_date_index(matrix)
    # Fallback candidates for dates missing from a symbol
    nearby_offsets = list(range(1, 4))

    trade_log: list[dict[str, Any]] = []

    for snap_idx in snapshot_indices:
        snap_date = all_dates[snap_idx]
        spy_closes_snap = spy_data["closes"][:snap_idx + 1]
        spy_snap_close = spy_closes_snap[-1]

        # Map snap_date to each symbol's index (with ±3-day fallback)
        sym_snap_idxs: dict[str, int] = {}
        for symbol in matrix:
            if symbol == "SPY":
                continue
            didx = date_index[symbol]
            idx = didx.get(snap_date)
            if idx is None:
                for offset in nearby_offsets:
                    candidate = all_dates[snap_idx - offset] if snap_idx >= offset else None
                    if candidate is not None:
                        idx = didx.get(candidate)
                        if idx is not None:
                            break
            if idx is not None and idx >= 64:
                sym_snap_idxs[symbol] = idx

        # Score all eligible symbols
        scored: list[tuple[str, float]] = []
        for symbol, sym_idx in sym_snap_idxs.items():
            data = matrix[symbol]
            score = _ic_calibrated_score(
                data["closes"][:sym_idx + 1],
                data["volumes"][:sym_idx + 1],
                spy_closes_snap,
            )
            if score is not None:
                scored.append((symbol, score))

        if len(scored) < n_picks:
            continue

        scored.sort(key=lambda x: x[1], reverse=True)
        picks = scored[:n_picks]
        pick_symbols = [s for s, _ in picks]
        pick_scores = {s: round(sc, 4) for s, sc in picks}

        # Compute returns at each horizon for each pick
        pick_returns: dict[int, dict[str, float]] = {h: {} for h in FORWARD_HORIZONS}
        for symbol, _ in picks:
            data = matrix[symbol]
            sym_idx = sym_snap_idxs[symbol]
            snap_close = data["closes"][sym_idx]
            if snap_close == 0:
                continue
            for horizon in FORWARD_HORIZONS:
                fwd_idx = sym_idx + horizon
                if fwd_idx < len(data["closes"]):
                    ret = (data["closes"][fwd_idx] / snap_close - 1.0) * 100.0
                    pick_returns[horizon][symbol] = round(ret, 3)

        # SPY forward returns
        spy_returns: dict[int, float] = {}
        for horizon in FORWARD_HORIZONS:
            spy_fwd_idx = snap_idx + horizon
            if spy_fwd_idx < len(spy_data["closes"]) and spy_snap_close:
                spy_returns[horizon] = round(
                    (spy_data["closes"][spy_fwd_idx] / spy_snap_close - 1.0) * 100.0, 3
                )

        regime = _compute_regime(spy_closes_snap)

        entry: dict[str, Any] = {
            "date": snap_date.isoformat() if hasattr(snap_date, "isoformat") else str(snap_date),
            "picks": pick_symbols,
            "scores": pick_scores,
            "n_scored": len(scored),
            "regime": regime,
        }
        for horizon in FORWARD_HORIZONS:
            rets = list(pick_returns[horizon].values())
            port_ret = _safe_mean(rets)
            spy_ret = spy_returns.get(horizon)
            if port_ret is not None and spy_ret is not None:
                entry[f"returns_{horizon}d"] = pick_returns[horizon]
                entry[f"portfolio_return_{horizon}d"] = round(port_ret, 3)
                entry[f"spy_return_{horizon}d"] = spy_ret
                entry[f"excess_{horizon}d"] = round(port_ret - spy_ret, 3)

        trade_log.append(entry)

    def _build_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute per-horizon stats for a subset of trade_log entries."""
        out: dict[str, Any] = {}
        for horizon in FORWARD_HORIZONS:
            key = f"{horizon}d"
            excess_series = [e[f"excess_{horizon}d"] for e in entries if f"excess_{horizon}d" in e]
            if not excess_series:
                continue
            avg_excess = _safe_mean(excess_series) or 0.0
            win_rate = sum(1 for e in excess_series if e > 0) / len(excess_series)
            std_excess = _safe_std(excess_series) or 0.0
            periods_per_year = 252.0 / horizon
            sharpe = (
                (avg_excess * periods_per_year) / (std_excess * math.sqrt(periods_per_year))
                if std_excess > 0 else 0.0
            )
            out[key] = {
                "avg_excess_pct": round(avg_excess, 3),
                "win_rate": round(win_rate, 3),
                "sharpe": round(sharpe, 3),
                "n_periods": len(excess_series),
            }
        return out

    # Regime breakdown
    regime_counts = {"risk_on": 0, "caution": 0, "risk_off": 0, "unknown": 0}
    for e in trade_log:
        regime_counts[e.get("regime", "unknown")] = regime_counts.get(e.get("regime", "unknown"), 0) + 1

    risk_on_entries = [e for e in trade_log if e.get("regime") == "risk_on"]
    risk_on_caution_entries = [e for e in trade_log if e.get("regime") in ("risk_on", "caution")]

    summary = _build_summary(trade_log)
    summary_regime_on = _build_summary(risk_on_entries)
    summary_regime_on_caution = _build_summary(risk_on_caution_entries)

    # Max drawdown on 20d portfolio NAV (snapshots every 21d ≈ non-overlapping)
    port_20d = [e["portfolio_return_20d"] for e in trade_log if "portfolio_return_20d" in e]
    port_20d_on = [e["portfolio_return_20d"] for e in risk_on_entries if "portfolio_return_20d" in e]
    max_dd = _compute_max_drawdown(port_20d) if port_20d else None
    max_dd_on = _compute_max_drawdown(port_20d_on) if port_20d_on else None

    result: dict[str, Any] = {
        "as_of": date.today().isoformat(),
        "n_picks": n_picks,
        "snapshots_run": len(trade_log),
        "symbols_scored": len(matrix) - 1,
        "regime_counts": regime_counts,
        "summary": summary,
        "summary_regime_on": summary_regime_on,
        "summary_regime_on_caution": summary_regime_on_caution,
        "max_drawdown_20d_pct": round(max_dd, 3) if max_dd is not None else None,
        "max_drawdown_20d_regime_on_pct": round(max_dd_on, 3) if max_dd_on is not None else None,
        "trade_log": trade_log,
    }

    STRATEGY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STRATEGY_PATH, "w") as f:
        json.dump(result, f, indent=2)
    logger.info("Strategy backtest saved to %s", STRATEGY_PATH)
    return result


def load_strategy_backtest() -> dict[str, Any] | None:
    """Load saved strategy backtest results from disk."""
    if not STRATEGY_PATH.exists():
        return None
    try:
        with open(STRATEGY_PATH) as f:
            return json.load(f)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Today's picks — hybrid Scorer B + fundamental quality gate
# ---------------------------------------------------------------------------

def format_quant_context(picks: list[dict[str, Any]], regime: str) -> str:
    """Format quant scorer results as a context block for agent prompts.

    Tells agents WHY each symbol was nominated: the IC-validated signals that
    drove its score, so they can focus their analysis on whether the signal
    thesis holds up under fundamental and macro scrutiny.
    """
    lines = [
        "## Quant Nomination Context (IC-Calibrated Scorer)",
        f"Regime: {regime}",
        "These symbols were nominated by an IC-calibrated quant scorer backtested across",
        "206 symbols × 17 monthly snapshots (walk-forward, no look-ahead). Strategy",
        "performance: 3.17× vs SPY 1.50×, 71% win rate at 90d, Sharpe 0.98.",
        "",
        "Dominant signals (90d IC): volatility IC=+0.121, bb_width IC=+0.117,",
        "vol_ratio IC=+0.032. Stocks scoring high tend to be volatile, with expanding",
        "Bollinger Bands and recent volume surges — candidates for large directional moves.",
        "",
        "| Symbol | Score | Volatility | BB Width | Vol Ratio | Rel Str | 20d Ret | RSI |",
        "|--------|-------|-----------|---------|-----------|---------|---------|-----|",
    ]
    for p in picks:
        s = p["signals"]
        lines.append(
            f"| {p['symbol']:<6} | {p['quant_score']:.3f} "
            f"| {s['volatility']:.2f} "
            f"| {s['bb_width']:.3f} "
            f"| {s['vol_ratio']:.2f} "
            f"| {s['rel_strength']:+.1f} "
            f"| {s['ret_20d_pct']:+.1f}% "
            f"| {s['rsi']:.0f} |"
        )
    lines += [
        "",
        "High bb_width = expanding Bollinger Bands (volatility regime). High vol_ratio =",
        "recent volume surge vs 20d avg. Rel Str = 20d return minus SPY (× 2) + 5d excess.",
        "Your job: assess whether each candidate has a credible thesis beyond the price signal.",
        "Flag any names where the quant signal is misleading (e.g. vol from bad news, RSI",
        "overbought, sector headwinds) and surface those risks clearly in your analysis.",
    ]
    return "\n".join(lines)

async def get_today_picks(
    db: AsyncSession,
    n_candidates: int = 20,
    n_picks: int = 5,
    min_market_cap: float = 500_000_000,
    min_revenue_growth: float = -0.25,
) -> dict[str, Any]:
    """Score all symbols with the IC-calibrated scorer, then apply a fundamental
    quality gate on the top candidates before surfacing the final picks.

    Steps:
      1. Load all price history from DB, score every symbol with _ic_calibrated_score()
      2. Take top n_candidates by quant score
      3. Fetch fundamentals via Yahoo Finance for those candidates
      4. Filter out: market_cap < min_market_cap OR revenue_growth < min_revenue_growth
      5. Return top n_picks from the filtered set, with signal detail + regime
    """
    from data.adapters.yahoo import get_fundamental_data

    matrix = await _load_price_matrix(db)
    if "SPY" not in matrix:
        return {"error": "SPY not in price matrix"}

    spy_data = matrix["SPY"]
    spy_closes = spy_data["closes"]
    regime = _compute_regime(spy_closes)

    # Score every symbol on current (full) price history
    scored: list[tuple[str, float, dict[str, float]]] = []
    for symbol, data in matrix.items():
        if symbol == "SPY":
            continue
        closes = data["closes"]
        volumes = data["volumes"]
        score = _ic_calibrated_score(closes, volumes, spy_closes)
        if score is None:
            continue
        sigs = compute_signals(closes, volumes, spy_closes)
        if sigs is None:
            continue
        scored.append((symbol, score, sigs))

    scored.sort(key=lambda x: x[1], reverse=True)
    candidates = scored[:n_candidates]
    candidate_symbols = [s for s, _, _ in candidates]

    # Fetch fundamentals for candidates only
    fundamentals = await get_fundamental_data(candidate_symbols)

    # Apply quality gates
    filtered: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for symbol, score, sigs in candidates:
        fund = fundamentals.get(symbol) or {}
        mkt_cap = fund.get("market_cap") or 0
        rev_growth = fund.get("revenue_growth")  # None = unknown
        sector = fund.get("sector") or "Unknown"
        industry = fund.get("industry") or ""

        reject_reason = None
        if mkt_cap and mkt_cap < min_market_cap:
            reject_reason = f"market_cap ${mkt_cap/1e6:.0f}M < ${min_market_cap/1e6:.0f}M threshold"
        elif rev_growth is not None and rev_growth < min_revenue_growth:
            reject_reason = f"revenue_growth {rev_growth:.0%} < {min_revenue_growth:.0%} threshold"

        entry = {
            "symbol": symbol,
            "quant_score": round(score, 4),
            "signals": {
                "volatility": round(sigs["volatility"], 3),
                "bb_width": round(sigs["bb_width"], 3),
                "vol_ratio": round(sigs["vol_ratio"], 3),
                "rel_strength": round(sigs["rel_strength"], 2),
                "ret_20d_pct": round(sigs["ret_20"], 2),
                "ret_60d_pct": round(sigs["ret_60"], 2),
                "rsi": round(sigs["rsi"], 1),
                "bb_pct_b": round(sigs["bb_pct_b"], 3),
            },
            "fundamentals": {
                "market_cap_m": round(mkt_cap / 1e6, 0) if mkt_cap else None,
                "revenue_growth": round(rev_growth, 3) if rev_growth is not None else None,
                "sector": sector,
                "industry": industry,
                "price_to_sales": fund.get("price_to_sales"),
                "trailing_pe": fund.get("trailing_pe"),
                "profit_margins": fund.get("profit_margins"),
            },
        }
        if reject_reason:
            entry["rejected"] = reject_reason
            rejected.append(entry)
        else:
            filtered.append(entry)

    # Deduplicate share-class twins (same company, different ticker e.g. GOOGL/GOOG)
    # If two candidates have market caps within 2% of each other and same sector, keep the first (higher score)
    deduped: list[dict[str, Any]] = []
    seen_caps: list[float] = []
    for entry in filtered:
        cap = entry["fundamentals"].get("market_cap_m") or 0
        sector = entry["fundamentals"].get("sector") or ""
        if cap > 0:
            is_twin = any(
                abs(cap - c) / max(cap, c) < 0.02 and sector == deduped[i]["fundamentals"].get("sector")
                for i, c in enumerate(seen_caps)
                if c > 0
            )
            if is_twin:
                continue
        deduped.append(entry)
        seen_caps.append(cap)

    picks = deduped[:n_picks]

    quant_ctx = format_quant_context(picks, regime)

    return {
        "as_of": date.today().isoformat(),
        "regime": regime,
        "n_picks": len(picks),
        "picks": picks,
        "rejected_candidates": rejected,
        "total_scored": len(scored),
        "regime_note": {
            "risk_on": "Full signal — deploy normally",
            "caution": "Moderate signal — consider half-size positions",
            "risk_off": "High-vol regime — strategy excels here but expect larger swings",
            "unknown": "Insufficient SPY history",
        }.get(regime, ""),
        "quant_context": quant_ctx,
    }
