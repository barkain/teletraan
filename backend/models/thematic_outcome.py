"""ThematicOutcome model for tracking basket-level thesis validation.

ThematicOutcomes track the performance of a basket of symbols against a
thematic thesis. Unlike per-symbol InsightOutcome tracking, this evaluates
direction agreement across multiple symbols and composite basket returns.
"""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import Boolean, Date, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

from .base import TimestampMixin
from .insight_outcome import TrackingStatus


class ThematicOutcome(TimestampMixin, Base):
    """Model for tracking validation of thematic thesis predictions.

    ThematicOutcome tracks a basket of symbols against a directional thesis,
    calculating composite metrics like direction agreement rate, basket
    average return, and best-of-basket return.
    """

    __tablename__ = "thematic_outcomes"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # Foreign key to thematic_insights table
    thematic_insight_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("thematic_insights.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Tracking status (reuses TrackingStatus enum from insight_outcome)
    tracking_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=TrackingStatus.PENDING.value,
        index=True,
    )

    # Tracking dates
    tracking_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    tracking_end_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Prediction
    predicted_direction: Mapped[str] = mapped_column(
        String(20), nullable=False,
    )  # bullish, bearish, mixed

    # Per-symbol tracking data
    # {symbol: {initial_price, current_price, final_price, return_pct,
    #           direction_correct, price_history: [{date, price}, ...]}}
    symbol_tracking: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict,
    )
    symbols_tracked: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    # Basket aggregate metrics
    basket_avg_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    direction_agreement_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_symbol_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    worst_symbol_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Validation
    thesis_validated: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    outcome_category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    validation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    composite_score: Mapped[float | None] = mapped_column(
        Float, nullable=True,
    )  # Weighted: 0.4 direction + 0.4 avg_return + 0.2 best_return

    # Extrema
    max_favorable_basket_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_adverse_basket_return: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Checkpoints
    # {10d: {avg_return, direction_agreement}, 20d: {...}, ...}
    intermediate_checkpoints: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, default=dict,
    )

    # Cross-reference to per-symbol InsightOutcome records
    related_insight_outcome_ids: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True, default=list,
    )

    # Relationship back to ThematicInsight
    thematic_insight = relationship(
        "ThematicInsight",
        back_populates="outcome",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_thematic_outcomes_status_end_date", "tracking_status", "tracking_end_date"),
        Index("ix_thematic_outcomes_created_at", "created_at"),
        Index("ix_thematic_outcomes_thesis_validated", "thesis_validated"),
    )

    def __repr__(self) -> str:
        return (
            f"<ThematicOutcome(id={self.id}, insight_id={self.thematic_insight_id}, "
            f"status={self.tracking_status!r}, validated={self.thesis_validated})>"
        )
