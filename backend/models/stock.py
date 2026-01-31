"""Stock model for storing stock metadata."""

from typing import TYPE_CHECKING

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

from .base import TimestampMixin

if TYPE_CHECKING:
    from .insight import Insight
    from .price import PriceHistory
    from .indicator import TechnicalIndicator


class Stock(TimestampMixin, Base):
    """Model representing a stock/security."""

    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    market_cap: Mapped[float | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)

    # Relationships
    price_history: Mapped[list["PriceHistory"]] = relationship(
        back_populates="stock",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    technical_indicators: Mapped[list["TechnicalIndicator"]] = relationship(
        back_populates="stock",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    insights: Mapped[list["Insight"]] = relationship(
        back_populates="stock",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_stocks_sector", "sector"),
        Index("ix_stocks_is_active", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<Stock(symbol={self.symbol!r}, name={self.name!r})>"
