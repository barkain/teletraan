"""Re-grade COMPLETED outcomes that were frozen under the retired grader.

``check_outcomes`` only ever visits rows in TRACKING status
(``analysis/outcome_tracker.py``), so once a row reaches COMPLETED it is never
looked at again. Every outcome completed before the grader rebuild is therefore
still carrying the *pre-rebuild* verdict: raw return against a flat band over a
window that ``scripts/backfill_patterns.py`` hardcoded to 20 trading days,
regardless of what horizon the insight itself stated. Those rows have
``alpha_pct``, ``benchmark_return_pct``, ``horizon_days``,
``evaluated_price_date`` and ``exit_reason`` all NULL, which is exactly the
shape of a row the current grader has never touched.

That is not a cosmetic disagreement. ``ConfidenceAdjuster`` reads
``InsightOutcome.thesis_validated`` directly for its ``historical`` (weight 0.2)
and ``symbol`` (weight 0.1) components, so the stale verdicts are wired into the
live confidence blend.

This module re-grades those rows **through the existing grader**. It contains no
scoring logic of its own: it repairs the window fields the old path got wrong and
then hands each row to ``InsightOutcomeTracker._evaluate_outcome``, the same
method ``check_outcomes`` calls. Reaching for a private method is deliberate — a
second implementation of the alpha rule is the failure this whole exercise is
about, and the public entry point cannot be used because it filters to TRACKING.

Two properties the callers depend on:

*Idempotent.* ``_evaluate_outcome`` is a pure function of (window, price series,
insight levels): it *replaces* ``price_history`` rather than appending, and
merges checkpoints by key. Running this twice therefore leaves byte-identical
rows apart from ``updated_at``.

*Never silently destructive.* No row is deleted, but a re-grade does overwrite
the retired verdict and the window fields that produced it -- that is the point.
Two rows do not come out graded, and both are left in a state the normal pass
can still resolve rather than in a half-updated one. A row whose window has not
actually closed yet under its true horizon goes back to TRACKING so grading
happens on time. A row the grader declines to score (no usable price series)
also goes back to TRACKING with its retired verdict cleared to NULL: "we do not
know" is the honest reading, a stale verdict would keep feeding the confidence
blend, and leaving it COMPLETED-but-ungraded would strand it, since
``check_outcomes`` only ever visits TRACKING rows and the price ETL back-fills
gaps on its own.

Usage::

    cd backend && uv run python -m analysis.outcome_backfill          # apply
    cd backend && uv run python -m analysis.outcome_backfill --dry-run
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from analysis.horizons import resolve_horizon_days, trading_to_calendar_days
from analysis.outcome_tracker import InsightOutcomeTracker
from models.deep_insight import DeepInsight
from models.insight_outcome import InsightOutcome, TrackingStatus

logger = logging.getLogger(__name__)

# Fields the current grader writes and the retired one did not. They are cleared
# before a re-grade so that a row the grader refuses to score cannot keep a
# half-updated mixture of the two rules.
_GRADED_FIELDS = (
    "alpha_pct",
    "benchmark_return_pct",
    "benchmark_initial_price",
    "benchmark_final_price",
    "evaluated_price_date",
    "exit_reason",
    "final_price",
    "actual_return_pct",
    "outcome_category",
    "thesis_validated",
)


@dataclass
class BackfillReport:
    """What one backfill pass did, in enough detail to audit it."""

    considered: int = 0
    regraded: int = 0
    verdict_unchanged: int = 0
    flipped_to_validated: int = 0
    flipped_to_failed: int = 0
    verdict_cleared: int = 0
    returned_to_tracking: int = 0
    window_corrected: int = 0
    skipped_no_symbol: int = 0
    skipped_unmappable_horizon: int = 0
    ungraded_no_data: int = 0
    validated_before: int = 0
    validated_after: int = 0
    graded_before: int = 0
    graded_after: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def hit_rate_before(self) -> float | None:
        """Share of validated theses before the pass, or None with no sample."""
        if not self.graded_before:
            return None
        return self.validated_before / self.graded_before

    @property
    def hit_rate_after(self) -> float | None:
        """Share of validated theses after the pass, or None with no sample."""
        if not self.graded_after:
            return None
        return self.validated_after / self.graded_after

    def summary(self) -> str:
        """One-screen human summary."""
        def _pct(rate: float | None) -> str:
            return "n/a" if rate is None else f"{rate * 100:.1f}%"

        return (
            f"considered={self.considered} regraded={self.regraded} "
            f"window_corrected={self.window_corrected} "
            f"returned_to_tracking={self.returned_to_tracking}\n"
            f"verdicts: unchanged={self.verdict_unchanged} "
            f"->validated={self.flipped_to_validated} "
            f"->failed={self.flipped_to_failed} "
            f"cleared={self.verdict_cleared}\n"
            f"skipped: no_symbol={self.skipped_no_symbol} "
            f"unmappable_horizon={self.skipped_unmappable_horizon} "
            f"no_price_data={self.ungraded_no_data}\n"
            f"hit rate: {_pct(self.hit_rate_before)} "
            f"({self.validated_before}/{self.graded_before}) -> "
            f"{_pct(self.hit_rate_after)} "
            f"({self.validated_after}/{self.graded_after})"
        )


def _expected_window(
    outcome: InsightOutcome, insight: DeepInsight
) -> tuple[int, date]:
    """The horizon and window end this outcome should have been graded on.

    An explicit ``horizon_days`` already on the row wins: ``start_tracking``
    accepts a caller override, and re-deriving from the label would silently
    overwrite a window that was chosen on purpose. Only rows that never recorded
    one — which is every row the retired path produced — fall back to the
    insight's own ``time_horizon``.

    Raises:
        ValueError: if no horizon can be resolved. Callers must skip such a row
            rather than invent a window for it.
    """
    horizon_days = outcome.horizon_days or resolve_horizon_days(
        insight.time_horizon
    )
    end = outcome.tracking_start_date + timedelta(
        days=trading_to_calendar_days(horizon_days)
    )
    return horizon_days, end


async def backfill_completed_outcomes(
    db: AsyncSession,
    *,
    as_of: date | None = None,
    dry_run: bool = False,
) -> BackfillReport:
    """Re-grade every COMPLETED outcome under the current grader.

    Args:
        db: Async session.
        as_of: Treated as "today" when deciding whether a corrected window has
            closed. Defaults to the real date; injectable so tests are stable.
        dry_run: Grade everything and report, then roll back instead of
            committing.

    Returns:
        A :class:`BackfillReport`. Safe to run repeatedly: a second pass over
        unchanged prices reports zero flips and leaves the rows as they are.
    """
    today = as_of or date.today()
    tracker = InsightOutcomeTracker(db)
    report = BackfillReport()

    rows = (
        (
            await db.execute(
                select(InsightOutcome)
                .where(
                    InsightOutcome.tracking_status
                    == TrackingStatus.COMPLETED.value
                )
                .order_by(InsightOutcome.tracking_start_date)
            )
        )
        .scalars()
        .all()
    )
    report.considered = len(rows)

    for outcome in rows:
        before = outcome.thesis_validated
        if before is not None:
            report.graded_before += 1
            report.validated_before += bool(before)

        insight = await db.get(DeepInsight, outcome.insight_id)
        if insight is None or not insight.primary_symbol:
            report.skipped_no_symbol += 1
            _count_after(report, before)
            continue

        try:
            horizon_days, expected_end = _expected_window(outcome, insight)
        except ValueError as exc:
            # An insight whose horizon cannot be read cannot be graded on a
            # horizon. Leaving the retired verdict in place would be worse than
            # saying so, but clearing it is not this function's call either.
            logger.warning("Outcome %s: %s", outcome.id, exc)
            report.skipped_unmappable_horizon += 1
            _count_after(report, before)
            continue

        if expected_end != outcome.tracking_end_date:
            outcome.tracking_end_date = expected_end
            report.window_corrected += 1
        outcome.horizon_days = horizon_days

        if expected_end > today:
            # The old window was too short, so this row was marked COMPLETED
            # before its real horizon elapsed. Grading it now would score a
            # partial window; hand it back to check_outcomes instead.
            _clear_graded_fields(outcome)
            outcome.tracking_status = TrackingStatus.TRACKING.value
            report.returned_to_tracking += 1
            if before is not None:
                report.verdict_cleared += 1
            continue

        _clear_graded_fields(outcome)
        try:
            await tracker._evaluate_outcome(outcome, insight=insight)
        except Exception as exc:  # noqa: BLE001 - one bad row must not abort
            logger.error("Outcome %s failed to re-grade: %s", outcome.id, exc)
            report.errors.append(f"{outcome.id}: {exc}")
            _count_after(report, outcome.thesis_validated)
            continue

        after = outcome.thesis_validated
        if after is None:
            # The grader refused: no usable price series over the window. Hand
            # the row back to check_outcomes instead of leaving it COMPLETED
            # with nothing on it, which no pass would ever look at again.
            outcome.tracking_status = TrackingStatus.TRACKING.value
            report.ungraded_no_data += 1
            if before is not None:
                report.verdict_cleared += 1
        else:
            report.regraded += 1
            if before is None or bool(after) == bool(before):
                report.verdict_unchanged += 1
            elif after:
                report.flipped_to_validated += 1
            else:
                report.flipped_to_failed += 1
        _count_after(report, after)

    if dry_run:
        await db.rollback()
    else:
        await db.commit()

    logger.info("Outcome backfill:\n%s", report.summary())
    return report


def _clear_graded_fields(outcome: InsightOutcome) -> None:
    """Null every field the grader owns, so a refusal cannot leave a mixture."""
    for name in _GRADED_FIELDS:
        setattr(outcome, name, None)


def _count_after(report: BackfillReport, validated: bool | None) -> None:
    """Fold one row's post-pass verdict into the after-totals."""
    if validated is not None:
        report.graded_after += 1
        report.validated_after += bool(validated)


async def _main(dry_run: bool) -> None:
    """CLI body: open a session, run the pass, print the report."""
    from database import async_session_factory, init_db

    await init_db()
    async with async_session_factory() as session:
        report = await backfill_completed_outcomes(session, dry_run=dry_run)
    print(report.summary())  # noqa: T201
    if report.errors:
        print(f"\n{len(report.errors)} errors:")  # noqa: T201
        for line in report.errors[:20]:
            print(f"  {line}")  # noqa: T201


if __name__ == "__main__":
    import argparse
    import asyncio
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="grade and report without writing anything",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(_main(args.dry_run))
