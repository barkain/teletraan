"""Tests for the rebuilt insight outcome grader.

Each test here pins down one of the defects that made the historical hit rate
untrustworthy: raw-return scoring with no benchmark, grading on whatever price
happened to be current when the checker ran, a horizon table whose keys never
matched the stored values, an intraperiod path that never persisted, and a
price-level parser that read indicator periods as prices.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest

from analysis.outcome_tracker import InsightOutcomeTracker
from models.deep_insight import DeepInsight
from models.insight_outcome import InsightOutcome, TrackingStatus

START = date(2026, 1, 5)
END = START + timedelta(days=28)


def series(closes: list[float], start: date = START) -> list[tuple[date, float]]:
    """Build a daily close series, one point per calendar day from ``start``."""
    return [(start + timedelta(days=i), close) for i, close in enumerate(closes)]


def ramp(first: float, last: float, points: int = 29) -> list[float]:
    """A straight line of ``points`` closes from ``first`` to ``last``."""
    step = (last - first) / (points - 1)
    return [first + step * i for i in range(points)]


async def make_insight(db, **overrides) -> DeepInsight:
    fields = {
        "insight_type": "opportunity",
        "action": "BUY",
        "title": "Test thesis",
        "thesis": "Test thesis body",
        "primary_symbol": "TEST",
        "confidence": 0.8,
        "time_horizon": "swing",
        "entry_zone": None,
        "target_price": None,
        "stop_loss": None,
    }
    fields.update(overrides)
    insight = DeepInsight(**fields)
    db.add(insight)
    await db.commit()
    await db.refresh(insight)
    return insight


async def make_outcome(
    db,
    insight: DeepInsight,
    direction: str = "bullish",
    initial_price: float = 100.0,
    start: date = START,
    end: date = END,
    **overrides,
) -> InsightOutcome:
    fields = {
        "insight_id": insight.id,
        "tracking_status": TrackingStatus.TRACKING.value,
        "tracking_start_date": start,
        "tracking_end_date": end,
        "initial_price": initial_price,
        "current_price": initial_price,
        "predicted_direction": direction,
        "price_history": [{"date": start.isoformat(), "price": initial_price}],
    }
    fields.update(overrides)
    outcome = InsightOutcome(**fields)
    db.add(outcome)
    await db.commit()
    await db.refresh(outcome)
    return outcome


def stub_series(tracker: InsightOutcomeTracker, by_symbol: dict[str, list]) -> None:
    """Replace the loader so grading logic is tested without market data."""

    async def _load(symbol, start, end):
        return list(by_symbol.get(symbol.upper(), []))

    tracker._load_close_series = _load  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# A. Benchmark-relative success criterion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bullish_call_beating_one_percent_but_trailing_spy_is_not_validated(
    db_session,
):
    """+4% while SPY did +8% is negative alpha, and must not count as a win.

    The old rule ("bullish validated if raw return > +1%") scored exactly this
    case as a success, which is how a book of calls averaging +1.67% in a
    market that rose 6.6% was reported as a 30% hit rate.
    """
    insight = await make_insight(db_session)
    outcome = await make_outcome(db_session, insight)

    tracker = InsightOutcomeTracker(db_session)
    stub_series(
        tracker,
        {"TEST": series(ramp(100.0, 104.0)), "SPY": series(ramp(400.0, 432.0))},
    )

    graded = await tracker._evaluate_outcome(outcome, insight=insight)

    assert graded.actual_return_pct == pytest.approx(4.0, abs=0.01)
    # Clears the old raw-return bar...
    assert graded.actual_return_pct > 1.0
    # ...but loses to the benchmark over the identical window.
    assert graded.benchmark_return_pct == pytest.approx(8.0, abs=0.01)
    assert graded.alpha_pct == pytest.approx(-4.0, abs=0.01)
    assert graded.thesis_validated is False


@pytest.mark.asyncio
async def test_bullish_call_beating_spy_is_validated(db_session):
    insight = await make_insight(db_session)
    outcome = await make_outcome(db_session, insight)

    tracker = InsightOutcomeTracker(db_session)
    stub_series(
        tracker,
        {"TEST": series(ramp(100.0, 108.0)), "SPY": series(ramp(400.0, 408.0))},
    )

    graded = await tracker._evaluate_outcome(outcome, insight=insight)

    assert graded.alpha_pct == pytest.approx(6.0, abs=0.01)
    assert graded.thesis_validated is True
    assert graded.benchmark_symbol == "SPY"


@pytest.mark.asyncio
async def test_bearish_call_is_scored_on_alpha_not_raw_return(db_session):
    """A short that rose 4% while the market rose 12% was a good short."""
    insight = await make_insight(db_session, action="SELL")
    outcome = await make_outcome(db_session, insight, direction="bearish")

    tracker = InsightOutcomeTracker(db_session)
    stub_series(
        tracker,
        {"TEST": series(ramp(100.0, 104.0)), "SPY": series(ramp(400.0, 448.0))},
    )

    graded = await tracker._evaluate_outcome(outcome, insight=insight)

    assert graded.actual_return_pct == pytest.approx(4.0, abs=0.01)
    assert graded.alpha_pct == pytest.approx(-8.0, abs=0.01)
    assert graded.thesis_validated is True


@pytest.mark.asyncio
async def test_neutral_call_validates_inside_the_band_and_fails_outside(db_session):
    """HOLD/WATCH claims 'no meaningful divergence from the market'.

    The old rule required the stock to move <1% in absolute terms over the
    whole window, which is why HOLDs essentially never validated.
    """
    insight = await make_insight(db_session, action="HOLD")

    tracker = InsightOutcomeTracker(db_session)

    quiet = await make_outcome(db_session, insight, direction="neutral")
    stub_series(
        tracker,
        {"TEST": series(ramp(100.0, 106.0)), "SPY": series(ramp(400.0, 424.0))},
    )
    graded_quiet = await tracker._evaluate_outcome(quiet, insight=insight)
    # +6% raw would have failed the old |return| <= 1% rule outright.
    assert graded_quiet.actual_return_pct == pytest.approx(6.0, abs=0.01)
    assert graded_quiet.alpha_pct == pytest.approx(0.0, abs=0.01)
    assert graded_quiet.thesis_validated is True

    runaway = await make_outcome(db_session, insight, direction="neutral")
    tracker._series_cache.clear()
    stub_series(
        tracker,
        {"TEST": series(ramp(100.0, 120.0)), "SPY": series(ramp(400.0, 408.0))},
    )
    graded_runaway = await tracker._evaluate_outcome(runaway, insight=insight)
    assert graded_runaway.alpha_pct == pytest.approx(18.0, abs=0.01)
    assert graded_runaway.thesis_validated is False


# ---------------------------------------------------------------------------
# B. Grading time and price
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grades_on_close_at_tracking_end_date_not_at_run_time(db_session):
    """The window's own end date decides the price, not when the checker ran.

    Completed outcomes were graded on average 30.9 days late because
    ``final_price = current_price``, so a 20-day call was scored on ~51 days
    of drift. Here the series continues well past the window and collapses;
    the grade must ignore everything after ``tracking_end_date``.
    """
    insight = await make_insight(db_session)
    outcome = await make_outcome(db_session, insight)
    # A stale spot price recorded long after the window closed.
    outcome.current_price = 60.0

    # 29 points to the end date (100 -> 110), then a crash over the next 30.
    closes = ramp(100.0, 110.0) + ramp(110.0, 60.0, points=30)
    tracker = InsightOutcomeTracker(db_session)
    stub_series(
        tracker,
        {
            "TEST": series(closes),
            "SPY": series(ramp(400.0, 404.0) + ramp(404.0, 300.0, points=30)),
        },
    )

    graded = await tracker._evaluate_outcome(outcome, insight=insight)

    assert graded.evaluated_price_date == END
    assert graded.final_price == pytest.approx(110.0, abs=0.01)
    assert graded.actual_return_pct == pytest.approx(10.0, abs=0.01)
    # Neither the drifted spot price nor the post-window crash leaks in.
    assert graded.final_price != pytest.approx(60.0)
    assert graded.benchmark_return_pct == pytest.approx(1.0, abs=0.01)
    assert graded.thesis_validated is True
    assert graded.exit_reason == "window_end"


@pytest.mark.asyncio
async def test_check_outcomes_resolves_a_window_that_closed_long_ago(db_session):
    """Retroactive grading: no need for the app to be up on the expiry day.

    61 of 67 tracking rows were already past their end date and could only
    resolve if the process happened to be running on a scheduler slot.
    """
    start = date.today() - timedelta(days=90)
    end = start + timedelta(days=28)
    insight = await make_insight(db_session)
    await make_outcome(db_session, insight, start=start, end=end)

    tracker = InsightOutcomeTracker(db_session)
    stub_series(
        tracker,
        {
            "TEST": series(ramp(100.0, 112.0), start=start),
            "SPY": series(ramp(400.0, 408.0), start=start),
        },
    )

    updated = await tracker.check_outcomes()

    assert len(updated) == 1
    assert updated[0].tracking_status == TrackingStatus.COMPLETED.value
    assert updated[0].evaluated_price_date == end
    assert updated[0].alpha_pct == pytest.approx(10.0, abs=0.01)


@pytest.mark.asyncio
async def test_ungradeable_outcome_stays_tracking_for_retry(db_session):
    """No price data must not produce an invented grade."""
    insight = await make_insight(db_session)
    outcome = await make_outcome(db_session, insight)

    tracker = InsightOutcomeTracker(db_session)
    stub_series(tracker, {})

    graded = await tracker._evaluate_outcome(outcome, insight=insight)

    assert graded.exit_reason == "no_data"
    assert graded.tracking_status == TrackingStatus.TRACKING.value
    assert graded.thesis_validated is None


# ---------------------------------------------------------------------------
# C. Horizon-derived tracking window
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("horizon", "expected_days"),
    [
        ("immediate", 5),
        ("near_term", 10),
        ("short_term", 15),
        ("swing", 20),
        ("medium_term", 30),
        ("position", 60),
        ("long_term", 125),
    ],
)
def test_horizon_table_is_keyed_on_the_values_actually_stored(horizon, expected_days):
    """The old table was keyed on '1-2 weeks'/'2-4 weeks'/... — zero overlap
    with what the column contains, so every lookup fell through to 30 days."""
    assert InsightOutcomeTracker.resolve_horizon_days(horizon) == expected_days


def test_horizon_table_has_a_single_source_of_truth():
    """The grader and the eval harness diverged on medium_term (30 vs 63)
    because each kept its own copy. The table lives in analysis.horizons now;
    the tracker must delegate rather than hold a second copy."""
    from analysis import horizons, outcome_tracker

    assert horizons.HORIZON_TRADING_DAYS["medium_term"] == 30
    assert horizons.HORIZON_TRADING_DAYS["position"] == 60
    assert not hasattr(outcome_tracker, "_HORIZON_DAYS")
    assert InsightOutcomeTracker.resolve_horizon_days("medium_term") == (
        horizons.resolve_horizon_days("medium_term")
    )


@pytest.mark.asyncio
async def test_summary_never_emits_a_bare_hit_rate(db_session):
    """A hit rate must travel with what makes it interpretable.

    The same book scored 40.5% on stored 28-day windows and 32.9% on
    horizon-derived ones, and swings ~10 points more on the decision rule
    alone. A float on its own invites comparing two different measurements.
    """
    insight = await make_insight(db_session)
    await make_outcome(
        db_session,
        insight,
        tracking_status=TrackingStatus.COMPLETED.value,
        thesis_validated=True,
        alpha_pct=5.0,
        actual_return_pct=6.0,
    )

    summary = await InsightOutcomeTracker(db_session).get_tracking_summary()

    assert "success_rate" not in summary, "bare rate must not be emitted"
    block = summary["hit_rate"]
    for key in (
        "rate",
        "n",
        "population",
        "window_basis",
        "decision_rule",
        "benchmark_symbol",
        "alpha_threshold_pct",
    ):
        assert key in block, f"rate block missing {key}"
    assert block["n"] == 1
    assert block["rate"] == 1.0
    assert summary["direction_stats"]["bullish"]["n"] == 1


def test_a_shorter_horizon_admits_insights_a_longer_one_cannot_see():
    """Changing the horizon constant changes WHICH insights are gradeable, not
    just how they score, so metrics at two settings are not comparable unless
    restricted to the insights closed under both."""
    from analysis.horizons import is_window_closed

    start, today = date(2026, 6, 20), date(2026, 8, 16)

    # 30 bars -> 42 calendar days: closed. 63 bars -> 88 days: still open.
    assert is_window_closed(start, "medium_term", as_of=today) is True
    assert is_window_closed(start, "position", as_of=today) is False


@pytest.mark.parametrize("horizon", ["unknown", "", None, "next tuesday"])
def test_unmappable_horizon_refuses_to_produce_a_window(horizon):
    with pytest.raises(ValueError):
        InsightOutcomeTracker.resolve_horizon_days(horizon)


@pytest.mark.asyncio
async def test_medium_term_insight_gets_a_window_derived_from_its_horizon(db_session):
    """A medium_term insight must not silently get the hardcoded 20-day window."""
    insight = await make_insight(db_session, time_horizon="medium_term")

    tracker = InsightOutcomeTracker(db_session)
    tracker._yahoo_adapter.get_current_price = AsyncMock(
        return_value={"symbol": "TEST", "price": 100.0}
    )

    outcome = await tracker.start_tracking(
        insight_id=insight.id, symbol="TEST", predicted_direction="bullish",
    )

    assert outcome.horizon_days == 30
    window = (outcome.tracking_end_date - outcome.tracking_start_date).days
    assert window == 42
    # The hardcoded tracking_days=20 produced a 28-day window for everything.
    assert window != 28


@pytest.mark.asyncio
async def test_start_tracking_refuses_an_insight_with_an_unknown_horizon(db_session):
    insight = await make_insight(db_session, time_horizon="unknown")

    tracker = InsightOutcomeTracker(db_session)
    tracker._yahoo_adapter.get_current_price = AsyncMock(
        return_value={"symbol": "TEST", "price": 100.0}
    )

    with pytest.raises(ValueError, match="time_horizon"):
        await tracker.start_tracking(
            insight_id=insight.id, symbol="TEST", predicted_direction="bullish",
        )


# ---------------------------------------------------------------------------
# D. Intraperiod path persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_price_history_appends_are_persisted(db_session):
    """price_history was a plain JSON column mutated in place, so SQLAlchemy
    never marked it dirty — all 221 rows kept exactly one entry forever."""
    insight = await make_insight(db_session)
    outcome = await make_outcome(db_session, insight)
    outcome_id = outcome.id

    outcome.price_history.append({"date": "2026-01-06", "price": 101.0})
    await db_session.commit()

    db_session.expunge_all()
    reloaded = await db_session.get(InsightOutcome, outcome_id)

    assert len(reloaded.price_history) == 2
    assert reloaded.price_history[-1]["price"] == 101.0


@pytest.mark.asyncio
async def test_grading_records_the_full_path_and_real_extrema(db_session):
    """max_favorable/max_adverse are only meaningful if the path is observed."""
    insight = await make_insight(db_session)
    outcome = await make_outcome(db_session, insight)

    # Up to 115, back down to 92, ending at 103.
    closes = ramp(100.0, 115.0, 10) + ramp(115.0, 92.0, 10) + ramp(92.0, 103.0, 9)
    tracker = InsightOutcomeTracker(db_session)
    stub_series(tracker, {"TEST": series(closes), "SPY": series(ramp(400.0, 400.0))})

    graded = await tracker._evaluate_outcome(outcome, insight=insight)

    assert len(graded.price_history) == len(closes)
    assert graded.max_favorable_move == pytest.approx(15.0, abs=0.01)
    assert graded.max_adverse_move == pytest.approx(-8.0, abs=0.01)
    assert graded.intermediate_checkpoints
    assert "5d" in graded.intermediate_checkpoints


# ---------------------------------------------------------------------------
# E. The insight's own levels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_target_hit_before_stop_validates_the_thesis(db_session):
    insight = await make_insight(
        db_session, target_price="$120", stop_loss="$90",
    )
    outcome = await make_outcome(db_session, insight)

    # Runs to 125 first, then collapses to 80 — the target resolved it.
    closes = ramp(100.0, 125.0, 15) + ramp(125.0, 80.0, 14)
    tracker = InsightOutcomeTracker(db_session)
    stub_series(tracker, {"TEST": series(closes), "SPY": series(ramp(400.0, 440.0))})

    graded = await tracker._evaluate_outcome(outcome, insight=insight)

    assert graded.exit_reason == "target"
    assert graded.thesis_validated is True
    assert graded.target_triggered is True
    assert graded.final_price >= 120.0
    # Graded at the touch, not at the end of the window.
    assert graded.evaluated_price_date < END


@pytest.mark.asyncio
async def test_stop_hit_before_target_invalidates_the_thesis(db_session):
    insight = await make_insight(
        db_session, target_price="$120", stop_loss="$90",
    )
    outcome = await make_outcome(db_session, insight)

    # Breaks the stop first, then rallies through the target.
    closes = ramp(100.0, 85.0, 15) + ramp(85.0, 130.0, 14)
    tracker = InsightOutcomeTracker(db_session)
    stub_series(tracker, {"TEST": series(closes), "SPY": series(ramp(400.0, 400.0))})

    graded = await tracker._evaluate_outcome(outcome, insight=insight)

    assert graded.exit_reason == "stop"
    assert graded.thesis_validated is False
    assert graded.stop_triggered is True
    assert graded.final_price <= 90.0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # The blocking case: an indicator period read as the low of a range.
        ("$370 on confirmation of SMA_50", (370.0, 370.0)),
        ("$1100 within 6 months", (1100.0, 1100.0)),
        ("$780 (-13%)", (780.0, 780.0)),
        ("$880-$920", (880.0, 920.0)),
        ("$150-155", (150.0, 155.0)),
        ("$150 to $155", (150.0, 155.0)),
        ("$210 once RSI(14) clears 60", (210.0, 210.0)),
        ("$95 target after 3 months", (95.0, 95.0)),
        ("150-155", (150.0, 155.0)),
        ("$150.50", (150.5, 150.5)),
        (None, None),
        ("N/A", None),
    ],
)
def test_price_level_parser_ignores_indicators_timeframes_and_percentages(
    raw, expected,
):
    """The old parser took the first two numbers anywhere in the string and
    sorted them, so '$370 on confirmation of SMA_50' became (50, 370) with a
    midpoint of $210 and every level check against it was meaningless."""
    assert InsightOutcomeTracker._parse_price_range(raw) == expected


@pytest.mark.asyncio
async def test_level_checks_use_the_repaired_parser(db_session):
    """A $370 target must not be treated as a $50-$370 range."""
    insight = await make_insight(
        db_session, target_price="$370 on confirmation of SMA_50",
    )
    outcome = await make_outcome(db_session, insight, initial_price=300.0)

    tracker = InsightOutcomeTracker(db_session)
    # Never reaches 370, so no target trigger. Under the old parse the range
    # high was 370 too, but the low of 50 made the range nonsense for entries.
    stub_series(
        tracker,
        {"TEST": series(ramp(300.0, 340.0)), "SPY": series(ramp(400.0, 400.0))},
    )

    graded = await tracker._evaluate_outcome(outcome, insight=insight)

    assert graded.exit_reason == "window_end"
    assert graded.target_triggered is not True


# ---------------------------------------------------------------------------
# Local-first price loading
# ---------------------------------------------------------------------------


def test_a_series_with_a_month_wide_hole_is_rejected_despite_good_endpoints():
    """Endpoint checks alone are not coverage.

    The local price_history table is heavily gapped for recent months (SPY has
    no bars at all in July 2026), so a June->August window finds a bar at each
    end and looks complete while hiding a month-wide hole.
    """
    start, end = date(2026, 6, 20), date(2026, 8, 1)
    holed = (
        [(date(2026, 6, 20) + timedelta(days=i), 100.0) for i in range(8)]
        + [(date(2026, 7, 30) + timedelta(days=i), 120.0) for i in range(4)]
    )

    # Both endpoints are covered...
    assert holed[0][0] <= start + timedelta(days=5)
    assert holed[-1][0] >= end - timedelta(days=5)
    # ...but the series must still be rejected.
    assert InsightOutcomeTracker._series_is_usable(holed, start, end) is False

    dense = [
        (start + timedelta(days=i), 100.0) for i in range((end - start).days + 1)
    ]
    assert InsightOutcomeTracker._series_is_usable(dense, start, end) is True


@pytest.mark.asyncio
async def test_window_is_not_graded_when_the_series_stops_well_before_the_end(
    db_session,
):
    """A series ending weeks early must not be graded as if it reached the end."""
    insight = await make_insight(db_session)
    outcome = await make_outcome(db_session, insight)

    tracker = InsightOutcomeTracker(db_session)
    # Closes stop 20 days before the window end.
    stub_series(
        tracker,
        {
            "TEST": series(ramp(100.0, 104.0, 9)),
            "SPY": series(ramp(400.0, 404.0, 9)),
        },
    )

    graded = await tracker._evaluate_outcome(outcome, insight=insight)

    assert graded.exit_reason == "no_data"
    assert graded.tracking_status == TrackingStatus.TRACKING.value
    assert graded.thesis_validated is None


@pytest.mark.asyncio
async def test_benchmark_too_far_from_the_window_is_treated_as_unavailable(
    db_session,
):
    """A benchmark read weeks off the window would corrupt alpha, not fix it."""
    insight = await make_insight(db_session)
    outcome = await make_outcome(db_session, insight)

    tracker = InsightOutcomeTracker(db_session)
    # SPY data stops a month before the window closes.
    stub_series(
        tracker,
        {"TEST": series(ramp(100.0, 108.0)), "SPY": series(ramp(400.0, 401.0, 5))},
    )

    graded = await tracker._evaluate_outcome(outcome, insight=insight)

    assert graded.benchmark_return_pct is None
    assert "Benchmark unavailable" in graded.validation_notes
    # Falls back to raw return rather than inventing an alpha.
    assert graded.alpha_pct == pytest.approx(8.0, abs=0.01)


@pytest.mark.asyncio
async def test_close_series_reads_from_the_local_price_history_table(db_session):
    from models.price import PriceHistory
    from models.stock import Stock

    stock = Stock(symbol="LOCL", name="Local Co")
    db_session.add(stock)
    await db_session.commit()
    await db_session.refresh(stock)

    for i in range(10):
        db_session.add(
            PriceHistory(
                stock_id=stock.id,
                date=START + timedelta(days=i),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0 + i,
                volume=1_000,
            )
        )
    await db_session.commit()

    tracker = InsightOutcomeTracker(db_session)
    loaded = await tracker._load_local_close_series(
        "LOCL", START, START + timedelta(days=9)
    )

    assert len(loaded) == 10
    assert loaded[0] == (START, 100.0)
    assert loaded[-1][1] == 109.0
