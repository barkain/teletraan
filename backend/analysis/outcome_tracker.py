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

from data.adapters.yahoo import YahooFinanceAdapter, YahooFinanceError
from models.deep_insight import DeepInsight
from models.insight_outcome import InsightOutcome, OutcomeCategory, TrackingStatus
from models.knowledge_pattern import KnowledgePattern

logger = logging.getLogger(__name__)

# Time horizon string to approximate days mapping
_HORIZON_DAYS: dict[str, int] = {
    "1-2 weeks": 10,
    "2-4 weeks": 21,
    "1-3 months": 60,
    "3-6 months": 120,
    "6-12 months": 270,
}

# Checkpoint intervals in trading days
_CHECKPOINT_DAYS = (5, 10, 20, 40)


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

    async def start_tracking(
        self,
        insight_id: int,
        symbol: str,
        predicted_direction: str,
        tracking_days: int = 20,
    ) -> InsightOutcome:
        """Start tracking an insight's prediction outcome.

        Creates a new InsightOutcome record to track the price movement
        from today until the end of the tracking period.

        Args:
            insight_id: ID of the DeepInsight being tracked
            symbol: Stock symbol to track (e.g., "AAPL")
            predicted_direction: "bullish", "bearish", or "neutral"
            tracking_days: Number of trading days to track (default 20 = ~1 month)

        Returns:
            Created InsightOutcome record

        Raises:
            ValueError: If insight not found or symbol invalid
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

        # Fetch initial price from market data
        try:
            price_data = await self._yahoo_adapter.get_current_price(symbol)
            initial_price = price_data["price"]
        except YahooFinanceError as e:
            logger.error(f"Failed to fetch initial price for {symbol}: {e}")
            raise

        # Calculate tracking end date (approximate trading days)
        # Assume ~5 trading days per week
        calendar_days = int(tracking_days * 7 / 5)
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
        - Fetches current price and updates current_price
        - If tracking period has ended, evaluates the final outcome

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

                # Fetch current price
                price_data = await self._yahoo_adapter.get_current_price(symbol)
                current_price = price_data["price"]

                # Update current price and price history
                outcome.current_price = current_price
                if outcome.price_history is None:
                    outcome.price_history = []
                outcome.price_history.append({
                    "date": today.isoformat(),
                    "price": current_price,
                })

                # Check if tracking period has ended
                if today >= outcome.tracking_end_date:
                    outcome = await self._evaluate_outcome(outcome)

                updated_outcomes.append(outcome)

            except YahooFinanceError as e:
                logger.warning(f"Failed to update outcome {outcome.id}: {e}")
                continue
            except Exception as e:
                logger.error(f"Error updating outcome {outcome.id}: {e}")
                continue

        await self.db.commit()
        return updated_outcomes

    async def _evaluate_outcome(self, outcome: InsightOutcome) -> InsightOutcome:
        """Evaluate the final outcome of a tracked insight.

        Sets final price, calculates actual return, determines if thesis
        was validated, and assigns outcome category.

        Args:
            outcome: The InsightOutcome to evaluate

        Returns:
            Updated InsightOutcome with evaluation results
        """
        # Set final price from current price
        outcome.final_price = outcome.current_price

        # Calculate actual return percentage
        if outcome.initial_price and outcome.initial_price > 0:
            outcome.actual_return_pct = (
                (outcome.final_price - outcome.initial_price)
                / outcome.initial_price
                * 100
            )
        else:
            outcome.actual_return_pct = 0.0

        # Determine if thesis was validated based on predicted direction
        actual_return = outcome.actual_return_pct or 0.0
        predicted_direction = outcome.predicted_direction.lower()

        if predicted_direction == "bullish":
            outcome.thesis_validated = actual_return > 1.0
        elif predicted_direction == "bearish":
            outcome.thesis_validated = actual_return < -1.0
        elif predicted_direction == "neutral":
            outcome.thesis_validated = -1.0 <= actual_return <= 1.0
        else:
            outcome.thesis_validated = False

        # Categorize the outcome
        outcome.outcome_category = self._categorize_return(
            actual_return, predicted_direction
        ).value

        # Mark tracking as complete
        outcome.tracking_status = TrackingStatus.COMPLETED.value

        # Generate validation notes
        direction_text = {
            "bullish": "upward",
            "bearish": "downward",
            "neutral": "sideways"
        }.get(predicted_direction, "unknown")

        outcome.validation_notes = (
            f"Predicted {direction_text} movement. "
            f"Actual return: {actual_return:.2f}%. "
            f"Thesis {'validated' if outcome.thesis_validated else 'not validated'}."
        )

        logger.info(
            f"Evaluated outcome {outcome.id}: "
            f"return={actual_return:.2f}%, validated={outcome.thesis_validated}, "
            f"category={outcome.outcome_category}"
        )

        return outcome

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

        Returns:
            Dictionary containing:
            - status_counts: Count of outcomes by tracking status
            - success_rate: Overall thesis validation rate for completed outcomes
            - direction_stats: Average returns by predicted direction
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

        total_completed = len(completed_outcomes)
        validated_count = sum(
            1 for o in completed_outcomes if o.thesis_validated
        )
        success_rate = (
            validated_count / total_completed if total_completed > 0 else 0.0
        )

        # Calculate average return by predicted direction
        direction_stats: dict[str, dict[str, Any]] = {}
        for direction in ("bullish", "bearish", "neutral"):
            direction_outcomes = [
                o for o in completed_outcomes
                if o.predicted_direction == direction
            ]
            if direction_outcomes:
                returns = [
                    o.actual_return_pct
                    for o in direction_outcomes
                    if o.actual_return_pct is not None
                ]
                direction_stats[direction] = {
                    "count": len(direction_outcomes),
                    "avg_return_pct": (
                        sum(returns) / len(returns) if returns else 0.0
                    ),
                    "validated_count": sum(
                        1 for o in direction_outcomes if o.thesis_validated
                    ),
                }

        return {
            "status_counts": status_counts,
            "total_completed": total_completed,
            "validated_count": validated_count,
            "success_rate": success_rate,
            "direction_stats": direction_stats,
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

        horizon_str = (insight.time_horizon or "").lower().strip()
        expected_days = _HORIZON_DAYS.get(horizon_str)

        if expected_days is None:
            # Try to extract from freeform text like "2 weeks", "3 months"
            for key, days in _HORIZON_DAYS.items():
                if key in horizon_str:
                    expected_days = days
                    break
            if expected_days is None:
                expected_days = 30  # default fallback

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
        """Parse '$150-155' or '$150' into (low, high) tuple."""
        if not price_str:
            return None
        # Extract all numbers (int or float) from the string
        numbers = re.findall(r"[\d]+(?:\.[\d]+)?", price_str)
        if not numbers:
            return None
        values = [float(n) for n in numbers]
        if len(values) == 1:
            return (values[0], values[0])
        return (min(values[0], values[1]), max(values[0], values[1]))

    def _categorize_return(
        self,
        return_pct: float,
        predicted_direction: str,
    ) -> OutcomeCategory:
        """Categorize the return percentage into an OutcomeCategory.

        The categorization accounts for the predicted direction:
        - For bullish predictions: positive returns are success, negative are failure
        - For bearish predictions: negative returns are success, positive are failure
        - For neutral predictions: small moves are success, large moves are failure

        Args:
            return_pct: Actual return percentage
            predicted_direction: "bullish", "bearish", or "neutral"

        Returns:
            Appropriate OutcomeCategory enum value
        """
        # Normalize direction
        direction = predicted_direction.lower()

        # For neutral predictions, categorize by absolute deviation from zero
        if direction == "neutral":
            abs_return = abs(return_pct)
            if abs_return <= 1.0:
                return OutcomeCategory.SUCCESS
            elif abs_return <= 3.0:
                return OutcomeCategory.PARTIAL_SUCCESS
            elif abs_return <= 5.0:
                return OutcomeCategory.PARTIAL_FAILURE
            elif abs_return <= 10.0:
                return OutcomeCategory.FAILURE
            else:
                return OutcomeCategory.STRONG_FAILURE

        # For directional predictions, calculate effective return
        # (positive if in predicted direction, negative if against)
        if direction == "bullish":
            effective_return = return_pct
        elif direction == "bearish":
            effective_return = -return_pct  # Invert: negative actual = positive effective
        else:
            effective_return = return_pct  # Fallback

        # Categorize based on effective return
        if effective_return > 10.0:
            return OutcomeCategory.STRONG_SUCCESS
        elif effective_return > 5.0:
            return OutcomeCategory.SUCCESS
        elif effective_return > 1.0:
            return OutcomeCategory.PARTIAL_SUCCESS
        elif effective_return >= -1.0:
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
