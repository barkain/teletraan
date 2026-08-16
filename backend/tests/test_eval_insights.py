"""Tests for the insight evaluation harness.

Every metric assertion below is hand-computed and written out in the docstring
or a comment, because the whole point of the harness is that its numbers can be
trusted without re-deriving them.  Fixtures are synthetic price paths with
returns chosen to be exact in floating point.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from analysis.eval_insights import (
    _merge_series,
    EvalRecord,
    ExclusionLedger,
    base_rate_brier,
    brier_score,
    brier_skill_score,
    build_record,
    calibration_slope,
    close_on_or_before,
    cohort_metrics,
    direction_for_action,
    entry_exit_indices,
    expected_calibration_error,
    hit_rate,
    horizon_trading_days,
    load_insight_eval,
    mean_alpha,
    needs_topup,
    pipeline_version_for,
    raw_hit_rate,
    reliability_curve,
    run_insight_eval,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_record(
    confidence: float,
    correct: bool,
    *,
    alpha: float = 1.0,
    direction: int = 1,
    action: str = "BUY",
    month: str = "2026-05",
    symbol: str = "AAA",
    pipeline_version: str = "v1-discovery",
    insight_id: int = 1,
    raw_correct: bool | None = None,
) -> EvalRecord:
    """Build an ``EvalRecord`` directly, so metric tests never touch price logic.

    ``alpha`` is the magnitude; the sign is set from ``correct`` and ``direction``
    so the record is internally consistent with its own label.
    """
    signed = abs(alpha) * direction * (1 if correct else -1)
    return EvalRecord(
        insight_id=insight_id,
        symbol=symbol,
        action=action,
        direction=direction,
        confidence=confidence,
        created_at=f"{month}-15T12:00:00",
        pipeline_version=pipeline_version,
        horizon_trading_days=21,
        entry_date=f"{month}-16",
        exit_date=f"{month}-28",
        entry_price=100.0,
        exit_price=100.0 + signed,
        symbol_return_pct=signed,
        benchmark_return_pct=0.0,
        alpha_pct=signed,
        correct=correct,
        raw_correct=correct if raw_correct is None else raw_correct,
        price_source="price_history",
    )


def flat_series(start: date, closes: list[float]) -> list[tuple[date, float]]:
    """Consecutive daily bars starting at ``start`` (no weekend logic needed)."""
    return [(start + timedelta(days=i), c) for i, c in enumerate(closes)]


# ---------------------------------------------------------------------------
# Action / horizon / version resolution
# ---------------------------------------------------------------------------


def test_direction_for_action_maps_longs_shorts_and_rejects_neutral():
    assert direction_for_action("BUY") == 1
    assert direction_for_action("STRONG_BUY") == 1
    assert direction_for_action("BUY_MORE") == 1
    assert direction_for_action("SELL") == -1
    assert direction_for_action("STRONG_SELL") == -1
    # HOLD/WATCH make no directional claim; unknown vocabulary is also None.
    assert direction_for_action("HOLD") is None
    assert direction_for_action("WATCH") is None
    assert direction_for_action("TELEPORT") is None
    assert direction_for_action(None) is None
    # Case and whitespace tolerant.
    assert direction_for_action("  buy  ") == 1


def test_horizon_trading_days_resolves_through_the_shared_table():
    """Values come from analysis.horizons -- the table shared with the grader."""
    assert horizon_trading_days("medium_term") == 30
    assert horizon_trading_days("short_term") == 15
    assert horizon_trading_days("immediate") == 5
    assert horizon_trading_days("swing") == 20
    assert horizon_trading_days("position") == 60
    assert horizon_trading_days("long_term") == 125
    assert horizon_trading_days("SWING") == 20
    # Decorated value still resolves via substring match.
    assert horizon_trading_days("medium_term (3 months)") == 30


def test_horizon_trading_days_refuses_to_invent_a_window():
    """Unresolvable horizons return None; the caller excludes rather than guesses."""
    assert horizon_trading_days("unknown") is None
    assert horizon_trading_days(None) is None
    assert horizon_trading_days("") is None
    assert horizon_trading_days("whenever") is None


def test_horizon_overrides_apply_only_to_the_named_key():
    """Sensitivity variants substitute one key without disturbing the rest."""
    assert horizon_trading_days("medium_term", {"medium_term": 63}) == 63
    assert horizon_trading_days("swing", {"medium_term": 63}) == 20
    # An override cannot resurrect an unresolvable horizon it does not name.
    assert horizon_trading_days("unknown", {"medium_term": 63}) is None


def test_eval_harness_and_grader_share_one_horizon_table():
    """Regression guard: the two must never diverge again.

    They previously disagreed on five of seven values, which made their
    measurements silently incomparable.
    """
    from analysis import eval_insights, horizons
    from analysis.outcome_tracker import InsightOutcomeTracker

    # Both sides must route through the shared module, not a private copy.
    assert eval_insights.HORIZON_TRADING_DAYS is horizons.HORIZON_TRADING_DAYS

    # And they must agree value-for-value on every label the engines write.
    for label in ("immediate", "near_term", "short_term", "swing",
                  "medium_term", "position", "long_term"):
        assert (
            horizon_trading_days(label)
            == InsightOutcomeTracker.resolve_horizon_days(label)
            == horizons.HORIZON_TRADING_DAYS[label]
        ), f"harness and grader disagree on {label!r}"

    # The arbitrated value, pinned so a silent revert is caught.
    assert horizons.HORIZON_TRADING_DAYS["medium_term"] == 30


def test_pipeline_version_prefers_an_explicit_discovery_context_stamp():
    stamped = pipeline_version_for(
        datetime(2026, 2, 5), {"pipeline_version": "v9-experimental"}
    )
    assert stamped == "v9-experimental"


def test_pipeline_version_falls_back_to_created_at_era():
    # Boundaries: 2026-02-01 v1, 2026-04-18 v2, 2026-05-03 v3, 2026-06-05 v4.
    assert pipeline_version_for(datetime(2026, 1, 31)) == "unknown"
    assert pipeline_version_for(datetime(2026, 2, 1)) == "v1-discovery"
    assert pipeline_version_for(datetime(2026, 4, 17)) == "v1-discovery"
    assert pipeline_version_for(datetime(2026, 4, 18)) == "v2-signals"
    assert pipeline_version_for(datetime(2026, 5, 4)) == "v3-portfolio-quant"
    assert pipeline_version_for(datetime(2026, 6, 30)) == "v4-news-sentiment"
    # An empty/blank stamp must not shadow the era fallback.
    assert pipeline_version_for(datetime(2026, 5, 4), {"pipeline_version": "  "}) == (
        "v3-portfolio-quant"
    )


# ---------------------------------------------------------------------------
# Window selection / look-ahead
# ---------------------------------------------------------------------------


def test_entry_bar_is_strictly_after_created_at_no_lookahead():
    """An insight written on the 3rd must not be entered at the 3rd's close."""
    dates = [date(2026, 5, d) for d in range(1, 11)]
    entry_idx, exit_idx = entry_exit_indices(dates, date(2026, 5, 3), horizon_bars=5)
    assert dates[entry_idx] == date(2026, 5, 4)  # next bar, not same-day
    assert dates[exit_idx] == date(2026, 5, 9)   # 5 bars later


def test_entry_lag_advances_further_when_requested():
    dates = [date(2026, 5, d) for d in range(1, 11)]
    entry_idx, _ = entry_exit_indices(
        dates, date(2026, 5, 3), horizon_bars=2, entry_lag=3
    )
    assert dates[entry_idx] == date(2026, 5, 6)


def test_window_is_none_when_horizon_has_not_elapsed():
    dates = [date(2026, 5, d) for d in range(1, 6)]  # only 5 bars
    assert entry_exit_indices(dates, date(2026, 5, 3), horizon_bars=21) is None


def test_window_is_none_when_no_bar_exists_after_created_at():
    dates = [date(2026, 5, d) for d in range(1, 6)]
    assert entry_exit_indices(dates, date(2026, 5, 5), horizon_bars=1) is None


def test_close_on_or_before_uses_last_prior_bar_and_respects_gap_limit():
    series = [(date(2026, 5, 1), 10.0), (date(2026, 5, 4), 12.0)]
    assert close_on_or_before(series, date(2026, 5, 4)) == 12.0
    assert close_on_or_before(series, date(2026, 5, 5)) == 12.0  # 1-day gap, fine
    # A 20-day gap is a data hole, not a price.
    assert close_on_or_before(series, date(2026, 5, 24)) is None
    assert close_on_or_before(series, date(2026, 4, 30)) is None


# ---------------------------------------------------------------------------
# Record construction / alpha arithmetic
# ---------------------------------------------------------------------------


def test_build_record_computes_alpha_as_symbol_minus_benchmark():
    """Symbol 100 -> 110 is +10%; SPY 400 -> 412 is +3%; alpha is exactly 7.0."""
    start = date(2026, 5, 1)
    symbol_series = flat_series(start, [99.0, 100.0, 105.0, 110.0])
    bench_series = flat_series(start, [399.0, 400.0, 406.0, 412.0])

    record, reason = build_record(
        insight_id=7,
        symbol="AAA",
        action="BUY",
        direction=1,
        confidence=0.8,
        created_at=datetime(2026, 5, 1, 10, 0),
        pipeline_version="v1-discovery",
        horizon_bars=2,
        symbol_series=symbol_series,
        benchmark_series=bench_series,
    )

    assert reason is None
    assert record is not None
    assert record.entry_date == "2026-05-02"  # strictly after created_at
    assert record.entry_price == 100.0
    assert record.exit_date == "2026-05-04"
    assert record.exit_price == 110.0
    assert record.symbol_return_pct == pytest.approx(10.0)
    assert record.benchmark_return_pct == pytest.approx(3.0)
    assert record.alpha_pct == pytest.approx(7.0)
    assert record.correct is True
    assert record.raw_correct is True


def test_long_that_rises_less_than_the_benchmark_is_a_miss():
    """+4% against a +6% tape is negative alpha: correct=False but raw_correct=True."""
    start = date(2026, 5, 1)
    symbol_series = flat_series(start, [99.0, 100.0, 104.0])
    bench_series = flat_series(start, [399.0, 400.0, 424.0])

    record, _ = build_record(
        insight_id=1, symbol="AAA", action="BUY", direction=1, confidence=0.9,
        created_at=datetime(2026, 5, 1), pipeline_version="v1", horizon_bars=1,
        symbol_series=symbol_series, benchmark_series=bench_series,
    )
    assert record.symbol_return_pct == pytest.approx(4.0)
    assert record.benchmark_return_pct == pytest.approx(6.0)
    assert record.alpha_pct == pytest.approx(-2.0)
    assert record.correct is False
    assert record.raw_correct is True


def test_short_call_is_correct_when_alpha_is_negative():
    """A SELL is right when the name underperforms, even if it rose in absolute terms."""
    start = date(2026, 5, 1)
    symbol_series = flat_series(start, [99.0, 100.0, 102.0])
    bench_series = flat_series(start, [399.0, 400.0, 420.0])

    record, _ = build_record(
        insight_id=2, symbol="BBB", action="SELL", direction=-1, confidence=0.7,
        created_at=datetime(2026, 5, 1), pipeline_version="v1", horizon_bars=1,
        symbol_series=symbol_series, benchmark_series=bench_series,
    )
    assert record.alpha_pct == pytest.approx(-3.0)
    assert record.correct is True       # short + negative alpha = hit
    assert record.raw_correct is False  # price rose, so the raw label misses it


def test_build_record_reports_horizon_not_elapsed_and_entry_bar_missing():
    start = date(2026, 5, 1)
    series = flat_series(start, [100.0, 101.0, 102.0])
    bench = flat_series(start, [400.0, 401.0, 402.0])

    _, reason = build_record(
        insight_id=3, symbol="AAA", action="BUY", direction=1, confidence=0.6,
        created_at=datetime(2026, 5, 1), pipeline_version="v1", horizon_bars=60,
        symbol_series=series, benchmark_series=bench,
    )
    assert reason == "horizon_not_elapsed"

    _, reason = build_record(
        insight_id=4, symbol="AAA", action="BUY", direction=1, confidence=0.6,
        created_at=datetime(2026, 6, 1), pipeline_version="v1", horizon_bars=1,
        symbol_series=series, benchmark_series=bench,
    )
    assert reason == "entry_bar_missing"


def test_window_gapped_rejects_a_calendar_stretched_window():
    """A 5-bar horizon must not be measured across a 6-month hole.

    Bars exist on 2026-01-01..05 and then not again until July: counting bars
    alone would call July minus January a "5-day return".
    """
    series = [(date(2026, 1, d), 100.0 + d) for d in range(1, 6)]
    series += [(date(2026, 7, d), 200.0 + d) for d in range(1, 6)]
    bench = [(date(2026, 1, d), 400.0) for d in range(1, 6)]
    bench += [(date(2026, 7, d), 400.0) for d in range(1, 6)]

    _, reason = build_record(
        insight_id=6, symbol="AAA", action="BUY", direction=1, confidence=0.8,
        created_at=datetime(2026, 1, 1), pipeline_version="v1", horizon_bars=5,
        symbol_series=series, benchmark_series=bench,
    )
    assert reason == "window_gapped"


def test_needs_topup_flags_missing_stale_and_gapped_series():
    start, end = date(2026, 5, 1), date(2026, 5, 20)
    dense = [(date(2026, 5, d), 100.0) for d in range(1, 25)]

    assert needs_topup([], start, end) is True                 # never ingested
    assert needs_topup(dense, start, end) is False             # good coverage
    # Stops before the window closes.
    assert needs_topup(dense[:10], start, end) is True
    # Interior hole: 2026-05-05 jumps to 2026-05-19.
    holey = [(date(2026, 5, d), 100.0) for d in list(range(1, 6)) + list(range(19, 25))]
    assert needs_topup(holey, start, end) is True
    # A weekend-sized gap is normal market closure, not a hole.
    weekend = [(date(2026, 5, d), 100.0) for d in range(1, 25) if d not in (9, 10)]
    assert needs_topup(weekend, start, end) is False


def test_merge_series_prefers_the_local_close_on_shared_dates():
    local = [(date(2026, 5, 1), 100.0), (date(2026, 5, 2), 101.0)]
    remote = [(date(2026, 5, 2), 999.0), (date(2026, 5, 3), 102.0)]
    merged = _merge_series(local, remote)

    assert merged == [
        (date(2026, 5, 1), 100.0),
        (date(2026, 5, 2), 101.0),  # local wins over the vendor's restatement
        (date(2026, 5, 3), 102.0),  # remote fills the date the ETL never wrote
    ]


def test_build_record_reports_missing_benchmark_bar():
    start = date(2026, 5, 1)
    series = flat_series(start, [100.0, 101.0, 102.0])
    # Benchmark stops months earlier -> no bar within the gap tolerance.
    bench = [(date(2026, 1, 5), 400.0)]

    _, reason = build_record(
        insight_id=5, symbol="AAA", action="BUY", direction=1, confidence=0.6,
        created_at=datetime(2026, 5, 1), pipeline_version="v1", horizon_bars=1,
        symbol_series=series, benchmark_series=bench,
    )
    assert reason == "no_benchmark_bar"


# ---------------------------------------------------------------------------
# Hit rate and alpha
# ---------------------------------------------------------------------------


def test_hit_rate_and_mean_alpha_hand_computed():
    """3 hits of 5 = 0.6; signed alphas +2,+4,+6,-3,-1 -> mean 8/5 = 1.6."""
    records = [
        make_record(0.7, True, alpha=2.0),
        make_record(0.7, True, alpha=4.0),
        make_record(0.7, True, alpha=6.0),
        make_record(0.7, False, alpha=3.0),
        make_record(0.7, False, alpha=1.0),
    ]
    assert hit_rate(records) == pytest.approx(0.6)
    assert mean_alpha(records) == pytest.approx(1.6)


def test_mean_alpha_is_direction_signed_so_shorts_are_not_penalised():
    """A short with alpha -5 contributes +5 to mean signed alpha."""
    shorts = [make_record(0.7, True, alpha=5.0, direction=-1)]
    assert shorts[0].alpha_pct == pytest.approx(-5.0)
    assert mean_alpha(shorts) == pytest.approx(5.0)


def test_raw_hit_rate_diverges_from_adjusted_hit_rate():
    records = [
        make_record(0.7, False, raw_correct=True),
        make_record(0.7, False, raw_correct=True),
        make_record(0.7, True, raw_correct=True),
        make_record(0.7, False, raw_correct=False),
    ]
    assert hit_rate(records) == pytest.approx(0.25)
    assert raw_hit_rate(records) == pytest.approx(0.75)


def test_empty_cohort_metrics_are_none_not_zero():
    assert hit_rate([]) is None
    assert mean_alpha([]) is None
    assert brier_score([]) is None
    assert expected_calibration_error([]) is None
    # An empty cohort still declares its basis rather than emitting a bare n.
    assert cohort_metrics([]) == {"n": 0, "basis": None}
    assert cohort_metrics([], basis="sign_of_alpha|thr=0.0%") == {
        "n": 0, "basis": "sign_of_alpha|thr=0.0%",
    }


# ---------------------------------------------------------------------------
# Brier / skill
# ---------------------------------------------------------------------------


def test_brier_score_hand_computed():
    """preds 0.8/0.6/0.9 vs outcomes 1/0/1 -> (0.04 + 0.36 + 0.01)/3 = 0.136667."""
    records = [
        make_record(0.8, True),
        make_record(0.6, False),
        make_record(0.9, True),
    ]
    assert brier_score(records) == pytest.approx(0.41 / 3)


def test_base_rate_brier_equals_p_times_one_minus_p():
    """Climatology Brier for base rate p is exactly p(1-p): (2/3)(1/3) = 0.22222."""
    records = [
        make_record(0.8, True),
        make_record(0.6, False),
        make_record(0.9, True),
    ]
    assert hit_rate(records) == pytest.approx(2 / 3)
    assert base_rate_brier(records) == pytest.approx((2 / 3) * (1 / 3))


def test_brier_skill_score_hand_computed():
    """1 - 0.136667/0.222222 = 0.385."""
    records = [
        make_record(0.8, True),
        make_record(0.6, False),
        make_record(0.9, True),
    ]
    expected = 1.0 - (0.41 / 3) / ((2 / 3) * (1 / 3))
    assert brier_skill_score(records) == pytest.approx(expected)
    assert brier_skill_score(records) == pytest.approx(0.385, abs=1e-3)


def test_brier_skill_score_is_zero_for_a_constant_base_rate_forecast():
    """Stating the base rate every time carries no information: skill exactly 0."""
    records = [make_record(0.5, True) for _ in range(5)]
    records += [make_record(0.5, False) for _ in range(5)]
    assert hit_rate(records) == pytest.approx(0.5)
    assert brier_score(records) == pytest.approx(0.25)
    assert brier_skill_score(records) == pytest.approx(0.0)


def test_confident_and_wrong_scores_the_worst_possible_brier():
    records = [make_record(1.0, False) for _ in range(10)]
    assert brier_score(records) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Calibration: ECE and the reliability curve
# ---------------------------------------------------------------------------


def _perfectly_calibrated() -> list[EvalRecord]:
    """One decile bin per 0.05..0.95, 20 records each, hits exactly matching conf.

    conf 0.05 -> 1/20 correct, 0.15 -> 3/20, ... 0.95 -> 19/20.  Every bin's
    realised hit rate equals its mean confidence exactly, so ECE must be 0.
    """
    records: list[EvalRecord] = []
    for tenth in range(10):
        conf = tenth / 10 + 0.05
        n_correct = round(conf * 20)
        for i in range(20):
            records.append(make_record(conf, i < n_correct, insight_id=len(records)))
    return records


def test_perfectly_calibrated_set_scores_ece_zero():
    records = _perfectly_calibrated()
    assert len(records) == 200
    assert expected_calibration_error(records) == pytest.approx(0.0, abs=1e-12)


def test_perfectly_calibrated_curve_is_monotonically_increasing():
    curve = reliability_curve(_perfectly_calibrated())
    hits = [row["hit_rate"] for row in curve]
    assert hits == sorted(hits)
    assert all(abs(row["gap"]) < 1e-9 for row in curve)
    # Slope of hit rate on confidence is exactly 1 when calibration is perfect.
    assert calibration_slope(curve) == pytest.approx(1.0)


def test_inverted_calibration_scores_ece_exactly_half():
    """Hit rate = 1 - confidence in every bin.

    Gaps are |c - (1-c)| = |2c-1| over c in {0.05..0.95}:
    0.9,0.7,0.5,0.3,0.1,0.1,0.3,0.5,0.7,0.9 -> mean 0.5 with equal bin weights.
    """
    records: list[EvalRecord] = []
    for tenth in range(10):
        conf = tenth / 10 + 0.05
        n_correct = round((1 - conf) * 20)
        for i in range(20):
            records.append(make_record(conf, i < n_correct, insight_id=len(records)))
    assert expected_calibration_error(records) == pytest.approx(0.5, abs=1e-9)
    # And the curve points the wrong way, which is the failure mode being tracked.
    assert calibration_slope(reliability_curve(records)) == pytest.approx(-1.0)


def test_maximally_miscalibrated_set_scores_ece_one():
    """Total confidence, total failure: the worst score the metric can take."""
    records = [make_record(1.0, False) for _ in range(50)]
    assert expected_calibration_error(records) == pytest.approx(1.0)

    # And the mirror image: no confidence, everything right.
    records = [make_record(0.0, True) for _ in range(50)]
    assert expected_calibration_error(records) == pytest.approx(1.0)


def test_ece_is_sample_weighted_not_bin_weighted():
    """90 records at conf 0.9 hitting 0.9, plus 10 at conf 0.1 hitting 1.0.

    Bin gaps are 0.0 and 0.9.  Sample-weighted ECE = (90/100)*0 + (10/100)*0.9
    = 0.09.  An unweighted mean over bins would wrongly give 0.45.
    """
    records = [make_record(0.9, i < 81, insight_id=i) for i in range(90)]
    records += [make_record(0.1, True, insight_id=100 + i) for i in range(10)]
    assert expected_calibration_error(records) == pytest.approx(0.09, abs=1e-9)


def test_reliability_curve_bins_by_decile_and_reports_shares():
    records = [make_record(0.05, True), make_record(0.65, False), make_record(0.65, True)]
    records.append(make_record(1.0, True))  # confidence 1.0 lands in the top bin
    curve = reliability_curve(records)

    bins = {row["bin"]: row for row in curve}
    assert set(bins) == {"0.0-0.1", "0.6-0.7", "0.9-1.0"}
    assert bins["0.6-0.7"]["n"] == 2
    assert bins["0.6-0.7"]["hit_rate"] == pytest.approx(0.5)
    assert bins["0.6-0.7"]["share"] == pytest.approx(0.5)
    assert bins["0.9-1.0"]["mean_confidence"] == pytest.approx(1.0)
    # Empty bins are omitted rather than reported as 0% hit rate.
    assert "0.3-0.4" not in bins


def test_reliability_curve_respects_bin_count():
    records = [make_record(0.05, True), make_record(0.30, True), make_record(0.80, False)]
    assert len(reliability_curve(records, n_bins=2)) == 2   # [0,0.5) and [0.5,1]
    assert len(reliability_curve(records, n_bins=10)) == 3


# ---------------------------------------------------------------------------
# Cohort assembly
# ---------------------------------------------------------------------------


def test_cohort_metrics_reports_the_full_block():
    records = [
        make_record(0.8, True, alpha=2.0),
        make_record(0.6, False, alpha=4.0),
        make_record(0.9, True, alpha=6.0),
    ]
    block = cohort_metrics(records)
    assert block["n"] == 3
    assert block["hit_rate"] == pytest.approx(2 / 3, abs=1e-4)
    # signed alphas +2, -4, +6 -> mean 4/3 = 1.333, median 2.0
    assert block["mean_alpha_pct"] == pytest.approx(1.333, abs=1e-3)
    assert block["median_alpha_pct"] == pytest.approx(2.0)
    assert block["brier"] == pytest.approx(0.1367, abs=1e-4)
    assert block["base_rate_brier"] == pytest.approx(0.2222, abs=1e-4)
    assert block["mean_confidence"] == pytest.approx(0.7667, abs=1e-4)
    assert "reliability_curve" in block



# ---------------------------------------------------------------------------
# Exclusion accounting
# ---------------------------------------------------------------------------


def test_exclusion_ledger_counts_and_samples_ids():
    ledger = ExclusionLedger()
    for i in range(20):
        ledger.record("horizon_not_elapsed", i)
    ledger.record("no_price_series", 99)
    ledger.record("non_directional_action")

    assert ledger.total == 22
    payload = ledger.to_dict()
    assert payload["total_excluded"] == 22
    assert payload["by_reason"]["horizon_not_elapsed"] == 20
    assert payload["by_reason"]["no_price_series"] == 1
    assert payload["by_reason"]["non_directional_action"] == 1
    # Sample ids are capped so a snapshot cannot balloon.
    assert len(payload["sample_insight_ids"]["horizon_not_elapsed"]) == 12
    # A reason with no id recorded still counts but contributes no sample.
    assert "non_directional_action" not in payload["sample_insight_ids"]
    # Reasons that never fired are omitted entirely.
    assert "invalid_price" not in payload["by_reason"]


# ---------------------------------------------------------------------------
# End-to-end against a synthetic database
# ---------------------------------------------------------------------------


async def _seed(db: AsyncSession) -> None:
    """Seed SPY plus three symbols and six insights covering every code path.

    Seven bars, so a 5-bar ("immediate") horizon closes: the insight is created
    on bar 0, entry is bar 1, exit is bar 6.  Entry/exit prices are chosen so
    the arithmetic below is exact:
      SPY  400 -> 404 (+1.0%)
      WINR 100 -> 110 (+10%)  -> alpha +9.0, a BUY hit
      LOSR 100 ->  95 (-5%)   -> alpha -6.0, a BUY miss / a SELL hit
    """
    from models.deep_insight import DeepInsight
    from models.price import PriceHistory
    from models.stock import Stock

    paths = {
        "SPY": [400.0, 400.0, 401.0, 402.0, 403.0, 403.0, 404.0],
        "WINR": [100.0, 100.0, 102.0, 104.0, 106.0, 108.0, 110.0],
        "LOSR": [100.0, 100.0, 99.0, 98.0, 97.0, 96.0, 95.0],
    }
    start = date(2026, 5, 4)
    for symbol, closes in paths.items():
        stock = Stock(symbol=symbol, name=symbol, is_active=True)
        db.add(stock)
        await db.flush()
        for offset, close in enumerate(closes):
            db.add(PriceHistory(
                stock_id=stock.id, date=start + timedelta(days=offset),
                open=close, high=close, low=close, close=close, volume=1000,
            ))

    created = datetime(2026, 5, 4, 9, 0)

    def insight(**kwargs) -> DeepInsight:
        base = dict(
            insight_type="opportunity", title="t", thesis="th",
            time_horizon="immediate", created_at=created, updated_at=created,
        )
        base.update(kwargs)
        return DeepInsight(**base)

    db.add_all([
        # Graded: WINR beats SPY -> hit.
        insight(action="BUY", primary_symbol="WINR", confidence=0.9),
        # Graded: LOSR lags SPY -> a BUY miss.
        insight(action="BUY", primary_symbol="LOSR", confidence=0.7),
        # Graded: the same underperformance is a SELL hit.
        insight(action="SELL", primary_symbol="LOSR", confidence=0.6),
        # Excluded: no directional claim.
        insight(action="HOLD", primary_symbol="WINR", confidence=0.8),
        # Excluded: pseudo-symbol.
        insight(action="BUY", primary_symbol="PORTFOLIO", confidence=0.8),
        # Excluded: symbol has no price history at all.
        insight(action="BUY", primary_symbol="GHOST", confidence=0.8),
        # Excluded: horizon runs past the end of the price data.
        insight(action="BUY", primary_symbol="WINR", confidence=0.8,
                time_horizon="long_term"),
    ])
    await db.commit()


@pytest.mark.asyncio
async def test_run_insight_eval_end_to_end(db_session: AsyncSession, tmp_path, monkeypatch):
    """The whole harness on a seeded DB: exact metrics and exact exclusions."""
    import analysis.eval_insights as module

    snapshot_path = tmp_path / "insight_eval.json"
    monkeypatch.setattr(module, "EVAL_SNAPSHOT_PATH", snapshot_path)
    monkeypatch.setattr(module, "EVAL_HISTORY_PATH", tmp_path / "insight_eval_history.jsonl")

    await _seed(db_session)
    snapshot = await run_insight_eval(
        db_session, save=True, allow_network=False,
    )

    overall = snapshot["overall"]
    # 3 of 7 insights are gradeable; 2 of those 3 are hits (WINR BUY, LOSR SELL).
    assert snapshot["universe"]["insights_total"] == 7
    assert snapshot["universe"]["directional_candidates"] == 5
    assert overall["n"] == 3
    assert overall["hit_rate"] == pytest.approx(2 / 3, abs=1e-4)
    # Signed alphas: +9.0 (WINR BUY), -6.0 (LOSR BUY), +6.0 (LOSR SELL) -> mean 3.0
    assert overall["mean_alpha_pct"] == pytest.approx(3.0, abs=1e-3)
    # Raw hit rate differs: WINR up (hit), LOSR down under BUY (miss), LOSR SELL (hit).
    assert overall["raw_hit_rate"] == pytest.approx(2 / 3, abs=1e-4)

    exclusions = snapshot["exclusions"]["by_reason"]
    assert exclusions["non_directional_action"] == 1  # HOLD
    assert exclusions["non_tradeable_symbol"] == 1    # PORTFOLIO
    assert exclusions["no_price_series"] == 1         # GHOST
    assert exclusions["horizon_not_elapsed"] == 1     # long_term
    assert snapshot["exclusions"]["total_excluded"] == 4

    # Cohorts split the way the seed implies.
    assert snapshot["by_action"]["BUY"]["n"] == 2
    assert snapshot["by_action"]["SELL"]["n"] == 1
    assert snapshot["by_direction"]["long"]["n"] == 2
    assert snapshot["by_direction"]["short"]["n"] == 1
    assert snapshot["by_month"]["2026-05"]["n"] == 3
    assert snapshot["by_pipeline_version"]["v3-portfolio-quant"]["n"] == 3

    # Snapshot lands on disk in the documented shape, and is round-trippable.
    assert snapshot_path.exists()
    written = json.loads(snapshot_path.read_text())
    assert written["harness_version"] == module.HARNESS_VERSION
    assert written["overall"]["n"] == 3
    assert len(written["records"]) == 3
    assert {r["symbol"] for r in written["records"]} == {"WINR", "LOSR"}

    # The history log gets one compact row per run.
    history_lines = (tmp_path / "insight_eval_history.jsonl").read_text().splitlines()
    assert len(history_lines) == 1
    assert json.loads(history_lines[0])["hit_rate"] == overall["hit_rate"]


@pytest.mark.asyncio
async def test_every_cohort_carries_the_decision_rule_that_produced_it(
    db_session: AsyncSession,
):
    """No hit rate may ship without the rule that produced it.

    The decision rule is worth ~10 points on identical data -- more than the
    horizon constant -- so a cohort block lifted out of context and quoted
    against the outcome grader's rate would be a straight category error.
    """
    await _seed(db_session)
    snapshot = await run_insight_eval(db_session, save=False)

    rule = snapshot["params"]["decision_rule"]
    assert rule["alpha_threshold_pct"] == 0.0
    assert rule["models_stop_target"] is False
    assert rule["benchmark_symbol"] == "SPY"
    assert "created_at" in rule["entry_basis"]
    assert "decision_rule" in snapshot["params"]["not_comparable_to"]

    expected = snapshot["overall"]["basis"]
    assert expected and "thr=0.0%" in expected and "no_levels" in expected

    # Every cohort in every breakdown, not just the headline.
    for group in ("by_pipeline_version", "by_month", "by_action", "by_direction"):
        for name, block in snapshot[group].items():
            assert block.get("basis") == expected, f"{group}.{name} lost its basis"


@pytest.mark.asyncio
async def test_snapshot_carries_a_like_for_like_horizon_sensitivity_block(
    db_session: AsyncSession, tmp_path, monkeypatch,
):
    """The snapshot must expose how much the horizon choice moves the headline.

    Critically, the comparison is on the insights graded under BOTH settings.
    A shorter horizon closes sooner and admits newer insights, so comparing
    full samples would conflate "which insights became gradeable" with "how
    good the analysis was".
    """
    import analysis.eval_insights as module

    monkeypatch.setattr(module, "EVAL_SNAPSHOT_PATH", tmp_path / "s.json")
    monkeypatch.setattr(module, "EVAL_HISTORY_PATH", tmp_path / "h.jsonl")

    await _seed(db_session)
    snapshot = await run_insight_eval(db_session, save=False)

    sens = snapshot["horizon_sensitivity"]
    assert "medium_term_63" in sens["variants"]
    block = sens["variants"]["medium_term_63"]
    assert block["overrides"] == {"medium_term": 63}

    # Both sides of the like-for-like comparison cover the same insights.
    shipped = block["comparable_intersection"]["shipped"]
    variant = block["comparable_intersection"]["variant"]
    assert shipped["n"] == variant["n"] == block["intersection_n"]
    # The intersection can never exceed either full sample it was drawn from.
    full = block["full_samples_NOT_comparable"]
    assert block["intersection_n"] <= full["shipped"]["n"]
    assert block["intersection_n"] <= full["variant"]["n"]

    # The non-comparable rows must carry their own warning, so a reader who
    # lands on them without the surrounding note still sees it.
    assert "not be compared" in full["why"]
    assert "comparable_intersection" in sens["note"]

    # The seed uses only `immediate` and `long_term`, which the override does
    # not touch, so shipped and variant must agree exactly here.
    assert shipped == variant
    assert block["admitted_only_by_shipped"]["n"] == 0


@pytest.mark.asyncio
async def test_horizon_sensitivity_moves_when_medium_term_insights_are_present(
    db_session: AsyncSession,
):
    """With a `medium_term` call in the sample, the two settings must diverge.

    Guards against a sensitivity block that silently reports "no difference"
    because the override was never actually applied.
    """
    from models.deep_insight import DeepInsight
    from models.price import PriceHistory
    from models.stock import Stock

    # 50 bars: entry is bar 1, so a 30-bar window exits at bar 31 (closed) but
    # a 63-bar window would need bar 64 (absent).  The variant drops the call.
    paths = {"SPY": [400.0] * 50, "WINR": [100.0 + i for i in range(50)]}
    start = date(2026, 1, 1)
    for symbol, closes in paths.items():
        stock = Stock(symbol=symbol, name=symbol, is_active=True)
        db_session.add(stock)
        await db_session.flush()
        for offset, close in enumerate(closes):
            db_session.add(PriceHistory(
                stock_id=stock.id, date=start + timedelta(days=offset),
                open=close, high=close, low=close, close=close, volume=1000,
            ))
    created = datetime(2026, 1, 1, 9, 0)
    db_session.add(DeepInsight(
        insight_type="opportunity", action="BUY", title="t", thesis="th",
        primary_symbol="WINR", confidence=0.8, time_horizon="medium_term",
        created_at=created, updated_at=created,
    ))
    await db_session.commit()

    snapshot = await run_insight_eval(db_session, save=False)
    block = snapshot["horizon_sensitivity"]["variants"]["medium_term_63"]

    assert snapshot["overall"]["n"] == 1                             # graded at 30 bars
    assert block["full_samples_NOT_comparable"]["variant"]["n"] == 0  # not at 63 bars
    assert block["intersection_n"] == 0                              # nothing in common

    # The confound is surfaced as data, not just prose: the harness names the
    # record that only the shipped setting can see, and which cohort it lands in.
    assert block["admitted_only_by_shipped"]["n"] == 1
    # Seeded at 2026-01-01, before the first era boundary, hence "unknown".
    assert block["admitted_only_by_shipped"]["by_pipeline_version"] == {"unknown": 1}
    assert "admits newer insights" in snapshot["horizon_sensitivity"]["note"]


@pytest.mark.asyncio
async def test_run_insight_eval_is_repeatable(db_session: AsyncSession, tmp_path, monkeypatch):
    """Two runs over unchanged data produce identical metrics -- no hidden randomness."""
    import analysis.eval_insights as module

    monkeypatch.setattr(module, "EVAL_SNAPSHOT_PATH", tmp_path / "s.json")
    monkeypatch.setattr(module, "EVAL_HISTORY_PATH", tmp_path / "h.jsonl")

    await _seed(db_session)
    first = await run_insight_eval(db_session, save=False)
    second = await run_insight_eval(db_session, save=False)
    assert first["overall"] == second["overall"]
    assert first["exclusions"] == second["exclusions"]
    assert first["records"] == second["records"]


@pytest.mark.asyncio
async def test_run_insight_eval_errors_without_a_benchmark(db_session: AsyncSession):
    """No SPY means no alpha; the harness says so instead of inventing a zero."""
    from models.deep_insight import DeepInsight
    from models.price import PriceHistory
    from models.stock import Stock

    stock = Stock(symbol="WINR", name="WINR", is_active=True)
    db_session.add(stock)
    await db_session.flush()
    for offset in range(5):
        db_session.add(PriceHistory(
            stock_id=stock.id, date=date(2026, 5, 4) + timedelta(days=offset),
            open=100.0, high=100.0, low=100.0, close=100.0 + offset, volume=10,
        ))
    created = datetime(2026, 5, 4, 9, 0)
    db_session.add(DeepInsight(
        insight_type="opportunity", action="BUY", title="t", thesis="th",
        primary_symbol="WINR", confidence=0.8, time_horizon="immediate",
        created_at=created, updated_at=created,
    ))
    await db_session.commit()

    snapshot = await run_insight_eval(db_session, save=False, allow_network=False)
    assert "error" in snapshot
    assert "SPY" in snapshot["error"]


def test_load_insight_eval_returns_none_when_never_run(tmp_path, monkeypatch):
    import analysis.eval_insights as module

    monkeypatch.setattr(module, "EVAL_SNAPSHOT_PATH", tmp_path / "absent.json")
    assert load_insight_eval() is None
