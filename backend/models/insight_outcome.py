"""InsightOutcome model for tracking thesis validation."""

import enum
import uuid
from datetime import date
from typing import Any

from sqlalchemy import Boolean, Date, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

from .base import TimestampMixin


class OutcomeCategory(str, enum.Enum):
    """Classification of insight outcome based on actual returns."""

    STRONG_SUCCESS = "STRONG_SUCCESS"  # >10% in predicted direction
    SUCCESS = "SUCCESS"  # 5-10% in predicted direction
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"  # 1-5% in predicted direction
    NEUTRAL = "NEUTRAL"  # -1% to 1%
    PARTIAL_FAILURE = "PARTIAL_FAILURE"  # -1% to -5% against prediction
    FAILURE = "FAILURE"  # -5% to -10% against prediction
    STRONG_FAILURE = "STRONG_FAILURE"  # >10% against prediction


class TrackingStatus(str, enum.Enum):
    """Status of outcome tracking for an insight."""

    PENDING = "PENDING"  # Not yet started
    TRACKING = "TRACKING"  # Actively monitoring
    COMPLETED = "COMPLETED"  # Evaluation window closed
    INVALIDATED = "INVALIDATED"  # External factors made tracking invalid
    STALE = "STALE"  # Insight has gone stale
    RE_EVALUATING = "RE_EVALUATING"  # Under re-evaluation
    EXPIRED = "EXPIRED"  # Time horizon exceeded


class InsightOutcome(TimestampMixin, Base):
    """Model for tracking validation of insight thesis predictions.

    InsightOutcome tracks the actual market performance after an insight
    is generated, enabling measurement of prediction accuracy and
    continuous improvement of analysis quality.
    """

    __tablename__ = "insight_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Foreign key to deep_insights table
    insight_id: Mapped[int] = mapped_column(
        ForeignKey("deep_insights.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Tracking status
    tracking_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=TrackingStatus.PENDING.value,
        index=True,
    )

    # Tracking dates
    tracking_start_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    tracking_end_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )  # Evaluation window end

    # Price tracking
    initial_price: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )  # Price when insight generated
    current_price: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )  # Latest tracked price
    final_price: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )  # Price at evaluation end

    # Return calculation
    actual_return_pct: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    # Prediction direction
    predicted_direction: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )  # "bullish", "bearish", "neutral"

    # Validation result
    thesis_validated: Mapped[bool | None] = mapped_column(
        nullable=True,
    )
    outcome_category: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )
    validation_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Benchmark-relative evaluation
    #
    # A raw return is not evidence of skill: a +3% call while the market ran
    # +7% is a losing call. Every completed outcome therefore records the
    # benchmark's move over the *same* window, and validation is decided on
    # alpha (symbol return minus benchmark return), not on raw return.
    benchmark_symbol: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default="SPY",
    )
    benchmark_initial_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    benchmark_final_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    benchmark_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    alpha_pct: Mapped[float | None] = mapped_column(
        Float, nullable=True,
    )  # actual_return_pct - benchmark_return_pct

    # Evaluation provenance
    evaluated_price_date: Mapped[date | None] = mapped_column(
        Date, nullable=True,
    )  # Trading date whose close produced final_price (<= tracking_end_date)
    horizon_days: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )  # Trading days derived from the insight's own time_horizon
    exit_reason: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
    )  # "target" | "stop" | "window_end" | "no_data"

    # Price history during tracking period
    #
    # MutableList so that in-place ``.append(...)`` marks the attribute dirty.
    # Without it SQLAlchemy never flushes the mutation and every row keeps
    # exactly the one entry written at creation time.
    price_history: Mapped[list[dict[str, Any]] | None] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=True,
    )  # Daily prices: [{"date": "2026-01-15", "price": 150.25}, ...]

    # Intermediate tracking checkpoints
    intermediate_checkpoints: Mapped[dict | None] = mapped_column(
        MutableDict.as_mutable(JSON), nullable=True, default=dict,
    )  # {"5d": {"price": 150.2, "return_pct": 2.1}, "10d": {...}, ...}

    # Price-level trigger flags
    entry_triggered: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=False,
    )  # True when price enters entry_zone

    target_triggered: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=False,
    )  # True when price hits target

    stop_triggered: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=False,
    )  # True when price hits stop_loss

    # Extrema tracking
    max_favorable_move: Mapped[float | None] = mapped_column(
        Float, nullable=True,
    )  # Best return % seen during tracking

    max_adverse_move: Mapped[float | None] = mapped_column(
        Float, nullable=True,
    )  # Worst return % seen during tracking

    # Relationship to DeepInsight
    deep_insight = relationship(
        "DeepInsight",
        back_populates="outcome",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_insight_outcomes_status_end_date", "tracking_status", "tracking_end_date"),
        Index("ix_insight_outcomes_created_at", "created_at"),
        Index("ix_insight_outcomes_thesis_validated", "thesis_validated"),
        Index("ix_insight_outcomes_outcome_category", "outcome_category"),
    )

    def __repr__(self) -> str:
        return (
            f"<InsightOutcome(id={self.id}, insight_id={self.insight_id}, "
            f"status={self.tracking_status!r}, category={self.outcome_category!r})>"
        )
