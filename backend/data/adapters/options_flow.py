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

logger = logging.getLogger(__name__)

_CACHE_TTL = 30 * 60
_MAX_WORKERS = 6
_NON_EQUITY_PATTERNS = ("=F", "^", "-USD", "=X")


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
            "available": self.available,
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
            signal = OptionsFlowSignal(
                symbol=symbol,
                as_of=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                available=False,
                expirations_scanned=0,
                call_volume=0,
                put_volume=0,
                call_open_interest=0,
                put_open_interest=0,
                call_put_volume_ratio=None,
                call_put_oi_ratio=None,
                average_iv=None,
                sentiment="neutral",
                signal_score=0.0,
                notes=["non_equity_symbol"],
            )
            self._set_cached(cache_key, signal)
            return signal

        ticker = yf.Ticker(symbol)

        try:
            expiries = await self._run_blocking(lambda t=ticker: list(getattr(t, "options", []) or []))
        except Exception as exc:
            logger.debug("Options flow: failed to load expirations for %s: %s", symbol, exc)
            expiries = []

        expiries = expiries[: max(1, expirations)]
        total_call_volume = 0
        total_put_volume = 0
        total_call_oi = 0
        total_put_oi = 0
        iv_values: list[float] = []
        contracts: list[OptionsContract] = []

        for expiry in expiries:
            try:
                chain = await self._run_blocking(lambda t=ticker, e=expiry: t.option_chain(e))
            except Exception as exc:
                logger.debug("Options flow: failed to load chain for %s %s: %s", symbol, expiry, exc)
                continue

            for option_type, frame in (("call", getattr(chain, "calls", None)), ("put", getattr(chain, "puts", None))):
                if frame is None or getattr(frame, "empty", True):
                    continue
                for _, row in frame.head(12).iterrows():
                    volume = int(float(row.get("volume") or 0))
                    open_interest = int(float(row.get("openInterest") or 0))
                    implied_vol = row.get("impliedVolatility")
                    if implied_vol is not None:
                        try:
                            iv_values.append(float(implied_vol))
                        except Exception:
                            pass
                    strike = float(row.get("strike") or 0.0)
                    contract_symbol = str(row.get("contractSymbol") or "")
                    contracts.append(
                        OptionsContract(
                            symbol=contract_symbol,
                            expiration=expiry,
                            option_type=option_type,
                            strike=strike,
                            volume=volume,
                            open_interest=open_interest,
                            implied_volatility=float(implied_vol) if implied_vol is not None else None,
                        )
                    )
                    if option_type == "call":
                        total_call_volume += volume
                        total_call_oi += open_interest
                    else:
                        total_put_volume += volume
                        total_put_oi += open_interest

        total_volume = total_call_volume + total_put_volume
        total_oi = total_call_oi + total_put_oi
        vol_ratio = round(total_call_volume / total_put_volume, 2) if total_put_volume else (float("inf") if total_call_volume else None)
        oi_ratio = round(total_call_oi / total_put_oi, 2) if total_put_oi else (float("inf") if total_call_oi else None)
        average_iv = round(sum(iv_values) / len(iv_values), 4) if iv_values else None

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
            as_of=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            available=bool(expiries),
            expirations_scanned=len(expiries),
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
