"""Institutional Memory Service - Manages patterns, themes, and insight outcomes.

This module provides the InstitutionalMemoryService class that manages the
system's institutional memory by:
1. Retrieving relevant patterns based on current market conditions
2. Managing conversation themes with time-based relevance decay
3. Tracking insight outcomes and success rates
4. Recording pattern occurrences and updating success metrics
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge_pattern import KnowledgePattern
from models.insight_outcome import InsightOutcome
from models.conversation_theme import ConversationTheme

logger = logging.getLogger(__name__)


class InstitutionalMemoryService:
    """Service for managing institutional memory across conversations.

    This service provides methods to:
    - Query relevant patterns matching current market conditions
    - Manage conversation themes with relevance decay
    - Track insight outcomes and calculate success rates
    - Record pattern occurrences and update metrics

    Example:
        ```python
        from database import async_session_factory

        async with async_session_factory() as session:
            memory_service = InstitutionalMemoryService(session)

            # Get patterns relevant to current conditions
            patterns = await memory_service.get_relevant_patterns(
                symbols=["AAPL", "NVDA"],
                current_conditions={"rsi_below": 25, "vix_above": 30}
            )

            # Get active themes for tech sector
            themes = await memory_service.get_active_themes(
                sectors=["Technology"]
            )

            # Get track record for opportunity insights
            track_record = await memory_service.get_insight_track_record(
                insight_type="opportunity"
            )
        ```
    """

    def __init__(self, db_session: AsyncSession) -> None:
        """Initialize the institutional memory service.

        Args:
            db_session: Async SQLAlchemy database session for queries.
        """
        self.db = db_session

    async def get_relevant_patterns(
        self,
        symbols: list[str],
        current_conditions: dict[str, Any],
    ) -> list[KnowledgePattern]:
        """Query patterns matching current market conditions.

        Retrieves active patterns with success_rate >= 50% where trigger
        conditions match the current market state. Conditions are matched
        using comparison operators:
        - "rsi_below": 30 matches if current RSI < 30
        - "vix_above": 25 matches if current VIX > 25
        - "volume_surge_pct": 200 matches if current volume surge >= 200%

        Args:
            symbols: List of stock symbols to focus on.
            current_conditions: Current market state with metrics like:
                - rsi: Current RSI value
                - vix: Current VIX level
                - volume_surge_pct: Current volume surge percentage
                - sector_momentum: Sector momentum score
                etc.

        Returns:
            List of matching KnowledgePattern objects sorted by success_rate
            descending, limited to top 10.
        """
        logger.info(
            f"Querying relevant patterns for {len(symbols)} symbols "
            f"with {len(current_conditions)} conditions"
        )

        # Query active patterns with minimum success rate
        query = (
            select(KnowledgePattern)
            .where(
                and_(
                    KnowledgePattern.is_active == True,  # noqa: E712
                    KnowledgePattern.success_rate >= 0.5,
                )
            )
            .order_by(KnowledgePattern.success_rate.desc())
        )

        result = await self.db.execute(query)
        all_patterns = result.scalars().all()

        # Filter patterns by matching trigger conditions
        matching_patterns: list[KnowledgePattern] = []

        for pattern in all_patterns:
            if self._matches_conditions(pattern.trigger_conditions, current_conditions):
                matching_patterns.append(pattern)
                if len(matching_patterns) >= 10:
                    break

        logger.info(f"Found {len(matching_patterns)} matching patterns")
        return matching_patterns

    def _matches_conditions(
        self,
        trigger_conditions: dict[str, Any],
        current_conditions: dict[str, Any],
    ) -> bool:
        """Check if current conditions match pattern trigger conditions.

        Supports comparison operators embedded in condition names:
        - *_below: Matches if current value < trigger value
        - *_above: Matches if current value > trigger value
        - *_equals: Matches if current value == trigger value
        - Default: Matches if current value >= trigger value

        Args:
            trigger_conditions: Pattern's trigger conditions dict.
            current_conditions: Current market conditions dict.

        Returns:
            True if all trigger conditions are satisfied.
        """
        if not trigger_conditions:
            return False

        for condition_key, trigger_value in trigger_conditions.items():
            # Parse condition key for comparison operator
            if condition_key.endswith("_below"):
                metric_name = condition_key.replace("_below", "")
                current_value = current_conditions.get(metric_name)
                if current_value is None or current_value >= trigger_value:
                    return False
            elif condition_key.endswith("_above"):
                metric_name = condition_key.replace("_above", "")
                current_value = current_conditions.get(metric_name)
                if current_value is None or current_value <= trigger_value:
                    return False
            elif condition_key.endswith("_equals"):
                metric_name = condition_key.replace("_equals", "")
                current_value = current_conditions.get(metric_name)
                if current_value is None or current_value != trigger_value:
                    return False
            else:
                # Default: check if current value >= trigger value
                current_value = current_conditions.get(condition_key)
                if current_value is None or current_value < trigger_value:
                    return False

        return True

    async def get_active_themes(
        self,
        sectors: list[str] | None = None,
    ) -> list[ConversationTheme]:
        """Query active themes with time-based relevance decay.

        Retrieves active themes with current_relevance > 0.3, applies
        time-based relevance decay based on days since last mention,
        and updates the database with new relevance scores.

        Decay formula: relevance *= (1 - decay_rate) ^ days_since_mention

        Args:
            sectors: Optional list of sectors to filter by. If provided,
                only themes with matching related_sectors are returned.

        Returns:
            List of ConversationTheme objects sorted by current_relevance
            descending, with updated relevance scores.
        """
        logger.info(f"Querying active themes for sectors: {sectors}")

        # Build query for active themes with minimum relevance
        query = (
            select(ConversationTheme)
            .where(
                and_(
                    ConversationTheme.is_active == True,  # noqa: E712
                    ConversationTheme.current_relevance > 0.3,
                )
            )
            .order_by(ConversationTheme.current_relevance.desc())
        )

        result = await self.db.execute(query)
        themes = list(result.scalars().all())

        now = datetime.utcnow()
        updated_themes: list[ConversationTheme] = []

        for theme in themes:
            # Apply time-based relevance decay
            if theme.last_mentioned_at:
                days_since_mention = (now - theme.last_mentioned_at).days
                if days_since_mention > 0:
                    decay_factor = (1 - theme.relevance_decay_rate) ** days_since_mention
                    new_relevance = theme.current_relevance * decay_factor
                    theme.current_relevance = max(new_relevance, 0.0)

            # Filter by sectors if specified
            if sectors:
                related_sectors = theme.related_sectors or []
                if not any(s in related_sectors for s in sectors):
                    continue

            # Only include if still above threshold after decay
            if theme.current_relevance > 0.3:
                updated_themes.append(theme)

        # Commit updated relevance scores
        await self.db.commit()

        logger.info(f"Returning {len(updated_themes)} active themes")
        return updated_themes

    async def get_insight_track_record(
        self,
        insight_type: str | None = None,
        action_type: str | None = None,
    ) -> dict[str, Any]:
        """Calculate insight success statistics.

        Queries InsightOutcome records where thesis_validated is not None
        and calculates aggregate statistics including total insights,
        successful validations, and success rate.

        Args:
            insight_type: Optional insight type to filter by (e.g., "opportunity").
            action_type: Optional action type to filter by (e.g., "BUY").

        Returns:
            Dictionary containing:
            - total_insights: Total number of validated insights
            - successful: Number of successfully validated insights
            - success_rate: Proportion of successful validations (0.0-1.0)
            - by_insight_type: Breakdown by insight type (if not filtered)
            - by_action_type: Breakdown by action type (if not filtered)
        """
        logger.info(
            f"Calculating track record for insight_type={insight_type}, "
            f"action_type={action_type}"
        )

        # Build base query for validated outcomes
        base_conditions = [InsightOutcome.thesis_validated.isnot(None)]

        # Join with DeepInsight for type/action filtering
        from models.deep_insight import DeepInsight

        query = (
            select(
                InsightOutcome,
                DeepInsight.insight_type,
                DeepInsight.action,
            )
            .join(DeepInsight, InsightOutcome.insight_id == DeepInsight.id)
            .where(and_(*base_conditions))
        )

        if insight_type:
            query = query.where(DeepInsight.insight_type == insight_type)
        if action_type:
            query = query.where(DeepInsight.action == action_type)

        result = await self.db.execute(query)
        rows = result.all()

        # Calculate aggregate statistics
        total_insights = len(rows)
        successful = sum(1 for row in rows if row[0].thesis_validated)
        success_rate = successful / total_insights if total_insights > 0 else 0.0

        track_record: dict[str, Any] = {
            "total_insights": total_insights,
            "successful": successful,
            "success_rate": round(success_rate, 4),
        }

        # Add breakdowns if not filtered
        if not insight_type:
            by_type: dict[str, dict[str, Any]] = {}
            for row in rows:
                itype = row[1]
                if itype not in by_type:
                    by_type[itype] = {"total": 0, "successful": 0}
                by_type[itype]["total"] += 1
                if row[0].thesis_validated:
                    by_type[itype]["successful"] += 1

            # Calculate success rates per type
            for type_stats in by_type.values():
                type_stats["success_rate"] = round(
                    type_stats["successful"] / type_stats["total"]
                    if type_stats["total"] > 0 else 0.0,
                    4,
                )
            track_record["by_insight_type"] = by_type

        if not action_type:
            by_action: dict[str, dict[str, Any]] = {}
            for row in rows:
                action = row[2]
                if action not in by_action:
                    by_action[action] = {"total": 0, "successful": 0}
                by_action[action]["total"] += 1
                if row[0].thesis_validated:
                    by_action[action]["successful"] += 1

            # Calculate success rates per action
            for action_stats in by_action.values():
                action_stats["success_rate"] = round(
                    action_stats["successful"] / action_stats["total"]
                    if action_stats["total"] > 0 else 0.0,
                    4,
                )
            track_record["by_action_type"] = by_action

        logger.info(
            f"Track record: {total_insights} total, {successful} successful, "
            f"{success_rate:.2%} rate"
        )
        return track_record

    async def record_pattern_occurrence(
        self,
        pattern_id: uuid.UUID,
        triggered_at: datetime,
        insight_id: uuid.UUID | None = None,
    ) -> bool:
        """Record a pattern occurrence and update metrics.

        Increments the occurrences count, updates last_triggered_at,
        and optionally adds the insight_id to source_insights array.

        Args:
            pattern_id: UUID of the pattern that was triggered.
            triggered_at: Timestamp when pattern was detected.
            insight_id: Optional UUID of the related insight.

        Returns:
            True if update succeeded, False otherwise.
        """
        logger.info(f"Recording pattern occurrence for pattern_id={pattern_id}")

        # Get the pattern
        result = await self.db.execute(
            select(KnowledgePattern).where(KnowledgePattern.id == pattern_id)
        )
        pattern = result.scalar_one_or_none()

        if not pattern:
            logger.warning(f"Pattern not found: {pattern_id}")
            return False

        # Update occurrences and last_triggered_at
        pattern.occurrences += 1
        pattern.last_triggered_at = triggered_at

        # Add insight_id to source_insights if provided
        if insight_id:
            source_insights = pattern.source_insights or []
            # Convert UUID to string for JSON storage
            source_insights.append(str(insight_id))
            pattern.source_insights = source_insights

        await self.db.commit()
        logger.info(
            f"Pattern {pattern_id} occurrence recorded: "
            f"occurrences={pattern.occurrences}"
        )
        return True

    async def update_pattern_success(
        self,
        pattern_id: uuid.UUID,
        was_successful: bool,
        actual_return: float | None = None,
    ) -> bool:
        """Update pattern success metrics after validation.

        Increments successful_outcomes if was_successful, recalculates
        success_rate, and updates avg_return_when_triggered using a
        running average.

        Args:
            pattern_id: UUID of the pattern to update.
            was_successful: Whether the pattern's expected outcome occurred.
            actual_return: Optional actual return percentage for this occurrence.

        Returns:
            True if update succeeded, False otherwise.
        """
        logger.info(
            f"Updating pattern success for pattern_id={pattern_id}, "
            f"was_successful={was_successful}"
        )

        # Get the pattern
        result = await self.db.execute(
            select(KnowledgePattern).where(KnowledgePattern.id == pattern_id)
        )
        pattern = result.scalar_one_or_none()

        if not pattern:
            logger.warning(f"Pattern not found: {pattern_id}")
            return False

        # Increment successful outcomes if applicable
        if was_successful:
            pattern.successful_outcomes += 1

        # Recalculate success rate
        if pattern.occurrences > 0:
            pattern.success_rate = pattern.successful_outcomes / pattern.occurrences

        # Update average return using running average formula
        if actual_return is not None:
            if pattern.avg_return_when_triggered is not None and pattern.occurrences > 0:
                # Running average: new_avg = old_avg + (new_value - old_avg) / n
                prev_avg = pattern.avg_return_when_triggered
                pattern.avg_return_when_triggered = (
                    prev_avg + (actual_return - prev_avg) / pattern.occurrences
                )
            else:
                pattern.avg_return_when_triggered = actual_return

        await self.db.commit()
        logger.info(
            f"Pattern {pattern_id} success updated: "
            f"success_rate={pattern.success_rate:.2%}, "
            f"successful_outcomes={pattern.successful_outcomes}"
        )
        return True

    async def add_theme_mention(
        self,
        theme_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> bool:
        """Record a new mention of a theme in a conversation.

        Increments mention_count, updates last_mentioned_at to now,
        resets current_relevance to 1.0, and adds conversation_id to
        source_conversation_ids array.

        Args:
            theme_id: UUID of the theme that was mentioned.
            conversation_id: UUID of the conversation where theme was mentioned.

        Returns:
            True if update succeeded, False otherwise.
        """
        logger.info(
            f"Adding theme mention for theme_id={theme_id}, "
            f"conversation_id={conversation_id}"
        )

        # Get the theme
        result = await self.db.execute(
            select(ConversationTheme).where(ConversationTheme.id == theme_id)
        )
        theme = result.scalar_one_or_none()

        if not theme:
            logger.warning(f"Theme not found: {theme_id}")
            return False

        # Update mention tracking
        theme.mention_count += 1
        theme.last_mentioned_at = datetime.utcnow()

        # Reset relevance to 1.0 (fully relevant since just mentioned)
        theme.current_relevance = 1.0

        # Add conversation_id to source_conversation_ids
        source_conversations = theme.source_conversation_ids or []
        # Convert UUID to string for JSON storage
        source_conversations.append(str(conversation_id))
        theme.source_conversation_ids = source_conversations

        await self.db.commit()
        logger.info(
            f"Theme {theme_id} mention recorded: "
            f"mention_count={theme.mention_count}, relevance=1.0"
        )
        return True


# =============================================================================
# Factory function for easy instantiation
# =============================================================================


async def get_memory_service(db_session: AsyncSession) -> InstitutionalMemoryService:
    """Factory function to create an InstitutionalMemoryService.

    Args:
        db_session: Async SQLAlchemy database session.

    Returns:
        Configured InstitutionalMemoryService instance.
    """
    return InstitutionalMemoryService(db_session)
