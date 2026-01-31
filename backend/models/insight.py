"""Insight models for storing AI-generated analysis and annotations."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

from .base import TimestampMixin

if TYPE_CHECKING:
    from .stock import Stock


class Insight(TimestampMixin, Base):
    """Model representing AI-generated insights about stocks or markets."""

    __tablename__ = "insights"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_id: Mapped[int | None] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"),
        nullable=True,  # Nullable for market-wide insights
        index=True,
    )
    insight_type: Mapped[str] = mapped_column(
        String(50),
        index=True,
    )  # 'pattern', 'anomaly', 'sector', 'technical', 'correlation'
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(
        String(20),
        default="info",
    )  # 'info', 'warning', 'alert'
    confidence: Mapped[float] = mapped_column()  # 0.0 to 1.0
    data_json: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )  # Supporting data for the insight
    is_active: Mapped[bool] = mapped_column(default=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Relationships
    stock: Mapped["Stock | None"] = relationship(back_populates="insights")
    annotations: Mapped[list["InsightAnnotation"]] = relationship(
        back_populates="insight",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_insights_type_severity", "insight_type", "severity"),
        Index("ix_insights_is_active", "is_active"),
        Index("ix_insights_expires_at", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<Insight(id={self.id}, type={self.insight_type!r}, title={self.title!r})>"


class InsightAnnotation(TimestampMixin, Base):
    """Model for user annotations/notes on insights."""

    __tablename__ = "insight_annotations"

    id: Mapped[int] = mapped_column(primary_key=True)
    insight_id: Mapped[int] = mapped_column(
        ForeignKey("insights.id", ondelete="CASCADE"),
        index=True,
    )
    note: Mapped[str] = mapped_column(Text)

    # Relationship
    insight: Mapped["Insight"] = relationship(back_populates="annotations")

    def __repr__(self) -> str:
        return f"<InsightAnnotation(id={self.id}, insight_id={self.insight_id})>"
