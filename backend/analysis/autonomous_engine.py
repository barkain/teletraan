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
import inspect
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from database import async_session_factory  # type: ignore[import-not-found]
from models.deep_insight import DeepInsight, InsightType, InsightAction  # type: ignore[import-not-found]
from models.insight_research_context import InsightResearchContext  # type: ignore[import-not-found]

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
from analysis.context_builder import (  # type: ignore[import-not-found]
    MarketContextBuilder,
    format_sentiment_context,
)
from analysis.news_intelligence import (  # type: ignore[import-not-found]
    STATUS_ERROR,
    get_news_intelligence,
    format_news_context,
)
from analysis.symbol_slice import (  # type: ignore[import-not-found]
    partition_by_freshness,
    slice_context_for_symbol,
    target_banner,
)
from analysis.memory_service import InstitutionalMemoryService  # type: ignore[import-not-found]
from analysis.pattern_extractor import PatternExtractor  # type: ignore[import-not-found]
from analysis.outcome_tracker import InsightOutcomeTracker  # type: ignore[import-not-found]
from analysis.confidence_adjuster import ConfidenceAdjuster  # type: ignore[import-not-found]
from llm.client_pool import pool_query_llm, LLMQueryResult  # type: ignore[import-not-found]

# Optional alternative data sources (availability flags)
_HAS_PREDICTIONS = importlib.util.find_spec("data.adapters.prediction_markets") is not None
_HAS_SENTIMENT = importlib.util.find_spec("data.adapters.reddit_sentiment") is not None
_HAS_INVESTOR_FEEDS = importlib.util.find_spec("data.adapters.investor_feeds") is not None

from analysis.agents.thematic_analyst import (  # type: ignore[import-not-found]
    format_thematic_context,
    parse_thematic_response,
    format_thematic_for_downstream,
    ThematicAnalysisResult,
    THEMATIC_ANALYST_PROMPT,
)
from analysis.agents.investor_sentiment import (  # type: ignore[import-not-found]
    format_investor_context,
    parse_investor_response,
    format_investor_for_synthesis,
    InvestorIntelligenceResult,
    INVESTOR_SENTIMENT_PROMPT,
)

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

# Entry-price sanity gate: an insight whose entry midpoint sits further than
# this from the live price is quoting a stale chart rather than a tradable
# level, so it is dropped instead of shown. Measured failure: a STRONG_BUY on
# ARM with entry "$205-215" while ARM traded at $439.46 -- the entry was ARM's
# close from seven weeks earlier.
MAX_ENTRY_DEVIATION_PCT = 15.0

# The factor model needs fundamentals for the whole heatmap universe
# (300-500 names). Cap the wait so a slow yfinance degrades the model to
# market-data-only instead of stalling the pipeline.
FACTOR_FUNDAMENTALS_TIMEOUT_S = 120.0


def _level_text(value: Any, max_len: int) -> str | None:
    """Normalize a trading-level field to a bounded string, or None if absent."""
    if value is None:
        return None
    text = str(value).strip()
    return text[:max_len] if text else None


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

    # Supplementary data for report generation (P1 enhancements)
    factor_scores: dict[str, Any] = field(default_factory=dict)
    correlation_highlights: dict[str, Any] = field(default_factory=dict)
    catalyst_data: list[dict[str, Any]] = field(default_factory=list)
    thematic_analysis: dict[str, Any] = field(default_factory=dict)
    investor_intelligence: dict[str, Any] = field(default_factory=dict)

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
    4. Deep Dive - 3 core analysts (technical, sector, risk) per symbol
    5. Synthesis - Aggregate and rank insights

    Optimized for speed: uses 3 analysts per symbol (macro context is already
    embedded via Phase 1, correlation is covered by sector strategist),
    12 concurrent LLM connections, and fire-and-forget pattern extraction.

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

    # All available analyst configurations
    ALL_ANALYSTS = {
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

    # Core analysts run per symbol during deep dive (3 instead of 5).
    # Macro economist is redundant with Phase 1 macro scan (its context is
    # already prepended to every analyst via discovery_context).
    # Correlation detective provides marginal per-symbol value; sector
    # strategist already captures relative strength and rotation signals.
    ANALYSTS = {
        k: v for k, v in ALL_ANALYSTS.items()
        if k in ("technical", "sector", "risk")
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

        # Throttle the deep-dive analyst fan-out (see _run_deep_dive); the
        # client pool enforces the global concurrency cap independently.
        self._llm_semaphore = asyncio.Semaphore(12)

        self._last_analysis_time: datetime | None = None

        # Thematic and investor intelligence results (populated during Phase 1.5)
        self._thematic_result: ThematicAnalysisResult | None = None
        self._investor_result: InvestorIntelligenceResult | None = None
        self._investor_data: dict = {}

        # Alternative-data prefetch buffers (populated during Phase 1)
        self._sentiment_data: dict | None = None  # Reddit social sentiment
        self._news_data: dict | None = None  # Financial-news sentiment intelligence
        self._macro_news_data: dict | None = None  # Macro-economic news for the regime scan

        # Stock thematic descriptions (populated during Phase 3.5)
        self._stock_descriptions: dict[str, str] = {}
        self._stock_clusters: list[dict[str, Any]] = []
        self._cluster_analyses: list[dict[str, Any]] = []

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

    def _news_sentiment_enabled(self) -> bool:
        """Read the NEWS_SENTIMENT_ENABLED feature flag (defaults to True)."""
        try:
            from config import get_settings  # type: ignore[import-not-found]

            return bool(getattr(get_settings(), "NEWS_SENTIMENT_ENABLED", True))
        except Exception:
            return True

    async def _prefetch_news_data(self, symbols: list[str] | None = None) -> dict:
        """Pre-fetch financial-news sentiment intelligence (best-effort).

        At Phase-1 prefetch time the candidate symbols are not known yet, so we
        only fetch market-level news tone (``get_news_intelligence([], days=3)``).
        The richer per-symbol fetch happens at synthesis once candidates are
        identified (see ``_run_synthesis*``).

        Args:
            symbols: Optional candidate symbols. When empty/None only market tone
                is fetched.

        Returns:
            News-intelligence dict, or empty dict on failure / when disabled.
        """
        if not self._news_sentiment_enabled():
            return {}
        try:
            days = 7 if symbols else 3
            intel = await get_news_intelligence(symbols or [], days=days)
            market = intel.get("market", {}) if isinstance(intel, dict) else {}
            logger.info(
                "Pre-fetched news intelligence: market tone=%s (%s articles), %s symbols",
                market.get("label", "NEUTRAL"),
                market.get("article_count", 0),
                len(intel.get("per_symbol", [])) if isinstance(intel, dict) else 0,
            )
            return intel
        except Exception as e:
            logger.warning(f"Failed to pre-fetch news data (non-fatal): {e}")
            return {}

    def _news_data_for_symbol(self, symbol: str | None) -> dict | None:
        """Build the news_data slice to persist on a DeepInsight row.

        Returns the market tone plus the matching per-symbol entry (when found),
        falling back to the whole news dict. ``None`` when no news was captured.
        """
        news = getattr(self, "_news_data", None)
        if not news:
            return None
        if not symbol:
            return news
        try:
            sym = symbol.upper().strip()
            per_symbol = news.get("per_symbol", []) if isinstance(news, dict) else []
            matched = next(
                (s for s in per_symbol if str(s.get("symbol", "")).upper() == sym),
                None,
            )
            if matched is None:
                return news
            return {
                "as_of": news.get("as_of"),
                "market": news.get("market"),
                "per_symbol": [matched],
                "vacuum": [v for v in news.get("vacuum", []) if str(v).upper() == sym],
            }
        except Exception:
            return news

    def _set_insight_news_data(self, insight: DeepInsight, symbol: str | None) -> None:
        """Defensively attach news_data to an insight (column added by a peer agent).

        Uses ``setattr`` guarded by ``hasattr`` so this is a no-op until the
        ``news_data`` mapped column exists, and never breaks the pipeline.
        """
        try:
            if hasattr(DeepInsight, "news_data"):
                insight.news_data = self._news_data_for_symbol(symbol) or None
        except Exception as e:
            logger.debug("Could not set news_data on insight (non-fatal): %s", e)

    async def _build_news_and_sentiment_context(self, candidate_symbols: list[str]) -> str:
        """Build the synthesis-time news + social-sentiment context block.

        Fetches per-symbol news intelligence for the deep-dive candidates (so the
        synthesis LLM sees headline-level sentiment per name), merges it with the
        Phase-1 market-tone fetch onto ``self._news_data``, and also renders the
        Phase-1 Reddit sentiment that was previously captured but never fed to the
        synthesis LLM. Best-effort: any failure yields an empty section.

        Args:
            candidate_symbols: Deep-dive / opportunity symbols feeding synthesis.

        Returns:
            Markdown block (possibly empty) to append to the synthesis context.
        """
        parts: list[str] = []

        # --- Financial-news sentiment (per-symbol, gated on the feature flag) ---
        if self._news_sentiment_enabled():
            try:
                uniq = list(dict.fromkeys(
                    s.upper().strip() for s in (candidate_symbols or []) if s and s.strip()
                ))
                news_intel = await self._prefetch_news_data(uniq) if uniq else (self._news_data or {})
                if news_intel:
                    # Merge: keep market tone from whichever fetch has it; prefer
                    # the per-symbol fetch (richer) for per_symbol/vacuum slices.
                    merged = dict(self._news_data or {})
                    merged.update(news_intel)
                    if not merged.get("market") and (self._news_data or {}).get("market"):
                        merged["market"] = self._news_data["market"]
                    self._news_data = merged
                    news_block = format_news_context(merged)
                    if news_block:
                        parts.append(news_block)
            except Exception as e:
                logger.warning(f"[AUTO] News context build failed (non-fatal): {e}")

        # --- Social sentiment (Reddit) -- close the existing capture/feed gap ---
        try:
            sentiment = getattr(self, "_sentiment_data", None)
            if sentiment:
                sentiment_block = format_sentiment_context(sentiment)
                if sentiment_block:
                    parts.append(sentiment_block)
        except Exception as e:
            logger.warning(f"[AUTO] Sentiment context build failed (non-fatal): {e}")

        if not parts:
            return ""
        return "\n\n" + "\n\n".join(parts)

    async def _prefetch_investor_data(self) -> dict:
        """Pre-fetch investor positions and commentary (I/O phase)."""
        try:
            if not _HAS_INVESTOR_FEEDS:
                return {}
            from data.adapters.investor_feeds import get_investor_feed_adapter  # type: ignore[import-not-found]
            adapter = get_investor_feed_adapter()
            # Load custom investor list from settings if available
            custom_investors = None
            try:
                from services.settings_service import get_settings_service  # type: ignore[import-not-found]
                svc = get_settings_service()
                custom_investors = await svc.get_setting("investor_watchlist")
            except Exception as settings_err:
                logger.debug("Could not load investor_watchlist setting: %s", settings_err)
            return await adapter.get_all_intelligence(investors=custom_investors)
        except Exception as e:
            logger.warning("Investor data pre-fetch failed: %s", e)
            return {}

    async def _run_thematic_analysis(self, macro_result: MacroScanResult) -> ThematicAnalysisResult | None:
        """Run thematic analysis on macro scan results."""
        try:
            macro_dict = macro_result.to_dict() if hasattr(macro_result, 'to_dict') else macro_result
            prompt = format_thematic_context(macro_dict)
            response = await self._query_llm(
                THEMATIC_ANALYST_PROMPT,
                prompt,
                "thematic_analyst",
                "thematic_analysis",
            )
            if not response:
                return None
            return parse_thematic_response(response)
        except Exception as e:
            logger.warning("Thematic analysis failed: %s", e)
            return None

    async def _run_investor_intelligence(self, investor_data: dict, macro_result: MacroScanResult) -> InvestorIntelligenceResult | None:
        """Run investor intelligence analysis."""
        try:
            if not investor_data:
                return None
            macro_dict = macro_result.to_dict() if hasattr(macro_result, 'to_dict') else macro_result
            prompt = format_investor_context(investor_data, macro_dict)
            response = await self._query_llm(
                INVESTOR_SENTIMENT_PROMPT,
                prompt,
                "investor_sentiment",
                "investor_intelligence",
            )
            if not response:
                return None
            return parse_investor_response(response)
        except Exception as e:
            logger.warning("Investor intelligence analysis failed: %s", e)
            return None

    async def _persist_thematic_insights(
        self,
        thematic_result: ThematicAnalysisResult,
        task_id: str | None = None,
    ) -> None:
        """Persist thematic threads to DB with dedup and outcome tracking.

        For each ThematicThread in the result:
        - Compute fingerprint, check for existing active theme
        - If exists + confidence within 0.2: update run_count, refresh confidence
        - If exists + confidence diverges >0.2: supersede old, create new
        - If new: create ThematicInsight + start ThematicOutcome tracking
        """
        from sqlalchemy import select

        from analysis.thematic_outcome_tracker import ThematicOutcomeTracker
        from models.thematic_insight import LifecycleState, ThematicInsight

        async with async_session_factory() as session:
            tracker = ThematicOutcomeTracker(session)

            for thread in thematic_result.threads:
                try:
                    async with session.begin_nested():
                        fingerprint = ThematicInsight.compute_fingerprint(
                            thread.category, thread.primary_symbols
                        )

                        # Check for existing active theme with same fingerprint
                        existing_query = (
                            select(ThematicInsight)
                            .where(
                                ThematicInsight.theme_fingerprint == fingerprint,
                                ThematicInsight.lifecycle_state == LifecycleState.ACTIVE.value,
                            )
                        )
                        existing_result = await session.execute(existing_query)
                        existing = existing_result.scalar_one_or_none()

                        if existing:
                            confidence_diff = abs(existing.confidence - thread.confidence)
                            if confidence_diff <= 0.2:
                                # Same theme, similar confidence: update run_count
                                existing.run_count += 1
                                existing.confidence = thread.confidence
                                existing.effective_confidence = existing.compute_effective_confidence()
                                existing.thesis = thread.thesis
                                existing.counter_thesis = thread.counter_thesis
                                logger.info(
                                    "Updated existing thematic insight %s (run_count=%d)",
                                    existing.id, existing.run_count,
                                )
                            else:
                                # Confidence diverged: supersede old, create new
                                existing.lifecycle_state = LifecycleState.SUPERSEDED.value
                                new_insight = ThematicInsight(
                                    theme_name=thread.theme_name,
                                    category=thread.category,
                                    theme_fingerprint=fingerprint,
                                    direction=thread.direction,
                                    confidence=thread.confidence,
                                    thesis=thread.thesis,
                                    counter_thesis=thread.counter_thesis,
                                    meta_narrative=thematic_result.meta_narrative,
                                    primary_symbols=thread.primary_symbols,
                                    affected_sectors=thread.affected_sectors,
                                    supply_chain_links=thread.supply_chain_links,
                                    catalyst_timeline=thread.catalyst_timeline,
                                    theme_interactions=thematic_result.theme_interactions,
                                    analysis_task_id=task_id,
                                    effective_confidence=thread.confidence,
                                )
                                session.add(new_insight)
                                await session.flush()
                                existing.superseded_by_id = new_insight.id

                                # Start tracking for new insight
                                if thread.primary_symbols:
                                    try:
                                        await tracker.start_tracking(
                                            insight_id=new_insight.id,
                                            symbols=thread.primary_symbols,
                                            predicted_direction=thread.direction,
                                            catalyst_timeline=thread.catalyst_timeline,
                                        )
                                    except Exception as track_err:
                                        logger.warning("Failed to start tracking for superseding theme: %s", track_err, exc_info=True)

                                logger.info(
                                    "Superseded thematic insight %s with %s (confidence diverged %.2f)",
                                    existing.id, new_insight.id, confidence_diff,
                                )
                        else:
                            # New theme
                            new_insight = ThematicInsight(
                                theme_name=thread.theme_name,
                                category=thread.category,
                                theme_fingerprint=fingerprint,
                                direction=thread.direction,
                                confidence=thread.confidence,
                                thesis=thread.thesis,
                                counter_thesis=thread.counter_thesis,
                                meta_narrative=thematic_result.meta_narrative,
                                primary_symbols=thread.primary_symbols,
                                affected_sectors=thread.affected_sectors,
                                supply_chain_links=thread.supply_chain_links,
                                catalyst_timeline=thread.catalyst_timeline,
                                theme_interactions=thematic_result.theme_interactions,
                                analysis_task_id=task_id,
                                effective_confidence=thread.confidence,
                            )
                            session.add(new_insight)
                            await session.flush()

                            # Start tracking
                            if thread.primary_symbols:
                                try:
                                    await tracker.start_tracking(
                                        insight_id=new_insight.id,
                                        symbols=thread.primary_symbols,
                                        predicted_direction=thread.direction,
                                        catalyst_timeline=thread.catalyst_timeline,
                                    )
                                except Exception as track_err:
                                    logger.warning("Failed to start tracking for new theme: %s", track_err, exc_info=True)

                            logger.info(
                                "Created new thematic insight %s: %s",
                                new_insight.id, thread.theme_name,
                            )

                except Exception as e:
                    logger.warning("Failed to persist thematic thread %s: %s", thread.theme_name, e, exc_info=True)
                    continue

            await session.commit()
            logger.info(
                "Persisted %d thematic threads from analysis",
                len(thematic_result.threads),
            )

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
        max_insights: int = 10,
        deep_dive_count: int = 12,
        task_id: str | None = None,
        quant_context: str | None = None,
    ) -> AutonomousAnalysisResult:
        """Run complete autonomous analysis pipeline.

        Executes the heatmap-driven autonomous analysis:
        1. Macro Scan - Global macro environment
        2. Heatmap Fetch - Dynamic sector/stock heatmap data
        3. Heatmap Analysis - LLM pattern detection and stock selection
        4. Deep Dive - 3 core analysts (technical, sector, risk) per stock
        5. Synthesis - Rank and produce final insights

        Post-analysis pattern extraction runs in the background (non-blocking).

        Falls back to legacy sector rotation / opportunity hunt if heatmap fails.

        Args:
            max_insights: Number of final insights to produce (default 5).
            deep_dive_count: Number of opportunities to analyze in detail (default 5).
            task_id: Optional task ID for progress tracking in database.

        Returns:
            AutonomousAnalysisResult with insights, context, and metadata.
        """
        analysis_id = str(uuid4())
        start_time = datetime.utcnow()
        result = AutonomousAnalysisResult(analysis_id=analysis_id)

        # Store quant context for injection into analyst and synthesis contexts
        self._quant_context = quant_context

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
            news_coro = self._prefetch_news_data()
            investor_coro = self._prefetch_investor_data()
            (
                phase1_result,
                phase2_result,
                prediction_data,
                sentiment_data,
                news_data,
                investor_data,
            ) = await asyncio.gather(
                macro_coro, heatmap_coro, prediction_coro, sentiment_coro,
                news_coro, investor_coro,
                return_exceptions=True,
            )

            # --- Handle pre-fetch results (non-blocking) ---
            if isinstance(prediction_data, BaseException):
                logger.warning(f"Prediction pre-fetch failed: {prediction_data}")
                prediction_data = {}
            if isinstance(sentiment_data, BaseException):
                logger.warning(f"Sentiment pre-fetch failed: {sentiment_data}")
                sentiment_data = {}
            if isinstance(news_data, BaseException):
                logger.warning(f"News pre-fetch failed: {news_data}")
                news_data = {}
            if isinstance(investor_data, BaseException):
                logger.warning(f"Investor data pre-fetch failed: {investor_data}")
                investor_data = {}

            # Store pre-fetched data on instance for downstream access
            self._prediction_data = prediction_data
            self._sentiment_data = sentiment_data
            self._news_data = news_data
            self._investor_data = investor_data

            # Merge macro-economic news (fetched inside the macro scan) into the
            # news payload so it persists and displays alongside market tone.
            if self._macro_news_data:
                if not isinstance(self._news_data, dict):
                    self._news_data = {}
                self._news_data["macro"] = self._macro_news_data

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

            # ===== PHASE 1.5: Thematic + Investor Intelligence (parallel) =====
            self._thematic_result = None
            self._investor_result = None
            try:
                thematic_coro = self._run_thematic_analysis(macro_result)
                investor_intel_coro = self._run_investor_intelligence(
                    self._investor_data, macro_result
                )
                phase_1_5_results = await asyncio.gather(
                    thematic_coro, investor_intel_coro, return_exceptions=True
                )
                if not isinstance(phase_1_5_results[0], BaseException):
                    self._thematic_result = phase_1_5_results[0]
                else:
                    logger.warning("Thematic analysis raised: %s", phase_1_5_results[0])
                if not isinstance(phase_1_5_results[1], BaseException):
                    self._investor_result = phase_1_5_results[1]
                else:
                    logger.warning("Investor intelligence raised: %s", phase_1_5_results[1])
            except Exception as phase_1_5_err:
                logger.warning("Phase 1.5 failed: %s", phase_1_5_err)

            # Store results on the analysis result object
            if self._thematic_result:
                result.thematic_analysis = self._thematic_result.to_dict()
            if self._investor_result:
                result.investor_intelligence = self._investor_result.to_dict()

            # Persist thematic insights to DB (non-blocking)
            if self._thematic_result and self._thematic_result.threads:
                try:
                    await self._persist_thematic_insights(
                        self._thematic_result, task_id=task_id
                    )
                except Exception as thematic_persist_err:
                    logger.warning("Failed to persist thematic insights: %s", thematic_persist_err, exc_info=True)

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

        # ===== Compute Factor Scores from heatmap data =====
        factor_scores = await self._compute_factor_scores(heatmap_data)
        if factor_scores:
            # Store factor scores on the result for report generation
            result.factor_scores = {
                sym: fs.to_dict() for sym, fs in factor_scores.items()
            }

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

        # Merge top portfolio holdings into deep dive list (max 3 extra,
        # sorted by position size to prioritize the most significant holdings)
        if portfolio_holdings:
            existing_symbols = set(symbols_to_analyze)
            sorted_holdings = sorted(
                [(sym, info) for sym, info in portfolio_holdings.items()
                 if sym not in existing_symbols],
                key=lambda x: x[1].get("total_cost", 0),
                reverse=True,
            )
            portfolio_additions = [sym for sym, _ in sorted_holdings[:3]]
            if portfolio_additions:
                symbols_to_analyze.extend(portfolio_additions)
                logger.info(
                    f"Added {len(portfolio_additions)} portfolio-held symbols "
                    f"to deep dive: {portfolio_additions}"
                )

        # Phase 3.5: Stock Description Enrichment (non-fatal)
        self._stock_descriptions = {}
        self._stock_clusters = []
        self._cluster_analyses = []
        try:
            logger.info(f"Phase 3.5: Enriching {len(symbols_to_analyze)} stocks with thematic descriptions...")
            await self._update_task_progress(
                task_id, "stock_enrichment", 52,
                f"Generating thematic profiles for {len(symbols_to_analyze)} stocks..."
            )
            if self._run_metrics:
                self._run_metrics.start_phase("stock_enrichment")

            # Fetch yfinance business summaries in parallel
            biz_summaries = await self._fetch_business_summaries(symbols_to_analyze)

            if not biz_summaries:
                logger.warning(
                    "Phase 3.5: All yfinance summaries empty for %s — skipping enrichment",
                    symbols_to_analyze,
                )

            if biz_summaries:
                # Build macro/thematic context for the LLM
                macro_themes = [t.name for t in macro_result.themes[:3]] if macro_result else []
                thematic_threads = []
                _tr = self._thematic_result
                if _tr is not None and _tr.threads:
                    thematic_threads = [t.theme_name for t in _tr.threads[:5]]

                # Single batched LLM call for all stocks
                self._stock_descriptions, self._stock_clusters = await self._enrich_stock_descriptions(
                    symbols_to_analyze, biz_summaries, macro_themes, thematic_threads,
                )

                # Compute cluster-relative performance for anomaly detection
                if self._stock_clusters:
                    try:
                        self._stock_clusters = self._compute_cluster_performance(
                            self._stock_clusters, heatmap_data,
                        )
                    except Exception as perf_err:
                        logger.warning(f"Phase 3.5: Cluster performance computation failed (non-fatal): {perf_err}")

                # Persist to Stock.thematic_description in DB
                if self._stock_descriptions:
                    if self._stock_clusters:
                        logger.info(
                            f"Phase 3.5: Identified {len(self._stock_clusters)} thematic clusters"
                        )
                    async with async_session_factory() as enrich_session:
                        from sqlalchemy import update  # type: ignore[import-not-found]
                        from models.stock import Stock  # type: ignore[import-not-found]
                        for sym, desc in self._stock_descriptions.items():
                            await enrich_session.execute(
                                update(Stock)
                                .where(Stock.symbol == sym)
                                .values(thematic_description=desc)
                            )
                        await enrich_session.commit()
                    logger.info(
                        f"Phase 3.5: Persisted thematic descriptions for "
                        f"{len(self._stock_descriptions)} stocks"
                    )

            if self._run_metrics:
                self._run_metrics.end_phase("stock_enrichment")
        except Exception as enrich_err:
            logger.warning(f"Phase 3.5: Stock enrichment failed (non-fatal): {enrich_err}")
            if self._run_metrics:
                self._run_metrics.end_phase("stock_enrichment")

        logger.info(f"Phase 4: Deep diving into {symbols_to_analyze}...")
        await self._update_task_progress(
            task_id, "deep_dive", 55,
            f"Analyzing {len(symbols_to_analyze)} candidates..."
        )
        if self._run_metrics:
            self._run_metrics.start_phase("deep_dive")

        # Build discovery context using macro result and heatmap analysis
        discovery_context = self._build_heatmap_discovery_context(
            macro_result, heatmap_analysis_result, factor_scores=factor_scores,
            thematic_result=getattr(self, '_thematic_result', None),
            stock_descriptions=self._stock_descriptions or None,
        )

        # Append IC-calibrated quant signals so analysts know which names the
        # quant model flagged and why — convergence with heatmap/thematic = higher conviction
        if getattr(self, '_quant_context', None):
            discovery_context = (
                f"{discovery_context}\n\n"
                f"## IC-Calibrated Quant Signals (Bottom-Up Screen)\n"
                f"{self._quant_context}"
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

        # Drop candidates whose price snapshot is stale or missing.  A symbol
        # whose last bar is weeks old cannot support entry, stop or target
        # levels, and analysing it anyway is how months-old prices ended up in
        # live recommendations.  partition_by_freshness logs each drop with the
        # status and bar date behind it.
        usable_symbols, dropped_symbols = partition_by_freshness(
            symbols_to_analyze, pre_context,
        )
        if dropped_symbols and usable_symbols:
            symbols_to_analyze = usable_symbols
            result.errors.append(
                f"Deep dive: dropped {len(dropped_symbols)} symbol(s) on stale or "
                f"missing price data: "
                f"{', '.join(sym for sym, _ in dropped_symbols)}"
            )
        elif dropped_symbols:
            # Every candidate is unusable -- a data outage, not a stock pick.
            # Analysing none of them beats recommending all of them off old
            # prices; the pipeline continues and synthesises zero insights.
            symbols_to_analyze = []
            logger.error(
                "[AUTO] Every deep-dive candidate has unusable price data "
                "(%d symbols); skipping the deep dive entirely.",
                len(dropped_symbols),
            )
            result.errors.append(
                "Deep dive skipped: no candidate had a usable price snapshot "
                f"({', '.join(sym for sym, _ in dropped_symbols)}). "
                "Check that the price ETL has run."
            )

        # Compute correlation matrix from price history and append to discovery context
        try:
            from analysis.statistical_calculator import StatisticalFeatureCalculator  # type: ignore[import-not-found]
            from analysis.agents.correlation_detective import format_correlation_matrix_context  # type: ignore[import-not-found]

            price_history = pre_context.get("price_history", {})
            if price_history and len(price_history) >= 2:
                import pandas as pd  # type: ignore[import-untyped]

                # Convert price_history dicts to DataFrames with 'close' column
                price_dfs: dict[str, Any] = {}
                for sym, prices in price_history.items():
                    if prices and len(prices) >= 5:
                        closes = [p.get("close") for p in prices if p.get("close") is not None]
                        if len(closes) >= 5:
                            price_dfs[sym] = pd.DataFrame({"close": closes})

                if len(price_dfs) >= 2:
                    async with async_session_factory() as corr_session:
                        calc = StatisticalFeatureCalculator(corr_session)
                        corr_result = await calc.compute_correlation_matrix(price_dfs)
                    corr_context = format_correlation_matrix_context(corr_result=corr_result)
                    discovery_context += f"\n\n{corr_context}"
                    logger.info(f"[AUTO] Correlation matrix computed for {len(price_dfs)} symbols")

                    # Store correlation highlights on the result for report generation
                    try:
                        corr_highlights: dict[str, Any] = {
                            "regime": macro_result.market_regime if macro_result else "Unknown",
                        }
                        # Top correlated pairs
                        top_pairs: list[dict[str, Any]] = []
                        anomalies: list[dict[str, Any]] = []
                        symbols_list = list(corr_result.matrix.index)
                        for i, sym_a in enumerate(symbols_list):
                            for sym_b in symbols_list[i + 1:]:
                                val = corr_result.get_pair(sym_a, sym_b)
                                if val is not None:
                                    top_pairs.append({
                                        "symbol1": sym_a,
                                        "symbol2": sym_b,
                                        "correlation": round(val, 3),
                                    })
                                    # Flag anomalies (unusually high or low)
                                    if abs(val) > 0.85:
                                        anomalies.append({
                                            "symbol1": sym_a,
                                            "symbol2": sym_b,
                                            "correlation": round(val, 3),
                                            "type": "unusually_high" if val > 0 else "negative_high",
                                        })
                                    elif abs(val) < 0.1:
                                        anomalies.append({
                                            "symbol1": sym_a,
                                            "symbol2": sym_b,
                                            "correlation": round(val, 3),
                                            "type": "near_zero",
                                        })
                        # Sort and keep top 10 most correlated
                        top_pairs.sort(key=lambda p: abs(p["correlation"]), reverse=True)
                        corr_highlights["top_pairs"] = top_pairs[:10]
                        corr_highlights["anomalies"] = anomalies[:5]
                        corr_highlights["period_days"] = corr_result.period_days
                        corr_highlights["method"] = corr_result.method
                        result.correlation_highlights = corr_highlights
                    except Exception as corr_store_err:
                        logger.debug(f"[AUTO] Failed to store correlation highlights: {corr_store_err}")
        except Exception as corr_err:
            logger.warning(f"[AUTO] Correlation matrix computation failed (non-fatal): {corr_err}")

        async def _analyze_symbol(sym: str) -> tuple[str, dict[str, Any]]:
            reports = await self._run_analysts_for_symbol(sym, discovery_context, pre_built_context=pre_context)
            return sym, reports

        async def _with_timeout(coro, sym):
            try:
                return await asyncio.wait_for(coro, timeout=self.timeout_seconds * 3)
            except asyncio.TimeoutError:
                logger.error(f"Symbol {sym} analysis timed out after {self.timeout_seconds * 3}s")
                return asyncio.TimeoutError(f"{sym} timed out")

        gather_results = await asyncio.gather(
            *[_with_timeout(_analyze_symbol(sym), sym) for sym in symbols_to_analyze],
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

        # Phase 4.5 (coverage evaluation) skipped — the heatmap analyzer
        # already selects a diverse set of stocks across sectors.  The
        # coverage loop added 10-25 extra LLM calls for marginal gain.
        result.phases_completed.append("coverage_evaluation")
        result.phase_summaries["coverage_evaluation"] = (
            f"Coverage evaluation skipped (optimized pipeline). "
            f"{len(analyst_reports)} stocks analyzed."
        )

        # ===== Capture catalyst data for report =====
        try:
            from analysis.catalyst_tracker import get_catalyst_tracker  # type: ignore[import-not-found]

            catalyst_tracker = get_catalyst_tracker()
            catalyst_symbols = list(analyst_reports.keys())[:10]
            catalyst_events = await catalyst_tracker.earnings_adapter.get_upcoming_catalysts(
                catalyst_symbols, days_ahead=30
            )
            if catalyst_events:
                result.catalyst_data = [
                    {
                        "symbol": evt.symbol,
                        "event_type": evt.event_type,
                        "date": evt.date.strftime("%Y-%m-%d") if evt.date else None,
                        "days_until": evt.days_until,
                        "details": evt.details,
                    }
                    for evt in catalyst_events
                ]
                logger.info(f"[AUTO] Captured {len(result.catalyst_data)} catalyst events for report")
        except Exception as cat_capture_err:
            logger.debug(f"[AUTO] Catalyst data capture for report failed (non-fatal): {cat_capture_err}")

        # ===== PHASE 4.7: Cluster-Level Analysis (non-fatal) =====
        self._cluster_analyses = []
        if self._stock_clusters:
            try:
                logger.info(f"Phase 4.7: Analyzing {len(self._stock_clusters)} thematic clusters...")
                await self._update_task_progress(
                    task_id, "cluster_analysis", 87,
                    f"Analyzing {len(self._stock_clusters)} thematic clusters..."
                )
                if self._run_metrics:
                    self._run_metrics.start_phase("cluster_analysis")

                macro_themes = [t.name for t in macro_result.themes[:3]] if macro_result else []

                self._cluster_analyses = await self._run_cluster_analysis(
                    self._stock_clusters, analyst_reports, macro_themes,
                )

                if self._cluster_analyses:
                    result.phases_completed.append("cluster_analysis")
                    result.phase_summaries["cluster_analysis"] = (
                        f"Analyzed {len(self._cluster_analyses)} thematic clusters"
                    )
                    logger.info(
                        f"Phase 4.7: Completed cluster analysis for "
                        f"{len(self._cluster_analyses)} clusters"
                    )

                if self._run_metrics:
                    self._run_metrics.end_phase("cluster_analysis")
            except Exception as cluster_err:
                logger.warning(f"Phase 4.7: Cluster analysis failed (non-fatal): {cluster_err}")
                if self._run_metrics:
                    self._run_metrics.end_phase("cluster_analysis")

        # ===== PHASE 5: Synthesis =====
        logger.info("Phase 5: Synthesizing insights...")
        await self._update_task_progress(task_id, "synthesis", 90, "Synthesizing insights...")
        if self._run_metrics:
            self._run_metrics.start_phase("synthesis")
        insights_data, synthesis_raw_response = await self._run_synthesis_with_heatmap(
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
                analyst_reports=analyst_reports,
                synthesis_raw_response=synthesis_raw_response,
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
        dynamic_holdings = None
        try:
            from analysis.agents.heatmap_fetcher import get_dynamic_holdings  # type: ignore[import-not-found]
            dynamic_holdings = await get_dynamic_holdings()
        except Exception as exc:
            logger.debug("Dynamic holdings unavailable for heatmap fetch: %s", exc)
        return await fetcher.fetch_heatmap_data(holdings=dynamic_holdings or None)

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

            async def _with_timeout(coro, sym):
                try:
                    return await asyncio.wait_for(coro, timeout=self.timeout_seconds * 3)
                except asyncio.TimeoutError:
                    logger.error(f"Symbol {sym} analysis timed out after {self.timeout_seconds * 3}s")
                    return asyncio.TimeoutError(f"{sym} timed out")

            coverage_results = await asyncio.gather(
                *[_with_timeout(_analyze_additional(sym), sym) for sym in additional_symbols],
                return_exceptions=True,
            )

            for r in coverage_results:
                if isinstance(r, BaseException):
                    logger.error(f"Additional deep dive failed: {r}")
                else:
                    sym, sym_reports = r
                    analyst_reports[sym] = sym_reports

        return analyst_reports

    # -----------------------------------------------------------------
    # Phase 3.5 helpers: Stock Description Enrichment
    # -----------------------------------------------------------------

    async def _fetch_business_summaries(
        self,
        symbols: list[str],
    ) -> dict[str, str]:
        """Fetch yfinance longBusinessSummary for each symbol in parallel.

        Uses ThreadPoolExecutor (8 workers) and truncates to 500 chars.
        Returns dict mapping symbol -> summary text.
        """
        import yfinance as yf  # type: ignore[import-untyped]
        from concurrent.futures import ThreadPoolExecutor

        def _get_summary(sym: str) -> tuple[str, str]:
            try:
                info = yf.Ticker(sym).info
                summary = (info or {}).get("longBusinessSummary", "")
                return sym, (summary[:500] if summary else "")
            except Exception:
                return sym, ""

        loop = asyncio.get_event_loop()

        def _fetch_all() -> list[tuple[str, str]]:
            with ThreadPoolExecutor(max_workers=8) as executor:
                return list(executor.map(_get_summary, symbols))

        results = await loop.run_in_executor(None, _fetch_all)
        return {sym: summary for sym, summary in results if summary}

    async def _enrich_stock_descriptions(
        self,
        symbols: list[str],
        biz_summaries: dict[str, str],
        macro_themes: list[str],
        thematic_threads: list[str],
    ) -> tuple[dict[str, str], list[dict[str, Any]]]:
        """Generate thematic descriptions and clusters via a single batched LLM call.

        Args:
            symbols: Stock symbols to describe.
            biz_summaries: yfinance business summaries per symbol.
            macro_themes: Current macro theme names.
            thematic_threads: Current thematic thread names.

        Returns:
            Tuple of (descriptions dict, thematic clusters list).
        """
        # Build the batch prompt
        stock_lines = []
        for sym in symbols:
            summary = biz_summaries.get(sym, "No summary available")
            stock_lines.append(f"- {sym}: {summary}")

        theme_context = ""
        if macro_themes:
            theme_context += f"\nCurrent macro themes: {', '.join(macro_themes)}"
        if thematic_threads:
            theme_context += f"\nThematic threads: {', '.join(thematic_threads)}"

        system_prompt = (
            "You are a thematic stock analyst. Your task has two parts:\n\n"
            "PART 1 — Per-stock descriptions:\n"
            "For each stock, write a concise thematic description (15-25 words) that captures:\n"
            "1. The company's investment angle and niche positioning\n"
            "2. Cross-stock thematic connections (e.g. 'AI infrastructure', "
            "'pick-and-shovel play')\n"
            "3. Use investment-relevant language, not corporate boilerplate\n\n"
            "PART 2 — Thematic clusters:\n"
            "Group stocks that share a thematic connection. Each cluster should have:\n"
            "- A short theme name (e.g. 'AI Optical Infrastructure')\n"
            "- The symbols that belong to this cluster\n"
            "- A brief rationale explaining the connection\n"
            "A stock can appear in multiple clusters. Only create clusters with 2+ stocks.\n\n"
            "Return ONLY valid JSON with this structure:\n"
            "{\n"
            '  "descriptions": {"SYMBOL": "description", ...},\n'
            '  "clusters": [\n'
            '    {"theme": "Theme Name", "symbols": ["SYM1", "SYM2"], "rationale": "Why these are connected"}\n'
            "  ]\n"
            "}\n"
            "No markdown, no code blocks, just the JSON object."
        )

        user_prompt = (
            f"Generate thematic descriptions for these stocks:{theme_context}\n\n"
            f"Stock summaries:\n" + "\n".join(stock_lines)
        )

        response = await self._query_llm(
            system_prompt, user_prompt,
            agent_name="stock_enrichment",
            phase="stock_enrichment",
        )

        # Parse JSON from response
        descriptions: dict[str, str] = {}
        clusters: list[dict[str, Any]] = []
        parsed = self._parse_json_response(response)
        if parsed:
            if "descriptions" in parsed:
                raw_desc = parsed["descriptions"]
                if isinstance(raw_desc, dict):
                    descriptions = raw_desc
                clusters = parsed.get("clusters", [])
                if not isinstance(clusters, list):
                    clusters = []
            else:
                # Fallback: flat dict (old format)
                descriptions = parsed
        else:
            logger.warning("Phase 3.5: Could not parse LLM response as JSON")

        # Filter to expected symbols and cap at 200 chars
        valid_symbols = set(symbols)
        filtered_descriptions = {
            sym: desc[:200]
            for sym, desc in descriptions.items()
            if sym in valid_symbols and isinstance(desc, str)
        }
        # Filter clusters to only include valid symbols
        filtered_clusters = []
        for cluster in clusters:
            if isinstance(cluster, dict) and isinstance(cluster.get("symbols"), list):
                valid_syms = [s for s in cluster["symbols"] if s in valid_symbols]
                if len(valid_syms) >= 2:
                    filtered_clusters.append({
                        "theme": str(cluster.get("theme", "Unknown"))[:100],
                        "symbols": valid_syms,
                        "rationale": str(cluster.get("rationale", ""))[:200],
                    })
        return filtered_descriptions, filtered_clusters

    def _compute_cluster_performance(
        self,
        clusters: list[dict[str, Any]],
        heatmap_data: HeatmapData,
    ) -> list[dict[str, Any]]:
        """Compute cluster-relative performance for anomaly detection.

        Uses already-fetched heatmap data (Phase 2) to avoid redundant
        yfinance calls. Flags laggards/outperformers vs cluster average.

        Args:
            clusters: List of cluster dicts with 'theme', 'symbols', 'rationale'.
            heatmap_data: Heatmap data from Phase 2 with per-stock metrics.

        Returns:
            Enriched cluster list with 'performance' key added to each cluster.
        """
        # Build returns lookup from already-fetched heatmap data
        returns: dict[str, float] = {}
        for stock in heatmap_data.stocks:
            if stock.change_20d is not None:
                returns[stock.symbol] = stock.change_20d

        if not returns:
            return clusters

        # Enrich each cluster with performance data
        enriched = []
        for cluster in clusters:
            cluster_copy = dict(cluster)
            syms = cluster.get("symbols", [])
            sym_returns = {s: returns[s] for s in syms if s in returns}

            if len(sym_returns) >= 2:
                avg_return = sum(sym_returns.values()) / len(sym_returns)
                performance = []
                for sym, ret in sorted(sym_returns.items(), key=lambda x: x[1], reverse=True):
                    delta = ret - avg_return
                    flag = ""
                    if delta < -10:
                        flag = "LAGGARD"
                    elif delta > 10:
                        flag = "OUTPERFORMER"
                    performance.append({
                        "symbol": sym,
                        "return_20d": round(ret, 1),
                        "vs_cluster_avg": round(delta, 1),
                        "flag": flag,
                    })
                cluster_copy["performance"] = performance
                cluster_copy["cluster_avg_return"] = round(avg_return, 1)

            enriched.append(cluster_copy)

        return enriched

    @staticmethod
    def _parse_json_response(text: str) -> dict[str, Any] | None:
        """Extract JSON dict from an LLM response.

        Handles pure JSON, JSON in code blocks, and JSON embedded in prose.
        """
        import re

        # Try full text as JSON
        try:
            result = json.loads(text.strip())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # Try code blocks
        for match in re.findall(r"```(?:json)?\s*([\s\S]*?)```", text):
            try:
                result = json.loads(match.strip())
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                continue

        # Try first { to last }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                result = json.loads(text[start:end + 1])
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        return None

    @staticmethod
    def _dump_synthesis_debug(response: str) -> None:
        """Dump full synthesis response to a file for post-mortem debugging."""
        try:
            from pathlib import Path
            debug_dir = Path(__file__).resolve().parent.parent / "data"
            debug_dir.mkdir(exist_ok=True)
            debug_file = debug_dir / "synthesis_debug_last.txt"
            debug_file.write_text(response)
            logger.warning("[AUTO] Full synthesis response dumped to %s", debug_file)
        except Exception as dump_err:
            logger.debug("Failed to dump synthesis debug file: %s", dump_err)

    async def _run_cluster_analysis(
        self,
        clusters: list[dict[str, Any]],
        analyst_reports: dict[str, dict[str, Any]],
        macro_themes: list[str],
    ) -> list[dict[str, Any]]:
        """Run Phase 4.7: Cluster-level analysis across thematic groups.

        For each cluster with 2+ stocks, runs a single LLM call with all
        member stocks' analyst reports to identify cluster-level dynamics.

        Args:
            clusters: Enriched cluster dicts (with performance data).
            analyst_reports: Per-symbol analyst reports from Phase 4.
            macro_themes: Current macro theme names for context.

        Returns:
            List of cluster analysis dicts with theme, symbols, and analysis.
        """
        if not clusters:
            return []

        results: list[dict[str, Any]] = []

        system_prompt = (
            "You are a thematic cluster analyst. You receive a group of stocks "
            "that share a thematic connection, along with their individual analyst "
            "reports and relative performance data.\n\n"
            "Analyze the CLUSTER as a whole — not individual stocks. Focus on:\n"
            "1. **Laggard diagnosis**: If a stock trails its cluster peers, is it a "
            "catch-up opportunity (delayed reaction, temporary headwind) or a "
            "fundamental divergence (losing market share, weaker execution)?\n"
            "2. **Cluster catalyst**: What shared demand driver or catalyst links these "
            "stocks? How strong is the thematic connection?\n"
            "3. **Concentration risk**: If an investor holds multiple stocks in this "
            "cluster, what correlated risk are they exposed to?\n"
            "4. **Trade opportunity**: Is there a pairs trade, basket trade, or "
            "relative-value opportunity within this cluster?\n\n"
            "Return ONLY valid JSON:\n"
            "{\n"
            '  "cluster_thesis": "2-3 sentence thesis about this cluster as a group",\n'
            '  "laggard_assessment": "diagnosis of any underperformers, or null if none",\n'
            '  "catalyst_strength": "strong|moderate|weak",\n'
            '  "concentration_risk": "high|moderate|low",\n'
            '  "trade_opportunity": "description of any relative-value or basket opportunity, or null",\n'
            '  "conviction": 0.75\n'
            "}\n"
            "No markdown, no code blocks, just the JSON object."
        )

        async def _analyze_one_cluster(cluster: dict[str, Any]) -> dict[str, Any] | None:
            syms = cluster.get("symbols", [])
            if len(syms) < 2:
                return None

            # Build per-stock report summaries for this cluster
            stock_sections = []
            for sym in syms:
                reports = analyst_reports.get(sym, {})
                if not reports:
                    stock_sections.append(f"### {sym}\nNo analyst reports available.")
                    continue

                section_lines = [f"### {sym}"]
                # Add thematic description if available
                desc = self._stock_descriptions.get(sym, "")
                if desc:
                    section_lines.append(f"Thematic Profile: {desc}")

                for analyst_name, report in reports.items():
                    if isinstance(report, dict):
                        if report.get("error"):
                            section_lines.append(f"{analyst_name}: Error — {report['error']}")
                        else:
                            summary = str(report)[:500]
                            section_lines.append(f"{analyst_name}: {summary}")
                stock_sections.append("\n".join(section_lines))

            # Build performance context
            perf_lines = []
            if cluster.get("performance"):
                avg = cluster.get("cluster_avg_return", 0)
                perf_lines.append(f"Cluster avg 20d return: {avg:+.1f}%")
                for p in cluster["performance"]:
                    flag = f" {p['flag']}" if p.get("flag") else ""
                    perf_lines.append(
                        f"  {p['symbol']}: {p['return_20d']:+.1f}% "
                        f"(vs cluster: {p['vs_cluster_avg']:+.1f}%){flag}"
                    )

            theme_context = ""
            if macro_themes:
                theme_context = f"\nMacro themes: {', '.join(macro_themes)}\n"

            user_prompt = (
                f"Cluster: {cluster.get('theme', 'Unknown')}\n"
                f"Symbols: {', '.join(syms)}\n"
                f"Rationale: {cluster.get('rationale', '')}\n"
                f"{theme_context}\n"
                f"### Performance:\n"
                + "\n".join(perf_lines)
                + "\n\n### Individual Analyst Reports:\n\n"
                + "\n\n".join(stock_sections)
            )

            try:
                response = await self._query_llm(
                    system_prompt, user_prompt,
                    agent_name="cluster_analyst",
                    phase="cluster_analysis",
                )

                analysis = self._parse_json_response(response) or {}
                if not analysis:
                    logger.warning(f"Phase 4.7: Could not parse cluster analysis for {cluster.get('theme')}")
                    return None

                return {
                    "theme": cluster.get("theme", "Unknown"),
                    "symbols": syms,
                    "analysis": analysis,
                }

            except Exception as e:
                logger.warning(f"Phase 4.7: Cluster analysis failed for {cluster.get('theme')}: {e}")
                return None

        # Run all cluster analyses concurrently
        async def _with_cluster_timeout(coro, cluster):
            theme = cluster.get("theme", "unknown")
            try:
                return await asyncio.wait_for(coro, timeout=self.timeout_seconds * 3)
            except asyncio.TimeoutError:
                logger.error(f"Cluster '{theme}' analysis timed out after {self.timeout_seconds * 3}s")
                return asyncio.TimeoutError(f"Cluster '{theme}' timed out")

        gather_results = await asyncio.gather(
            *[_with_cluster_timeout(_analyze_one_cluster(c), c) for c in clusters],
            return_exceptions=True,
        )
        for r in gather_results:
            if isinstance(r, BaseException):
                logger.warning(f"Phase 4.7: Cluster analysis error: {r}")
            elif r is not None:
                results.append(r)

        return results

    def _render_cluster_context(self) -> list[str]:
        """Render thematic cluster data as context lines.

        Includes cluster descriptions, performance data, and anomaly flags.
        Used by both discovery and synthesis context builders.
        """
        if not self._stock_clusters:
            return []
        lines = ["", "### Thematic Clusters (Cross-Stock Connections):"]
        for cluster in self._stock_clusters:
            syms = ", ".join(cluster["symbols"])
            lines.append(f"- **{cluster['theme']}** [{syms}]: {cluster['rationale']}")
            if cluster.get("performance"):
                avg = cluster.get("cluster_avg_return", 0)
                lines.append(f"  Cluster avg 20d return: {avg:+.1f}%")
                for p in cluster["performance"]:
                    flag = f"  {p['flag']}" if p.get("flag") else ""
                    lines.append(
                        f"    {p['symbol']}: {p['return_20d']:+.1f}% "
                        f"(vs cluster: {p['vs_cluster_avg']:+.1f}%){flag}"
                    )
        return lines

    @staticmethod
    def _enforce_portfolio_action_rules(
        insights: list[dict[str, Any]],
        portfolio_holdings: dict[str, dict[str, float]] | None,
    ) -> list[dict[str, Any]]:
        """Enforce portfolio-aware action rules.

        - SELL/STRONG_SELL on non-held stocks → AVOID
        - HOLD/BUY_MORE on non-held stocks → WATCH/BUY respectively

        Args:
            insights: Parsed insight dicts from synthesis.
            portfolio_holdings: Dict of {symbol: {shares, total_cost}} or None.

        Returns:
            The same list with actions corrected in-place.
        """
        if not insights:
            return insights
        held_symbols = set((portfolio_holdings or {}).keys())
        for insight in insights:
            action = insight.get("action", "")
            symbol = insight.get("primary_symbol", "")
            if not symbol or symbol.upper() in held_symbols:
                continue
            if action in ("SELL", "STRONG_SELL"):
                logger.info(
                    f"[AUTO] Converting {action} → AVOID for {symbol} (not in portfolio)"
                )
                insight["action"] = "AVOID"
            elif action == "HOLD":
                logger.info(
                    f"[AUTO] Converting HOLD → WATCH for {symbol} (not in portfolio)"
                )
                insight["action"] = "WATCH"
            elif action == "BUY_MORE":
                logger.info(
                    f"[AUTO] Converting BUY_MORE → BUY for {symbol} (not in portfolio)"
                )
                insight["action"] = "BUY"
        return insights

    @staticmethod
    def _dedupe_insights(insights: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Collapse insights that share a primary symbol.

        The synthesis LLM occasionally anchors two insights on the same
        ticker (e.g. a single-stock thesis plus a basket framed around the
        same name). Keep the higher-confidence insight per symbol and merge
        the dropped insight's related symbols into the survivor so no
        coverage is lost. Insights without a primary symbol (theme/basket
        insights) are never collapsed.

        Args:
            insights: Parsed insight dicts from synthesis.

        Returns:
            Insights with at most one entry per primary symbol, original
            order preserved.
        """
        if not insights:
            return insights
        kept_by_symbol: dict[str, dict[str, Any]] = {}
        result: list[dict[str, Any]] = []
        for insight in insights:
            symbol = (insight.get("primary_symbol") or "").strip().upper()
            if not symbol:
                result.append(insight)
                continue
            existing = kept_by_symbol.get(symbol)
            if existing is None:
                kept_by_symbol[symbol] = insight
                result.append(insight)
                continue
            existing_conf = float(existing.get("confidence") or 0)
            new_conf = float(insight.get("confidence") or 0)
            keep, drop = (
                (existing, insight) if existing_conf >= new_conf else (insight, existing)
            )
            if keep is not existing:
                result[result.index(existing)] = keep
                kept_by_symbol[symbol] = keep
            # Merge related symbols from the dropped insight (deduped,
            # order-preserving, excluding the primary itself).
            keep["related_symbols"] = list(dict.fromkeys(
                [s for s in (keep.get("related_symbols") or []) if s]
                + [
                    s for s in (drop.get("related_symbols") or [])
                    if s and s.strip().upper() != symbol
                ]
            ))
            logger.info(
                f"[AUTO] Dropping duplicate insight for {symbol}: "
                f"'{str(drop.get('title', ''))[:60]}' (conf {drop.get('confidence')}) "
                f"in favor of '{str(keep.get('title', ''))[:60]}' (conf {keep.get('confidence')})"
            )
        return result

    def _build_heatmap_discovery_context(
        self,
        macro_result: MacroScanResult,
        heatmap_analysis: HeatmapAnalysis,
        factor_scores: dict[str, Any] | None = None,
        thematic_result: ThematicAnalysisResult | None = None,
        stock_descriptions: dict[str, str] | None = None,
    ) -> str:
        """Build discovery context for deep dive analysts using heatmap data.

        Args:
            macro_result: Results from macro scan.
            heatmap_analysis: Results from heatmap analysis.
            factor_scores: Optional dict of symbol -> FactorScore from factor model.
            thematic_result: Optional thematic analysis result for downstream context.

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

        # Append factor score summary if available
        if factor_scores:
            lines.extend(["", "### Factor Model Scores (Top 10 by Composite):"])
            sorted_scores = sorted(
                factor_scores.values(),
                key=lambda fs: getattr(fs, "composite_score", 0),
                reverse=True,
            )
            for fs in sorted_scores[:10]:
                lines.append(
                    f"- {fs.symbol}: Composite={fs.composite_score:.1f} "
                    f"(Mom={fs.momentum_score:.0f} Vol={fs.volatility_score:.0f} "
                    f"Tech={fs.technical_score:.0f})"
                )

        if thematic_result:
            lines.append("")
            lines.append(format_thematic_for_downstream(thematic_result))

        if stock_descriptions:
            lines.extend(["", "### Stock Thematic Profiles:"])
            for sym, desc in stock_descriptions.items():
                lines.append(f"- {sym}: {desc}")

        lines.extend(self._render_cluster_context())

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
    ) -> tuple[list[dict[str, Any]], str]:
        """Run Phase 5: Synthesis Lead with heatmap context.

        Args:
            analyst_reports: Reports from all analysts per symbol.
            macro_context: Macro scan results.
            heatmap_analysis: Heatmap analysis results.
            max_insights: Maximum insights to generate.
            portfolio_holdings: Optional dict of user portfolio holdings.

        Returns:
            Tuple of (list of insight dictionaries, raw LLM response).
        """
        # Build enhanced synthesis context
        async with async_session_factory() as session:
            memory_service = InstitutionalMemoryService(session)

            # Get patterns and track record
            symbols = list(analyst_reports.keys())[:10]
            current_conditions = self._extract_conditions_from_analyst_reports(analyst_reports)
            patterns = await memory_service.get_relevant_patterns(
                symbols=symbols,
                current_conditions=current_conditions,
            )
            track_record = await memory_service.get_insight_track_record()

        pattern_context_str = build_pattern_context(patterns)
        track_record_str = build_track_record_context(track_record)

        # Fetch catalyst/earnings context for analyzed symbols
        catalyst_context_str: str | None = None
        try:
            from analysis.catalyst_tracker import get_catalyst_tracker  # type: ignore[import-not-found]

            catalyst_tracker = get_catalyst_tracker()
            catalyst_context_str = await catalyst_tracker.build_catalyst_context(
                symbols, days_ahead=30
            )
            if catalyst_context_str:
                logger.info(f"[AUTO] Catalyst context built for {len(symbols)} symbols")
        except Exception as cat_err:
            logger.warning(f"[AUTO] Catalyst context fetch failed (non-fatal): {cat_err}")

        # Build enhanced synthesis prompt
        enhanced_prompt = format_synthesis_prompt_with_context(
            pattern_context=pattern_context_str,
            track_record_context=track_record_str,
            catalyst_context=catalyst_context_str,
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

        # Build thematic and investor context if available
        thematic_context = ""
        if getattr(self, '_thematic_result', None):
            thematic_context = "\n\n" + format_thematic_for_downstream(self._thematic_result)

        investor_context = ""
        if getattr(self, '_investor_result', None):
            investor_context = "\n\n" + format_investor_for_synthesis(self._investor_result)

        # Format analyst reports for synthesis
        synthesis_context = format_synthesis_context(
            self._flatten_analyst_reports(analyst_reports)
        )

        quant_context_block = ""
        if getattr(self, '_quant_context', None):
            quant_context_block = (
                f"\n\n## IC-Calibrated Quant Signals\n"
                f"Stocks flagged by bottom-up quant scorer (IC-calibrated, 400-symbol universe). "
                f"Convergence between quant signals and thematic/heatmap discovery = highest conviction.\n"
                f"{self._quant_context}"
            )

        # News + social-sentiment augmentation (per-symbol news for the
        # deep-dive candidates + the Phase-1 Reddit sentiment capture).
        news_sentiment_context = await self._build_news_and_sentiment_context(symbols)

        full_context = (
            f"{autonomous_context}{portfolio_context}{thematic_context}"
            f"{investor_context}{quant_context_block}{news_sentiment_context}"
            f"\n\n{synthesis_context}"
        )

        # Query LLM
        response = await self._query_llm(enhanced_prompt, full_context, "synthesis", "synthesis")

        try:
            insights = parse_synthesis_response(response)
            if not insights:
                logger.warning(
                    "[AUTO] Synthesis returned 0 insights. Response preview (first 1000 chars): %s",
                    response[:1000]
                )
                self._dump_synthesis_debug(response)
        except Exception as parse_err:
            logger.error(f"[AUTO] Failed to parse synthesis response: {parse_err} | preview: {response[:1000]}")
            self._dump_synthesis_debug(response)
            insights = []

        insights = self._dedupe_insights(insights)
        insights = self._enforce_portfolio_action_rules(insights, portfolio_holdings)

        # Adjust confidence based on historical track record
        try:
            async with async_session_factory() as adj_session:
                memory_service_adj = InstitutionalMemoryService(adj_session)
                adjuster = ConfidenceAdjuster(adj_session, memory_service_adj)
                for insight_dict in insights:
                    try:
                        result = await adjuster.adjust_confidence(
                            base_confidence=float(insight_dict.get("confidence", 0.5)),
                            insight_type=insight_dict.get("insight_type", "opportunity"),
                            action_type=insight_dict.get("action", "HOLD"),
                            symbols=[insight_dict["primary_symbol"]] if insight_dict.get("primary_symbol") else None,
                        )
                        old_conf = insight_dict.get("confidence", 0.5)
                        insight_dict["confidence"] = result["adjusted_confidence"]
                        if result["adjusted_confidence"] != old_conf:
                            logger.info(
                                f"[AUTO] Confidence adjusted for {insight_dict.get('primary_symbol')}: "
                                f"{old_conf:.2f} -> {result['adjusted_confidence']:.2f}"
                            )
                    except Exception as adj_err:
                        logger.warning(f"[AUTO] Confidence adjustment failed: {adj_err}")
        except Exception as e:
            logger.warning(f"[AUTO] Confidence adjustment phase failed: {e}")

        return insights, response

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

        # Include thematic descriptions if available
        if self._stock_descriptions:
            lines.extend(["", "### Stock Thematic Profiles:"])
            for sym, desc in self._stock_descriptions.items():
                lines.append(f"- {sym}: {desc}")

        lines.extend(self._render_cluster_context())

        if self._cluster_analyses:
            lines.extend(["", "### Cluster-Level Analysis (Phase 4.7):"])
            for ca in self._cluster_analyses:
                analysis = ca.get("analysis", {})
                lines.append(f"\n**{ca['theme']}** [{', '.join(ca['symbols'])}]:")
                if analysis.get("cluster_thesis"):
                    lines.append(f"  Thesis: {analysis['cluster_thesis']}")
                if analysis.get("laggard_assessment"):
                    lines.append(f"  Laggard Assessment: {analysis['laggard_assessment']}")
                if analysis.get("catalyst_strength"):
                    lines.append(f"  Catalyst Strength: {analysis['catalyst_strength']}")
                if analysis.get("concentration_risk"):
                    lines.append(f"  Concentration Risk: {analysis['concentration_risk']}")
                if analysis.get("trade_opportunity"):
                    lines.append(f"  Trade Opportunity: {analysis['trade_opportunity']}")
                if analysis.get("conviction"):
                    lines.append(f"  Conviction: {analysis['conviction']}")

        lines.extend([
            "",
            f"Symbols Analyzed: {', '.join(analyst_reports.keys())}",
            "",
            f"### Target: Generate {max_insights} actionable insights",
            "Prioritize opportunities with:",
            "- Strong macro/heatmap alignment",
            "- Thematic connections between stocks",
            "- Pattern confirmation from deep dive",
            "- Multiple analyst agreement",
            "- Clear risk/reward profiles",
            "",
            "CRITICAL: Respond with ONLY the JSON object as specified in the system instructions. "
            "No prose, no commentary, no markdown code fences, no // comments inside JSON values. "
            "Start your response with { and end with }.",
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

    def _create_research_context(
        self,
        insight: DeepInsight,
        analyst_reports: dict[str, dict[str, Any]],
        macro_result: MacroScanResult,
        synthesis_raw_response: str | None = None,
        total_insights_count: int = 0,
        pre_context: dict[str, Any] | None = None,
        heatmap_analysis: HeatmapAnalysis | None = None,
        sector_result: SectorRotationResult | None = None,
    ) -> InsightResearchContext:
        """Create an InsightResearchContext for an autonomous engine insight.

        Maps the per-symbol analyst report structure to the flat schema
        expected by InsightResearchContext, using the insight's primary_symbol
        to select the relevant reports.

        Args:
            insight: The parent DeepInsight.
            analyst_reports: Per-symbol analyst reports dict.
            macro_result: Global macro scan results.
            synthesis_raw_response: Raw LLM synthesis response text.
            total_insights_count: Total insights generated in this run.
            pre_context: Market context dict (heatmap pipeline).
            heatmap_analysis: Heatmap analysis results (heatmap pipeline).
            sector_result: Sector rotation results (legacy pipeline).

        Returns:
            InsightResearchContext model instance.
        """
        symbol = insight.primary_symbol
        symbol_reports = analyst_reports.get(symbol, {}) if symbol else {}

        def clean_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
            if not report or "error" in report:
                return None
            return {k: v for k, v in report.items() if not k.startswith("_")}

        # Extract per-symbol analyst reports
        technical_report = clean_report(symbol_reports.get("technical"))
        sector_report = clean_report(symbol_reports.get("sector"))
        risk_report = clean_report(symbol_reports.get("risk"))

        # Macro is global in autonomous engine
        macro_report = macro_result.to_dict() if macro_result else None

        # Correlation not run in autonomous pipeline
        correlation_report = None

        # Market context snapshots from pre_context (heatmap pipeline)
        market_summary_snapshot = pre_context.get("market_summary") if pre_context else None
        sector_performance_snapshot = pre_context.get("sector_performance") if pre_context else None
        economic_indicators_snapshot = pre_context.get("economic_indicators") if pre_context else None

        # Build synthesis summary
        analyst_names: set[str] = set()
        for sym_reports in analyst_reports.values():
            if isinstance(sym_reports, dict):
                for name, report in sym_reports.items():
                    if isinstance(report, dict) and "error" not in report:
                        analyst_names.add(name)
        synthesis_summary: dict[str, Any] = {
            "insight_count": total_insights_count,
            "analysts_included": sorted(analyst_names),
            "pipeline": "heatmap" if heatmap_analysis else "legacy",
        }

        # Build condensed analysts summary
        summaries: list[str] = []
        if technical_report:
            finding = technical_report.get("market_structure", "N/A")
            conf = technical_report.get("confidence", 0)
            summaries.append(f"Technical({symbol}): {finding} (conf: {conf:.0%})")
        summaries.append(f"Macro: {macro_result.market_regime}")
        if sector_report:
            phase = sector_report.get("market_phase", "N/A")
            summaries.append(f"Sector: {phase}")
        if risk_report:
            vol_regime = risk_report.get("volatility_regime", {})
            vol_name = vol_regime.get("name", "N/A") if isinstance(vol_regime, dict) else "N/A"
            summaries.append(f"Risk: {vol_name} volatility")
        if heatmap_analysis:
            summaries.append(f"Heatmap: {heatmap_analysis.overview[:80]}")
        analysts_summary = " | ".join(summaries)[:2000]

        # Build key data points
        key_data_points: list[str] = []
        key_data_points.append(f"regime:{macro_result.market_regime}")
        if pre_context:
            market_summary = pre_context.get("market_summary", {})
            spy_data = market_summary.get("SPY", {})
            if spy_data:
                change = spy_data.get("change_percent", 0)
                key_data_points.append(f"SPY_change={change:+.2f}%")
        if technical_report:
            for finding in (technical_report.get("findings") or [])[:3]:
                if isinstance(finding, dict):
                    rsi = finding.get("rsi")
                    sym = finding.get("symbol", symbol)
                    if rsi:
                        key_data_points.append(f"RSI:{sym}={rsi:.1f}")

        # Estimate token count
        total_chars = len(str(symbol_reports)) + len(str(synthesis_raw_response or ""))
        estimated_token_count = total_chars // 4

        # Build successful analysts list
        successful_analysts = [
            f"{sym}:{analyst_name}"
            for sym, reports in analyst_reports.items()
            for analyst_name, report in (reports.items() if isinstance(reports, dict) else [])
            if isinstance(report, dict) and "error" not in report
        ]

        return InsightResearchContext(
            deep_insight=insight,
            schema_version="1.0",
            technical_report=technical_report,
            macro_report=macro_report,
            sector_report=sector_report,
            risk_report=risk_report,
            correlation_report=correlation_report,
            synthesis_raw_response=synthesis_raw_response,
            synthesis_summary=synthesis_summary,
            symbols_analyzed=list(analyst_reports.keys()),
            market_summary_snapshot=market_summary_snapshot,
            sector_performance_snapshot=sector_performance_snapshot,
            economic_indicators_snapshot=economic_indicators_snapshot,
            analysts_summary=analysts_summary,
            key_data_points=key_data_points[:20],
            estimated_token_count=estimated_token_count,
            analysis_duration_seconds=None,
            successful_analysts=successful_analysts,
            analyst_errors=None,
        )

    async def _compute_factor_scores(self, heatmap_data: HeatmapData) -> dict[str, Any]:
        """Score the heatmap universe with the six-factor model.

        Fundamentals are fetched here rather than reused from the deep-dive
        context: that context is not built until Phase 4 and covers only the
        shortlist, whereas the model ranks the whole heatmap universe. Without
        them ``value`` and ``quality`` are unmeasurable and every symbol is
        capped at 0.60 coverage. The fetch is bounded by
        ``FACTOR_FUNDAMENTALS_TIMEOUT_S`` and backed by the factor model's own
        5-min TTL cache, and degrades to market-data-only on failure.

        Args:
            heatmap_data: Fetched heatmap for this run.

        Returns:
            Dict mapping symbol -> FactorScore; empty when scoring failed.
        """
        try:
            from analysis.factor_model import get_factor_model  # type: ignore[import-not-found]

            factor_model = get_factor_model()
            heatmap_factor_data: dict[str, dict] = {
                stock.symbol: stock.to_dict() for stock in heatmap_data.stocks
            }
            if not heatmap_factor_data:
                return {}

            fundamentals: dict[str, dict] = {}
            try:
                fundamentals = await asyncio.wait_for(
                    factor_model.fetch_fundamental_data(list(heatmap_factor_data)),
                    timeout=FACTOR_FUNDAMENTALS_TIMEOUT_S,
                )
            except Exception as fund_err:
                logger.warning(
                    "[AUTO] Fundamental fetch for factor model failed (%s); "
                    "falling back to market-data-only factors", fund_err,
                )

            factor_scores = await factor_model.compute_factor_scores(
                heatmap_factor_data, fundamentals or None
            )
            mean_coverage = (
                sum(fs.coverage for fs in factor_scores.values()) / len(factor_scores)
                if factor_scores else 0.0
            )
            logger.info(
                "[AUTO] Factor scores computed for %d symbols "
                "(fundamentals for %d/%d; mean coverage %.2f)",
                len(factor_scores), len(fundamentals),
                len(heatmap_factor_data), mean_coverage,
            )
            return factor_scores
        except Exception as e:
            logger.warning(f"[AUTO] Factor model computation failed (non-fatal): {e}")
            return {}

    async def _live_price_for_gate(
        self,
        symbol: str,
        pre_context: dict[str, Any] | None,
    ) -> tuple[float | None, str]:
        """Resolve a price to sanity-check an entry zone against.

        Prefers the freshness snapshot the pipeline already built (so the gate
        judges against the same price the analysts saw) and falls back to a
        direct Yahoo quote only when no usable snapshot exists.

        Args:
            symbol: Ticker to price.
            pre_context: Pre-built market context, may carry price_freshness.

        Returns:
            ``(price, source)``. Price is None when nothing usable was found,
            in which case source explains why.
        """
        if pre_context:
            try:
                from analysis.price_freshness import (  # type: ignore[import-not-found]
                    is_usable,
                    snapshot_price,
                )

                price, freshness = snapshot_price(pre_context, symbol.upper())
                if price > 0 and is_usable(freshness):
                    source = (freshness or {}).get("source", "unknown")
                    return price, f"snapshot:{source}"
            except Exception as e:
                logger.debug("Freshness snapshot lookup failed for %s: %s", symbol, e)

        try:
            from data.adapters.yahoo import yahoo_adapter  # type: ignore[import-not-found]

            quote = await yahoo_adapter.get_current_price(symbol)
            price = float((quote or {}).get("price") or 0.0)
            if price > 0:
                return price, "yahoo_quote"
        except Exception as e:
            logger.debug("Yahoo quote failed for %s: %s", symbol, e)

        return None, "unavailable"

    async def _passes_entry_sanity_gate(
        self,
        symbol: str | None,
        entry_zone: str | None,
        pre_context: dict[str, Any] | None,
    ) -> bool:
        """True when *entry_zone* is close enough to the live price to be tradable.

        An entry more than ``MAX_ENTRY_DEVIATION_PCT`` from the market is a
        stale level, not a plan. When no price can be resolved at all the
        insight fails the gate: an entry nobody can verify is exactly what this
        gate exists to keep away from the user.

        Args:
            symbol: Primary symbol of the insight.
            entry_zone: Entry level string, e.g. "$205-215".
            pre_context: Pre-built market context for the freshness snapshot.

        Returns:
            True to keep the insight, False to drop it.
        """
        if not symbol or not entry_zone:
            # No price claim to verify. Missing levels are a separate problem.
            return True

        parsed = InsightOutcomeTracker._parse_price_range(entry_zone)
        if parsed is None:
            logger.debug(
                "Entry gate skipped for %s: no numeric level in %r", symbol, entry_zone
            )
            return True

        midpoint = (parsed[0] + parsed[1]) / 2
        if midpoint <= 0:
            logger.warning(
                "[GATE] Rejected %s: non-positive entry midpoint %.2f from %r",
                symbol, midpoint, entry_zone,
            )
            return False

        live_price, source = await self._live_price_for_gate(symbol, pre_context)
        if live_price is None:
            logger.warning(
                "[GATE] Rejected %s: entry %r (midpoint $%.2f) could not be "
                "checked against any usable price (%s)",
                symbol, entry_zone, midpoint, source,
            )
            return False

        deviation = abs(midpoint - live_price) / live_price * 100
        if deviation > MAX_ENTRY_DEVIATION_PCT:
            logger.warning(
                "[GATE] Rejected %s: entry %r (midpoint $%.2f) is %.1f%% from "
                "live price $%.2f (%s), limit %.0f%%",
                symbol, entry_zone, midpoint, deviation, live_price, source,
                MAX_ENTRY_DEVIATION_PCT,
            )
            return False

        logger.debug(
            "[GATE] %s passed: entry midpoint $%.2f is %.1f%% from $%.2f (%s)",
            symbol, midpoint, deviation, live_price, source,
        )
        return True

    async def _store_insights_from_heatmap(
        self,
        session: Any,
        insights_data: list[dict[str, Any]],
        macro_result: MacroScanResult,
        heatmap_analysis: HeatmapAnalysis,
        pre_context: dict[str, Any] | None = None,
        analyst_reports: dict[str, dict[str, Any]] | None = None,
        synthesis_raw_response: str | None = None,
    ) -> list[DeepInsight]:
        """Store insights in database with heatmap metadata.

        Args:
            session: Database session.
            insights_data: List of insight dictionaries.
            macro_result: Macro scan results for context.
            heatmap_analysis: Heatmap analysis for context.
            pre_context: Pre-built market context with rich_technical data.
            analyst_reports: Per-symbol analyst reports for research context.
            synthesis_raw_response: Raw LLM synthesis response text.

        Returns:
            List of created DeepInsight objects.
        """
        stored: list[DeepInsight] = []
        rejected = 0

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

                # Trading levels emitted by the synthesis lead. Without these
                # the insight is untradable and outcome tracking can never fire
                # entry_triggered.
                entry_zone = _level_text(data.get("entry_zone"), 50)
                target_price = _level_text(data.get("target_price"), 50)
                stop_loss = _level_text(data.get("stop_loss"), 50)
                timeframe = _level_text(data.get("timeframe"), 30)

                if not await self._passes_entry_sanity_gate(
                    primary_symbol, entry_zone, pre_context
                ):
                    rejected += 1
                    continue

                insight = DeepInsight(
                    insight_type=insight_type,
                    action=action,
                    title=data.get("title", "Untitled")[:200],
                    thesis=data.get("thesis", ""),
                    primary_symbol=primary_symbol,
                    related_symbols=data.get("related_symbols", []),
                    secondary_plays=data.get("secondary_plays"),
                    supporting_evidence=data.get("supporting_evidence", []),
                    confidence=float(data.get("confidence", 0.5)),
                    time_horizon=data.get("time_horizon", "medium_term"),
                    risk_factors=data.get("risk_factors", []),
                    invalidation_trigger=data.get("invalidation_trigger"),
                    historical_precedent=data.get("historical_precedent"),
                    analysts_involved=data.get("analysts_involved", []),
                    data_sources=data_sources,
                    entry_zone=entry_zone,
                    target_price=target_price,
                    stop_loss=stop_loss,
                    timeframe=timeframe,
                    prediction_market_data=getattr(self, '_prediction_data', None) or None,
                    sentiment_data=getattr(self, '_sentiment_data', None) or None,
                    technical_analysis_data=self._extract_ta_for_symbol(primary_symbol, pre_context) if pre_context and primary_symbol else None,
                )
                # Persist news sentiment slice (column added by a peer agent).
                self._set_insight_news_data(insight, primary_symbol)

                session.add(insight)

                # Create and attach research context
                if analyst_reports:
                    try:
                        research_ctx = self._create_research_context(
                            insight=insight,
                            analyst_reports=analyst_reports,
                            macro_result=macro_result,
                            synthesis_raw_response=synthesis_raw_response,
                            total_insights_count=len(insights_data),
                            pre_context=pre_context,
                            heatmap_analysis=heatmap_analysis,
                        )
                        session.add(research_ctx)
                    except Exception as rc_err:
                        logger.warning(
                            f"[AUTO] Research context creation failed for "
                            f"{data.get('primary_symbol')}: {rc_err}"
                        )

                stored.append(insight)

            except Exception as e:
                logger.error(f"Failed to create insight: {e}")
                continue

        if rejected:
            logger.warning(
                "[GATE] Dropped %d/%d insights whose entry zone failed the "
                "price sanity gate",
                rejected, len(insights_data),
            )

        if stored:
            try:
                await session.commit()
                logger.info(f"Stored {len(stored)} insights to database")
            except Exception as commit_err:
                logger.error(f"DB commit failed for {len(stored)} insights: {commit_err}")
                await session.rollback()
                self._dump_synthesis_debug(
                    f"COMMIT_ERROR: {commit_err}\n\nInsights data:\n{json.dumps(insights_data, indent=2, default=str)}"
                )
                return []

            # Fire-and-forget pattern extraction in background (uses LLM calls
            # per insight, so running in background avoids blocking the pipeline).
            # Uses a separate DB session since the current session may close.
            _stored_dicts = [
                {
                    "id": ins.id,
                    "title": ins.title,
                    "insight_type": ins.insight_type,
                    "action": ins.action,
                    "thesis": ins.thesis,
                    "confidence": ins.confidence,
                    "time_horizon": ins.time_horizon,
                    "primary_symbol": ins.primary_symbol,
                    "risk_factors": ins.risk_factors or [],
                    "related_symbols": ins.related_symbols or [],
                    "sector": (ins.discovery_context or {}).get("sector"),
                }
                for ins in stored
            ]

            async def _background_pattern_extraction(
                insight_dicts: list[dict],
            ) -> None:
                """Extract patterns in a background task with its own DB session."""
                try:
                    async with async_session_factory() as bg_session:
                        extractor = PatternExtractor(bg_session)
                        for d in insight_dicts:
                            try:
                                await extractor.extract_from_insight(d)
                                logger.info(f"[AUTO-BG] Pattern extraction completed for {d.get('primary_symbol')}")
                            except Exception as pe:
                                logger.error(f"[AUTO-BG] Pattern extraction failed for {d.get('primary_symbol')}: {pe}")
                        await bg_session.commit()
                    logger.info(f"[AUTO-BG] Background pattern extraction finished for {len(insight_dicts)} insights")
                except Exception as e:
                    logger.error(f"[AUTO-BG] Background pattern extraction failed: {e}", exc_info=True)

            asyncio.create_task(_background_pattern_extraction(_stored_dicts))
            logger.info(f"[AUTO] Pattern extraction dispatched to background for {len(stored)} insights")

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

            # Merge top portfolio holdings into deep dive list (max 3 extra)
            if portfolio_holdings:
                existing_symbols = set(symbols_to_analyze)
                sorted_holdings = sorted(
                    [(sym, info) for sym, info in portfolio_holdings.items()
                     if sym not in existing_symbols],
                    key=lambda x: x[1].get("total_cost", 0),
                    reverse=True,
                )
                portfolio_additions = [sym for sym, _ in sorted_holdings[:3]]
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

            # Build the market context once for every candidate, as the heatmap
            # pipeline does.  It carries the reconciled price_freshness records,
            # so the entry-sanity gate in _store_insights can price against the
            # same snapshot the analysts were shown instead of firing one serial
            # live Yahoo quote per insight inside the DB store loop.  A failure
            # here is non-fatal: the analysts fall back to their own per-symbol
            # builds and the gate falls back to a live quote, which is exactly
            # the previous behaviour.
            # An empty symbol list would make build_context fetch the whole
            # active universe, so only build when there is something to analyse.
            legacy_context: dict[str, Any] | None = None
            if symbols_to_analyze:
                try:
                    legacy_context = await self.context_builder.build_context(
                        symbols=symbols_to_analyze,
                        include_price_history=True,
                        include_technical=True,
                        include_economic=True,
                        include_sectors=True,
                        include_rich_technical=True,
                        include_fundamentals=True,
                    )
                except Exception as ctx_err:
                    logger.warning(
                        f"[Legacy] Shared context build failed (non-fatal): {ctx_err}"
                    )

            analyst_reports: dict[str, dict[str, Any]] = {}

            async def _analyze_one(sym: str) -> tuple[str, dict[str, Any] | None]:
                try:
                    reports = await self._run_analysts_for_symbol(
                        sym, discovery_context, pre_built_context=legacy_context
                    )
                    return sym, reports
                except Exception as e:
                    logger.error(f"Deep dive failed for {sym}: {e}")
                    result.errors.append(f"Deep dive {sym}: {str(e)}")
                    return sym, None

            async def _with_timeout(coro, sym):
                try:
                    return await asyncio.wait_for(coro, timeout=self.timeout_seconds * 3)
                except asyncio.TimeoutError:
                    logger.error(f"Symbol {sym} analysis timed out after {self.timeout_seconds * 3}s")
                    return asyncio.TimeoutError(f"{sym} timed out")

            gather_results = await asyncio.gather(
                *[_with_timeout(_analyze_one(sym), sym) for sym in symbols_to_analyze],
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
            insights_data, synthesis_raw_response = await self._run_synthesis(
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
                    session, insights_data, macro_result, sector_result, candidates,
                    analyst_reports=analyst_reports,
                    synthesis_raw_response=synthesis_raw_response,
                    pre_context=legacy_context,
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

        # Fetch macro-economic news so the regime call is news-aware (best-effort,
        # ~1-2s cached vs the multi-second LLM scan, so the added latency is
        # negligible). Stored on self._news_data["macro"] for persistence/display.
        macro_context: dict[str, Any] | None = None
        if self._news_sentiment_enabled():
            try:
                from analysis.news_intelligence import get_macro_news_intelligence  # type: ignore[import-not-found]

                macro_news = await get_macro_news_intelligence(days=3)
                # An unavailable feed reports article_count 0, so gating on the
                # count alone gave the scanner silence during an outage instead
                # of the "feed UNAVAILABLE" notice format_macro_news_context
                # renders.  Mirror that formatter's own unavailable test.
                macro_unavailable = bool(macro_news) and (
                    macro_news.get("data_status") == STATUS_ERROR
                    or macro_news.get("available") is False
                )
                if macro_news and (macro_news.get("article_count") or macro_unavailable):
                    macro_context = {"macro_news": macro_news}
                    # Stash on a dedicated attr — the Phase-1 gather reassigns
                    # self._news_data afterwards, so mutating it here would be
                    # clobbered. Merged back in after the prefetch assignment.
                    self._macro_news_data = macro_news
                    logger.info(
                        "Macro news: tone=%s (%s articles, %s topics)",
                        macro_news.get("label"),
                        macro_news.get("article_count"),
                        len(macro_news.get("by_topic", {})),
                    )
            except Exception as exc:  # noqa: BLE001 - macro news must never break the scan
                logger.warning("Macro news fetch failed (non-fatal): %s", exc)

        try:
            scan_result = await self.macro_scanner.scan(context=macro_context)
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

        # Fetch catalyst context for opportunity screening
        opp_catalyst_ctx: str | None = None
        try:
            from analysis.catalyst_tracker import get_catalyst_tracker  # type: ignore[import-not-found]

            catalyst_tracker = get_catalyst_tracker()
            opp_symbols = [c.get("symbol", "") for c in screened_candidates[:20] if c.get("symbol")]
            if opp_symbols:
                opp_catalyst_ctx = await catalyst_tracker.build_catalyst_context(
                    opp_symbols, days_ahead=14
                )
                if opp_catalyst_ctx:
                    logger.info(f"[AUTO] Catalyst context for opportunity hunt: {len(opp_symbols)} symbols")
        except Exception as cat_err:
            logger.warning(f"[AUTO] Opportunity catalyst fetch failed (non-fatal): {cat_err}")

        # Format context for LLM
        formatted_context = format_opportunity_context(
            macro_context_dict,
            sector_context_dict,
            screened_candidates,
            catalyst_context=opp_catalyst_ctx,
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
            shared_context = pre_built_context
        else:
            shared_context = await self.context_builder.build_context(
                symbols=[symbol],
                include_price_history=True,
                include_technical=True,
                include_economic=True,
                include_sectors=True,
                include_rich_technical=True,
                include_fundamentals=True,
            )

        # Narrow the shared context to this symbol.  The pre-built context
        # covers every deep-dive candidate and build_context() serves it from a
        # TTL cache, so this must copy rather than mutate: handing the whole
        # thing to each symbol's analysts is what made every per-symbol prompt
        # byte-identical.
        agent_context = slice_context_for_symbol(shared_context, symbol)

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

        async def _with_analyst_timeout(coro, name):
            try:
                return await asyncio.wait_for(coro, timeout=self.timeout_seconds * 2)
            except asyncio.TimeoutError:
                logger.error(f"Analyst {name} for {symbol} timed out after {self.timeout_seconds * 2}s")
                return asyncio.TimeoutError(f"{name} timed out for {symbol}")

        results = await asyncio.gather(
            *[_with_analyst_timeout(t, n) for t, n in zip(tasks, analyst_names)],
            return_exceptions=True,
        )

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

        # Format context for analyst.  Formatters that understand a target
        # render only that symbol's data; the rest (macro, correlation) are
        # market-wide by nature and take the context as-is.
        if "target_symbol" in inspect.signature(format_func).parameters:
            formatted_context = format_func(agent_context, target_symbol=symbol)
        else:
            formatted_context = format_func(agent_context)

        # State the target in-band, ahead of everything else.  It used to
        # travel only as LLM call metadata, which the model never sees.
        full_context = (
            f"{target_banner(symbol)}\n\n{discovery_context}\n\n{formatted_context}"
        )

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
    ) -> tuple[list[dict[str, Any]], str]:
        """Run Phase 5: Synthesis Lead (legacy pipeline).

        Args:
            analyst_reports: Reports from all analysts per symbol.
            macro_context: Macro scan results.
            sector_context: Sector rotation results.
            candidates: Opportunity candidates.
            max_insights: Maximum insights to generate.
            portfolio_holdings: Optional dict of user portfolio holdings.

        Returns:
            Tuple of (list of insight dictionaries, raw LLM response).
        """
        # Build enhanced synthesis context
        async with async_session_factory() as session:
            memory_service = InstitutionalMemoryService(session)

            # Get patterns and track record
            current_conditions = self._extract_conditions_from_analyst_reports(analyst_reports)
            patterns = await memory_service.get_relevant_patterns(
                symbols=[c.symbol for c in candidates.candidates[:10]],
                current_conditions=current_conditions,
            )
            track_record = await memory_service.get_insight_track_record()

        pattern_context_str = build_pattern_context(patterns)
        track_record_str = build_track_record_context(track_record)

        # Fetch catalyst/earnings context for legacy pipeline symbols
        legacy_catalyst_str: str | None = None
        try:
            from analysis.catalyst_tracker import get_catalyst_tracker  # type: ignore[import-not-found]

            catalyst_tracker = get_catalyst_tracker()
            legacy_symbols = [c.symbol for c in candidates.candidates[:10]]
            legacy_catalyst_str = await catalyst_tracker.build_catalyst_context(
                legacy_symbols, days_ahead=30
            )
            if legacy_catalyst_str:
                logger.info(f"[AUTO] Legacy catalyst context built for {len(legacy_symbols)} symbols")
        except Exception as cat_err:
            logger.warning(f"[AUTO] Legacy catalyst context fetch failed (non-fatal): {cat_err}")

        # Build enhanced synthesis prompt
        enhanced_prompt = format_synthesis_prompt_with_context(
            pattern_context=pattern_context_str,
            track_record_context=track_record_str,
            catalyst_context=legacy_catalyst_str,
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

        # News + social-sentiment augmentation (per-symbol news for the
        # candidate symbols + the Phase-1 Reddit sentiment capture).
        legacy_candidate_symbols = [c.symbol for c in candidates.candidates[:10]]
        news_sentiment_context = await self._build_news_and_sentiment_context(
            legacy_candidate_symbols
        )

        full_context = (
            f"{autonomous_context}{portfolio_context}"
            f"{news_sentiment_context}\n\n{synthesis_context}"
        )

        # Query LLM
        response = await self._query_llm(enhanced_prompt, full_context, "synthesis", "synthesis")

        try:
            insights = parse_synthesis_response(response)
            if not insights:
                logger.warning(
                    "[AUTO] Synthesis returned 0 insights. Response preview (first 1000 chars): %s",
                    response[:1000]
                )
                self._dump_synthesis_debug(response)
        except Exception as parse_err:
            logger.error(f"[AUTO] Failed to parse synthesis response: {parse_err} | preview: {response[:1000]}")
            self._dump_synthesis_debug(response)
            insights = []

        insights = self._dedupe_insights(insights)
        insights = self._enforce_portfolio_action_rules(insights, portfolio_holdings)

        # Adjust confidence based on historical track record
        try:
            async with async_session_factory() as adj_session:
                memory_service_adj = InstitutionalMemoryService(adj_session)
                adjuster = ConfidenceAdjuster(adj_session, memory_service_adj)
                for insight_dict in insights:
                    try:
                        result = await adjuster.adjust_confidence(
                            base_confidence=float(insight_dict.get("confidence", 0.5)),
                            insight_type=insight_dict.get("insight_type", "opportunity"),
                            action_type=insight_dict.get("action", "HOLD"),
                            symbols=[insight_dict["primary_symbol"]] if insight_dict.get("primary_symbol") else None,
                        )
                        old_conf = insight_dict.get("confidence", 0.5)
                        insight_dict["confidence"] = result["adjusted_confidence"]
                        if result["adjusted_confidence"] != old_conf:
                            logger.info(
                                f"[AUTO] Confidence adjusted for {insight_dict.get('primary_symbol')}: "
                                f"{old_conf:.2f} -> {result['adjusted_confidence']:.2f}"
                            )
                    except Exception as adj_err:
                        logger.warning(f"[AUTO] Confidence adjustment failed: {adj_err}")
        except Exception as e:
            logger.warning(f"[AUTO] Confidence adjustment phase failed: {e}")

        return insights, response

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

    def _extract_conditions_from_analyst_reports(
        self,
        analyst_reports: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Extract current market conditions from analyst reports for pattern matching.

        Pulls measurable indicators like RSI, VIX, and volume data from
        the per-symbol analyst reports to enable pattern matching.

        Args:
            analyst_reports: Dictionary mapping symbols to their analyst report dicts.

        Returns:
            Dictionary of current conditions (rsi, vix, volume_surge_pct, etc.).
        """
        conditions: dict[str, Any] = {}

        for symbol, reports in analyst_reports.items():
            if not isinstance(reports, dict):
                continue

            # Extract RSI from technical report
            tech = reports.get("technical", {})
            if isinstance(tech, dict) and "error" not in tech:
                findings = tech.get("findings", [])
                for finding in findings if isinstance(findings, list) else []:
                    if isinstance(finding, dict):
                        rsi = finding.get("rsi")
                        if rsi is not None and "rsi" not in conditions:
                            conditions["rsi"] = rsi

            # Extract VIX from risk report
            risk = reports.get("risk", {})
            if isinstance(risk, dict) and "error" not in risk:
                vol_regime = risk.get("volatility_regime", {})
                if isinstance(vol_regime, dict):
                    vix = vol_regime.get("vix") or vol_regime.get("current_vix")
                    if vix is not None and "vix" not in conditions:
                        conditions["vix"] = vix

            # Extract volume data from technical report
            if isinstance(tech, dict) and "error" not in tech:
                for finding in tech.get("findings", []) if isinstance(tech.get("findings"), list) else []:
                    if isinstance(finding, dict):
                        vol = finding.get("volume_surge_pct") or finding.get("volume_ratio")
                        if vol is not None and "volume_surge_pct" not in conditions:
                            conditions["volume_surge_pct"] = vol

        if conditions:
            logger.info(f"[AUTO] Extracted conditions from analyst reports: {conditions}")

        return conditions

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
        analyst_reports: dict[str, dict[str, Any]] | None = None,
        synthesis_raw_response: str | None = None,
        pre_context: dict[str, Any] | None = None,
    ) -> list[DeepInsight]:
        """Store insights in database (legacy pipeline).

        Args:
            session: Database session.
            insights_data: List of insight dictionaries.
            macro_result: Macro scan results for context.
            sector_result: Sector rotation results for context.
            candidates: Opportunity candidates for context.
            analyst_reports: Per-symbol analyst reports for research context.
            synthesis_raw_response: Raw LLM synthesis response text.
            pre_context: Market context built for the deep dive. Supplies the
                reconciled price snapshot the entry gate checks against, so the
                store loop does not fire a live quote per insight.

        Returns:
            List of created DeepInsight objects.
        """
        stored: list[DeepInsight] = []
        rejected = 0

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

                # Trading levels emitted by the synthesis lead. The gate prices
                # against the deep dive's own freshness snapshot when the caller
                # supplied one, and only falls back to a live quote otherwise.
                entry_zone = _level_text(data.get("entry_zone"), 50)
                target_price = _level_text(data.get("target_price"), 50)
                stop_loss = _level_text(data.get("stop_loss"), 50)
                timeframe = _level_text(data.get("timeframe"), 30)

                if not await self._passes_entry_sanity_gate(
                    data.get("primary_symbol"), entry_zone, pre_context
                ):
                    rejected += 1
                    continue

                insight = DeepInsight(
                    insight_type=insight_type,
                    action=action,
                    title=data.get("title", "Untitled")[:200],
                    thesis=data.get("thesis", ""),
                    primary_symbol=data.get("primary_symbol"),
                    related_symbols=data.get("related_symbols", []),
                    secondary_plays=data.get("secondary_plays"),
                    supporting_evidence=data.get("supporting_evidence", []),
                    confidence=float(data.get("confidence", 0.5)),
                    time_horizon=data.get("time_horizon", "medium_term"),
                    risk_factors=data.get("risk_factors", []),
                    invalidation_trigger=data.get("invalidation_trigger"),
                    historical_precedent=data.get("historical_precedent"),
                    analysts_involved=data.get("analysts_involved", []),
                    data_sources=data_sources,
                    entry_zone=entry_zone,
                    target_price=target_price,
                    stop_loss=stop_loss,
                    timeframe=timeframe,
                    prediction_market_data=getattr(self, '_prediction_data', None) or None,
                    sentiment_data=getattr(self, '_sentiment_data', None) or None,
                    # The legacy pipeline does not persist a TA payload; the
                    # context is threaded in for the entry gate only.
                    technical_analysis_data=None,
                )
                # Persist news sentiment slice (column added by a peer agent).
                self._set_insight_news_data(insight, data.get("primary_symbol"))

                session.add(insight)

                # Create and attach research context
                if analyst_reports:
                    try:
                        research_ctx = self._create_research_context(
                            insight=insight,
                            analyst_reports=analyst_reports,
                            macro_result=macro_result,
                            synthesis_raw_response=synthesis_raw_response,
                            total_insights_count=len(insights_data),
                            sector_result=sector_result,
                        )
                        session.add(research_ctx)
                    except Exception as rc_err:
                        logger.warning(
                            f"[AUTO] Research context creation failed for "
                            f"{data.get('primary_symbol')}: {rc_err}"
                        )

                stored.append(insight)

            except Exception as e:
                logger.error(f"Failed to create insight: {e}")
                continue

        if rejected:
            logger.warning(
                "[GATE] Dropped %d/%d legacy insights whose entry zone failed "
                "the price sanity gate",
                rejected, len(insights_data),
            )

        if stored:
            try:
                await session.commit()
                logger.info(f"Stored {len(stored)} insights to database")
            except Exception as commit_err:
                logger.error(f"DB commit failed for {len(stored)} insights (legacy): {commit_err}")
                await session.rollback()
                self._dump_synthesis_debug(
                    f"COMMIT_ERROR_LEGACY: {commit_err}\n\nInsights data:\n{json.dumps(insights_data, indent=2, default=str)}"
                )
                return []

            # Fire-and-forget pattern extraction in background (same as heatmap pipeline)
            _stored_dicts_legacy = [
                {
                    "id": ins.id,
                    "title": ins.title,
                    "insight_type": ins.insight_type,
                    "action": ins.action,
                    "thesis": ins.thesis,
                    "confidence": ins.confidence,
                    "time_horizon": ins.time_horizon,
                    "primary_symbol": ins.primary_symbol,
                    "risk_factors": ins.risk_factors or [],
                    "related_symbols": ins.related_symbols or [],
                    "sector": (ins.discovery_context or {}).get("sector"),
                }
                for ins in stored
            ]

            async def _background_pattern_extraction_legacy(
                insight_dicts: list[dict],
            ) -> None:
                try:
                    async with async_session_factory() as bg_session:
                        extractor = PatternExtractor(bg_session)
                        for d in insight_dicts:
                            try:
                                await extractor.extract_from_insight(d)
                                logger.info(f"[AUTO-BG] Pattern extraction completed for {d.get('primary_symbol')}")
                            except Exception as pe:
                                logger.error(f"[AUTO-BG] Pattern extraction failed for {d.get('primary_symbol')}: {pe}")
                        await bg_session.commit()
                except Exception as e:
                    logger.error(f"[AUTO-BG] Legacy pattern extraction failed: {e}", exc_info=True)

            asyncio.create_task(_background_pattern_extraction_legacy(_stored_dicts_legacy))
            logger.info(f"[AUTO] Pattern extraction dispatched to background for {len(stored)} legacy insights")

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
