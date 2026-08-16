"""Pin the bar-ordering contract the daily alpha engine depends on.

`MarketContextBuilder._get_price_history()` returns bars NEWEST first and
prepends a live refresh quote at index 0; every scoring helper in
`analysis.alpha_engine` reads the TAIL as "now". Feeding one to the other
inverted momentum silently -- the numbers stayed plausible, only the sign was
wrong -- so these tests fix the direction with a worked example rather than
asserting that some function was called.
"""

from __future__ import annotations

import pytest

from analysis import alpha_engine as ae


# The reviewer's reproduction, kept literal: three consecutive sessions in which
# the stock rose 100 -> 110 -> 120. In the builder's real (newest-first) order
# that is [120, 110, 100].
NEWEST_FIRST = [
    {"date": "2026-04-30", "close": 120.0, "volume": 3_000_000},
    {"date": "2026-04-29", "close": 110.0, "volume": 2_000_000},
    {"date": "2026-04-28", "close": 100.0, "volume": 1_000_000},
]
OLDEST_FIRST = list(reversed(NEWEST_FIRST))


class TestCanonicalBarOrder:
    def test_newest_first_input_is_flipped_to_oldest_first(self):
        assert ae.as_oldest_first(NEWEST_FIRST) == OLDEST_FIRST

    def test_oldest_first_input_is_left_alone(self):
        assert ae.as_oldest_first(OLDEST_FIRST) == OLDEST_FIRST

    def test_normalizing_does_not_mutate_the_cached_context_list(self):
        original = list(NEWEST_FIRST)
        ae.as_oldest_first(NEWEST_FIRST)
        assert NEWEST_FIRST == original, "build_context() caches this list"

    def test_undated_rows_pass_through_untouched(self):
        rows = [{"close": 1.0}, {"close": 2.0}, {"close": 3.0}]
        assert ae.as_oldest_first(rows) == rows


class TestWorkedExample:
    """The exact numbers from the review. A refactor that re-inverts the order
    has to change these constants, which is the point of writing them out."""

    def test_latest_close_is_the_most_recent_bar_not_the_last_element(self):
        assert ae._latest_close(ae.as_oldest_first(NEWEST_FIRST)) == 120.0

    def test_one_bar_return_is_positive_nine_percent(self):
        closes, _ = ae._price_series(ae.as_oldest_first(NEWEST_FIRST))
        ret = ae._pct_return(closes, 1)
        assert ret == pytest.approx(9.0909, abs=1e-3)
        assert ret > 0, "the stock rose 110 -> 120; a negative return is inverted"

    def test_two_bar_return_is_positive_twenty_percent(self):
        closes, _ = ae._price_series(ae.as_oldest_first(NEWEST_FIRST))
        assert ae._pct_return(closes, 2) == pytest.approx(20.0)

    def test_volume_ratio_uses_the_most_recent_bars_volume(self):
        # Newest bar has 3M shares against a 1.5M average of the two before it.
        ratio = ae._volume_ratio(ae.as_oldest_first(NEWEST_FIRST), lookback=2)
        assert ratio == pytest.approx(2.0)

    def test_reading_the_builders_order_directly_would_invert_the_sign(self):
        """Guards the guard: prove the un-normalized read really is backwards."""
        raw_closes = [row["close"] for row in NEWEST_FIRST]
        assert ae._pct_return(raw_closes, 1) == pytest.approx(-9.0909, abs=1e-3)


class TestOrderingIsAsserted:
    """Normalizing at the boundary is only half the fix. The helpers refuse
    newest-first input outright so a future caller cannot silently re-invert."""

    def test_price_series_rejects_newest_first_input(self):
        with pytest.raises(ae.BarOrderError, match="newest-first"):
            ae._price_series(NEWEST_FIRST)

    def test_latest_close_rejects_newest_first_input(self):
        with pytest.raises(ae.BarOrderError):
            ae._latest_close(NEWEST_FIRST)

    def test_scoring_rejects_newest_first_input(self):
        with pytest.raises(ae.BarOrderError):
            ae._score_basic_technical(NEWEST_FIRST, [], [], None, None)


class TestHistoryMapBoundary:
    def test_every_symbol_in_the_context_map_is_normalized(self):
        normalized = ae._oldest_first_history_map(
            {"AAPL": NEWEST_FIRST, "SPY": NEWEST_FIRST}
        )
        for symbol, bars in normalized.items():
            assert ae._latest_close(bars) == 120.0, symbol

    def test_a_refreshed_live_quote_at_index_zero_becomes_the_latest_close(self):
        """The refresh path prepends one live bar. Pre-fix it was ignored:
        `closes[-1]` returned the OLDEST bar, 90 sessions behind."""
        refreshed = [{"date": "2026-05-01", "close": 131.0, "source": "live_quote"}]
        refreshed += NEWEST_FIRST

        normalized = ae._oldest_first_history_map({"AAPL": refreshed})["AAPL"]
        assert ae._latest_close(normalized) == 131.0

    def test_missing_or_empty_map_is_harmless(self):
        assert ae._oldest_first_history_map(None) == {}
        assert ae._oldest_first_history_map({}) == {}
