"""Autonomous Deep Analysis Engine.

Orchestrates the heatmap-driven autonomous market analysis pipeline:
1. MacroScanner - Global macro environment scan
2. HeatmapFetch - Dynamic sector heatmap data from yfinance
3. HeatmapAnalysis - LLM-driven pattern detection and stock selection
4. Deep Dive Analysts - Detailed analysis per selected stock
4.5. CoverageEvaluation - Adaptive loop (max 2 iterations) to fill coverage gaps
5. SynthesisLead - Rank and produce final insights

This engine discovers opportunities autonomously without requiring user-provided symbols.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from database import async_session_factory  # type: ignore[import-not-found]
from models.deep_insight import DeepInsight, InsightType, InsightAction  # type: ignore[import-not-found]

from analysis.agents.macro_scanner import (  # type: ignore[import-not-found]
    MacroScanner,
    MacroScanResult,
)
from analysis.agents.sector_rotator import (  # type: ignore[import-not-found]
    SectorRotationResult,
    SECTOR_ROTATOR_PROMPT,
    format_sector_rotator_context,
    parse_sector_rotator_response,
)
from analysis.agents.opportunity_hunter import (  # type: ignore[import-not-found]
    OpportunityList,
    OPPORTUNITY_HUNTER_PROMPT,
    format_opportunity_context,
    parse_opportunity_response,
    get_all_screening_stocks,
    passes_technical_screen,
    calculate_screen_score,
    SYMBOL_TO_SECTOR,
)
from analysis.agents.heatmap_fetcher import (  # type: ignore[import-not-found]
    get_heatmap_fetcher,
    format_heatmap_for_llm,
)
from analysis.agents.heatmap_analyzer import (  # type: ignore[import-not-found]
    format_heatmap_analysis_context,
    parse_heatmap_analysis_response,
)
from analysis.agents.coverage_evaluator import (  # type: ignore[import-not-found]
    format_coverage_context,
    parse_coverage_response,
    COVERAGE_EVALUATOR_PROMPT,
)
from analysis.agents.heatmap_interfaces import (  # type: ignore[import-not-found]
    HeatmapData,
    HeatmapAnalysis,
    CoverageEvaluation,
)
from analysis.agents.technical_analyst import (  # type: ignore[import-not-found]
    TECHNICAL_ANALYST_PROMPT,
    format_technical_context,
    parse_technical_response,
)
from analysis.agents.sector_strategist import (  # type: ignore[import-not-found]
    SECTOR_STRATEGIST_PROMPT,
    format_sector_context,
    parse_sector_response,
)
from analysis.agents.macro_economist import (  # type: ignore[import-not-found]
    MACRO_ECONOMIST_PROMPT,
    format_macro_context,
    parse_macro_response,
)
from analysis.agents.risk_analyst import (  # type: ignore[import-not-found]
    RISK_ANALYST_PROMPT,
    format_risk_context,
    parse_risk_response,
)
from analysis.agents.correlation_detective import (  # type: ignore[import-not-found]
    CORRELATION_DETECTIVE_PROMPT,
    format_correlation_context,
    parse_correlation_response,
)
from analysis.agents.synthesis_lead import (  # type: ignore[import-not-found]
    format_synthesis_context,
    parse_synthesis_response,
    format_synthesis_prompt_with_context,
    build_pattern_context,
    build_track_record_context,
)
from analysis.context_builder import MarketContextBuilder  # type: ignore[import-not-found]
from analysis.memory_service import InstitutionalMemoryService  # type: ignore[import-not-found]
from analysis.pattern_extractor import PatternExtractor  # type: ignore[import-not-found]
from analysis.outcome_tracker import InsightOutcomeTracker  # type: ignore[import-not-found]
from llm.client_pool import pool_query_llm, LLMQueryResult  # type: ignore[import-not-found]

# Optional alternative data sources (availability flags)
_HAS_PREDICTIONS = importlib.util.find_spec("data.adapters.prediction_markets") is not None
_HAS_SENTIMENT = importlib.util.find_spec("data.adapters.reddit_sentiment") is not None

logger = logging.getLogger(__name__)


@dataclass
class LLMActivityEntry:
    """Record of a single LLM query during analysis."""

    seq: int  # auto-increment sequence number
    timestamp: str  # ISO datetime
    phase: str  # e.g. "macro_scan", "deep_dive"
    agent_name: str  # e.g. "technical", "synthesis"
    prompt_preview: str  # first ~300 chars of user_prompt
    response_preview: str  # first ~500 chars of response (filled after completion)
    input_tokens: int  # from LLMQueryResult
    output_tokens: int
    duration_ms: int
    status: str  # "running" | "done" | "error"
    symbol: str = ""  # stock symbol for deep_dive entries (e.g. "AAPL")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON response."""
        return {
            "seq": self.seq,
            "timestamp": self.timestamp,
            "phase": self.phase,
            "agent_name": self.agent_name,
            "prompt_preview": self.prompt_preview,
            "response_preview": self.response_preview,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "symbol": self.symbol,
        }


# Valid insight types and actions for validation
VALID_INSIGHT_TYPES = {t.value for t in InsightType}
VALID_ACTIONS = {a.value for a in InsightAction}


@dataclass
class AutonomousAnalysisResult:
    """Complete result from autonomous analysis pipeline."""

    analysis_id: str
    insights: list[DeepInsight] = field(default_factory=list)
    macro_result: MacroScanResult | None = None
    sector_result: SectorRotationResult | None = None
    heatmap_data: HeatmapData | None = None
    heatmap_analysis: HeatmapAnalysis | None = None
    candidates: OpportunityList | None = None
    discovery_summary: str = ""
    analyst_reports: dict[str, dict[str, Any]] = field(default_factory=dict)
    elapsed_seconds: float = 0.0
    phases_completed: list[str] = field(default_factory=list)
    phase_summaries: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    run_metrics: RunMetrics | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "analysis_id": self.analysis_id,
            "insights": [
                {
                    "id": i.id,
                    "insight_type": i.insight_type,
                    "action": i.action,
                    "title": i.title,
                    "thesis": i.thesis,
                    "primary_symbol": i.primary_symbol,
                    "confidence": i.confidence,
                    "time_horizon": i.time_horizon,
                }
                for i in self.insights
            ],
            "macro_result": self.macro_result.to_dict() if self.macro_result else None,
            "sector_result": self.sector_result.to_dict() if self.sector_result else None,
            "heatmap_data": self.heatmap_data.to_dict() if self.heatmap_data else None,
            "heatmap_analysis": self.heatmap_analysis.to_dict() if self.heatmap_analysis else None,
            "candidates": self.candidates.to_dict() if self.candidates else None,
            "discovery_summary": self.discovery_summary,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "phases_completed": self.phases_completed,
            "phase_summaries": self.phase_summaries,
            "errors": self.errors,
        }


@dataclass
class RunMetrics:
    """Accumulator for LLM usage and phase timing metrics across an analysis run."""

    phase_timings: dict[str, dict[str, Any]] = field(default_factory=dict)
    phase_token_usage: dict[str, dict[str, Any]] = field(default_factory=dict)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    model: str = ""
    provider: str = ""
    llm_call_count: int = 0

    # Track which phase is currently active so _query_llm can attribute tokens
    _current_phase: str | None = field(default=None, repr=False)

    def start_phase(self, name: str) -> None:
        """Record the start of a pipeline phase."""
        self.phase_timings[name] = {
            "start": datetime.utcnow().isoformat(),
            "end": None,
            "duration_seconds": 0.0,
        }
        # Initialise token bucket for the phase
        if name not in self.phase_token_usage:
            self.phase_token_usage[name] = {
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
                "llm_calls": 0,
            }
        self._current_phase = name

    def end_phase(self, name: str) -> None:
        """Record the end of a pipeline phase and compute duration."""
        entry = self.phase_timings.get(name)
        if entry and entry.get("start"):
            end_time = datetime.utcnow()
            entry["end"] = end_time.isoformat()
            try:
                start_dt = datetime.fromisoformat(entry["start"])
                entry["duration_seconds"] = round(
                    (end_time - start_dt).total_seconds(), 2
                )
            except (ValueError, TypeError) as parse_err:
                logger.debug("Could not compute phase duration for %s: %s", name, parse_err)
        if self._current_phase == name:
            self._current_phase = None

    def record_llm_call(self, result: LLMQueryResult) -> None:
        """Accumulate token counts and cost from a single LLM call."""
        self.total_input_tokens += result.input_tokens
        self.total_output_tokens += result.output_tokens
        self.total_cost_usd += result.cost_usd
        self.llm_call_count += 1

        if result.model and not self.model:
            self.model = result.model

        # Attribute to current phase
        phase = self._current_phase
        if phase and phase in self.phase_token_usage:
            bucket = self.phase_token_usage[phase]
            bucket["input_tokens"] += result.input_tokens
            bucket["output_tokens"] += result.output_tokens
            bucket["cost_usd"] += result.cost_usd
            bucket["llm_calls"] = bucket.get("llm_calls", 0) + 1

    def to_task_fields(self) -> dict[str, Any]:
        """Return a dict of values ready to set on an AnalysisTask row."""
        return {
            "phase_timings": json.dumps(self.phase_timings),
            "phase_token_usage": json.dumps(self.phase_token_usage),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "model_used": self.model,
            "provider_used": self.provider,
            "llm_call_count": self.llm_call_count,
        }


class AutonomousDeepEngine:
    """Self-guided market analysis engine.

    Discovers opportunities autonomously without requiring user-provided symbols.
    Runs a heatmap-driven analysis pipeline:
    1. Macro Scan - Identify market regime and themes
    2. Heatmap Fetch - Dynamic sector heatmap data
    3. Heatmap Analysis - LLM pattern detection and stock selection
    4. Deep Dive - Detailed analysis by specialist analysts
    4.5. Coverage Evaluation - Adaptive loop to fill gaps (max 2 iterations)
    5. Synthesis - Aggregate and rank insights

    Falls back to the legacy sector rotation / opportunity hunt pipeline
    if heatmap fetch fails.

    Example:
        ```python
        engine = AutonomousDeepEngine()
        result = await engine.run_autonomous_analysis()

        for insight in result.insights:
            print(f"{insight.action}: {insight.title}")
        ```
    """

    # Analyst configurations (same as DeepAnalysisEngine)
    ANALYSTS = {
        "technical": {
            "prompt": TECHNICAL_ANALYST_PROMPT,
            "format_context": format_technical_context,
            "parse_response": parse_technical_response,
            "context_type": "technical",
        },
        "sector": {
            "prompt": SECTOR_STRATEGIST_PROMPT,
            "format_context": format_sector_context,
            "parse_response": parse_sector_response,
            "context_type": "sector",
        },
        "macro": {
            "prompt": MACRO_ECONOMIST_PROMPT,
            "format_context": format_macro_context,
            "parse_response": parse_macro_response,
            "context_type": "macro",
        },
        "correlation": {
            "prompt": CORRELATION_DETECTIVE_PROMPT,
            "format_context": format_correlation_context,
            "parse_response": parse_correlation_response,
            "context_type": "correlation",
        },
        "risk": {
            "prompt": RISK_ANALYST_PROMPT,
            "format_context": format_risk_context,
            "parse_response": parse_risk_response,
            "context_type": "risk",
        },
    }

    def __init__(
        self,
        max_retries: int = 2,
        timeout_seconds: int = 120,
    ) -> None:
        """Initialize the autonomous analysis engine.

        Args:
            max_retries: Maximum retries per analyst on failure.
            timeout_seconds: Timeout for each analyst query.
        """
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self.context_builder = MarketContextBuilder()

        # Per-run metrics accumulator (set at the start of each analysis run)
        self._run_metrics: RunMetrics | None = None

        # Activity log for live LLM tracking (scoped per task_id)
        self._activity_log: list[LLMActivityEntry] = []
        self._activity_seq: int = 0
        self._current_task_id: str | None = None

        # Phase 1: Macro Scanner
        self.macro_scanner = MacroScanner()

        # Limit concurrent LLM calls to avoid overloading the client pool
        self._llm_semaphore = asyncio.Semaphore(5)

        self._last_analysis_time: datetime | None = None

    async def _get_portfolio_holdings(self) -> dict[str, dict[str, float]]:
        """Fetch portfolio holdings from the database.

        Returns a dict mapping symbol to holding info, e.g.:
        {"AAPL": {"shares": 50, "cost_basis": 150.0, "total_cost": 7500.0}}

        Returns an empty dict if no portfolio exists or on any error.
        Portfolio fetch failure must never break the analysis pipeline.
        """
        try:
            from sqlalchemy import select  # type: ignore[import-not-found]
            from models.portfolio import Portfolio  # type: ignore[import-not-found]

            async with async_session_factory() as session:
                result = await session.execute(select(Portfolio).limit(1))
                portfolio = result.scalar_one_or_none()

                if not portfolio or not portfolio.holdings:
                    return {}

                holdings: dict[str, dict[str, float]] = {}
                for h in portfolio.holdings:
                    holdings[h.symbol.upper()] = {
                        "shares": h.shares,
                        "cost_basis": h.cost_basis,
                        "total_cost": h.shares * h.cost_basis,
                    }

                logger.info(
                    f"Loaded {len(holdings)} portfolio holdings: "
                    f"{', '.join(holdings.keys())}"
                )
                return holdings

        except Exception as e:
            logger.warning(f"Failed to fetch portfolio holdings (non-fatal): {e}")
            return {}

    async def _prefetch_prediction_data(self) -> dict:
        """Pre-fetch prediction market data before pipeline starts.

        Returns:
            Dict of macro prediction categories, or empty dict on failure.
        """
        if not _HAS_PREDICTIONS:
            return {}
        try:
            from data.adapters.prediction_markets import get_prediction_market_aggregator  # type: ignore[import-not-found]

            aggregator = get_prediction_market_aggregator()
            data = await aggregator.get_macro_predictions()
            logger.info(f"Pre-fetched prediction market data: {len(data)} categories")
            return data
        except Exception as e:
            logger.warning(f"Failed to pre-fetch prediction data: {e}")
            return {}

    async def _prefetch_sentiment_data(self) -> dict:
        """Pre-fetch Reddit sentiment data before pipeline starts.

        Returns:
            Dict with 'trending' and 'market_mood' keys, or empty dict on failure.
        """
        if not _HAS_SENTIMENT:
            return {}
        try:
            from data.adapters.reddit_sentiment import get_reddit_sentiment_adapter  # type: ignore[import-not-found]

            adapter = get_reddit_sentiment_adapter()
            trending = await adapter.get_trending_tickers(limit=50)
            market_mood = await adapter.get_market_sentiment()
            logger.info(f"Pre-fetched sentiment data: {len(trending)} trending tickers")
            return {"trending": trending, "market_mood": market_mood}
        except Exception as e:
            logger.warning(f"Failed to pre-fetch sentiment data: {e}")
            return {}

    def _build_portfolio_synthesis_context(
        self,
        portfolio_holdings: dict[str, dict[str, float]],
    ) -> str:
        """Build portfolio context string for the synthesis prompt.

        Args:
            portfolio_holdings: Dict from _get_portfolio_holdings().

        Returns:
            Formatted portfolio context string, or empty string if no holdings.
        """
        if not portfolio_holdings:
            return ""

        total_cost = sum(h["total_cost"] for h in portfolio_holdings.values())

        lines = [
            "",
            "## Portfolio Holdings",
            "The user holds positions in the following stocks. "
            "Consider how the analysis findings impact these holdings specifically. "
            "Highlight any risks or opportunities directly relevant to held positions.",
            "",
        ]

        for symbol, info in sorted(
            portfolio_holdings.items(),
            key=lambda x: x[1]["total_cost"],
            reverse=True,
        ):
            allocation_pct = (
                (info["total_cost"] / total_cost * 100) if total_cost > 0 else 0
            )
            lines.append(
                f"- {symbol}: {info['shares']:.1f} shares @ "
                f"${info['cost_basis']:.2f} cost basis "
                f"({allocation_pct:.1f}% of portfolio)"
            )

        lines.append(
            "\nPrioritize insights that directly affect held positions. "
            "Flag any bearish signals on held stocks as portfolio risks."
        )

        return "\n".join(lines)

    async def run_autonomous_analysis(
        self,
        max_insights: int = 5,
        deep_dive_count: int = 7,
        task_id: str | None = None,
    ) -> AutonomousAnalysisResult:
        """Run complete autonomous analysis pipeline.

        Executes the heatmap-driven autonomous analysis:
        1. Macro Scan - Global macro environment
        2. Heatmap Fetch - Dynamic sector/stock heatmap data
        3. Heatmap Analysis - LLM pattern detection and stock selection
        4. Deep Dive - Detailed analysis per selected stock
        4.5. Coverage Evaluation - Adaptive coverage loop (max 2 iterations)
        5. Synthesis - Rank and produce final insights

        Falls back to legacy sector rotation / opportunity hunt if heatmap fails.

        Args:
            max_insights: Number of final insights to produce (default 5).
            deep_dive_count: Number of opportunities to analyze in detail (default 7).
            task_id: Optional task ID for progress tracking in database.

        Returns:
            AutonomousAnalysisResult with insights, context, and metadata.
        """
        analysis_id = str(uuid4())
        start_time = datetime.utcnow()
        result = AutonomousAnalysisResult(analysis_id=analysis_id)

        # Clear activity log for new run, scoped to this task_id
        self.clear_activity_log(task_id=task_id)

        # Initialise per-run metrics accumulator
        metrics = RunMetrics()
        self._run_metrics = metrics
        try:
            from config import get_settings  # type: ignore[import-not-found]
            cfg = get_settings()
            metrics.provider = cfg.get_llm_provider()
            metrics.model = getattr(cfg, "ANTHROPIC_MODEL", "")
        except Exception as cfg_err:
            logger.debug("Could not read LLM config for metrics: %s", cfg_err)

        logger.info(f"Starting autonomous analysis {analysis_id}")

        try:
            # ===== PRE-FETCH + PHASE 1 + PHASE 2 (all concurrent) =====
            # Macro scan, heatmap fetch, and alternative data pre-fetches are
            # all independent -- run them concurrently to save wall-clock time.
            logger.info("Phase 1+2 + data pre-fetch: Scanning macro, fetching heatmap & alternative data concurrently...")
            await self._update_task_progress(task_id, "macro_scan", 10, "Scanning macro environment & fetching heatmap...")
            metrics.start_phase("macro_scan")
            metrics.start_phase("heatmap_fetch")

            macro_coro = self._run_macro_scan()
            heatmap_coro = self._run_heatmap_fetch()
            prediction_coro = self._prefetch_prediction_data()
            sentiment_coro = self._prefetch_sentiment_data()
            phase1_result, phase2_result, prediction_data, sentiment_data = await asyncio.gather(
                macro_coro, heatmap_coro, prediction_coro, sentiment_coro,
                return_exceptions=True,
            )

            # --- Handle pre-fetch results (non-blocking) ---
            if isinstance(prediction_data, BaseException):
                logger.warning(f"Prediction pre-fetch failed: {prediction_data}")
                prediction_data = {}
            if isinstance(sentiment_data, BaseException):
                logger.warning(f"Sentiment pre-fetch failed: {sentiment_data}")
                sentiment_data = {}

            # Store pre-fetched data on instance for downstream access
            self._prediction_data = prediction_data
            self._sentiment_data = sentiment_data

            # Build pre-fetch phase summary
            prediction_count = len(prediction_data) if isinstance(prediction_data, dict) else 0
            trending_count = len(sentiment_data.get("trending", [])) if isinstance(sentiment_data, dict) else 0
            result.phase_summaries["data_prefetch"] = (
                f"Pre-fetched {prediction_count} prediction categories "
                f"and {trending_count} trending tickers from alternative data sources."
            )

            # --- Handle Phase 1 (macro scan) result ---
            if isinstance(phase1_result, BaseException):
                raise phase1_result  # Macro scan is required; propagate failure
            macro_result: MacroScanResult = phase1_result
            result.macro_result = macro_result
            result.phases_completed.append("macro_scan")
            metrics.end_phase("macro_scan")
            logger.info(f"Macro scan complete. Regime: {macro_result.market_regime}")

            # Capture macro scan summary from structured data
            theme_names = [t.name for t in macro_result.themes[:3]]
            risk_names = [r.description for r in macro_result.key_risks[:2]]
            macro_summary_parts = [
                f"Detected {macro_result.market_regime} regime ({macro_result.regime_confidence:.0%} confidence).",
            ]
            if theme_names:
                macro_summary_parts.append(f"Key themes: {', '.join(theme_names)}.")
            if risk_names:
                macro_summary_parts.append(f"Top risks: {', '.join(risk_names)}.")
            result.phase_summaries["macro_scan"] = " ".join(macro_summary_parts)

            # --- Handle Phase 2 (heatmap fetch) result ---
            metrics.end_phase("heatmap_fetch")
            if isinstance(phase2_result, BaseException):
                logger.warning(f"Heatmap fetch failed (will use legacy fallback): {phase2_result}")
                result.errors.append(f"Heatmap fetch failed (using legacy fallback): {str(phase2_result)}")
                result = await self._run_legacy_pipeline(
                    result, macro_result, deep_dive_count, max_insights, task_id
                )
            else:
                heatmap_data: HeatmapData = phase2_result
                result.heatmap_data = heatmap_data
                result.phases_completed.append("heatmap_fetch")
                logger.info(
                    f"Heatmap fetch complete. {len(heatmap_data.sectors)} sectors, "
                    f"{len(heatmap_data.stocks)} stocks"
                )

                # Capture heatmap fetch summary from structured data
                best_sector = max(heatmap_data.sectors, key=lambda s: s.change_1d) if heatmap_data.sectors else None
                worst_sector = min(heatmap_data.sectors, key=lambda s: s.change_1d) if heatmap_data.sectors else None
                hf_parts = [
                    f"Fetched {len(heatmap_data.sectors)} sectors and {len(heatmap_data.stocks)} stocks ({heatmap_data.market_status}).",
                ]
                if best_sector and worst_sector:
                    hf_parts.append(
                        f"Strongest: {best_sector.name} ({best_sector.change_1d:+.1f}%), "
                        f"weakest: {worst_sector.name} ({worst_sector.change_1d:+.1f}%)."
                    )
                result.phase_summaries["heatmap_fetch"] = " ".join(hf_parts)

                # ===== PHASE 3+: Heatmap Pipeline (with legacy fallback) =====
                try:
                    result = await self._run_heatmap_pipeline(
                        result, macro_result, heatmap_data, deep_dive_count, max_insights, task_id
                    )
                except Exception as heatmap_err:
                    logger.warning(f"Heatmap pipeline failed, falling back to legacy: {heatmap_err}")
                    result.errors.append(f"Heatmap pipeline failed (using legacy fallback): {str(heatmap_err)}")
                    result = await self._run_legacy_pipeline(
                        result, macro_result, deep_dive_count, max_insights, task_id
                    )

        except Exception as e:
            logger.error(f"Autonomous analysis failed: {e}")
            result.errors.append(str(e))

        result.elapsed_seconds = (datetime.utcnow() - start_time).total_seconds()
        self._last_analysis_time = datetime.utcnow()

        # Attach metrics to result and clear instance reference
        result.run_metrics = metrics
        self._run_metrics = None

        logger.info(
            f"Autonomous analysis complete in {result.elapsed_seconds:.1f}s. "
            f"Generated {len(result.insights)} insights. "
            f"LLM calls: {metrics.llm_call_count}, "
            f"tokens: {metrics.total_input_tokens}+{metrics.total_output_tokens}, "
            f"cost: ${metrics.total_cost_usd:.4f}"
        )

        return result

    # ------------------------------------------------------------------
    # New heatmap pipeline phases
    # ------------------------------------------------------------------

    async def _run_heatmap_pipeline(
        self,
        result: AutonomousAnalysisResult,
        macro_result: MacroScanResult,
        heatmap_data: HeatmapData,
        deep_dive_count: int,
        max_insights: int,
        task_id: str | None,
    ) -> AutonomousAnalysisResult:
        """Run the heatmap-driven pipeline (Phases 3-5).

        Heatmap data is already fetched by the caller and passed in.
        Any failure propagates to the caller which falls back to
        the legacy pipeline.

        Args:
            result: The in-progress result to populate.
            macro_result: Macro scan results from Phase 1.
            heatmap_data: Heatmap data from Phase 2.
            deep_dive_count: Number of stocks to deep dive.
            max_insights: Max insights to generate.
            task_id: Optional task ID for progress tracking.

        Returns:
            Completed AutonomousAnalysisResult.
        """

        # ===== Load portfolio holdings (non-blocking) =====
        portfolio_holdings = await self._get_portfolio_holdings()

        # ===== PHASE 3: Heatmap Analysis =====
        logger.info("Phase 3: Analyzing heatmap patterns...")
        await self._update_task_progress(task_id, "heatmap_analysis", 35, "Analyzing heatmap patterns...")
        if self._run_metrics:
            self._run_metrics.start_phase("heatmap_analysis")
        heatmap_analysis_result = await self._run_heatmap_analysis(
            heatmap_data, macro_result
        )
        result.heatmap_analysis = heatmap_analysis_result
        result.phases_completed.append("heatmap_analysis")
        if self._run_metrics:
            self._run_metrics.end_phase("heatmap_analysis")
        logger.info(
            f"Heatmap analysis complete. Selected {len(heatmap_analysis_result.selected_stocks)} stocks"
        )

        # Capture heatmap analysis summary
        ha_high = heatmap_analysis_result.get_high_priority_stocks()
        ha_patterns_desc = [p.description[:60] for p in heatmap_analysis_result.patterns[:2]]
        ha_parts = [
            f"Selected {len(heatmap_analysis_result.selected_stocks)} stocks "
            f"({len(ha_high)} high priority) at {heatmap_analysis_result.confidence:.0%} confidence.",
        ]
        if heatmap_analysis_result.sectors_to_watch:
            ha_parts.append(f"Sectors to watch: {', '.join(heatmap_analysis_result.sectors_to_watch[:4])}.")
        if ha_patterns_desc:
            ha_parts.append(f"Key patterns: {'; '.join(ha_patterns_desc)}.")
        result.phase_summaries["heatmap_analysis"] = " ".join(ha_parts)

        # ===== PHASE 4: Deep Dive Analysis =====
        # Get stocks from heatmap analysis: high priority first, then others
        high_priority = heatmap_analysis_result.get_high_priority_stocks()
        remaining = [
            s for s in heatmap_analysis_result.selected_stocks
            if s.priority != "high"
        ]
        ordered_selections = high_priority + remaining
        symbols_to_analyze = [
            s.symbol for s in ordered_selections[:deep_dive_count]
        ]

        # Merge portfolio holdings into deep dive list (max 10 extra)
        if portfolio_holdings:
            existing_symbols = set(symbols_to_analyze)
            portfolio_additions = [
                sym for sym in portfolio_holdings
                if sym not in existing_symbols
            ][:10]
            if portfolio_additions:
                symbols_to_analyze.extend(portfolio_additions)
                logger.info(
                    f"Added {len(portfolio_additions)} portfolio-held symbols "
                    f"to deep dive: {portfolio_additions}"
                )

        logger.info(f"Phase 4: Deep diving into {symbols_to_analyze}...")
        await self._update_task_progress(
            task_id, "deep_dive", 55,
            f"Analyzing {len(symbols_to_analyze)} candidates..."
        )
        if self._run_metrics:
            self._run_metrics.start_phase("deep_dive")

        # Build discovery context using macro result and heatmap analysis
        discovery_context = self._build_heatmap_discovery_context(
            macro_result, heatmap_analysis_result
        )

        # Run all symbols concurrently (semaphore gates actual LLM calls)
        analyst_reports: dict[str, dict[str, Any]] = {}

        # Pre-build context for all symbols at once to avoid redundant fetches
        pre_context = await self.context_builder.build_context(
            symbols=symbols_to_analyze,
            include_price_history=True,
            include_technical=True,
            include_economic=True,
            include_sectors=True,
            include_rich_technical=True,
            include_fundamentals=True,
        )

        async def _analyze_symbol(sym: str) -> tuple[str, dict[str, Any]]:
            reports = await self._run_analysts_for_symbol(sym, discovery_context, pre_built_context=pre_context)
            return sym, reports

        gather_results = await asyncio.gather(
            *[_analyze_symbol(sym) for sym in symbols_to_analyze],
            return_exceptions=True,
        )

        for r in gather_results:
            if isinstance(r, BaseException):
                logger.error(f"Deep dive failed for a symbol: {r}")
                result.errors.append(f"Deep dive: {str(r)}")
            else:
                symbol, symbol_reports = r
                analyst_reports[symbol] = symbol_reports

        result.analyst_reports = analyst_reports
        result.phases_completed.append("deep_dive")
        if self._run_metrics:
            self._run_metrics.end_phase("deep_dive")
        await self._update_task_progress(task_id, "deep_dive", 70, "Deep analysis complete")

        # Capture deep dive summary
        successful_symbols = list(analyst_reports.keys())
        failed_count = sum(1 for r in gather_results if isinstance(r, BaseException))
        dd_parts = [
            f"Analyzed {len(successful_symbols)} stocks successfully"
            f"{f' ({failed_count} failed)' if failed_count else ''}.",
            f"Symbols: {', '.join(successful_symbols[:8])}"
            f"{'...' if len(successful_symbols) > 8 else ''}.",
        ]
        result.phase_summaries["deep_dive"] = " ".join(dd_parts)

        # ===== PHASE 4.5: Coverage Evaluation (adaptive loop) =====
        logger.info("Phase 4.5: Evaluating coverage...")
        await self._update_task_progress(
            task_id, "coverage_evaluation", 75, "Evaluating coverage..."
        )
        if self._run_metrics:
            self._run_metrics.start_phase("coverage_evaluation")

        analyst_reports = await self._run_coverage_loop(
            analyst_reports=analyst_reports,
            heatmap_data=heatmap_data,
            macro_result=macro_result,
            discovery_context=discovery_context,
            task_id=task_id,
        )
        result.analyst_reports = analyst_reports
        result.phases_completed.append("coverage_evaluation")
        if self._run_metrics:
            self._run_metrics.end_phase("coverage_evaluation")

        # Capture coverage evaluation summary
        pre_coverage_count = len(symbols_to_analyze)
        post_coverage_count = len(analyst_reports)
        added_count = post_coverage_count - pre_coverage_count
        if added_count > 0:
            added_symbols = [s for s in analyst_reports if s not in symbols_to_analyze]
            ce_summary = (
                f"Coverage loop added {added_count} additional stocks: "
                f"{', '.join(added_symbols[:5])}. "
                f"Total coverage: {post_coverage_count} stocks."
            )
        else:
            ce_summary = (
                f"Coverage sufficient with {post_coverage_count} stocks. "
                f"No additional symbols needed."
            )
        result.phase_summaries["coverage_evaluation"] = ce_summary

        # ===== PHASE 5: Synthesis =====
        logger.info("Phase 5: Synthesizing insights...")
        await self._update_task_progress(task_id, "synthesis", 90, "Synthesizing insights...")
        if self._run_metrics:
            self._run_metrics.start_phase("synthesis")
        insights_data = await self._run_synthesis_with_heatmap(
            analyst_reports=analyst_reports,
            macro_context=macro_result,
            heatmap_analysis=heatmap_analysis_result,
            max_insights=max_insights,
            portfolio_holdings=portfolio_holdings,
        )
        result.phases_completed.append("synthesis")
        if self._run_metrics:
            self._run_metrics.end_phase("synthesis")

        # Save insights to database
        async with async_session_factory() as session:
            saved_insights = await self._store_insights_from_heatmap(
                session,
                insights_data,
                macro_result,
                heatmap_analysis_result,
                pre_context=pre_context,
            )
            result.insights = saved_insights

        # Capture synthesis summary
        actions = [i.get("action", "HOLD") for i in insights_data]
        avg_conf = (
            sum(float(i.get("confidence", 0)) for i in insights_data) / len(insights_data)
            if insights_data else 0
        )
        titles = [i.get("title", "")[:40] for i in insights_data[:3]]
        synth_parts = [
            f"Generated {len(insights_data)} insights (avg confidence: {avg_conf:.0%}).",
        ]
        if actions:
            from collections import Counter
            action_counts = Counter(actions)
            action_str = ", ".join(f"{cnt} {act}" for act, cnt in action_counts.most_common(3))
            synth_parts.append(f"Actions: {action_str}.")
        if titles:
            synth_parts.append(f"Top: {'; '.join(titles)}.")
        result.phase_summaries["synthesis"] = " ".join(synth_parts)

        result.discovery_summary = self._build_heatmap_discovery_summary(
            macro_result, heatmap_analysis_result, heatmap_data
        )

        return result

    async def _run_heatmap_fetch(self) -> HeatmapData:
        """Run Phase 2: Heatmap Fetch.

        Attempts to use the dynamic universe from universe_builder for a
        broader stock universe. Falls back to the default static holdings.

        Returns:
            HeatmapData with sector and stock heatmap entries.
        """
        fetcher = get_heatmap_fetcher()
        # Attempt to inject dynamic holdings into the fetcher
        try:
            from analysis.agents.heatmap_fetcher import get_dynamic_holdings  # type: ignore[import-not-found]
            dynamic_holdings = await get_dynamic_holdings()
            if dynamic_holdings:
                fetcher._fallback_holdings = dynamic_holdings
        except Exception as exc:
            logger.debug("Dynamic holdings unavailable for heatmap fetch: %s", exc)
        return await fetcher.fetch_heatmap_data()

    async def _run_heatmap_analysis(
        self,
        heatmap_data: HeatmapData,
        macro_result: MacroScanResult,
    ) -> HeatmapAnalysis:
        """Run Phase 3: Heatmap Analysis.

        Args:
            heatmap_data: Heatmap data from Phase 2.
            macro_result: Macro scan results from Phase 1.

        Returns:
            HeatmapAnalysis with patterns and selected stocks.
        """
        # Format heatmap data for LLM
        heatmap_summary = format_heatmap_for_llm(heatmap_data)

        # Build macro context dict for the analyzer
        macro_context_dict = macro_result.to_dict()

        # Format complete analysis context (returns the filled prompt)
        formatted_context = format_heatmap_analysis_context(
            heatmap_summary,
            macro_context_dict,
        )

        # Query LLM — the formatted_context IS the full prompt (system+context merged)
        response = await self._query_llm(
            formatted_context,
            "Analyze the heatmap data and select stocks for deep dive.",
            "heatmap_analyzer",
            "heatmap_analysis",
        )

        return parse_heatmap_analysis_response(response)

    async def _run_coverage_evaluation(
        self,
        analyst_reports: dict[str, dict[str, Any]],
        heatmap_data: HeatmapData,
        macro_result: MacroScanResult,
        iteration: int,
    ) -> CoverageEvaluation:
        """Run a single coverage evaluation iteration.

        Args:
            analyst_reports: Deep dive results so far.
            heatmap_data: Full heatmap data.
            macro_result: Macro scan results.
            iteration: Current iteration number (1 or 2).

        Returns:
            CoverageEvaluation with gaps and recommended additions.
        """
        # Build analyzed stocks summary from analyst reports
        analyzed_stocks: list[dict[str, Any]] = []
        for symbol, reports in analyst_reports.items():
            summary_parts: list[str] = []
            action = "N/A"
            confidence = 0.0
            sector = "Unknown"

            for analyst_name, report in reports.items():
                if "error" in report:
                    continue
                if analyst_name == "technical":
                    findings = report.get("findings", [])
                    if findings:
                        summary_parts.append(f"Technical: {len(findings)} findings")
                    confidence = max(confidence, report.get("confidence", 0.0))
                elif analyst_name == "risk":
                    assessments = report.get("risk_assessments", [])
                    if assessments:
                        summary_parts.append(f"Risk: {len(assessments)} assessments")

            # Try to get sector from heatmap data
            for stock in heatmap_data.stocks:
                if stock.symbol == symbol:
                    sector = stock.sector
                    break

            analyzed_stocks.append({
                "symbol": symbol,
                "sector": sector,
                "summary": "; ".join(summary_parts) if summary_parts else "Analysis complete",
                "action": action,
                "confidence": confidence,
            })

        # Format context for coverage evaluator
        formatted_context = format_coverage_context(
            analyzed_stocks,
            heatmap_data.to_dict(),
            macro_result.to_dict(),
            iteration,
        )

        # Query LLM
        response = await self._query_llm(
            COVERAGE_EVALUATOR_PROMPT,
            formatted_context,
            "coverage_evaluator",
            "coverage_evaluation",
        )

        evaluation = parse_coverage_response(response)
        evaluation.iteration_number = iteration
        return evaluation

    async def _run_coverage_loop(
        self,
        analyst_reports: dict[str, dict[str, Any]],
        heatmap_data: HeatmapData,
        macro_result: MacroScanResult,
        discovery_context: str,
        task_id: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Run the adaptive coverage evaluation loop.

        Evaluates coverage and runs additional deep dives if needed,
        up to CoverageEvaluation.MAX_ITERATIONS times.

        Args:
            analyst_reports: Current deep dive results.
            heatmap_data: Full heatmap data.
            macro_result: Macro scan results.
            discovery_context: Pre-built discovery context for analysts.
            task_id: Optional task ID for progress tracking.

        Returns:
            Updated analyst_reports dict (may include additional symbols).
        """
        for iteration in range(1, CoverageEvaluation.MAX_ITERATIONS + 1):
            logger.info(f"Coverage evaluation iteration {iteration}...")

            evaluation = await self._run_coverage_evaluation(
                analyst_reports, heatmap_data, macro_result, iteration
            )

            logger.info(
                f"Coverage evaluation: sufficient={evaluation.is_sufficient}, "
                f"gaps={len(evaluation.gaps)}, "
                f"additional_recommended={len(evaluation.additional_stocks_recommended)}"
            )

            if evaluation.is_sufficient:
                logger.info("Coverage is sufficient, proceeding to synthesis")
                break

            if not evaluation.can_iterate:
                logger.info("Max coverage iterations reached, proceeding to synthesis")
                break

            # Run additional deep dives for recommended stocks
            additional_symbols = [
                s.symbol for s in evaluation.additional_stocks_recommended
                if s.symbol not in analyst_reports
            ]

            if not additional_symbols:
                logger.info("No new symbols to analyze, proceeding to synthesis")
                break

            logger.info(f"Running additional deep dives for: {additional_symbols}")
            await self._update_task_progress(
                task_id, "coverage_evaluation", 78,
                f"Analyzing {len(additional_symbols)} additional stocks (iteration {iteration})..."
            )

            async def _analyze_additional(sym: str) -> tuple[str, dict[str, Any]]:
                reports = await self._run_analysts_for_symbol(sym, discovery_context)
                return sym, reports

            coverage_results = await asyncio.gather(
                *[_analyze_additional(sym) for sym in additional_symbols],
                return_exceptions=True,
            )

            for r in coverage_results:
                if isinstance(r, BaseException):
                    logger.error(f"Additional deep dive failed: {r}")
                else:
                    sym, sym_reports = r
                    analyst_reports[sym] = sym_reports

        return analyst_reports

    def _build_heatmap_discovery_context(
        self,
        macro_result: MacroScanResult,
        heatmap_analysis: HeatmapAnalysis,
    ) -> str:
        """Build discovery context for deep dive analysts using heatmap data.

        Args:
            macro_result: Results from macro scan.
            heatmap_analysis: Results from heatmap analysis.

        Returns:
            Formatted discovery context string.
        """
        lines = [
            "## AUTONOMOUS DISCOVERY CONTEXT (Heatmap-Driven)",
            "",
            f"### Market Regime: {macro_result.market_regime}",
            f"Regime Confidence: {macro_result.regime_confidence:.0%}",
            "",
            "### Key Macro Themes:",
        ]

        for theme in macro_result.themes[:3]:
            lines.append(f"- {theme.name} ({theme.direction}): {theme.rationale[:100]}...")

        lines.extend([
            "",
            "### Heatmap Analysis Overview:",
            heatmap_analysis.overview,
            "",
            "### Identified Patterns:",
        ])

        for pattern in heatmap_analysis.patterns[:5]:
            lines.append(f"- {pattern.description}")
            if pattern.implication:
                lines.append(f"  Implication: {pattern.implication}")

        lines.extend([
            "",
            f"### Sectors to Watch: {', '.join(heatmap_analysis.sectors_to_watch)}",
            f"### Analysis Confidence: {heatmap_analysis.confidence:.0%}",
        ])

        return "\n".join(lines)

    async def _run_synthesis_with_heatmap(
        self,
        analyst_reports: dict[str, dict[str, Any]],
        macro_context: MacroScanResult,
        heatmap_analysis: HeatmapAnalysis,
        max_insights: int,
        portfolio_holdings: dict[str, dict[str, float]] | None = None,
    ) -> list[dict[str, Any]]:
        """Run Phase 5: Synthesis Lead with heatmap context.

        Args:
            analyst_reports: Reports from all analysts per symbol.
            macro_context: Macro scan results.
            heatmap_analysis: Heatmap analysis results.
            max_insights: Maximum insights to generate.
            portfolio_holdings: Optional dict of user portfolio holdings.

        Returns:
            List of insight dictionaries.
        """
        # Build enhanced synthesis context
        async with async_session_factory() as session:
            memory_service = InstitutionalMemoryService(session)

            # Get patterns and track record
            symbols = list(analyst_reports.keys())[:10]
            patterns = await memory_service.get_relevant_patterns(
                symbols=symbols,
                current_conditions={},
            )
            track_record = await memory_service.get_insight_track_record()

        pattern_context_str = build_pattern_context(patterns)
        track_record_str = build_track_record_context(track_record)

        # Build enhanced synthesis prompt
        enhanced_prompt = format_synthesis_prompt_with_context(
            pattern_context=pattern_context_str,
            track_record_context=track_record_str,
        )

        # Build heatmap-enriched autonomous context
        autonomous_context = self._build_heatmap_autonomous_synthesis_context(
            analyst_reports,
            macro_context,
            heatmap_analysis,
            max_insights,
        )

        # Add portfolio context if holdings exist
        portfolio_context = self._build_portfolio_synthesis_context(
            portfolio_holdings or {}
        )

        # Format analyst reports for synthesis
        synthesis_context = format_synthesis_context(
            self._flatten_analyst_reports(analyst_reports)
        )

        full_context = f"{autonomous_context}{portfolio_context}\n\n{synthesis_context}"

        # Query LLM
        response = await self._query_llm(enhanced_prompt, full_context, "synthesis", "synthesis")

        return parse_synthesis_response(response)

    def _build_heatmap_autonomous_synthesis_context(
        self,
        analyst_reports: dict[str, dict[str, Any]],
        macro_context: MacroScanResult,
        heatmap_analysis: HeatmapAnalysis,
        max_insights: int,
    ) -> str:
        """Build autonomous synthesis context with heatmap data.

        Args:
            analyst_reports: Per-symbol analyst reports.
            macro_context: Macro scan results.
            heatmap_analysis: Heatmap analysis results.
            max_insights: Target number of insights.

        Returns:
            Formatted autonomous context string.
        """
        lines = [
            "## AUTONOMOUS DISCOVERY CONTEXT (Heatmap-Driven)",
            "",
            f"### Market Regime: {macro_context.market_regime}",
            f"Regime Confidence: {macro_context.regime_confidence:.0%}",
            "",
            "### Key Macro Themes:",
        ]

        for theme in macro_context.themes[:3]:
            lines.append(f"- {theme.name} ({theme.direction}): {theme.rationale[:100]}...")

        lines.extend([
            "",
            "### Heatmap Analysis:",
            f"Overview: {heatmap_analysis.overview}",
            f"Confidence: {heatmap_analysis.confidence:.0%}",
            "",
            "### Identified Patterns:",
        ])

        for pattern in heatmap_analysis.patterns[:5]:
            lines.append(f"- {pattern.description}")
            if pattern.sectors:
                lines.append(f"  Sectors: {', '.join(pattern.sectors)}")

        lines.extend([
            "",
            f"### Sectors to Watch: {', '.join(heatmap_analysis.sectors_to_watch)}",
            "",
            "### Stock Selection Rationale:",
        ])

        for stock in heatmap_analysis.selected_stocks[:10]:
            lines.append(
                f"- {stock.symbol} ({stock.sector}): {stock.reason[:100]}... "
                f"[{stock.opportunity_type}, {stock.priority}]"
            )

        lines.extend([
            "",
            f"Symbols Analyzed: {', '.join(analyst_reports.keys())}",
            "",
            f"### Target: Generate {max_insights} actionable insights",
            "Prioritize opportunities with:",
            "- Strong macro/heatmap alignment",
            "- Pattern confirmation from deep dive",
            "- Multiple analyst agreement",
            "- Clear risk/reward profiles",
        ])

        return "\n".join(lines)

    def _extract_ta_for_symbol(self, symbol: str, context: dict) -> dict | None:
        """Extract technical analysis data for a symbol from pre-built context."""
        rich_ta = context.get("rich_technical", {})
        if not rich_ta or symbol not in rich_ta:
            return None
        ta = rich_ta[symbol]
        # Return the signal_summary which has composite_score, rating, confidence, breakdown, key_levels
        summary = ta.get("signal_summary")
        if summary:
            return {
                "composite_score": summary.get("composite_score"),
                "rating": summary.get("rating"),
                "confidence": summary.get("confidence"),
                "breakdown": summary.get("breakdown"),
                "key_levels": summary.get("key_levels"),
                "signals": summary.get("signals", []),
            }
        return None

    async def _store_insights_from_heatmap(
        self,
        session: Any,
        insights_data: list[dict[str, Any]],
        macro_result: MacroScanResult,
        heatmap_analysis: HeatmapAnalysis,
        pre_context: dict[str, Any] | None = None,
    ) -> list[DeepInsight]:
        """Store insights in database with heatmap metadata.

        Args:
            session: Database session.
            insights_data: List of insight dictionaries.
            macro_result: Macro scan results for context.
            heatmap_analysis: Heatmap analysis for context.
            pre_context: Pre-built market context with rich_technical data.

        Returns:
            List of created DeepInsight objects.
        """
        stored: list[DeepInsight] = []

        # Build a lookup for opportunity types from heatmap selections
        heatmap_opp_types: dict[str, str] = {
            s.symbol: s.opportunity_type
            for s in heatmap_analysis.selected_stocks
        }

        for data in insights_data:
            try:
                # Validate insight_type
                insight_type = data.get("insight_type", "opportunity").lower()
                if insight_type not in VALID_INSIGHT_TYPES:
                    insight_type = "opportunity"

                # Validate action
                action = data.get("action", "HOLD").upper()
                if action not in VALID_ACTIONS:
                    action = "HOLD"

                # Get opportunity type from heatmap selections
                primary_symbol = data.get("primary_symbol")
                opportunity_type = heatmap_opp_types.get(
                    primary_symbol, "unknown"
                ) if primary_symbol else "unknown"

                # Build data sources list with discovery metadata
                data_sources = data.get("data_sources", [])
                data_sources.extend([
                    f"macro_regime:{macro_result.market_regime}",
                    f"opportunity_type:{opportunity_type}",
                    "analysis_type:autonomous_heatmap_discovery",
                ])

                insight = DeepInsight(
                    insight_type=insight_type,
                    action=action,
                    title=data.get("title", "Untitled")[:200],
                    thesis=data.get("thesis", ""),
                    primary_symbol=primary_symbol,
                    related_symbols=data.get("related_symbols", []),
                    supporting_evidence=data.get("supporting_evidence", []),
                    confidence=float(data.get("confidence", 0.5)),
                    time_horizon=data.get("time_horizon", "medium_term"),
                    risk_factors=data.get("risk_factors", []),
                    invalidation_trigger=data.get("invalidation_trigger"),
                    historical_precedent=data.get("historical_precedent"),
                    analysts_involved=data.get("analysts_involved", []),
                    data_sources=data_sources,
                    prediction_market_data=getattr(self, '_prediction_data', None) or None,
                    sentiment_data=getattr(self, '_sentiment_data', None) or None,
                    technical_analysis_data=self._extract_ta_for_symbol(primary_symbol, pre_context) if pre_context and primary_symbol else None,
                )

                session.add(insight)
                stored.append(insight)

            except Exception as e:
                logger.error(f"Failed to create insight: {e}")
                continue

        if stored:
            await session.commit()
            logger.info(f"Stored {len(stored)} insights to database")

            # Extract patterns from each stored insight (in parallel)
            try:
                pattern_extractor = PatternExtractor(session)

                async def _extract_pattern(insight: DeepInsight) -> None:
                    try:
                        insight_dict = {
                            "id": insight.id,
                            "title": insight.title,
                            "insight_type": insight.insight_type,
                            "action": insight.action,
                            "thesis": insight.thesis,
                            "confidence": insight.confidence,
                            "time_horizon": insight.time_horizon,
                            "primary_symbol": insight.primary_symbol,
                            "risk_factors": insight.risk_factors or [],
                            "related_symbols": insight.related_symbols or [],
                            "sector": (insight.discovery_context or {}).get("sector"),
                        }
                        await pattern_extractor.extract_from_insight(insight_dict)
                        logger.info(f"[AUTO] Pattern extraction completed for {insight.primary_symbol}")
                    except Exception as pe:
                        logger.error(f"[AUTO] Pattern extraction failed for {insight.primary_symbol}: {pe}", exc_info=True)

                await asyncio.gather(
                    *[_extract_pattern(ins) for ins in stored],
                    return_exceptions=True,
                )
                await session.commit()
            except Exception as e:
                logger.error(f"[AUTO] Pattern extraction phase failed: {e}", exc_info=True)

            # Auto-initiate outcome tracking for actionable insights
            try:
                actionable_actions = {"STRONG_BUY", "BUY", "SELL", "STRONG_SELL"}
                action_to_direction = {
                    "STRONG_BUY": "bullish",
                    "BUY": "bullish",
                    "SELL": "bearish",
                    "STRONG_SELL": "bearish",
                }
                outcome_tracker = InsightOutcomeTracker(session)
                tracked_count = 0
                for insight in stored:
                    try:
                        if not insight.primary_symbol:
                            continue
                        if insight.action not in actionable_actions:
                            continue
                        predicted_direction = action_to_direction[insight.action]
                        await outcome_tracker.start_tracking(
                            insight_id=insight.id,
                            symbol=insight.primary_symbol,
                            predicted_direction=predicted_direction,
                            tracking_days=20,
                        )
                        tracked_count += 1
                        logger.info(
                            f"[AUTO] Outcome tracking started for {insight.primary_symbol} "
                            f"(action={insight.action}, direction={predicted_direction})"
                        )
                    except Exception as te:
                        logger.warning(
                            f"[AUTO] Outcome tracking failed for {insight.primary_symbol}: {te}"
                        )
                if tracked_count > 0:
                    logger.info(f"[AUTO] Started outcome tracking for {tracked_count}/{len(stored)} heatmap insights")
            except Exception as e:
                logger.warning(f"[AUTO] Outcome tracking phase failed: {e}")

            # Compute statistical features for discovered symbols
            try:
                from analysis.statistical_calculator import StatisticalFeatureCalculator  # type: ignore[import-not-found]

                symbols = list({ins.primary_symbol for ins in stored if ins.primary_symbol})
                if symbols:
                    calculator = StatisticalFeatureCalculator(session)
                    await calculator.compute_all_features(symbols)
                    await session.commit()
                    logger.info(f"[AUTO] Statistical features computed for {len(symbols)} heatmap symbols")
            except Exception as e:
                logger.warning(f"[AUTO] Statistical feature computation failed: {e}")

        return stored

    def _build_heatmap_discovery_summary(
        self,
        macro_result: MacroScanResult,
        heatmap_analysis: HeatmapAnalysis,
        heatmap_data: HeatmapData,
    ) -> str:
        """Build human-readable summary of the heatmap-driven discovery.

        Args:
            macro_result: Macro scan results.
            heatmap_analysis: Heatmap analysis results.
            heatmap_data: Raw heatmap data.

        Returns:
            Formatted summary string.
        """
        lines = [
            "## How These Opportunities Were Discovered\n",
            f"**Market Regime:** {macro_result.market_regime}",
            "\n**Key Macro Themes:**",
        ]

        for theme in macro_result.themes[:3]:
            lines.append(f"- {theme.name}: {theme.rationale[:100]}...")

        lines.append(f"\n**Heatmap Analysis:** {heatmap_analysis.overview}")

        lines.append("\n**Sectors Scanned:**")
        for sector in heatmap_data.sectors:
            lines.append(
                f"- {sector.name}: {sector.change_1d:+.1f}% (1D), "
                f"breadth {sector.breadth:.0%}"
            )

        lines.append(f"\n**Stocks in Universe:** {len(heatmap_data.stocks)}")
        lines.append(f"**Stocks Selected for Deep Dive:** {len(heatmap_analysis.selected_stocks)}")

        if heatmap_analysis.patterns:
            lines.append("\n**Key Patterns Identified:**")
            for pattern in heatmap_analysis.patterns[:3]:
                lines.append(f"- {pattern.description}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Legacy pipeline fallback
    # ------------------------------------------------------------------

    async def _run_legacy_pipeline(
        self,
        result: AutonomousAnalysisResult,
        macro_result: MacroScanResult,
        deep_dive_count: int,
        max_insights: int,
        task_id: str | None,
    ) -> AutonomousAnalysisResult:
        """Run the legacy sector rotation + opportunity hunt pipeline.

        Used as fallback when heatmap fetch fails.

        Args:
            result: The in-progress result to populate.
            macro_result: Macro scan results from Phase 1.
            deep_dive_count: Number of opportunities to deep dive.
            max_insights: Max insights to generate.
            task_id: Optional task ID for progress tracking.

        Returns:
            Completed AutonomousAnalysisResult.
        """
        logger.info("Running legacy pipeline (sector rotation + opportunity hunt)...")

        try:
            # ===== Load portfolio holdings (non-blocking) =====
            portfolio_holdings = await self._get_portfolio_holdings()

            # ===== LEGACY PHASE 2: Sector Rotation =====
            logger.info("Legacy Phase 2: Analyzing sector rotation...")
            await self._update_task_progress(task_id, "sector_rotation", 25, "Analyzing sector rotation...")
            if self._run_metrics:
                self._run_metrics.start_phase("sector_rotation")
            sector_result = await self._run_sector_rotation(macro_result)
            result.sector_result = sector_result
            result.phases_completed.append("sector_rotation")
            if self._run_metrics:
                self._run_metrics.end_phase("sector_rotation")

            # Capture sector rotation summary
            top_sector_names = [s.sector_name for s in sector_result.top_sectors[:3]]
            avoid_names = [s.sector_name for s in sector_result.sectors_to_avoid[:2]]
            sr_parts = [
                f"Top sectors: {', '.join(top_sector_names) if top_sector_names else 'none identified'}.",
            ]
            if avoid_names:
                sr_parts.append(f"Avoid: {', '.join(avoid_names)}.")
            if sector_result.rotation_active:
                sr_parts.append(
                    f"Rotation active ({sector_result.rotation_stage}): "
                    f"{', '.join(sector_result.rotation_from[:2])} -> "
                    f"{', '.join(sector_result.rotation_to[:2])}."
                )
            result.phase_summaries["sector_rotation"] = " ".join(sr_parts)

            # ===== LEGACY PHASE 3: Opportunity Hunt =====
            logger.info("Legacy Phase 3: Hunting for opportunities...")
            await self._update_task_progress(task_id, "opportunity_hunt", 45, "Discovering opportunities...")
            if self._run_metrics:
                self._run_metrics.start_phase("opportunity_hunt")
            candidates = await self._run_opportunity_hunt(macro_result, sector_result)
            result.candidates = candidates
            result.phases_completed.append("opportunity_hunt")
            if self._run_metrics:
                self._run_metrics.end_phase("opportunity_hunt")

            # Capture opportunity hunt summary
            candidate_symbols = [c.symbol for c in candidates.candidates[:5]]
            oh_parts = [
                f"Screened {candidates.total_screened} stocks, found {len(candidates.candidates)} candidates "
                f"({candidates.confidence:.0%} confidence).",
            ]
            if candidate_symbols:
                oh_parts.append(f"Top picks: {', '.join(candidate_symbols)}.")
            result.phase_summaries["opportunity_hunt"] = " ".join(oh_parts)

            # ===== LEGACY PHASE 4: Deep Dive =====
            top_candidates = candidates.get_top_candidates(deep_dive_count)
            symbols_to_analyze = [c.symbol for c in top_candidates]

            # Merge portfolio holdings into deep dive list (max 10 extra)
            if portfolio_holdings:
                existing_symbols = set(symbols_to_analyze)
                portfolio_additions = [
                    sym for sym in portfolio_holdings
                    if sym not in existing_symbols
                ][:10]
                if portfolio_additions:
                    symbols_to_analyze.extend(portfolio_additions)
                    logger.info(
                        f"[Legacy] Added {len(portfolio_additions)} portfolio-held "
                        f"symbols to deep dive: {portfolio_additions}"
                    )

            logger.info(f"Legacy Phase 4: Deep diving into {symbols_to_analyze}...")
            await self._update_task_progress(
                task_id, "deep_dive", 55,
                f"Analyzing {len(symbols_to_analyze)} candidates..."
            )
            if self._run_metrics:
                self._run_metrics.start_phase("deep_dive")

            discovery_context = await self._build_discovery_context(
                macro_result, sector_result
            )

            analyst_reports: dict[str, dict[str, Any]] = {}

            async def _analyze_one(sym: str) -> tuple[str, dict[str, Any] | None]:
                try:
                    reports = await self._run_analysts_for_symbol(sym, discovery_context)
                    return sym, reports
                except Exception as e:
                    logger.error(f"Deep dive failed for {sym}: {e}")
                    result.errors.append(f"Deep dive {sym}: {str(e)}")
                    return sym, None

            gather_results = await asyncio.gather(
                *[_analyze_one(sym) for sym in symbols_to_analyze],
                return_exceptions=True,
            )
            for r in gather_results:
                if isinstance(r, BaseException):
                    logger.error(f"Deep dive failed: {r}")
                    result.errors.append(f"Deep dive: {str(r)}")
                elif r[1] is not None:
                    analyst_reports[r[0]] = r[1]

            result.analyst_reports = analyst_reports
            result.phases_completed.append("deep_dive")
            if self._run_metrics:
                self._run_metrics.end_phase("deep_dive")
            await self._update_task_progress(task_id, "deep_dive", 70, "Deep analysis complete")

            # Capture legacy deep dive summary
            legacy_successful = list(analyst_reports.keys())
            legacy_failed = len(symbols_to_analyze) - len(legacy_successful)
            ldd_parts = [
                f"Analyzed {len(legacy_successful)} stocks successfully"
                f"{f' ({legacy_failed} failed)' if legacy_failed else ''}.",
                f"Symbols: {', '.join(legacy_successful[:8])}"
                f"{'...' if len(legacy_successful) > 8 else ''}.",
            ]
            result.phase_summaries["deep_dive"] = " ".join(ldd_parts)

            # ===== LEGACY PHASE 5: Synthesis =====
            logger.info("Legacy Phase 5: Synthesizing insights...")
            await self._update_task_progress(task_id, "synthesis", 85, "Synthesizing insights...")
            if self._run_metrics:
                self._run_metrics.start_phase("synthesis")
            insights_data = await self._run_synthesis(
                analyst_reports=analyst_reports,
                macro_context=macro_result,
                sector_context=sector_result,
                candidates=candidates,
                max_insights=max_insights,
                portfolio_holdings=portfolio_holdings,
            )
            result.phases_completed.append("synthesis")
            if self._run_metrics:
                self._run_metrics.end_phase("synthesis")

            async with async_session_factory() as session:
                saved_insights = await self._store_insights(
                    session, insights_data, macro_result, sector_result, candidates
                )
                result.insights = saved_insights

            # Capture legacy synthesis summary
            l_actions = [i.get("action", "HOLD") for i in insights_data]
            l_avg_conf = (
                sum(float(i.get("confidence", 0)) for i in insights_data) / len(insights_data)
                if insights_data else 0
            )
            l_titles = [i.get("title", "")[:40] for i in insights_data[:3]]
            ls_parts = [
                f"Generated {len(insights_data)} insights (avg confidence: {l_avg_conf:.0%}).",
            ]
            if l_actions:
                from collections import Counter
                l_action_counts = Counter(l_actions)
                l_action_str = ", ".join(
                    f"{cnt} {act}" for act, cnt in l_action_counts.most_common(3)
                )
                ls_parts.append(f"Actions: {l_action_str}.")
            if l_titles:
                ls_parts.append(f"Top: {'; '.join(l_titles)}.")
            result.phase_summaries["synthesis"] = " ".join(ls_parts)

            result.discovery_summary = self._build_discovery_summary(
                macro_result, sector_result, candidates
            )

        except Exception as e:
            logger.error(f"Legacy pipeline failed: {e}")
            result.errors.append(str(e))

        result.elapsed_seconds = (datetime.utcnow() - datetime.utcnow()).total_seconds()
        self._last_analysis_time = datetime.utcnow()

        return result

    # ------------------------------------------------------------------
    # Shared and unchanged methods
    # ------------------------------------------------------------------

    async def _update_task_progress(
        self,
        task_id: str | None,
        status: str,
        progress: int,
        phase_details: str,
    ) -> None:
        """Update task progress in database.

        Args:
            task_id: The task ID to update, or None to skip.
            status: Current phase status.
            progress: Progress percentage (0-100).
            phase_details: Human-readable phase description.
        """
        if not task_id:
            return

        try:
            from models.analysis_task import AnalysisTask  # type: ignore[import-not-found]

            async with async_session_factory() as session:
                from sqlalchemy import select  # type: ignore[import-not-found]

                db_result = await session.execute(
                    select(AnalysisTask).where(AnalysisTask.id == task_id)
                )
                task = db_result.scalar_one_or_none()

                if task:
                    task.status = status
                    task.progress = progress
                    task.current_phase = status
                    task.phase_details = phase_details
                    await session.commit()
                    logger.debug(f"Task {task_id} progress: {progress}% - {phase_details}")

        except Exception as e:
            logger.warning(f"Failed to update task progress: {e}")

    async def _run_macro_scan(self) -> MacroScanResult:
        """Run Phase 1: Macro Scanner.

        The MacroScanner has its own _query_llm that calls pool_query_llm
        directly. We wrap the call with activity recording so the LLM
        activity feed shows the macro scan phase.

        Returns:
            MacroScanResult with market regime and themes.
        """
        entry_idx = self._record_activity_start(
            "macro_scanner", "Scanning global macro environment...", "macro_scan"
        )
        start_time = datetime.utcnow()

        try:
            scan_result = await self.macro_scanner.scan()
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            # Read token metadata from the scanner's last LLM result
            llm_result = getattr(self.macro_scanner, "last_llm_result", None)
            if llm_result is not None:
                self._record_activity_end(entry_idx, llm_result, duration_ms)
                if self._run_metrics is not None:
                    self._run_metrics.record_llm_call(llm_result)
            else:
                # No LLM result metadata available; mark entry as done with timing only
                if entry_idx < len(self._activity_log):
                    entry = self._activity_log[entry_idx]
                    regime = getattr(scan_result, "market_regime", "")
                    entry.response_preview = f"Macro scan complete. Regime: {regime}"
                    entry.duration_ms = duration_ms
                    entry.status = "done"

            return scan_result
        except Exception:
            self._record_activity_error(entry_idx)
            raise

    # DEPRECATED — used by legacy fallback pipeline only
    async def _run_sector_rotation(
        self,
        macro_result: MacroScanResult,
    ) -> SectorRotationResult:
        """Run legacy Phase 2: Sector Rotation analysis.

        Args:
            macro_result: Results from macro scan.

        Returns:
            SectorRotationResult with sector recommendations.
        """
        # Build sector data context
        sector_data = await self.context_builder._fetch_sector_data()

        # Build macro context dict for sector rotator
        macro_context_dict: dict[str, Any] = {
            "regime": {
                "growth": macro_result.market_regime,
                "inflation": "moderate",  # Derived from themes
                "fed_stance": macro_result.actionable_implications.risk_posture,
            },
            "fed_outlook": "",
            "market_implications": [
                {
                    "asset_class": theme.name,
                    "bias": theme.direction,
                    "rationale": theme.rationale[:100],
                }
                for theme in macro_result.themes[:3]
            ],
        }

        # Check themes for inflation signal
        for theme in macro_result.themes:
            if "inflation" in theme.name.lower():
                macro_context_dict["regime"]["inflation"] = theme.direction

        # Format context for LLM
        formatted_context = format_sector_rotator_context(
            {"sector_performance": sector_data},
            macro_context_dict,
        )

        # Query LLM
        response = await self._query_llm(
            SECTOR_ROTATOR_PROMPT,
            formatted_context,
            "sector_rotator",
            "sector_rotation",
        )

        return parse_sector_rotator_response(response)

    # DEPRECATED — used by legacy fallback pipeline only
    async def _run_opportunity_hunt(
        self,
        macro_result: MacroScanResult,
        sector_result: SectorRotationResult,
    ) -> OpportunityList:
        """Run legacy Phase 3: Opportunity Hunter.

        Args:
            macro_result: Results from macro scan.
            sector_result: Results from sector rotation analysis.

        Returns:
            OpportunityList with candidate opportunities.
        """
        # Get all stocks in screening universe (dynamic)
        try:
            from analysis.agents.universe_builder import get_screening_universe  # type: ignore[import-not-found]
            universe = await get_screening_universe()
            all_stocks: list[str] = []
            for symbols in universe.values():
                all_stocks.extend(symbols)
            all_stocks = list(set(all_stocks))
        except Exception:
            all_stocks = get_all_screening_stocks()

        # Fetch stock data for screening
        screened_candidates = await self._screen_stocks(all_stocks)

        # Build macro context dict
        macro_context_dict: dict[str, Any] = {
            "regime": {
                "growth": macro_result.market_regime,
                "inflation": "moderate",
                "fed_stance": macro_result.actionable_implications.risk_posture,
            },
            "risk_factors": [r.description for r in macro_result.key_risks[:3]],
            "market_implications": [
                {
                    "asset_class": theme.name,
                    "bias": theme.direction,
                    "rationale": theme.rationale[:100],
                }
                for theme in macro_result.themes[:3]
            ],
        }

        # Build sector context dict
        sector_context_dict = sector_result.to_dict()

        # Format context for LLM
        formatted_context = format_opportunity_context(
            macro_context_dict,
            sector_context_dict,
            screened_candidates,
        )

        # Query LLM
        response = await self._query_llm(
            OPPORTUNITY_HUNTER_PROMPT,
            formatted_context,
            "opportunity_hunter",
            "opportunity_hunt",
        )

        return parse_opportunity_response(response)

    async def _screen_stocks(
        self,
        symbols: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Screen stocks and return candidates with data.

        Uses asyncio.gather with run_in_executor to fetch yfinance data
        concurrently instead of blocking the event loop sequentially.

        If *symbols* is None or empty, the dynamic screening universe from
        ``universe_builder`` is used. Falls back to the synchronous
        hardcoded list from ``opportunity_hunter`` on failure.

        Args:
            symbols: List of stock symbols to screen. If None, uses
                the dynamic universe.

        Returns:
            List of screened candidate dictionaries.
        """
        # Resolve symbols from the dynamic universe when none provided
        resolved_symbols: list[str] = symbols or []
        if not resolved_symbols:
            try:
                from analysis.agents.universe_builder import get_screening_universe  # type: ignore[import-not-found]
                universe = await get_screening_universe()
                all_syms: list[str] = []
                for syms in universe.values():
                    all_syms.extend(syms)
                resolved_symbols = list(set(all_syms))
            except Exception:
                from analysis.agents.opportunity_hunter import get_all_screening_stocks_sync  # type: ignore[import-not-found]
                resolved_symbols = get_all_screening_stocks_sync()

        import yfinance as yf  # type: ignore[import-not-found]

        loop = asyncio.get_event_loop()
        yf_semaphore = asyncio.Semaphore(20)

        async def _screen_one(symbol: str) -> dict[str, Any] | None:
            async with yf_semaphore:
                try:
                    ticker = yf.Ticker(symbol)
                    hist = await loop.run_in_executor(
                        None, lambda t=ticker: t.history(period="1mo")
                    )

                    if hist.empty or len(hist) < 5:
                        return None

                    current = hist["Close"].iloc[-1]
                    return_5d = ((current / hist["Close"].iloc[-5]) - 1) * 100
                    return_20d = ((current / hist["Close"].iloc[0]) - 1) * 100
                    avg_volume = hist["Volume"].mean()
                    current_volume = hist["Volume"].iloc[-1]

                    data = {
                        "symbol": symbol,
                        "sector": SYMBOL_TO_SECTOR.get(symbol, "Unknown"),
                        "price": current,
                        "return_5d": return_5d,
                        "return_20d": return_20d,
                        "avg_volume": avg_volume,
                        "volume_ratio": current_volume / avg_volume if avg_volume > 0 else 1.0,
                    }

                    # Apply technical screen
                    if passes_technical_screen(data):
                        data["screen_score"] = calculate_screen_score(data)
                        return data

                    return None
                except Exception as e:
                    logger.warning(f"Failed to screen {symbol}: {e}")
                    return None

        results = await asyncio.gather(
            *[_screen_one(sym) for sym in resolved_symbols],
            return_exceptions=True,
        )

        # Filter out None values and exceptions
        candidates: list[dict[str, Any]] = [
            r for r in results
            if isinstance(r, dict)
        ]

        # Sort by screen score
        candidates.sort(key=lambda x: x.get("screen_score", 0), reverse=True)
        return candidates[:50]  # Return top 50

    async def _build_discovery_context(
        self,
        macro_result: MacroScanResult,
        sector_result: SectorRotationResult,
    ) -> str:
        """Build discovery context for deep dive analysts (legacy pipeline).

        Args:
            macro_result: Results from macro scan.
            sector_result: Results from sector rotation.

        Returns:
            Formatted discovery context string.
        """
        return await self.context_builder.build_discovery_context(
            macro_result.to_dict(),
            sector_result.to_dict(),
        )

    async def _run_analysts_for_symbol(
        self,
        symbol: str,
        discovery_context: str,
        pre_built_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run all analysts for a single symbol.

        Args:
            symbol: Stock symbol to analyze.
            discovery_context: Pre-built discovery context.
            pre_built_context: Optional pre-built market context covering all
                symbols. When provided, skips the per-symbol build_context()
                call, saving redundant data fetches.

        Returns:
            Dictionary mapping analyst names to their reports.
        """
        # Use pre-built context if available, otherwise build per-symbol
        if pre_built_context is not None:
            agent_context = pre_built_context
        else:
            agent_context = await self.context_builder.build_context(
                symbols=[symbol],
                include_price_history=True,
                include_technical=True,
                include_economic=True,
                include_sectors=True,
                include_rich_technical=True,
                include_fundamentals=True,
            )

        reports: dict[str, Any] = {}

        # Run analysts in parallel
        tasks = []
        analyst_names = []

        for analyst_name, config in self.ANALYSTS.items():
            task = self._run_single_analyst(
                analyst_name,
                config,
                agent_context,
                discovery_context,
                symbol,
            )
            tasks.append(task)
            analyst_names.append(analyst_name)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for analyst_name, analyst_result in zip(analyst_names, results):
            if isinstance(analyst_result, Exception):
                logger.warning(f"{analyst_name} failed for {symbol}: {analyst_result}")
                reports[analyst_name] = {"error": str(analyst_result)}
            else:
                reports[analyst_name] = analyst_result

        return reports

    async def _run_single_analyst(
        self,
        analyst_name: str,
        config: dict[str, Any],
        agent_context: dict[str, Any],
        discovery_context: str,
        symbol: str,
    ) -> dict[str, Any]:
        """Run a single analyst agent.

        Args:
            analyst_name: Name of the analyst.
            config: Analyst configuration.
            agent_context: Symbol-specific context.
            discovery_context: Discovery context from phases 1-3.
            symbol: Symbol being analyzed.

        Returns:
            Parsed analyst report.
        """
        prompt = config["prompt"]
        format_func = config["format_context"]
        parse_func = config["parse_response"]

        # Format context for analyst
        formatted_context = format_func(agent_context)

        # Prepend discovery context
        full_context = f"{discovery_context}\n\n{formatted_context}"

        # Build a meaningful preview that distinguishes this entry from other
        # analysts analyzing the same symbol (the discovery context prefix is
        # identical for all analysts and would make entries look like duplicates).
        analyst_preview = f"[{symbol}] {analyst_name}: {formatted_context[:200]}"

        # Query LLM (semaphore limits concurrent LLM calls across all analysts)
        for attempt in range(self.max_retries + 1):
            try:
                async with self._llm_semaphore:
                    response = await self._query_llm(
                        prompt, full_context, analyst_name, "deep_dive",
                        symbol=symbol, prompt_preview=analyst_preview,
                    )
                parsed = parse_func(response)

                if hasattr(parsed, "to_dict"):
                    return parsed.to_dict()
                elif isinstance(parsed, dict):
                    return parsed
                else:
                    return {"raw": str(parsed), "confidence": 0.5}

            except Exception as e:
                logger.warning(
                    f"Analyst {analyst_name} attempt {attempt + 1} failed: {e}"
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(1)

        raise Exception(f"Analyst {analyst_name} failed after {self.max_retries + 1} attempts")

    async def _run_synthesis(
        self,
        analyst_reports: dict[str, dict[str, Any]],
        macro_context: MacroScanResult,
        sector_context: SectorRotationResult,
        candidates: OpportunityList,
        max_insights: int,
        portfolio_holdings: dict[str, dict[str, float]] | None = None,
    ) -> list[dict[str, Any]]:
        """Run Phase 5: Synthesis Lead (legacy pipeline).

        Args:
            analyst_reports: Reports from all analysts per symbol.
            macro_context: Macro scan results.
            sector_context: Sector rotation results.
            candidates: Opportunity candidates.
            max_insights: Maximum insights to generate.
            portfolio_holdings: Optional dict of user portfolio holdings.

        Returns:
            List of insight dictionaries.
        """
        # Build enhanced synthesis context
        async with async_session_factory() as session:
            memory_service = InstitutionalMemoryService(session)

            # Get patterns and track record
            patterns = await memory_service.get_relevant_patterns(
                symbols=[c.symbol for c in candidates.candidates[:10]],
                current_conditions={},
            )
            track_record = await memory_service.get_insight_track_record()

        pattern_context_str = build_pattern_context(patterns)
        track_record_str = build_track_record_context(track_record)

        # Build enhanced synthesis prompt
        enhanced_prompt = format_synthesis_prompt_with_context(
            pattern_context=pattern_context_str,
            track_record_context=track_record_str,
        )

        # Add autonomous context to synthesis
        autonomous_context = self._build_autonomous_synthesis_context(
            analyst_reports,
            macro_context,
            sector_context,
            candidates,
            max_insights,
        )

        # Add portfolio context if holdings exist
        portfolio_context = self._build_portfolio_synthesis_context(
            portfolio_holdings or {}
        )

        # Format analyst reports for synthesis
        synthesis_context = format_synthesis_context(
            self._flatten_analyst_reports(analyst_reports)
        )

        full_context = f"{autonomous_context}{portfolio_context}\n\n{synthesis_context}"

        # Query LLM
        response = await self._query_llm(enhanced_prompt, full_context, "synthesis", "synthesis")

        return parse_synthesis_response(response)

    def _build_autonomous_synthesis_context(
        self,
        analyst_reports: dict[str, dict[str, Any]],
        macro_context: MacroScanResult,
        sector_context: SectorRotationResult,
        candidates: OpportunityList,
        max_insights: int,
    ) -> str:
        """Build additional context for autonomous synthesis (legacy pipeline).

        Args:
            analyst_reports: Per-symbol analyst reports.
            macro_context: Macro scan results.
            sector_context: Sector rotation results.
            candidates: Opportunity candidates.
            max_insights: Target number of insights.

        Returns:
            Formatted autonomous context string.
        """
        lines = [
            "## AUTONOMOUS DISCOVERY CONTEXT",
            "",
            f"### Market Regime: {macro_context.market_regime}",
            f"Regime Confidence: {macro_context.regime_confidence:.0%}",
            "",
            "### Key Macro Themes:",
        ]

        for theme in macro_context.themes[:3]:
            lines.append(f"- {theme.name} ({theme.direction}): {theme.rationale[:100]}...")

        lines.extend([
            "",
            "### Sector Signals:",
            f"Rotation Active: {sector_context.rotation_active}",
        ])

        if sector_context.rotation_active:
            lines.append(
                f"Rotating: {', '.join(sector_context.rotation_from)} -> "
                f"{', '.join(sector_context.rotation_to)}"
            )

        lines.append("\nTop Sectors:")
        for sector in sector_context.top_sectors[:3]:
            lines.append(f"- {sector.sector_name}: {sector.rationale[:80]}...")

        lines.extend([
            "",
            f"### Candidates Screened: {candidates.total_screened}",
            f"Symbols Analyzed: {', '.join(analyst_reports.keys())}",
            "",
            f"### Target: Generate {max_insights} actionable insights",
            "Prioritize opportunities with:",
            "- Strong macro/sector alignment",
            "- Multiple analyst agreement",
            "- Clear risk/reward profiles",
        ])

        return "\n".join(lines)

    def _flatten_analyst_reports(
        self,
        analyst_reports: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Flatten per-symbol analyst reports for synthesis.

        Args:
            analyst_reports: Dict mapping symbols to analyst reports.

        Returns:
            Flattened dict for synthesis context formatting.
        """
        # Aggregate reports by analyst type
        aggregated: dict[str, Any] = {
            "technical": {"findings": [], "confidence": 0.0},
            "macro": {"market_implications": [], "confidence": 0.0},
            "sector": {"sector_rankings": [], "confidence": 0.0},
            "risk": {"risk_assessments": [], "confidence": 0.0},
            "correlation": {"divergences": [], "confidence": 0.0},
        }

        for symbol, reports in analyst_reports.items():
            for analyst_name, report in reports.items():
                if analyst_name not in aggregated:
                    continue
                if "error" in report:
                    continue

                # Merge findings/data
                if analyst_name == "technical":
                    findings = report.get("findings", [])
                    for f in findings:
                        f["_symbol"] = symbol
                    aggregated["technical"]["findings"].extend(findings)
                elif analyst_name == "risk":
                    assessments = report.get("risk_assessments", [])
                    for a in assessments:
                        a["_symbol"] = symbol
                    aggregated["risk"]["risk_assessments"].extend(assessments)

                # Average confidence
                if "confidence" in report:
                    current = aggregated[analyst_name].get("confidence", 0.0)
                    aggregated[analyst_name]["confidence"] = (
                        current + report["confidence"]
                    ) / 2

        return aggregated

    async def _store_insights(
        self,
        session: Any,
        insights_data: list[dict[str, Any]],
        macro_result: MacroScanResult,
        sector_result: SectorRotationResult,
        candidates: OpportunityList,
    ) -> list[DeepInsight]:
        """Store insights in database (legacy pipeline).

        Args:
            session: Database session.
            insights_data: List of insight dictionaries.
            macro_result: Macro scan results for context.
            sector_result: Sector rotation results for context.
            candidates: Opportunity candidates for context.

        Returns:
            List of created DeepInsight objects.
        """
        stored: list[DeepInsight] = []

        for data in insights_data:
            try:
                # Validate insight_type
                insight_type = data.get("insight_type", "opportunity").lower()
                if insight_type not in VALID_INSIGHT_TYPES:
                    insight_type = "opportunity"

                # Validate action
                action = data.get("action", "HOLD").upper()
                if action not in VALID_ACTIONS:
                    action = "HOLD"

                # Get opportunity type for data_sources
                opportunity_type = self._get_opportunity_type(
                    data.get("primary_symbol"), candidates
                )

                # Build data sources list with discovery metadata
                data_sources = data.get("data_sources", [])
                data_sources.extend([
                    f"macro_regime:{macro_result.market_regime}",
                    f"opportunity_type:{opportunity_type}",
                    "analysis_type:autonomous_discovery",
                ])

                insight = DeepInsight(
                    insight_type=insight_type,
                    action=action,
                    title=data.get("title", "Untitled")[:200],
                    thesis=data.get("thesis", ""),
                    primary_symbol=data.get("primary_symbol"),
                    related_symbols=data.get("related_symbols", []),
                    supporting_evidence=data.get("supporting_evidence", []),
                    confidence=float(data.get("confidence", 0.5)),
                    time_horizon=data.get("time_horizon", "medium_term"),
                    risk_factors=data.get("risk_factors", []),
                    invalidation_trigger=data.get("invalidation_trigger"),
                    historical_precedent=data.get("historical_precedent"),
                    analysts_involved=data.get("analysts_involved", []),
                    data_sources=data_sources,
                    prediction_market_data=getattr(self, '_prediction_data', None) or None,
                    sentiment_data=getattr(self, '_sentiment_data', None) or None,
                    technical_analysis_data=None,  # No pre_context in legacy pipeline
                )

                session.add(insight)
                stored.append(insight)

            except Exception as e:
                logger.error(f"Failed to create insight: {e}")
                continue

        if stored:
            await session.commit()
            logger.info(f"Stored {len(stored)} insights to database")

            # Extract patterns from each stored insight (in parallel)
            try:
                pattern_extractor = PatternExtractor(session)

                async def _extract_pattern_legacy(insight: DeepInsight) -> None:
                    try:
                        insight_dict = {
                            "id": insight.id,
                            "title": insight.title,
                            "insight_type": insight.insight_type,
                            "action": insight.action,
                            "thesis": insight.thesis,
                            "confidence": insight.confidence,
                            "time_horizon": insight.time_horizon,
                            "primary_symbol": insight.primary_symbol,
                            "risk_factors": insight.risk_factors or [],
                            "related_symbols": insight.related_symbols or [],
                            "sector": (insight.discovery_context or {}).get("sector"),
                        }
                        await pattern_extractor.extract_from_insight(insight_dict)
                        logger.info(f"[AUTO] Pattern extraction completed for {insight.primary_symbol}")
                    except Exception as pe:
                        logger.error(f"[AUTO] Pattern extraction failed for {insight.primary_symbol}: {pe}", exc_info=True)

                await asyncio.gather(
                    *[_extract_pattern_legacy(ins) for ins in stored],
                    return_exceptions=True,
                )
                await session.commit()
            except Exception as e:
                logger.error(f"[AUTO] Pattern extraction phase failed: {e}", exc_info=True)

            # Auto-initiate outcome tracking for actionable insights
            try:
                actionable_actions = {"STRONG_BUY", "BUY", "SELL", "STRONG_SELL"}
                action_to_direction = {
                    "STRONG_BUY": "bullish",
                    "BUY": "bullish",
                    "SELL": "bearish",
                    "STRONG_SELL": "bearish",
                }
                outcome_tracker = InsightOutcomeTracker(session)
                tracked_count = 0
                for insight in stored:
                    try:
                        if not insight.primary_symbol:
                            continue
                        if insight.action not in actionable_actions:
                            continue
                        predicted_direction = action_to_direction[insight.action]
                        await outcome_tracker.start_tracking(
                            insight_id=insight.id,
                            symbol=insight.primary_symbol,
                            predicted_direction=predicted_direction,
                            tracking_days=20,
                        )
                        tracked_count += 1
                        logger.info(
                            f"[AUTO] Outcome tracking started for {insight.primary_symbol} "
                            f"(action={insight.action}, direction={predicted_direction})"
                        )
                    except Exception as te:
                        logger.warning(
                            f"[AUTO] Outcome tracking failed for {insight.primary_symbol}: {te}"
                        )
                if tracked_count > 0:
                    logger.info(f"[AUTO] Started outcome tracking for {tracked_count}/{len(stored)} legacy insights")
            except Exception as e:
                logger.warning(f"[AUTO] Outcome tracking phase failed: {e}")

            # Compute statistical features for discovered symbols
            try:
                from analysis.statistical_calculator import StatisticalFeatureCalculator  # type: ignore[import-not-found]

                symbols = list({ins.primary_symbol for ins in stored if ins.primary_symbol})
                if symbols:
                    calculator = StatisticalFeatureCalculator(session)
                    await calculator.compute_all_features(symbols)
                    await session.commit()
                    logger.info(f"[AUTO] Statistical features computed for {len(symbols)} legacy symbols")
            except Exception as e:
                logger.warning(f"[AUTO] Statistical feature computation failed: {e}")

        return stored

    def _get_opportunity_type(
        self,
        symbol: str | None,
        candidates: OpportunityList,
    ) -> str:
        """Get opportunity type for a symbol from candidates.

        Args:
            symbol: Stock symbol.
            candidates: OpportunityList with candidates.

        Returns:
            Opportunity type string.
        """
        if not symbol:
            return "unknown"

        for c in candidates.candidates:
            if c.symbol == symbol:
                return c.opportunity_type

        return "unknown"

    def _build_discovery_summary(
        self,
        macro_result: MacroScanResult,
        sector_result: SectorRotationResult,
        candidates: OpportunityList,
    ) -> str:
        """Build human-readable summary of the discovery process (legacy).

        Args:
            macro_result: Macro scan results.
            sector_result: Sector rotation results.
            candidates: Opportunity candidates.

        Returns:
            Formatted summary string.
        """
        lines = [
            "## How These Opportunities Were Discovered\n",
            f"**Market Regime:** {macro_result.market_regime}",
            "\n**Key Macro Themes:**"
        ]

        for theme in macro_result.themes[:3]:
            lines.append(f"- {theme.name}: {theme.rationale[:100]}...")

        lines.append("\n**Sector Focus:**")
        for sector in sector_result.top_sectors:
            lines.append(
                f"- {sector.sector_name} (RS: {sector.relative_strength_20d:+.1f}%)"
            )

        lines.append(f"\n**Candidates Screened:** {candidates.total_screened}")
        lines.append(f"**Opportunities Identified:** {len(candidates.candidates)}")

        return "\n".join(lines)

    def _record_activity_start(
        self,
        agent_name: str,
        user_prompt: str,
        phase: str = "unknown",
        symbol: str = "",
        prompt_preview: str | None = None,
    ) -> int:
        """Record the start of an LLM query. Returns the activity entry index.

        Args:
            agent_name: Name of the agent.
            user_prompt: Full user prompt text.
            phase: Pipeline phase name.
            symbol: Stock symbol (for deep_dive entries).
            prompt_preview: Optional override for the prompt preview text.
                If not provided, uses first 300 chars of user_prompt.
        """
        self._activity_seq += 1
        entry = LLMActivityEntry(
            seq=self._activity_seq,
            timestamp=datetime.now(timezone.utc).isoformat(),
            phase=phase,
            agent_name=agent_name,
            prompt_preview=prompt_preview if prompt_preview is not None else user_prompt[:300],
            response_preview="",
            input_tokens=0,
            output_tokens=0,
            duration_ms=0,
            status="running",
            symbol=symbol,
        )
        self._activity_log.append(entry)
        return len(self._activity_log) - 1

    def _record_activity_end(
        self,
        entry_idx: int,
        result: LLMQueryResult,
        duration_ms: int,
    ) -> None:
        """Update activity log entry with response and metrics."""
        if entry_idx < len(self._activity_log):
            entry = self._activity_log[entry_idx]
            entry.response_preview = result.text[:500]
            entry.input_tokens = result.input_tokens
            entry.output_tokens = result.output_tokens
            entry.duration_ms = duration_ms
            entry.status = "done"

    def _record_activity_error(self, entry_idx: int) -> None:
        """Mark activity log entry as errored."""
        if entry_idx < len(self._activity_log):
            entry = self._activity_log[entry_idx]
            entry.status = "error"

    def get_activity_log(self, since_seq: int = 0, task_id: str | None = None) -> list[dict]:
        """Get all activity log entries for the current run.

        Always returns ALL entries (no cursor-based filtering). With a cap of
        ~150 entries per run, the overhead of returning them all is negligible,
        and this avoids a race condition where the frontend advances its cursor
        past a "running" entry before the entry transitions to "done" with
        populated token counts — causing the "done" version to never be sent.

        Args:
            since_seq: Deprecated / ignored. Kept for API compatibility.
            task_id: If provided, only return entries if this matches the
                current run's task_id. Prevents returning stale entries
                from a previous run.

        Returns:
            List of activity entry dicts, or empty list if task_id
            doesn't match the current run.
        """
        if task_id is not None and self._current_task_id != task_id:
            return []
        return [e.to_dict() for e in self._activity_log]

    def clear_activity_log(self, task_id: str | None = None) -> None:
        """Clear the activity log for a new run.

        Args:
            task_id: The task_id of the new run. Activity entries will
                only be returned for requests matching this task_id.
        """
        self._activity_log = []
        self._activity_seq = 0
        self._current_task_id = task_id

    async def _query_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        agent_name: str = "unknown",
        phase: str = "unknown",
        symbol: str = "",
        prompt_preview: str | None = None,
    ) -> str:
        """Query the LLM using the shared client pool.

        Args:
            system_prompt: System prompt for the agent.
            user_prompt: User prompt with context.
            agent_name: Name of the agent (for logging).
            phase: Phase name for activity tracking.
            symbol: Stock symbol for deep_dive entries.
            prompt_preview: Optional override for the prompt preview shown in
                the activity feed. If not provided, uses the first 300 chars
                of user_prompt.

        Returns:
            LLM response text.
        """
        entry_idx = self._record_activity_start(
            agent_name, user_prompt, phase,
            symbol=symbol, prompt_preview=prompt_preview,
        )
        start_time = datetime.utcnow()

        try:
            result = await pool_query_llm(system_prompt, user_prompt, agent_name)
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            self._record_activity_end(entry_idx, result, duration_ms)

            try:
                if self._run_metrics is not None:
                    self._run_metrics.record_llm_call(result)
            except Exception as metrics_err:
                logger.debug("Metrics recording failed (non-fatal): %s", metrics_err)

            return result.text
        except Exception:
            self._record_activity_error(entry_idx)
            raise

    async def get_more_insights(
        self,
        offset: int = 5,
        limit: int = 5,
    ) -> list[DeepInsight]:
        """Get additional insights from previous analyses.

        Args:
            offset: Number of insights to skip.
            limit: Number of insights to return.

        Returns:
            List of DeepInsight objects.
        """
        from sqlalchemy import select  # type: ignore[import-not-found]

        async with async_session_factory() as session:
            query = (
                select(DeepInsight)
                .order_by(DeepInsight.created_at.desc())
                .offset(offset)
                .limit(limit)
            )

            db_result = await session.execute(query)
            return list(db_result.scalars().all())

    @property
    def last_analysis_time(self) -> datetime | None:
        """Get timestamp of last completed analysis."""
        return self._last_analysis_time


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================


_autonomous_engine_instance: AutonomousDeepEngine | None = None


def get_autonomous_engine() -> AutonomousDeepEngine:
    """Get or create the singleton autonomous engine instance.

    Returns:
        The AutonomousDeepEngine singleton instance.
    """
    global _autonomous_engine_instance
    if _autonomous_engine_instance is None:
        _autonomous_engine_instance = AutonomousDeepEngine()
    return _autonomous_engine_instance


# Convenience alias
autonomous_engine = get_autonomous_engine()
