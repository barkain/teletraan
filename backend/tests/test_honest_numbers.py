"""Tests for the two "honest numbers" changes.

Two things happened and each needs pinning down separately.

*The backfill* (``analysis/outcome_backfill.py``) re-grades COMPLETED outcomes
that were frozen under the retired rule -- flat +/-1% raw move over a hardcoded
20-day window -- through the current benchmark-relative grader. Those verdicts
are not decorative: ``ConfidenceAdjuster`` reads ``thesis_validated`` directly,
so they feed the live confidence blend. The tests here pin that the backfill
delegates to the real grader rather than reimplementing it, that a second run
changes nothing, and that it never touches a decision.

*The display change* (``analysis/action_base_rates.py`` and the routes that
serve it) replaces the model-stated per-idea confidence with the measured hit
rate for the action type. The tests pin the three properties that make that an
improvement rather than a relabelling: a rate never appears without its sample
size, an action with too few graded outcomes renders as unmeasured instead of as
a number, and the raw stated confidence is still stored and still served.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from analysis.action_base_rates import (
    MIN_GRADED_SAMPLE,
    ActionBaseRate,
    ActionBaseRates,
    load_action_base_rates,
)
from analysis.outcome_backfill import backfill_completed_outcomes
from analysis.outcome_tracker import InsightOutcomeTracker
from api.routes.reports import _build_report_html
from models.analysis_task import AnalysisTask
from models.deep_insight import DeepInsight
from models.insight_outcome import InsightOutcome, TrackingStatus

START = date(2026, 1, 5)

# "Today" for the backfill: far enough past every window below that they all
# count as closed, and fixed so the tests do not drift with the calendar.
AS_OF = date(2026, 12, 31)

# Window lengths in calendar days, via analysis/horizons.py: a horizon in
# trading days becomes trading_days * 7 / 5 calendar days. A stubbed price ramp
# has to span exactly the window it is graded over -- a longer ramp puts its
# stated endpoint outside the window and the grader reads a mid-ramp price.
SWING_DAYS = 28  # swing = 20 trading days
MEDIUM_DAYS = 42  # medium_term = 30 trading days
SWING_POINTS = SWING_DAYS + 1
MEDIUM_POINTS = MEDIUM_DAYS + 1

# Every field the grader owns. A backfill re-run must leave all of them alone.
GRADED_FIELDS = (
    "tracking_status",
    "tracking_end_date",
    "horizon_days",
    "final_price",
    "actual_return_pct",
    "benchmark_symbol",
    "benchmark_initial_price",
    "benchmark_final_price",
    "benchmark_return_pct",
    "alpha_pct",
    "evaluated_price_date",
    "exit_reason",
    "outcome_category",
    "thesis_validated",
    "validation_notes",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def series(closes: list[float], start: date = START) -> list[tuple[date, float]]:
    """A daily close series, one point per calendar day from ``start``."""
    return [(start + timedelta(days=i), close) for i, close in enumerate(closes)]


def ramp(first: float, last: float, points: int) -> list[float]:
    """A straight line of ``points`` closes from ``first`` to ``last``."""
    step = (last - first) / (points - 1)
    return [first + step * i for i in range(points)]


async def make_insight(db: AsyncSession, **overrides) -> DeepInsight:
    """A DeepInsight with the fields the grader and the base rates need."""
    fields = {
        "insight_type": "opportunity",
        "action": "BUY",
        "title": "Test thesis",
        "thesis": "Test thesis body",
        "primary_symbol": "TEST",
        "confidence": 0.87,
        "time_horizon": "medium_term",
        "target_price": None,
        "stop_loss": None,
    }
    fields.update(overrides)
    insight = DeepInsight(**fields)
    db.add(insight)
    await db.commit()
    await db.refresh(insight)
    return insight


async def make_retired_outcome(
    db: AsyncSession,
    insight: DeepInsight,
    *,
    thesis_validated: bool = True,
    start: date = START,
    window_days: int = 28,
    direction: str = "bullish",
) -> InsightOutcome:
    """An outcome in exactly the shape the retired grader left behind.

    COMPLETED with a verdict, but no ``alpha_pct``, no benchmark, no
    ``horizon_days``, no ``evaluated_price_date`` and no ``exit_reason`` -- and
    a window that came from the old hardcoded 20 trading days rather than from
    the insight's own horizon.
    """
    outcome = InsightOutcome(
        insight_id=insight.id,
        tracking_status=TrackingStatus.COMPLETED.value,
        tracking_start_date=start,
        tracking_end_date=start + timedelta(days=window_days),
        initial_price=100.0,
        current_price=104.0,
        final_price=104.0,
        actual_return_pct=4.0,
        predicted_direction=direction,
        thesis_validated=thesis_validated,
        outcome_category="SUCCESS" if thesis_validated else "FAILURE",
        # The retired-rule signature: every field below stays NULL.
        alpha_pct=None,
        benchmark_return_pct=None,
        benchmark_initial_price=None,
        benchmark_final_price=None,
        horizon_days=None,
        evaluated_price_date=None,
        exit_reason=None,
    )
    db.add(outcome)
    await db.commit()
    await db.refresh(outcome)
    return outcome


def stub_prices(monkeypatch, by_symbol: dict[str, list[tuple[date, float]]]) -> None:
    """Serve the grader a fixed price series instead of market data.

    Patches the tracker class rather than an instance because the backfill
    constructs its own tracker.
    """

    async def _load(self, symbol, start, end):  # noqa: ANN001
        points = by_symbol.get((symbol or "").upper(), [])
        return [p for p in points if start <= p[0] <= end]

    monkeypatch.setattr(InsightOutcomeTracker, "_load_close_series", _load)


def snapshot(outcome: InsightOutcome) -> dict:
    """The grader-owned fields of one row, for before/after comparison."""
    return {name: getattr(outcome, name) for name in GRADED_FIELDS}


async def seed_graded(
    db: AsyncSession, action: str, *, graded: int, validated: int
) -> None:
    """Insert ``graded`` COMPLETED outcomes for ``action``, ``validated`` of them wins."""
    for i in range(graded):
        insight = await make_insight(db, action=action, title=f"{action} {i}")
        db.add(
            InsightOutcome(
                insight_id=insight.id,
                tracking_status=TrackingStatus.COMPLETED.value,
                tracking_start_date=START,
                tracking_end_date=START + timedelta(days=42),
                initial_price=100.0,
                predicted_direction="bullish",
                thesis_validated=i < validated,
            )
        )
    await db.commit()


# ===========================================================================
# Task 1 -- the backfill
# ===========================================================================


@pytest.mark.asyncio
async def test_backfill_regrades_a_retired_verdict_through_the_alpha_rule(
    db_session, monkeypatch
):
    """+4% raw was a win under the old rule; against SPY's +8% it is not.

    This is the whole point of the backfill. The row goes in carrying
    ``thesis_validated=True`` with no benchmark anywhere on it, and must come
    out graded on alpha -- the same verdict ``check_outcomes`` would reach.
    """
    insight = await make_insight(db_session, time_horizon="swing")  # 20 trading days
    outcome = await make_retired_outcome(db_session, insight, thesis_validated=True)
    stub_prices(
        monkeypatch,
        {
            "TEST": series(ramp(100.0, 104.0, SWING_POINTS)),
            "SPY": series(ramp(400.0, 432.0, SWING_POINTS)),
        },
    )

    report = await backfill_completed_outcomes(db_session, as_of=AS_OF)

    await db_session.refresh(outcome)
    assert outcome.benchmark_return_pct == pytest.approx(8.0, abs=0.2)
    assert outcome.alpha_pct == pytest.approx(-4.0, abs=0.4)
    assert outcome.thesis_validated is False
    assert outcome.exit_reason == "window_end"
    assert outcome.evaluated_price_date is not None
    assert report.flipped_to_failed == 1
    assert report.regraded == 1


@pytest.mark.asyncio
async def test_backfill_is_idempotent(db_session, monkeypatch):
    """Two passes over unchanged prices leave byte-identical rows.

    The backfill is a repair run, not a scheduled job, so it will be run again
    by hand. If a second pass moved the numbers, nobody could tell a repair from
    a drift.
    """
    insight = await make_insight(db_session, time_horizon="swing")
    outcome = await make_retired_outcome(db_session, insight)
    stub_prices(
        monkeypatch,
        {
            "TEST": series(ramp(100.0, 110.0, SWING_POINTS)),
            "SPY": series(ramp(400.0, 404.0, SWING_POINTS)),
        },
    )

    first = await backfill_completed_outcomes(db_session, as_of=AS_OF)
    await db_session.refresh(outcome)
    after_first = snapshot(outcome)
    history_first = outcome.price_history
    checkpoints_first = outcome.intermediate_checkpoints

    second = await backfill_completed_outcomes(db_session, as_of=AS_OF)
    await db_session.refresh(outcome)

    assert snapshot(outcome) == after_first
    # price_history is replaced, not appended to -- the failure mode that would
    # make repeated runs grow the row without changing the verdict.
    assert outcome.price_history == history_first
    assert outcome.intermediate_checkpoints == checkpoints_first
    # And the second pass reports no verdict movement at all.
    assert second.flipped_to_validated == 0
    assert second.flipped_to_failed == 0
    assert second.verdict_cleared == 0
    assert second.window_corrected == 0
    assert second.regraded == first.regraded


@pytest.mark.asyncio
async def test_backfill_takes_the_window_from_the_insights_own_horizon(
    db_session, monkeypatch
):
    """A 28-day row on a medium_term insight is re-windowed to 30 trading days.

    The retired path graded everything on a hardcoded 20 trading days whatever
    the insight said. Correcting the window is what makes the re-grade mean
    anything: grading the same wrong window under a better rule would just be a
    different wrong answer.
    """
    insight = await make_insight(db_session, time_horizon="medium_term")
    outcome = await make_retired_outcome(db_session, insight, window_days=28)
    stub_prices(
        monkeypatch,
        {
            "TEST": series(ramp(100.0, 110.0, MEDIUM_POINTS)),
            "SPY": series(ramp(400.0, 404.0, MEDIUM_POINTS)),
        },
    )

    report = await backfill_completed_outcomes(db_session, as_of=AS_OF)

    await db_session.refresh(outcome)
    assert outcome.horizon_days == 30  # medium_term, from analysis/horizons.py
    assert outcome.tracking_end_date == START + timedelta(days=MEDIUM_DAYS)
    assert report.window_corrected == 1
    # Graded at the corrected end, not the old one.
    assert outcome.evaluated_price_date == START + timedelta(days=MEDIUM_DAYS)


@pytest.mark.asyncio
async def test_backfill_returns_a_row_whose_window_has_not_closed_to_tracking(
    db_session, monkeypatch
):
    """A row completed early goes back to TRACKING with its verdict cleared.

    Its true horizon has not elapsed, so any grade would score a partial window.
    Clearing rather than keeping the retired verdict matters because the
    confidence blend reads these rows.
    """
    insight = await make_insight(db_session, time_horizon="long_term")  # 125 days
    outcome = await make_retired_outcome(db_session, insight, window_days=28)
    stub_prices(monkeypatch, {"TEST": series(ramp(100.0, 110.0, 60))})

    report = await backfill_completed_outcomes(
        db_session, as_of=START + timedelta(days=40)
    )

    await db_session.refresh(outcome)
    assert outcome.tracking_status == TrackingStatus.TRACKING.value
    assert outcome.thesis_validated is None
    assert outcome.alpha_pct is None
    assert report.returned_to_tracking == 1
    assert report.verdict_cleared == 1


@pytest.mark.asyncio
async def test_backfill_hands_an_ungradeable_row_back_to_tracking(
    db_session, monkeypatch
):
    """No price series means no verdict, and the row must not be stranded.

    Leaving it COMPLETED with every graded field NULL would put it somewhere no
    pass ever looks again: ``check_outcomes`` only visits TRACKING rows. The
    price ETL back-fills gaps on its own, so the row can become gradeable later
    and needs to be somewhere that will notice.
    """
    insight = await make_insight(db_session, time_horizon="swing")
    outcome = await make_retired_outcome(db_session, insight)
    stub_prices(monkeypatch, {})  # the grader finds nothing for TEST

    report = await backfill_completed_outcomes(db_session, as_of=AS_OF)

    await db_session.refresh(outcome)
    assert report.ungraded_no_data == 1
    assert report.verdict_cleared == 1
    assert outcome.tracking_status == TrackingStatus.TRACKING.value
    assert outcome.thesis_validated is None
    assert outcome.alpha_pct is None
    # And an ungraded row contributes to no displayed rate.
    rates = await load_action_base_rates(db_session)
    assert rates.for_action("BUY").graded == 0


@pytest.mark.asyncio
async def test_backfill_skips_an_unmappable_horizon_rather_than_inventing_one(
    db_session, monkeypatch
):
    """No readable horizon means no window, and no window means no re-grade."""
    insight = await make_insight(db_session, time_horizon="")
    outcome = await make_retired_outcome(db_session, insight)
    stub_prices(monkeypatch, {"TEST": series(ramp(100.0, 110.0, 40))})

    report = await backfill_completed_outcomes(db_session, as_of=AS_OF)

    await db_session.refresh(outcome)
    assert report.skipped_unmappable_horizon == 1
    assert report.regraded == 0
    assert outcome.horizon_days is None


@pytest.mark.asyncio
async def test_backfill_never_touches_a_decision(db_session, monkeypatch):
    """The action, the symbol and the stated confidence come out untouched.

    The eval harness cohorts runs by ``pipeline_version``; a backfill that
    nudged an action would break the comparability the whole measurement rests
    on. Re-grading is allowed to change what we *say about* a call, never the
    call.
    """
    insight = await make_insight(
        db_session, action="STRONG_BUY", confidence=0.91, time_horizon="swing"
    )
    before = (insight.action, insight.primary_symbol, insight.confidence)
    await make_retired_outcome(db_session, insight)
    stub_prices(
        monkeypatch,
        {
            "TEST": series(ramp(100.0, 90.0, SWING_POINTS)),
            "SPY": series(ramp(400.0, 440.0, SWING_POINTS)),
        },
    )

    await backfill_completed_outcomes(db_session, as_of=AS_OF)

    fresh = await db_session.get(DeepInsight, insight.id)
    assert (fresh.action, fresh.primary_symbol, fresh.confidence) == before


# ===========================================================================
# Task 2 -- what the reader sees where the confidence number used to be
# ===========================================================================


@pytest.mark.asyncio
async def test_a_quoted_rate_always_carries_its_sample_size(db_session):
    """Every rendering of a rate names n. A bare percentage is the old mistake."""
    await seed_graded(db_session, "BUY", graded=MIN_GRADED_SAMPLE, validated=7)

    rates = await load_action_base_rates(db_session)
    record = rates.for_action("BUY")

    assert record.graded == MIN_GRADED_SAMPLE
    assert record.percent == 35
    assert record.available is True
    assert f"n={MIN_GRADED_SAMPLE}" in record.headline()
    assert "35%" in record.headline()
    # It is a statement about past calls, not about the idea on screen.
    assert "past BUY calls" in record.headline()
    assert "not a forecast" in record.to_dict()["caveat"]


@pytest.mark.asyncio
async def test_an_action_below_the_minimum_sample_renders_unavailable_not_zero(
    db_session,
):
    """Six graded HOLDs is not a 33% hit rate, it is no hit rate."""
    await seed_graded(db_session, "HOLD", graded=6, validated=2)

    rates = await load_action_base_rates(db_session)
    record = rates.for_action("HOLD")

    assert record.graded == 6
    assert record.rate is None
    assert record.percent is None
    assert record.available is False
    assert "Too few" in record.headline()
    assert "n=6" in record.headline()
    # Never zero, and never borrowed from the pooled rate.
    assert "0%" not in record.headline()
    assert "33%" not in record.headline()


@pytest.mark.asyncio
async def test_an_action_never_seen_reports_zero_sample_not_the_overall_rate(
    db_session,
):
    """A label with no graded outcomes must not inherit everyone else's rate."""
    await seed_graded(db_session, "BUY", graded=MIN_GRADED_SAMPLE, validated=10)

    rates = await load_action_base_rates(db_session)

    assert rates.overall.percent == 50
    unseen = rates.for_action("STRONG_SELL")
    assert unseen.graded == 0
    assert unseen.rate is None
    assert unseen.available is False


@pytest.mark.asyncio
async def test_ungradeable_outcomes_are_excluded_from_both_sides_of_the_rate(
    db_session,
):
    """A row the grader declined to score is not a loss."""
    await seed_graded(db_session, "BUY", graded=MIN_GRADED_SAMPLE, validated=10)
    ungraded_insight = await make_insight(db_session, action="BUY")
    db_session.add(
        InsightOutcome(
            insight_id=ungraded_insight.id,
            tracking_status=TrackingStatus.COMPLETED.value,
            tracking_start_date=START,
            tracking_end_date=START + timedelta(days=42),
            initial_price=100.0,
            predicted_direction="bullish",
            thesis_validated=None,
            exit_reason="no_data",
        )
    )
    await db_session.commit()

    rates = await load_action_base_rates(db_session)

    assert rates.for_action("BUY").graded == MIN_GRADED_SAMPLE
    assert rates.for_action("BUY").percent == 50


@pytest.mark.asyncio
async def test_base_rates_endpoint_serves_the_rate_with_its_sample_size(
    client: AsyncClient, db_session
):
    """The API carries n, the caveat and the method alongside every rate."""
    await seed_graded(db_session, "BUY", graded=MIN_GRADED_SAMPLE, validated=7)
    await seed_graded(db_session, "WATCH", graded=4, validated=1)

    resp = await client.get("/api/v1/knowledge/action-base-rates")

    assert resp.status_code == 200
    body = resp.json()
    assert body["min_sample"] == MIN_GRADED_SAMPLE
    assert "not a forecast" in body["caveat"]
    assert "SPY" in body["method"]

    buy = body["by_action"]["BUY"]
    assert buy["graded"] == MIN_GRADED_SAMPLE
    assert buy["percent"] == 35
    assert buy["available"] is True
    assert f"n={MIN_GRADED_SAMPLE}" in buy["headline"]

    watch = body["by_action"]["WATCH"]
    assert watch["rate"] is None
    assert watch["percent"] is None
    assert watch["available"] is False
    assert "Too few" in watch["headline"]


@pytest.mark.asyncio
async def test_deep_insight_response_carries_a_track_record_and_keeps_raw_confidence(
    client: AsyncClient, db_session
):
    """The API attaches the action's record and still serves the stated number.

    Both halves matter. The record is what clients render; the raw confidence
    stays on the wire and in the row because deleting it would destroy the
    ability to re-run the calibrator on future data.
    """
    await seed_graded(db_session, "BUY", graded=MIN_GRADED_SAMPLE, validated=7)
    insight = await make_insight(db_session, action="BUY", confidence=0.87)

    resp = await client.get(f"/api/v1/deep-insights/{insight.id}")

    assert resp.status_code == 200
    body = resp.json()
    record = body["track_record"]
    assert record["action"] == "BUY"
    assert record["graded"] == MIN_GRADED_SAMPLE
    assert record["percent"] == 35
    # The record is a property of the action, not of this idea: it does not
    # move with the insight's own stated confidence.
    assert record["percent"] != round(body["confidence"] * 100)
    assert body["confidence"] == pytest.approx(0.87)

    stored = (
        await db_session.execute(
            select(DeepInsight.confidence).where(DeepInsight.id == insight.id)
        )
    ).scalar_one()
    assert stored == pytest.approx(0.87)


@pytest.mark.asyncio
async def test_deep_insight_response_marks_a_thin_action_unavailable(
    client: AsyncClient, db_session
):
    """An action with too few graded calls arrives populated but unavailable.

    ``track_record: null`` would mean "the caller did not populate it", which a
    client renders as nothing. This is the different state: we looked, and the
    record cannot support a rate.
    """
    await seed_graded(db_session, "SELL", graded=5, validated=2)
    insight = await make_insight(db_session, action="SELL", confidence=0.77)

    resp = await client.get(f"/api/v1/deep-insights/{insight.id}")

    body = resp.json()
    record = body["track_record"]
    assert record is not None
    assert record["available"] is False
    assert record["rate"] is None
    assert record["graded"] == 5
    assert "Too few" in record["headline"]
    assert body["confidence"] == pytest.approx(0.77)


@pytest.mark.asyncio
async def test_html_report_shows_the_track_record_and_not_the_stated_confidence(
    db_session,
):
    """The rendered report prints the graded rate with n, and no 87%.

    87 is the insight's stated confidence. Its absence from the HTML is the
    assertion: any path that still rendered it would put a per-idea probability
    back on the page.
    """
    insight = await make_insight(
        db_session, action="BUY", confidence=0.87, supporting_evidence=[]
    )
    task = AnalysisTask(id="task-honest-numbers", status="completed")
    rates = ActionBaseRates(
        by_action={"BUY": ActionBaseRate("BUY", 116, 41)},
        overall=ActionBaseRate("ALL", 213, 70),
    )

    html = _build_report_html(task, [insight], rates)

    assert "BUY track record" in html
    assert "n=116" in html
    assert "35%" in html  # 41/116
    assert "87%" not in html
    assert "Avg Confidence" not in html
    assert "Confidence Distribution" not in html
    assert "not a forecast" in html


@pytest.mark.asyncio
async def test_html_report_says_so_when_nothing_has_been_graded(db_session):
    """With no graded record the report says it has none, and quotes no number."""
    insight = await make_insight(
        db_session, action="BUY", confidence=0.87, supporting_evidence=[]
    )
    task = AnalysisTask(id="task-honest-numbers", status="completed")

    html = _build_report_html(task, [insight], None)

    assert "Not enough data" in html
    assert "no graded calls yet" in html
    assert "too few graded calls" in html
    assert "87%" not in html
