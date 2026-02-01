"""InsightOutcomeTracker service for tracking and evaluating insight predictions.

This service manages the lifecycle of insight outcome tracking, from initiating
tracking when an insight is generated, to evaluating the final outcome after
the tracking period ends.
"""

import logging
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from data.adapters.yahoo import YahooFinanceAdapter, YahooFinanceError
from models.deep_insight import DeepInsight
from models.insight_outcome import InsightOutcome, OutcomeCategory, TrackingStatus
from models.knowledge_pattern import KnowledgePattern

logger = logging.getLogger(__name__)


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
            if not hasattr(research_context, "identified_patterns"):
                continue

            pattern_refs = getattr(research_context, "identified_patterns", [])
            if not pattern_refs:
                continue

            for pattern_ref in pattern_refs:
                # Extract pattern ID from reference (could be UUID or dict)
                pattern_id = None
                if isinstance(pattern_ref, dict):
                    pattern_id = pattern_ref.get("pattern_id")
                elif isinstance(pattern_ref, (str, UUID)):
                    pattern_id = pattern_ref

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
