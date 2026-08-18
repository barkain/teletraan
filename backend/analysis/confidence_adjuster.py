"""ConfidenceAdjuster service for adjusting insight confidence based on historical track record.

This module provides the ConfidenceAdjuster class that adjusts analyst-generated
confidence scores using historical performance data from InsightOutcome records
and KnowledgePattern success rates.

The adjustment is a normalized weighted average over whichever evidence
components have enough supporting data:
1. Base confidence (raw weight 0.6) - the analyst's original confidence
2. Historical accuracy (raw weight 0.2) - track record for this insight/action
3. Thematic accuracy (raw weight 0.1) - completed-theme validation rate
4. Symbol accuracy (raw weight 0.1) - track record for this specific symbol

The raw weights are normalized over the components that are actually present,
so the applied weights always sum to 1.0. A pattern boost (0-20%) is then added
on top for matching patterns with >60% success rate, and the result is clamped
to [0.1, 0.95].
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.deep_insight import DeepInsight
from models.insight_outcome import InsightOutcome, TrackingStatus
from models.knowledge_pattern import KnowledgePattern

logger = logging.getLogger(__name__)


class ConfidenceAdjuster:
    """Service for adjusting insight confidence using historical performance data.

    This service uses the system's institutional memory to calibrate confidence
    scores based on actual track record:
    - Past accuracy of similar insight types
    - Past accuracy of similar action recommendations
    - Success rates of matching patterns

    The goal is to produce well-calibrated confidence scores that reflect
    the system's actual predictive accuracy.

    Example:
        ```python
        from analysis.memory_service import InstitutionalMemoryService

        async with async_session_factory() as session:
            memory_service = InstitutionalMemoryService(session)
            adjuster = ConfidenceAdjuster(session, memory_service)

            result = await adjuster.adjust_confidence(
                base_confidence=0.75,
                insight_type="opportunity",
                action_type="BUY",
                symbols=["AAPL"],
            )
            # result contains adjusted_confidence, reasoning, etc.
        ```
    """

    # Raw weights for the confidence blend. These deliberately do NOT sum to 1.0
    # on their own: the historical, thematic and symbol components only join the
    # blend once they have enough supporting data, so `_weighted_average`
    # normalizes over whichever components are actually present. The applied
    # weights therefore always sum to 1.0 and the result is a true weighted
    # average rather than a systematic haircut on the analyst's confidence.
    BASE_WEIGHT = 0.6  # Weight for analyst's original confidence
    HISTORICAL_WEIGHT = 0.2  # Weight for historical track record
    THEMATIC_WEIGHT = 0.1  # Weight for thematic track record (when available)
    SYMBOL_WEIGHT = 0.1  # Weight for symbol-specific track record (when available)

    # Minimum sample sizes before a component is allowed to join the blend
    MIN_HISTORICAL_SAMPLE = 5
    MIN_THEMATIC_SAMPLE = 3
    MIN_SYMBOL_SAMPLE = 3

    # Pattern boost thresholds
    PATTERN_SUCCESS_THRESHOLD = 0.6  # Minimum pattern success rate for boost
    MAX_PATTERN_BOOST = 0.2  # Maximum pattern boost (20%)

    # Confidence bounds
    MIN_CONFIDENCE = 0.1  # Never allow confidence below 10%
    MAX_CONFIDENCE = 0.95  # Never allow confidence above 95%

    def __init__(
        self,
        db_session: AsyncSession,
        memory_service: Any,  # InstitutionalMemoryService
    ) -> None:
        """Initialize the confidence adjuster.

        Args:
            db_session: Async SQLAlchemy database session for queries.
            memory_service: InstitutionalMemoryService for track record queries.
        """
        self.db = db_session
        self.memory_service = memory_service

    async def adjust_confidence(
        self,
        base_confidence: float,
        insight_type: str,
        action_type: str,
        symbols: list[str] | None = None,
        patterns: list[KnowledgePattern] | None = None,
    ) -> dict[str, Any]:
        """Adjust confidence score based on historical performance.

        Combines the analyst's base confidence with historical accuracy data
        to produce a calibrated confidence score.

        Formula:
            adjusted = sum(value_i * weight_i) / sum(weight_i) + pattern_boost

            where the components are base confidence (0.6), historical accuracy
            (0.2, needs >= 5 outcomes), thematic accuracy (0.1, needs >= 3
            completed themes) and symbol accuracy (0.1, needs >= 3 outcomes).
            Dividing by the total raw weight of the present components makes the
            applied weights sum to 1.0 regardless of which evidence is
            available. Final confidence is clamped to [0.1, 0.95].

        Args:
            base_confidence: Analyst's original confidence score (0.0-1.0)
            insight_type: Type of insight (e.g., "opportunity", "risk", "trend")
            action_type: Recommended action (e.g., "BUY", "SELL", "HOLD")
            symbols: Optional list of stock symbols for symbol-specific accuracy
            patterns: Optional list of matching KnowledgePattern objects

        Returns:
            Dictionary containing:
            - adjusted_confidence: Final calibrated confidence (0.1-0.95)
            - base_confidence: Original analyst confidence
            - historical_accuracy: Historical track record accuracy
            - pattern_boost: Additional boost from pattern matching
            - applied_weights: Normalized weight actually applied to each
              component, summing to 1.0
            - reasoning: Human-readable explanation of adjustment
        """
        logger.info(
            f"Adjusting confidence for insight_type={insight_type}, "
            f"action_type={action_type}, base_confidence={base_confidence:.2f}"
        )

        # Get historical track record from memory service
        track_record = await self.memory_service.get_insight_track_record(
            insight_type=insight_type,
            action_type=action_type,
        )

        # Extract historical accuracy
        historical_accuracy = track_record.get("success_rate", 0.5)
        total_insights = track_record.get("total_insights", 0)

        # Calculate symbol-specific accuracy if symbols provided
        symbol_accuracy = None
        symbol_total = 0
        if symbols:
            for symbol in symbols:
                symbol_stats = await self.get_symbol_accuracy(symbol)
                if symbol_stats.get("total", 0) > 0:
                    symbol_accuracy = symbol_stats.get("accuracy", 0.5)
                    symbol_total = symbol_stats.get("total", 0)
                    break  # Use first symbol with data

        # Calculate pattern boost if patterns provided
        pattern_boost = 0.0
        if patterns:
            pattern_boost = await self.calculate_pattern_boost(patterns)

        # Build reasoning explanation
        reasoning_parts = []

        # Assemble the blend. Each component contributes only when it has enough
        # supporting data; the weights are normalized over the ones present.
        components: list[tuple[str, float, float]] = [
            ("base", base_confidence, self.BASE_WEIGHT),
        ]

        if total_insights >= self.MIN_HISTORICAL_SAMPLE:
            components.append(
                ("historical", historical_accuracy, self.HISTORICAL_WEIGHT)
            )
            reasoning_parts.append(
                f"Historical accuracy of {historical_accuracy:.1%} "
                f"from {total_insights} similar insights."
            )
        else:
            reasoning_parts.append(
                f"Insufficient historical data ({total_insights} insights). "
                f"Using analyst confidence of {base_confidence:.1%}."
            )

        # Blend in thematic track record if available
        try:
            thematic_record = await self.get_thematic_accuracy()
            thematic_total = thematic_record.get("total", 0)
            if thematic_total >= self.MIN_THEMATIC_SAMPLE:
                thematic_accuracy = thematic_record.get("accuracy", 0.5)
                components.append(
                    ("thematic", thematic_accuracy, self.THEMATIC_WEIGHT)
                )
                reasoning_parts.append(
                    f"Thematic track record of {thematic_accuracy:.1%} "
                    f"from {thematic_total} completed themes."
                )
        except Exception as thematic_err:
            logger.debug("Thematic track record unavailable: %s", thematic_err)

        # Blend in symbol-specific track record if available and significant
        if symbol_accuracy is not None and symbol_total >= self.MIN_SYMBOL_SAMPLE:
            components.append(("symbol", symbol_accuracy, self.SYMBOL_WEIGHT))
            reasoning_parts.append(
                f"Symbol-specific accuracy of {symbol_accuracy:.1%} "
                f"from {symbol_total} past predictions."
            )

        adjusted, applied_weights = self._weighted_average(components)

        # Apply pattern boost
        if pattern_boost > 0:
            adjusted += pattern_boost
            reasoning_parts.append(
                f"Pattern boost of {pattern_boost:.1%} from matching high-success patterns."
            )

        # Ensure bounds
        adjusted = self._ensure_bounds(adjusted)

        # Construct final reasoning
        if adjusted > base_confidence:
            direction = "increased"
        elif adjusted < base_confidence:
            direction = "decreased"
        else:
            direction = "unchanged"

        reasoning = (
            f"Confidence {direction} from {base_confidence:.1%} to {adjusted:.1%}. "
            + " ".join(reasoning_parts)
        )

        result = {
            "adjusted_confidence": round(adjusted, 4),
            "base_confidence": round(base_confidence, 4),
            "historical_accuracy": round(historical_accuracy, 4),
            "pattern_boost": round(pattern_boost, 4),
            "applied_weights": applied_weights,
            "reasoning": reasoning,
        }

        logger.info(
            f"Confidence adjusted: {base_confidence:.2f} -> {adjusted:.2f} "
            f"(historical={historical_accuracy:.2f}, boost={pattern_boost:.2f})"
        )

        return result

    async def get_type_accuracy(
        self,
        insight_type: str,
        lookback_days: int = 90,
    ) -> dict[str, Any]:
        """Get historical accuracy statistics for a specific insight type.

        Queries InsightOutcome records for the given insight type within
        the lookback period and calculates aggregate statistics.

        Args:
            insight_type: Type of insight to filter by (e.g., "opportunity")
            lookback_days: Number of days to look back (default 90)

        Returns:
            Dictionary containing:
            - total: Total validated outcomes
            - successful: Number of validated successes
            - accuracy: Success rate (0.0-1.0)
            - avg_return_when_successful: Average return on successful predictions
            - avg_return_when_failed: Average return on failed predictions
        """
        cutoff_date = datetime.utcnow() - timedelta(days=lookback_days)

        # Query completed outcomes for this insight type
        query = (
            select(InsightOutcome, DeepInsight)
            .join(DeepInsight, InsightOutcome.insight_id == DeepInsight.id)
            .where(
                and_(
                    InsightOutcome.tracking_status == TrackingStatus.COMPLETED.value,
                    InsightOutcome.thesis_validated.isnot(None),
                    InsightOutcome.created_at >= cutoff_date,
                    DeepInsight.insight_type == insight_type,
                )
            )
        )

        result = await self.db.execute(query)
        rows = result.all()

        total = len(rows)
        successful = sum(1 for row in rows if row[0].thesis_validated)
        accuracy = successful / total if total > 0 else 0.0

        # Calculate average returns
        successful_returns = [
            row[0].actual_return_pct
            for row in rows
            if row[0].thesis_validated and row[0].actual_return_pct is not None
        ]
        failed_returns = [
            row[0].actual_return_pct
            for row in rows
            if not row[0].thesis_validated and row[0].actual_return_pct is not None
        ]

        avg_return_success = (
            sum(successful_returns) / len(successful_returns)
            if successful_returns
            else 0.0
        )
        avg_return_failed = (
            sum(failed_returns) / len(failed_returns) if failed_returns else 0.0
        )

        logger.debug(
            f"Type accuracy for {insight_type}: {total} total, "
            f"{accuracy:.2%} accuracy"
        )

        return {
            "total": total,
            "successful": successful,
            "accuracy": round(accuracy, 4),
            "avg_return_when_successful": round(avg_return_success, 4),
            "avg_return_when_failed": round(avg_return_failed, 4),
        }

    async def get_action_accuracy(
        self,
        action_type: str,
        lookback_days: int = 90,
    ) -> dict[str, Any]:
        """Get historical accuracy statistics for a specific action type.

        Queries InsightOutcome records for the given action type (BUY, SELL, HOLD)
        within the lookback period and calculates aggregate statistics.

        Args:
            action_type: Action type to filter by (e.g., "BUY", "SELL", "HOLD")
            lookback_days: Number of days to look back (default 90)

        Returns:
            Dictionary containing:
            - total: Total validated outcomes
            - successful: Number of validated successes
            - accuracy: Success rate (0.0-1.0)
            - avg_return_when_successful: Average return on successful predictions
            - avg_return_when_failed: Average return on failed predictions
        """
        cutoff_date = datetime.utcnow() - timedelta(days=lookback_days)

        # Query completed outcomes for this action type
        query = (
            select(InsightOutcome, DeepInsight)
            .join(DeepInsight, InsightOutcome.insight_id == DeepInsight.id)
            .where(
                and_(
                    InsightOutcome.tracking_status == TrackingStatus.COMPLETED.value,
                    InsightOutcome.thesis_validated.isnot(None),
                    InsightOutcome.created_at >= cutoff_date,
                    DeepInsight.action == action_type,
                )
            )
        )

        result = await self.db.execute(query)
        rows = result.all()

        total = len(rows)
        successful = sum(1 for row in rows if row[0].thesis_validated)
        accuracy = successful / total if total > 0 else 0.0

        # Calculate average returns
        successful_returns = [
            row[0].actual_return_pct
            for row in rows
            if row[0].thesis_validated and row[0].actual_return_pct is not None
        ]
        failed_returns = [
            row[0].actual_return_pct
            for row in rows
            if not row[0].thesis_validated and row[0].actual_return_pct is not None
        ]

        avg_return_success = (
            sum(successful_returns) / len(successful_returns)
            if successful_returns
            else 0.0
        )
        avg_return_failed = (
            sum(failed_returns) / len(failed_returns) if failed_returns else 0.0
        )

        logger.debug(
            f"Action accuracy for {action_type}: {total} total, "
            f"{accuracy:.2%} accuracy"
        )

        return {
            "total": total,
            "successful": successful,
            "accuracy": round(accuracy, 4),
            "avg_return_when_successful": round(avg_return_success, 4),
            "avg_return_when_failed": round(avg_return_failed, 4),
        }

    async def get_symbol_accuracy(
        self,
        symbol: str,
        lookback_days: int = 180,
    ) -> dict[str, Any]:
        """Get historical accuracy statistics for a specific symbol.

        Queries InsightOutcome records for the given stock symbol within
        the lookback period. Uses longer default lookback (180 days) for
        symbol-specific data since there's typically less data per symbol.

        Args:
            symbol: Stock symbol to filter by (e.g., "AAPL")
            lookback_days: Number of days to look back (default 180)

        Returns:
            Dictionary containing:
            - total: Total validated outcomes
            - successful: Number of validated successes
            - accuracy: Success rate (0.0-1.0)
            - avg_return_when_successful: Average return on successful predictions
            - avg_return_when_failed: Average return on failed predictions
        """
        cutoff_date = datetime.utcnow() - timedelta(days=lookback_days)

        # Query completed outcomes for this symbol
        query = (
            select(InsightOutcome, DeepInsight)
            .join(DeepInsight, InsightOutcome.insight_id == DeepInsight.id)
            .where(
                and_(
                    InsightOutcome.tracking_status == TrackingStatus.COMPLETED.value,
                    InsightOutcome.thesis_validated.isnot(None),
                    InsightOutcome.created_at >= cutoff_date,
                    DeepInsight.primary_symbol == symbol,
                )
            )
        )

        result = await self.db.execute(query)
        rows = result.all()

        total = len(rows)
        successful = sum(1 for row in rows if row[0].thesis_validated)
        accuracy = successful / total if total > 0 else 0.0

        # Calculate average returns
        successful_returns = [
            row[0].actual_return_pct
            for row in rows
            if row[0].thesis_validated and row[0].actual_return_pct is not None
        ]
        failed_returns = [
            row[0].actual_return_pct
            for row in rows
            if not row[0].thesis_validated and row[0].actual_return_pct is not None
        ]

        avg_return_success = (
            sum(successful_returns) / len(successful_returns)
            if successful_returns
            else 0.0
        )
        avg_return_failed = (
            sum(failed_returns) / len(failed_returns) if failed_returns else 0.0
        )

        logger.debug(
            f"Symbol accuracy for {symbol}: {total} total, "
            f"{accuracy:.2%} accuracy"
        )

        return {
            "total": total,
            "successful": successful,
            "accuracy": round(accuracy, 4),
            "avg_return_when_successful": round(avg_return_success, 4),
            "avg_return_when_failed": round(avg_return_failed, 4),
        }

    async def get_thematic_accuracy(
        self,
        category: str | None = None,
        lookback_days: int = 180,
    ) -> dict[str, Any]:
        """Get thematic track record accuracy for confidence blending.

        Queries completed ThematicOutcome records to calculate the thematic
        thesis validation rate, used to blend into the confidence formula.

        Args:
            category: Optional theme category filter.
            lookback_days: Number of days to look back (default 180).

        Returns:
            Dictionary with total, validated, accuracy, avg_composite.
        """
        from analysis.thematic_outcome_tracker import ThematicOutcomeTracker

        tracker = ThematicOutcomeTracker(self.db)
        return await tracker.get_thematic_accuracy(
            category=category,
            lookback_days=lookback_days,
        )

    async def calculate_pattern_boost(
        self,
        patterns: list[KnowledgePattern],
    ) -> float:
        """Calculate confidence boost from matching patterns.

        Averages the success rates of provided patterns, weighted by
        occurrences (more data = more weight), and returns a boost factor.

        Only patterns with success_rate > 60% contribute to the boost.

        Args:
            patterns: List of matching KnowledgePattern objects

        Returns:
            Boost factor in range 0.0 to 0.2 (0-20%)
        """
        if not patterns:
            return 0.0

        # Filter to high-success patterns
        high_success_patterns = [
            p for p in patterns
            if p.success_rate >= self.PATTERN_SUCCESS_THRESHOLD
        ]

        if not high_success_patterns:
            logger.debug("No patterns with >60% success rate for boost")
            return 0.0

        # Calculate weighted average success rate
        total_weight = 0
        weighted_sum = 0.0

        for pattern in high_success_patterns:
            # Weight by occurrences (more data = more reliable)
            weight = min(pattern.occurrences, 100)  # Cap weight at 100
            weighted_sum += pattern.success_rate * weight
            total_weight += weight

        if total_weight == 0:
            return 0.0

        avg_success_rate = weighted_sum / total_weight

        # Calculate boost: scale from 0.6-1.0 success rate to 0-0.2 boost
        # At 60% success rate: 0% boost
        # At 100% success rate: 20% boost
        boost = (avg_success_rate - self.PATTERN_SUCCESS_THRESHOLD) * 0.5
        boost = max(0.0, min(self.MAX_PATTERN_BOOST, boost))

        logger.debug(
            f"Pattern boost from {len(high_success_patterns)} patterns: "
            f"{boost:.2%} (avg success: {avg_success_rate:.2%})"
        )

        return round(boost, 4)

    def adjust_confidence_with_decay(
        self,
        base_confidence: float,
        symbol: str,
        staleness_score: float = 0.0,
        patterns: list | None = None,
        track_record: dict | None = None,
    ) -> float:
        """Enhanced confidence adjustment with time-decay factor.

        Applies the existing pattern/track-record boost then multiplies
        by a staleness-derived decay so older insights lose conviction.

        Args:
            base_confidence: Analyst's original confidence (0.0-1.0).
            symbol: Stock symbol for symbol-specific accuracy lookup.
            staleness_score: Staleness score (0.0=fresh, 1.0=stale).
            patterns: Optional matching KnowledgePattern objects.
            track_record: Optional pre-fetched track record dict.

        Returns:
            Adjusted confidence clamped to [0.1, 0.95].
        """
        adjusted = base_confidence

        # Apply pattern boost if available
        if patterns:
            high_success = [
                p for p in patterns
                if p.success_rate >= self.PATTERN_SUCCESS_THRESHOLD
            ]
            if high_success:
                total_weight = 0
                weighted_sum = 0.0
                for p in high_success:
                    w = min(p.occurrences, 100)
                    weighted_sum += p.success_rate * w
                    total_weight += w
                if total_weight > 0:
                    avg = weighted_sum / total_weight
                    boost = max(0.0, min(self.MAX_PATTERN_BOOST,
                                         (avg - self.PATTERN_SUCCESS_THRESHOLD) * 0.5))
                    adjusted += boost

        # Apply track-record blending if sufficient data. Normalized over the two
        # components so this stays a weighted average instead of a 20% haircut.
        if track_record and track_record.get("total_insights", 0) >= self.MIN_HISTORICAL_SAMPLE:
            hist = track_record.get("success_rate", 0.5)
            adjusted, _ = self._weighted_average(
                [
                    ("base", adjusted, self.BASE_WEIGHT),
                    ("historical", hist, self.HISTORICAL_WEIGHT),
                ]
            )

        # Apply time decay
        decay_multiplier = max(0.5, 1.0 - staleness_score * 0.3)
        adjusted = adjusted * decay_multiplier

        return round(self._ensure_bounds(adjusted), 4)

    @staticmethod
    def _weighted_average(
        components: list[tuple[str, float, float]],
    ) -> tuple[float, dict[str, float]]:
        """Combine weighted components into a normalized weighted average.

        The raw class weights are declared per component but do not sum to 1.0,
        because the historical, thematic and symbol components only participate
        once they have enough supporting data. Normalizing over the components
        that are actually present keeps the result a true weighted average: a
        unanimous set of high inputs can reach the top of the range, and a
        mid-range input is not silently deflated toward zero.

        Args:
            components: List of (name, value, raw_weight) tuples.

        Returns:
            Tuple of (weighted average, {name: normalized_weight}). The
            normalized weights sum to 1.0. An empty or zero-weight component
            list yields (0.0, {}).
        """
        total_weight = sum(weight for _, _, weight in components)
        if total_weight <= 0:
            return 0.0, {}

        normalized = {
            name: weight / total_weight for name, _, weight in components
        }
        value = sum(val * normalized[name] for name, val, _ in components)
        return value, {name: round(w, 6) for name, w in normalized.items()}

    def _ensure_bounds(self, confidence: float) -> float:
        """Clamp confidence to valid bounds.

        Ensures confidence is never 0 or 1 (there's always uncertainty)
        by clamping to [0.1, 0.95].

        Args:
            confidence: Raw confidence value

        Returns:
            Confidence clamped to [0.1, 0.95]
        """
        return max(self.MIN_CONFIDENCE, min(self.MAX_CONFIDENCE, confidence))


# =============================================================================
# Factory function for easy instantiation
# =============================================================================


async def create_confidence_adjuster(
    db_session: AsyncSession,
    memory_service: Any,
) -> ConfidenceAdjuster:
    """Factory function to create a ConfidenceAdjuster.

    Args:
        db_session: Async SQLAlchemy database session.
        memory_service: InstitutionalMemoryService instance.

    Returns:
        Configured ConfidenceAdjuster instance.
    """
    return ConfidenceAdjuster(db_session, memory_service)
