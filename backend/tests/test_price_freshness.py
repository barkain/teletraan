"""Tests for the price freshness contract.

Regression cover for the defect where analyst prompts printed a stored close
under the label "Current Price" (and the same bar's high/low as "Today's
High"/"Today's Low") no matter how far behind the ETL had fallen -- two runs
fifty minutes apart quoted ARM at $205-215 and $430-445 off the same pipeline.
"""

from datetime import date, datetime, timedelta

import pytest

from analysis.agents.risk_analyst import format_risk_context
from analysis.agents.technical_analyst import format_technical_context
from analysis.context_builder import MarketContextBuilder
from analysis.price_freshness import (
    STALE_AFTER_TRADING_DAYS,
    build_freshness,
    derive_freshness,
    last_weekday,
    reconcile,
    resolve_snapshot,
    snapshot_price,
    trading_days_between,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bars(latest: date, count: int = 25, close: float = 205.0) -> list[dict]:
    """Build *count* newest-first daily bars ending on *latest*."""
    return [
        {
            "date": (latest - timedelta(days=i)).isoformat(),
            "open": close - 1,
            "high": close + 2,
            "low": close - 3,
            "close": close,
            "volume": 1_000_000,
            "adjusted_close": close,
            "source": "db_close",
        }
        for i in range(count)
    ]


def _market_data(symbol: str, bars: list[dict], freshness: dict | None = None) -> dict:
    data = {
        "stocks": [{"symbol": symbol, "name": f"{symbol} Inc.", "sector": "Technology"}],
        "price_history": {symbol: bars},
        "technical_indicators": {symbol: {"atr": {"value": 8.0}}},
    }
    if freshness is not None:
        data["price_freshness"] = {symbol: freshness}
    return data


class _FakeAdapter:
    """Stand-in for ``yahoo_adapter`` -- no network access in tests."""

    def __init__(self, quotes: dict):
        self.quotes = quotes
        self.calls: list[list[str]] = []

    async def get_multiple_prices(self, symbols: list[str]) -> dict:
        self.calls.append(list(symbols))
        return {s: self.quotes.get(s, {"error": "not stubbed", "symbol": s}) for s in symbols}


@pytest.fixture()
def patch_yahoo(monkeypatch):
    """Install a fake Yahoo adapter and hand the test its handle."""

    def _install(quotes: dict) -> _FakeAdapter:
        adapter = _FakeAdapter(quotes)
        monkeypatch.setattr("data.adapters.yahoo.yahoo_adapter", adapter)
        return adapter

    return _install


# ---------------------------------------------------------------------------
# Age arithmetic
# ---------------------------------------------------------------------------

def test_trading_days_between_skips_weekends():
    """A Friday bar read on the following Monday is one trading day old."""
    friday = date(2026, 8, 7)
    monday = date(2026, 8, 10)
    assert trading_days_between(friday, monday) == 1
    assert trading_days_between(friday, date(2026, 8, 9)) == 0  # Sunday
    assert trading_days_between(date(2026, 4, 30), date(2026, 6, 19)) == 36


def test_freshness_threshold_boundary():
    """Exactly at the threshold is fresh; one trading day past it is stale."""
    as_of = date(2026, 8, 12)  # Wednesday
    at_limit = build_freshness("AAPL", date(2026, 8, 10), 100.0, "db_close", as_of=as_of)
    past_limit = build_freshness("AAPL", date(2026, 8, 7), 100.0, "db_close", as_of=as_of)

    assert trading_days_between(date(2026, 8, 10), as_of) == STALE_AFTER_TRADING_DAYS
    assert at_limit["status"] == "fresh"
    assert past_limit["status"] == "stale"
    assert past_limit["age_days"] == 5


# ---------------------------------------------------------------------------
# A. Context builder: staleness detection and live refresh
# ---------------------------------------------------------------------------

async def test_stale_db_bars_are_refreshed_from_live_adapter(
    db_session, sample_stock, patch_yahoo,
):
    """THE regression: 50-day-old stored bars must not be served as current.

    They are re-quoted from the live adapter, the quote becomes bar 0, and the
    freshness record says so.
    """
    from models.price import PriceHistory

    stale_day = last_weekday(date.today() - timedelta(days=50))
    for bar in _bars(stale_day, count=10, close=205.0):
        db_session.add(
            PriceHistory(
                stock_id=sample_stock.id,
                date=date.fromisoformat(bar["date"]),
                open=bar["open"], high=bar["high"], low=bar["low"],
                close=bar["close"], volume=bar["volume"],
            )
        )
    await db_session.commit()

    adapter = patch_yahoo({
        "AAPL": {
            "symbol": "AAPL", "price": 439.46, "previous_close": 435.0,
            "day_high": 441.0, "day_low": 433.2, "volume": 52_000_000,
        }
    })

    builder = MarketContextBuilder()
    bundle = await builder._get_price_history(
        db_session, ["AAPL"], {"AAPL": sample_stock.id}, days=200,
    )

    assert adapter.calls == [["AAPL"]], "the live adapter must actually be consulted"

    freshness = bundle["freshness"]["AAPL"]
    assert freshness["status"] == "refreshed"
    assert freshness["price"] == 439.46
    assert freshness["source"] == "live_quote"
    # The builder dates the quote off UTC (last_weekday(utcnow().date())), so
    # the expectation must read the same clock -- local date.today() differs
    # from the UTC date for part of every day and made this assertion fail
    # whenever the two straddled a weekend.
    expected_quote_date = last_weekday(datetime.utcnow().date())
    assert freshness["latest_bar_date"] == expected_quote_date.isoformat()
    assert "trading days are missing" in (freshness["reason"] or "")

    bars = bundle["bars"]["AAPL"]
    assert bars[0]["close"] == 439.46
    assert bars[0]["source"] == "live_quote"
    assert bars[1]["close"] == 205.0, "stored history is kept behind the live bar"


async def test_failed_refresh_marks_symbol_stale_not_current(
    db_session, sample_stock, patch_yahoo,
):
    """When the live quote fails the old bar keeps its place but is labelled stale."""
    from models.price import PriceHistory

    stale_day = last_weekday(date.today() - timedelta(days=50))
    for bar in _bars(stale_day, count=10, close=205.0):
        db_session.add(
            PriceHistory(
                stock_id=sample_stock.id,
                date=date.fromisoformat(bar["date"]),
                open=bar["open"], high=bar["high"], low=bar["low"],
                close=bar["close"], volume=bar["volume"],
            )
        )
    await db_session.commit()

    patch_yahoo({"AAPL": {"error": "rate limited", "symbol": "AAPL"}})

    builder = MarketContextBuilder()
    bundle = await builder._get_price_history(
        db_session, ["AAPL"], {"AAPL": sample_stock.id}, days=200,
    )

    freshness = bundle["freshness"]["AAPL"]
    assert freshness["status"] == "stale"
    assert "rate limited" in freshness["reason"]
    assert bundle["bars"]["AAPL"][0]["close"] == 205.0
    assert bundle["bars"]["AAPL"][0]["source"] == "db_close", "no synthetic bar on failure"

    # And the stale price must never reach the prompt as a current one.
    market_data = _market_data("AAPL", bundle["bars"]["AAPL"], freshness)
    for rendered in (format_technical_context(market_data), format_risk_context(market_data)):
        assert "Current Price" not in rendered
        assert "Today's High" not in rendered
        assert "Today's Low" not in rendered
        assert "STALE" in rendered
        assert stale_day.isoformat() in rendered


async def test_symbol_without_stored_history_is_marked_missing(
    db_session, sample_stock, patch_yahoo,
):
    """A symbol with no bars at all reads as ``missing``, not as absent."""
    patch_yahoo({"AAPL": {"error": "delisted", "symbol": "AAPL"}})

    builder = MarketContextBuilder()
    bundle = await builder._get_price_history(
        db_session, ["AAPL"], {"AAPL": sample_stock.id}, days=60,
    )

    assert bundle["freshness"]["AAPL"]["status"] == "missing"
    assert bundle["freshness"]["AAPL"]["price"] is None


async def test_fresh_symbol_is_not_re_quoted(db_session, sample_stock, patch_yahoo):
    """The healthy path must not pay for a network round trip."""
    from models.price import PriceHistory

    fresh_day = last_weekday(date.today())
    for bar in _bars(fresh_day, count=5, close=189.0):
        db_session.add(
            PriceHistory(
                stock_id=sample_stock.id,
                date=date.fromisoformat(bar["date"]),
                open=bar["open"], high=bar["high"], low=bar["low"],
                close=bar["close"], volume=bar["volume"],
            )
        )
    await db_session.commit()

    adapter = patch_yahoo({})

    builder = MarketContextBuilder()
    bundle = await builder._get_price_history(
        db_session, ["AAPL"], {"AAPL": sample_stock.id}, days=60,
    )

    assert adapter.calls == []
    assert bundle["freshness"]["AAPL"]["status"] == "fresh"
    assert bundle["freshness"]["AAPL"]["price"] == 189.0


# ---------------------------------------------------------------------------
# Reconciling the two independently-sourced "current" prices
# ---------------------------------------------------------------------------

def test_reconcile_prefers_the_more_recent_snapshot():
    """The yfinance rich-TA price wins when the stored bar is older, not otherwise."""
    db_record = build_freshness(
        "ARM", date(2026, 4, 30), 205.0, "db_close", as_of=date(2026, 6, 19),
    )
    merged = reconcile(db_record, "ARM", "2026-06-18", 439.46, "yfinance_history")

    assert merged["price"] == 439.46
    assert merged["source"] == "yfinance_history"
    assert merged["latest_bar_date"] == "2026-06-18"

    # An older rich-TA snapshot must not displace a newer stored bar.
    fresh_db = build_freshness(
        "ARM", date(2026, 6, 18), 439.46, "db_close", as_of=date(2026, 6, 19),
    )
    kept = reconcile(fresh_db, "ARM", "2026-04-30", 205.0, "yfinance_history")
    assert kept["price"] == 439.46


def test_resolve_snapshot_derives_freshness_when_context_has_none():
    """Hand-built contexts still get a dated snapshot, preferring the newer source."""
    market_data = {
        "price_history": {"ARM": _bars(date(2026, 4, 30), count=3, close=205.0)},
        "rich_technical": {"ARM": {"latest_price": 439.46, "latest_date": "2026-06-18"}},
    }
    snapshot = resolve_snapshot(market_data, "ARM")

    assert snapshot["price"] == 439.46
    assert snapshot["source"] == "yfinance_history"


# ---------------------------------------------------------------------------
# B. Rendered labels
# ---------------------------------------------------------------------------

def test_formatters_never_quote_two_disagreeing_prices():
    """One snapshot feeds the whole prompt when DB and yfinance disagree.

    The audit found a $205 DB close printed as the current price beside rich-TA
    levels computed off $439 in the same output.
    """
    stale_day = last_weekday(date.today() - timedelta(days=100))
    fresh_day = last_weekday(date.today())
    market_data = _market_data(
        "ARM",
        _bars(stale_day, count=25, close=205.0),
        build_freshness("ARM", stale_day, 205.0, "db_close"),
    )
    market_data["rich_technical"] = {
        "ARM": {"latest_price": 439.46, "latest_date": fresh_day.isoformat()},
    }

    technical = format_technical_context(market_data)
    risk = format_risk_context(market_data)

    for rendered in (technical, risk):
        assert "Last Close: $439.46" in rendered
        assert "Last Close: $205.00" not in rendered
        assert "source: yfinance daily bar" in rendered


def test_fresh_output_carries_the_bar_date_and_age():
    """Every quoted price states the date it is valid for and how old it is."""
    fresh_day = last_weekday(date.today())
    bars = _bars(fresh_day, count=25, close=189.0)
    freshness = build_freshness("AAPL", fresh_day, 189.0, "db_close")
    market_data = _market_data("AAPL", bars, freshness)

    technical = format_technical_context(market_data)
    risk = format_risk_context(market_data)

    for rendered in (technical, risk):
        assert "Last Close: $189.00" in rendered
        assert f"as of {fresh_day.isoformat()}" in rendered
        assert "d old" in rendered
        assert "source: DB close" in rendered
        assert "STALE" not in rendered


def test_fresh_output_keeps_the_substance_of_the_old_rendering():
    """No regression on the healthy path: the same numbers still reach the prompt."""
    fresh_day = last_weekday(date.today())
    bars = _bars(fresh_day, count=25, close=189.0)
    freshness = build_freshness("AAPL", fresh_day, 189.0, "db_close")
    market_data = _market_data("AAPL", bars, freshness)

    technical = format_technical_context(market_data)
    risk = format_risk_context(market_data)

    # Price, volume, rolling extremes and ATR% all still present and correct.
    assert "$189.00" in technical
    assert "1,000,000" in technical
    assert "20-Period High: $191.00" in technical
    assert "20-Period Low: $186.00" in technical
    assert "ATR(14): $8.00 (4.23%" in technical

    assert "Session High" in risk and "$191.00" in risk
    assert "20-Period Support: $186.00" in risk
    assert "20-Period Resistance: $191.00" in risk
    assert "ATR (14-day): $8.00 (4.2%" in risk


def test_stale_snapshot_suppresses_percent_of_price_metrics():
    """ATR-as-%-of-price is withheld rather than computed off a stale price."""
    stale_day = last_weekday(date.today() - timedelta(days=50))
    bars = _bars(stale_day, count=25, close=205.0)
    freshness = build_freshness("ARM", stale_day, 205.0, "db_close")
    assert freshness["status"] == "stale"

    market_data = _market_data("ARM", bars, freshness)
    technical = format_technical_context(market_data)
    risk = format_risk_context(market_data)

    assert "% of price not shown" in technical
    assert "% of price withheld" in risk
    assert "PRICE DATA IS STALE" in risk


def test_refreshed_snapshot_is_quoted_over_the_stored_bar():
    """After a live refresh the prompt quotes the live price, not the old close."""
    stale_day = last_weekday(date.today() - timedelta(days=50))
    quote_day = last_weekday(date.today())
    bars = _bars(stale_day, count=25, close=205.0)
    bars.insert(0, {
        "date": quote_day.isoformat(), "open": 435.0, "high": 441.0, "low": 433.2,
        "close": 439.46, "volume": 52_000_000, "adjusted_close": 439.46,
        "source": "live_quote", "partial": True,
    })
    freshness = build_freshness(
        "ARM", quote_day, 439.46, "live_quote", refreshed=True,
    )
    market_data = _market_data("ARM", bars, freshness)

    technical = format_technical_context(market_data)
    risk = format_risk_context(market_data)

    assert "Last Close: $439.46" in technical
    assert "source: live quote" in technical
    assert "Last Close: $439.46" in risk
    assert "Current Price" not in risk
    assert "Today's High" not in risk


# ---------------------------------------------------------------------------
# Symbol case: the context builder keys every block upper-case, but candidate
# symbols arrive from LLM JSON in whatever case the model chose.  An exact-key
# lookup here reads a healthy context as "no price data".
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("requested", ["aapl", "Aapl", "AAPL"])
def test_resolve_snapshot_is_case_insensitive(requested):
    """A lower/mixed-case request must find the upper-case-keyed record."""
    fresh_day = last_weekday(date.today())
    bars = _bars(fresh_day, count=25, close=189.0)
    freshness = build_freshness("AAPL", fresh_day, 189.0, "db_close")
    market_data = _market_data("AAPL", bars, freshness)

    resolved = resolve_snapshot(market_data, requested)

    assert resolved is not None, f"{requested} did not resolve against an AAPL context"
    assert resolved["status"] == "fresh"
    assert resolved["price"] == 189.0


@pytest.mark.parametrize("requested", ["aapl", "Aapl"])
def test_derive_freshness_is_case_insensitive(requested):
    """The derived path (no price_freshness block) normalises case too."""
    fresh_day = last_weekday(date.today())
    market_data = _market_data("AAPL", _bars(fresh_day, count=25, close=189.0))
    assert "price_freshness" not in market_data

    derived = derive_freshness(market_data, requested)

    assert derived is not None
    assert derived["status"] == "fresh"
    assert derived["price"] == 189.0


def test_snapshot_price_is_case_insensitive():
    """snapshot_price feeds the entry gate -- it must not return 0.0 on case."""
    fresh_day = last_weekday(date.today())
    freshness = build_freshness("AAPL", fresh_day, 189.0, "db_close")
    market_data = _market_data("AAPL", _bars(fresh_day, close=189.0), freshness)

    price, resolved = snapshot_price(market_data, "aapl")

    assert price == 189.0
    assert resolved is not None and resolved["status"] == "fresh"


def test_unknown_symbol_still_resolves_to_nothing():
    """Case-insensitivity must not turn a genuinely absent symbol into a hit."""
    fresh_day = last_weekday(date.today())
    freshness = build_freshness("AAPL", fresh_day, 189.0, "db_close")
    market_data = _market_data("AAPL", _bars(fresh_day, close=189.0), freshness)

    assert resolve_snapshot(market_data, "TSLA") is None
    assert snapshot_price(market_data, "tsla") == (0.0, None)
