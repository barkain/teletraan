"""Tests for the post-hoc confidence calibrator.

The synthetic fixtures below are constructed so the *right* answer is known
before the fitter runs:

* a perfectly calibrated book must come back near-unchanged -- a calibrator
  that "improves" an already-honest number is broken;
* a systematically overconfident book must be pulled toward the realised base
  rate, and by roughly the amount it was inflated;
* with nothing fitted, serving must be byte-identical to no calibrator at all.

Everything here is deterministic and offline.  No database, no network, no
price fetch: the fitter takes graded records and the records are built inline.
"""

from __future__ import annotations

import json
import math

import pytest

from analysis.confidence_calibrator import (
    ARTIFACT_PATH,
    CALIBRATION_VERSION,
    MIN_DISTINCT_DATES,
    MIN_OOS_BRIER_SKILL,
    MIN_PROBABILITY,
    MIN_RECORDS,
    Calibrator,
    IdentityCalibrator,
    IsotonicCalibrator,
    PlattCalibrator,
    _deterministic_permutation,
    brier,
    brier_skill,
    calibrate,
    calibrator_from_dict,
    chronological_holdout,
    cross_validate,
    date_grouped_folds,
    effective_sample,
    expected_calibration_error,
    extract_columns,
    fit_calibration,
    fit_isotonic,
    fit_platt,
    format_calibration_summary,
    leave_one_date_out_folds,
    load_artifact,
    load_calibrator,
    logit,
    reliability_curve,
    save_artifact,
    sigmoid,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _record(insight_id, confidence, correct, day, symbol="AAA"):
    """One graded call in the shape ``eval_insights`` emits."""
    return {
        "insight_id": insight_id,
        "symbol": symbol,
        "confidence": confidence,
        "correct": correct,
        "created_at": f"2026-01-{day:02d}T12:00:00",
    }


def _calibrated_book(levels=(0.2, 0.4, 0.6, 0.8), per_level=50, dates=25):
    """A book where a stated ``c`` really does come true ``c`` of the time.

    Hits are laid down deterministically (every k-th row) rather than sampled,
    so the realised frequency in each level equals the stated confidence
    exactly and the test has no seed to be lucky with.
    """
    records = []
    rid = 0
    for conf in levels:
        n_hits = round(conf * per_level)
        for i in range(per_level):
            rid += 1
            records.append(_record(
                rid,
                conf,
                # Spread the hits evenly through the level.
                (i * n_hits) % per_level < n_hits,
                (rid % dates) + 1,
                symbol=f"S{rid % 17}",
            ))
    return records


def _overconfident_book(per_level=60, dates=25):
    """Stated confidences of 0.7-0.95 against a flat ~40% realised hit rate.

    This is the shape the live corpus has: the number is high, varied, and
    unrelated to whether the call worked.
    """
    records = []
    rid = 0
    for conf in (0.70, 0.80, 0.90, 0.95):
        for i in range(per_level):
            rid += 1
            records.append(_record(
                rid, conf, (i % 5) < 2, (rid % dates) + 1, symbol=f"S{rid % 17}",
            ))
    return records


# ---------------------------------------------------------------------------
# Numeric primitives
# ---------------------------------------------------------------------------

def test_logit_and_sigmoid_round_trip():
    """``sigmoid(logit(p)) == p`` across the range, and the ends stay finite."""
    for p in (0.01, 0.1, 0.5, 0.9, 0.99):
        assert sigmoid(logit(p)) == pytest.approx(p, abs=1e-9)
    # 0 and 1 are squeezed rather than raising or returning +/-inf.
    assert math.isfinite(logit(0.0))
    assert math.isfinite(logit(1.0))


def test_brier_and_skill_are_the_textbook_quantities():
    """Hand-computed: predictions .5/.5 against labels 1/0 give Brier 0.25."""
    assert brier([0.5, 0.5], [1.0, 0.0]) == pytest.approx(0.25)
    # A model matching the reference exactly has zero skill.
    assert brier_skill([0.5, 0.5], [1.0, 0.0], [0.5, 0.5]) == pytest.approx(0.0)
    # A perfect model has skill 1.0.
    assert brier_skill([1.0, 0.0], [1.0, 0.0], [0.5, 0.5]) == pytest.approx(1.0)
    # A model worse than the reference has negative skill.
    assert brier_skill([0.9, 0.9], [1.0, 0.0], [0.5, 0.5]) < 0.0


def test_expected_calibration_error_is_zero_on_a_calibrated_book():
    """A book whose bins realise their stated rate has no calibration error."""
    conf, lab, _, _ = extract_columns(_calibrated_book())
    assert expected_calibration_error(conf, lab) == pytest.approx(0.0, abs=0.02)


def test_reliability_curve_bins_and_drops_empties():
    curve = reliability_curve([0.05, 0.15, 0.15, 0.95], [0.0, 1.0, 0.0, 1.0], n_bins=10)
    assert [row["bin"] for row in curve] == [0, 1, 9]
    assert curve[1]["n"] == 2
    assert curve[1]["hit_rate"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Requirement: a perfectly calibrated set is left near-unchanged
# ---------------------------------------------------------------------------

def test_platt_leaves_a_perfectly_calibrated_book_near_unchanged():
    """Slope ~1, intercept ~0, and every stated level maps back to itself."""
    conf, lab, _, _ = extract_columns(_calibrated_book())
    model = fit_platt(conf, lab)

    assert model.slope == pytest.approx(1.0, abs=0.15)
    assert model.intercept == pytest.approx(0.0, abs=0.15)
    for stated in (0.2, 0.4, 0.6, 0.8):
        assert model.apply(stated) == pytest.approx(stated, abs=0.04)


def test_isotonic_leaves_a_perfectly_calibrated_book_near_unchanged():
    conf, lab, _, _ = extract_columns(_calibrated_book())
    model = fit_isotonic(conf, lab)
    for stated in (0.2, 0.4, 0.6, 0.8):
        assert model.apply(stated) == pytest.approx(stated, abs=0.04)


def test_calibrating_a_calibrated_book_does_not_make_it_worse():
    """The Brier score must not degrade when there was nothing to fix."""
    conf, lab, _, _ = extract_columns(_calibrated_book())
    model = fit_platt(conf, lab)
    after = [model.apply(c) for c in conf]
    assert brier(after, lab) <= brier(conf, lab) + 1e-3


# ---------------------------------------------------------------------------
# Requirement: an overconfident set is pulled toward the base rate
# ---------------------------------------------------------------------------

def test_platt_pulls_an_overconfident_book_toward_the_base_rate():
    conf, lab, _, _ = extract_columns(_overconfident_book())
    base = sum(lab) / len(lab)
    assert base == pytest.approx(0.4, abs=0.02)

    model = fit_platt(conf, lab)
    for stated in (0.70, 0.80, 0.90, 0.95):
        adjusted = model.apply(stated)
        assert adjusted < stated, f"{stated} was not pulled down"
        assert adjusted == pytest.approx(base, abs=0.08), (
            f"{stated} -> {adjusted}, expected close to the base rate {base}"
        )


def test_calibration_removes_the_overconfidence_it_was_given():
    """ECE collapses and Brier improves once the map is applied."""
    conf, lab, _, _ = extract_columns(_overconfident_book())
    model = fit_platt(conf, lab)
    after = [model.apply(c) for c in conf]

    assert expected_calibration_error(conf, lab) > 0.35
    assert expected_calibration_error(after, lab) < 0.05
    assert brier(after, lab) < brier(conf, lab) - 0.2


def test_monotone_constraint_refuses_to_invert_the_map():
    """Anti-predictive input yields the base rate, never a negative slope.

    The book below has the labels running *against* confidence.  The
    unconstrained fit sees that and wants a negative slope -- which would turn
    a high stated confidence into a low probability, and so into a signal.  The
    constrained fit reports the base rate and claims nothing.
    """
    records = []
    rid = 0
    for conf, hit_in_five in ((0.9, 1), (0.7, 2), (0.5, 3), (0.3, 4)):
        for i in range(50):
            rid += 1
            records.append(_record(rid, conf, (i % 5) < hit_in_five, (rid % 25) + 1))
    conf, lab, _, _ = extract_columns(records)
    base = sum(lab) / len(lab)

    loose = fit_platt(conf, lab, monotone=False)
    assert loose.slope < 0, "fixture is not anti-predictive; the test proves nothing"

    tight = fit_platt(conf, lab, monotone=True)
    assert tight.slope == 0.0
    for stated in (0.3, 0.5, 0.7, 0.9):
        assert tight.apply(stated) == pytest.approx(base, abs=0.02)


# ---------------------------------------------------------------------------
# Isotonic mechanics
# ---------------------------------------------------------------------------

def test_isotonic_output_is_non_decreasing():
    conf, lab, _, _ = extract_columns(_overconfident_book())
    model = fit_isotonic(conf, lab)
    values = [model.apply(c / 100) for c in range(1, 100)]
    assert all(b >= a - 1e-12 for a, b in zip(values, values[1:]))


def test_isotonic_pools_violating_blocks():
    """0.6 realises 1.0 and 0.7 realises 0.0; PAVA must pool them to 0.5."""
    conf = [0.6, 0.6, 0.7, 0.7]
    lab = [1.0, 1.0, 0.0, 0.0]
    model = fit_isotonic(conf, lab)
    assert model.apply(0.6) == pytest.approx(0.5)
    assert model.apply(0.7) == pytest.approx(0.5)


def test_isotonic_pooling_ignores_the_order_ties_arrive_in():
    """Equal confidences are pooled before the sweep, so order cannot matter."""
    a = fit_isotonic([0.5, 0.5, 0.5, 0.9], [1.0, 0.0, 1.0, 0.0])
    b = fit_isotonic([0.5, 0.9, 0.5, 0.5], [0.0, 0.0, 1.0, 1.0])
    assert a.knots_x == b.knots_x
    assert a.knots_y == pytest.approx(b.knots_y)


def test_calibrated_probabilities_stay_inside_the_clamp():
    """No fitted map may emit 0.0 or 1.0 -- no finite sample supports either."""
    model = fit_isotonic([0.1, 0.1, 0.9, 0.9], [0.0, 0.0, 1.0, 1.0])
    assert model.apply(0.05) >= MIN_PROBABILITY
    assert model.apply(0.99) <= 1.0 - MIN_PROBABILITY


# ---------------------------------------------------------------------------
# Requirement: date-grouped splitting never leaks a date across the fence
# ---------------------------------------------------------------------------

def test_date_grouped_folds_never_share_a_date_between_train_and_test():
    records = _overconfident_book()
    _, _, dates, _ = extract_columns(records)

    for seed in range(10):
        folds = date_grouped_folds(dates, n_splits=5, seed=seed)
        assert folds, "no usable folds"
        for train_idx, test_idx in folds:
            train_dates = {dates[i] for i in train_idx}
            test_dates = {dates[i] for i in test_idx}
            assert not (train_dates & test_dates), (
                f"seed {seed}: dates {train_dates & test_dates} on both sides"
            )
            assert set(train_idx) & set(test_idx) == set()


def test_date_grouped_folds_cover_every_row_exactly_once():
    _, _, dates, _ = extract_columns(_overconfident_book())
    folds = date_grouped_folds(dates, n_splits=5, seed=3)
    seen = [i for _, test_idx in folds for i in test_idx]
    assert sorted(seen) == list(range(len(dates)))


def test_date_grouped_folds_are_reproducible_and_seed_dependent():
    _, _, dates, _ = extract_columns(_overconfident_book())
    assert date_grouped_folds(dates, 5, 7) == date_grouped_folds(dates, 5, 7)
    assert date_grouped_folds(dates, 5, 7) != date_grouped_folds(dates, 5, 8)


def test_deterministic_permutation_is_a_permutation():
    items = [f"2026-01-{d:02d}" for d in range(1, 31)]
    out = _deterministic_permutation(items, 4)
    assert sorted(out) == sorted(items)
    assert out != items  # 30 items; an identity shuffle would be a bug


def test_date_grouped_folds_rejects_a_single_split():
    with pytest.raises(ValueError, match="at least 2"):
        date_grouped_folds(["2026-01-01"], n_splits=1)


def test_leave_one_date_out_holds_out_exactly_one_date():
    _, _, dates, _ = extract_columns(_overconfident_book())
    folds = leave_one_date_out_folds(dates)
    assert len(folds) == len(set(dates))
    for train_idx, test_idx in folds:
        assert len({dates[i] for i in test_idx}) == 1
        assert not ({dates[i] for i in train_idx} & {dates[i] for i in test_idx})


def test_chronological_holdout_puts_every_test_date_after_every_train_date():
    _, _, dates, _ = extract_columns(_overconfident_book())
    train_idx, test_idx = chronological_holdout(dates, holdout_fraction=0.30)
    assert train_idx and test_idx
    assert max(dates[i] for i in train_idx) < min(dates[i] for i in test_idx)
    assert len(test_idx) >= 0.30 * len(dates)


def test_cross_validate_scores_against_the_training_base_rate():
    """A constant-base-rate model must score exactly zero skill against itself."""
    conf, lab, dates, _ = extract_columns(_overconfident_book())
    folds = leave_one_date_out_folds(dates)
    raw = cross_validate(conf, lab, dates, "raw", folds, "loo")
    platt = cross_validate(conf, lab, dates, "platt", folds, "loo")

    assert raw.n == platt.n == len(conf)
    # The overconfident book's raw number is much worse than the base rate.
    assert raw.skill_vs_base_rate < -0.2
    # Calibration recovers essentially all of that.
    assert platt.skill_vs_base_rate > raw.skill_vs_base_rate + 0.2


def test_cross_validate_rejects_an_unknown_method():
    conf, lab, dates, _ = extract_columns(_calibrated_book())
    with pytest.raises(ValueError, match="unknown method"):
        cross_validate(conf, lab, dates, "nonesuch", leave_one_date_out_folds(dates), "loo")


# ---------------------------------------------------------------------------
# Effective sample accounting
# ---------------------------------------------------------------------------

def test_effective_sample_reports_dates_symbols_and_the_worst_repeat():
    records = [
        _record(1, 0.7, True, 1, "GC=F"),
        _record(2, 0.7, False, 1, "GC=F"),
        _record(3, 0.7, True, 1, "GC=F"),
        _record(4, 0.7, False, 2, "NVDA"),
    ]
    _, _, dates, syms = extract_columns(records)
    sample = effective_sample(dates, syms)

    assert sample["rows"] == 4
    assert sample["distinct_dates"] == 2
    assert sample["distinct_symbols"] == 2
    assert sample["most_repeated_symbol"] == "GC=F"
    assert sample["most_repeated_symbol_n"] == 3
    assert sample["largest_date_cluster"] == 3
    assert sample["rows_per_date"] == pytest.approx(2.0)


def test_extract_columns_accepts_eval_record_objects():
    """The fitter must take the grader's dataclass, not only its dict form."""
    from analysis.eval_insights import EvalRecord

    rec = EvalRecord(
        insight_id=1, symbol="AAA", action="BUY", direction=1, confidence=0.8,
        created_at="2026-01-05T10:00:00", pipeline_version="v1", horizon_trading_days=30,
        entry_date="2026-01-06", exit_date="2026-02-17", entry_price=100.0,
        exit_price=110.0, symbol_return_pct=10.0, benchmark_return_pct=2.0,
        alpha_pct=8.0, correct=True, raw_correct=True, price_source="db",
    )
    conf, lab, dates, syms = extract_columns([rec])
    assert conf == [0.8]
    assert lab == [1.0]
    assert dates == ["2026-01-05"]
    assert syms == ["AAA"]


def test_extract_columns_refuses_a_record_with_no_confidence():
    with pytest.raises(ValueError, match="no confidence"):
        extract_columns([_record(1, None, True, 1)])


# ---------------------------------------------------------------------------
# Requirement: the identity fallback fires when nothing is fitted
# ---------------------------------------------------------------------------

def test_identity_calibrator_returns_its_input(tmp_path):
    model = IdentityCalibrator()
    for c in (0.0, 0.1, 0.5, 0.87, 1.0):
        assert model.apply(c) == c


def test_no_artifact_means_identity(tmp_path):
    missing = tmp_path / "not_written_yet.json"
    assert load_artifact(missing) is None
    assert isinstance(load_calibrator(missing), IdentityCalibrator)
    assert calibrate(0.83, missing) == 0.83


def test_an_inactive_artifact_means_identity(tmp_path):
    """A fit that failed its gate must never be served."""
    path = tmp_path / "cal.json"
    save_artifact({
        "calibration_version": CALIBRATION_VERSION,
        "active": False,
        "calibrator": {"kind": "platt", "slope": 0.0, "intercept": -2.0},
    }, path)
    assert isinstance(load_calibrator(path), IdentityCalibrator)
    assert calibrate(0.83, path) == 0.83


def test_a_stale_version_means_identity(tmp_path):
    path = tmp_path / "cal.json"
    save_artifact({
        "calibration_version": "0.0.1-from-an-older-build",
        "active": True,
        "calibrator": {"kind": "platt", "slope": 1.0, "intercept": 0.0},
    }, path)
    assert isinstance(load_calibrator(path), IdentityCalibrator)


def test_a_corrupt_artifact_means_identity_not_an_exception(tmp_path):
    """Serving must not fail because a diagnostic file was truncated."""
    path = tmp_path / "cal.json"
    path.write_text('{"calibration_version": "1.0.0", "active": tr')
    assert load_artifact(path) is None
    assert isinstance(load_calibrator(path), IdentityCalibrator)


def test_an_unusable_calibrator_body_means_identity(tmp_path):
    path = tmp_path / "cal.json"
    save_artifact({
        "calibration_version": CALIBRATION_VERSION,
        "active": True,
        "calibrator": {"kind": "quantum_regression"},
    }, path)
    assert isinstance(load_calibrator(path), IdentityCalibrator)


def test_the_shipped_repository_serves_identity():
    """Whatever is committed at ``data/confidence_calibration.json`` is inert.

    This is the assertion that makes the module safe to import from a live
    path: if a future refit ever flips ``active`` to true, this test fails and
    forces the change to be argued for rather than absorbed.
    """
    assert isinstance(load_calibrator(ARTIFACT_PATH), IdentityCalibrator)
    assert calibrate(0.83, ARTIFACT_PATH) == 0.83


def test_an_active_artifact_is_actually_served(tmp_path):
    """The fallback is not vacuous -- a passing artifact does get applied."""
    path = tmp_path / "cal.json"
    save_artifact({
        "calibration_version": CALIBRATION_VERSION,
        "active": True,
        "calibrator": {"kind": "platt", "slope": 0.5, "intercept": -0.5},
    }, path)
    model = load_calibrator(path)
    assert isinstance(model, PlattCalibrator)
    assert calibrate(0.9, path) == pytest.approx(model.apply(0.9))
    assert calibrate(0.9, path) != pytest.approx(0.9)


# ---------------------------------------------------------------------------
# Requirement: the fitted artifact round-trips
# ---------------------------------------------------------------------------

def test_platt_artifact_round_trips(tmp_path):
    conf, lab, _, _ = extract_columns(_overconfident_book())
    original = fit_platt(conf, lab)

    path = tmp_path / "cal.json"
    save_artifact({
        "calibration_version": CALIBRATION_VERSION,
        "active": True,
        "calibrator": original.to_dict(),
    }, path)

    restored = load_calibrator(path)
    assert isinstance(restored, PlattCalibrator)
    for stated in (0.1, 0.35, 0.7, 0.95):
        assert restored.apply(stated) == pytest.approx(original.apply(stated), abs=1e-5)


def test_isotonic_artifact_round_trips(tmp_path):
    conf, lab, _, _ = extract_columns(_overconfident_book())
    original = fit_isotonic(conf, lab)

    path = tmp_path / "cal.json"
    save_artifact({
        "calibration_version": CALIBRATION_VERSION,
        "active": True,
        "calibrator": original.to_dict(),
    }, path)

    restored = load_calibrator(path)
    assert isinstance(restored, IsotonicCalibrator)
    for stated in (0.05, 0.5, 0.75, 0.99):
        assert restored.apply(stated) == pytest.approx(original.apply(stated), abs=1e-5)


def test_calibrator_from_dict_rejects_an_unknown_kind():
    with pytest.raises(ValueError, match="unknown calibrator kind"):
        calibrator_from_dict({"kind": "hand_wave"})


def test_full_artifact_is_json_serializable_and_reloads(tmp_path):
    artifact = fit_calibration(_overconfident_book(), grouped_seeds=3)
    path = tmp_path / "cal.json"
    save_artifact(artifact, path)
    assert json.loads(path.read_text()) == json.loads(json.dumps(artifact))


# ---------------------------------------------------------------------------
# The fit and its gate
# ---------------------------------------------------------------------------

def test_fit_records_the_label_rule_and_effective_sample():
    artifact = fit_calibration(_overconfident_book(), grouped_seeds=3)
    assert artifact["label_rule"] == "sign_of_alpha"
    assert "alpha_threshold_pct=0.0" in artifact["label_rule_description"]
    assert artifact["n"] == 240
    assert artifact["effective_sample"]["distinct_dates"] == 25
    assert artifact["calibration_version"] == CALIBRATION_VERSION
    assert artifact["gate"]["min_oos_brier_skill"] == MIN_OOS_BRIER_SKILL


def test_fit_refuses_to_run_below_the_minimum_sample():
    """Too few rows or too few dates and the fit is not attempted at all."""
    tiny = [_record(i, 0.7, i % 2 == 0, (i % 3) + 1) for i in range(1, 20)]
    artifact = fit_calibration(tiny)
    assert artifact["active"] is False
    assert "insufficient data" in artifact["verdict"]
    assert artifact["calibrator"] == {"kind": "identity"}
    assert "out_of_sample" not in artifact


def test_fit_refuses_when_rows_are_plentiful_but_dates_are_not():
    """200 rows across 4 days is 4 market moves, not 200 observations."""
    many = [_record(i, 0.7, i % 2 == 0, (i % 4) + 1) for i in range(1, 201)]
    assert len(many) > MIN_RECORDS
    artifact = fit_calibration(many)
    assert artifact["active"] is False
    assert f"{MIN_DISTINCT_DATES}" in artifact["verdict"]


def test_a_book_with_real_signal_clears_the_gate():
    """The gate is not unpassable: separable confidence earns positive skill.

    Low-confidence calls fail and high-confidence calls succeed, consistently
    across dates.  A calibrator that could not ship on this fixture would be
    rejecting everything, and the failing verdict on live data would carry no
    information.
    """
    records = []
    rid = 0
    for conf, hit_in_ten in ((0.2, 1), (0.4, 3), (0.6, 6), (0.9, 9)):
        for i in range(60):
            rid += 1
            records.append(_record(rid, conf, (i % 10) < hit_in_ten, (rid % 25) + 1))

    artifact = fit_calibration(records, grouped_seeds=3)
    assert artifact["active"] is True, artifact["verdict"]
    assert "clears the gate" in artifact["verdict"]
    loo = artifact["out_of_sample"]["platt"]["leave_one_date_out"]
    assert loo["skill_vs_base_rate"] >= MIN_OOS_BRIER_SKILL


def test_an_informationless_book_fails_the_gate():
    """Varied confidence with a flat hit rate must not ship a calibrator.

    This is the live corpus in miniature.  The best available map is "report
    the base rate", which is not worth two parameters, so the artifact stays
    inactive and serving stays on identity.
    """
    records = []
    rid = 0
    for conf in (0.35, 0.55, 0.75, 0.90):
        for i in range(60):
            rid += 1
            records.append(_record(rid, conf, (i % 5) < 2, (rid % 25) + 1))

    artifact = fit_calibration(records, grouped_seeds=3)
    assert artifact["active"] is False
    assert "carries no measurable information" in artifact["verdict"]
    assert isinstance(calibrator_from_dict(artifact["calibrator"]), Calibrator)


def test_fit_measures_every_method_including_the_unconstrained_diagnostic():
    artifact = fit_calibration(_overconfident_book(), grouped_seeds=3)
    methods = artifact["out_of_sample"]
    assert set(methods) == {"raw", "platt", "platt_unconstrained", "isotonic"}
    for blocks in methods.values():
        assert set(blocks) == {
            "leave_one_date_out", "chronological_holdout", "grouped_kfold",
        }
    # The unconstrained fit is reported but never selected.
    assert artifact["diagnostics"]["selected_method"] in {"platt", "isotonic"}


def test_fit_reports_the_mapping_in_plain_terms():
    artifact = fit_calibration(_overconfident_book(), grouped_seeds=3)
    mapping = artifact["mapping"]
    assert "0.80" in mapping
    # The overconfident book must map 0.80 well below 0.80.
    assert mapping["0.80"] < 0.60


def test_summary_formats_without_raising_for_both_verdicts():
    passing = fit_calibration(_overconfident_book(), grouped_seeds=2)
    text = format_calibration_summary(passing)
    assert "Confidence calibration" in text
    assert "verdict" in text

    tiny = fit_calibration([_record(i, 0.7, True, 1) for i in range(1, 10)])
    assert "insufficient data" in format_calibration_summary(tiny)
