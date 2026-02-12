"""DeepInsight model for storing AI-synthesized cross-analyst insights."""

import enum
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

from .base import TimestampMixin

if TYPE_CHECKING:
    from .insight_conversation import InsightConversation
    from .insight_outcome import InsightOutcome
    from .insight_research_context import InsightResearchContext


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

    # Trading levels (autonomous analysis)
    entry_zone: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )  # e.g., "$150-155"
    target_price: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )  # e.g., "$180 within 3 months"
    stop_loss: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )  # e.g., "$142 (-5%)"
    timeframe: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )  # swing, position, long-term

    # Discovery context (autonomous analysis)
    discovery_context: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )  # Macro regime, sector signals, discovery metadata

    # Additional data fields
    technical_analysis_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    prediction_market_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    sentiment_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Parent insight linking (for follow-up insights derived from conversations)
    parent_insight_id: Mapped[int | None] = mapped_column(
        ForeignKey("deep_insights.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )  # Links follow-up insights to parent

    # Source conversation (when insight was generated from a conversation)
    source_conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("insight_conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )  # Tracks which conversation spawned this insight

    # Self-referential relationship for parent/child insights
    parent_insight: Mapped["DeepInsight | None"] = relationship(
        "DeepInsight",
        back_populates="child_insights",
        remote_side="DeepInsight.id",
        foreign_keys=[parent_insight_id],
    )
    child_insights: Mapped[list["DeepInsight"]] = relationship(
        "DeepInsight",
        back_populates="parent_insight",
        foreign_keys=[parent_insight_id],
    )

    # Relationship to source conversation
    source_conversation: Mapped["InsightConversation | None"] = relationship(
        foreign_keys=[source_conversation_id],
    )

    # Relationship to research context (1:1)
    research_context: Mapped["InsightResearchContext | None"] = relationship(
        back_populates="deep_insight",
        uselist=False,  # 1:1 relationship
        cascade="all, delete-orphan",  # Delete context when insight deleted
        lazy="selectin",  # Async-compatible eager loading
    )

    # Relationship to outcome tracking (1:1)
    outcome: Mapped["InsightOutcome | None"] = relationship(
        back_populates="deep_insight",
        uselist=False,  # 1:1 relationship
        cascade="all, delete-orphan",  # Delete outcome when insight deleted
        lazy="selectin",  # Async-compatible eager loading
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
