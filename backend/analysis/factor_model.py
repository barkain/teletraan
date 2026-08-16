"""Multi-factor scoring model for quantitative pre-screening of stock candidates.

Computes composite factor scores across six dimensions (momentum, value, quality,
volatility, volume, technical) to replace crude heuristic screening in the
autonomous analysis pipeline. Each factor is z-scored against the universe and
converted to a 0-100 percentile rank before weighted aggregation.

Fundamental data (PE, PB, ROE, etc.) is fetched via yfinance with a 5-min TTL
cache. Blocking yfinance calls use run_in_executor with a ThreadPoolExecutor.

Missing evidence is represented as missing, never as a neutral 50: a factor
that could not be measured is dropped from that symbol's composite and the
remaining weights are renormalized to sum to 1.0. A symbol whose measured
factors cover less than MIN_FACTOR_COVERAGE of the total weight is not scored
at all, so thin evidence cannot masquerade as an average-across-the-board
candidate and outrank a fully measured one.
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import yfinance as yf  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Non-equity symbol filter
# ---------------------------------------------------------------------------
# Patterns that indicate non-equity instruments (futures, indices, etc.)
_NON_EQUITY_PATTERNS = ("=F", "^", "-USD", "=X")


def _is_equity_symbol(symbol: str) -> bool:
    """Return True if *symbol* looks like a plain equity ticker.

    Filters out futures (``GC=F``), indices (``^VIX``), forex
    (``EURUSD=X``), and crypto pairs (``BTC-USD``).
    """
    for pat in _NON_EQUITY_PATTERNS:
        if pat in symbol:
            return False
    return True


# ---------------------------------------------------------------------------
# Fundamental data cache (5-minute TTL)
# ---------------------------------------------------------------------------
_fundamental_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL = 300  # 5 minutes


def _get_cached_fundamental(symbol: str) -> dict[str, Any] | None:
    if symbol in _fundamental_cache:
        ts, data = _fundamental_cache[symbol]
        if time.time() - ts < _CACHE_TTL:
            return data
        del _fundamental_cache[symbol]
    return None


def _set_fundamental_cache(symbol: str, data: dict[str, Any]) -> None:
    _fundamental_cache[symbol] = (time.time(), data)


# ---------------------------------------------------------------------------
# Factor weights
# ---------------------------------------------------------------------------
FACTOR_WEIGHTS = {
    "momentum": 0.25,
    "value": 0.20,
    "quality": 0.20,
    "volatility": 0.15,
    "volume": 0.10,
    "technical": 0.10,
}

# Retained for backwards compatibility. No longer used to switch weighting
# schemes: missing factors are now dropped and the surviving FACTOR_WEIGHTS are
# renormalized, which reproduces roughly these numbers when fundamentals are
# absent (momentum 0.417, volatility 0.25, volume 0.167, technical 0.167).
DEGRADED_WEIGHTS = {
    "momentum": 0.40,
    "value": 0.0,
    "quality": 0.0,
    "volatility": 0.25,
    "volume": 0.20,
    "technical": 0.15,
}

FACTOR_NAMES = ("momentum", "value", "quality", "volatility", "volume", "technical")

# A symbol must have factors covering at least this share of the total weight
# before it gets a ranked composite. 0.50 admits the market-data-only path
# (momentum + volatility + volume + technical = 0.60 of total weight) while
# rejecting anything thinner — e.g. momentum + volume alone (0.35), which is
# not enough evidence to put a stock in front of an analyst.
MIN_FACTOR_COVERAGE = 0.50

# Momentum is itself a composite of 5d/20d/60d returns. Require sub-components
# covering at least half its internal weight so "momentum" never means a lone
# 5-day return.
_MOMENTUM_SUBWEIGHTS = {"5d": 0.3, "20d": 0.5, "60d": 0.2}
MIN_MOMENTUM_COVERAGE = 0.5


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class FactorScore:
    """Composite and per-factor scores for a single symbol.

    Per-factor scores are ``None`` when the underlying input was unavailable —
    never a neutral 50 — and such factors are excluded from the composite with
    the remaining weights renormalized. ``coverage`` is the share of total
    factor weight that was actually measured.
    """

    symbol: str
    composite_score: float  # 0-100, weighted over measured factors only
    coverage: float = 0.0
    momentum_score: float | None = None
    value_score: float | None = None
    quality_score: float | None = None
    volatility_score: float | None = None
    volume_score: float | None = None
    technical_score: float | None = None
    factors_used: list[str] = field(default_factory=list)
    missing_factors: list[str] = field(default_factory=list)
    effective_weights: dict[str, float] = field(default_factory=dict)
    factor_details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize. Unmeasured per-factor scores are omitted, not zeroed.

        Consumers that default a missing key (``scores.get("value_score", 50)``)
        keep rendering; ``missing_factors`` tells them which of those defaults
        are placeholders.
        """
        result: dict[str, Any] = {
            "symbol": self.symbol,
            "composite_score": round(self.composite_score, 2),
            "coverage": round(self.coverage, 3),
            "factors_used": self.factors_used,
            "missing_factors": self.missing_factors,
            "effective_weights": {
                k: round(v, 4) for k, v in self.effective_weights.items()
            },
            "factor_details": self.factor_details,
        }
        for name in FACTOR_NAMES:
            value = getattr(self, f"{name}_score")
            if value is not None:
                result[f"{name}_score"] = round(value, 2)
        return result


# ---------------------------------------------------------------------------
# Helper: rendering optional factor scores
# ---------------------------------------------------------------------------
def format_factor_value(
    value: float | None,
    spec: str = ".0f",
    missing: str = "n/a",
) -> str:
    """Render one factor score, or an explicit absence marker when unmeasured.

    Per-factor scores are ``None`` by design (see :class:`FactorScore`), so a
    bare ``f"{value:.0f}"`` raises ``TypeError`` on exactly the honest-coverage
    rows this model was changed to produce.  Every text formatter goes through
    here; the HTML report's ``_factor_cell`` is the same rule in markup.

    Note what this deliberately does *not* do: substitute ``0`` or ``50``.  A
    missing factor must read as missing all the way to the prompt, or the
    coverage accounting upstream is decorative.
    """
    if value is None:
        return missing
    return format(float(value), spec)


# ---------------------------------------------------------------------------
# Helper: z-score -> percentile rank (0-100)
# ---------------------------------------------------------------------------
def _zscore_to_percentile(values: list[float | None]) -> list[float | None]:
    """Convert raw values to 0-100 percentile ranks via z-scoring.

    None entries stay None: a symbol that did not report a factor must remain
    distinguishable from one that reported an average value. Fewer than two
    observations means the factor cannot be ranked cross-sectionally at all,
    so every entry comes back None.
    """
    clean: list[tuple[int, float]] = [
        (i, v) for i, v in enumerate(values) if v is not None
    ]
    if len(clean) < 2:
        return [None] * len(values)

    vals = [v for _, v in clean]
    mean = sum(vals) / len(vals)
    variance = sum((v - mean) ** 2 for v in vals) / len(vals)

    result: list[float | None] = [None] * len(values)
    if variance <= 0:
        # No cross-sectional dispersion — every observation genuinely sits at
        # the median. This is a measurement, not a placeholder.
        for idx, _ in clean:
            result[idx] = 50.0
        return result

    std = variance**0.5
    for idx, val in clean:
        z = (val - mean) / std
        # Clamp z to [-3, 3] then map to 0-100
        z = max(-3.0, min(3.0, z))
        result[idx] = round((z + 3.0) / 6.0 * 100.0, 2)
    return result


def _inverse_zscore_to_percentile(values: list[float | None]) -> list[float | None]:
    """Like _zscore_to_percentile but inverted (lower raw = higher score).

    Used for volatility where lower is better.
    """
    inverted: list[float | None] = [(-v if v is not None else None) for v in values]
    return _zscore_to_percentile(inverted)


def _first_present(data: dict[str, Any], *keys: str) -> float | None:
    """Return the first key that is present and non-None, as a float.

    Uses an explicit None check rather than ``or`` chaining so a legitimate
    0.0 return is not treated as absent.
    """
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


# ---------------------------------------------------------------------------
# FactorModel
# ---------------------------------------------------------------------------
class FactorModel:
    """Multi-factor scoring model for stock screening."""

    def __init__(self) -> None:
        # Symbols dropped by the most recent compute_factor_scores() call,
        # mapped to the coverage they achieved. Useful for diagnostics.
        self.last_excluded: dict[str, float] = {}

    async def compute_factor_scores(
        self,
        heatmap_data: dict[str, dict],
        fundamental_data: dict[str, dict] | None = None,
    ) -> dict[str, FactorScore]:
        """Compute composite factor scores for all symbols in the heatmap.

        Factors that could not be measured for a symbol are excluded from that
        symbol's composite and the surviving weights are renormalized to sum to
        1.0, so a score is always an average over real evidence. Symbols whose
        measured factors cover less than ``MIN_FACTOR_COVERAGE`` of the total
        weight are omitted from the result entirely — they are not ranked.

        Args:
            heatmap_data: Mapping of symbol -> dict with keys like price,
                return_1d (or change_1d), return_5d (or change_5d),
                return_20d (or change_20d), change_60d, volume_ratio,
                rsi_14, volatility_20d.
            fundamental_data: Optional mapping of symbol -> dict with keys
                like pe_ratio, pb_ratio, fcf_yield, roe, profit_margins,
                debt_to_equity. If None, value/quality factors are skipped.

        Returns:
            Dict mapping symbol -> FactorScore, covering only symbols that
            cleared the coverage threshold.
        """
        symbols = list(heatmap_data.keys())
        self.last_excluded = {}
        if not symbols:
            return {}

        has_fundamentals = fundamental_data is not None and len(fundamental_data) > 0

        # --- Extract raw factor values ---
        momentum_raw: list[float | None] = []
        volume_raw: list[float | None] = []
        volatility_raw: list[float | None] = []
        technical_raw: list[float | None] = []
        value_raw: list[float | None] = []
        quality_raw: list[float | None] = []

        details_per_symbol: list[dict[str, Any]] = []

        for sym in symbols:
            d = heatmap_data[sym]
            det: dict[str, Any] = {}

            # Momentum: composite of 5d (30%), 20d (50%), 60d (20%).
            # Whichever windows are present are renormalized among themselves;
            # a missing window is never substituted with 0.0 ("flat").
            returns = {
                "5d": _first_present(d, "return_5d", "change_5d"),
                "20d": _first_present(d, "return_20d", "change_20d"),
                "60d": _first_present(d, "return_60d", "change_60d"),
            }
            present = {k: v for k, v in returns.items() if v is not None}
            sub_coverage = sum(_MOMENTUM_SUBWEIGHTS[k] for k in present)
            if present and sub_coverage >= MIN_MOMENTUM_COVERAGE:
                mom = (
                    sum(_MOMENTUM_SUBWEIGHTS[k] * v for k, v in present.items())
                    / sub_coverage
                )
                momentum_raw.append(mom)
                det["momentum_composite"] = round(mom, 4)
                det["momentum_windows"] = sorted(present)
            else:
                momentum_raw.append(None)
                det["momentum_windows"] = sorted(present)

            # Volume ratio
            vr = _first_present(d, "volume_ratio")
            volume_raw.append(vr)
            det["volume_ratio"] = vr

            # Volatility (lower is better — will be inverted)
            vol = _first_present(d, "volatility_20d")
            volatility_raw.append(vol)
            det["volatility_20d"] = vol

            # Technical: RSI mean-reversion signal
            # Oversold (<30) = bullish -> high score; Overbought (>70) = bearish -> low score
            rsi = _first_present(d, "rsi_14", "rsi")
            if rsi is not None:
                # Invert RSI: 100 - RSI so that oversold maps to high values
                technical_raw.append(100.0 - rsi)
                det["rsi_14"] = rsi
            else:
                technical_raw.append(None)

            # Value factors (if fundamentals available)
            if fundamental_data is not None and sym in fundamental_data:
                fd = fundamental_data[sym]
                pe = fd.get("pe_ratio")
                pb = fd.get("pb_ratio")
                fcf_y = fd.get("fcf_yield")

                earnings_yield = (1.0 / pe) if pe and pe > 0 else None
                book_yield = (1.0 / pb) if pb and pb > 0 else None

                components = [
                    v for v in [earnings_yield, book_yield, fcf_y] if v is not None
                ]
                val_composite = sum(components) / len(components) if components else None
                value_raw.append(val_composite)
                det["earnings_yield"] = earnings_yield
                det["book_yield"] = book_yield
                det["fcf_yield"] = fcf_y
            else:
                value_raw.append(None)

            # Quality factors
            if fundamental_data is not None and sym in fundamental_data:
                fd = fundamental_data[sym]
                roe = fd.get("roe")
                margins = fd.get("profit_margins")
                dte = fd.get("debt_to_equity")

                # For debt_to_equity, lower is better -> invert. yfinance
                # reports D/E as a percentage (150.0 == 1.5x), so rescale
                # before inverting; otherwise inv_dte collapses toward 0 and
                # drags the average of roe/margins (both ~0-1) with it.
                inv_dte = None
                if dte is not None and dte >= 0:
                    dte_ratio = dte / 100.0 if dte > 3.0 else float(dte)
                    inv_dte = 1.0 / (1.0 + dte_ratio)
                components = [
                    v for v in [roe, margins, inv_dte] if v is not None
                ]
                qual_composite = (
                    sum(components) / len(components) if components else None
                )
                quality_raw.append(qual_composite)
                det["roe"] = roe
                det["profit_margins"] = margins
                det["debt_to_equity"] = dte
            else:
                quality_raw.append(None)

            details_per_symbol.append(det)

        # --- Z-score each factor to 0-100 percentile ---
        momentum_pct = _zscore_to_percentile(momentum_raw)
        volume_pct = _zscore_to_percentile(volume_raw)
        volatility_pct = _inverse_zscore_to_percentile(volatility_raw)
        technical_pct = _zscore_to_percentile(technical_raw)
        value_pct = _zscore_to_percentile(value_raw)
        quality_pct = _zscore_to_percentile(quality_raw)

        by_factor: dict[str, list[float | None]] = {
            "momentum": momentum_pct,
            "value": value_pct,
            "quality": quality_pct,
            "volatility": volatility_pct,
            "volume": volume_pct,
            "technical": technical_pct,
        }

        # --- Compute weighted composite over measured factors only ---
        result: dict[str, FactorScore] = {}
        for i, sym in enumerate(symbols):
            measured: dict[str, float] = {}
            for name in FACTOR_NAMES:
                value = by_factor[name][i]
                if value is not None:
                    measured[name] = value
            missing = [name for name in FACTOR_NAMES if name not in measured]
            coverage = sum(FACTOR_WEIGHTS[name] for name in measured)

            if coverage < MIN_FACTOR_COVERAGE:
                # Not enough measured evidence to rank this symbol at all.
                self.last_excluded[sym] = round(coverage, 3)
                continue

            # Renormalize the surviving weights so they sum to 1.0.
            effective = {
                name: FACTOR_WEIGHTS[name] / coverage for name in measured
            }
            composite = sum(
                measured[name] * weight for name, weight in effective.items()
            )

            details = details_per_symbol[i]
            details["coverage"] = round(coverage, 3)
            details["missing_factors"] = missing

            result[sym] = FactorScore(
                symbol=sym,
                composite_score=round(composite, 2),
                coverage=coverage,
                momentum_score=momentum_pct[i],
                value_score=value_pct[i],
                quality_score=quality_pct[i],
                volatility_score=volatility_pct[i],
                volume_score=volume_pct[i],
                technical_score=technical_pct[i],
                factors_used=sorted(measured),
                missing_factors=missing,
                effective_weights=effective,
                factor_details=details,
            )

        logger.info(
            "Factor scores computed for %d/%d symbols (fundamentals=%s); "
            "%d excluded below %.0f%% coverage",
            len(result),
            len(symbols),
            has_fundamentals,
            len(self.last_excluded),
            MIN_FACTOR_COVERAGE * 100,
        )
        return result

    async def fetch_fundamental_data(
        self, symbols: list[str]
    ) -> dict[str, dict]:
        """Fetch fundamental data (PE, PB, ROE, etc.) via yfinance in thread pool.

        Results are cached per-symbol with a 5-min TTL.

        Args:
            symbols: List of ticker symbols.

        Returns:
            Dict mapping symbol -> fundamental data dict.
        """
        loop = asyncio.get_event_loop()

        # Filter out non-equity symbols (futures, indices, etc.)
        equity_symbols = [s for s in symbols if _is_equity_symbol(s)]
        skipped = len(symbols) - len(equity_symbols)
        if skipped:
            logger.debug(
                "Skipped %d non-equity symbols for fundamental fetch", skipped
            )

        # Split into cached vs uncached
        result: dict[str, dict] = {}
        to_fetch: list[str] = []
        for sym in equity_symbols:
            cached = _get_cached_fundamental(sym)
            if cached is not None:
                result[sym] = cached
            else:
                to_fetch.append(sym)

        if not to_fetch:
            return result

        def _fetch_single(sym: str) -> tuple[str, dict[str, Any] | None]:
            try:
                info = yf.Ticker(sym).info
                data = {
                    "pe_ratio": info.get("trailingPE") or info.get("forwardPE"),
                    "pb_ratio": info.get("priceToBook"),
                    "fcf_yield": None,
                    "roe": info.get("returnOnEquity"),
                    "profit_margins": info.get("profitMargins"),
                    "debt_to_equity": info.get("debtToEquity"),
                }
                # Compute FCF yield if possible
                fcf = info.get("freeCashflow")
                mcap = info.get("marketCap")
                if fcf and mcap and mcap > 0:
                    data["fcf_yield"] = fcf / mcap

                _set_fundamental_cache(sym, data)
                return sym, data
            except Exception as e:
                logger.debug("Failed to fetch fundamentals for %s: %s", sym, e)
                return sym, None

        def _fetch_all() -> list[tuple[str, dict[str, Any] | None]]:
            with ThreadPoolExecutor(max_workers=8) as executor:
                return list(executor.map(_fetch_single, to_fetch))

        fetched = await loop.run_in_executor(None, _fetch_all)

        success = 0
        for sym, data in fetched:
            if data is not None:
                result[sym] = data
                success += 1

        logger.info(
            "Fetched fundamentals: %d/%d symbols succeeded",
            success,
            len(to_fetch),
        )
        return result

    def rank_candidates(
        self, scores: dict[str, FactorScore], top_n: int = 20
    ) -> list[dict]:
        """Return top N candidates sorted by composite score with factor breakdown.

        Symbols whose measured factors cover less than ``MIN_FACTOR_COVERAGE``
        of the total weight are never returned, even if a caller hands in a
        score dict assembled elsewhere: a composite built on too little
        evidence must not compete with one built on the full factor set.

        Args:
            scores: Dict mapping symbol -> FactorScore.
            top_n: Number of top candidates to return.

        Returns:
            List of dicts with symbol, composite_score, coverage, and the
            factor breakdown.
        """
        eligible = [
            s for s in scores.values() if s.coverage >= MIN_FACTOR_COVERAGE
        ]
        dropped = len(scores) - len(eligible)
        if dropped:
            logger.info(
                "rank_candidates dropped %d symbol(s) below %.0f%% factor coverage",
                dropped, MIN_FACTOR_COVERAGE * 100,
            )
        eligible.sort(key=lambda s: s.composite_score, reverse=True)
        return [s.to_dict() for s in eligible[:top_n]]


# ---------------------------------------------------------------------------
# Module singleton
# ---------------------------------------------------------------------------
_factor_model: FactorModel | None = None


def get_factor_model() -> FactorModel:
    """Get or create the singleton FactorModel instance."""
    global _factor_model
    if _factor_model is None:
        _factor_model = FactorModel()
    return _factor_model
