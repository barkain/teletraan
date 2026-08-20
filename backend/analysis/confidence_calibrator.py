"""Post-hoc calibration of stated confidence against realised outcomes.

This module maps a *stated* confidence onto the frequency with which calls at
that confidence actually came true.  It changes nothing about a decision -- not
which symbol, not which action, not the ranking -- only the probability
attached to a decision that has already been made.  That is the entire reason
it is defensible at the sample sizes available here: learning a policy from a
few hundred overlapping outcomes would be overfitting, whereas fitting a
one- or two-parameter monotone map is a far weaker ask.

Labels come from :mod:`analysis.eval_insights`, which grades each directional
call on benchmark-relative alpha over the insight's own horizon.  They are
*not* taken from ``InsightOutcome.thesis_validated``: as of this writing every
completed row in that table predates the grader rebuild and still carries the
old raw-return rule, so calibrating against it would calibrate against a
measurement the project has already retired.

Two methods are fitted and compared:

* **Platt scaling** -- ``sigmoid(a * logit(p) + b)``.  Two parameters, fitted
  by Newton/IRLS on log-loss.  Optionally constrained to ``a >= 0`` so the map
  can never invert; when the unconstrained fit wants a negative slope the
  constrained answer is ``a = 0``, i.e. "the input carries no information,
  report the base rate", which is the honest degenerate case rather than a
  spurious inversion.
* **Isotonic regression** -- pool-adjacent-violators.  Non-parametric and more
  flexible, but at these sample sizes it fits fold noise; it is fitted so the
  comparison can be made on numbers rather than on assertion.

Neither depends on scikit-learn, which is not a dependency of this backend and
is not worth adding for ~60 lines of arithmetic.

Nothing here is applied to live confidence unless a fitted artifact exists
*and* records a passing out-of-sample gate.  :func:`load_calibrator` returns
:class:`IdentityCalibrator` otherwise, so a fresh clone behaves exactly as it
does today.  See :func:`fit_calibration` for the gate.

Refit with::

    cd backend && uv run python -m analysis.confidence_calibrator --refit
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"
ARTIFACT_PATH = _DATA_DIR / "confidence_calibration.json"

# Bumped whenever the fitting procedure or the gate changes.  Artifacts written
# under a different version are not comparable and are refused at load time.
CALIBRATION_VERSION = "1.0.0"

# Probabilities are squeezed off the open interval's ends before any logit, and
# every emitted probability is clamped to the same range.  A calibrated 0.0 is
# a claim no finite sample can support.
_EPS = 1e-6
MIN_PROBABILITY = 0.02
MAX_PROBABILITY = 0.98

DEFAULT_BINS = 10

# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
# A calibrator ships only if it beats, out of sample, the one thing that is
# free: quoting the training base rate on every call.  Beating the *raw stated
# confidence* is not the bar -- a constant would clear that -- because the
# question is whether the stated number carries information worth preserving.
#
# The margin is deliberately above zero.  A fit that merely ties the base rate
# has learned nothing and would spend two parameters saying so, and the
# date-clustered bootstrap at n~200 cannot separate a tie from a small loss.
MIN_OOS_BRIER_SKILL = 0.01

# Below these the fit is not attempted at all.  Distinct dates matter far more
# than rows: calls made on the same day share one market move, so 200 rows
# across 30 dates carry closer to 30 independent observations than 200.
MIN_RECORDS = 100
MIN_DISTINCT_DATES = 20


# ---------------------------------------------------------------------------
# Small numeric helpers (pure Python -- no numpy/scipy needed at serve time)
# ---------------------------------------------------------------------------

def _clip(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else (hi if x > hi else x)


def logit(p: float) -> float:
    """Log-odds of ``p``, with the ends squeezed so the result stays finite."""
    q = _clip(float(p), _EPS, 1.0 - _EPS)
    return math.log(q / (1.0 - q))


def sigmoid(z: float) -> float:
    """Numerically stable logistic."""
    if z >= 0.0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


# ---------------------------------------------------------------------------
# Calibrators
# ---------------------------------------------------------------------------

class Calibrator:
    """Interface: map a stated confidence onto a calibrated probability."""

    kind = "abstract"

    def apply(self, confidence: float) -> float:  # pragma: no cover - abstract
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:  # pragma: no cover - abstract
        raise NotImplementedError

    def describe(self, points: Sequence[float] = (0.5, 0.6, 0.7, 0.8, 0.9)) -> dict[str, float]:
        """The fitted map at a few stated confidences, for reporting."""
        return {f"{c:.2f}": round(self.apply(c), 4) for c in points}


@dataclass(frozen=True)
class IdentityCalibrator(Calibrator):
    """Returns the stated confidence unchanged.

    This is what :func:`load_calibrator` hands back when no artifact exists,
    when the artifact was written by a different :data:`CALIBRATION_VERSION`,
    or when the artifact records a failing gate.  It is the reason wiring this
    module into a live path cannot silently change behaviour.
    """

    kind = "identity"

    def apply(self, confidence: float) -> float:
        return float(confidence)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "identity"}


@dataclass(frozen=True)
class PlattCalibrator(Calibrator):
    """``sigmoid(slope * logit(p) + intercept)``.

    ``slope == 0`` is the degenerate, information-free fit: every input maps to
    ``sigmoid(intercept)``, the base rate.  That is a legitimate outcome, not a
    failure of the fitter.
    """

    slope: float
    intercept: float
    kind = "platt"

    def apply(self, confidence: float) -> float:
        z = self.slope * logit(confidence) + self.intercept
        return _clip(sigmoid(z), MIN_PROBABILITY, MAX_PROBABILITY)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "platt",
            "slope": round(self.slope, 6),
            "intercept": round(self.intercept, 6),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PlattCalibrator:
        return cls(slope=float(payload["slope"]), intercept=float(payload["intercept"]))


@dataclass(frozen=True)
class IsotonicCalibrator(Calibrator):
    """Piecewise-constant non-decreasing step function from PAVA.

    ``knots_x`` are the right edges of the pooled blocks and ``knots_y`` their
    fitted values.  Lookup is a step, not a linear interpolation: PAVA fits
    block means, and interpolating between them invents values the fit never
    claimed.  Inputs below the first block take the first value and inputs
    above the last take the last, which is the standard clamped extrapolation.
    """

    knots_x: tuple[float, ...]
    knots_y: tuple[float, ...]
    kind = "isotonic"

    def apply(self, confidence: float) -> float:
        c = float(confidence)
        for x, y in zip(self.knots_x, self.knots_y):
            if c <= x:
                return _clip(y, MIN_PROBABILITY, MAX_PROBABILITY)
        return _clip(self.knots_y[-1], MIN_PROBABILITY, MAX_PROBABILITY)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "isotonic",
            "knots_x": [round(x, 6) for x in self.knots_x],
            "knots_y": [round(y, 6) for y in self.knots_y],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> IsotonicCalibrator:
        return cls(
            knots_x=tuple(float(x) for x in payload["knots_x"]),
            knots_y=tuple(float(y) for y in payload["knots_y"]),
        )


def calibrator_from_dict(payload: dict[str, Any]) -> Calibrator:
    """Rebuild a calibrator from its serialized form."""
    kind = payload.get("kind")
    if kind == "platt":
        return PlattCalibrator.from_dict(payload)
    if kind == "isotonic":
        return IsotonicCalibrator.from_dict(payload)
    if kind == "identity":
        return IdentityCalibrator()
    raise ValueError(f"unknown calibrator kind: {kind!r}")


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------

def fit_platt(
    confidences: Sequence[float],
    labels: Sequence[float],
    *,
    monotone: bool = True,
    l2: float = 1e-6,
    max_iter: int = 100,
) -> PlattCalibrator:
    """Fit ``sigmoid(a*logit(p)+b)`` by Newton/IRLS on penalised log-loss.

    Args:
        confidences: stated confidences in (0, 1).
        labels: 0/1 outcomes, same length.
        monotone: refuse a negative slope.  A negative slope says the stated
            confidence is *anti*-predictive; at these sample sizes that is far
            more likely to be noise than a real inversion, and shipping it
            would turn "high confidence" into a short signal.  When the
            unconstrained fit is negative the constrained answer is the base
            rate (slope 0), which claims nothing.
        l2: ridge on both parameters; keeps the Hessian invertible when the
            labels are separable or the confidences are near-constant.
        max_iter: Newton steps before giving up on the tolerance.

    Returns:
        The fitted calibrator.  Falls back to the base-rate-only fit if the
        Newton iteration cannot make progress.
    """
    n = len(confidences)
    if n == 0 or n != len(labels):
        raise ValueError("confidences and labels must be non-empty and the same length")

    xs = [logit(c) for c in confidences]
    ys = [float(y) for y in labels]

    a, b = 0.0, 0.0
    for _ in range(max_iter):
        g0 = l2 * a
        g1 = l2 * b
        h00, h01, h11 = l2, 0.0, l2
        for x, y in zip(xs, ys):
            q = sigmoid(a * x + b)
            r = q - y
            g0 += r * x
            g1 += r
            w = max(q * (1.0 - q), 1e-9)
            h00 += w * x * x
            h01 += w * x
            h11 += w
        det = h00 * h11 - h01 * h01
        if abs(det) < 1e-12:
            break
        da = (h11 * g0 - h01 * g1) / det
        db = (h00 * g1 - h01 * g0) / det
        a -= da
        b -= db
        if max(abs(da), abs(db)) < 1e-10:
            break

    if monotone and a < 0.0:
        return _base_rate_platt(ys)
    return PlattCalibrator(slope=a, intercept=b)


def _base_rate_platt(labels: Sequence[float]) -> PlattCalibrator:
    """The zero-slope fit: every input maps to the sample base rate."""
    mean = sum(float(y) for y in labels) / len(labels)
    return PlattCalibrator(slope=0.0, intercept=logit(mean))


def fit_isotonic(
    confidences: Sequence[float],
    labels: Sequence[float],
) -> IsotonicCalibrator:
    """Fit a non-decreasing step function by pool-adjacent-violators.

    Ties in ``confidences`` are pooled before the sweep so the fit does not
    depend on the order equal inputs happened to arrive in.
    """
    n = len(confidences)
    if n == 0 or n != len(labels):
        raise ValueError("confidences and labels must be non-empty and the same length")

    # Pool exact ties first -- otherwise two identical confidences with
    # different labels form a "violation" whose resolution depends on input
    # order, and the fitted map stops being a function of the data alone.
    pooled: dict[float, list[float]] = defaultdict(list)
    for c, y in zip(confidences, labels):
        pooled[float(c)].append(float(y))

    # (right_edge, value, weight) blocks in increasing confidence order.
    blocks: list[list[float]] = []
    for c in sorted(pooled):
        vals = pooled[c]
        blocks.append([c, sum(vals) / len(vals), float(len(vals))])
        # Merge backwards while the sequence decreases.
        while len(blocks) > 1 and blocks[-2][1] > blocks[-1][1]:
            x_hi = blocks[-1][0]
            w = blocks[-2][2] + blocks[-1][2]
            v = (blocks[-2][1] * blocks[-2][2] + blocks[-1][1] * blocks[-1][2]) / w
            blocks[-2:] = [[x_hi, v, w]]

    return IsotonicCalibrator(
        knots_x=tuple(bl[0] for bl in blocks),
        knots_y=tuple(bl[1] for bl in blocks),
    )


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def brier(predictions: Sequence[float], labels: Sequence[float]) -> float:
    """Mean squared error of a probabilistic forecast.  Lower is better."""
    n = len(labels)
    return sum((float(p) - float(y)) ** 2 for p, y in zip(predictions, labels)) / n


def brier_skill(
    predictions: Sequence[float],
    labels: Sequence[float],
    reference: Sequence[float],
) -> float:
    """``1 - brier(model) / brier(reference)``.  Positive means better.

    ``reference`` is passed in rather than derived, because the honest
    reference is the *training* base rate repeated across the test rows.
    Deriving it from the test labels would hand the baseline information the
    model was not given, which flatters the model.
    """
    ref = brier(reference, labels)
    if ref <= 0.0:
        return 0.0
    return 1.0 - brier(predictions, labels) / ref


def reliability_curve(
    predictions: Sequence[float],
    labels: Sequence[float],
    n_bins: int = DEFAULT_BINS,
) -> list[dict[str, Any]]:
    """Per-bin mean forecast against realised frequency.  Empty bins are dropped."""
    buckets: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for p, y in zip(predictions, labels):
        idx = min(int(float(p) * n_bins), n_bins - 1)
        buckets[idx].append((float(p), float(y)))

    curve: list[dict[str, Any]] = []
    for idx in sorted(buckets):
        rows = buckets[idx]
        curve.append({
            "bin": idx,
            "range": [round(idx / n_bins, 4), round((idx + 1) / n_bins, 4)],
            "n": len(rows),
            "mean_prediction": round(sum(p for p, _ in rows) / len(rows), 4),
            "hit_rate": round(sum(y for _, y in rows) / len(rows), 4),
        })
    return curve


def expected_calibration_error(
    predictions: Sequence[float],
    labels: Sequence[float],
    n_bins: int = DEFAULT_BINS,
) -> float:
    """Sample-weighted mean gap between forecast and realised frequency."""
    total = len(labels)
    if total == 0:
        return 0.0
    return sum(
        row["n"] / total * abs(row["mean_prediction"] - row["hit_rate"])
        for row in reliability_curve(predictions, labels, n_bins)
    )


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------
# Every split in this module partitions *dates*, never rows.  Calls made on the
# same day are graded over near-identical market windows, so a row-wise split
# puts the same market move on both sides of the fence and reports a
# generalisation number that is really an in-sample one.

def _deterministic_permutation(items: Sequence[str], seed: int) -> list[str]:
    """Reproducible shuffle via a Fisher-Yates sweep over a small LCG.

    ``random`` is deliberately avoided: this is a fold assignment, not a source
    of randomness, and it must produce the same folds on every machine and
    every Python version so a reported cross-validation number can be checked.
    """
    out = list(items)
    state = (seed * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
    for i in range(len(out) - 1, 0, -1):
        state = (state * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        j = (state >> 33) % (i + 1)
        out[i], out[j] = out[j], out[i]
    return out


def date_grouped_folds(
    dates: Sequence[str],
    n_splits: int = 5,
    seed: int = 0,
) -> list[tuple[list[int], list[int]]]:
    """K-fold over distinct dates.  Returns ``[(train_idx, test_idx), ...]``.

    A date appears in exactly one test fold, so no date is ever split across
    train and test.  Folds with no rows are dropped rather than yielded empty.
    """
    distinct = sorted(set(dates))
    if n_splits < 2:
        raise ValueError("n_splits must be at least 2")

    shuffled = _deterministic_permutation(distinct, seed)
    assignment = {d: i % n_splits for i, d in enumerate(shuffled)}

    folds: list[tuple[list[int], list[int]]] = []
    for k in range(n_splits):
        test = [i for i, d in enumerate(dates) if assignment[d] == k]
        train = [i for i, d in enumerate(dates) if assignment[d] != k]
        if test and train:
            folds.append((train, test))
    return folds


def leave_one_date_out_folds(dates: Sequence[str]) -> list[tuple[list[int], list[int]]]:
    """One fold per distinct date.  The finest date-respecting split available."""
    folds: list[tuple[list[int], list[int]]] = []
    for d in sorted(set(dates)):
        test = [i for i, dd in enumerate(dates) if dd == d]
        train = [i for i, dd in enumerate(dates) if dd != d]
        if test and train:
            folds.append((train, test))
    return folds


def chronological_holdout(
    dates: Sequence[str],
    holdout_fraction: float = 0.30,
) -> tuple[list[int], list[int]]:
    """Split on time: the earliest dates train, the latest test.

    This is the deployment analogue -- a calibrator fitted today is applied to
    calls made tomorrow -- but at these sample sizes it is dominated by drift
    in the base rate between the two periods, so it is reported alongside the
    grouped folds rather than instead of them.
    """
    distinct = sorted(set(dates))
    counts = Counter(dates)
    total = len(dates)

    taken = 0
    k = 0
    for d in reversed(distinct):
        k += 1
        taken += counts[d]
        if taken >= holdout_fraction * total:
            break

    test_dates = set(distinct[len(distinct) - k:])
    test = [i for i, d in enumerate(dates) if d in test_dates]
    train = [i for i, d in enumerate(dates) if d not in test_dates]
    return train, test


# ---------------------------------------------------------------------------
# Cross-validated evaluation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CvResult:
    """Out-of-sample metrics for one fitting method over one split scheme."""

    method: str
    scheme: str
    n: int
    brier: float
    ece: float
    skill_vs_base_rate: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "scheme": self.scheme,
            "n": self.n,
            "brier": round(self.brier, 4),
            "ece": round(self.ece, 4),
            "skill_vs_base_rate": round(self.skill_vs_base_rate, 4),
        }


def _fit_method(method: str, conf: Sequence[float], lab: Sequence[float]) -> Calibrator:
    if method == "platt":
        return fit_platt(conf, lab, monotone=True)
    if method == "platt_unconstrained":
        return fit_platt(conf, lab, monotone=False)
    if method == "isotonic":
        return fit_isotonic(conf, lab)
    if method == "raw":
        return IdentityCalibrator()
    raise ValueError(f"unknown method: {method!r}")


def cross_validate(
    confidences: Sequence[float],
    labels: Sequence[float],
    dates: Sequence[str],
    method: str,
    folds: Sequence[tuple[list[int], list[int]]],
    scheme: str,
    n_bins: int = DEFAULT_BINS,
) -> CvResult:
    """Fit ``method`` on each fold's train half and score its test half.

    The base-rate reference for each test row is the *training* base rate of
    the fold that predicted it.
    """
    preds: list[float] = []
    refs: list[float] = []
    truth: list[float] = []

    for train_idx, test_idx in folds:
        tr_conf = [confidences[i] for i in train_idx]
        tr_lab = [labels[i] for i in train_idx]
        base = sum(tr_lab) / len(tr_lab)
        model = _fit_method(method, tr_conf, tr_lab)
        for i in test_idx:
            preds.append(model.apply(confidences[i]))
            refs.append(base)
            truth.append(labels[i])

    return CvResult(
        method=method,
        scheme=scheme,
        n=len(truth),
        brier=brier(preds, truth),
        ece=expected_calibration_error(preds, truth, n_bins),
        skill_vs_base_rate=brier_skill(preds, truth, refs),
    )


# ---------------------------------------------------------------------------
# Record extraction
# ---------------------------------------------------------------------------

LABEL_RULE = "sign_of_alpha"
LABEL_RULE_DESCRIPTION = (
    "sign(symbol_return - SPY_return) == predicted_direction, over the "
    "insight's own time_horizon, entered at the close one bar after "
    "created_at.  This is analysis.eval_insights' decision rule with "
    "alpha_threshold_pct=0.0.  It is the only rule under which Brier and ECE "
    "are coherent: a threshold band carves out a region in which a directional "
    "call can neither win nor lose, so the graded event stops being a "
    "partition of outcomes and the forecast stops being a probability of "
    "anything.  The outcome grader's +/-2% band answers the track-record "
    "question instead and scores ~10 points lower on identical data."
)


def extract_columns(
    records: Iterable[Any],
) -> tuple[list[float], list[float], list[str], list[str]]:
    """Pull ``(confidences, labels, dates, symbols)`` out of eval records.

    Accepts :class:`analysis.eval_insights.EvalRecord` instances or the dicts
    ``asdict`` produces for them, so a stored ``insight_eval.json`` snapshot
    can be replayed without re-running the grader.
    """
    conf: list[float] = []
    lab: list[float] = []
    dates: list[str] = []
    syms: list[str] = []

    for rec in records:
        def field(name: str, _rec: Any = rec) -> Any:
            if isinstance(_rec, dict):
                return _rec[name]
            return getattr(_rec, name)

        confidence = field("confidence")
        if confidence is None:
            raise ValueError("eval record has no confidence -- it should have been excluded")
        conf.append(float(confidence))
        lab.append(1.0 if field("correct") else 0.0)
        dates.append(str(field("created_at"))[:10])
        syms.append(str(field("symbol")))

    return conf, lab, dates, syms


def effective_sample(dates: Sequence[str], symbols: Sequence[str]) -> dict[str, Any]:
    """How much independent evidence the rows actually represent.

    A row count is the wrong number to quote for overlapping calls.  Distinct
    dates bound the number of independent market moves; the most-repeated
    symbol bounds how much of the book is one instrument.
    """
    date_counts = Counter(dates)
    sym_counts = Counter(symbols)
    top_sym, top_n = sym_counts.most_common(1)[0] if sym_counts else ("", 0)
    return {
        "rows": len(dates),
        "distinct_dates": len(date_counts),
        "distinct_symbols": len(sym_counts),
        "most_repeated_symbol": top_sym,
        "most_repeated_symbol_n": top_n,
        "largest_date_cluster": date_counts.most_common(1)[0][1] if date_counts else 0,
        "rows_per_date": round(len(dates) / len(date_counts), 2) if date_counts else 0.0,
    }


# ---------------------------------------------------------------------------
# The fit
# ---------------------------------------------------------------------------

def fit_calibration(
    records: Sequence[Any],
    *,
    n_bins: int = DEFAULT_BINS,
    holdout_fraction: float = 0.30,
    grouped_splits: int = 5,
    grouped_seeds: int = 20,
    source: str = "analysis.eval_insights",
) -> dict[str, Any]:
    """Fit both methods, score them out of sample, and decide whether to ship.

    Returns the artifact dict written to :data:`ARTIFACT_PATH`.  The artifact
    always records the full measurement, including a failing one -- a refit
    that concludes "not yet" is a result worth keeping, and overwriting it with
    silence would lose the only record that the question was asked.

    ``active`` is ``True`` only when the chosen method clears
    :data:`MIN_OOS_BRIER_SKILL` on the leave-one-date-out split.  Nothing else
    in this module consults anything but that flag.
    """
    conf, lab, dates, syms = extract_columns(records)
    sample = effective_sample(dates, syms)

    artifact: dict[str, Any] = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "calibration_version": CALIBRATION_VERSION,
        "source": source,
        "label_rule": LABEL_RULE,
        "label_rule_description": LABEL_RULE_DESCRIPTION,
        "n": len(conf),
        "base_rate": round(sum(lab) / len(lab), 4) if lab else None,
        "effective_sample": sample,
        "gate": {
            "min_oos_brier_skill": MIN_OOS_BRIER_SKILL,
            "min_records": MIN_RECORDS,
            "min_distinct_dates": MIN_DISTINCT_DATES,
        },
    }

    if len(conf) < MIN_RECORDS or sample["distinct_dates"] < MIN_DISTINCT_DATES:
        artifact["active"] = False
        artifact["verdict"] = (
            f"insufficient data: {len(conf)} rows across "
            f"{sample['distinct_dates']} dates (need {MIN_RECORDS}/"
            f"{MIN_DISTINCT_DATES})"
        )
        artifact["calibrator"] = IdentityCalibrator().to_dict()
        return artifact

    loo = leave_one_date_out_folds(dates)
    chrono_train, chrono_test = chronological_holdout(dates, holdout_fraction)

    methods = ("raw", "platt", "platt_unconstrained", "isotonic")
    results: dict[str, dict[str, Any]] = {}

    for method in methods:
        blocks: dict[str, Any] = {}
        blocks["leave_one_date_out"] = cross_validate(
            conf, lab, dates, method, loo, "leave_one_date_out", n_bins
        ).to_dict()
        blocks["chronological_holdout"] = cross_validate(
            conf, lab, dates, method, [(chrono_train, chrono_test)],
            "chronological_holdout", n_bins,
        ).to_dict()

        # Repeated grouped k-fold: one seed's fold assignment is itself a
        # sample, and at 30 dates the spread across seeds is not negligible.
        skills = []
        for seed in range(grouped_seeds):
            folds = date_grouped_folds(dates, grouped_splits, seed)
            skills.append(
                cross_validate(conf, lab, dates, method, folds, "grouped_kfold", n_bins)
                .skill_vs_base_rate
            )
        mean = sum(skills) / len(skills)
        blocks["grouped_kfold"] = {
            "method": method,
            "scheme": f"grouped_{grouped_splits}fold_x{grouped_seeds}seeds",
            "mean_skill_vs_base_rate": round(mean, 4),
            "min_skill": round(min(skills), 4),
            "max_skill": round(max(skills), 4),
            "seeds_with_positive_skill": sum(1 for s in skills if s > 0),
        }
        results[method] = blocks

    artifact["out_of_sample"] = results

    # Method selection: the primary criterion is leave-one-date-out skill,
    # the split that uses the most training data while still respecting dates.
    # ``platt_unconstrained`` is measured for the report but never selected --
    # it is diagnostic, not a candidate.
    candidates = ("platt", "isotonic")
    ranked = sorted(
        candidates,
        key=lambda m: results[m]["leave_one_date_out"]["skill_vs_base_rate"],
        reverse=True,
    )
    chosen = ranked[0]
    chosen_skill = results[chosen]["leave_one_date_out"]["skill_vs_base_rate"]

    # The shipped parameters are fitted on everything.  The held-out numbers
    # above estimate how such a fit generalises; they are not themselves the
    # model.  Refitting on the full sample is standard and is what makes the
    # artifact worth more than any single fold's model.
    full = _fit_method(chosen, conf, lab)
    artifact["calibrator"] = full.to_dict()
    artifact["mapping"] = full.describe((0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95))
    artifact["diagnostics"] = {
        "full_sample_platt": fit_platt(conf, lab, monotone=False).to_dict(),
        "raw_reliability": reliability_curve(conf, lab, n_bins),
        "selected_method": chosen,
        "selected_leave_one_date_out_skill": chosen_skill,
        "runner_up": ranked[1],
    }

    passed = chosen_skill >= MIN_OOS_BRIER_SKILL
    artifact["active"] = passed
    if passed:
        artifact["verdict"] = (
            f"{chosen} clears the gate: leave-one-date-out Brier skill "
            f"{chosen_skill:+.4f} >= {MIN_OOS_BRIER_SKILL}"
        )
    else:
        artifact["verdict"] = (
            f"no method clears the gate. Best is {chosen} at leave-one-date-out "
            f"Brier skill {chosen_skill:+.4f}, below {MIN_OOS_BRIER_SKILL}. "
            f"Stated confidence carries no measurable information about "
            f"outcomes at n={len(conf)} across {sample['distinct_dates']} "
            f"dates, so the calibrated probability is the base rate and a "
            f"fitted map only spends parameters to say so. Serving stays on "
            f"the identity fallback."
        )
    return artifact


# ---------------------------------------------------------------------------
# Artifact I/O
# ---------------------------------------------------------------------------

def save_artifact(artifact: dict[str, Any], path: Path = ARTIFACT_PATH) -> None:
    """Write the artifact, creating ``data/`` if a fresh clone has not yet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2, sort_keys=False) + "\n")
    logger.info("Wrote confidence calibration artifact to %s", path)


def load_artifact(path: Path = ARTIFACT_PATH) -> dict[str, Any] | None:
    """Read the artifact, or ``None`` if it is missing or unreadable.

    An unreadable artifact is not an error worth raising: the caller's correct
    response is the identity fallback either way, and a serving path must not
    fail because a diagnostic file was truncated.
    """
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as err:
        logger.warning("Confidence calibration artifact at %s is unreadable: %s", path, err)
        return None


def load_calibrator(path: Path = ARTIFACT_PATH) -> Calibrator:
    """The calibrator to apply to live confidence.

    Returns :class:`IdentityCalibrator` -- leaving confidence exactly as the
    caller stated it -- unless *all* of the following hold:

    * the artifact exists and parses;
    * it was written by this :data:`CALIBRATION_VERSION`;
    * it records ``active: true``, meaning its fit cleared the out-of-sample
      gate at the time it was written;
    * its serialized calibrator rebuilds.

    Every failure is a silent fall back to identity, by design.  A calibration
    artifact is an optimisation, never a dependency.
    """
    payload = load_artifact(path)
    if payload is None:
        return IdentityCalibrator()

    version = payload.get("calibration_version")
    if version != CALIBRATION_VERSION:
        logger.warning(
            "Ignoring confidence calibration artifact written under version %s "
            "(this build expects %s)", version, CALIBRATION_VERSION,
        )
        return IdentityCalibrator()

    if not payload.get("active"):
        return IdentityCalibrator()

    try:
        return calibrator_from_dict(payload.get("calibrator") or {})
    except (ValueError, KeyError, TypeError) as err:
        logger.warning("Confidence calibration artifact has an unusable calibrator: %s", err)
        return IdentityCalibrator()


def calibrate(confidence: float, path: Path = ARTIFACT_PATH) -> float:
    """Convenience one-shot: load and apply.  Identity when nothing is fitted.

    Callers in a loop should hoist :func:`load_calibrator` out instead -- this
    re-reads the artifact on every call.
    """
    return load_calibrator(path).apply(confidence)


# ---------------------------------------------------------------------------
# Refit CLI
# ---------------------------------------------------------------------------

async def refit_from_database(*, save: bool = True, path: Path = ARTIFACT_PATH) -> dict[str, Any]:
    """Grade every elapsed insight, fit, and write the artifact.

    Runs the eval harness with ``save=False`` so a refit never disturbs
    ``insight_eval.json``, which is that harness's own published snapshot.
    """
    from analysis.eval_insights import run_insight_eval  # type: ignore[import-not-found]
    from database import async_session_factory  # type: ignore[import-not-found]

    async with async_session_factory() as session:
        snapshot = await run_insight_eval(
            session, save=False, allow_network=False, include_records=True
        )

    if "error" in snapshot:
        raise RuntimeError(f"eval harness failed: {snapshot['error']}")

    artifact = fit_calibration(snapshot.get("records", []))
    artifact["eval_harness_version"] = snapshot.get("harness_version")
    artifact["eval_git_sha"] = snapshot.get("git_sha")
    if save:
        save_artifact(artifact, path)
    return artifact


def format_calibration_summary(artifact: dict[str, Any]) -> str:
    """Human-readable report for the CLI."""
    lines = [
        "Confidence calibration",
        "=" * 60,
        f"as_of            {artifact.get('as_of')}",
        f"label rule       {artifact.get('label_rule')}",
        f"n                {artifact.get('n')}  base rate {artifact.get('base_rate')}",
    ]
    sample = artifact.get("effective_sample") or {}
    if sample:
        lines.append(
            f"effective sample {sample.get('distinct_dates')} distinct dates, "
            f"{sample.get('distinct_symbols')} symbols, most repeated "
            f"{sample.get('most_repeated_symbol')} x{sample.get('most_repeated_symbol_n')}"
        )

    oos = artifact.get("out_of_sample") or {}
    if oos:
        lines += ["", "Out-of-sample Brier skill vs the training base rate:", ""]
        lines.append(f"  {'method':<22}{'LOO-date':>10}{'chrono':>10}{'grouped':>10}{'LOO ECE':>10}")
        for method, blocks in oos.items():
            loo = blocks["leave_one_date_out"]
            lines.append(
                f"  {method:<22}{loo['skill_vs_base_rate']:>+10.4f}"
                f"{blocks['chronological_holdout']['skill_vs_base_rate']:>+10.4f}"
                f"{blocks['grouped_kfold']['mean_skill_vs_base_rate']:>+10.4f}"
                f"{loo['ece']:>10.4f}"
            )

    mapping = artifact.get("mapping") or {}
    if mapping:
        lines += ["", "Fitted map (stated -> calibrated):"]
        lines.append("  " + "  ".join(f"{k}->{v:.3f}" for k, v in mapping.items()))

    lines += [
        "",
        f"active           {artifact.get('active')}",
        f"verdict          {artifact.get('verdict')}",
    ]
    return "\n".join(lines)


async def _main() -> None:  # pragma: no cover -- CLI entry point
    parser = argparse.ArgumentParser(
        description="Fit the post-hoc confidence calibrator against graded outcomes.",
    )
    parser.add_argument("--refit", action="store_true",
                        help="grade outcomes and fit (default action)")
    parser.add_argument("--no-save", action="store_true",
                        help="report the fit without writing the artifact")
    parser.add_argument("--show", action="store_true",
                        help="print the stored artifact without refitting")
    args = parser.parse_args()

    if args.show:
        payload = load_artifact()
        if payload is None:
            print("No calibration artifact -- serving falls back to identity.")  # noqa: T201
            return
        print(format_calibration_summary(payload))  # noqa: T201
        return

    artifact = await refit_from_database(save=not args.no_save)
    print(format_calibration_summary(artifact))  # noqa: T201


if __name__ == "__main__":  # pragma: no cover
    import asyncio

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(_main())
