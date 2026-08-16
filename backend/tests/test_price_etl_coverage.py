"""Regression tests for the price ETL and its coverage reporting.

The ``price_history`` table stopped being fed for three and a half months
without a single log line, endpoint or test noticing.  Three independent
defects combined:

1. The nightly ``daily_price_refresh`` job is registered with no arguments, so
   ``symbols`` arrived as ``None`` and fell through to the sixteen hard-coded
   ``DEFAULT_SYMBOLS``.  The universe-expansion scripts had grown ``stocks`` to
   ~400 rows; the other ~380 were seeded once and never refreshed again.
2. The fetch window was a fixed ``period="5d"``, which is narrower than any
   outage longer than a long weekend.  A run after a two-week gap wrote the
   last five days and left the rest permanently unwritten -- interior holes,
   not trailing staleness.
3. A symbol that raised was recorded as ``results[symbol] = 0``, identical to
   "no new bars", and nothing aggregated the result.  A run in which every
   symbol failed logged exactly like a healthy one.

Each test below pins one of those, plus the catch-up backfill and the coverage
report that make a future recurrence visible.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from analysis.price_coverage import (
    benchmark_gap_report,
    format_coverage_report,
    price_coverage_report,
)
from models.price import PriceHistory
from models.stock import Stock
from scheduler.etl import ETLOrchestrator

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeYahooAdapter:
    """Records every fetch and returns synthetic bars for the window asked for.

    The point of most of these tests is *what window the ETL asks for*, so the
    call arguments are recorded rather than just the returned data.
    """

    def __init__(self, failing: set[str] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.failing = failing or set()

    async def get_stock_info(self, symbol: str) -> dict[str, Any]:
        return {"symbol": symbol.upper(), "name": symbol.upper()}

    async def get_price_history(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
        period: str = "1y",
    ) -> list[dict[str, Any]]:
        self.calls.append({
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "period": period,
        })
        if symbol.upper() in self.failing:
            raise RuntimeError(f"simulated yfinance failure for {symbol}")
        if start_date is None:
            return []
        end = end_date or date.today()
        bars: list[dict[str, Any]] = []
        cursor = start_date
        while cursor < end:
            if cursor.weekday() < 5:
                bars.append({
                    "date": cursor,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 1_000,
                    "adjusted_close": 100.5,
                })
            cursor += timedelta(days=1)
        return bars

    @property
    def fetched_symbols(self) -> set[str]:
        return {call["symbol"].upper() for call in self.calls}

    def call_for(self, symbol: str) -> dict[str, Any]:
        matches = [c for c in self.calls if c["symbol"].upper() == symbol.upper()]
        assert matches, f"{symbol} was never fetched"
        return matches[0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _add_stock(
    session: AsyncSession,
    symbol: str,
    *,
    is_active: bool = True,
) -> Stock:
    stock = Stock(symbol=symbol, name=symbol, is_active=is_active)
    session.add(stock)
    await session.commit()
    await session.refresh(stock)
    return stock


async def _add_bars(
    session: AsyncSession,
    stock: Stock,
    days: list[date],
    close: float = 100.0,
) -> None:
    for day in days:
        session.add(
            PriceHistory(
                stock_id=stock.id,
                date=day,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=1_000,
                adjusted_close=close,
            )
        )
    await session.commit()


def _weekdays_back(anchor: date, count: int) -> list[date]:
    """The *count* most recent weekdays at or before *anchor*, oldest first."""
    days: list[date] = []
    cursor = anchor
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return sorted(days)


@pytest.fixture()
def etl(monkeypatch: pytest.MonkeyPatch) -> ETLOrchestrator:
    """An orchestrator wired to the in-memory test database."""
    from tests.conftest import TestSessionFactory, test_engine

    monkeypatch.setattr("scheduler.etl.async_session_factory", TestSessionFactory)
    monkeypatch.setattr("scheduler.etl.engine", test_engine)
    return ETLOrchestrator()


@pytest.fixture()
def fake_yahoo(monkeypatch: pytest.MonkeyPatch) -> FakeYahooAdapter:
    adapter = FakeYahooAdapter()
    monkeypatch.setattr("scheduler.etl.yahoo_adapter", adapter)
    return adapter


# ---------------------------------------------------------------------------
# Defect 1 -- the nightly job only ever refreshed DEFAULT_SYMBOLS
# ---------------------------------------------------------------------------


async def test_default_refresh_covers_every_active_stock_not_just_defaults(
    db_session: AsyncSession,
    etl: ETLOrchestrator,
    fake_yahoo: FakeYahooAdapter,
) -> None:
    """A no-argument refresh must fetch the whole active universe.

    This is the defect that froze ~380 symbols: the scheduler calls
    ``fetch_and_store_prices`` with no arguments, and the old body resolved
    that to sixteen hard-coded benchmark tickers.
    """
    await _add_stock(db_session, "SPY")
    for symbol in ("ZZZA", "ZZZB", "ZZZC"):
        await _add_stock(db_session, symbol)

    await etl.fetch_and_store_prices()

    assert {"ZZZA", "ZZZB", "ZZZC"} <= fake_yahoo.fetched_symbols, (
        "symbols outside DEFAULT_SYMBOLS were never refreshed"
    )


async def test_default_refresh_still_covers_benchmarks_on_an_empty_universe(
    db_session: AsyncSession,
    etl: ETLOrchestrator,
    fake_yahoo: FakeYahooAdapter,
) -> None:
    """With no stocks in the DB the benchmark set must still be fetched."""
    await etl.fetch_and_store_prices()

    assert "SPY" in fake_yahoo.fetched_symbols


async def test_default_refresh_skips_inactive_stocks(
    db_session: AsyncSession,
    etl: ETLOrchestrator,
    fake_yahoo: FakeYahooAdapter,
) -> None:
    await _add_stock(db_session, "ZZZDEAD", is_active=False)

    await etl.fetch_and_store_prices()

    assert "ZZZDEAD" not in fake_yahoo.fetched_symbols


# ---------------------------------------------------------------------------
# Defect 2 -- a fixed 5-day window can never close a longer gap
# ---------------------------------------------------------------------------


async def test_refresh_window_spans_the_entire_gap(
    db_session: AsyncSession,
    etl: ETLOrchestrator,
    fake_yahoo: FakeYahooAdapter,
) -> None:
    """A symbol 90 days behind must be fetched from 90 days back, not 5.

    ``period="5d"`` is why SPY has no July 2026 bars but does have August
    ones: each run could only ever see the last five days.
    """
    stock = await _add_stock(db_session, "ZZZGAP")
    last_bar = date.today() - timedelta(days=90)
    await _add_bars(db_session, stock, [last_bar])

    await etl.fetch_and_store_prices(["ZZZGAP"])

    call = fake_yahoo.call_for("ZZZGAP")
    assert call["start_date"] is not None, "fetch used a fixed period, not a window"
    assert call["start_date"] <= last_bar, (
        "fetch window starts after the last stored bar -- the gap stays open"
    )


async def test_refresh_window_overlaps_recent_bars_for_revisions(
    db_session: AsyncSession,
    etl: ETLOrchestrator,
    fake_yahoo: FakeYahooAdapter,
) -> None:
    """A current symbol still re-fetches a few settled days."""
    stock = await _add_stock(db_session, "ZZZFRESH")
    last_bar = date.today() - timedelta(days=1)
    await _add_bars(db_session, stock, [last_bar])

    await etl.fetch_and_store_prices(["ZZZFRESH"])

    call = fake_yahoo.call_for("ZZZFRESH")
    assert call["start_date"] < last_bar


async def test_symbol_with_no_history_gets_a_long_initial_lookback(
    db_session: AsyncSession,
    etl: ETLOrchestrator,
    fake_yahoo: FakeYahooAdapter,
) -> None:
    """A brand-new ticker needs enough history for a 200-day average."""
    await _add_stock(db_session, "ZZZNEW")

    await etl.fetch_and_store_prices(["ZZZNEW"])

    call = fake_yahoo.call_for("ZZZNEW")
    assert (date.today() - call["start_date"]).days >= 300


# ---------------------------------------------------------------------------
# Defect 3 -- a failed symbol was indistinguishable from an empty one
# ---------------------------------------------------------------------------


async def test_partial_batch_failure_is_counted_and_surfaced(
    db_session: AsyncSession,
    etl: ETLOrchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One symbol raising must be reported, not folded into a zero count."""
    adapter = FakeYahooAdapter(failing={"ZZZBAD"})
    monkeypatch.setattr("scheduler.etl.yahoo_adapter", adapter)

    await _add_stock(db_session, "ZZZGOOD")
    await _add_stock(db_session, "ZZZBAD")

    report = await etl.fetch_and_store_prices(["ZZZGOOD", "ZZZBAD"])

    assert report.requested == 2
    assert report.attempted == 2
    assert report.succeeded == 1
    assert report.failed == 1
    assert "ZZZBAD" in report.failures
    assert "simulated yfinance failure" in report.failures["ZZZBAD"]
    assert report.is_complete is False, "a partial failure must not look complete"
    assert report.as_dict()["failed"] == 1


async def test_a_failed_symbol_does_not_lose_its_siblings_writes(
    db_session: AsyncSession,
    etl: ETLOrchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-symbol sessions: one rollback must not discard another's bars."""
    adapter = FakeYahooAdapter(failing={"ZZZBAD"})
    monkeypatch.setattr("scheduler.etl.yahoo_adapter", adapter)

    await _add_stock(db_session, "ZZZGOOD")
    await _add_stock(db_session, "ZZZBAD")

    await etl.fetch_and_store_prices(["ZZZGOOD", "ZZZBAD"])

    rows = (
        await db_session.execute(
            select(PriceHistory)
            .join(Stock, Stock.id == PriceHistory.stock_id)
            .where(Stock.symbol == "ZZZGOOD")
        )
    ).scalars().all()
    assert rows, "the healthy symbol's bars were lost with the failing one's"


async def test_a_fully_successful_run_reports_complete(
    db_session: AsyncSession,
    etl: ETLOrchestrator,
    fake_yahoo: FakeYahooAdapter,
) -> None:
    await _add_stock(db_session, "ZZZOK")

    report = await etl.fetch_and_store_prices(["ZZZOK"])

    assert report.failed == 0
    assert report.is_complete is True
    assert report.new_bars > 0
    assert "ZZZOK" in report.summary() or report.succeeded == 1


# ---------------------------------------------------------------------------
# The catch-up backfill
# ---------------------------------------------------------------------------


async def test_catch_up_closes_a_synthetic_gap(
    db_session: AsyncSession,
    etl: ETLOrchestrator,
    fake_yahoo: FakeYahooAdapter,
) -> None:
    """A symbol frozen 60 days ago must have its missing bars written."""
    stock = await _add_stock(db_session, "ZZZSTALE")
    frozen_at = date.today() - timedelta(days=60)
    await _add_bars(db_session, stock, [frozen_at])

    before = (
        await db_session.execute(
            select(PriceHistory).where(PriceHistory.stock_id == stock.id)
        )
    ).scalars().all()
    assert len(before) == 1

    report = await etl.catch_up_prices()

    after = (
        await db_session.execute(
            select(PriceHistory).where(PriceHistory.stock_id == stock.id)
        )
    ).scalars().all()
    assert len(after) > 30, "the 60-day gap was not backfilled"
    assert max(row.date for row in after) > frozen_at
    assert report.new_bars > 0


async def test_catch_up_repairs_an_interior_hole_behind_a_current_bar(
    db_session: AsyncSession,
    etl: ETLOrchestrator,
    fake_yahoo: FakeYahooAdapter,
) -> None:
    """SPY's exact symptom: a current newest bar with a month missing behind it.

    A staleness check that only looks at the newest bar calls this healthy and
    skips it forever, so the hole never closes.
    """
    spy = await _add_stock(db_session, "SPY")
    recent = _weekdays_back(date.today(), 3)
    old = _weekdays_back(date.today() - timedelta(days=60), 3)
    await _add_bars(db_session, spy, old + recent)

    report = await etl.catch_up_prices()

    assert "SPY" in fake_yahoo.fetched_symbols, (
        "a symbol with a current newest bar was skipped despite interior holes"
    )
    call = fake_yahoo.call_for("SPY")
    assert (date.today() - call["start_date"]).days >= 60, (
        "the fetch window did not reach back over the hole"
    )
    assert report.new_bars > 20


async def test_catch_up_skips_symbols_that_are_already_current(
    db_session: AsyncSession,
    etl: ETLOrchestrator,
    fake_yahoo: FakeYahooAdapter,
) -> None:
    """A warm database must not re-download the whole universe on startup."""
    stock = await _add_stock(db_session, "ZZZCURRENT")
    # Dense enough that the gap scan sees intact history, not just a fresh
    # newest bar.
    await _add_bars(db_session, stock, _weekdays_back(date.today(), 130))

    report = await etl.catch_up_prices()

    assert "ZZZCURRENT" not in fake_yahoo.fetched_symbols
    assert report.skipped_current >= 1


async def test_a_symbol_that_returns_no_data_is_counted_separately(
    db_session: AsyncSession,
    etl: ETLOrchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A delisted ticker succeeds and writes nothing -- that is not a success.

    Nineteen tickers in the live table are in exactly this state; folding them
    into the success count is why they were never noticed.
    """

    class EmptyAdapter(FakeYahooAdapter):
        async def get_price_history(self, symbol: str, **kwargs: Any) -> list[Any]:
            await super().get_price_history(symbol, **kwargs)
            return []

    adapter = EmptyAdapter()
    monkeypatch.setattr("scheduler.etl.yahoo_adapter", adapter)
    await _add_stock(db_session, "ZZZDELISTED")

    report = await etl.fetch_and_store_prices(["ZZZDELISTED"])

    assert report.failed == 0
    assert report.returned_no_data == 1
    assert "ZZZDELISTED" in report.no_data_symbols
    assert report.as_dict()["returned_no_data"] == 1


# ---------------------------------------------------------------------------
# Coverage reporting -- what makes a recurrence visible
# ---------------------------------------------------------------------------


async def test_coverage_report_flags_a_stale_universe(
    db_session: AsyncSession,
) -> None:
    """The exact shape of the outage: a few current symbols, the rest frozen."""
    fresh = await _add_stock(db_session, "ZZZFRESH1")
    await _add_bars(db_session, fresh, _weekdays_back(date.today(), 2))

    frozen_at = date.today() - timedelta(days=100)
    for i in range(20):
        stale = await _add_stock(db_session, f"ZZZOLD{i}")
        await _add_bars(db_session, stale, [frozen_at])

    report = await price_coverage_report(db_session)

    assert report["symbols_tracked"] == 21
    assert report["symbols_current"] == 1
    assert report["symbols_stale"] == 20
    assert report["is_healthy"] is False
    assert report["stale_symbols"][0]["trading_days_behind"] > 2
    assert "stale" in format_coverage_report(report)


async def test_coverage_report_counts_symbols_with_no_bars_at_all(
    db_session: AsyncSession,
) -> None:
    await _add_stock(db_session, "ZZZEMPTY")

    report = await price_coverage_report(db_session)

    assert report["symbols_missing"] == 1
    assert "ZZZEMPTY" in report["missing_symbols"]


async def test_coverage_report_is_healthy_when_the_feed_works(
    db_session: AsyncSession,
) -> None:
    recent = _weekdays_back(date.today(), 5)
    for i in range(20):
        stock = await _add_stock(db_session, f"ZZZLIVE{i}")
        await _add_bars(db_session, stock, recent)

    report = await price_coverage_report(db_session)

    assert report["symbols_stale"] == 0
    assert report["is_healthy"] is True


async def test_benchmark_gap_report_counts_interior_holes(
    db_session: AsyncSession,
) -> None:
    """SPY's July hole is a different defect from trailing staleness.

    The benchmark had recent bars *and* a month-long interior hole; a report
    that only looked at the newest bar called it healthy.
    """
    spy = await _add_stock(db_session, "SPY")
    recent = _weekdays_back(date.today(), 5)
    old = _weekdays_back(date.today() - timedelta(days=60), 5)
    await _add_bars(db_session, spy, old + recent)

    report = await benchmark_gap_report(db_session, benchmark="SPY")

    assert report["present"] is True
    assert report["bars_in_window"] == 10
    assert report["missing_weekdays"] > 20, "the interior hole was not detected"


async def test_benchmark_gap_report_handles_a_missing_benchmark(
    db_session: AsyncSession,
) -> None:
    report = await benchmark_gap_report(db_session, benchmark="NOPE")

    assert report["present"] is False
    assert report["missing_weekdays"] == 0


async def test_price_coverage_endpoint_exposes_the_report(client: Any) -> None:
    """An operator has to be able to see this without reading logs."""
    response = await client.get("/api/v1/health/price-coverage")

    assert response.status_code == 200
    body = response.json()
    assert "symbols_tracked" in body
    assert "is_healthy" in body
    assert "benchmark" in body
