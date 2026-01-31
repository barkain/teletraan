"""Technical indicator model for storing calculated indicators."""

from datetime import date as date_type
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

from .base import TimestampMixin

if TYPE_CHECKING:
    from .stock import Stock


class TechnicalIndicator(TimestampMixin, Base):
    """Model representing technical indicators calculated for a stock."""

    __tablename__ = "technical_indicators"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"),
        index=True,
    )
    date: Mapped[date_type] = mapped_column(index=True)
    indicator_type: Mapped[str] = mapped_column(
        String(50),
        index=True,
    )  # 'SMA_20', 'RSI_14', 'MACD', 'BOLLINGER_UPPER', etc.
    value: Mapped[float] = mapped_column()
    metadata_json: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )  # For complex indicators with multiple values (e.g., MACD signal/histogram)

    # Relationship
    stock: Mapped["Stock"] = relationship(back_populates="technical_indicators")

    __table_args__ = (
        UniqueConstraint(
            "stock_id", "date", "indicator_type", name="uq_stock_date_indicator"
        ),
        Index("ix_indicator_stock_date_type", "stock_id", "date", "indicator_type"),
    )

    def __repr__(self) -> str:
        return f"<TechnicalIndicator(stock_id={self.stock_id}, date={self.date}, type={self.indicator_type}, value={self.value})>"
