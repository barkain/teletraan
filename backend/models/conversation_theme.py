"""ConversationTheme model for cross-conversation pattern tracking.

This module defines the data model for tracking recurring themes and patterns
that emerge across multiple insight conversations, enabling the system to
build institutional memory about market regimes, trends, and concerns.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Float, Index, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

from .base import TimestampMixin


class ThemeType(str, enum.Enum):
    """Classification of recurring conversation themes.

    Themes are categorized by their nature to help organize and filter
    the institutional memory built from conversations.
    """

    MARKET_REGIME = "MARKET_REGIME"  # e.g., "risk-off environment"
    SECTOR_TREND = "SECTOR_TREND"  # e.g., "AI infrastructure buildout"
    MACRO_THEME = "MACRO_THEME"  # e.g., "Fed pivot expectations"
    FACTOR_ROTATION = "FACTOR_ROTATION"  # e.g., "value to growth rotation"
    RISK_CONCERN = "RISK_CONCERN"  # e.g., "commercial real estate stress"
    OPPORTUNITY_THESIS = "OPPORTUNITY_THESIS"  # e.g., "energy transition plays"


class ConversationTheme(TimestampMixin, Base):
    """Model for tracking recurring themes across insight conversations.

    ConversationThemes capture patterns, concerns, and opportunities that
    surface repeatedly across multiple conversations. This builds institutional
    memory that enriches future conversations with relevant context.

    The relevance scoring system uses time-based decay to ensure that stale
    themes naturally fade while frequently-discussed themes remain prominent.

    Attributes:
        id: UUID primary key for distributed systems compatibility
        theme_name: Concise name for the theme (e.g., "Fed Rate Cut Expectations")
        theme_type: Classification of the theme type
        description: Detailed explanation of the theme and its implications
        keywords: Array of related terms for search and matching
        related_symbols: Array of ticker symbols associated with this theme
        related_sectors: Array of sector names associated with this theme
        source_conversation_ids: Array of conversation UUIDs where theme was discussed
        first_mentioned_at: When this theme was first identified
        last_mentioned_at: Most recent mention of this theme
        mention_count: Total number of times theme has been discussed
        current_relevance: Relevance score (0.0-1.0) that decays over time
        relevance_decay_rate: Daily decay factor for relevance (e.g., 0.95 = 5% daily decay)
        supporting_data_points: Evidence and data backing this theme
        is_active: Whether this theme is currently being tracked
    """

    __tablename__ = "conversation_themes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Core identification
    theme_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        index=True,
    )
    theme_type: Mapped[ThemeType] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Search and matching
    keywords: Mapped[list[str] | None] = mapped_column(
        JSON,
        default=list,
        nullable=True,
    )  # ["rate cuts", "FOMC", "monetary policy", "fed funds"]

    # Related entities
    related_symbols: Mapped[list[str] | None] = mapped_column(
        JSON,
        default=list,
        nullable=True,
    )  # ["TLT", "IEF", "ZROZ", "SHY"]
    related_sectors: Mapped[list[str] | None] = mapped_column(
        JSON,
        default=list,
        nullable=True,
    )  # ["Financials", "Real Estate", "Utilities"]

    # Provenance tracking
    source_conversation_ids: Mapped[list[str] | None] = mapped_column(
        JSON,
        default=list,
        nullable=True,
    )  # UUIDs stored as strings for JSON compatibility

    # Temporal tracking
    first_mentioned_at: Mapped[datetime] = mapped_column(
        nullable=False,
    )
    last_mentioned_at: Mapped[datetime] = mapped_column(
        nullable=False,
        index=True,
    )
    mention_count: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    # Relevance scoring
    current_relevance: Mapped[float] = mapped_column(
        Float,
        default=1.0,
        nullable=False,
    )  # 0.0 to 1.0, higher = more relevant
    relevance_decay_rate: Mapped[float] = mapped_column(
        Float,
        default=0.95,  # 5% daily decay by default
        nullable=False,
    )

    # Evidence
    supporting_data_points: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        default=dict,
        nullable=True,
    )  # {"key_events": [...], "analyst_views": [...], "market_data": {...}}

    # Status
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
    )

    __table_args__ = (
        Index("ix_conv_themes_type_active", "theme_type", "is_active"),
        Index("ix_conv_themes_relevance_active", "current_relevance", "is_active"),
        Index(
            "ix_conv_themes_last_mentioned_active",
            "last_mentioned_at",
            "is_active",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ConversationTheme(id={self.id}, name={self.theme_name!r}, "
            f"type={self.theme_type!r}, relevance={self.current_relevance:.2f})>"
        )
