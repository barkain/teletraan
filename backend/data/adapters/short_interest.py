"""Short-interest adapter built from public yfinance fundamentals fields.

This is a deterministic proxy for crowding / squeeze risk:
- short ratio
- short percent of float
- shares short

It is not a borrow desk feed, but it is good enough to flag names where
short positioning might materially matter.
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

logger = logging.getLogger(__name__)

_CACHE_TTL = 60 * 60
_MAX_WORKERS = 4
_NON_EQUITY_PATTERNS = ("=F", "^", "-USD", "=X")

#: The fields that actually carry short-interest information. yfinance happily
#: returns ``{'trailingPegRatio': None}`` for symbols it knows nothing about, so
#: "the dict is non-empty" says nothing about whether we have data.
_SHORT_INTEREST_FIELDS = ("sharesShort", "shortRatio", "shortPercentOfFloat", "floatShares")


def _is_equity_symbol(symbol: str) -> bool:
    upper = symbol.upper()
    return not any(pat in upper for pat in _NON_EQUITY_PATTERNS)


def _normalize_short_percent(raw: float | None) -> float | None:
    """Return short interest as a percentage of float, in percentage points.

    yfinance reports ``shortPercentOfFloat`` as a *fraction* (AAPL = 0.01 for
    1%), but the scoring below has always treated it as percentage points and
    subtracted a 5-point threshold, so real values silently scored zero. Values
    at or below 1.0 are read as fractions and scaled once; anything above is
    already in percentage points and is left alone. The ambiguity at exactly 1.0
    resolves to 1% -- a 100%-of-float short position does not occur in practice.
    """
    if raw is None:
        return None
    return raw * 100.0 if raw <= 1.0 else raw


class _CacheEntry:
    __slots__ = ("data", "expires_at")

    def __init__(self, data: Any, ttl: float) -> None:
        self.data = data
        self.expires_at = time.monotonic() + ttl

    @property
    def is_valid(self) -> bool:
        return time.monotonic() < self.expires_at


@dataclass
class ShortInterestSignal:
    symbol: str
    as_of: str
    available: bool
    shares_short: int | None
    short_ratio: float | None
    #: Percentage points of float sold short (1.0 == 1%), normalized from
    #: yfinance's fractional ``shortPercentOfFloat``.
    short_percent_float: float | None
    float_shares: int | None
    squeeze_score: float
    sentiment: str
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
            "shares_short": self.shares_short,
            "short_ratio": self.short_ratio,
            "short_percent_float": self.short_percent_float,
            "float_shares": self.float_shares,
            "squeeze_score": self.squeeze_score,
            "sentiment": self.sentiment,
            "notes": self.notes,
        }


class ShortInterestAdapter:
    """Fetch a public short-interest proxy from yfinance."""

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

    async def _run_blocking(self, func: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, func)

    async def get_symbol_short_interest(self, symbol: str) -> ShortInterestSignal:
        symbol = symbol.upper()
        cache_key = symbol
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        if not _is_equity_symbol(symbol):
            signal = self._empty_signal(symbol, note="non_equity_symbol")
            self._set_cached(cache_key, signal)
            return signal

        ticker = yf.Ticker(symbol)
        try:
            info = await self._run_blocking(lambda t=ticker: dict(getattr(t, "info", {}) or {}))
        except Exception as exc:
            logger.debug("Short interest fetch failed for %s: %s", symbol, exc)
            info = {}

        present_fields = [key for key in _SHORT_INTEREST_FIELDS if info.get(key) is not None]
        if not present_fields:
            # A response with no short-interest field is not "zero short
            # interest" -- it is no data. Scoring it produced squeeze_score=0.0
            # with sentiment 'low_short_interest' on symbols we know nothing
            # about.
            signal = self._empty_signal(symbol, note="no_short_interest_fields")
            self._set_cached(cache_key, signal)
            return signal

        shares_short = info.get("sharesShort")
        short_ratio = info.get("shortRatio")
        short_percent_float = info.get("shortPercentOfFloat")
        float_shares = info.get("floatShares")

        shares_short_i = int(shares_short) if shares_short is not None else None
        float_shares_i = int(float_shares) if float_shares is not None else None
        short_ratio_f = float(short_ratio) if short_ratio is not None else None
        short_percent_f = _normalize_short_percent(
            float(short_percent_float) if short_percent_float is not None else None
        )

        notes: list[str] = []
        if short_ratio_f is not None:
            notes.append(f"short_ratio={short_ratio_f:.2f}")
        if short_percent_f is not None:
            notes.append(f"short_percent_float={short_percent_f:.2f}")

        score = 0.0
        if short_ratio_f is not None:
            score += min(35.0, max(0.0, short_ratio_f - 1.0) * 6.0)
        if short_percent_f is not None:
            score += min(40.0, max(0.0, short_percent_f - 5.0) * 1.5)
        if shares_short_i is not None and float_shares_i:
            short_interest_pct = (shares_short_i / float_shares_i) * 100.0 if float_shares_i else 0.0
            score += min(20.0, max(0.0, short_interest_pct - 5.0) * 1.0)

        if score >= 55:
            sentiment = "squeeze_setup"
        elif score <= 25:
            sentiment = "low_short_interest"
        else:
            sentiment = "neutral"

        signal = ShortInterestSignal(
            symbol=symbol,
            as_of=utc_now_iso(),
            available=True,
            shares_short=shares_short_i,
            short_ratio=short_ratio_f,
            short_percent_float=short_percent_f,
            float_shares=float_shares_i,
            squeeze_score=round(max(0.0, min(100.0, score)), 2),
            sentiment=sentiment,
            status=STATUS_OK if len(present_fields) == len(_SHORT_INTEREST_FIELDS) else STATUS_PARTIAL,
            coverage=round(len(present_fields) / len(_SHORT_INTEREST_FIELDS), 4),
            notes=notes,
        )

        self._set_cached(cache_key, signal)
        return signal

    @staticmethod
    def _empty_signal(symbol: str, *, note: str) -> ShortInterestSignal:
        """No short-interest field came back: no score, and a sentiment that
        cannot be mistaken for a measured 'low short interest'."""
        return ShortInterestSignal(
            symbol=symbol,
            as_of=utc_now_iso(),
            available=False,
            shares_short=None,
            short_ratio=None,
            short_percent_float=None,
            float_shares=None,
            squeeze_score=0.0,
            sentiment="unknown",
            status=STATUS_UNAVAILABLE,
            coverage=0.0,
            notes=[note],
        )

    async def get_symbol_short_interests(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        if not symbols:
            return {}
        results = await asyncio.gather(
            *[self.get_symbol_short_interest(symbol) for symbol in symbols],
            return_exceptions=True,
        )
        signals: dict[str, dict[str, Any]] = {}
        for result in results:
            if isinstance(result, ShortInterestSignal):
                signals[result.symbol] = result.to_dict()
        return signals

    async def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


_adapter_instance: ShortInterestAdapter | None = None


def get_short_interest_adapter() -> ShortInterestAdapter:
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = ShortInterestAdapter()
    return _adapter_instance

