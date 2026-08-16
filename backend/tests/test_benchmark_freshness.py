"""Tests for the benchmark-index and sector-ETF price refresh.

The per-symbol freshness contract (``tests/test_price_freshness.py``) covered
``price_history`` only.  ``market_summary.market_index`` and
``sector_performance`` are built by their own DB queries, so they missed the
refresh entirely: a live run handed the analysts a correctly re-quoted AAPL
next to a 56-day-old SPY benchmark, and every relative-strength judgement made
against that benchmark was worthless.
"""

from datetime import date, datetime, timedelta

import pytest

from analysis.agents.correlation_detective import format_correlation_context
from analysis.agents.macro_economist import format_macro_context
from analysis.agents.risk_analyst import format_risk_context
from analysis.agents.sector_rotator import format_sector_rotator_context
from analysis.agents.sector_strategist import format_sector_context
from analysis.agents.technical_analyst import format_technical_context
from analysis.context_builder import (
    MAX_BENCHMARK_REFRESH_SYMBOLS,
    MarketContextBuilder,
)
from analysis.price_freshness import last_weekday


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STALE_DAY = last_weekday(date.today() - timedelta(days=56))


class _FakeAdapter:
    """Stand-in for ``yahoo_adapter`` -- no network access in tests."""

    def __init__(self, quotes: dict, raises: Exception | None = None):
        self.quotes = quotes
        self.raises = raises
        self.calls: list[list[str]] = []

    async def get_multiple_prices(self, symbols: list[str]) -> dict:
        self.calls.append(list(symbols))
        if self.raises is not None:
            raise self.raises
        return {s: self.quotes.get(s, {"error": "not stubbed", "symbol": s}) for s in symbols}


@pytest.fixture()
def patch_yahoo(monkeypatch):
    """Install a fake Yahoo adapter and hand the test its handle."""

    def _install(quotes: dict, raises: Exception | None = None) -> _FakeAdapter:
        adapter = _FakeAdapter(quotes, raises)
        monkeypatch.setattr("data.adapters.yahoo.yahoo_adapter", adapter)
        return adapter

    return _install


def _quote(price: float, previous_close: float) -> dict:
    return {
        "price": price,
        "previous_close": previous_close,
        "day_high": price + 2,
        "day_low": price - 3,
        "volume": 71_000_000,
    }


def _market_index(day: date = STALE_DAY, price: float = 746.74) -> dict:
    """A ``market_summary`` shaped exactly as ``_get_market_summary`` builds it."""
    return {
        "date": datetime.utcnow().isoformat(),
        "market_index": {
            "symbol": "SPY",
            "name": "SPDR S&P 500 ETF Trust",
            "current": price,
            "previous_close": price - 1.5,
            "change": 1.5,
            "change_pct": 0.2,
            "volume": 60_000_000,
            "high": price + 1,
            "low": price - 2,
            "date": day.isoformat(),
        },
        "trading_session": "closed",
    }


def _with_analysed_symbol(context: dict) -> dict:
    """Add a healthy per-symbol block.

    ``format_technical_context`` / ``format_risk_context`` bail out with "no
    price data" unless the context carries a symbol to analyse; the benchmark
    alone is not one.  The symbol here is deliberately fresh so any stale date
    the assertions catch can only have come from the benchmark.
    """
    today = last_weekday(date.today())
    bars = [
        {
            "date": (today - timedelta(days=i)).isoformat(),
            "open": 300.0, "high": 305.0, "low": 298.0, "close": 302.25,
            "volume": 50_000_000, "adjusted_close": 302.25, "source": "db_close",
        }
        for i in range(25)
    ]
    context["stocks"] = [{"symbol": "AAPL", "name": "Apple Inc.", "sector": "Technology"}]
    context["price_history"] = {"AAPL": bars}
    context["technical_indicators"] = {"AAPL": {"atr": {"value": 8.0}}}
    context["price_freshness"] = {
        "AAPL": {
            "symbol": "AAPL", "status": "fresh", "latest_bar_date": today.isoformat(),
            "age_days": 0, "trading_age_days": 0, "price": 302.25,
            "source": "db_close", "as_of": today.isoformat(), "reason": None,
        }
    }
    return context


def _sector_row(symbol: str, day: date = STALE_DAY, price: float = 100.0) -> dict:
    """One ``sector_performance`` row as ``_calculate_sector_performance`` builds it."""
    return {
        "name": f"{symbol} Select Sector SPDR",
        "sector": "Technology",
        "current_price": price,
        "previous_close": price - 1,
        "daily_change": 1.0,
        "daily_change_pct": 1.0,
        "weekly_change_pct": 2.0,
        "monthly_change_pct": 5.0,
        "volume": 9_000_000,
        "as_of": day.isoformat(),
        "week_base_close": price * 0.98,
        "week_base_date": (day - timedelta(days=7)).isoformat(),
        "month_base_close": price * 0.95,
        "month_base_date": (day - timedelta(days=30)).isoformat(),
    }


# ---------------------------------------------------------------------------
# A. The benchmark index
# ---------------------------------------------------------------------------

async def test_stale_benchmark_is_refreshed_to_a_live_quote(patch_yahoo):
    """THE regression: a 56-day-old SPY row must not reach the prompt as-is."""
    adapter = patch_yahoo({"SPY": _quote(802.15, 799.0)})
    context = {"market_summary": _market_index()}

    builder = MarketContextBuilder()
    await builder._refresh_benchmark_prices(context)

    assert adapter.calls == [["SPY"]], "the live adapter must actually be consulted"

    market_index = context["market_summary"]["market_index"]
    freshness = market_index["freshness"]
    assert freshness["status"] == "refreshed"
    assert freshness["source"] == "live_quote"
    assert freshness["price"] == 802.15
    assert freshness["latest_bar_date"] == last_weekday(datetime.utcnow().date()).isoformat()

    # The block itself is rewritten, not just annotated -- everything derived
    # from it (change, session high/low) must come from the same quote.
    assert market_index["current"] == 802.15
    assert market_index["date"] == freshness["latest_bar_date"]
    assert market_index["previous_close"] == 799.0
    assert market_index["change"] == pytest.approx(3.15)
    assert market_index["change_pct"] == pytest.approx(3.15 / 799.0 * 100)
    assert market_index["high"] == 804.15
    assert market_index["low"] == 799.15


async def test_refreshed_benchmark_renders_as_a_current_dated_price(patch_yahoo):
    """Every analyst that quotes the benchmark shows the live price, undecorated."""
    patch_yahoo({"SPY": _quote(802.15, 799.0)})
    context = _with_analysed_symbol({"market_summary": _market_index()})

    builder = MarketContextBuilder()
    await builder._refresh_benchmark_prices(context)

    today = last_weekday(datetime.utcnow().date()).isoformat()
    rendered = [
        format_technical_context(context),
        format_risk_context(context),
        format_sector_context(context),
        format_sector_rotator_context(context),
    ]
    for text in rendered:
        assert "Last Close: $802.15" in text
        assert f"as of {today}" in text
        assert STALE_DAY.isoformat() not in text
        assert "[STALE" not in text
        assert "Current Price" not in text


async def test_failed_benchmark_refresh_stays_stale_with_its_real_date(patch_yahoo):
    """A failed quote keeps the old number, its real date, and the STALE warning."""
    patch_yahoo({"SPY": {"error": "rate limited", "symbol": "SPY"}})
    context = _with_analysed_symbol({"market_summary": _market_index()})

    builder = MarketContextBuilder()
    await builder._refresh_benchmark_prices(context)

    market_index = context["market_summary"]["market_index"]
    freshness = market_index["freshness"]
    assert freshness["status"] == "stale"
    assert freshness["latest_bar_date"] == STALE_DAY.isoformat()
    assert "rate limited" in freshness["reason"]
    assert market_index["current"] == 746.74, "no synthetic price on failure"
    assert market_index["date"] == STALE_DAY.isoformat()

    for text in (
        format_technical_context(context),
        format_risk_context(context),
        format_sector_context(context),
        format_sector_rotator_context(context),
    ):
        assert "Last Close: $746.74" in text
        assert STALE_DAY.isoformat() in text
        assert "[STALE" in text
        assert "Current Price" not in text


async def test_benchmark_refresh_survives_an_adapter_exception(patch_yahoo):
    """A raising adapter degrades to ``stale``; it must not kill the context build."""
    patch_yahoo({}, raises=RuntimeError("yahoo unreachable"))
    context = {"market_summary": _market_index()}

    builder = MarketContextBuilder()
    await builder._refresh_benchmark_prices(context)

    freshness = context["market_summary"]["market_index"]["freshness"]
    assert freshness["status"] == "stale"
    assert "yahoo unreachable" in freshness["reason"]


async def test_fresh_benchmark_is_not_re_quoted(patch_yahoo):
    """The healthy path must not pay for a network round trip."""
    adapter = patch_yahoo({"SPY": _quote(802.15, 799.0)})
    today = last_weekday(datetime.utcnow().date())
    context = {"market_summary": _market_index(day=today, price=801.0)}

    builder = MarketContextBuilder()
    await builder._refresh_benchmark_prices(context)

    assert adapter.calls == []
    freshness = context["market_summary"]["market_index"]["freshness"]
    assert freshness["status"] == "fresh"
    assert freshness["price"] == 801.0


async def test_market_summary_from_the_db_flows_into_the_refresh(
    db_session, patch_yahoo,
):
    """End to end over the real query: a stale stored SPY bar is re-quoted."""
    from models.price import PriceHistory
    from models.stock import Stock

    spy = Stock(symbol="SPY", name="SPDR S&P 500 ETF Trust", sector="ETF")
    db_session.add(spy)
    await db_session.commit()
    await db_session.refresh(spy)

    for offset in range(3):
        day = STALE_DAY - timedelta(days=offset)
        db_session.add(PriceHistory(
            stock_id=spy.id, date=day, open=745.0, high=748.0, low=744.0,
            close=746.74 - offset, volume=60_000_000,
        ))
    await db_session.commit()

    patch_yahoo({"SPY": _quote(802.15, 799.0)})

    builder = MarketContextBuilder()
    summary = await builder._get_market_summary(db_session)
    assert summary["market_index"]["date"] == STALE_DAY.isoformat()

    context = {"market_summary": summary}
    await builder._refresh_benchmark_prices(context)

    assert summary["market_index"]["current"] == 802.15
    assert summary["market_index"]["freshness"]["status"] == "refreshed"


# ---------------------------------------------------------------------------
# B. The sector ETFs
# ---------------------------------------------------------------------------

async def test_stale_sector_etfs_are_refreshed_in_one_batched_call(patch_yahoo):
    """All eleven ETFs and the benchmark share a single adapter round trip."""
    etfs = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLC", "XLRE", "XLB"]
    adapter = patch_yahoo(
        {"SPY": _quote(802.15, 799.0)}
        | {etf: _quote(110.0, 109.0) for etf in etfs}
    )
    context = {
        "market_summary": _market_index(),
        "sector_performance": {etf: _sector_row(etf) for etf in etfs},
    }

    builder = MarketContextBuilder()
    await builder._refresh_benchmark_prices(context)

    assert len(adapter.calls) == 1, "the benchmark and the ETFs must batch together"
    assert sorted(adapter.calls[0]) == sorted([*etfs, "SPY"])

    row = context["sector_performance"]["XLK"]
    assert row["freshness"]["status"] == "refreshed"
    assert row["current_price"] == 110.0
    assert row["as_of"] == last_weekday(datetime.utcnow().date()).isoformat()
    assert row["daily_change_pct"] == pytest.approx(1.0 / 109.0 * 100)
    # Multi-day returns are re-measured against the refreshed price so the whole
    # row ends at the price printed next to it.
    assert row["weekly_change_pct"] == pytest.approx((110.0 - 98.0) / 98.0 * 100)
    assert row["monthly_change_pct"] == pytest.approx((110.0 - 95.0) / 95.0 * 100)


async def test_failed_sector_quote_degrades_to_stale_without_killing_the_build(
    patch_yahoo,
):
    """One dead ETF must not cost the other ten their refresh."""
    patch_yahoo({
        "XLK": _quote(110.0, 109.0),
        "XLF": {"error": "no quote returned", "symbol": "XLF"},
    })
    context = {
        "sector_performance": {"XLK": _sector_row("XLK"), "XLF": _sector_row("XLF")},
    }

    builder = MarketContextBuilder()
    await builder._refresh_benchmark_prices(context)

    assert context["sector_performance"]["XLK"]["freshness"]["status"] == "refreshed"

    failed = context["sector_performance"]["XLF"]
    assert failed["freshness"]["status"] == "stale"
    assert failed["current_price"] == 100.0, "the stale close is kept, not overwritten"
    assert failed["as_of"] == STALE_DAY.isoformat()

    rendered = format_sector_context(context)
    assert "** STALE" in rendered, "the failed ETF must still carry its warning"
    assert f"as of {STALE_DAY.isoformat()}" in rendered


async def test_refreshed_sector_etf_renders_without_the_stale_banner(patch_yahoo):
    """The strategist prints a current dated close and names the return windows."""
    patch_yahoo({"XLK": _quote(110.0, 109.0)})
    context = {"sector_performance": {"XLK": _sector_row("XLK")}}

    builder = MarketContextBuilder()
    await builder._refresh_benchmark_prices(context)

    rendered = format_sector_context(context)
    today = last_weekday(datetime.utcnow().date()).isoformat()

    assert f"Close: $110.00 (as of {today}" in rendered
    assert "** STALE" not in rendered
    # The weekly/monthly windows are stretched by the data gap, so the label
    # must name the bar they are measured from rather than imply 5 / 20 days.
    assert f"Weekly (since {(STALE_DAY - timedelta(days=7)).isoformat()})" in rendered
    assert f"Monthly (since {(STALE_DAY - timedelta(days=30)).isoformat()})" in rendered


async def test_benchmark_refresh_fan_out_is_capped(patch_yahoo):
    """A misconfigured ETF list cannot turn one build into a quote storm."""
    rows = {f"ET{i:02d}": _sector_row(f"ET{i:02d}") for i in range(40)}
    adapter = patch_yahoo({sym: _quote(110.0, 109.0) for sym in rows})
    context = {"sector_performance": rows}

    builder = MarketContextBuilder()
    await builder._refresh_benchmark_prices(context)

    assert len(adapter.calls) == 1
    assert len(adapter.calls[0]) == MAX_BENCHMARK_REFRESH_SYMBOLS

    skipped = [
        row for sym, row in rows.items() if sym not in adapter.calls[0]
    ]
    assert all(row["freshness"]["status"] == "stale" for row in skipped)
    assert all("refresh skipped" in row["freshness"]["reason"] for row in skipped)


# ---------------------------------------------------------------------------
# C. The last undated price label
# ---------------------------------------------------------------------------

def test_sector_rotator_never_emits_an_undated_price_label():
    """``sector_rotator`` printed a bare ``Current Price:`` for the benchmark."""
    context = {
        "market_summary": _market_index(),
        "sector_performance": {"XLK": _sector_row("XLK")},
    }

    rendered = format_sector_rotator_context(context)

    assert "Current Price" not in rendered
    assert "Today's" not in rendered
    assert f"Last Close: $746.74 (as of {STALE_DAY.isoformat()}" in rendered
    assert "[STALE" in rendered


def test_sector_rotator_states_the_real_return_windows():
    """The Weekly/Monthly columns name the bars they are measured from."""
    context = {"sector_performance": {"XLK": _sector_row("XLK")}}

    rendered = format_sector_rotator_context(context)

    assert f"Weekly from the {(STALE_DAY - timedelta(days=7)).isoformat()} close" in rendered
    assert f"Monthly from the {(STALE_DAY - timedelta(days=30)).isoformat()} close" in rendered
    assert f"ending at the {STALE_DAY.isoformat()} close" in rendered


def test_return_window_note_is_omitted_for_legacy_rows():
    """Data that predates the base-date fields renders exactly as before."""
    legacy = {"name": "Tech", "sector": "Technology", "daily_change_pct": 1.0,
              "weekly_change_pct": 2.0, "monthly_change_pct": 5.0, "volume": 10}

    rendered = format_sector_rotator_context({"sector_performance": {"XLK": legacy}})

    assert "Return windows" not in rendered


# ---------------------------------------------------------------------------
# D. The two labels that escaped the ``Current Price`` / ``Today's`` greps
#
# ``macro_economist`` printed ``Current: $746.74`` and ``correlation_detective``
# printed ``SPY: $746.74`` -- both undated, both invisible to a grep for the
# labels the earlier waves fixed.
# ---------------------------------------------------------------------------


def _refreshed_index(price: float = 802.15) -> dict:
    """A ``market_index`` carrying the record ``_refresh_benchmark_prices`` attaches."""
    today = last_weekday(datetime.utcnow().date())
    summary = _market_index(day=today, price=price)
    summary["market_index"]["freshness"] = {
        "symbol": "SPY", "status": "refreshed", "latest_bar_date": today.isoformat(),
        "age_days": 0, "trading_age_days": 0, "price": price,
        "source": "live_quote", "as_of": today.isoformat(), "reason": None,
    }
    return summary


def _stale_index(price: float = 746.74) -> dict:
    """The same block after a failed refresh: real date kept, status ``stale``."""
    summary = _market_index(day=STALE_DAY, price=price)
    summary["market_index"]["freshness"] = {
        "symbol": "SPY", "status": "stale", "latest_bar_date": STALE_DAY.isoformat(),
        "age_days": (date.today() - STALE_DAY).days, "trading_age_days": 40,
        "price": price, "source": "db_close", "as_of": date.today().isoformat(),
        "reason": "live quote unavailable: rate limited",
    }
    return summary


def test_macro_economist_dates_a_refreshed_benchmark():
    """``Current: $X`` is gone; the live quote reads as a dated close."""
    today = last_weekday(datetime.utcnow().date()).isoformat()

    rendered = format_macro_context({"market_summary": _refreshed_index()})

    assert "Current: $" not in rendered
    assert "Current Price" not in rendered
    assert f"Last Close: $802.15 (as of {today}" in rendered
    assert "[STALE" not in rendered


def test_macro_economist_flags_a_stale_benchmark_with_its_real_date():
    """A stale benchmark keeps its number but can never read as the live price."""
    rendered = format_macro_context({"market_summary": _stale_index()})

    assert "Current: $" not in rendered
    assert f"Last Close: $746.74 (as of {STALE_DAY.isoformat()}" in rendered
    assert "[STALE" in rendered
    assert "rate limited" in rendered


def test_correlation_detective_dates_a_refreshed_benchmark():
    """``SPY: $X (+0.2%)`` is gone; the benchmark reads as a dated close."""
    today = last_weekday(datetime.utcnow().date()).isoformat()
    context = _with_analysed_symbol({"market_summary": _refreshed_index()})

    rendered = format_correlation_context(context)

    assert f"SPY Last Close: $802.15 (as of {today}" in rendered
    assert "\nSPY: $" not in rendered
    assert "Current Price" not in rendered
    assert "[STALE" not in rendered


def test_correlation_detective_flags_a_stale_benchmark_with_its_real_date():
    """The stale benchmark keeps its real date and carries the STALE warning."""
    context = _with_analysed_symbol({"market_summary": _stale_index()})

    rendered = format_correlation_context(context)

    assert f"SPY Last Close: $746.74 (as of {STALE_DAY.isoformat()}" in rendered
    assert "\nSPY: $" not in rendered
    assert "[STALE" in rendered


def test_correlation_detective_dates_every_per_symbol_quote():
    """The same sweep caught the per-symbol ``AAPL: $302.25`` lines beside it."""
    today = last_weekday(date.today()).isoformat()
    context = _with_analysed_symbol({"market_summary": _refreshed_index()})

    rendered = format_correlation_context(context)

    assert f"AAPL: $302.25 (as of {today}" in rendered
    assert "\nAAPL: $302.25 (1D" not in rendered


def test_correlation_detective_dates_legacy_payload_quotes():
    """Hand-built ``prices`` dicts still render -- dated off their own bars."""
    bar_date = STALE_DAY.isoformat()
    legacy = {
        "symbols": ["MSFT"],
        "prices": {
            "MSFT": [
                {"date": (STALE_DAY - timedelta(days=1)).isoformat(), "close": 400.0},
                {"date": bar_date, "close": 410.0},
            ]
        },
    }

    rendered = format_correlation_context(legacy)

    assert f"MSFT: $410.00 (as of {bar_date}" in rendered
    assert "[STALE" in rendered


def test_undated_hand_built_benchmark_renders_without_crashing():
    """A legacy block with no date at all says so rather than quoting a bare number."""
    undated = {"market_summary": {"market_index": {"symbol": "SPY", "current": 746.74,
                                                   "change_pct": 0.2, "volume": 1_000}}}

    for rendered in (
        format_macro_context(undated),
        format_correlation_context(_with_analysed_symbol(dict(undated))),
    ):
        assert "$746.74" not in rendered, "an undatable price must not be quoted"
        assert "UNAVAILABLE" in rendered
