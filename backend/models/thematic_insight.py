"""ThematicInsight model for persisting cross-cutting investment themes.

Thematic insights represent structural investment narratives identified from
macro analysis (e.g., "AI infrastructure bottleneck benefits photonics companies").
Unlike DeepInsights which track individual stock predictions, thematic insights
track a basket of symbols against a directional narrative thesis.
"""

import enum
import hashlib
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

from .base import TimestampMixin

if TYPE_CHECKING:
    from .thematic_outcome import ThematicOutcome


class LifecycleState(str, enum.Enum):
    """Lifecycle state of a thematic insight."""

    ACTIVE = "active"
    STALE = "stale"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


class ThematicInsight(TimestampMixin, Base):
    """Model representing a persisted thematic investment thesis.

    ThematicInsights are cross-cutting investment themes identified from
    autonomous macro analysis. They track a basket of symbols against a
    directional narrative and have their own lifecycle and outcome tracking
    independent from per-symbol DeepInsight tracking.
    """

    __tablename__ = "thematic_insights"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # Identity
    theme_name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    theme_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
    )

    # Thesis
    direction: Mapped[str] = mapped_column(
        String(20), nullable=False, default="mixed", index=True,
    )  # bullish, bearish, mixed
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    thesis: Mapped[str] = mapped_column(Text, nullable=False)
    counter_thesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_narrative: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Basket
    primary_symbols: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list,
    )
    affected_sectors: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True, default=list,
    )
    supply_chain_links: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True, default=list,
    )

    # Timing
    catalyst_timeline: Mapped[str] = mapped_column(
        String(30), nullable=False, default="medium_term",
    )  # near_term, medium_term, long_term

    # Interactions
    theme_interactions: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True, default=list,
    )

    # Lifecycle
    lifecycle_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default=LifecycleState.ACTIVE.value, index=True,
    )
    staleness_score: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=0.0,
    )
    conviction_decay_factor: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=1.0,
    )
    effective_confidence: Mapped[float | None] = mapped_column(
        Float, nullable=True,
    )
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
    )

    # Provenance
    analysis_task_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True,
    )
    run_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
    )
    superseded_by_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("thematic_insights.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Self-referential relationship
    superseded_by: Mapped["ThematicInsight | None"] = relationship(
        "ThematicInsight",
        remote_side="ThematicInsight.id",
        foreign_keys=[superseded_by_id],
    )

    # 1:1 relationship with ThematicOutcome
    outcome: Mapped["ThematicOutcome | None"] = relationship(
        back_populates="thematic_insight",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_thematic_insights_fingerprint_state", "theme_fingerprint", "lifecycle_state"),
        Index("ix_thematic_insights_created_at", "created_at"),
        Index("ix_thematic_insights_category_direction", "category", "direction"),
    )

    def compute_effective_confidence(self) -> float:
        """Return confidence adjusted by conviction decay."""
        base = self.confidence or 0.5
        decay = self.conviction_decay_factor or 1.0
        return round(base * decay, 4)

    @staticmethod
    def compute_fingerprint(category: str, primary_symbols: list[str]) -> str:
        """Compute a dedup fingerprint from category + sorted top-3 symbols.

        Args:
            category: Theme category string.
            primary_symbols: List of symbols in the theme basket.

        Returns:
            16-char hex digest for dedup matching.
        """
        top_3 = sorted(s.upper() for s in primary_symbols)[:3]
        raw = f"{category.lower()}|{'|'.join(top_3)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def __repr__(self) -> str:
        return (
            f"<ThematicInsight(id={self.id}, name={self.theme_name!r}, "
            f"category={self.category!r}, state={self.lifecycle_state!r})>"
        )
