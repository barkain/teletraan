"""Price history model for storing historical stock prices."""

from datetime import date as date_type
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

from .base import TimestampMixin

if TYPE_CHECKING:
    from .stock import Stock


class PriceHistory(TimestampMixin, Base):
    """Model representing historical price data for a stock."""

    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"),
        index=True,
    )
    date: Mapped[date_type] = mapped_column(index=True)
    open: Mapped[float] = mapped_column()
    high: Mapped[float] = mapped_column()
    low: Mapped[float] = mapped_column()
    close: Mapped[float] = mapped_column()
    volume: Mapped[int] = mapped_column()
    adjusted_close: Mapped[float | None] = mapped_column(nullable=True)

    # Relationship
    stock: Mapped["Stock"] = relationship(back_populates="price_history")

    __table_args__ = (
        UniqueConstraint("stock_id", "date", name="uq_stock_date"),
        Index("ix_price_history_stock_date", "stock_id", "date"),
    )

    def __repr__(self) -> str:
        return f"<PriceHistory(stock_id={self.stock_id}, date={self.date}, close={self.close})>"
