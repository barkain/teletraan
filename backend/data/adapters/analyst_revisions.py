"""Analyst revision momentum adapter.

Combines:
- Finnhub recommendation trend history, when available
- Yahoo Finance target / recommendation fields

The goal is to capture whether analyst sentiment is improving or deteriorating
fast enough to matter for the factor engine.
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import yfinance as yf  # type: ignore[import-untyped]

from data.adapters.evidence import (
    STATUS_OK,
    STATUS_PARTIAL,
    STATUS_UNAVAILABLE,
    utc_now_iso,
)
from data.adapters.finnhub import finnhub_adapter

logger = logging.getLogger(__name__)

_CACHE_TTL = 60 * 60
_MAX_WORKERS = 4
_NON_EQUITY_PATTERNS = ("=F", "^", "-USD", "=X")

#: yfinance ``info`` keys that actually carry analyst opinion. As elsewhere, a
#: non-empty ``info`` dict proves nothing -- yfinance returns
#: ``{'trailingPegRatio': None}`` for symbols it has no coverage for.
_ANALYST_INFO_FIELDS = (
    "recommendationMean",
    "recommendationKey",
    "targetMeanPrice",
    "targetHighPrice",
    "targetLowPrice",
    "numberOfAnalystOpinions",
)

#: Weights for the two scoring components. They are renormalized over whichever
#: components are present, so an all-neutral input lands on 50 rather than the
#: 42.5 the unnormalized 0.55/0.30 pair used to produce.
_TREND_WEIGHT = 0.55
_RECOMMENDATION_WEIGHT = 0.30

#: Evidence buckets counted for coverage: trend history, recommendation, target.
_COVERAGE_BUCKETS = 3


def _is_equity_symbol(symbol: str) -> bool:
    upper = symbol.upper()
    return not any(pat in upper for pat in _NON_EQUITY_PATTERNS)


class _CacheEntry:
    __slots__ = ("data", "expires_at")

    def __init__(self, data: Any, ttl: float) -> None:
        self.data = data
        self.expires_at = time.monotonic() + ttl

    @property
    def is_valid(self) -> bool:
        return time.monotonic() < self.expires_at


@dataclass
class AnalystRevisionSignal:
    symbol: str
    as_of: str
    available: bool
    revision_score: float
    recommendation_key: str | None
    recommendation_mean: float | None
    target_mean_price: float | None
    target_upside_pct: float | None
    latest_trend: dict[str, Any] | None = None
    trend_history: list[dict[str, Any]] = field(default_factory=list)
    # Evidence contract (see data/adapters/evidence.py). `as_of` is kept as the
    # legacy key; `fetched_at`/`status`/`coverage` are additive.
    status: str = STATUS_UNAVAILABLE
    coverage: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "as_of": self.as_of,
            "fetched_at": self.as_of,
            "available": self.available,
            "status": self.status,
            "coverage": self.coverage,
            "revision_score": self.revision_score,
            "recommendation_key": self.recommendation_key,
            "recommendation_mean": self.recommendation_mean,
            "target_mean_price": self.target_mean_price,
            "target_upside_pct": self.target_upside_pct,
            "latest_trend": self.latest_trend,
            "trend_history": self.trend_history,
            "notes": self.notes,
        }


class AnalystRevisionAdapter:
    """Fetch analyst revision momentum for symbols."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS)
        self._cache: dict[str, _CacheEntry] = {}

    def _get_cached(self, key: str) -> Any | None:
        entry = self._cache.get(key)
        if entry is not None and entry.is_valid:
            return entry.data
        self._cache.pop(key, None)
        return None

    def _set_cached(self, key: str, data: Any) -> None:
        self._cache[key] = _CacheEntry(data, _CACHE_TTL)

    async def _run_blocking(self, func: Any, *args: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, func, *args)

    @staticmethod
    def _score_recommendation_mean(rec_mean: float | None) -> float | None:
        """Score a consensus rating, or None when there is no rating to score."""
        if rec_mean is None:
            return None
        # 1=strong buy, 5=strong sell
        return max(0.0, min(100.0, 100.0 - ((rec_mean - 1.0) / 4.0) * 100.0))

    @staticmethod
    def _trend_score(trends: list[dict[str, Any]]) -> tuple[float | None, dict[str, Any] | None]:
        """Score revision momentum, or None when there is no trend history."""
        if not trends:
            return None, None

        latest = trends[0]
        latest_buy = float(latest.get("buy", 0) or 0) + float(latest.get("strongBuy", 0) or 0)
        latest_sell = float(latest.get("sell", 0) or 0) + float(latest.get("strongSell", 0) or 0)
        latest_hold = float(latest.get("hold", 0) or 0)
        latest_total = latest_buy + latest_sell + latest_hold
        latest_ratio = (latest_buy - latest_sell) / latest_total if latest_total else 0.0

        trend_delta = 0.0
        if len(trends) > 1:
            prior = trends[1]
            prior_buy = float(prior.get("buy", 0) or 0) + float(prior.get("strongBuy", 0) or 0)
            prior_sell = float(prior.get("sell", 0) or 0) + float(prior.get("strongSell", 0) or 0)
            prior_hold = float(prior.get("hold", 0) or 0)
            prior_total = prior_buy + prior_sell + prior_hold
            prior_ratio = (prior_buy - prior_sell) / prior_total if prior_total else 0.0
            trend_delta = latest_ratio - prior_ratio

        score = 50.0 + latest_ratio * 25.0 + trend_delta * 25.0
        return max(0.0, min(100.0, score)), latest

    async def get_symbol_revision(self, symbol: str) -> AnalystRevisionSignal:
        symbol = symbol.upper()
        cache_key = symbol
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        if not _is_equity_symbol(symbol):
            signal = self._empty_signal(symbol, note="non_equity_symbol")
            self._set_cached(cache_key, signal)
            return signal

        trends: list[dict[str, Any]] = []
        if finnhub_adapter.is_configured:
            try:
                trends = await finnhub_adapter.get_recommendation_trends(symbol)
            except Exception as exc:
                logger.debug("Analyst revision trends failed for %s: %s", symbol, exc)
                trends = []

        try:
            ticker = await self._run_blocking(yf.Ticker, symbol)
            info = await self._run_blocking(lambda: ticker.info)
        except Exception as exc:
            logger.debug("Analyst revision yfinance fetch failed for %s: %s", symbol, exc)
            info = {}

        present_fields = [key for key in _ANALYST_INFO_FIELDS if info.get(key) is not None]
        if not trends and not present_fields:
            # Nothing to score. The old code still emitted 42.5 here (the
            # unnormalized 0.55+0.30 weights applied to two neutral 50s), which
            # downstream read as a real, mildly bearish revision signal.
            signal = self._empty_signal(symbol, note="no_analyst_coverage")
            self._set_cached(cache_key, signal)
            return signal

        recommendation_mean = info.get("recommendationMean")
        recommendation_key = info.get("recommendationKey")
        target_mean_price = info.get("targetMeanPrice")
        latest_price = info.get("currentPrice") or info.get("regularMarketPrice")

        rec_score = self._score_recommendation_mean(
            float(recommendation_mean) if recommendation_mean is not None else None
        )
        trend_score, latest_trend = self._trend_score(trends)

        upside_pct = None
        if target_mean_price and latest_price:
            try:
                upside_pct = ((float(target_mean_price) / float(latest_price)) - 1.0) * 100.0
            except Exception:
                upside_pct = None

        # Renormalize over the components we actually have, so a missing
        # component leaves the score where the present ones put it instead of
        # dragging it toward zero.
        weighted: list[tuple[float, float]] = []
        if trend_score is not None:
            weighted.append((_TREND_WEIGHT, trend_score))
        if rec_score is not None:
            weighted.append((_RECOMMENDATION_WEIGHT, rec_score))
        if weighted:
            total_weight = sum(weight for weight, _ in weighted)
            score = sum(weight * value for weight, value in weighted) / total_weight
        else:
            # Only price-target evidence: start neutral and let the upside and
            # rating adjustments below move it.
            score = 50.0
        if upside_pct is not None:
            score += max(-10.0, min(10.0, upside_pct / 10.0))
        if recommendation_key:
            key = str(recommendation_key).lower()
            if "buy" in key:
                score += 5.0
            elif "sell" in key:
                score -= 8.0

        notes: list[str] = []
        if recommendation_key:
            notes.append(f"rating={recommendation_key}")
        if recommendation_mean is not None:
            notes.append(f"recommendation_mean={float(recommendation_mean):.2f}")
        if upside_pct is not None:
            notes.append(f"upside_pct={upside_pct:.1f}")
        if trends:
            notes.append(f"trend_months={len(trends)}")

        buckets_present = sum(
            1
            for present in (
                bool(trends),
                recommendation_mean is not None or recommendation_key is not None,
                target_mean_price is not None,
            )
            if present
        )

        signal = AnalystRevisionSignal(
            symbol=symbol,
            as_of=utc_now_iso(),
            available=True,
            revision_score=round(max(0.0, min(100.0, score)), 2),
            recommendation_key=str(recommendation_key) if recommendation_key is not None else None,
            recommendation_mean=float(recommendation_mean) if recommendation_mean is not None else None,
            target_mean_price=float(target_mean_price) if target_mean_price is not None else None,
            target_upside_pct=round(upside_pct, 2) if upside_pct is not None else None,
            latest_trend=latest_trend,
            trend_history=trends,
            status=STATUS_OK if buckets_present == _COVERAGE_BUCKETS else STATUS_PARTIAL,
            coverage=round(buckets_present / _COVERAGE_BUCKETS, 4),
            notes=notes,
        )

        self._set_cached(cache_key, signal)
        return signal

    @staticmethod
    def _empty_signal(symbol: str, *, note: str) -> AnalystRevisionSignal:
        """No analyst evidence: no score at all.

        The score is 0.0 rather than the old 50.0 so that the three signal
        adapters share one convention (options flow and short interest already
        used 0.0); consumers must gate on `available`/`status`, never on the
        number.
        """
        return AnalystRevisionSignal(
            symbol=symbol,
            as_of=utc_now_iso(),
            available=False,
            revision_score=0.0,
            recommendation_key=None,
            recommendation_mean=None,
            target_mean_price=None,
            target_upside_pct=None,
            status=STATUS_UNAVAILABLE,
            coverage=0.0,
            notes=[note],
        )

    async def get_symbol_revisions(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        if not symbols:
            return {}
        results = await asyncio.gather(
            *[self.get_symbol_revision(symbol) for symbol in symbols],
            return_exceptions=True,
        )
        signals: dict[str, dict[str, Any]] = {}
        for result in results:
            if isinstance(result, AnalystRevisionSignal):
                signals[result.symbol] = result.to_dict()
        return signals

    async def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


_adapter_instance: AnalystRevisionAdapter | None = None


def get_analyst_revision_adapter() -> AnalystRevisionAdapter:
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = AnalystRevisionAdapter()
    return _adapter_instance

