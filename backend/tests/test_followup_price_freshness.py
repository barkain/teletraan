"""Tests for dated prices in the follow-up-research prompt builder.

``FollowUpResearchLauncher._format_market_context`` fed the focused analyst two
undated numbers -- ``SPY: $746.74`` off ``market_summary.market_index`` and
``AAPL: $205.10`` off the newest ``price_history`` bar.  Both are the defect
that had the system recommending entries near $205 for a stock trading at $439:
a stored close reaches the LLM with no date, so a bar that is weeks old reads
as the live quote.  Every price this formatter emits must now carry its date,
or say ``UNAVAILABLE`` when it has none.
"""

import re
from datetime import date, timedelta

from analysis.followup_research import FollowUpResearchLauncher
from analysis.price_freshness import build_freshness, last_weekday


STALE_DAY = last_weekday(date.today() - timedelta(days=56))
FRESH_DAY = last_weekday(date.today() - timedelta(days=1))

# A dollar amount that is not immediately followed by its provenance suffix.
# This is exactly what the pre-fix code emitted, and what no call site may.
_UNDATED_PRICE = re.compile(r"\$[\d,]+\.\d{2}(?! \(as of )")


def _undated_prices(text: str) -> list[str]:
    """Every price in *text* that reaches the analyst without a date."""
    return _UNDATED_PRICE.findall(text)


def _format(context: dict) -> str:
    return FollowUpResearchLauncher()._format_market_context(context)


# ---------------------------------------------------------------------------
# Benchmark line (was: followup_research.py:515 -- "SPY: $<current>")
# ---------------------------------------------------------------------------


def test_refreshed_benchmark_renders_dated_price():
    """A re-quoted benchmark shows its date and no undated number."""
    context = {
        "market_summary": {
            "market_index": {
                "symbol": "SPY",
                "current": 802.15,
                "change_pct": 0.39,
                "freshness": build_freshness(
                    "SPY", FRESH_DAY, 802.15, "live_quote", refreshed=True
                ),
            }
        }
    }

    text = _format(context)

    assert "SPY Last Close: $802.15" in text
    assert f"(as of {FRESH_DAY.isoformat()}" in text
    assert "[STALE" not in text
    assert _undated_prices(text) == []


def test_stale_benchmark_keeps_its_real_date_and_warns():
    """A benchmark that could not be refreshed keeps its true date plus the
    STALE warning -- never a bare number, and never a synthetic date."""
    context = {
        "market_summary": {
            "market_index": {
                "symbol": "SPY",
                "current": 746.74,
                "change_pct": 0.12,
                "freshness": build_freshness("SPY", STALE_DAY, 746.74, "db_close"),
            }
        }
    }

    text = _format(context)

    assert "SPY Last Close: $746.74" in text
    assert STALE_DAY.isoformat() in text
    assert "[STALE" in text
    assert _undated_prices(text) == []


def test_stale_benchmark_change_pct_is_not_swallowed_by_the_warning():
    """The daily change goes on its own line: appended to a line ending in
    ``... Do not derive entry, stop or target levels from it]`` it reads as
    though the warning applied to the percentage."""
    context = {
        "market_summary": {
            "market_index": {
                "symbol": "SPY",
                "current": 746.74,
                "change_pct": 0.12,
                "freshness": build_freshness("SPY", STALE_DAY, 746.74, "db_close"),
            }
        }
    }

    lines = [ln for ln in _format(context).splitlines() if ln.strip()]
    stale_line = next(ln for ln in lines if "[STALE" in ln)
    change_line = next(ln for ln in lines if ln.startswith("Change:"))

    assert stale_line.endswith("levels from it]")
    assert "%" not in stale_line
    assert change_line == "Change: +0.12%"


def test_benchmark_without_freshness_record_falls_back_to_context_dates():
    """A hand-built payload that never went through the context builder is
    still dated, from the reconciled snapshot in the context."""
    context = {
        "market_summary": {"market_index": {"symbol": "SPY", "current": 802.15}},
        "price_freshness": {
            "SPY": build_freshness("SPY", FRESH_DAY, 802.15, "db_close")
        },
    }

    text = _format(context)

    assert f"SPY Last Close: $802.15 (as of {FRESH_DAY.isoformat()}" in text
    assert _undated_prices(text) == []


def test_benchmark_with_no_date_at_all_renders_unavailable():
    """No date anywhere in the payload must render UNAVAILABLE rather than
    quoting a bare number -- and must not raise."""
    context = {"market_summary": {"market_index": {"symbol": "SPY", "current": 802.15}}}

    text = _format(context)

    assert "SPY Last Close: UNAVAILABLE" in text
    assert "802.15" not in text
    assert _undated_prices(text) == []


# ---------------------------------------------------------------------------
# Per-symbol line (was: followup_research.py:523 -- "{symbol}: $<close>")
# ---------------------------------------------------------------------------


def test_price_history_quote_renders_dated_price():
    context = {
        "price_history": {
            "AAPL": [
                {"date": FRESH_DAY.isoformat(), "close": 231.50},
                {"date": (FRESH_DAY - timedelta(days=1)).isoformat(), "close": 229.00},
            ]
        }
    }

    text = _format(context)

    assert f"AAPL: $231.50 (as of {FRESH_DAY.isoformat()}" in text
    assert "[STALE" not in text
    assert _undated_prices(text) == []


def test_stale_price_history_quote_keeps_its_real_date_and_warns():
    """The original $205-vs-$439 defect: a 56-day-old bar must announce itself."""
    context = {
        "price_history": {"AAPL": [{"date": STALE_DAY.isoformat(), "close": 205.10}]}
    }

    text = _format(context)

    assert "AAPL: $205.10" in text
    assert STALE_DAY.isoformat() in text
    assert "[STALE" in text
    assert "Do not derive entry, stop or target levels from it" in text
    assert _undated_prices(text) == []


def test_price_history_quote_prefers_the_reconciled_snapshot():
    """When the context builder already reconciled a newer quote, the formatter
    quotes that one -- not the older bar it happens to be iterating over."""
    context = {
        "price_history": {"AAPL": [{"date": STALE_DAY.isoformat(), "close": 205.10}]},
        "price_freshness": {
            "AAPL": build_freshness(
                "AAPL", FRESH_DAY, 439.20, "live_quote", refreshed=True
            )
        },
    }

    text = _format(context)

    assert f"AAPL: $439.20 (as of {FRESH_DAY.isoformat()}" in text
    assert "205.10" not in text
    assert _undated_prices(text) == []


def test_undated_price_history_bar_renders_unavailable():
    """A bar with a close but no date must not be quoted as a number."""
    context = {"price_history": {"AAPL": [{"close": 231.50}]}}

    text = _format(context)

    assert "AAPL: UNAVAILABLE" in text
    assert "231.50" not in text
    assert _undated_prices(text) == []


def test_empty_context_still_reports_no_data():
    assert _format({}) == "No market data available"
