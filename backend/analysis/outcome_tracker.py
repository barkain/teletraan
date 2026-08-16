"""InsightOutcomeTracker service for tracking and evaluating insight predictions.

This service manages the lifecycle of insight outcome tracking, from initiating
tracking when an insight is generated, to evaluating the final outcome after
the tracking period ends.
"""

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from analysis.horizons import resolve_horizon_days, trading_to_calendar_days
from data.adapters.yahoo import YahooFinanceAdapter, YahooFinanceError
from models.deep_insight import DeepInsight
from models.insight_outcome import InsightOutcome, OutcomeCategory, TrackingStatus
from models.knowledge_pattern import KnowledgePattern
from models.price import PriceHistory
from models.stock import Stock

logger = logging.getLogger(__name__)

# Checkpoint intervals in trading days
_CHECKPOINT_DAYS = (5, 10, 20, 40)

# Benchmark used for relative scoring. Beating +1% in a market that rose 6.6%
# is not a successful call, so all validation is decided on alpha vs this.
_BENCHMARK_SYMBOL = "SPY"

# Alpha (percentage points) a call must clear, in the predicted direction, to
# count as validated. Also the half-width of the band in which a neutral
# (HOLD/WATCH) call is considered correct — see _validate_thesis.
_ALPHA_THRESHOLD_PCT = 2.0

# Slack allowed at each edge of a price window, in calendar days, so that a
# window ending on a weekend or holiday does not trigger a needless refetch.
_SERIES_EDGE_GRACE_DAYS = 5

# Largest acceptable hole inside a price series, in calendar days. A normal
# weekend is 3 and a long holiday weekend 4-5; anything wider means the series
# is missing trading days and must not be graded on.
_MAX_SERIES_GAP_DAYS = 5


class InsightOutcomeTracker:
    """Service for tracking and evaluating insight prediction outcomes.

    This tracker manages the complete lifecycle of insight outcome validation:
    1. Start tracking when an insight is generated
    2. Periodically update current prices during tracking
    3. Evaluate final outcome when tracking period ends
    4. Update pattern success rates based on validated outcomes
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize the outcome tracker.

        Args:
            db: Async database session for persistence operations
        """
        self.db = db
        self._yahoo_adapter = YahooFinanceAdapter()
        # Close-series cache, keyed by (symbol, start, end). A single
        # check_outcomes() pass grades many insights against the same
        # benchmark window; without this it would refetch SPY every time.
        self._series_cache: dict[tuple[str, date, date], list[tuple[date, float]]] = {}

    @staticmethod
    def resolve_horizon_days(time_horizon: str | None) -> int:
        """Map a DeepInsight.time_horizon onto a tracking window in trading days.

        Thin delegate to ``analysis.horizons`` — the table lives there so the
        grader and the evaluation harness cannot drift apart again. Raises
        ValueError on an unmappable horizon.
        """
        return resolve_horizon_days(time_horizon)

    async def start_tracking(
        self,
        insight_id: int,
        symbol: str,
        predicted_direction: str,
        tracking_days: int | None = None,
    ) -> InsightOutcome:
        """Start tracking an insight's prediction outcome.

        Creates a new InsightOutcome record to track the price movement
        from today until the end of the tracking period.

        Args:
            insight_id: ID of the DeepInsight being tracked
            symbol: Stock symbol to track (e.g., "AAPL")
            predicted_direction: "bullish", "bearish", or "neutral"
            tracking_days: Explicit override for the window, in trading days.
                When omitted (the normal path) the window is derived from the
                insight's own ``time_horizon``.

        Returns:
            Created InsightOutcome record

        Raises:
            ValueError: If insight not found, symbol invalid, or the insight's
                time_horizon cannot be mapped to a window
            YahooFinanceError: If unable to fetch initial price
        """
        # Verify the insight exists
        insight = await self.db.get(DeepInsight, insight_id)
        if not insight:
            raise ValueError(f"DeepInsight with id {insight_id} not found")

        # Validate predicted direction
        valid_directions = ("bullish", "bearish", "neutral")
        if predicted_direction.lower() not in valid_directions:
            raise ValueError(
                f"Invalid predicted_direction: {predicted_direction}. "
                f"Must be one of {valid_directions}"
            )

        # Derive the window from the insight unless explicitly overridden.
        # Raises if the horizon is unknown, so an ungradeable insight is never
        # tracked against a fabricated window.
        if tracking_days is None:
            tracking_days = self.resolve_horizon_days(insight.time_horizon)

        # Fetch initial price from market data
        try:
            price_data = await self._yahoo_adapter.get_current_price(symbol)
            initial_price = price_data["price"]
        except YahooFinanceError as e:
            logger.error(f"Failed to fetch initial price for {symbol}: {e}")
            raise

        # Calculate tracking end date (approximate trading days)
        calendar_days = trading_to_calendar_days(tracking_days)
        tracking_start = date.today()
        tracking_end = tracking_start + timedelta(days=calendar_days)

        # Create the outcome record
        outcome = InsightOutcome(
            insight_id=insight_id,
            tracking_status=TrackingStatus.TRACKING.value,
            tracking_start_date=tracking_start,
            tracking_end_date=tracking_end,
            initial_price=initial_price,
            current_price=initial_price,
            predicted_direction=predicted_direction.lower(),
            horizon_days=tracking_days,
            benchmark_symbol=_BENCHMARK_SYMBOL,
            price_history=[
                {"date": tracking_start.isoformat(), "price": initial_price}
            ],
        )

        self.db.add(outcome)
        await self.db.commit()
        await self.db.refresh(outcome)

        logger.info(
            f"Started tracking insight {insight_id} for {symbol}: "
            f"initial_price={initial_price}, direction={predicted_direction}, "
            f"end_date={tracking_end}"
        )

        return outcome

    async def check_outcomes(self) -> list[InsightOutcome]:
        """Check and update all active outcome tracking records.

        For each outcome with TRACKING status:
        - Loads the daily close series over the window so far and records the
          full intraperiod path (not just a single spot price)
        - Terminates tracking early if the insight's stop or target was touched
        - Evaluates the final outcome once the window has closed

        Evaluation is *retroactive*: a window that closed weeks ago is graded
        on the close at its own ``tracking_end_date``, so nothing is lost by
        the process not having been running on the day the window expired.

        Returns:
            List of updated InsightOutcome records
        """
        # Query all actively tracking outcomes
        query = (
            select(InsightOutcome)
            .where(InsightOutcome.tracking_status == TrackingStatus.TRACKING.value)
        )
        result = await self.db.execute(query)
        outcomes = result.scalars().all()

        updated_outcomes: list[InsightOutcome] = []
        today = date.today()

        for outcome in outcomes:
            try:
                # Get the symbol from the linked insight
                insight = await self.db.get(DeepInsight, outcome.insight_id)
                if not insight or not insight.primary_symbol:
                    logger.warning(
                        f"Outcome {outcome.id} has no linked insight or symbol"
                    )
                    continue

                symbol = insight.primary_symbol
                is_due = today >= outcome.tracking_end_date

                # Only ever look at data inside the window. Grading a "20-day"
                # call on 50 days of drift is what the old code did.
                window_end = min(today, outcome.tracking_end_date)
                series = await self._load_close_series(
                    symbol, outcome.tracking_start_date, window_end
                )
                if not series:
                    logger.warning(
                        f"No close series for {symbol} over "
                        f"{outcome.tracking_start_date}..{window_end}; "
                        f"leaving outcome {outcome.id} in TRACKING for retry"
                    )
                    continue

                direction = (outcome.predicted_direction or "").lower()
                level_event = self._scan_levels(series, insight, direction)

                if is_due or level_event:
                    outcome = await self._evaluate_outcome(
                        outcome, insight=insight, series=series
                    )
                else:
                    self._apply_path(outcome, series)
                    outcome.current_price = series[-1][1]

                updated_outcomes.append(outcome)

            except YahooFinanceError as e:
                logger.warning(f"Failed to update outcome {outcome.id}: {e}")
                continue
            except Exception as e:
                logger.error(f"Error updating outcome {outcome.id}: {e}")
                continue

        await self.db.commit()
        return updated_outcomes

    # ------------------------------------------------------------------
    # Price series loading
    # ------------------------------------------------------------------

    async def _load_close_series(
        self, symbol: str, start: date, end: date,
    ) -> list[tuple[date, float]]:
        """Load daily closes for ``symbol`` over [start, end], inclusive.

        Prefers the local ``price_history`` table and falls back to Yahoo when
        local data does not usably cover the window. Results are cached per
        instance.
        """
        if not symbol:
            return []
        cache_key = (symbol.upper(), start, end)
        if cache_key in self._series_cache:
            return self._series_cache[cache_key]

        series = await self._load_local_close_series(symbol, start, end)

        if not self._series_is_usable(series, start, end):
            try:
                rows = await self._yahoo_adapter.get_price_history(
                    symbol, start_date=start, end_date=end + timedelta(days=1),
                )
                fetched = [
                    (self._as_date(row["date"]), float(row["close"]))
                    for row in rows
                    if row.get("close") is not None and row.get("date") is not None
                ]
                fetched = [(d, c) for d, c in fetched if d and start <= d <= end]
                # Prefer a usable remote series over a longer but holed local
                # one; the local table is heavily gapped for recent months.
                if self._series_is_usable(fetched, start, end) or len(fetched) > len(
                    series
                ):
                    series = fetched
            except YahooFinanceError as e:
                logger.warning(f"Yahoo fallback failed for {symbol}: {e}")
            except Exception as e:  # noqa: BLE001 - never fail a grading pass
                logger.warning(f"Unexpected error fetching {symbol} history: {e}")

        series.sort(key=lambda point: point[0])
        self._series_cache[cache_key] = series
        return series

    async def _load_local_close_series(
        self, symbol: str, start: date, end: date,
    ) -> list[tuple[date, float]]:
        """Read daily closes for a symbol out of the local price_history table."""
        stmt = (
            select(PriceHistory.date, PriceHistory.close)
            .join(Stock, Stock.id == PriceHistory.stock_id)
            .where(
                Stock.symbol == symbol.upper(),
                PriceHistory.date >= start,
                PriceHistory.date <= end,
            )
            .order_by(PriceHistory.date)
        )
        rows = (await self.db.execute(stmt)).all()
        return [(row[0], float(row[1])) for row in rows if row[1] is not None]

    @staticmethod
    def _as_date(value: Any) -> date | None:
        """Coerce a datetime/date/ISO string into a plain date."""
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return None
        return None

    @staticmethod
    def _series_is_usable(
        series: list[tuple[date, float]], start: date, end: date,
    ) -> bool:
        """Whether a series really covers the window, holes included.

        Checking only the two endpoints is not enough. The local price_history
        table is badly gapped for recent months (SPY, for instance, has no bars
        at all in July 2026), so a window running from June to August finds a
        June bar at one end and an August bar at the other and looks complete
        while hiding a month-wide hole in between. Grading such a series would
        anchor the "end date" close to a price from weeks earlier without any
        error being raised, and would also stretch bar-indexed checkpoints
        across far more calendar time than the horizon they claim to measure.
        """
        if not series:
            return False
        grace = timedelta(days=_SERIES_EDGE_GRACE_DAYS)
        if series[0][0] > start + grace or series[-1][0] < end - grace:
            return False
        return all(
            (nxt[0] - prev[0]).days <= _MAX_SERIES_GAP_DAYS
            for prev, nxt in zip(series, series[1:])
        )

    @staticmethod
    def _close_on_or_before(
        series: list[tuple[date, float]], target: date,
    ) -> tuple[date, float] | None:
        """Last observation at or before ``target`` (handles weekends/holidays)."""
        candidates = [point for point in series if point[0] <= target]
        return candidates[-1] if candidates else None

    @staticmethod
    def _close_on_or_after(
        series: list[tuple[date, float]], target: date,
    ) -> tuple[date, float] | None:
        """First observation at or after ``target``."""
        for point in series:
            if point[0] >= target:
                return point
        return None

    async def _evaluate_outcome(
        self,
        outcome: InsightOutcome,
        insight: DeepInsight | None = None,
        series: list[tuple[date, float]] | None = None,
        benchmark_series: list[tuple[date, float]] | None = None,
    ) -> InsightOutcome:
        """Evaluate the final outcome of a tracked insight.

        Grading rules, in order of precedence:

        1. If the insight's own stop_loss was touched before its target_price,
           the thesis failed and is graded at the stop.
        2. If the target was touched first, the thesis is validated and graded
           at the target.
        3. Otherwise the thesis is graded on the close at ``tracking_end_date``
           (not on whatever the price happens to be when this runs), against
           the benchmark's move over the identical window.

        Args:
            outcome: The InsightOutcome to evaluate
            insight: Linked insight; loaded if not supplied
            series: Daily closes over the window; loaded if not supplied
            benchmark_series: Benchmark closes; loaded if not supplied

        Returns:
            Updated InsightOutcome with evaluation results. If no price data is
            available the outcome is left in TRACKING so a later pass retries.
        """
        if insight is None:
            insight = await self.db.get(DeepInsight, outcome.insight_id)

        start = outcome.tracking_start_date
        end = outcome.tracking_end_date
        symbol = insight.primary_symbol if insight else None

        if series is None:
            series = await self._load_close_series(symbol, start, end) if symbol else []

        if not series:
            # Refuse to invent a grade. Staying in TRACKING means the next pass
            # can still resolve it, since grading is retroactive.
            outcome.exit_reason = "no_data"
            logger.warning(
                f"Outcome {outcome.id}: no price data for {symbol} over "
                f"{start}..{end}; not graded"
            )
            return outcome

        predicted_direction = (outcome.predicted_direction or "").lower()

        # Record the full intraperiod path before deciding anything.
        self._apply_path(outcome, series, insight, predicted_direction)

        # Did the insight's own levels resolve the trade before the window end?
        level_event = self._scan_levels(series, insight, predicted_direction)
        if level_event:
            exit_reason, eval_date, final_price = level_event
        else:
            # Grading at the window end requires a close that is actually near
            # the window end. Falling back to series[-1] would silently grade a
            # July window on a June price when the series stops early.
            eval_point = self._close_on_or_before(series, end)
            if (
                eval_point is None
                or (end - eval_point[0]).days > _SERIES_EDGE_GRACE_DAYS
            ):
                outcome.exit_reason = "no_data"
                logger.warning(
                    f"Outcome {outcome.id}: no {symbol} close near {end} "
                    f"(nearest {eval_point[0] if eval_point else None}); not graded"
                )
                return outcome
            eval_date, final_price = eval_point
            exit_reason = "window_end"

        outcome.final_price = final_price
        outcome.current_price = final_price
        outcome.evaluated_price_date = eval_date
        outcome.exit_reason = exit_reason

        # Raw return, kept alongside alpha so both are visible.
        if outcome.initial_price and outcome.initial_price > 0:
            outcome.actual_return_pct = (
                (final_price - outcome.initial_price) / outcome.initial_price * 100
            )
        else:
            outcome.actual_return_pct = 0.0
        actual_return = outcome.actual_return_pct or 0.0

        # Benchmark over the identical window.
        if benchmark_series is None:
            benchmark_series = await self._load_close_series(
                _BENCHMARK_SYMBOL, start, end
            )
        bench_open = self._close_on_or_after(benchmark_series, start)
        bench_close = self._close_on_or_before(benchmark_series, eval_date)

        # Both benchmark anchors must sit near the dates they stand for; a
        # benchmark read weeks away from the window measures a different period
        # than the symbol leg and would corrupt alpha rather than correct it.
        grace = _SERIES_EDGE_GRACE_DAYS
        if bench_open and (bench_open[0] - start).days > grace:
            bench_open = None
        if bench_close and (eval_date - bench_close[0]).days > grace:
            bench_close = None

        benchmark_note = ""
        if bench_open and bench_close and bench_open[1] > 0:
            outcome.benchmark_symbol = _BENCHMARK_SYMBOL
            outcome.benchmark_initial_price = bench_open[1]
            outcome.benchmark_final_price = bench_close[1]
            outcome.benchmark_return_pct = (
                (bench_close[1] - bench_open[1]) / bench_open[1] * 100
            )
        else:
            # Do not silently fall back to raw-return scoring without saying so.
            outcome.benchmark_return_pct = None
            benchmark_note = " Benchmark unavailable; alpha falls back to raw return."

        alpha = actual_return - (outcome.benchmark_return_pct or 0.0)
        outcome.alpha_pct = round(alpha, 4)

        # A resolved stop or target settles the question on its own; otherwise
        # the alpha rule decides.
        if exit_reason == "target":
            outcome.thesis_validated = True
        elif exit_reason == "stop":
            outcome.thesis_validated = False
        else:
            outcome.thesis_validated = self._validate_thesis(
                predicted_direction, alpha
            )

        # Category is graded on alpha too, so it agrees with thesis_validated.
        outcome.outcome_category = self._categorize_return(
            alpha, predicted_direction
        ).value

        outcome.tracking_status = TrackingStatus.COMPLETED.value

        direction_text = {
            "bullish": "upward",
            "bearish": "downward",
            "neutral": "sideways",
        }.get(predicted_direction, "unknown")

        exit_text = {
            "target": "target reached",
            "stop": "stop loss hit",
            "window_end": "window closed",
        }.get(exit_reason, exit_reason)

        bench_return_text = (
            f"{outcome.benchmark_return_pct:.2f}%"
            if outcome.benchmark_return_pct is not None
            else "n/a"
        )
        outcome.validation_notes = (
            f"Predicted {direction_text} movement over {start}..{end}. "
            f"Graded at close on {eval_date} ({exit_text}). "
            f"Return: {actual_return:.2f}% vs {_BENCHMARK_SYMBOL} "
            f"{bench_return_text} -> alpha {alpha:+.2f}%. "
            f"Thesis {'validated' if outcome.thesis_validated else 'not validated'}."
            f"{benchmark_note}"
        )

        logger.info(
            f"Evaluated outcome {outcome.id}: return={actual_return:.2f}%, "
            f"alpha={alpha:+.2f}%, exit={exit_reason} on {eval_date}, "
            f"validated={outcome.thesis_validated}, "
            f"category={outcome.outcome_category}"
        )

        return outcome

    @staticmethod
    def _validate_thesis(predicted_direction: str, alpha_pct: float) -> bool:
        """Decide whether a thesis was correct, on benchmark-relative terms.

        The three rules tile the alpha axis without overlap or gaps:

        - bullish  wins when alpha >= +threshold
        - bearish  wins when alpha <= -threshold
        - neutral  wins when |alpha| <  threshold

        Neutral (HOLD/WATCH) is deliberately defined this way. The previous
        rule asked the stock to move less than 1% in absolute terms across the
        whole window, which almost nothing does, so HOLDs essentially never
        validated. Read as a claim, a HOLD says "this will not diverge
        meaningfully from the market" — exactly the region the directional
        rules leave unclaimed. Scoring it on alpha also keeps a HOLD from being
        punished for a market-wide selloff it did not predict, and still marks
        it wrong when the name runs away in either direction.
        """
        if predicted_direction == "bullish":
            return alpha_pct >= _ALPHA_THRESHOLD_PCT
        if predicted_direction == "bearish":
            return alpha_pct <= -_ALPHA_THRESHOLD_PCT
        if predicted_direction == "neutral":
            return abs(alpha_pct) < _ALPHA_THRESHOLD_PCT
        return False

    def _scan_levels(
        self,
        series: list[tuple[date, float]],
        insight: DeepInsight | None,
        predicted_direction: str,
    ) -> tuple[str, date, float] | None:
        """Find the first stop or target touch along the close path.

        Returns ``(exit_reason, date, price)`` or None if neither level was
        touched. Uses daily closes, so an intraday wick through a level is not
        counted — a deliberately conservative reading.
        """
        if insight is None or predicted_direction not in ("bullish", "bearish"):
            return None

        target = self._parse_price_range(insight.target_price)
        stop = self._parse_price_range(insight.stop_loss)
        if not target and not stop:
            return None

        for point_date, close in series:
            if predicted_direction == "bullish":
                if stop and close <= stop[0]:
                    return ("stop", point_date, close)
                if target and close >= target[1]:
                    return ("target", point_date, close)
            else:
                if stop and close >= stop[1]:
                    return ("stop", point_date, close)
                if target and close <= target[0]:
                    return ("target", point_date, close)
        return None

    def _apply_path(
        self,
        outcome: InsightOutcome,
        series: list[tuple[date, float]],
        insight: DeepInsight | None = None,
        predicted_direction: str = "",
    ) -> None:
        """Write the observed daily path onto the outcome.

        This is what makes max_favorable_move, max_adverse_move, the
        checkpoints and the trigger flags mean anything: previously a single
        spot price was appended in place, the mutation was never flushed, and
        every row kept exactly one entry forever.
        """
        outcome.price_history = [
            {"date": point_date.isoformat(), "price": round(close, 4)}
            for point_date, close in series
        ]

        initial = outcome.initial_price
        if not initial or initial <= 0:
            return

        returns = [(close - initial) / initial * 100 for _, close in series]
        if returns:
            outcome.max_favorable_move = round(max(returns), 4)
            outcome.max_adverse_move = round(min(returns), 4)

        checkpoints = dict(outcome.intermediate_checkpoints or {})
        for checkpoint_day in _CHECKPOINT_DAYS:
            if len(series) > checkpoint_day:
                _, close = series[checkpoint_day]
                checkpoints[f"{checkpoint_day}d"] = {
                    "price": round(close, 4),
                    "return_pct": round((close - initial) / initial * 100, 2),
                }
        outcome.intermediate_checkpoints = checkpoints

        if insight is None:
            return

        entry = self._parse_price_range(insight.entry_zone)
        if entry and any(entry[0] <= close <= entry[1] for _, close in series):
            outcome.entry_triggered = True

        level_event = self._scan_levels(series, insight, predicted_direction)
        if level_event and level_event[0] == "target":
            outcome.target_triggered = True
        elif level_event and level_event[0] == "stop":
            outcome.stop_triggered = True

    async def update_pattern_success_rates(self) -> int:
        """Update success rates for patterns linked to completed outcomes.

        Finds all completed outcomes with linked patterns and updates
        their success statistics using the KnowledgePattern.record_occurrence method.

        Returns:
            Count of patterns that were updated
        """
        # Query completed outcomes that have insight with research context
        query = (
            select(InsightOutcome)
            .where(InsightOutcome.tracking_status == TrackingStatus.COMPLETED.value)
        )
        result = await self.db.execute(query)
        completed_outcomes = result.scalars().all()

        patterns_updated = 0

        for outcome in completed_outcomes:
            # Get the linked insight to find pattern references
            insight = await self.db.get(DeepInsight, outcome.insight_id)
            if not insight or not insight.research_context:
                continue

            # Check if research context has pattern references
            research_context = insight.research_context

            # Read pattern IDs from the new identified_pattern_ids field
            pattern_ids = research_context.identified_pattern_ids
            if not pattern_ids:
                continue

            for pattern_id in pattern_ids:
                if not pattern_id:
                    continue

                try:
                    # Fetch and update the pattern
                    pattern = await self.db.get(KnowledgePattern, pattern_id)
                    if pattern:
                        pattern.record_occurrence(
                            was_successful=outcome.thesis_validated or False,
                            return_pct=outcome.actual_return_pct,
                        )
                        patterns_updated += 1
                        logger.debug(
                            f"Updated pattern {pattern_id} success rate: "
                            f"{pattern.success_rate:.2%}"
                        )
                except Exception as e:
                    logger.warning(f"Failed to update pattern {pattern_id}: {e}")
                    continue

        await self.db.commit()
        logger.info(f"Updated {patterns_updated} pattern success rates")
        return patterns_updated

    async def get_tracking_summary(self) -> dict[str, Any]:
        """Get a summary of all outcome tracking statistics.

        Every rate is returned as a ``_rate_block``, never as a bare float.
        A hit rate is not interpretable on its own: the same book of calls
        scored 40.5% on the stored 28-day windows and 32.9% on windows derived
        from each insight's own horizon, and moves ~10 points more depending on
        whether "correct" means alpha above a threshold or merely alpha above
        zero. Shipping the number without its ``n``, window basis, population
        and decision rule is how two measurements of the same system get
        compared as if they were the same measurement.

        Returns:
            Dictionary containing:
            - status_counts: Count of outcomes by tracking status
            - hit_rate: Rate block for overall thesis validation
            - direction_stats: Rate block per predicted direction
        """
        # Get counts by status
        status_query = (
            select(
                InsightOutcome.tracking_status,
                func.count(InsightOutcome.id).label("count")
            )
            .group_by(InsightOutcome.tracking_status)
        )
        status_result = await self.db.execute(status_query)
        status_counts = {
            row.tracking_status: row.count
            for row in status_result
        }

        # Calculate success rate for completed outcomes
        completed_query = (
            select(InsightOutcome)
            .where(InsightOutcome.tracking_status == TrackingStatus.COMPLETED.value)
        )
        completed_result = await self.db.execute(completed_query)
        completed_outcomes = completed_result.scalars().all()

        # Calculate hit rate by predicted direction
        direction_stats: dict[str, dict[str, Any]] = {}
        for direction in ("bullish", "bearish", "neutral"):
            direction_outcomes = [
                o for o in completed_outcomes
                if o.predicted_direction == direction
            ]
            if direction_outcomes:
                direction_stats[direction] = self._rate_block(
                    direction_outcomes, population=f"completed/{direction}"
                )

        return {
            "status_counts": status_counts,
            "hit_rate": self._rate_block(
                completed_outcomes, population="completed/all_directions"
            ),
            "direction_stats": direction_stats,
        }

    @staticmethod
    def _rate_block(
        outcomes: list[InsightOutcome], population: str,
    ) -> dict[str, Any]:
        """Package a hit rate together with everything needed to read it.

        The rate is deliberately not available as a bare float anywhere in this
        module's public output: ``n``, the window basis, the population it was
        computed over and the decision rule travel in the same object, so a
        number cannot be quoted without the context that makes it mean
        something. Two rates may only be compared when their ``window_basis``,
        ``population`` and ``decision_rule`` all match.
        """
        n = len(outcomes)
        validated = sum(1 for o in outcomes if o.thesis_validated)
        returns = [o.actual_return_pct for o in outcomes if o.actual_return_pct is not None]
        alphas = [o.alpha_pct for o in outcomes if o.alpha_pct is not None]

        return {
            "rate": validated / n if n else 0.0,
            "n": n,
            "validated": validated,
            "population": population,
            # Historical rows were tracked over whatever window start_tracking
            # recorded at the time; that is what these were graded on.
            "window_basis": "stored_tracking_dates",
            "decision_rule": (
                f"alpha vs {_BENCHMARK_SYMBOL} beyond "
                f"{_ALPHA_THRESHOLD_PCT}pp, stop/target terminates"
            ),
            "benchmark_symbol": _BENCHMARK_SYMBOL,
            "alpha_threshold_pct": _ALPHA_THRESHOLD_PCT,
            "avg_return_pct": sum(returns) / len(returns) if returns else 0.0,
            "avg_alpha_pct": sum(alphas) / len(alphas) if alphas else None,
            "graded_n": len(alphas),
        }

    # ------------------------------------------------------------------
    # Lifecycle management methods
    # ------------------------------------------------------------------

    async def check_lifecycle_states(self, db: AsyncSession) -> dict[str, Any]:
        """Check all active insights for staleness and lifecycle transitions."""
        query = (
            select(DeepInsight)
            .where(
                or_(
                    DeepInsight.lifecycle_state == "active",
                    DeepInsight.lifecycle_state == "re_evaluating",
                    DeepInsight.lifecycle_state.is_(None),
                )
            )
        )
        result = await db.execute(query)
        insights = result.scalars().all()

        transitions: list[dict[str, str]] = []
        now = datetime.utcnow()

        for insight in insights:
            staleness = await self.compute_staleness(insight)
            insight.staleness_score = staleness

            decay = await self.apply_conviction_decay(insight)
            insight.conviction_decay_factor = decay
            insight.effective_confidence = insight.compute_effective_confidence()
            insight.last_evaluated_at = now

            old_state = insight.lifecycle_state or "active"

            if staleness >= 1.0 and old_state == "active":
                insight.lifecycle_state = "expired"
                transitions.append({
                    "insight_id": str(insight.id),
                    "from": old_state,
                    "to": "expired",
                })
            elif staleness >= 0.7 and old_state == "active":
                insight.lifecycle_state = "stale"
                transitions.append({
                    "insight_id": str(insight.id),
                    "from": old_state,
                    "to": "stale",
                })

            # Check price-level triggers if outcome exists
            if insight.outcome and insight.outcome.tracking_status == TrackingStatus.TRACKING.value:
                triggers = await self.check_price_level_triggers(insight.outcome, insight)
                if triggers.get("entry_triggered"):
                    insight.outcome.entry_triggered = True
                if triggers.get("target_triggered"):
                    insight.outcome.target_triggered = True
                if triggers.get("stop_triggered"):
                    insight.outcome.stop_triggered = True
                await self.update_max_moves(insight.outcome)

        await db.commit()

        return {
            "insights_checked": len(insights),
            "transitions": transitions,
        }

    async def compute_staleness(self, insight: DeepInsight) -> float:
        """Compute staleness score (0-1) based on age vs time_horizon."""
        if not insight.created_at:
            return 0.0

        try:
            trading_days = self.resolve_horizon_days(insight.time_horizon)
        except ValueError:
            # Staleness is advisory, so an unreadable horizon degrades to a
            # default here rather than raising the way tracking does.
            trading_days = 20

        expected_days = trading_to_calendar_days(trading_days)

        age_days = (datetime.utcnow() - insight.created_at).total_seconds() / 86400
        staleness = min(1.0, age_days / expected_days)
        return round(staleness, 4)

    async def apply_conviction_decay(self, insight: DeepInsight) -> float:
        """Apply time-based conviction decay to insight confidence."""
        staleness = insight.staleness_score or 0.0
        decay = max(0.5, 1.0 - (staleness * 0.5))
        return round(decay, 4)

    async def check_price_level_triggers(
        self, outcome: InsightOutcome, insight: DeepInsight,
    ) -> dict[str, bool]:
        """Check if current price has hit entry_zone, target, or stop_loss."""
        current = outcome.current_price
        if current is None:
            return {"entry_triggered": False, "target_triggered": False, "stop_triggered": False}

        result = {"entry_triggered": False, "target_triggered": False, "stop_triggered": False}

        entry = self._parse_price_range(insight.entry_zone)
        if entry:
            low, high = entry
            if low <= current <= high:
                result["entry_triggered"] = True

        target = self._parse_price_range(insight.target_price)
        if target:
            target_low, target_high = target
            is_bullish = (insight.action or "").upper() in ("BUY", "STRONG_BUY")
            if is_bullish and current >= target_high:
                result["target_triggered"] = True
            elif not is_bullish and current <= target_low:
                result["target_triggered"] = True

        stop = self._parse_price_range(insight.stop_loss)
        if stop:
            stop_low, stop_high = stop
            is_bullish = (insight.action or "").upper() in ("BUY", "STRONG_BUY")
            if is_bullish and current <= stop_low:
                result["stop_triggered"] = True
            elif not is_bullish and current >= stop_high:
                result["stop_triggered"] = True

        return result

    async def record_intermediate_checkpoint(
        self, outcome: InsightOutcome, checkpoint_day: int,
    ) -> None:
        """Record price at checkpoint intervals (5d, 10d, 20d, 40d)."""
        if outcome.initial_price is None or outcome.initial_price == 0:
            return
        current = outcome.current_price
        if current is None:
            return

        return_pct = round((current - outcome.initial_price) / outcome.initial_price * 100, 2)
        key = f"{checkpoint_day}d"

        checkpoints = dict(outcome.intermediate_checkpoints or {})
        checkpoints[key] = {"price": current, "return_pct": return_pct}
        outcome.intermediate_checkpoints = checkpoints

    async def update_max_moves(self, outcome: InsightOutcome) -> None:
        """Update max favorable/adverse move tracking."""
        if outcome.initial_price is None or outcome.initial_price == 0:
            return
        current = outcome.current_price
        if current is None:
            return

        return_pct = (current - outcome.initial_price) / outcome.initial_price * 100

        if outcome.max_favorable_move is None or return_pct > outcome.max_favorable_move:
            outcome.max_favorable_move = round(return_pct, 4)
        if outcome.max_adverse_move is None or return_pct < outcome.max_adverse_move:
            outcome.max_adverse_move = round(return_pct, 4)

    @staticmethod
    def _parse_price_range(price_str: str | None) -> tuple[float, float] | None:
        """Parse a price level string such as '$150-155' or '$150' into (low, high).

        These strings are LLM-written prose, not clean numerics, so the naive
        "take the first two numbers and sort them" approach mangles them:
        ``"$370 on confirmation of SMA_50"`` became the range (50, 370) with a
        midpoint of $210, and any level check against it was meaningless.

        The parser therefore strips tokens that are numeric but are plainly not
        prices — indicator periods (SMA_50, RSI(14)), timeframes ("within 3
        months") and percentages — and then prefers explicitly ``$``-prefixed
        numbers over bare ones.
        """
        if not price_str:
            return None

        cleaned = price_str
        # Indicator references: SMA_50, SMA 50, EMA-20, RSI(14), ATR(14), BB(20)
        cleaned = re.sub(
            r"\b(?:SMA|EMA|WMA|MA|RSI|MACD|ATR|ADX|VWAP|BB|DMA)\s*[_\-]?\s*"
            r"\(?\s*\d+(?:\.\d+)?\s*\)?",
            " ",
            cleaned,
            flags=re.IGNORECASE,
        )
        # Timeframes: "3 months", "2 weeks", "10 sessions", "5d"
        cleaned = re.sub(
            r"\b\d+(?:\.\d+)?\s*[-–]?\s*"
            r"(?:day|days|week|weeks|month|months|quarter|quarters|year|years|"
            r"session|sessions|hr|hrs|hour|hours|d|w|mo|yr)\b",
            " ",
            cleaned,
            flags=re.IGNORECASE,
        )
        # Percentages: "8%", "12.5 %"
        cleaned = re.sub(r"\b\d+(?:\.\d+)?\s*%", " ", cleaned)

        number = r"\d+(?:\.\d+)?"

        # An explicit $-anchored range: "$150-155", "$150 to $155"
        range_match = re.search(
            rf"\$\s*({number})\s*(?:[-–—]|to)\s*\$?\s*({number})",
            cleaned,
            flags=re.IGNORECASE,
        )
        if range_match:
            low, high = float(range_match.group(1)), float(range_match.group(2))
            return (min(low, high), max(low, high))

        # Otherwise prefer $-prefixed numbers; they are unambiguously prices.
        dollar_values = [float(n) for n in re.findall(rf"\$\s*({number})", cleaned)]
        if dollar_values:
            if len(dollar_values) == 1:
                return (dollar_values[0], dollar_values[0])
            low, high = dollar_values[0], dollar_values[1]
            return (min(low, high), max(low, high))

        # No currency markers at all — fall back to bare numbers in the
        # cleaned string (so "150-155" still parses).
        values = [float(n) for n in re.findall(number, cleaned)]
        if not values:
            return None
        if len(values) == 1:
            return (values[0], values[0])
        return (min(values[0], values[1]), max(values[0], values[1]))

    def _categorize_return(
        self,
        return_pct: float,
        predicted_direction: str,
    ) -> OutcomeCategory:
        """Categorize a benchmark-relative return (alpha) into an OutcomeCategory.

        Callers pass alpha, not raw return, so the category describes skill
        rather than market drift. Band edges are pinned to the same threshold
        that decides ``thesis_validated``, so the two never disagree: for a
        directional call the SUCCESS-family categories are exactly the
        validated region.

        Args:
            return_pct: Alpha in percentage points (symbol return - benchmark)
            predicted_direction: "bullish", "bearish", or "neutral"

        Returns:
            Appropriate OutcomeCategory enum value
        """
        # Normalize direction
        direction = predicted_direction.lower()

        # For neutral predictions, categorize by absolute deviation from the
        # benchmark: staying inside the band is the prediction.
        if direction == "neutral":
            abs_return = abs(return_pct)
            if abs_return < _ALPHA_THRESHOLD_PCT:
                return OutcomeCategory.SUCCESS
            elif abs_return <= 2 * _ALPHA_THRESHOLD_PCT:
                return OutcomeCategory.PARTIAL_FAILURE
            elif abs_return <= 10.0:
                return OutcomeCategory.FAILURE
            else:
                return OutcomeCategory.STRONG_FAILURE

        # For directional predictions, calculate effective alpha
        # (positive if in predicted direction, negative if against)
        if direction == "bullish":
            effective_return = return_pct
        elif direction == "bearish":
            effective_return = -return_pct  # Invert: negative actual = positive effective
        else:
            effective_return = return_pct  # Fallback

        # Categorize based on effective alpha
        if effective_return > 10.0:
            return OutcomeCategory.STRONG_SUCCESS
        elif effective_return > 5.0:
            return OutcomeCategory.SUCCESS
        elif effective_return >= _ALPHA_THRESHOLD_PCT:
            return OutcomeCategory.PARTIAL_SUCCESS
        elif effective_return > -_ALPHA_THRESHOLD_PCT:
            return OutcomeCategory.NEUTRAL
        elif effective_return >= -5.0:
            return OutcomeCategory.PARTIAL_FAILURE
        elif effective_return >= -10.0:
            return OutcomeCategory.FAILURE
        else:
            return OutcomeCategory.STRONG_FAILURE


# Convenience function to create tracker with session
def create_outcome_tracker(db: AsyncSession) -> InsightOutcomeTracker:
    """Create an InsightOutcomeTracker with the given database session.

    Args:
        db: Async database session

    Returns:
        Configured InsightOutcomeTracker instance
    """
    return InsightOutcomeTracker(db)
