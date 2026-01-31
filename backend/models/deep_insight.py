"""DeepInsight model for storing AI-synthesized cross-analyst insights."""

import enum
from typing import Any

from sqlalchemy import JSON, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

from .base import TimestampMixin


class InsightAction(str, enum.Enum):
    """Recommended trading action based on insight analysis."""

    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"
    WATCH = "WATCH"


class InsightType(str, enum.Enum):
    """Classification of the insight type."""

    OPPORTUNITY = "opportunity"
    RISK = "risk"
    ROTATION = "rotation"
    MACRO = "macro"
    DIVERGENCE = "divergence"
    CORRELATION = "correlation"


class DeepInsight(TimestampMixin, Base):
    """Model representing AI-synthesized deep insights from multiple analysts.

    DeepInsights are high-level analysis combining findings from multiple
    specialized analysts (technical, fundamental, macro, sentiment) into
    actionable intelligence with confidence scoring and risk assessment.
    """

    __tablename__ = "deep_insights"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Classification
    insight_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )

    # Content
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    thesis: Mapped[str] = mapped_column(Text, nullable=False)  # Detailed reasoning

    # Symbols
    primary_symbol: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        index=True,
    )
    related_symbols: Mapped[list[str] | None] = mapped_column(
        JSON,
        default=list,
        nullable=True,
    )  # ["NVDA", "SMH", "XLK"]

    # Evidence from analysts
    supporting_evidence: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON,
        default=list,
        nullable=True,
    )  # [{"analyst": "technical", "finding": "..."}, ...]

    # Confidence & Timing
    confidence: Mapped[float] = mapped_column(nullable=False)
    time_horizon: Mapped[str] = mapped_column(String(50), nullable=False)

    # Risk Management
    risk_factors: Mapped[list[str] | None] = mapped_column(
        JSON,
        default=list,
        nullable=True,
    )
    invalidation_trigger: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Historical context
    historical_precedent: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Metadata
    analysts_involved: Mapped[list[str] | None] = mapped_column(
        JSON,
        default=list,
        nullable=True,
    )
    data_sources: Mapped[list[str] | None] = mapped_column(
        JSON,
        default=list,
        nullable=True,
    )

    __table_args__ = (
        Index("ix_deep_insights_type_action", "insight_type", "action"),
        Index("ix_deep_insights_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<DeepInsight(id={self.id}, type={self.insight_type!r}, "
            f"action={self.action!r}, title={self.title!r})>"
        )
