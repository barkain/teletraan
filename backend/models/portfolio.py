"""Portfolio models for tracking investment holdings."""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

from .base import TimestampMixin

if TYPE_CHECKING:
    pass


class Portfolio(TimestampMixin, Base):
    """Model representing an investment portfolio."""

    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), default="My Portfolio")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    holdings: Mapped[list["PortfolioHolding"]] = relationship(
        back_populates="portfolio",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Portfolio(id={self.id}, name={self.name!r})>"


class PortfolioHolding(TimestampMixin, Base):
    """Model representing a stock holding within a portfolio."""

    __tablename__ = "portfolio_holdings"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"),
        index=True,
    )
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    shares: Mapped[float] = mapped_column()
    cost_basis: Mapped[float] = mapped_column()  # price per share at purchase
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationship
    portfolio: Mapped["Portfolio"] = relationship(back_populates="holdings")

    __table_args__ = (
        UniqueConstraint("portfolio_id", "symbol", name="uq_portfolio_symbol"),
    )

    def __repr__(self) -> str:
        return f"<PortfolioHolding(id={self.id}, portfolio_id={self.portfolio_id}, symbol={self.symbol!r}, shares={self.shares})>"
