"""Models for the v2 alpha engine pipeline."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

from .base import TimestampMixin


class AnalysisRunStatus(str, enum.Enum):
    """Lifecycle of a market analysis run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class AnalysisRun(TimestampMixin, Base):
    """One execution of the daily alpha pipeline."""

    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_type: Mapped[str] = mapped_column(String(32), default="daily", nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20),
        default=AnalysisRunStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    market_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    market_regime: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    market_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    universe_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    symbols_scanned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ideas_persisted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    portfolio_symbols: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    analysis_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    market_snapshot = relationship(
        "MarketSnapshot",
        back_populates="analysis_run",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    security_signals = relationship(
        "SecuritySignal",
        back_populates="analysis_run",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    candidate_ideas = relationship(
        "CandidateIdea",
        back_populates="analysis_run",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_analysis_runs_run_type_market_date", "run_type", "market_date"),
        Index("ix_analysis_runs_status_created_at", "status", "created_at"),
    )


class MarketSnapshot(TimestampMixin, Base):
    """Immutable market snapshot captured at analysis time."""

    __tablename__ = "market_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    market_date: Mapped[date] = mapped_column(Date, nullable=False)
    regime_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    regime_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    benchmark_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    sector_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    macro_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    breadth_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    portfolio_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    universe_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    analysis_run = relationship("AnalysisRun", back_populates="market_snapshot", lazy="selectin")

    __table_args__ = (
        Index("ix_market_snapshots_market_date", "market_date"),
        Index("ix_market_snapshots_regime_name", "regime_name"),
    )


class SecuritySignal(TimestampMixin, Base):
    """Per-symbol factor input bundle for the ranking model."""

    __tablename__ = "security_signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    signal_version: Mapped[str] = mapped_column(String(32), default="v2", nullable=False)
    overall_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    technical_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    fundamental_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    valuation_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    flow_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    sentiment_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    macro_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    catalyst_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    liquidity_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    data_completeness: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    subscores: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    analysis_run = relationship("AnalysisRun", back_populates="security_signals", lazy="selectin")

    __table_args__ = (
        Index("ix_security_signals_run_symbol", "analysis_run_id", "symbol"),
        Index("ix_security_signals_overall_score", "overall_score"),
    )


class CandidateIdea(TimestampMixin, Base):
    """Ranked output candidate from the alpha engine."""

    __tablename__ = "candidate_ideas"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    thesis_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    overall_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    expected_horizon_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bull_case: Mapped[str | None] = mapped_column(Text, nullable=True)
    bear_case: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_drivers: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    setup_trigger: Mapped[str | None] = mapped_column(Text, nullable=True)
    invalidations: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    portfolio_relevance: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_portfolio_holding: Mapped[bool] = mapped_column(default=False, nullable=False)
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    analysis_run = relationship("AnalysisRun", back_populates="candidate_ideas", lazy="selectin")

    __table_args__ = (
        Index("ix_candidate_ideas_run_rank", "analysis_run_id", "rank"),
        Index("ix_candidate_ideas_symbol", "symbol"),
    )


__all__ = [
    "AnalysisRun",
    "AnalysisRunStatus",
    "MarketSnapshot",
    "SecuritySignal",
    "CandidateIdea",
]
