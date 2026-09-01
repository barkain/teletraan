"""Measured hit rate per action type, for display in place of stated confidence.

Why this module exists
----------------------
Every insight carries a model-stated ``confidence`` in [0, 1], and the app used
to render it as a headline percentage next to the action badge. The calibration
work in ``analysis/confidence_calibrator.py`` measured whether that number
predicts anything and found it does not: across 209 graded calls spanning 30
distinct dates, the date-clustered bootstrap puts the calibration slope at
−0.151 with a 95% interval of [−0.503, +0.150], and the monotone fit collapses
to a constant equal to the base rate — a stated 0.8 and a stated 0.3 map to the
same 0.450. The signal is not inverted; it is absent.

Rendering a number with no measured information content as "82%" next to
"STRONG_BUY" tells a reader something false. This module supplies what the
record actually supports: **how often calls of this action type have been graded
correct**. That is a property of a class of call, never a forecast for the one on
screen, and every rendering path is required to label it that way.

What "graded correct" means
---------------------------
Exactly what ``analysis/outcome_tracker.py`` decides, read straight off
``InsightOutcome.thesis_validated`` for COMPLETED rows: the symbol beat SPY by
more than 2 percentage points in the predicted direction over the insight's own
horizon (a neutral call wins inside that band), with a touched stop or target
settling the question earlier. Rows the grader declined to score are NULL and are
excluded from both numerator and denominator, so an ungradeable call cannot
quietly count as a loss.

Too few outcomes
----------------
Below :data:`MIN_GRADED_SAMPLE` no rate is returned at all. At n = 6 the 95%
interval on a proportion is roughly ±38 points, which cannot separate one action
from any other, and publishing it would repeat the exact error this module
exists to remove. The codebase already takes this line elsewhere —
``format_factor_value`` refuses to substitute a plausible score for a missing
one, and ``price_freshness`` reports staleness rather than serving a stale price
as fresh. Callers get ``rate is None`` plus the sample count, and must render the
absence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.deep_insight import DeepInsight
from models.insight_outcome import InsightOutcome, TrackingStatus

# Fewest graded outcomes an action needs before a rate is quoted for it.
#
# 20 is the point at which the 95% interval on a proportion near 1/3 narrows to
# about ±21 points. That is still wide, and the UI says so, but it is the first
# level at which the number is worth more than the space it occupies.
MIN_GRADED_SAMPLE = 20

# One sentence, shown wherever a rate is shown. It is the whole guard against
# the number being read as a per-idea probability.
BASE_RATE_CAVEAT = (
    "Historical hit rate for this type of call, not a forecast for this idea."
)

# How a call is scored, in one line, for tooltips and report footnotes.
BASE_RATE_METHOD = (
    "A call counts as correct when the symbol beat SPY by more than 2 "
    "percentage points in the predicted direction over the insight's own "
    "horizon; a stop or target touched first settles it earlier."
)


@dataclass(frozen=True)
class ActionBaseRate:
    """The graded record for one action type.

    Attributes:
        action: The action label, e.g. ``"BUY"``.
        graded: Outcomes with a verdict. Ungraded rows are not counted.
        validated: How many of those were graded correct.
        rate: ``validated / graded``, or None when ``graded`` is below
            :data:`MIN_GRADED_SAMPLE`. None is the honest value, not zero.
    """

    action: str
    graded: int
    validated: int

    @property
    def rate(self) -> float | None:
        """Measured hit rate, or None when the sample cannot support one."""
        if self.graded < MIN_GRADED_SAMPLE or self.graded == 0:
            return None
        return self.validated / self.graded

    @property
    def available(self) -> bool:
        """Whether a rate can be quoted at all."""
        return self.rate is not None

    @property
    def percent(self) -> int | None:
        """The rate as whole percentage points, or None."""
        rate = self.rate
        return None if rate is None else round(rate * 100)

    def headline(self) -> str:
        """The short form shown next to the action badge.

        Reads as a statement about the past, never as a probability. When the
        sample is too small it says so and still shows n, because "we have only
        graded 6 of these" is itself the useful fact.
        """
        if self.rate is None:
            return f"Too few graded {self.action} calls (n={self.graded})"
        return f"{self.percent}% of past {self.action} calls worked (n={self.graded})"

    def to_dict(self) -> dict[str, Any]:
        """Serializable form, shared by the API and the HTML report."""
        return {
            "action": self.action,
            "graded": self.graded,
            "validated": self.validated,
            "rate": self.rate,
            "percent": self.percent,
            "available": self.available,
            "headline": self.headline(),
            "caveat": BASE_RATE_CAVEAT,
        }


@dataclass(frozen=True)
class ActionBaseRates:
    """Every action's graded record, plus the all-actions total."""

    by_action: dict[str, ActionBaseRate]
    overall: ActionBaseRate
    min_sample: int = MIN_GRADED_SAMPLE

    def for_action(self, action: str | None) -> ActionBaseRate:
        """The record for one action.

        An action with no graded outcomes at all — a newly introduced label, or
        one that has never been tracked — returns a zero-sample entry rather
        than raising or falling back to the overall rate. Borrowing the overall
        rate would state something the record does not say about that action.
        """
        key = (action or "").upper()
        return self.by_action.get(key, ActionBaseRate(key, 0, 0))

    def to_dict(self) -> dict[str, Any]:
        """Serializable form, shared by the API and the HTML report."""
        return {
            "min_sample": self.min_sample,
            "caveat": BASE_RATE_CAVEAT,
            "method": BASE_RATE_METHOD,
            "overall": self.overall.to_dict(),
            "by_action": {
                action: rate.to_dict()
                for action, rate in sorted(self.by_action.items())
            },
        }


async def load_action_base_rates(db: AsyncSession) -> ActionBaseRates:
    """Read the graded record out of ``insight_outcomes``.

    Deliberately unfiltered by date. ``ConfidenceAdjuster`` windows its lookups
    to 90 days because it is asking "how are we doing lately"; this is asking
    "what has this class of call ever done", and at ~30 distinct trading dates in
    the whole record a 90-day window would leave most actions below
    :data:`MIN_GRADED_SAMPLE` and reporting nothing.

    Args:
        db: Async session.

    Returns:
        An :class:`ActionBaseRates` covering every action that has at least one
        graded outcome, plus the all-actions total.
    """
    # case() rather than sum(thesis_validated): summing a Boolean column relies
    # on the backend storing it as 0/1, which SQLite does and other dialects do
    # not have to.
    validated_count = func.sum(
        case((InsightOutcome.thesis_validated.is_(True), 1), else_=0)
    )
    stmt = (
        select(
            DeepInsight.action,
            func.count(InsightOutcome.id),
            validated_count,
        )
        .join(DeepInsight, DeepInsight.id == InsightOutcome.insight_id)
        .where(
            InsightOutcome.tracking_status == TrackingStatus.COMPLETED.value,
            InsightOutcome.thesis_validated.isnot(None),
        )
        .group_by(DeepInsight.action)
    )
    rows = (await db.execute(stmt)).all()

    by_action: dict[str, ActionBaseRate] = {}
    total_graded = 0
    total_validated = 0
    for action, graded, validated in rows:
        key = (action or "").upper()
        if not key:
            continue
        graded = int(graded or 0)
        validated = int(validated or 0)
        by_action[key] = ActionBaseRate(key, graded, validated)
        total_graded += graded
        total_validated += validated

    return ActionBaseRates(
        by_action=by_action,
        overall=ActionBaseRate("ALL", total_graded, total_validated),
    )
