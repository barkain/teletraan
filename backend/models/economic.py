"""Economic indicator model for storing FRED and other economic data."""

from datetime import date as date_type

from sqlalchemy import Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

from .base import TimestampMixin


class EconomicIndicator(TimestampMixin, Base):
    """Model representing economic indicators from FRED and other sources."""

    __tablename__ = "economic_indicators"

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[str] = mapped_column(
        String(50),
        index=True,
    )  # FRED series ID (e.g., 'GDP', 'UNRATE', 'FEDFUNDS')
    name: Mapped[str] = mapped_column(String(255))
    date: Mapped[date_type] = mapped_column(index=True)
    value: Mapped[float] = mapped_column()
    unit: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )  # e.g., 'Percent', 'Billions of Dollars'
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("series_id", "date", name="uq_series_date"),
        Index("ix_economic_series_date", "series_id", "date"),
    )

    def __repr__(self) -> str:
        return f"<EconomicIndicator(series_id={self.series_id!r}, date={self.date}, value={self.value})>"
