"""ThematicOutcomeTracker service for basket-level thesis validation.

Tracks thematic insight predictions by monitoring a basket of symbols,
calculating composite metrics (direction agreement, avg return, best-of-basket),
and evaluating thesis validation using weighted scoring.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from data.adapters.yahoo import YahooFinanceAdapter, YahooFinanceError
from models.insight_outcome import OutcomeCategory, TrackingStatus
from models.knowledge_pattern import KnowledgePattern, PatternType
from models.thematic_insight import LifecycleState, ThematicInsight
from models.thematic_outcome import ThematicOutcome

logger = logging.getLogger(__name__)

# Catalyst timeline to trading days mapping
_TIMELINE_DAYS: dict[str, int] = {
    "near_term": 40,
    "medium_term": 120,
    "long_term": 252,
}

# Checkpoint intervals in trading days
_CHECKPOINT_DAYS = (10, 20, 40, 80, 120)

# Composite score weights
WEIGHT_DIRECTION = 0.4
WEIGHT_AVG_RETURN = 0.4
WEIGHT_BEST_RETURN = 0.2


class ThematicOutcomeTracker:
    """Service for tracking and evaluating thematic thesis outcomes.

    Manages the complete lifecycle of thematic outcome validation:
    1. Start tracking when a thematic insight is persisted
    2. Periodically update prices for all basket symbols
    3. Evaluate basket-level outcome when tracking period ends
    4. Update SUPPLY_CHAIN pattern success rates from results
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._yahoo_adapter = YahooFinanceAdapter()

    async def start_tracking(
        self,
        insight_id: Any,
        symbols: list[str],
        predicted_direction: str,
        catalyst_timeline: str = "medium_term",
    ) -> ThematicOutcome:
        """Start tracking a thematic insight's basket of symbols.

        Args:
            insight_id: UUID of the ThematicInsight to track.
            symbols: List of symbols in the basket.
            predicted_direction: "bullish", "bearish", or "mixed".
            catalyst_timeline: near_term/medium_term/long_term.

        Returns:
            Created ThematicOutcome record.
        """
        tracking_days = _TIMELINE_DAYS.get(catalyst_timeline, 120)
        calendar_days = int(tracking_days * 7 / 5)
        tracking_start = date.today()
        tracking_end = tracking_start + timedelta(days=calendar_days)

        # Fetch initial prices for all symbols
        symbol_tracking: dict[str, Any] = {}
        for symbol in symbols:
            try:
                price_data = await self._yahoo_adapter.get_current_price(symbol)
                initial_price = price_data["price"]
                symbol_tracking[symbol] = {
                    "initial_price": initial_price,
                    "current_price": initial_price,
                    "final_price": None,
                    "return_pct": 0.0,
                    "direction_correct": None,
                    "price_history": [
                        {"date": tracking_start.isoformat(), "price": initial_price}
                    ],
                }
            except YahooFinanceError as e:
                logger.warning(f"Could not fetch price for {symbol}: {e}")
                continue

        if not symbol_tracking:
            raise ValueError(f"Could not fetch initial prices for any symbols: {symbols}")

        outcome = ThematicOutcome(
            thematic_insight_id=insight_id,
            tracking_status=TrackingStatus.TRACKING.value,
            tracking_start_date=tracking_start,
            tracking_end_date=tracking_end,
            predicted_direction=predicted_direction.lower(),
            symbol_tracking=symbol_tracking,
            symbols_tracked=len(symbol_tracking),
        )

        self.db.add(outcome)
        await self.db.flush()
        await self.db.refresh(outcome)

        logger.info(
            f"Started thematic tracking for insight {insight_id}: "
            f"{len(symbol_tracking)}/{len(symbols)} symbols, end_date={tracking_end}"
        )
        return outcome

    async def check_outcomes(self) -> list[ThematicOutcome]:
        """Check and update all active thematic outcome tracking records.

        Returns:
            List of updated ThematicOutcome records.
        """
        query = select(ThematicOutcome).where(
            ThematicOutcome.tracking_status == TrackingStatus.TRACKING.value
        )
        result = await self.db.execute(query)
        outcomes = result.scalars().all()

        updated: list[ThematicOutcome] = []
        today = date.today()

        for outcome in outcomes:
            try:
                symbol_tracking = dict(outcome.symbol_tracking or {})
                for symbol, data in symbol_tracking.items():
                    try:
                        price_data = await self._yahoo_adapter.get_current_price(symbol)
                        current_price = price_data["price"]
                        data["current_price"] = current_price
                        history = data.get("price_history", [])
                        history.append({"date": today.isoformat(), "price": current_price})
                        data["price_history"] = history

                        # Calculate running return
                        initial = data.get("initial_price", 0)
                        if initial and initial > 0:
                            data["return_pct"] = round(
                                (current_price - initial) / initial * 100, 4
                            )
                    except YahooFinanceError as e:
                        logger.warning(f"Failed to update {symbol}: {e}")
                        continue

                outcome.symbol_tracking = symbol_tracking
                self._update_basket_metrics(outcome)
                self._update_extrema(outcome)

                # Record checkpoint if applicable
                days_elapsed = (today - outcome.tracking_start_date).days
                trading_days = int(days_elapsed * 5 / 7)
                for cp in _CHECKPOINT_DAYS:
                    if abs(trading_days - cp) <= 1:
                        self._record_checkpoint(outcome, cp)

                # Evaluate if tracking period ended
                if today >= outcome.tracking_end_date:
                    self._evaluate_outcome(outcome)

                updated.append(outcome)

            except Exception as e:
                logger.error(f"Error updating thematic outcome {outcome.id}: {e}")
                continue

        await self.db.commit()
        return updated

    def _update_basket_metrics(self, outcome: ThematicOutcome) -> None:
        """Recalculate basket-level aggregate metrics."""
        tracking = outcome.symbol_tracking or {}
        if not tracking:
            return

        returns = []
        direction = outcome.predicted_direction.lower()

        for data in tracking.values():
            ret = data.get("return_pct")
            if ret is not None:
                returns.append(ret)
                # Determine direction correctness
                if direction == "bullish":
                    data["direction_correct"] = ret > 0
                elif direction == "bearish":
                    data["direction_correct"] = ret < 0
                else:  # mixed
                    data["direction_correct"] = abs(ret) > 1.0

        if returns:
            outcome.basket_avg_return_pct = round(sum(returns) / len(returns), 4)
            outcome.best_symbol_return_pct = round(max(returns), 4)
            outcome.worst_symbol_return_pct = round(min(returns), 4)

        correct_count = sum(
            1 for d in tracking.values() if d.get("direction_correct") is True
        )
        total = len(tracking)
        if total > 0:
            outcome.direction_agreement_rate = round(correct_count / total, 4)

    def _update_extrema(self, outcome: ThematicOutcome) -> None:
        """Update max favorable/adverse basket return."""
        avg = outcome.basket_avg_return_pct
        if avg is None:
            return
        if outcome.max_favorable_basket_return is None or avg > outcome.max_favorable_basket_return:
            outcome.max_favorable_basket_return = round(avg, 4)
        if outcome.max_adverse_basket_return is None or avg < outcome.max_adverse_basket_return:
            outcome.max_adverse_basket_return = round(avg, 4)

    def _record_checkpoint(self, outcome: ThematicOutcome, checkpoint_day: int) -> None:
        """Record basket metrics at a checkpoint interval."""
        checkpoints = dict(outcome.intermediate_checkpoints or {})
        key = f"{checkpoint_day}d"
        if key in checkpoints:
            return  # Already recorded
        checkpoints[key] = {
            "avg_return": outcome.basket_avg_return_pct,
            "direction_agreement": outcome.direction_agreement_rate,
            "best_return": outcome.best_symbol_return_pct,
            "worst_return": outcome.worst_symbol_return_pct,
        }
        outcome.intermediate_checkpoints = checkpoints

    def _evaluate_outcome(self, outcome: ThematicOutcome) -> None:
        """Evaluate final basket outcome and set validation results."""
        tracking = outcome.symbol_tracking or {}

        # Finalize per-symbol data
        for data in tracking.values():
            data["final_price"] = data.get("current_price")
            initial = data.get("initial_price", 0)
            final = data.get("final_price", 0)
            if initial and initial > 0 and final:
                data["return_pct"] = round((final - initial) / initial * 100, 4)

        outcome.symbol_tracking = tracking
        self._update_basket_metrics(outcome)

        # Calculate composite score
        dir_rate = outcome.direction_agreement_rate or 0.0
        avg_ret = outcome.basket_avg_return_pct or 0.0
        best_ret = outcome.best_symbol_return_pct or 0.0

        # Normalize returns to 0-1 scale for scoring
        # Cap at +/-30% for normalization
        norm_avg = min(1.0, max(0.0, (avg_ret + 30) / 60))
        norm_best = min(1.0, max(0.0, (best_ret + 30) / 60))

        # For bearish predictions, invert the return normalization
        if outcome.predicted_direction.lower() == "bearish":
            norm_avg = 1.0 - norm_avg
            norm_best = 1.0 - norm_best

        composite = (
            WEIGHT_DIRECTION * dir_rate
            + WEIGHT_AVG_RETURN * norm_avg
            + WEIGHT_BEST_RETURN * norm_best
        )
        outcome.composite_score = round(composite, 4)

        # Categorize
        outcome.outcome_category = self._categorize_basket_return(composite).value
        outcome.thesis_validated = composite >= 0.6

        # Mark complete
        outcome.tracking_status = TrackingStatus.COMPLETED.value

        # Validation notes
        outcome.validation_notes = (
            f"Basket of {outcome.symbols_tracked} symbols. "
            f"Direction agreement: {dir_rate:.0%}. "
            f"Avg return: {avg_ret:+.2f}%. "
            f"Composite score: {composite:.2f}. "
            f"Thesis {'validated' if outcome.thesis_validated else 'not validated'}."
        )

        logger.info(
            f"Evaluated thematic outcome {outcome.id}: "
            f"composite={composite:.2f}, validated={outcome.thesis_validated}"
        )

    @staticmethod
    def _categorize_basket_return(composite_score: float) -> OutcomeCategory:
        """Map composite score to OutcomeCategory (adjusted for baskets)."""
        if composite_score >= 0.8:
            return OutcomeCategory.STRONG_SUCCESS
        elif composite_score >= 0.65:
            return OutcomeCategory.SUCCESS
        elif composite_score >= 0.55:
            return OutcomeCategory.PARTIAL_SUCCESS
        elif composite_score >= 0.45:
            return OutcomeCategory.NEUTRAL
        elif composite_score >= 0.35:
            return OutcomeCategory.PARTIAL_FAILURE
        elif composite_score >= 0.2:
            return OutcomeCategory.FAILURE
        else:
            return OutcomeCategory.STRONG_FAILURE

    async def get_tracking_summary(self) -> dict[str, Any]:
        """Get aggregate statistics for thematic outcome tracking."""
        status_query = (
            select(
                ThematicOutcome.tracking_status,
                func.count(ThematicOutcome.id).label("count"),
            )
            .group_by(ThematicOutcome.tracking_status)
        )
        status_result = await self.db.execute(status_query)
        status_counts = {row.tracking_status: row.count for row in status_result}

        # Completed outcomes
        completed_query = select(ThematicOutcome).where(
            ThematicOutcome.tracking_status == TrackingStatus.COMPLETED.value
        )
        completed_result = await self.db.execute(completed_query)
        completed = completed_result.scalars().all()

        total_completed = len(completed)
        validated = sum(1 for o in completed if o.thesis_validated)
        success_rate = validated / total_completed if total_completed > 0 else 0.0

        composites = [o.composite_score for o in completed if o.composite_score is not None]
        avg_composite = sum(composites) / len(composites) if composites else 0.0

        basket_returns = [o.basket_avg_return_pct for o in completed if o.basket_avg_return_pct is not None]
        avg_basket = sum(basket_returns) / len(basket_returns) if basket_returns else 0.0

        agreements = [o.direction_agreement_rate for o in completed if o.direction_agreement_rate is not None]
        avg_agreement = sum(agreements) / len(agreements) if agreements else 0.0

        return {
            "status_counts": status_counts,
            "total_tracked": sum(status_counts.values()),
            "currently_tracking": status_counts.get(TrackingStatus.TRACKING.value, 0),
            "completed": total_completed,
            "success_rate": round(success_rate, 4),
            "avg_composite_score": round(avg_composite, 4),
            "avg_basket_return": round(avg_basket, 4),
            "avg_direction_agreement": round(avg_agreement, 4),
        }

    async def check_lifecycle_states(self, db: AsyncSession) -> dict[str, Any]:
        """Check all active thematic insights for staleness and lifecycle transitions."""
        query = select(ThematicInsight).where(
            or_(
                ThematicInsight.lifecycle_state == LifecycleState.ACTIVE.value,
                ThematicInsight.lifecycle_state.is_(None),
            )
        )
        result = await db.execute(query)
        insights = result.scalars().all()

        transitions: list[dict[str, str]] = []
        now = datetime.utcnow()

        for insight in insights:
            timeline_days = _TIMELINE_DAYS.get(insight.catalyst_timeline, 120)
            if not insight.created_at:
                continue

            age_days = (now - insight.created_at).total_seconds() / 86400
            staleness = min(1.0, age_days / timeline_days)
            insight.staleness_score = round(staleness, 4)

            decay = max(0.5, 1.0 - (staleness * 0.5))
            insight.conviction_decay_factor = round(decay, 4)
            insight.effective_confidence = insight.compute_effective_confidence()
            insight.last_evaluated_at = now

            old_state = insight.lifecycle_state or LifecycleState.ACTIVE.value

            if staleness >= 1.0 and old_state == LifecycleState.ACTIVE.value:
                insight.lifecycle_state = LifecycleState.EXPIRED.value
                transitions.append({
                    "insight_id": str(insight.id),
                    "from": old_state,
                    "to": LifecycleState.EXPIRED.value,
                })
            elif staleness >= 0.7 and old_state == LifecycleState.ACTIVE.value:
                insight.lifecycle_state = LifecycleState.STALE.value
                transitions.append({
                    "insight_id": str(insight.id),
                    "from": old_state,
                    "to": LifecycleState.STALE.value,
                })

        await db.commit()

        return {
            "insights_checked": len(insights),
            "transitions": transitions,
        }

    async def update_pattern_success_rates(self) -> int:
        """Update SUPPLY_CHAIN KnowledgePatterns from completed thematic outcomes."""
        query = select(ThematicOutcome).where(
            ThematicOutcome.tracking_status == TrackingStatus.COMPLETED.value
        )
        result = await self.db.execute(query)
        completed = result.scalars().all()

        patterns_updated = 0

        for outcome in completed:
            # Find SUPPLY_CHAIN patterns with overlapping symbols
            insight = await self.db.get(ThematicInsight, outcome.thematic_insight_id)
            if not insight:
                continue

            pattern_query = select(KnowledgePattern).where(
                and_(
                    KnowledgePattern.pattern_type == PatternType.SUPPLY_CHAIN.value,
                    KnowledgePattern.is_active.is_(True),
                )
            )
            pattern_result = await self.db.execute(pattern_query)
            patterns = pattern_result.scalars().all()

            for pattern in patterns:
                related_syms = set(pattern.related_symbols or [])
                insight_syms = set(insight.primary_symbols or [])
                if related_syms & insight_syms:
                    pattern.record_occurrence(
                        was_successful=outcome.thesis_validated or False,
                        return_pct=outcome.basket_avg_return_pct,
                    )
                    patterns_updated += 1

        await self.db.commit()
        logger.info(f"Updated {patterns_updated} SUPPLY_CHAIN patterns from thematic outcomes")
        return patterns_updated

    async def get_thematic_accuracy(
        self,
        category: str | None = None,
        lookback_days: int = 180,
    ) -> dict[str, Any]:
        """Get thematic track record accuracy for confidence calibration.

        Args:
            category: Optional category filter.
            lookback_days: How far back to look.

        Returns:
            Dict with total, validated, accuracy, avg_composite.
        """
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)

        query = (
            select(ThematicOutcome, ThematicInsight)
            .join(ThematicInsight, ThematicOutcome.thematic_insight_id == ThematicInsight.id)
            .where(
                and_(
                    ThematicOutcome.tracking_status == TrackingStatus.COMPLETED.value,
                    ThematicOutcome.created_at >= cutoff,
                )
            )
        )
        if category:
            query = query.where(ThematicInsight.category == category)

        result = await self.db.execute(query)
        rows = result.all()

        total = len(rows)
        validated = sum(1 for r in rows if r[0].thesis_validated)
        accuracy = validated / total if total > 0 else 0.0

        composites = [r[0].composite_score for r in rows if r[0].composite_score is not None]
        avg_composite = sum(composites) / len(composites) if composites else 0.0

        return {
            "total": total,
            "validated": validated,
            "accuracy": round(accuracy, 4),
            "avg_composite": round(avg_composite, 4),
        }


def create_thematic_outcome_tracker(db: AsyncSession) -> ThematicOutcomeTracker:
    """Factory function to create a ThematicOutcomeTracker."""
    return ThematicOutcomeTracker(db)
