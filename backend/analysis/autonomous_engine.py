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
import logging
from dataclasses import dataclass, field
from datetime import datetime
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
from llm.client_pool import pool_query_llm  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)


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
    errors: list[str] = field(default_factory=list)

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
            "errors": self.errors,
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

        # Phase 1: Macro Scanner
        self.macro_scanner = MacroScanner()

        self._last_analysis_time: datetime | None = None

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

        logger.info(f"Starting autonomous analysis {analysis_id}")

        try:
            # ===== PHASE 1 + PHASE 2: Macro Scan & Heatmap Fetch (concurrent) =====
            # These two phases are independent -- only Phase 3 (HeatmapAnalysis)
            # needs both results.  Running them concurrently saves wall-clock time.
            logger.info("Phase 1+2: Scanning macro environment & fetching heatmap concurrently...")
            await self._update_task_progress(task_id, "macro_scan", 10, "Scanning macro environment & fetching heatmap...")

            macro_coro = self._run_macro_scan()
            heatmap_coro = self._run_heatmap_fetch()
            phase1_result, phase2_result = await asyncio.gather(
                macro_coro, heatmap_coro, return_exceptions=True
            )

            # --- Handle Phase 1 (macro scan) result ---
            if isinstance(phase1_result, BaseException):
                raise phase1_result  # Macro scan is required; propagate failure
            macro_result: MacroScanResult = phase1_result
            result.macro_result = macro_result
            result.phases_completed.append("macro_scan")
            logger.info(f"Macro scan complete. Regime: {macro_result.market_regime}")

            # --- Handle Phase 2 (heatmap fetch) result ---
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

        logger.info(
            f"Autonomous analysis complete in {result.elapsed_seconds:.1f}s. "
            f"Generated {len(result.insights)} insights."
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

        # ===== PHASE 3: Heatmap Analysis =====
        logger.info("Phase 3: Analyzing heatmap patterns...")
        await self._update_task_progress(task_id, "heatmap_analysis", 35, "Analyzing heatmap patterns...")
        heatmap_analysis_result = await self._run_heatmap_analysis(
            heatmap_data, macro_result
        )
        result.heatmap_analysis = heatmap_analysis_result
        result.phases_completed.append("heatmap_analysis")
        logger.info(
            f"Heatmap analysis complete. Selected {len(heatmap_analysis_result.selected_stocks)} stocks"
        )

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

        logger.info(f"Phase 4: Deep diving into {symbols_to_analyze}...")
        await self._update_task_progress(
            task_id, "deep_dive", 55,
            f"Analyzing {len(symbols_to_analyze)} candidates..."
        )

        # Build discovery context using macro result and heatmap analysis
        discovery_context = self._build_heatmap_discovery_context(
            macro_result, heatmap_analysis_result
        )

        # Run all symbols concurrently (semaphore gates actual LLM calls)
        analyst_reports: dict[str, dict[str, Any]] = {}

        async def _analyze_symbol(sym: str) -> tuple[str, dict[str, Any]]:
            reports = await self._run_analysts_for_symbol(sym, discovery_context)
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
        await self._update_task_progress(task_id, "deep_dive", 70, "Deep analysis complete")

        # ===== PHASE 4.5: Coverage Evaluation (adaptive loop) =====
        logger.info("Phase 4.5: Evaluating coverage...")
        await self._update_task_progress(
            task_id, "coverage_evaluation", 75, "Evaluating coverage..."
        )

        analyst_reports = await self._run_coverage_loop(
            analyst_reports=analyst_reports,
            heatmap_data=heatmap_data,
            macro_result=macro_result,
            discovery_context=discovery_context,
            task_id=task_id,
        )
        result.analyst_reports = analyst_reports
        result.phases_completed.append("coverage_evaluation")

        # ===== PHASE 5: Synthesis =====
        logger.info("Phase 5: Synthesizing insights...")
        await self._update_task_progress(task_id, "synthesis", 90, "Synthesizing insights...")
        insights_data = await self._run_synthesis_with_heatmap(
            analyst_reports=analyst_reports,
            macro_context=macro_result,
            heatmap_analysis=heatmap_analysis_result,
            max_insights=max_insights,
        )
        result.phases_completed.append("synthesis")

        # Save insights to database
        async with async_session_factory() as session:
            saved_insights = await self._store_insights_from_heatmap(
                session,
                insights_data,
                macro_result,
                heatmap_analysis_result,
            )
            result.insights = saved_insights

        result.discovery_summary = self._build_heatmap_discovery_summary(
            macro_result, heatmap_analysis_result, heatmap_data
        )

        return result

    async def _run_heatmap_fetch(self) -> HeatmapData:
        """Run Phase 2: Heatmap Fetch.

        Returns:
            HeatmapData with sector and stock heatmap entries.
        """
        fetcher = get_heatmap_fetcher()
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
    ) -> list[dict[str, Any]]:
        """Run Phase 5: Synthesis Lead with heatmap context.

        Args:
            analyst_reports: Reports from all analysts per symbol.
            macro_context: Macro scan results.
            heatmap_analysis: Heatmap analysis results.
            max_insights: Maximum insights to generate.

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

        # Format analyst reports for synthesis
        synthesis_context = format_synthesis_context(
            self._flatten_analyst_reports(analyst_reports)
        )

        full_context = f"{autonomous_context}\n\n{synthesis_context}"

        # Query LLM
        response = await self._query_llm(enhanced_prompt, full_context, "synthesis")

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

    async def _store_insights_from_heatmap(
        self,
        session: Any,
        insights_data: list[dict[str, Any]],
        macro_result: MacroScanResult,
        heatmap_analysis: HeatmapAnalysis,
    ) -> list[DeepInsight]:
        """Store insights in database with heatmap metadata.

        Args:
            session: Database session.
            insights_data: List of insight dictionaries.
            macro_result: Macro scan results for context.
            heatmap_analysis: Heatmap analysis for context.

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
                )

                session.add(insight)
                stored.append(insight)

            except Exception as e:
                logger.error(f"Failed to create insight: {e}")
                continue

        if stored:
            await session.commit()
            logger.info(f"Stored {len(stored)} insights to database")

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
            # ===== LEGACY PHASE 2: Sector Rotation =====
            logger.info("Legacy Phase 2: Analyzing sector rotation...")
            await self._update_task_progress(task_id, "sector_rotation", 25, "Analyzing sector rotation...")
            sector_result = await self._run_sector_rotation(macro_result)
            result.sector_result = sector_result
            result.phases_completed.append("sector_rotation")

            # ===== LEGACY PHASE 3: Opportunity Hunt =====
            logger.info("Legacy Phase 3: Hunting for opportunities...")
            await self._update_task_progress(task_id, "opportunity_hunt", 45, "Discovering opportunities...")
            candidates = await self._run_opportunity_hunt(macro_result, sector_result)
            result.candidates = candidates
            result.phases_completed.append("opportunity_hunt")

            # ===== LEGACY PHASE 4: Deep Dive =====
            top_candidates = candidates.get_top_candidates(deep_dive_count)
            symbols_to_analyze = [c.symbol for c in top_candidates]

            logger.info(f"Legacy Phase 4: Deep diving into {symbols_to_analyze}...")
            await self._update_task_progress(
                task_id, "deep_dive", 55,
                f"Analyzing {len(symbols_to_analyze)} candidates..."
            )

            discovery_context = await self._build_discovery_context(
                macro_result, sector_result
            )

            analyst_reports: dict[str, dict[str, Any]] = {}
            for symbol in symbols_to_analyze:
                try:
                    symbol_reports = await self._run_analysts_for_symbol(
                        symbol, discovery_context
                    )
                    analyst_reports[symbol] = symbol_reports
                except Exception as e:
                    logger.error(f"Deep dive failed for {symbol}: {e}")
                    result.errors.append(f"Deep dive {symbol}: {str(e)}")

            result.analyst_reports = analyst_reports
            result.phases_completed.append("deep_dive")
            await self._update_task_progress(task_id, "deep_dive", 70, "Deep analysis complete")

            # ===== LEGACY PHASE 5: Synthesis =====
            logger.info("Legacy Phase 5: Synthesizing insights...")
            await self._update_task_progress(task_id, "synthesis", 85, "Synthesizing insights...")
            insights_data = await self._run_synthesis(
                analyst_reports=analyst_reports,
                macro_context=macro_result,
                sector_context=sector_result,
                candidates=candidates,
                max_insights=max_insights,
            )
            result.phases_completed.append("synthesis")

            async with async_session_factory() as session:
                saved_insights = await self._store_insights(
                    session, insights_data, macro_result, sector_result, candidates
                )
                result.insights = saved_insights

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

        Returns:
            MacroScanResult with market regime and themes.
        """
        return await self.macro_scanner.scan()

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
        # Get all stocks in screening universe
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
        )

        return parse_opportunity_response(response)

    async def _screen_stocks(
        self,
        symbols: list[str],
    ) -> list[dict[str, Any]]:
        """Screen stocks and return candidates with data.

        Args:
            symbols: List of stock symbols to screen.

        Returns:
            List of screened candidate dictionaries.
        """
        import yfinance as yf  # type: ignore[import-not-found]

        candidates: list[dict[str, Any]] = []

        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="1mo")

                if hist.empty or len(hist) < 5:
                    continue

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
                    candidates.append(data)

            except Exception as e:
                logger.warning(f"Failed to screen {symbol}: {e}")
                continue

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
    ) -> dict[str, Any]:
        """Run all analysts for a single symbol.

        Args:
            symbol: Stock symbol to analyze.
            discovery_context: Pre-built discovery context.

        Returns:
            Dictionary mapping analyst names to their reports.
        """
        # Build symbol-specific context
        agent_context = await self.context_builder.build_context(
            symbols=[symbol],
            include_price_history=True,
            include_technical=True,
            include_economic=False,
            include_sectors=False,
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

        # Query LLM
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._query_llm(prompt, full_context, analyst_name)
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
    ) -> list[dict[str, Any]]:
        """Run Phase 5: Synthesis Lead (legacy pipeline).

        Args:
            analyst_reports: Reports from all analysts per symbol.
            macro_context: Macro scan results.
            sector_context: Sector rotation results.
            candidates: Opportunity candidates.
            max_insights: Maximum insights to generate.

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

        # Format analyst reports for synthesis
        synthesis_context = format_synthesis_context(
            self._flatten_analyst_reports(analyst_reports)
        )

        full_context = f"{autonomous_context}\n\n{synthesis_context}"

        # Query LLM
        response = await self._query_llm(enhanced_prompt, full_context, "synthesis")

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
                )

                session.add(insight)
                stored.append(insight)

            except Exception as e:
                logger.error(f"Failed to create insight: {e}")
                continue

        if stored:
            await session.commit()
            logger.info(f"Stored {len(stored)} insights to database")

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

    async def _query_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        agent_name: str = "unknown",
    ) -> str:
        """Query the LLM using the shared client pool.

        Args:
            system_prompt: System prompt for the agent.
            user_prompt: User prompt with context.
            agent_name: Name of the agent (for logging).

        Returns:
            LLM response text.
        """
        return await pool_query_llm(system_prompt, user_prompt, agent_name)

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
