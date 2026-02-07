"""AnalysisTask model for tracking background autonomous analysis jobs."""

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Index, Integer, String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

from .base import TimestampMixin


class AnalysisTaskStatus(str, enum.Enum):
    """Status of an autonomous analysis task."""

    PENDING = "pending"
    MACRO_SCAN = "macro_scan"
    SECTOR_ROTATION = "sector_rotation"
    OPPORTUNITY_HUNT = "opportunity_hunt"
    HEATMAP_FETCH = "heatmap_fetch"
    HEATMAP_ANALYSIS = "heatmap_analysis"
    DEEP_DIVE = "deep_dive"
    COVERAGE_EVALUATION = "coverage_evaluation"
    SYNTHESIS = "synthesis"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Phase progress mapping for each status
PHASE_PROGRESS = {
    AnalysisTaskStatus.PENDING: 0,
    AnalysisTaskStatus.MACRO_SCAN: 10,
    AnalysisTaskStatus.SECTOR_ROTATION: 25,
    AnalysisTaskStatus.OPPORTUNITY_HUNT: 45,
    AnalysisTaskStatus.HEATMAP_FETCH: 20,
    AnalysisTaskStatus.HEATMAP_ANALYSIS: 35,
    AnalysisTaskStatus.DEEP_DIVE: 55,
    AnalysisTaskStatus.COVERAGE_EVALUATION: 75,
    AnalysisTaskStatus.SYNTHESIS: 90,
    AnalysisTaskStatus.COMPLETED: 100,
    AnalysisTaskStatus.FAILED: -1,
    AnalysisTaskStatus.CANCELLED: -1,
}

# Human-readable phase names
PHASE_NAMES = {
    AnalysisTaskStatus.PENDING: "Initializing...",
    AnalysisTaskStatus.MACRO_SCAN: "Scanning macro environment",
    AnalysisTaskStatus.SECTOR_ROTATION: "Analyzing sector rotation",
    AnalysisTaskStatus.OPPORTUNITY_HUNT: "Discovering opportunities",
    AnalysisTaskStatus.HEATMAP_FETCH: "Fetching market heatmap",
    AnalysisTaskStatus.HEATMAP_ANALYSIS: "Analyzing heatmap patterns",
    AnalysisTaskStatus.DEEP_DIVE: "Running deep analysis",
    AnalysisTaskStatus.COVERAGE_EVALUATION: "Evaluating coverage",
    AnalysisTaskStatus.SYNTHESIS: "Synthesizing insights",
    AnalysisTaskStatus.COMPLETED: "Analysis complete",
    AnalysisTaskStatus.FAILED: "Analysis failed",
    AnalysisTaskStatus.CANCELLED: "Analysis cancelled",
}


class AnalysisTask(TimestampMixin, Base):
    """Model for tracking autonomous analysis background tasks.

    This model persists analysis task state so that:
    1. Users can navigate away and return to see progress
    2. Running analyses survive page refreshes
    3. Completed results are available immediately on return
    """

    __tablename__ = "analysis_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    # Status tracking
    status: Mapped[str] = mapped_column(
        String(20),
        default=AnalysisTaskStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    progress: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )  # 0-100 percentage

    # Current phase details
    current_phase: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    phase_details: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )  # Additional context about current phase

    # Analysis parameters
    max_insights: Mapped[int] = mapped_column(
        Integer,
        default=5,
        nullable=False,
    )
    deep_dive_count: Mapped[int] = mapped_column(
        Integer,
        default=7,
        nullable=False,
    )

    # Results
    result_insight_ids: Mapped[list[int] | None] = mapped_column(
        JSON,
        nullable=True,
    )  # List of generated insight IDs
    result_analysis_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )  # Reference to the analysis result

    # Summary data (cached from analysis result)
    market_regime: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    top_sectors: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    discovery_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    phases_completed: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    # Error handling
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )
    elapsed_seconds: Mapped[float | None] = mapped_column(
        nullable=True,
    )

    __table_args__ = (
        Index("ix_analysis_tasks_status_created", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<AnalysisTask(id={self.id!r}, status={self.status!r}, "
            f"progress={self.progress})>"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "current_phase": self.current_phase,
            "phase_details": self.phase_details,
            "max_insights": self.max_insights,
            "deep_dive_count": self.deep_dive_count,
            "result_insight_ids": self.result_insight_ids,
            "result_analysis_id": self.result_analysis_id,
            "market_regime": self.market_regime,
            "top_sectors": self.top_sectors,
            "discovery_summary": self.discovery_summary,
            "phases_completed": self.phases_completed,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "elapsed_seconds": self.elapsed_seconds,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
