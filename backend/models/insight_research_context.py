"""InsightResearchContext model for storing complete research context with DeepInsights.

This model preserves the full analysis chain including:
- Individual analyst reports (technical, macro, sector, risk, correlation)
- Synthesis lead's aggregation and reasoning
- Market context snapshot at time of analysis

Designed for efficient retrieval to populate AI conversation context.
"""

from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

from .base import TimestampMixin

if TYPE_CHECKING:
    from .deep_insight import DeepInsight


class InsightResearchContext(TimestampMixin, Base):
    """Stores complete research context for a DeepInsight.

    This model preserves the full analysis chain including:
    - Individual analyst reports (technical, macro, sector, risk, correlation)
    - Synthesis lead's aggregation and reasoning
    - Market context snapshot at time of analysis

    Designed for efficient retrieval to populate AI conversation context.
    """

    __tablename__ = "insight_research_contexts"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # Relationship to parent DeepInsight (1:1)
    deep_insight_id: Mapped[int] = mapped_column(
        ForeignKey("deep_insights.id", ondelete="CASCADE"),
        unique=True,  # Enforces 1:1 relationship
        nullable=False,
        index=True,
    )

    # Schema version for future migrations
    schema_version: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="1.0",
    )

    # =========================================================================
    # ANALYST REPORTS (Full Structured Output)
    # =========================================================================

    # Technical Analyst complete report
    # Structure: TechnicalAnalysisResult.to_dict()
    # Contains: findings[], market_structure, key_observations, confidence,
    #           timeframes_analyzed, conflicting_signals
    technical_report: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )

    # Macro Economist complete report
    # Structure: MacroAnalysisResult.to_dict()
    # Contains: regime{}, yield_curve{}, fed_outlook, key_indicators[],
    #           market_implications[], risk_factors[]
    macro_report: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )

    # Sector Strategist complete report
    # Structure: SectorAnalysisResult.to_dict()
    # Contains: market_phase, sector_rankings[], recommendations[],
    #           rotation_signals[], phase_confidence
    sector_report: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )

    # Risk Analyst complete report
    # Structure: RiskAnalysisResult.to_dict()
    # Contains: volatility_regime{}, risk_assessments[], portfolio_risks[],
    #           tail_risks[], position_sizing{}
    risk_report: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )

    # Correlation Detective complete report
    # Structure: CorrelationAnalysisResult.to_dict()
    # Contains: divergences[], lead_lag_signals[], historical_analogs[],
    #           anomalies[], correlation_shifts[]
    correlation_report: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )

    # =========================================================================
    # SYNTHESIS DATA
    # =========================================================================

    # Synthesis Lead's raw LLM response (full text)
    synthesis_raw_response: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Synthesis summary metadata
    # Structure: SynthesisSummary.to_dict()
    # Contains: total_analysts, agreeing_analysts, conflicting_signals[],
    #           overall_market_bias, key_themes[]
    synthesis_summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )

    # =========================================================================
    # MARKET CONTEXT SNAPSHOT
    # =========================================================================

    # Symbols analyzed in this run
    symbols_analyzed: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
        default=list,
    )

    # Market summary at analysis time (SPY status, trading session)
    # Structure: { market_index: {...}, trading_session: str }
    market_summary_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )

    # Sector performance snapshot
    # Structure: { "XLK": {...}, "XLF": {...}, ... }
    sector_performance_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )

    # Economic indicators snapshot (most recent values at analysis time)
    # Structure: [{ series_id, name, value, unit, date, description }, ...]
    economic_indicators_snapshot: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON,
        nullable=True,
        default=list,
    )

    # =========================================================================
    # SUMMARY FIELDS (For Context Window Management)
    # =========================================================================

    # Condensed summary of all analyst findings (< 2000 chars)
    # Pre-generated for quick context injection without loading full reports
    analysts_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Key data points referenced (for quick validation)
    # Structure: ["RSI:NVDA=65.2", "VIX=18.5", "SPY_change=-0.5%", ...]
    key_data_points: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
        default=list,
    )

    # Total token count estimate for full context
    estimated_token_count: Mapped[int | None] = mapped_column(
        nullable=True,
        default=None,
    )

    # =========================================================================
    # METADATA
    # =========================================================================

    # Analysis duration in seconds
    analysis_duration_seconds: Mapped[float | None] = mapped_column(
        nullable=True,
    )

    # Which analysts completed successfully
    successful_analysts: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
        default=list,
    )

    # Any analyst errors captured
    analyst_errors: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )

    # =========================================================================
    # INDEXES
    # =========================================================================

    __table_args__ = (
        # Fast lookup by insight ID (already covered by unique constraint, but explicit)
        Index("ix_research_context_insight_id", "deep_insight_id"),
        # For filtering by schema version during migrations
        Index("ix_research_context_version", "schema_version"),
        # For querying by analysis time
        Index("ix_research_context_created", "created_at"),
    )

    # =========================================================================
    # RELATIONSHIP
    # =========================================================================

    # Back-reference to parent DeepInsight
    deep_insight: Mapped["DeepInsight"] = relationship(
        back_populates="research_context",
        lazy="joined",  # Eager load when accessing InsightResearchContext
    )

    def __repr__(self) -> str:
        return (
            f"<InsightResearchContext("
            f"id={self.id}, "
            f"insight_id={self.deep_insight_id}, "
            f"version={self.schema_version!r}"
            f")>"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "deep_insight_id": self.deep_insight_id,
            "schema_version": self.schema_version,
            # Analyst reports
            "technical_report": self.technical_report,
            "macro_report": self.macro_report,
            "sector_report": self.sector_report,
            "risk_report": self.risk_report,
            "correlation_report": self.correlation_report,
            # Synthesis
            "synthesis_raw_response": self.synthesis_raw_response,
            "synthesis_summary": self.synthesis_summary,
            # Market context
            "symbols_analyzed": self.symbols_analyzed,
            "market_summary_snapshot": self.market_summary_snapshot,
            "sector_performance_snapshot": self.sector_performance_snapshot,
            "economic_indicators_snapshot": self.economic_indicators_snapshot,
            # Summaries
            "analysts_summary": self.analysts_summary,
            "key_data_points": self.key_data_points,
            "estimated_token_count": self.estimated_token_count,
            # Metadata
            "analysis_duration_seconds": self.analysis_duration_seconds,
            "successful_analysts": self.successful_analysts,
            "analyst_errors": self.analyst_errors,
            # Timestamps
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def to_summary_dict(self) -> dict[str, Any]:
        """Convert to condensed dictionary for context window optimization."""
        return {
            "id": self.id,
            "deep_insight_id": self.deep_insight_id,
            "analysts_summary": self.analysts_summary,
            "key_data_points": self.key_data_points,
            "synthesis_summary": self.synthesis_summary,
            "estimated_token_count": self.estimated_token_count,
            "successful_analysts": self.successful_analysts,
        }
