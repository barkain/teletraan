"""Earnings calendar and catalyst data adapter via yfinance.

Fetches upcoming earnings dates, consensus estimates, historical quarterly
earnings (beat/miss), and ex-dividend dates. All blocking yfinance calls
are wrapped with run_in_executor() for async compatibility.

Uses a module-level TTL cache (1 hour) following the same pattern as
heatmap_fetcher.py.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import yfinance as yf  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level cache (1-hour TTL)
# ---------------------------------------------------------------------------
_earnings_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 3600  # 1 hour


def _get_cached(key: str) -> Any | None:
    """Get cached data if within TTL."""
    if key in _earnings_cache:
        ts, data = _earnings_cache[key]
        if time.time() - ts < _CACHE_TTL:
            return data
        del _earnings_cache[key]
    return None


def _set_cache(key: str, data: Any) -> None:
    """Cache data with current timestamp."""
    _earnings_cache[key] = (time.time(), data)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class EarningsInfo:
    """Upcoming earnings information for a single symbol."""

    symbol: str
    next_earnings_date: datetime | None = None
    days_until_earnings: int | None = None
    eps_estimate: float | None = None
    revenue_estimate: float | None = None


@dataclass
class EarningsQuarter:
    """Historical quarterly earnings data."""

    date: datetime
    eps_actual: float | None = None
    eps_estimate: float | None = None
    surprise_pct: float | None = None  # (actual - estimate) / |estimate| * 100
    revenue_actual: float | None = None
    revenue_estimate: float | None = None


@dataclass
class CatalystEvent:
    """An upcoming catalyst event (earnings, ex-dividend, etc.)."""

    symbol: str
    event_type: str  # "earnings", "ex_dividend"
    date: datetime
    days_until: int
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers (module-level so type checker can see them clearly)
# ---------------------------------------------------------------------------


def _safe_float(value: Any) -> float | None:
    """Safely convert to float, returning None on failure."""
    if value is None:
        return None
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def _to_datetime(value: Any) -> datetime | None:
    """Convert various date representations to datetime.

    Handles: datetime, date, pandas Timestamp, int/float epoch, str formats.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    # pandas Timestamp / similar objects with to_pydatetime()
    if hasattr(value, "to_pydatetime"):
        try:
            dt = value.to_pydatetime()
            if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt
        except Exception as e:
            logger.debug(f"to_pydatetime conversion failed: {e}")
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value)
        except (OSError, ValueError) as e:
            logger.debug(f"Timestamp conversion failed for {value}: {e}")
            return None
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class EarningsAdapter:
    """Fetches earnings calendar, estimates, and history via yfinance."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=8)

    async def _run_blocking(self, func: Any) -> Any:
        """Run a blocking callable in the thread pool executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, func)

    async def get_earnings_calendar(
        self, symbols: list[str]
    ) -> dict[str, EarningsInfo]:
        """Fetch upcoming earnings dates and consensus estimates for symbols.

        Args:
            symbols: List of ticker symbols.

        Returns:
            Dict mapping symbol -> EarningsInfo.
        """
        cache_key = "cal:" + ",".join(sorted(s.upper() for s in symbols))
        cached = _get_cached(cache_key)
        if cached is not None:
            return cached

        async def _fetch_one(symbol: str) -> tuple[str, EarningsInfo]:
            sym = symbol.upper()
            try:
                info = await self._run_blocking(
                    lambda: self._fetch_earnings_info(sym)
                )
                return sym, info
            except Exception as e:
                logger.debug(f"Failed to fetch earnings info for {sym}: {e}")
                return sym, EarningsInfo(symbol=sym)

        results = await asyncio.gather(
            *[_fetch_one(s) for s in symbols],
            return_exceptions=True,
        )

        calendar: dict[str, EarningsInfo] = {}
        for r in results:
            if isinstance(r, BaseException):
                logger.warning(f"Earnings fetch failed: {r}")
                continue
            sym, info = r
            calendar[sym] = info

        _set_cache(cache_key, calendar)
        return calendar

    def _fetch_earnings_info(self, symbol: str) -> EarningsInfo:
        """Blocking: fetch earnings info for a single symbol."""
        ticker = yf.Ticker(symbol)
        now = datetime.now()

        next_date: datetime | None = None
        eps_est: float | None = None
        rev_est: float | None = None

        # Try ticker.calendar for upcoming earnings
        try:
            cal = ticker.calendar
            if cal is not None:
                if isinstance(cal, dict):
                    earnings_dates = cal.get("Earnings Date")
                    if earnings_dates:
                        if (
                            isinstance(earnings_dates, list)
                            and len(earnings_dates) > 0
                        ):
                            next_date = _to_datetime(earnings_dates[0])
                        else:
                            next_date = _to_datetime(earnings_dates)
                    eps_est = _safe_float(cal.get("Earnings Average"))
                    rev_est = _safe_float(cal.get("Revenue Average"))
                else:
                    next_date, eps_est, rev_est = self._parse_calendar_dataframe(
                        cal
                    )
        except Exception as e:
            logger.debug(f"calendar fetch failed for {symbol}: {e}")

        # Fallback: try earnings_dates for the next upcoming date
        if next_date is None:
            try:
                ed = ticker.earnings_dates
                if ed is not None and not ed.empty:
                    future_dates = [
                        idx
                        for idx in ed.index
                        if _to_datetime(idx)
                        and _to_datetime(idx) >= now  # type: ignore[operator]
                    ]
                    if future_dates:
                        next_date = _to_datetime(future_dates[0])
                    elif len(ed.index) > 0:
                        next_date = _to_datetime(ed.index[0])
            except Exception as e:
                logger.debug(f"earnings_dates fetch failed for {symbol}: {e}")

        days_until: int | None = None
        if next_date is not None:
            delta = next_date - now
            days_until = delta.days

        return EarningsInfo(
            symbol=symbol,
            next_earnings_date=next_date,
            days_until_earnings=days_until,
            eps_estimate=eps_est,
            revenue_estimate=rev_est,
        )

    @staticmethod
    def _parse_calendar_dataframe(
        cal: Any,
    ) -> tuple[datetime | None, float | None, float | None]:
        """Extract earnings date and estimates from a DataFrame-like calendar.

        Returns:
            Tuple of (next_date, eps_estimate, revenue_estimate).
        """
        next_date: datetime | None = None
        eps_est: float | None = None
        rev_est: float | None = None

        try:
            if hasattr(cal, "columns"):
                if "Earnings Date" in cal.columns:
                    vals = cal["Earnings Date"].dropna()
                    if len(vals) > 0:
                        next_date = _to_datetime(vals.iloc[0])
                if "Earnings Average" in cal.columns:
                    eps_est = _safe_float(cal["Earnings Average"].iloc[0])
                if "Revenue Average" in cal.columns:
                    rev_est = _safe_float(cal["Revenue Average"].iloc[0])
            elif hasattr(cal, "index"):
                if "Earnings Date" in cal.index:
                    val = cal.loc["Earnings Date"]
                    if hasattr(val, "iloc"):
                        next_date = _to_datetime(val.iloc[0])
                    else:
                        next_date = _to_datetime(val)
                if "Earnings Average" in cal.index:
                    ea_val = cal.loc["Earnings Average"]
                    eps_est = _safe_float(
                        ea_val.iloc[0] if hasattr(ea_val, "iloc") else ea_val
                    )
                if "Revenue Average" in cal.index:
                    ra_val = cal.loc["Revenue Average"]
                    rev_est = _safe_float(
                        ra_val.iloc[0] if hasattr(ra_val, "iloc") else ra_val
                    )
        except Exception as e:
            logger.debug(f"DataFrame calendar parsing failed: {e}")

        return next_date, eps_est, rev_est

    async def get_earnings_history(
        self, symbol: str, quarters: int = 8
    ) -> list[EarningsQuarter]:
        """Fetch historical quarterly earnings with beat/miss data.

        Args:
            symbol: Ticker symbol.
            quarters: Number of past quarters to fetch.

        Returns:
            List of EarningsQuarter, most recent first.
        """
        cache_key = f"hist:{symbol.upper()}:{quarters}"
        cached = _get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            history = await self._run_blocking(
                lambda: self._fetch_earnings_history(symbol.upper(), quarters)
            )
        except Exception as e:
            logger.warning(
                f"Failed to fetch earnings history for {symbol}: {e}"
            )
            history = []

        _set_cache(cache_key, history)
        return history

    def _fetch_earnings_history(
        self, symbol: str, quarters: int
    ) -> list[EarningsQuarter]:
        """Blocking: fetch historical earnings for a symbol."""
        ticker = yf.Ticker(symbol)
        result: list[EarningsQuarter] = []

        # Try earnings_dates which has actual vs estimate EPS
        try:
            ed = ticker.earnings_dates
            if ed is not None and not ed.empty:
                for idx, row in list(ed.iterrows())[:quarters]:
                    dt = _to_datetime(idx)
                    if dt is None:
                        continue

                    eps_actual = _safe_float(row.get("Reported EPS"))
                    eps_estimate = _safe_float(row.get("EPS Estimate"))
                    surprise_pct: float | None = None

                    if row.get("Surprise(%)") is not None:
                        surprise_pct = _safe_float(row.get("Surprise(%)"))
                    elif (
                        eps_actual is not None
                        and eps_estimate is not None
                        and eps_estimate != 0
                    ):
                        surprise_pct = (
                            (eps_actual - eps_estimate) / abs(eps_estimate)
                        ) * 100

                    result.append(
                        EarningsQuarter(
                            date=dt,
                            eps_actual=eps_actual,
                            eps_estimate=eps_estimate,
                            surprise_pct=surprise_pct,
                        )
                    )

                if result:
                    return result
        except Exception as e:
            logger.debug(f"earnings_dates history failed for {symbol}: {e}")

        # Fallback: quarterly_earnings
        try:
            qe = ticker.quarterly_earnings
            if qe is not None and not qe.empty:
                for idx, row in list(qe.iterrows())[:quarters]:
                    dt = _to_datetime(idx)
                    if dt is None:
                        dt = datetime.now()

                    eps_actual = _safe_float(row.get("Actual"))
                    eps_estimate = _safe_float(row.get("Estimate"))
                    surprise_pct = None
                    if (
                        eps_actual is not None
                        and eps_estimate is not None
                        and eps_estimate != 0
                    ):
                        surprise_pct = (
                            (eps_actual - eps_estimate) / abs(eps_estimate)
                        ) * 100

                    rev_actual = _safe_float(row.get("Revenue"))

                    result.append(
                        EarningsQuarter(
                            date=dt,
                            eps_actual=eps_actual,
                            eps_estimate=eps_estimate,
                            surprise_pct=surprise_pct,
                            revenue_actual=rev_actual,
                        )
                    )
        except Exception as e:
            logger.debug(f"quarterly_earnings failed for {symbol}: {e}")

        return result

    async def get_upcoming_catalysts(
        self, symbols: list[str], days_ahead: int = 30
    ) -> list[CatalystEvent]:
        """Get all upcoming catalysts (earnings, ex-div dates) within N days.

        Args:
            symbols: List of ticker symbols.
            days_ahead: How many days ahead to look.

        Returns:
            List of CatalystEvent sorted by date.
        """
        cache_key = (
            f"cat:{','.join(sorted(s.upper() for s in symbols))}:{days_ahead}"
        )
        cached = _get_cached(cache_key)
        if cached is not None:
            return cached

        now = datetime.now()
        cutoff = now + timedelta(days=days_ahead)
        events: list[CatalystEvent] = []

        # Fetch earnings calendar
        calendar = await self.get_earnings_calendar(symbols)

        for sym, info in calendar.items():
            if (
                info.next_earnings_date
                and now <= info.next_earnings_date <= cutoff
            ):
                history = await self.get_earnings_history(sym, quarters=4)
                beats = sum(
                    1
                    for q in history
                    if q.surprise_pct is not None and q.surprise_pct > 0
                )
                total_with_data = sum(
                    1 for q in history if q.surprise_pct is not None
                )
                beat_rate = (
                    beats / total_with_data if total_with_data > 0 else None
                )
                avg_surprise = None
                if total_with_data > 0:
                    surprises = [
                        q.surprise_pct
                        for q in history
                        if q.surprise_pct is not None
                    ]
                    avg_surprise = (
                        sum(surprises) / len(surprises) if surprises else None
                    )

                events.append(
                    CatalystEvent(
                        symbol=sym,
                        event_type="earnings",
                        date=info.next_earnings_date,
                        days_until=info.days_until_earnings or 0,
                        details={
                            "eps_estimate": info.eps_estimate,
                            "revenue_estimate": info.revenue_estimate,
                            "beat_rate_last_4q": beat_rate,
                            "avg_surprise_pct": avg_surprise,
                        },
                    )
                )

        # Fetch ex-dividend dates
        for sym in symbols:
            try:
                div_event = await self._run_blocking(
                    lambda s=sym: self._fetch_ex_div(s.upper(), now, cutoff)  # type: ignore[misc]
                )
                if div_event is not None:
                    events.append(div_event)
            except Exception as e:
                logger.debug(f"Ex-div fetch failed for {sym}: {e}")

        events.sort(key=lambda e: e.date)

        _set_cache(cache_key, events)
        return events

    def _fetch_ex_div(
        self, symbol: str, now: datetime, cutoff: datetime
    ) -> CatalystEvent | None:
        """Blocking: fetch next ex-dividend date if within range."""
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            ex_div = info.get("exDividendDate")
            if ex_div is not None:
                ex_dt = _to_datetime(ex_div)
                if ex_dt and now <= ex_dt <= cutoff:
                    div_yield = info.get("dividendYield")
                    return CatalystEvent(
                        symbol=symbol,
                        event_type="ex_dividend",
                        date=ex_dt,
                        days_until=(ex_dt - now).days,
                        details={
                            "dividend_yield": div_yield,
                        },
                    )
        except Exception as e:
            logger.debug(f"Ex-div fetch failed for {symbol}: {e}")
        return None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_adapter: EarningsAdapter | None = None


def get_earnings_adapter() -> EarningsAdapter:
    """Get or create the singleton EarningsAdapter instance."""
    global _adapter
    if _adapter is None:
        _adapter = EarningsAdapter()
    return _adapter
