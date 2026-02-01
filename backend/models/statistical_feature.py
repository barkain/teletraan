"""StatisticalFeature model for storing computed statistical market features."""

import enum
import uuid
from datetime import date as date_type
from typing import Any

from sqlalchemy import Date, Float, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

from .base import TimestampMixin


class StatisticalFeatureType(str, enum.Enum):
    """Types of statistical features computed for market analysis."""

    # Momentum indicators
    MOMENTUM_ROC_5D = "momentum_roc_5d"
    MOMENTUM_ROC_10D = "momentum_roc_10d"
    MOMENTUM_ROC_20D = "momentum_roc_20d"

    # Z-Score indicators
    ZSCORE_20D = "zscore_20d"
    ZSCORE_50D = "zscore_50d"

    # Bollinger band analysis
    BOLLINGER_DEVIATION = "bollinger_deviation"

    # Volatility measures
    VOLATILITY_REGIME = "volatility_regime"
    VOLATILITY_PERCENTILE = "volatility_percentile"

    # Seasonality patterns
    DAY_OF_WEEK_EFFECT = "day_of_week_effect"
    MONTH_EFFECT = "month_effect"

    # Relative strength indicators
    SECTOR_MOMENTUM_RANK = "sector_momentum_rank"
    RELATIVE_STRENGTH_SECTOR = "relative_strength_sector"

    # Market correlation
    BETA_VS_SPY = "beta_vs_spy"


class StatisticalFeature(TimestampMixin, Base):
    """Model representing computed statistical features for market symbols.

    StatisticalFeatures store quantitative signals derived from price and volume
    data, including momentum metrics, z-scores, volatility regimes, and relative
    strength measures. Each feature includes a computed value, interpretive signal,
    and optional percentile ranking.
    """

    __tablename__ = "statistical_features"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    # Symbol identification
    symbol: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )

    # Feature classification
    feature_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    # Computed values
    value: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    signal: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )  # e.g., "bullish", "bearish", "oversold", "overbought", "neutral"

    percentile: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )  # 0-100 ranking

    # Timing
    calculation_date: Mapped[date_type] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )

    # Additional context
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        default=dict,
    )

    __table_args__ = (
        Index("ix_statistical_features_symbol_date", "symbol", "calculation_date"),
        Index(
            "ix_statistical_features_symbol_type_date",
            "symbol",
            "feature_type",
            "calculation_date",
        ),
        Index("ix_statistical_features_type_signal", "feature_type", "signal"),
    )

    def __repr__(self) -> str:
        return (
            f"<StatisticalFeature(id={self.id}, symbol={self.symbol!r}, "
            f"type={self.feature_type!r}, value={self.value}, signal={self.signal!r})>"
        )
