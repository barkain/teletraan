"""Symbol-level options flow adapter built on top of yfinance.

The goal is not perfect tape-level flow; it is a deterministic proxy that
captures whether positioning is call-heavy, put-heavy, or balanced across
near-term expiries, with enough detail to be useful in the alpha pipeline.
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
    STATUS_ERROR,
    STATUS_OK,
    STATUS_PARTIAL,
    STATUS_UNAVAILABLE,
    utc_now_iso,
)

logger = logging.getLogger(__name__)

_CACHE_TTL = 30 * 60
_MAX_WORKERS = 6
_NON_EQUITY_PATTERNS = ("=F", "^", "-USD", "=X")


def _is_equity_symbol(symbol: str) -> bool:
    upper = symbol.upper()
    return not any(pat in upper for pat in _NON_EQUITY_PATTERNS)


def _to_float(value: Any) -> float | None:
    """Coerce a chain cell to a float, treating NaN/None/junk as missing.

    yfinance leaves ``volume``/``openInterest`` as NaN for untraded strikes, and
    NaN is truthy -- ``float(row.get("volume") or 0)`` happily yields NaN and
    ``int(NaN)`` then raises.  Now that we walk the whole chain instead of the
    first twelve strikes, those rows are the common case, not the exception.
    """
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return result


def _to_int(value: Any) -> int:
    result = _to_float(value)
    return int(result) if result is not None else 0


def _weighted_average_iv(samples: list[tuple[float, int]]) -> float | None:
    """Open-interest weighted mean implied volatility.

    A flat mean over a full chain is dominated by the wings of the volatility
    smile, which would add a near-constant positive tilt to `signal_score` now
    that we read every strike. Weighting by open interest concentrates the
    average where the contracts actually are, i.e. near the money. Falls back to
    a flat mean when no strike carries open interest.
    """
    if not samples:
        return None
    total_weight = sum(oi for _, oi in samples if oi > 0)
    if total_weight:
        weighted = sum(iv * oi for iv, oi in samples if oi > 0)
        return round(weighted / total_weight, 4)
    return round(sum(iv for iv, _ in samples) / len(samples), 4)


class _CacheEntry:
    __slots__ = ("data", "expires_at")

    def __init__(self, data: Any, ttl: float) -> None:
        self.data = data
        self.expires_at = time.monotonic() + ttl

    @property
    def is_valid(self) -> bool:
        return time.monotonic() < self.expires_at


@dataclass
class OptionsContract:
    symbol: str
    expiration: str
    option_type: str
    strike: float
    volume: int
    open_interest: int
    implied_volatility: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "expiration": self.expiration,
            "option_type": self.option_type,
            "strike": self.strike,
            "volume": self.volume,
            "open_interest": self.open_interest,
            "implied_volatility": self.implied_volatility,
        }


@dataclass
class OptionsFlowSignal:
    symbol: str
    as_of: str
    available: bool
    expirations_scanned: int
    # Evidence contract (see data/adapters/evidence.py). `as_of` is kept as the
    # legacy key; `fetched_at`/`status`/`coverage` are additive.
    status: str
    coverage: float
    contracts_parsed: int
    chains_failed: int
    call_volume: int
    put_volume: int
    call_open_interest: int
    put_open_interest: int
    call_put_volume_ratio: float | None
    call_put_oi_ratio: float | None
    average_iv: float | None
    sentiment: str
    signal_score: float
    notes: list[str] = field(default_factory=list)
    top_contracts: list[OptionsContract] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "as_of": self.as_of,
            "fetched_at": self.as_of,
            "available": self.available,
            "status": self.status,
            "coverage": self.coverage,
            "contracts_parsed": self.contracts_parsed,
            "chains_failed": self.chains_failed,
            "expirations_scanned": self.expirations_scanned,
            "call_volume": self.call_volume,
            "put_volume": self.put_volume,
            "call_open_interest": self.call_open_interest,
            "put_open_interest": self.put_open_interest,
            "call_put_volume_ratio": self.call_put_volume_ratio,
            "call_put_oi_ratio": self.call_put_oi_ratio,
            "average_iv": self.average_iv,
            "sentiment": self.sentiment,
            "signal_score": self.signal_score,
            "notes": self.notes,
            "top_contracts": [contract.to_dict() for contract in self.top_contracts],
        }


class OptionsFlowAdapter:
    """Fetch symbol-level options flow proxies."""

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

    async def get_symbol_flow(self, symbol: str, expirations: int = 2) -> OptionsFlowSignal:
        symbol = symbol.upper()
        cache_key = f"{symbol}:{expirations}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        if not _is_equity_symbol(symbol):
            signal = self._empty_signal(
                symbol,
                status=STATUS_UNAVAILABLE,
                note="non_equity_symbol",
            )
            self._set_cached(cache_key, signal)
            return signal

        ticker = yf.Ticker(symbol)

        expiry_fetch_failed = False
        try:
            expiries = await self._run_blocking(lambda t=ticker: list(getattr(t, "options", []) or []))
        except Exception as exc:
            logger.debug("Options flow: failed to load expirations for %s: %s", symbol, exc)
            expiries = []
            expiry_fetch_failed = True

        if not expiries:
            signal = self._empty_signal(
                symbol,
                status=STATUS_ERROR if expiry_fetch_failed else STATUS_UNAVAILABLE,
                note="expiry_fetch_failed" if expiry_fetch_failed else "no_expirations",
            )
            self._set_cached(cache_key, signal)
            return signal

        expiries = expiries[: max(1, expirations)]
        total_call_volume = 0
        total_put_volume = 0
        total_call_oi = 0
        total_put_oi = 0
        # (implied_vol, open_interest) pairs -- see the OI weighting below.
        iv_samples: list[tuple[float, int]] = []
        contracts: list[OptionsContract] = []
        chains_ok = 0
        chains_failed = 0

        for expiry in expiries:
            try:
                chain = await self._run_blocking(lambda t=ticker, e=expiry: t.option_chain(e))
            except Exception as exc:
                logger.debug("Options flow: failed to load chain for %s %s: %s", symbol, expiry, exc)
                chains_failed += 1
                continue

            rows_this_chain = 0
            for option_type, frame in (("call", getattr(chain, "calls", None)), ("put", getattr(chain, "puts", None))):
                if frame is None or getattr(frame, "empty", True):
                    continue
                # Total over the COMPLETE chain for each selected expiry. The
                # previous `frame.head(12)` took the twelve lowest strikes --
                # deep-ITM calls and deep-OTM puts -- which is not a sample of
                # the chain at all: for AAPL it reported a call/put volume ratio
                # of 1.02 against a true 2.52, inverting the signal. Expiry
                # count (`expirations`) stays the liquidity window; within an
                # expiry every listed strike counts.
                for _, row in frame.iterrows():
                    volume = _to_int(row.get("volume"))
                    open_interest = _to_int(row.get("openInterest"))
                    implied_vol = _to_float(row.get("impliedVolatility"))
                    if implied_vol is not None:
                        iv_samples.append((implied_vol, open_interest))
                    strike = _to_float(row.get("strike")) or 0.0
                    contract_symbol = str(row.get("contractSymbol") or "")
                    contracts.append(
                        OptionsContract(
                            symbol=contract_symbol,
                            expiration=expiry,
                            option_type=option_type,
                            strike=strike,
                            volume=volume,
                            open_interest=open_interest,
                            implied_volatility=implied_vol,
                        )
                    )
                    rows_this_chain += 1
                    if option_type == "call":
                        total_call_volume += volume
                        total_call_oi += open_interest
                    else:
                        total_put_volume += volume
                        total_put_oi += open_interest

            if rows_this_chain:
                chains_ok += 1
            else:
                chains_failed += 1

        total_volume = total_call_volume + total_put_volume
        total_oi = total_call_oi + total_put_oi

        # A chain we could not read is not a balanced chain. Emitting the
        # neutral 50 below for zero parsed rows is what let a total fetch
        # failure look like "no directional edge".
        if not contracts or (total_volume == 0 and total_oi == 0):
            signal = self._empty_signal(
                symbol,
                status=STATUS_ERROR if chains_failed and not chains_ok else STATUS_UNAVAILABLE,
                note="all_chains_failed" if chains_failed and not chains_ok else "empty_chains",
                expirations_scanned=len(expiries),
                chains_failed=chains_failed,
            )
            self._set_cached(cache_key, signal)
            return signal

        vol_ratio = round(total_call_volume / total_put_volume, 2) if total_put_volume else (float("inf") if total_call_volume else None)
        oi_ratio = round(total_call_oi / total_put_oi, 2) if total_put_oi else (float("inf") if total_call_oi else None)
        average_iv = _weighted_average_iv(iv_samples)

        imbalance = 0.0
        if total_volume:
            imbalance = (total_call_volume - total_put_volume) / total_volume
        oi_imbalance = 0.0
        if total_oi:
            oi_imbalance = (total_call_oi - total_put_oi) / total_oi

        notes: list[str] = []
        if vol_ratio is not None:
            notes.append(f"volume_ratio={vol_ratio}")
        if oi_ratio is not None:
            notes.append(f"oi_ratio={oi_ratio}")
        if average_iv is not None:
            notes.append(f"avg_iv={average_iv:.4f}")
        notes.append(f"contracts_parsed={len(contracts)}")
        if chains_failed:
            notes.append(f"chains_failed={chains_failed}")

        raw_score = 50.0 + imbalance * 35.0 + oi_imbalance * 20.0
        if average_iv is not None:
            raw_score += min(10.0, max(-10.0, (average_iv - 0.3) * 20.0))
        signal_score = max(0.0, min(100.0, raw_score))

        if signal_score >= 60:
            sentiment = "bullish"
        elif signal_score <= 40:
            sentiment = "bearish"
        else:
            sentiment = "neutral"

        signal = OptionsFlowSignal(
            symbol=symbol,
            as_of=utc_now_iso(),
            available=True,
            status=STATUS_OK if not chains_failed else STATUS_PARTIAL,
            coverage=round(chains_ok / len(expiries), 4),
            contracts_parsed=len(contracts),
            chains_failed=chains_failed,
            expirations_scanned=chains_ok,
            call_volume=total_call_volume,
            put_volume=total_put_volume,
            call_open_interest=total_call_oi,
            put_open_interest=total_put_oi,
            call_put_volume_ratio=vol_ratio if vol_ratio != float("inf") else None,
            call_put_oi_ratio=oi_ratio if oi_ratio != float("inf") else None,
            average_iv=average_iv,
            sentiment=sentiment,
            signal_score=round(signal_score, 2),
            notes=notes,
            top_contracts=sorted(contracts, key=lambda item: (item.volume, item.open_interest), reverse=True)[:12],
        )

        self._set_cached(cache_key, signal)
        return signal

    @staticmethod
    def _empty_signal(
        symbol: str,
        *,
        status: str,
        note: str,
        expirations_scanned: int = 0,
        chains_failed: int = 0,
    ) -> OptionsFlowSignal:
        """No usable chain: no score, so downstream gating cannot mistake this
        for a balanced market."""
        return OptionsFlowSignal(
            symbol=symbol,
            as_of=utc_now_iso(),
            available=False,
            status=status,
            coverage=0.0,
            contracts_parsed=0,
            chains_failed=chains_failed,
            expirations_scanned=expirations_scanned,
            call_volume=0,
            put_volume=0,
            call_open_interest=0,
            put_open_interest=0,
            call_put_volume_ratio=None,
            call_put_oi_ratio=None,
            average_iv=None,
            sentiment="unknown",
            signal_score=0.0,
            notes=[note],
        )

    async def get_symbol_flows(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        if not symbols:
            return {}
        results = await asyncio.gather(
            *[self.get_symbol_flow(symbol) for symbol in symbols],
            return_exceptions=True,
        )
        flows: dict[str, dict[str, Any]] = {}
        for result in results:
            if isinstance(result, OptionsFlowSignal):
                flows[result.symbol] = result.to_dict()
        return flows

    async def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


_adapter_instance: OptionsFlowAdapter | None = None


def get_options_flow_adapter() -> OptionsFlowAdapter:
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = OptionsFlowAdapter()
    return _adapter_instance
