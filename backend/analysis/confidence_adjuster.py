"""ConfidenceAdjuster service for adjusting insight confidence based on historical track record.

This module provides the ConfidenceAdjuster class that adjusts analyst-generated
confidence scores using historical performance data from InsightOutcome records
and KnowledgePattern success rates.

The adjustment formula combines:
1. Base confidence (70% weight) - the analyst's original confidence
2. Historical accuracy (30% weight) - track record from past predictions
3. Pattern boost (0-20% bonus) - if matching patterns with >60% success rate
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

    # Weight constants for confidence adjustment formula
    BASE_WEIGHT = 0.7  # Weight for analyst's original confidence
    HISTORICAL_WEIGHT = 0.3  # Weight for historical track record

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
            adjusted = (base * 0.7) + (historical * 0.3) + pattern_boost
            Final confidence is clamped to [0.1, 0.95]

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

        # Calculate adjusted confidence
        if total_insights < 5:
            # Not enough historical data - use base confidence with minimal adjustment
            adjusted = base_confidence
            reasoning_parts.append(
                f"Insufficient historical data ({total_insights} insights). "
                f"Using analyst confidence of {base_confidence:.1%}."
            )
        else:
            # Apply adjustment formula
            adjusted = (
                base_confidence * self.BASE_WEIGHT
                + historical_accuracy * self.HISTORICAL_WEIGHT
            )
            reasoning_parts.append(
                f"Historical accuracy of {historical_accuracy:.1%} "
                f"from {total_insights} similar insights."
            )

        # Apply symbol-specific adjustment if available and significant
        if symbol_accuracy is not None and symbol_total >= 3:
            # Blend in symbol accuracy with small weight
            symbol_weight = 0.1
            adjusted = adjusted * (1 - symbol_weight) + symbol_accuracy * symbol_weight
            reasoning_parts.append(
                f"Symbol-specific accuracy of {symbol_accuracy:.1%} "
                f"from {symbol_total} past predictions."
            )

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
