"""Autonomous Deep Analysis Engine.

Orchestrates 5-phase self-guided market analysis:
1. MacroScanner - Global macro environment scan
2. SectorRotator - Sector momentum and rotation analysis
3. OpportunityHunter - Discover specific opportunities
4. Deep Dive Analysts - Detailed analysis per opportunity
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
            "candidates": self.candidates.to_dict() if self.candidates else None,
            "discovery_summary": self.discovery_summary,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "phases_completed": self.phases_completed,
            "errors": self.errors,
        }


class AutonomousDeepEngine:
    """Self-guided market analysis engine.

    Discovers opportunities autonomously without requiring user-provided symbols.
    Runs a 5-phase analysis pipeline:
    1. Macro Scan - Identify market regime and themes
    2. Sector Rotation - Find sector momentum and rotation signals
    3. Opportunity Hunt - Screen for specific stock opportunities
    4. Deep Dive - Detailed analysis by specialist analysts
    5. Synthesis - Aggregate and rank insights

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

        Executes the 5-phase autonomous analysis:
        1. Macro Scan - Global macro environment
        2. Sector Rotation - Sector momentum and rotation
        3. Opportunity Hunt - Discover specific opportunities
        4. Deep Dive - Detailed analysis per opportunity
        5. Synthesis - Rank and produce final insights

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
            # ===== PHASE 1: Macro Scan =====
            logger.info("Phase 1: Scanning macro environment...")
            await self._update_task_progress(task_id, "macro_scan", 10, "Scanning macro environment...")
            macro_result = await self._run_macro_scan()
            result.macro_result = macro_result
            result.phases_completed.append("macro_scan")
            logger.info(f"Macro scan complete. Regime: {macro_result.market_regime}")

            # ===== PHASE 2: Sector Rotation =====
            logger.info("Phase 2: Analyzing sector rotation...")
            await self._update_task_progress(task_id, "sector_rotation", 25, "Analyzing sector rotation...")
            sector_result = await self._run_sector_rotation(macro_result)
            result.sector_result = sector_result
            result.phases_completed.append("sector_rotation")
            logger.info(
                f"Sector analysis complete. Top sectors: "
                f"{[s.sector_name for s in sector_result.top_sectors]}"
            )

            # ===== PHASE 3: Opportunity Hunt =====
            logger.info("Phase 3: Hunting for opportunities...")
            await self._update_task_progress(task_id, "opportunity_hunt", 45, "Discovering opportunities...")
            candidates = await self._run_opportunity_hunt(macro_result, sector_result)
            result.candidates = candidates
            result.phases_completed.append("opportunity_hunt")
            logger.info(f"Found {len(candidates.candidates)} candidate opportunities")

            # ===== PHASE 4: Deep Dive Analysis =====
            # Take top N candidates for detailed analysis
            top_candidates = candidates.get_top_candidates(deep_dive_count)
            symbols_to_analyze = [c.symbol for c in top_candidates]

            logger.info(f"Phase 4: Deep diving into {symbols_to_analyze}...")
            await self._update_task_progress(task_id, "deep_dive", 55, f"Analyzing {len(symbols_to_analyze)} candidates...")

            # Build discovery context for analysts
            discovery_context = await self._build_discovery_context(
                macro_result, sector_result
            )

            # Run all analysts in parallel for each symbol
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

            # ===== PHASE 5: Synthesis =====
            logger.info("Phase 5: Synthesizing insights...")
            await self._update_task_progress(task_id, "synthesis", 85, "Synthesizing insights...")
            insights_data = await self._run_synthesis(
                analyst_reports=analyst_reports,
                macro_context=macro_result,
                sector_context=sector_result,
                candidates=candidates,
                max_insights=max_insights,
            )
            result.phases_completed.append("synthesis")

            # Save insights to database
            async with async_session_factory() as session:
                saved_insights = await self._store_insights(
                    session,
                    insights_data,
                    macro_result,
                    sector_result,
                    candidates,
                )
                result.insights = saved_insights

            result.discovery_summary = self._build_discovery_summary(
                macro_result, sector_result, candidates
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

                result = await session.execute(
                    select(AnalysisTask).where(AnalysisTask.id == task_id)
                )
                task = result.scalar_one_or_none()

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

    async def _run_sector_rotation(
        self,
        macro_result: MacroScanResult,
    ) -> SectorRotationResult:
        """Run Phase 2: Sector Rotation analysis.

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

    async def _run_opportunity_hunt(
        self,
        macro_result: MacroScanResult,
        sector_result: SectorRotationResult,
    ) -> OpportunityList:
        """Run Phase 3: Opportunity Hunter.

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
        """Build discovery context for deep dive analysts.

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

        for analyst_name, result in zip(analyst_names, results):
            if isinstance(result, Exception):
                logger.warning(f"{analyst_name} failed for {symbol}: {result}")
                reports[analyst_name] = {"error": str(result)}
            else:
                reports[analyst_name] = result

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
        """Run Phase 5: Synthesis Lead.

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
        """Build additional context for autonomous synthesis.

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
        """Store insights in database.

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
        """Build human-readable summary of the discovery process.

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
        agent_name: str,
    ) -> str:
        """Query the LLM using ClaudeSDKClient.

        Args:
            system_prompt: System prompt for the agent.
            user_prompt: User prompt with context.
            agent_name: Name of the agent (for logging).

        Returns:
            LLM response text.
        """
        try:
            from claude_agent_sdk import (  # type: ignore[import-not-found]
                ClaudeAgentOptions,
                ClaudeSDKClient,
                AssistantMessage,
                TextBlock,
            )

            logger.info(f"[AUTO] Querying {agent_name}, prompt length: {len(user_prompt)} chars")

            response_text = ""

            options = ClaudeAgentOptions(system_prompt=system_prompt)

            async with ClaudeSDKClient(options=options) as client:
                await client.query(user_prompt)

                async for msg in client.receive_response():
                    if isinstance(msg, AssistantMessage):
                        for block in msg.content:
                            if isinstance(block, TextBlock):
                                response_text += block.text

            logger.info(f"[AUTO] {agent_name} complete: {len(response_text)} chars")
            return response_text

        except ImportError:
            logger.error("ClaudeSDKClient not available")
            raise ImportError(
                "claude_agent_sdk is required for LLM queries. "
                "Install it to use the autonomous analysis engine."
            )

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

            result = await session.execute(query)
            return list(result.scalars().all())

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
