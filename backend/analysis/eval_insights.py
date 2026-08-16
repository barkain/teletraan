"""Deterministic evaluation harness for the LLM insight pipeline.

``analysis/backtester.py`` measures the *technical factors* that feed the alpha
engine.  Nothing measured the thing users actually read: the ``DeepInsight``
recommendations produced by ``DeepAnalysisEngine`` / ``AutonomousDeepEngine``.
This module closes that gap.

Design constraints that shaped it:

* **Zero LLM cost, read-only, repeatable.**  Every number comes from the local
  ``price_history`` table (with an optional, disk-cached yfinance fallback for
  symbols the ETL never ingested).  Running it twice on the same data gives the
  same answer.
* **Independent of the outcome tracker.**  ``insight_outcomes.thesis_validated``
  was computed with a flat +/-1% absolute bar, no benchmark, and on average 30
  days after the window closed.  This harness derives its own labels straight
  from prices so it can grade the system honestly even when the tracker is
  wrong.  It never reads ``insight_outcomes``.
* **Benchmark-relative.**  A BUY that returns +4% while SPY returns +6% is a
  miss.  The label is ``sign(alpha) == predicted_direction`` where
  ``alpha = symbol_return - benchmark_return`` over the same calendar window.
* **No look-ahead.**  The entry bar is the first trading bar *strictly after*
  ``created_at`` (``ENTRY_LAG_TRADING_DAYS``), so a mid-session insight can
  never be entered at a close it could not have known.  The exit bar is a fixed
  number of trading bars later; an insight whose exit bar does not exist yet is
  excluded rather than truncated.

Usage::

    from analysis.eval_insights import run_insight_eval
    results = await run_insight_eval(db)
    # snapshot saved to data/insight_eval.json
    # summary appended to data/insight_eval_history.jsonl

Or from the command line (read-only against the production DB)::

    uv run python -m analysis.eval_insights --allow-network
"""
from __future__ import annotations

import json
import logging
import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from analysis.horizons import HORIZON_TRADING_DAYS, resolve_horizon_days

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"
EVAL_SNAPSHOT_PATH = _DATA_DIR / "insight_eval.json"
EVAL_HISTORY_PATH = _DATA_DIR / "insight_eval_history.jsonl"
PRICE_CACHE_PATH = _DATA_DIR / "eval_price_cache.json"

# Bumped whenever the *measurement* changes (label rule, entry lag, binning).
# Snapshots taken under different harness versions are not comparable.
HARNESS_VERSION = "1.0.0"

BENCHMARK_SYMBOL = "SPY"

# Trading bars between ``created_at`` and the entry close.  1 == "next close",
# which is the earliest price a reader of the insight could actually transact
# at and therefore the smallest lag that is free of look-ahead.
ENTRY_LAG_TRADING_DAYS = 1

# Largest acceptable calendar gap between consecutive bars.  Five days spans a
# weekend plus a holiday; anything wider is an ETL hole, not a market closure.
MAX_BAR_GAP_DAYS = 5

# A window is rejected when its realised calendar span exceeds the span its
# trading-bar horizon implies by more than this factor -- the signature of a
# data hole that would otherwise turn a 21-bar return into a 70-day return.
MAX_WINDOW_STRETCH = 2.0

# Directional reading of each action.  HOLD/WATCH make no directional claim and
# are excluded from scoring rather than being scored as flat.
DIRECTION_BY_ACTION: dict[str, int] = {
    "STRONG_BUY": 1,
    "BUY": 1,
    "BUY_MORE": 1,
    "SELL": -1,
    "STRONG_SELL": -1,
}
NON_DIRECTIONAL_ACTIONS = frozenset({"HOLD", "WATCH"})

# Horizons resolve through ``analysis.horizons``, the single source of truth
# shared with the outcome grader.  This module deliberately keeps no private
# table: the two used to disagree on five of seven values, which made their
# measurements silently incomparable.
#
# There is no default.  An insight whose horizon cannot be resolved is excluded
# and counted (``unknown_horizon``) rather than graded over an invented window.

# Alternative horizon tables graded alongside the primary one, so every
# snapshot carries the size of its own largest free parameter.  ``medium_term``
# is the most common value in the corpus and the one that was arbitrated; see
# ``analysis/horizons`` for why 30 was adopted over 63.
HORIZON_SENSITIVITY_VARIANTS: dict[str, dict[str, int]] = {
    "medium_term_63": {"medium_term": 63},
}

# Pseudo-symbols the synthesis emits for portfolio-level commentary.  They are
# not tradeable instruments and must not be priced.
NON_TRADEABLE_SYMBOLS = frozenset({"PORTFOLIO", "PORTFOLIO_RISK", "N/A", "NONE", "CASH"})

# ---------------------------------------------------------------------------
# Pipeline versioning
# ---------------------------------------------------------------------------
# The original design suggested carrying a version tag in
# ``DeepInsight.discovery_context``.  Nothing writes one today, and 306 of the
# 440 stored insights have a NULL ``discovery_context`` at all, so relying on it
# alone would leave every historical row uncohorted -- and backfilling it would
# mean editing the engines, which this module deliberately does not do.
#
# Resolution order, most to least authoritative:
#   1. ``discovery_context["pipeline_version"]`` -- honoured if an engine ever
#      starts stamping it (forward-compatible, no engine change needed here).
#   2. The era table below: ``created_at`` bucketed by the dates on which
#      pipeline-shaping commits landed.  A recommendation is a product of the
#      code that ran that day, and ``created_at`` is the one field that is
#      always present and never rewritten.
#   3. ``"unknown"`` for rows predating the first era.
#
# Boundaries are the author dates of the commits that changed what the analysts
# see or how synthesis decides -- not every commit that touched the files.
PIPELINE_ERAS: tuple[tuple[date, str], ...] = (
    (date(2026, 2, 1), "v1-discovery"),          # initial autonomous pipeline
    (date(2026, 4, 18), "v2-signals"),           # b1f53bb options + sector momentum
    (date(2026, 5, 3), "v3-portfolio-quant"),    # 51c5283/f308376 quant + portfolio ctx
    (date(2026, 6, 5), "v4-news-sentiment"),     # 6d6187e/7f08f8d dedupe + news
    (date(2026, 8, 16), "v5-evidence-layer"),    # 0344385 evidence-layer rebuild
)
CURRENT_PIPELINE_VERSION = PIPELINE_ERAS[-1][1]

DEFAULT_RELIABILITY_BINS = 10


# ---------------------------------------------------------------------------
# Exclusion reasons
# ---------------------------------------------------------------------------

EXCLUSION_REASONS = (
    "non_directional_action",   # HOLD / WATCH -- no directional claim to grade
    "unknown_action",           # action outside the known vocabulary
    "no_primary_symbol",        # nothing to price
    "non_tradeable_symbol",     # PORTFOLIO / PORTFOLIO_RISK pseudo-symbols
    "missing_confidence",       # cannot enter the calibration curve
    "unknown_horizon",          # time_horizon unresolvable -- no window to grade over
    "no_price_series",          # symbol absent from price_history and yfinance
    "entry_bar_missing",        # no trading bar after created_at
    "horizon_not_elapsed",      # exit bar is in the future / beyond loaded data
    "no_benchmark_bar",         # SPY has no bar covering entry or exit
    "window_gapped",            # data hole stretched the window past its horizon
    "invalid_price",            # zero or negative close
)
_MAX_SAMPLE_IDS = 12


@dataclass
class ExclusionLedger:
    """Counts (and a sample of ids) for every insight the harness dropped."""

    counts: dict[str, int] = field(default_factory=lambda: {r: 0 for r in EXCLUSION_REASONS})
    sample_ids: dict[str, list[int]] = field(default_factory=lambda: defaultdict(list))

    def record(self, reason: str, insight_id: int | None = None) -> None:
        self.counts[reason] = self.counts.get(reason, 0) + 1
        if insight_id is not None and len(self.sample_ids[reason]) < _MAX_SAMPLE_IDS:
            self.sample_ids[reason].append(insight_id)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_excluded": self.total,
            "by_reason": {k: v for k, v in self.counts.items() if v},
            "sample_insight_ids": {k: v for k, v in self.sample_ids.items() if v},
        }


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------

@dataclass
class EvalRecord:
    """One graded directional call.

    ``alpha_pct`` is the benchmark-adjusted return over the insight's own
    horizon; ``correct`` is the label used by every metric in this module.
    """

    insight_id: int
    symbol: str
    action: str
    direction: int
    confidence: float
    created_at: str
    pipeline_version: str
    horizon_trading_days: int
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    symbol_return_pct: float
    benchmark_return_pct: float
    alpha_pct: float
    correct: bool
    raw_correct: bool
    price_source: str

    @property
    def month(self) -> str:
        return self.created_at[:7]


def direction_for_action(action: str | None) -> int | None:
    """Map an ``InsightAction`` to +1 (long), -1 (short) or ``None``.

    ``None`` means "not a directional call" -- either an explicit HOLD/WATCH or
    an action outside the known vocabulary.  Callers distinguish the two via
    :data:`NON_DIRECTIONAL_ACTIONS`.
    """
    if not action:
        return None
    return DIRECTION_BY_ACTION.get(action.strip().upper())


def horizon_trading_days(
    time_horizon: str | None,
    overrides: dict[str, int] | None = None,
) -> int | None:
    """Resolve a ``time_horizon`` string to trading bars, or ``None``.

    Delegates to :mod:`analysis.horizons`.  ``None`` means the horizon could not
    be resolved; the caller excludes the insight rather than inventing a window.
    ``overrides`` substitutes individual keys and exists for the sensitivity
    variants -- it never changes the shipped default.
    """
    if overrides:
        key = (time_horizon or "").strip().lower()
        if key in overrides:
            return overrides[key]
    try:
        return resolve_horizon_days(time_horizon)
    except ValueError:
        # The grader raises here; this harness excludes and counts instead.
        # Same refusal to invent a window, different policy for a batch job.
        return None


def pipeline_version_for(
    created_at: datetime | date | None,
    discovery_context: dict[str, Any] | None = None,
) -> str:
    """Resolve the pipeline version that produced an insight.

    See the ``PIPELINE_ERAS`` comment for why ``created_at`` is the fallback
    carrier rather than ``discovery_context`` alone.
    """
    if isinstance(discovery_context, dict):
        stamped = discovery_context.get("pipeline_version")
        if isinstance(stamped, str) and stamped.strip():
            return stamped.strip()

    if created_at is None:
        return "unknown"
    created = created_at.date() if isinstance(created_at, datetime) else created_at

    version = "unknown"
    for boundary, name in PIPELINE_ERAS:
        if created >= boundary:
            version = name
        else:
            break
    return version


# ---------------------------------------------------------------------------
# Price series helpers  (a series is a date-ascending list of (date, close))
# ---------------------------------------------------------------------------

Series = list[tuple[date, float]]


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def entry_exit_indices(
    dates: Sequence[date],
    created: date,
    horizon_bars: int,
    entry_lag: int = ENTRY_LAG_TRADING_DAYS,
) -> tuple[int, int] | None:
    """Indices of the entry and exit bars, or ``None`` if the window is not closed.

    The entry bar is the ``entry_lag``-th bar *strictly after* ``created``.  A
    same-day close is never used: an insight written at 10:00 could not have
    been transacted at that day's 16:00 print without look-ahead.
    """
    if horizon_bars <= 0 or entry_lag < 1:
        return None

    first_after = None
    for idx, bar_date in enumerate(dates):
        if bar_date > created:
            first_after = idx
            break
    if first_after is None:
        return None

    entry_idx = first_after + (entry_lag - 1)
    exit_idx = entry_idx + horizon_bars
    if exit_idx >= len(dates):
        return None
    return entry_idx, exit_idx


def close_on_or_before(series: Series, target: date, max_back_days: int = 7) -> float | None:
    """Last close at or before ``target``, tolerating up to ``max_back_days`` of gap.

    Used to price the benchmark on the symbol's own entry/exit dates so both
    legs cover the identical calendar window even when the symbol trades on a
    calendar the benchmark does not (futures, foreign listings).
    """
    best: float | None = None
    for bar_date, close in series:
        if bar_date > target:
            break
        if (target - bar_date).days <= max_back_days:
            best = close
        else:
            best = None
    return best


def pct_return(entry: float, exit_: float) -> float | None:
    if entry is None or exit_ is None or entry <= 0:
        return None
    return (exit_ / entry - 1.0) * 100.0


# ---------------------------------------------------------------------------
# Metric math (pure -- these are what the unit tests pin)
# ---------------------------------------------------------------------------

def hit_rate(records: Sequence[EvalRecord]) -> float | None:
    """Benchmark-adjusted hit rate: share of calls whose alpha went the predicted way."""
    if not records:
        return None
    return sum(1 for r in records if r.correct) / len(records)


def raw_hit_rate(records: Sequence[EvalRecord]) -> float | None:
    """Directional hit rate against the *raw* return, ignoring the benchmark.

    Reported alongside the adjusted rate so a bull-market illusion is visible:
    a long book in a rising tape scores well raw and poorly adjusted.
    """
    if not records:
        return None
    return sum(1 for r in records if r.raw_correct) / len(records)


def mean_alpha(records: Sequence[EvalRecord]) -> float | None:
    """Mean *signed* alpha per call: alpha in the direction the insight predicted."""
    if not records:
        return None
    return statistics.fmean(r.alpha_pct * r.direction for r in records)


def brier_score(records: Sequence[EvalRecord]) -> float | None:
    """Mean squared error of stated confidence against the realised outcome.

    Lower is better; 0.25 is what a constant 0.5 forecast scores.
    """
    if not records:
        return None
    return statistics.fmean((r.confidence - (1.0 if r.correct else 0.0)) ** 2 for r in records)


def base_rate_brier(records: Sequence[EvalRecord]) -> float | None:
    """Brier score of the climatology forecast (predict the sample base rate every time).

    Equals ``p * (1 - p)`` for base rate ``p``.  This is the bar confidence has
    to clear: a model whose confidence carries no information cannot beat it.
    """
    if not records:
        return None
    base = hit_rate(records) or 0.0
    return statistics.fmean((base - (1.0 if r.correct else 0.0)) ** 2 for r in records)


def brier_skill_score(records: Sequence[EvalRecord]) -> float | None:
    """``1 - brier/base_rate_brier``.  Positive means confidence adds information."""
    if not records:
        return None
    reference = base_rate_brier(records)
    score = brier_score(records)
    if reference is None or score is None or reference <= 0:
        return None
    return 1.0 - (score / reference)


def reliability_curve(
    records: Sequence[EvalRecord],
    n_bins: int = DEFAULT_RELIABILITY_BINS,
) -> list[dict[str, Any]]:
    """Reliability (calibration) curve over equal-width confidence bins.

    Bin ``i`` covers ``[i/n, (i+1)/n)``; confidence 1.0 lands in the top bin.
    Empty bins are omitted from the returned curve but contribute nothing to
    ECE either way.  A well-calibrated pipeline has ``hit_rate`` tracking
    ``mean_confidence`` and rising monotonically down the list.
    """
    if n_bins <= 0:
        return []
    buckets: dict[int, list[EvalRecord]] = defaultdict(list)
    for r in records:
        conf = min(max(r.confidence, 0.0), 1.0)
        idx = min(int(conf * n_bins), n_bins - 1)
        buckets[idx].append(r)

    curve: list[dict[str, Any]] = []
    total = len(records)
    for idx in sorted(buckets):
        bucket = buckets[idx]
        bucket_hit = hit_rate(bucket) or 0.0
        mean_conf = statistics.fmean(r.confidence for r in bucket)
        curve.append({
            "bin": f"{idx / n_bins:.1f}-{(idx + 1) / n_bins:.1f}",
            "bin_index": idx,
            "n": len(bucket),
            "share": round(len(bucket) / total, 4) if total else 0.0,
            "mean_confidence": round(mean_conf, 4),
            "hit_rate": round(bucket_hit, 4),
            "gap": round(bucket_hit - mean_conf, 4),
            "mean_alpha_pct": round(mean_alpha(bucket) or 0.0, 3),
        })
    return curve


def expected_calibration_error(
    records: Sequence[EvalRecord],
    n_bins: int = DEFAULT_RELIABILITY_BINS,
) -> float | None:
    """Sample-weighted mean gap between stated confidence and realised hit rate.

    0 is perfect; 1 is the worst attainable (total confidence, total failure).
    """
    if not records:
        return None
    curve = reliability_curve(records, n_bins)
    total = len(records)
    return sum(
        (row["n"] / total) * abs(row["hit_rate"] - row["mean_confidence"])
        for row in curve
    )


def calibration_slope(curve: Sequence[dict[str, Any]]) -> float | None:
    """OLS slope of hit rate on mean confidence, weighted by bin population.

    The single number that says whether the curve points the right way.
    Positive = more confidence means more accuracy.  The audited pipeline is
    negative, which is worse than uninformative.
    """
    rows = [r for r in curve if r["n"] > 0]
    if len(rows) < 2:
        return None
    weights = [r["n"] for r in rows]
    total_w = sum(weights)
    xs = [r["mean_confidence"] for r in rows]
    ys = [r["hit_rate"] for r in rows]
    mean_x = sum(w * x for w, x in zip(weights, xs)) / total_w
    mean_y = sum(w * y for w, y in zip(weights, ys)) / total_w
    denom = sum(w * (x - mean_x) ** 2 for w, x in zip(weights, xs))
    if denom == 0:
        return None
    numer = sum(w * (x - mean_x) * (y - mean_y) for w, x, y in zip(weights, xs, ys))
    return numer / denom


def cohort_metrics(
    records: Sequence[EvalRecord],
    n_bins: int = DEFAULT_RELIABILITY_BINS,
    with_curve: bool = True,
) -> dict[str, Any]:
    """Full metric block for one cohort of graded calls."""
    if not records:
        return {"n": 0}

    alphas = [r.alpha_pct * r.direction for r in records]
    curve = reliability_curve(records, n_bins)
    metrics: dict[str, Any] = {
        "n": len(records),
        "hit_rate": round(hit_rate(records) or 0.0, 4),
        "raw_hit_rate": round(raw_hit_rate(records) or 0.0, 4),
        "mean_alpha_pct": round(mean_alpha(records) or 0.0, 3),
        "median_alpha_pct": round(statistics.median(alphas), 3),
        "alpha_stdev_pct": round(statistics.stdev(alphas), 3) if len(alphas) > 1 else None,
        "mean_symbol_return_pct": round(
            statistics.fmean(r.symbol_return_pct for r in records), 3),
        "mean_benchmark_return_pct": round(
            statistics.fmean(r.benchmark_return_pct for r in records), 3),
        "mean_confidence": round(statistics.fmean(r.confidence for r in records), 4),
        "brier": round(brier_score(records) or 0.0, 4),
        "base_rate_brier": round(base_rate_brier(records) or 0.0, 4),
        "ece": round(expected_calibration_error(records, n_bins) or 0.0, 4),
    }
    bss = brier_skill_score(records)
    metrics["brier_skill_score"] = round(bss, 4) if bss is not None else None
    slope = calibration_slope(curve)
    metrics["calibration_slope"] = round(slope, 4) if slope is not None else None
    if with_curve:
        metrics["reliability_curve"] = curve
    return metrics


def _group(
    records: Sequence[EvalRecord],
    key: Any,
    n_bins: int,
    with_curve: bool = False,
) -> dict[str, Any]:
    buckets: dict[str, list[EvalRecord]] = defaultdict(list)
    for r in records:
        buckets[str(key(r))].append(r)
    return {
        k: cohort_metrics(v, n_bins, with_curve=with_curve)
        for k, v in sorted(buckets.items())
    }


# ---------------------------------------------------------------------------
# Price loading
# ---------------------------------------------------------------------------

async def load_local_series(db: AsyncSession, symbols: Iterable[str]) -> dict[str, Series]:
    """Load date-ascending close series for ``symbols`` from ``price_history``."""
    from models.price import PriceHistory
    from models.stock import Stock

    wanted = {s.upper() for s in symbols}
    if not wanted:
        return {}

    rows = (await db.execute(
        select(Stock.symbol, PriceHistory.date, PriceHistory.close)
        .join(PriceHistory, PriceHistory.stock_id == Stock.id)
        .where(Stock.symbol.in_(wanted))
        .order_by(Stock.symbol, PriceHistory.date)
    )).all()

    series: dict[str, Series] = defaultdict(list)
    for symbol, bar_date, close in rows:
        coerced = _coerce_date(bar_date)
        if coerced is None or close is None or float(close) <= 0:
            continue
        series[symbol.upper()].append((coerced, float(close)))
    for values in series.values():
        values.sort(key=lambda pair: pair[0])
    return dict(series)


def _load_price_cache() -> dict[str, list[list[Any]]]:
    if not PRICE_CACHE_PATH.exists():
        return {}
    try:
        with open(PRICE_CACHE_PATH) as fh:
            return json.load(fh)
    except Exception:  # pragma: no cover -- corrupt cache is not worth failing on
        logger.warning("Could not read eval price cache at %s", PRICE_CACHE_PATH)
        return {}


def _save_price_cache(cache: dict[str, list[list[Any]]]) -> None:
    PRICE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PRICE_CACHE_PATH, "w") as fh:
        json.dump(cache, fh)


def fetch_yfinance_series(
    symbols: Sequence[str],
    start: date,
    end: date,
) -> dict[str, Series]:
    """Blocking yfinance fallback for symbols the ETL never ingested.

    Results are cached on disk (:data:`PRICE_CACHE_PATH`) so a second run of the
    harness costs no network at all -- the repeatability requirement.
    """
    if not symbols:
        return {}

    cache = _load_price_cache()
    out: dict[str, Series] = {}
    missing: list[str] = []
    for symbol in symbols:
        cached = cache.get(symbol)
        if cached:
            parsed = [
                (parsed_date, float(close))
                for parsed_date, close in (
                    (_coerce_date(row[0]), row[1]) for row in cached
                )
                if parsed_date is not None and close and float(close) > 0
            ]
            if parsed:
                out[symbol] = sorted(parsed, key=lambda pair: pair[0])
                continue
        missing.append(symbol)

    if not missing:
        return out

    try:
        import yfinance as yf
    except ImportError:  # pragma: no cover
        logger.warning("yfinance unavailable -- %d symbols left unpriced", len(missing))
        return out

    logger.info("Fetching %d symbols from yfinance: %s", len(missing), ", ".join(missing))
    try:
        frame = yf.download(
            missing,
            start=start.isoformat(),
            end=end.isoformat(),
            progress=False,
            auto_adjust=False,
            group_by="ticker",
            threads=False,
        )
    except Exception as exc:  # pragma: no cover -- network failures are not fatal
        logger.warning("yfinance fallback failed: %s", exc)
        return out

    if frame is None or getattr(frame, "empty", True):
        return out

    for symbol in missing:
        try:
            if len(missing) == 1 and symbol not in getattr(frame.columns, "levels", [[]])[0]:
                closes = frame["Close"]
            else:
                closes = frame[symbol]["Close"]
        except Exception as exc:
            logger.debug("No yfinance close column for %s: %s", symbol, exc)
            continue
        values: Series = []
        for idx, close in closes.items():
            parsed_date = _coerce_date(idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx)
            if parsed_date is None or close is None:
                continue
            try:
                close_f = float(close)
            except (TypeError, ValueError):
                continue
            if close_f != close_f or close_f <= 0:  # NaN or non-positive
                continue
            values.append((parsed_date, close_f))
        if values:
            values.sort(key=lambda pair: pair[0])
            out[symbol] = values
            cache[symbol] = [[d.isoformat(), c] for d, c in values]

    try:
        _save_price_cache(cache)
    except Exception:  # pragma: no cover
        logger.warning("Could not write eval price cache")
    return out


def _merge_series(local: Series, remote: Series) -> Series:
    """Union of two series, preferring the local bar on any shared date.

    The DB is the system of record where it has data; yfinance only fills the
    dates the ETL never wrote.  Preferring local keeps a re-run stable even if
    the vendor silently restates a close.
    """
    merged = {bar_date: close for bar_date, close in remote}
    merged.update({bar_date: close for bar_date, close in local})
    return sorted(merged.items(), key=lambda pair: pair[0])


def _required_coverage(
    candidates: Sequence[dict[str, Any]],
) -> dict[str, tuple[date, date]]:
    """Calendar span each symbol's price series must cover to close its windows.

    Trading bars are converted to calendar days at 7/5 plus a holiday cushion;
    this only decides *whether to fetch*, so erring long is free.
    """
    needed: dict[str, tuple[date, date]] = {}
    today = date.today()
    for cand in candidates:
        created = cand["created_at"]
        created_date = created.date() if isinstance(created, datetime) else created
        # Use the longest horizon any sensitivity variant could ask for, so one
        # fetch covers every parameterisation the run will grade under.
        bars = max(
            [horizon_trading_days(cand["time_horizon"]) or 0]
            + [horizon_trading_days(cand["time_horizon"], o) or 0
               for o in HORIZON_SENSITIVITY_VARIANTS.values()]
        )
        span = int(bars * 7 / 5) + 10
        until = min(created_date + timedelta(days=span), today)
        symbol = cand["symbol"]
        if symbol not in needed:
            needed[symbol] = (created_date, until)
        else:
            start, end = needed[symbol]
            needed[symbol] = (min(start, created_date), max(end, until))
    return needed


def needs_topup(
    series: Series,
    start: date,
    end: date,
    max_gap_days: int = MAX_BAR_GAP_DAYS,
) -> bool:
    """True when a local series cannot support grading over ``[start, end]``.

    Three failure modes, all present in the live table: the symbol was never
    ingested, its history stops before the window closes, or it has an interior
    hole.  A hole is the subtle one -- ``entry_exit_indices`` counts *bars*, so
    a 50-day gap silently stretches a 21-bar horizon across 70 calendar days
    and the measured return stops being a 21-bar return.
    """
    if not series:
        return True
    if series[-1][0] < end:
        return True

    previous: date | None = None
    for bar_date, _ in series:
        if bar_date < start:
            previous = bar_date
            continue
        if bar_date > end:
            break
        if previous is not None and (bar_date - previous).days > max_gap_days:
            return True
        previous = bar_date
    return False


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

def build_record(
    *,
    insight_id: int,
    symbol: str,
    action: str,
    direction: int,
    confidence: float,
    created_at: datetime,
    pipeline_version: str,
    horizon_bars: int,
    symbol_series: Series,
    benchmark_series: Series,
    price_source: str = "db",
    entry_lag: int = ENTRY_LAG_TRADING_DAYS,
) -> tuple[EvalRecord | None, str | None]:
    """Grade one insight.  Returns ``(record, None)`` or ``(None, exclusion_reason)``."""
    created = created_at.date() if isinstance(created_at, datetime) else created_at
    dates = [d for d, _ in symbol_series]

    window = entry_exit_indices(dates, created, horizon_bars, entry_lag)
    if window is None:
        # Distinguish "never traded after the call" from "window still open".
        if not dates or dates[-1] <= created:
            return None, "entry_bar_missing"
        return None, "horizon_not_elapsed"

    entry_idx, exit_idx = window
    entry_date, entry_price = symbol_series[entry_idx]
    exit_date, exit_price = symbol_series[exit_idx]

    # A hole in the series would make the window span far more calendar time
    # than its trading-bar horizon implies, so the "21-bar return" would not be
    # one.  Reject rather than silently mismeasure.
    implied_days = horizon_bars * 7 / 5
    if (exit_date - entry_date).days > implied_days * MAX_WINDOW_STRETCH + 10:
        return None, "window_gapped"

    symbol_ret = pct_return(entry_price, exit_price)
    if symbol_ret is None:
        return None, "invalid_price"

    bench_entry = close_on_or_before(benchmark_series, entry_date)
    bench_exit = close_on_or_before(benchmark_series, exit_date)
    bench_ret = pct_return(bench_entry, bench_exit) if bench_entry and bench_exit else None
    if bench_ret is None:
        return None, "no_benchmark_bar"

    alpha = symbol_ret - bench_ret
    return EvalRecord(
        insight_id=insight_id,
        symbol=symbol,
        action=action,
        direction=direction,
        confidence=float(confidence),
        created_at=created_at.isoformat() if isinstance(created_at, datetime) else str(created_at),
        pipeline_version=pipeline_version,
        horizon_trading_days=horizon_bars,
        entry_date=entry_date.isoformat(),
        exit_date=exit_date.isoformat(),
        entry_price=round(entry_price, 4),
        exit_price=round(exit_price, 4),
        symbol_return_pct=round(symbol_ret, 4),
        benchmark_return_pct=round(bench_ret, 4),
        alpha_pct=round(alpha, 4),
        correct=(alpha * direction) > 0,
        raw_correct=(symbol_ret * direction) > 0,
        price_source=price_source,
    ), None


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def run_insight_eval(
    db: AsyncSession,
    *,
    save: bool = True,
    allow_network: bool = False,
    n_bins: int = DEFAULT_RELIABILITY_BINS,
    include_records: bool = True,
    entry_lag: int = ENTRY_LAG_TRADING_DAYS,
    benchmark: str = BENCHMARK_SYMBOL,
) -> dict[str, Any]:
    """Grade every elapsed directional ``DeepInsight`` and return a snapshot dict.

    Args:
        db: async session; only SELECTs are issued.
        save: write ``data/insight_eval.json`` and append to the history log.
        allow_network: permit the disk-cached yfinance fallback for symbols the
            ETL never ingested.  ``False`` keeps the run strictly local.
        n_bins: reliability-curve resolution (10 = deciles).
        include_records: embed the per-call rows so a snapshot is auditable.
        entry_lag: trading bars between ``created_at`` and the entry close.
        benchmark: symbol the alpha is measured against.
    """
    from models.deep_insight import DeepInsight

    # Explicit columns, not the ORM entity: ``DeepInsight.outcome`` and
    # ``.research_context`` are ``lazy="selectin"``, so loading the entity would
    # drag in ``insight_outcomes`` -- the very table this harness must not
    # depend on, and one whose schema is actively changing.  Selecting columns
    # makes that independence structural rather than a matter of discipline.
    insights = (await db.execute(
        select(
            DeepInsight.id,
            DeepInsight.action,
            DeepInsight.primary_symbol,
            DeepInsight.confidence,
            DeepInsight.time_horizon,
            DeepInsight.created_at,
            DeepInsight.discovery_context,
        ).order_by(DeepInsight.created_at)
    )).all()

    ledger = ExclusionLedger()

    # Pass 1 -- filter to gradeable candidates and collect the symbol universe.
    candidates: list[dict[str, Any]] = []
    for insight in insights:
        action = (insight.action or "").strip().upper()
        direction = direction_for_action(action)
        if direction is None:
            reason = ("non_directional_action" if action in NON_DIRECTIONAL_ACTIONS
                      else "unknown_action")
            ledger.record(reason, insight.id)
            continue

        symbol = (insight.primary_symbol or "").strip().upper()
        if not symbol:
            ledger.record("no_primary_symbol", insight.id)
            continue
        if symbol in NON_TRADEABLE_SYMBOLS:
            ledger.record("non_tradeable_symbol", insight.id)
            continue
        if insight.confidence is None:
            ledger.record("missing_confidence", insight.id)
            continue

        if horizon_trading_days(insight.time_horizon) is None:
            # No resolvable window.  Excluded rather than graded over an
            # invented horizon -- a made-up window produces a made-up grade.
            ledger.record("unknown_horizon", insight.id)
            continue

        candidates.append({
            "insight_id": insight.id,
            "symbol": symbol,
            "action": action,
            "direction": direction,
            "confidence": float(insight.confidence),
            "created_at": insight.created_at,
            "time_horizon": insight.time_horizon,
            "pipeline_version": pipeline_version_for(
                insight.created_at, insight.discovery_context),
        })

    symbols = {c["symbol"] for c in candidates}
    series_map = await load_local_series(db, symbols | {benchmark})
    price_source = {s: "price_history" for s in series_map}

    # A symbol needs the network when the ETL never ingested it *or* when its
    # local history stops before the last exit date this eval needs.  Only 16 of
    # ~400 symbols in the live table are current, so treating staleness as
    # "missing data" would silently drop most of the sample.
    needed = _required_coverage(candidates)
    # The benchmark is held to the same standard as any symbol.  The live SPY
    # series has multi-week holes (no July 2026 bars at all); an unpatched
    # benchmark silently voids every window that lands in one.
    if needed:
        needed[benchmark] = (
            min(start for start, _ in needed.values()),
            max(end for _, end in needed.values()),
        )
    stale = sorted(
        symbol for symbol, (start, end) in needed.items()
        if needs_topup(series_map.get(symbol, []), start, end)
    )
    coverage = {
        "symbols_required": len(needed),
        "local_sufficient": len(needed) - len(stale),
        "needed_topup": len(stale),
    }

    if stale and allow_network:
        start = min(s for s, _ in needed.values())
        fetched = fetch_yfinance_series(stale, start, date.today())
        for symbol, values in fetched.items():
            merged = _merge_series(series_map.get(symbol, []), values)
            series_map[symbol] = merged
            price_source[symbol] = "yfinance" if symbol not in price_source else "merged"
        coverage["topped_up"] = len(fetched)
        coverage["topup_failed"] = len(stale) - len(fetched)

    benchmark_series = series_map.get(benchmark, [])

    if not benchmark_series:
        return {
            "error": f"benchmark {benchmark} has no price history -- cannot compute alpha",
            "harness_version": HARNESS_VERSION,
            "candidates": len(candidates),
        }

    # Pass 2 -- grade under the canonical horizons, then under each variant.
    records = _grade(
        candidates, series_map, benchmark_series, price_source, entry_lag,
        overrides=None, ledger=ledger,
    )
    sensitivity = _horizon_sensitivity(
        candidates, series_map, benchmark_series, price_source, entry_lag,
        primary=records, n_bins=n_bins,
    )

    last_bar = max((d for d, _ in benchmark_series), default=None)
    snapshot: dict[str, Any] = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "harness_version": HARNESS_VERSION,
        "pipeline_version": CURRENT_PIPELINE_VERSION,
        "git_sha": _git_sha(),
        "params": {
            "benchmark": benchmark,
            "entry_lag_trading_days": entry_lag,
            "reliability_bins": n_bins,
            "horizon_trading_days": HORIZON_TRADING_DAYS,
            "horizon_source": "analysis.horizons (shared with outcome_tracker)",
            "label_rule": "sign(symbol_return - benchmark_return) == predicted_direction",
            "allow_network": allow_network,
            "last_benchmark_bar": last_bar.isoformat() if last_bar else None,
        },
        "universe": {
            "insights_total": len(insights),
            "directional_candidates": len(candidates),
            "graded": len(records),
            "graded_share_of_candidates": (
                round(len(records) / len(candidates), 4) if candidates else 0.0),
            "symbols_graded": len({r.symbol for r in records}),
            "price_source_counts": _count(r.price_source for r in records),
            "price_coverage": coverage,
            "date_range": {
                "first_insight": records[0].created_at if records else None,
                "last_insight": max((r.created_at for r in records), default=None),
            },
        },
        "exclusions": ledger.to_dict(),
        "horizon_sensitivity": sensitivity,
        "overall": cohort_metrics(records, n_bins, with_curve=True),
        "by_pipeline_version": _group(records, lambda r: r.pipeline_version, n_bins, True),
        "by_month": _group(records, lambda r: r.month, n_bins),
        "by_action": _group(records, lambda r: r.action, n_bins),
        "by_direction": _group(
            records, lambda r: "long" if r.direction > 0 else "short", n_bins, True),
    }
    if include_records:
        snapshot["records"] = [asdict(r) for r in records]

    if save:
        _save_snapshot(snapshot)
    return snapshot


def _grade(
    candidates: Sequence[dict[str, Any]],
    series_map: dict[str, Series],
    benchmark_series: Series,
    price_source: dict[str, str],
    entry_lag: int,
    overrides: dict[str, int] | None,
    ledger: ExclusionLedger | None = None,
) -> list[EvalRecord]:
    """Grade every candidate under one horizon table.

    ``ledger`` is only passed for the primary run -- the sensitivity variants
    reuse this to score the same candidates over different windows and their
    exclusions are not part of the published accounting.
    """
    records: list[EvalRecord] = []
    for cand in candidates:
        bars = horizon_trading_days(cand["time_horizon"], overrides)
        if bars is None:
            if ledger:
                ledger.record("unknown_horizon", cand["insight_id"])
            continue
        series = series_map.get(cand["symbol"])
        if not series:
            if ledger:
                ledger.record("no_price_series", cand["insight_id"])
            continue
        record, reason = build_record(
            insight_id=cand["insight_id"],
            symbol=cand["symbol"],
            action=cand["action"],
            direction=cand["direction"],
            confidence=cand["confidence"],
            created_at=cand["created_at"],
            pipeline_version=cand["pipeline_version"],
            horizon_bars=bars,
            symbol_series=series,
            benchmark_series=benchmark_series,
            price_source=price_source.get(cand["symbol"], "price_history"),
            entry_lag=entry_lag,
        )
        if record is None:
            if ledger:
                ledger.record(reason or "invalid_price", cand["insight_id"])
            continue
        records.append(record)
    return records


def _horizon_sensitivity(
    candidates: Sequence[dict[str, Any]],
    series_map: dict[str, Series],
    benchmark_series: Series,
    price_source: dict[str, str],
    entry_lag: int,
    primary: Sequence[EvalRecord],
    n_bins: int,
) -> dict[str, Any]:
    """Headline metrics under alternative horizon tables, on a like-for-like sample.

    A shorter horizon closes sooner, so it admits insights a longer one cannot
    see yet.  Comparing full samples across settings would therefore conflate
    *which insights became gradeable* with *how good the analysis was* --
    differing in sample size, calendar period and market regime at once.  The
    headline comparison here is restricted to the insights graded under **both**
    settings; the differing full-sample sizes are reported separately and
    flagged as not directly comparable.
    """
    out: dict[str, Any] = {
        "note": (
            "Anchor on 'comparable_intersection'. The 'full_samples_NOT_comparable' "
            "rows score different populations: a shorter horizon closes sooner and "
            "admits newer insights, so those rows differ in sample size, calendar "
            "period and benchmark regime simultaneously. Quoting them side by side "
            "attributes a population change to a parameter change."
        ),
        "variants": {},
    }
    primary_by_id = {r.insight_id: r for r in primary}

    for name, overrides in HORIZON_SENSITIVITY_VARIANTS.items():
        alt = _grade(
            candidates, series_map, benchmark_series, price_source, entry_lag,
            overrides=overrides, ledger=None,
        )
        alt_by_id = {r.insight_id: r for r in alt}
        shared = sorted(set(primary_by_id) & set(alt_by_id))

        # Records the shipped setting can see and the variant cannot.  This is
        # the confound made explicit: if these cluster into one cohort, that
        # cohort's apparent movement is largely "who got let into the sample".
        only_shipped = [primary_by_id[i] for i in set(primary_by_id) - set(alt_by_id)]
        only_variant = [alt_by_id[i] for i in set(alt_by_id) - set(primary_by_id)]

        out["variants"][name] = {
            "overrides": overrides,
            "intersection_n": len(shared),
            "comparable_intersection": {
                "shipped": _headline([primary_by_id[i] for i in shared], n_bins),
                "variant": _headline([alt_by_id[i] for i in shared], n_bins),
            },
            "admitted_only_by_shipped": {
                "n": len(only_shipped),
                "by_pipeline_version": _count(r.pipeline_version for r in only_shipped),
                "by_month": _count(r.month for r in only_shipped),
            },
            "admitted_only_by_variant": {
                "n": len(only_variant),
                "by_pipeline_version": _count(r.pipeline_version for r in only_variant),
            },
            "full_samples_NOT_comparable": {
                "why": (
                    f"{len(only_shipped)} records are gradeable only under the shipped "
                    f"setting and {len(only_variant)} only under the variant; these rows "
                    "are reported for completeness and must not be compared to each other"
                ),
                "shipped": _headline(primary, n_bins),
                "variant": _headline(alt, n_bins),
            },
        }
    return out


def _headline(records: Sequence[EvalRecord], n_bins: int) -> dict[str, Any]:
    """The few numbers worth comparing across parameterisations."""
    block = cohort_metrics(records, n_bins, with_curve=False)
    keys = ("n", "hit_rate", "raw_hit_rate", "mean_alpha_pct", "median_alpha_pct",
            "ece", "brier", "base_rate_brier", "brier_skill_score",
            "calibration_slope", "mean_benchmark_return_pct")
    return {k: block.get(k) for k in keys}


def _count(values: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for value in values:
        out[value] += 1
    return dict(out)


def _git_sha() -> str | None:
    """Short SHA of the checkout, so a snapshot can be traced to the code that made it."""
    import shutil
    import subprocess

    git = shutil.which("git")
    if not git:
        return None
    try:
        return subprocess.run(  # noqa: S603 — fixed argv, resolved git path, no shell
            [git, "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).parent.parent),
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip() or None
    except Exception:
        return None


def _save_snapshot(snapshot: dict[str, Any]) -> None:
    """Write the full snapshot and append a compact row to the history log.

    Mirrors ``backtester.CALIBRATION_PATH``: latest-run JSON under ``data/``.
    The extra JSONL history exists because the point of the harness is
    comparing two runs across a deliberate change, which needs more than one.
    """
    EVAL_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(EVAL_SNAPSHOT_PATH, "w") as fh:
        json.dump(snapshot, fh, indent=2)
    logger.info("Insight eval snapshot saved to %s", EVAL_SNAPSHOT_PATH)

    overall = snapshot.get("overall", {})
    row = {
        "as_of": snapshot.get("as_of"),
        "harness_version": snapshot.get("harness_version"),
        "pipeline_version": snapshot.get("pipeline_version"),
        "git_sha": snapshot.get("git_sha"),
        "n": overall.get("n"),
        "hit_rate": overall.get("hit_rate"),
        "mean_alpha_pct": overall.get("mean_alpha_pct"),
        "ece": overall.get("ece"),
        "brier": overall.get("brier"),
        "brier_skill_score": overall.get("brier_skill_score"),
        "calibration_slope": overall.get("calibration_slope"),
        "excluded": snapshot.get("exclusions", {}).get("total_excluded"),
    }
    with open(EVAL_HISTORY_PATH, "a") as fh:
        fh.write(json.dumps(row) + "\n")


def load_insight_eval() -> dict[str, Any] | None:
    """Load the most recent snapshot from disk, or ``None`` if never run."""
    if not EVAL_SNAPSHOT_PATH.exists():
        return None
    try:
        with open(EVAL_SNAPSHOT_PATH) as fh:
            return json.load(fh)
    except Exception:
        return None


def format_eval_summary(snapshot: dict[str, Any]) -> str:
    """Render a snapshot as a plain-text report."""
    if "error" in snapshot:
        return f"eval failed: {snapshot['error']}"

    overall = snapshot["overall"]
    universe = snapshot["universe"]
    lines = [
        f"Insight eval  harness={snapshot['harness_version']}  "
        f"pipeline={snapshot['pipeline_version']}  sha={snapshot.get('git_sha')}",
        f"graded {overall.get('n', 0)} of {universe['directional_candidates']} "
        f"directional calls ({universe['insights_total']} insights total)",
        "",
        f"  benchmark-adjusted hit rate : {overall.get('hit_rate')}",
        f"  raw (unadjusted) hit rate   : {overall.get('raw_hit_rate')}",
        f"  mean alpha per call         : {overall.get('mean_alpha_pct')}%",
        f"  median alpha per call       : {overall.get('median_alpha_pct')}%",
        f"  mean confidence             : {overall.get('mean_confidence')}",
        f"  ECE                         : {overall.get('ece')}",
        f"  Brier                       : {overall.get('brier')} "
        f"(base-rate benchmark {overall.get('base_rate_brier')})",
        f"  Brier skill score           : {overall.get('brier_skill_score')}",
        f"  calibration slope           : {overall.get('calibration_slope')}",
        "",
        "  reliability curve (confidence bin -> realised hit rate):",
    ]
    for row in overall.get("reliability_curve", []):
        lines.append(
            f"    {row['bin']}  n={row['n']:>4}  conf={row['mean_confidence']:.3f}  "
            f"hit={row['hit_rate']:.3f}  gap={row['gap']:+.3f}  "
            f"alpha={row['mean_alpha_pct']:+.2f}%"
        )

    sens = snapshot.get("horizon_sensitivity", {})
    for name, block in sens.get("variants", {}).items():
        lines.append("")
        lines.append(
            f"  horizon sensitivity [{name} = {block['overrides']}], "
            f"like-for-like on {block['intersection_n']} calls graded under both:"
        )
        for label in ("shipped", "variant"):
            h = block["comparable_intersection"][label]
            lines.append(
                f"    {label:<8} hit={h['hit_rate']:.4f}  alpha={h['mean_alpha_pct']:+.3f}%  "
                f"ece={h['ece']:.4f}  brier={h['brier']:.4f}  bss={h['brier_skill_score']:+.4f}"
            )
        only = block["admitted_only_by_shipped"]
        if only["n"]:
            lines.append(
                f"    {only['n']} records are gradeable ONLY under the shipped setting, "
                f"concentrated in: {only['by_pipeline_version']}"
            )
        lines.append(
            f"    full samples (shipped n={block['full_samples_NOT_comparable']['shipped']['n']}, "
            f"variant n={block['full_samples_NOT_comparable']['variant']['n']}) are NOT comparable"
        )

    lines.append("")
    lines.append("  exclusions:")
    for reason, count in sorted(
        snapshot["exclusions"]["by_reason"].items(), key=lambda kv: -kv[1]
    ):
        lines.append(f"    {reason:<24} {count}")

    for label, key in (
        ("by pipeline version", "by_pipeline_version"),
        ("by month", "by_month"),
        ("by action", "by_action"),
        ("by direction", "by_direction"),
    ):
        lines.append("")
        lines.append(f"  {label}:")
        for name, block in snapshot.get(key, {}).items():
            if not block.get("n"):
                continue
            lines.append(
                f"    {name:<22} n={block['n']:>4}  hit={block['hit_rate']:.3f}  "
                f"alpha={block['mean_alpha_pct']:+.2f}%  ece={block['ece']:.3f}  "
                f"brier={block['brier']:.3f}"
            )
    return "\n".join(lines)


async def _main() -> None:  # pragma: no cover -- CLI entry point
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate the DeepInsight pipeline.")
    parser.add_argument("--allow-network", action="store_true",
                        help="use the cached yfinance fallback for symbols missing from the DB")
    parser.add_argument("--no-save", action="store_true", help="do not write the snapshot")
    parser.add_argument("--bins", type=int, default=DEFAULT_RELIABILITY_BINS)
    args = parser.parse_args()

    from database import async_session_factory

    async with async_session_factory() as session:
        snapshot = await run_insight_eval(
            session,
            save=not args.no_save,
            allow_network=args.allow_network,
            n_bins=args.bins,
        )
    print(format_eval_summary(snapshot))  # noqa: T201 — CLI report


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(_main())
