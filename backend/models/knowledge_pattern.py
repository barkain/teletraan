"""KnowledgePattern model for storing validated patterns discovered from conversations.

This module defines the data model for market patterns that are extracted from
insight conversations, validated over time, and used to enhance future analysis.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

from .base import TimestampMixin


class PatternType(str, enum.Enum):
    """Classification of market pattern types."""

    TECHNICAL_SETUP = "TECHNICAL_SETUP"  # e.g., RSI oversold + volume spike
    MACRO_CORRELATION = "MACRO_CORRELATION"  # e.g., VIX spike -> tech selloff
    SECTOR_ROTATION = "SECTOR_ROTATION"  # e.g., defensive to growth rotation
    EARNINGS_PATTERN = "EARNINGS_PATTERN"  # e.g., pre-earnings drift
    SEASONALITY = "SEASONALITY"  # e.g., January effect
    CROSS_ASSET = "CROSS_ASSET"  # e.g., bond/equity correlation


class KnowledgePattern(TimestampMixin, Base):
    """Model representing validated market patterns discovered from conversations.

    KnowledgePatterns are market behaviors identified through insight exploration
    that have been validated over time. They store trigger conditions, expected
    outcomes, and statistical performance metrics.

    Attributes:
        id: UUID primary key
        pattern_name: Human-readable name for the pattern
        pattern_type: Classification (TECHNICAL_SETUP, MACRO_CORRELATION, etc.)
        description: Detailed explanation of the pattern
        trigger_conditions: JSON defining when pattern activates
        expected_outcome: What typically happens when pattern triggers
        success_rate: Validated accuracy (0.0-1.0)
        occurrences: Total times pattern was identified
        successful_outcomes: Times pattern played out correctly
        avg_return_when_triggered: Average return when pattern triggers
        source_insights: Array of insight IDs where pattern was discovered
        source_conversations: Array of conversation IDs where discussed
        is_active: Whether pattern is currently active for detection
        last_triggered_at: When pattern was last detected in market
    """

    __tablename__ = "knowledge_patterns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Pattern identification
    pattern_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        index=True,
    )
    pattern_type: Mapped[PatternType] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Trigger conditions - JSON for flexible structure
    # e.g., {"rsi_below": 30, "vix_above": 25, "volume_surge_pct": 200}
    trigger_conditions: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    # Expected behavior when triggered
    expected_outcome: Mapped[str] = mapped_column(Text, nullable=False)

    # Performance metrics
    success_rate: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )  # 0.0-1.0, validated accuracy
    occurrences: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )  # Times pattern was identified
    successful_outcomes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )  # Times pattern played out correctly
    avg_return_when_triggered: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )  # Average return when pattern triggers

    # Source tracking - linking back to discoveries
    source_insights: Mapped[list[int] | None] = mapped_column(
        JSON,
        nullable=True,
        default=list,
    )  # Array of DeepInsight IDs
    source_conversations: Mapped[list[int] | None] = mapped_column(
        JSON,
        nullable=True,
        default=list,
    )  # Array of conversation IDs

    # Status and recency
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
    )
    last_triggered_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index("ix_knowledge_patterns_type_active", "pattern_type", "is_active"),
        Index("ix_knowledge_patterns_success_rate", "success_rate"),
        Index("ix_knowledge_patterns_occurrences", "occurrences"),
        Index("ix_knowledge_patterns_last_triggered", "last_triggered_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<KnowledgePattern(id={self.id}, name={self.pattern_name!r}, "
            f"type={self.pattern_type!r}, success_rate={self.success_rate:.2%})>"
        )

    def record_occurrence(self, was_successful: bool, return_pct: float | None = None) -> None:
        """Record a new occurrence of this pattern and update statistics.

        Args:
            was_successful: Whether the expected outcome materialized
            return_pct: Optional return percentage for this occurrence
        """
        self.occurrences += 1
        if was_successful:
            self.successful_outcomes += 1

        # Recalculate success rate
        if self.occurrences > 0:
            self.success_rate = self.successful_outcomes / self.occurrences

        # Update average return if provided
        if return_pct is not None and self.avg_return_when_triggered is not None:
            # Running average calculation
            prev_avg = self.avg_return_when_triggered
            self.avg_return_when_triggered = (
                prev_avg + (return_pct - prev_avg) / self.occurrences
            )
        elif return_pct is not None:
            self.avg_return_when_triggered = return_pct
