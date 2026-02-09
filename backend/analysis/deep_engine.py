"""Deep Analysis Engine - Orchestrates parallel multi-agent market analysis.

This module provides the DeepAnalysisEngine class that:
1. Spawns 5 specialist analyst agents in parallel using asyncio.gather()
2. Collects their findings and passes them to the Synthesis Lead
3. Generates unified DeepInsight recommendations
4. Stores insights in the database

Uses the shared client pool for LLM interactions.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from llm.client_pool import pool_query_llm

from database import async_session_factory
from models.deep_insight import DeepInsight, InsightType, InsightAction
from models.insight_research_context import InsightResearchContext

from analysis.agents.technical_analyst import (
    TECHNICAL_ANALYST_PROMPT,
    format_technical_context,
    parse_technical_response,
)
from analysis.agents.sector_strategist import (
    SECTOR_STRATEGIST_PROMPT,
    format_sector_context,
    parse_sector_response,
)
from analysis.agents.macro_economist import (
    MACRO_ECONOMIST_PROMPT,
    format_macro_context,
    parse_macro_response,
)
from analysis.agents.correlation_detective import (
    CORRELATION_DETECTIVE_PROMPT,
    format_correlation_context,
    parse_correlation_response,
)
from analysis.agents.risk_analyst import (
    RISK_ANALYST_PROMPT,
    format_risk_context,
    parse_risk_response,
)
from analysis.agents.synthesis_lead import (
    SYNTHESIS_LEAD_PROMPT,
    format_synthesis_context,
    parse_synthesis_response,
)
from analysis.context_builder import market_context_builder
from analysis.statistical_calculator import StatisticalFeatureCalculator
from analysis.memory_service import InstitutionalMemoryService
from analysis.outcome_tracker import InsightOutcomeTracker

logger = logging.getLogger(__name__)

# Valid insight types and actions for validation
VALID_INSIGHT_TYPES = {t.value for t in InsightType}
VALID_ACTIONS = {a.value for a in InsightAction}


class DeepAnalysisEngine:
    """Orchestrates multi-agent deep market analysis.

    This engine coordinates 5 specialist analyst agents running in parallel,
    then synthesizes their findings into actionable DeepInsight recommendations.

    The analysis flow:
    1. Build market context from database
    2. Run 5 analysts in parallel (technical, sector, macro, correlation, risk)
    3. Collect and format all analyst outputs
    4. Run synthesis lead to aggregate findings
    5. Parse synthesis output and store DeepInsight records

    Example:
        ```python
        engine = DeepAnalysisEngine()

        # Run full analysis
        insights = await engine.run_analysis(symbols=["AAPL", "MSFT", "NVDA"])

        # Or run analysis and store results
        stored_insights = await engine.run_and_store(symbols=["AAPL", "MSFT"])
        ```
    """

    # Analyst configurations
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

    def __init__(self, max_retries: int = 2, timeout_seconds: int = 120) -> None:
        """Initialize the deep analysis engine.

        Args:
            max_retries: Maximum retries per analyst on failure.
            timeout_seconds: Timeout for each analyst query.
        """
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self._last_analysis_time: datetime | None = None
        # Services will be initialized per-session with database context
        self._statistical_calculator: StatisticalFeatureCalculator | None = None
        self._memory_service: InstitutionalMemoryService | None = None
        self._outcome_tracker: InsightOutcomeTracker | None = None

    async def run_analysis(
        self,
        symbols: list[str] | None = None,
        include_synthesis: bool = True,
    ) -> dict[str, Any]:
        """Run full multi-agent analysis.

        Executes all 5 analyst agents in parallel, then optionally runs
        the synthesis lead to aggregate their findings.

        Args:
            symbols: Optional list of symbols to focus on. If None, uses
                all active stocks from database.
            include_synthesis: Whether to run synthesis after analysts complete.

        Returns:
            Dictionary containing:
            - analyst_reports: Dict mapping analyst names to their parsed outputs
            - synthesis: Parsed synthesis output (if include_synthesis=True)
            - insights: List of DeepInsight-compatible dicts
            - metadata: Analysis metadata (timestamp, symbols, etc.)
        """
        start_time = datetime.utcnow()
        symbol_count = len(symbols) if symbols else "all"
        logger.info(f"Starting deep analysis for {symbol_count} symbols...")

        # Step 0: Prepare enhanced context with statistical features and memory
        enhanced_context: dict[str, Any] = {}
        if symbols:
            async with async_session_factory() as session:
                enhanced_context = await self._prepare_enhanced_context(symbols, session)
            logger.info(
                f"Enhanced context prepared: {len(enhanced_context.get('matching_patterns', []))} patterns found"
            )

        # Step 1: Build market context
        logger.info("Building market context from database...")
        market_context = await market_context_builder.build_context(symbols=symbols)

        # Merge enhanced context into market context for analysts
        if enhanced_context:
            market_context["_enhanced_context"] = enhanced_context

        # Step 2: Run all analysts in parallel
        logger.info("Running Technical Analyst...")
        logger.info("Running Sector Strategist...")
        logger.info("Running Macro Economist...")
        logger.info("Running Correlation Detective...")
        logger.info("Running Risk Analyst...")

        analysts_start = datetime.utcnow()
        analyst_tasks = [
            self._run_analyst(analyst_name, config, market_context, symbols)
            for analyst_name, config in self.ANALYSTS.items()
        ]

        analyst_results = await asyncio.gather(*analyst_tasks, return_exceptions=True)
        analysts_elapsed = (datetime.utcnow() - analysts_start).total_seconds()

        # Collect results, handling any exceptions
        analyst_reports: dict[str, Any] = {}
        successful_count = 0
        for (analyst_name, _), result in zip(self.ANALYSTS.items(), analyst_results):
            if isinstance(result, Exception):
                logger.error(f"Analyst {analyst_name} failed: {result}")
                analyst_reports[analyst_name] = {
                    "error": str(result),
                    "confidence": 0.0,
                }
            else:
                analyst_reports[analyst_name] = result
                successful_count += 1

        logger.info(f"All analysts completed in {analysts_elapsed:.1f}s ({successful_count}/5 successful)")

        # Step 3: Run synthesis lead (if enabled)
        synthesis_result: dict[str, Any] = {}
        insights: list[dict[str, Any]] = []

        if include_synthesis:
            logger.info("Running Synthesis Lead...")
            synthesis_start = datetime.utcnow()
            try:
                synthesis_result, insights = await self._run_synthesis(analyst_reports)
                synthesis_elapsed = (datetime.utcnow() - synthesis_start).total_seconds()
                logger.info(f"Synthesis complete in {synthesis_elapsed:.1f}s, storing {len(insights)} insights...")
            except Exception as e:
                logger.error(f"Synthesis failed: {e}")
                synthesis_result = {"error": str(e)}

        self._last_analysis_time = datetime.utcnow()
        elapsed = (self._last_analysis_time - start_time).total_seconds()

        # Identify successful analysts
        successful_analysts = [
            k for k, v in analyst_reports.items() if "error" not in v
        ]

        # Capture analyst errors for context storage
        analyst_errors = {
            k: v.get("error") for k, v in analyst_reports.items() if "error" in v
        }

        result = {
            "analyst_reports": analyst_reports,
            "synthesis": synthesis_result,
            "insights": insights,
            "metadata": {
                "timestamp": start_time.isoformat(),
                "elapsed_seconds": round(elapsed, 2),
                "symbols": symbols,
                "analysts_run": list(self.ANALYSTS.keys()),
                "successful_analysts": successful_analysts,
            },
            # Research context data for storage
            "_research_context": {
                "market_context": market_context,
                "symbols_analyzed": symbols,
                "successful_analysts": successful_analysts,
                "analyst_errors": analyst_errors if analyst_errors else None,
                "analysis_duration_seconds": round(elapsed, 2),
            },
            # Enhanced context with statistical features and institutional memory
            "_enhanced_context": enhanced_context,
        }

        logger.info(f"Deep analysis complete: {len(insights)} insights generated in {elapsed:.1f}s")

        return result

    async def run_and_store(
        self,
        symbols: list[str] | None = None,
    ) -> list[DeepInsight]:
        """Run analysis and store insights in database.

        Executes full multi-agent analysis and persists the resulting
        DeepInsight records to the database along with their research contexts.
        Also starts outcome tracking for insights with actionable recommendations.

        Args:
            symbols: Optional list of symbols to focus on.

        Returns:
            List of created DeepInsight database objects with research_context attached.
        """
        # Run the analysis
        result = await self.run_analysis(symbols=symbols, include_synthesis=True)
        insights_data = result.get("insights", [])

        if not insights_data:
            logger.warning("No insights generated to store")
            return []

        # Extract research context data
        research_context_data = {
            "analyst_reports": result.get("analyst_reports", {}),
            "synthesis": result.get("synthesis", {}),
            **result.get("_research_context", {}),
        }

        # Add enhanced context if available
        if "_enhanced_context" in result:
            research_context_data["enhanced_context"] = result["_enhanced_context"]

        # Store in database with research context
        stored_insights = await self._store_insights(insights_data, research_context_data)

        logger.info(f"Stored {len(stored_insights)} DeepInsight records with research context")

        # Start outcome tracking for actionable insights
        if stored_insights:
            async with async_session_factory() as session:
                tracked_count = await self._start_insight_tracking(
                    stored_insights, session
                )
                logger.info(f"Started outcome tracking for {tracked_count} insights")

        return stored_insights

    async def _run_analyst(
        self,
        analyst_name: str,
        config: dict[str, Any],
        market_context: dict[str, Any],
        symbols: list[str] | None,
    ) -> dict[str, Any]:
        """Run a single analyst agent.

        Args:
            analyst_name: Name of the analyst (technical, macro, etc.).
            config: Analyst configuration with prompt, format/parse functions.
            market_context: Full market context from context builder.
            symbols: Optional symbols to focus on.

        Returns:
            Parsed analyst output dictionary with additional '_raw_response' key
            containing the full LLM response text for context storage.

        Raises:
            Exception: If analyst fails after all retries.
        """
        analyst_start = datetime.utcnow()
        prompt = config["prompt"]
        format_func = config["format_context"]
        parse_func = config["parse_response"]
        context_type = config["context_type"]

        # Get agent-specific context
        agent_context = await market_context_builder.build_agent_context(
            agent_type=context_type,
            symbols=symbols,
        )

        # Format context for the analyst
        formatted_context = format_func(agent_context)

        # Run with retries
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response_text = await self._query_llm(
                    prompt, formatted_context, analyst_name
                )

                # Parse the response
                parsed = parse_func(response_text)

                analyst_elapsed = (datetime.utcnow() - analyst_start).total_seconds()
                logger.info(f"  {analyst_name.capitalize()} analyst returned in {analyst_elapsed:.1f}s")

                # Handle different return types from parse functions
                if hasattr(parsed, "to_dict"):
                    result = parsed.to_dict()
                elif isinstance(parsed, dict):
                    result = parsed
                else:
                    result = {"raw": str(parsed), "confidence": 0.5}

                # Store raw response for research context
                result["_raw_response"] = response_text
                result["_elapsed_seconds"] = analyst_elapsed
                return result

            except Exception as e:
                last_error = e
                logger.warning(
                    f"Analyst {analyst_name} attempt {attempt + 1} failed: {e}"
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(1)  # Brief pause before retry

        raise last_error or Exception(f"Analyst {analyst_name} failed")

    async def _run_synthesis(
        self,
        analyst_reports: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Run the synthesis lead agent.

        Args:
            analyst_reports: Dictionary mapping analyst names to their outputs.

        Returns:
            Tuple of (raw synthesis result dict, list of insight dicts).
            The synthesis result includes '_full_response' with complete LLM output.
        """
        synthesis_start = datetime.utcnow()

        # Format analyst reports for synthesis
        synthesis_context = format_synthesis_context(analyst_reports)
        logger.info(f"[DEEP] Synthesis context length: {len(synthesis_context)} chars")

        # Query LLM
        response_text = await self._query_llm(SYNTHESIS_LEAD_PROMPT, synthesis_context, "synthesis")
        logger.info(f"[DEEP] Synthesis response length: {len(response_text)} chars")
        logger.info(f"[DEEP] Synthesis response preview: {response_text[:500]}")

        # Parse synthesis response
        insights = parse_synthesis_response(response_text)
        logger.info(f"[DEEP] Parsed {len(insights)} insights from synthesis")

        synthesis_elapsed = (datetime.utcnow() - synthesis_start).total_seconds()

        # Build synthesis result with full response for context storage
        synthesis_result = {
            "raw_response": response_text[:500],  # Truncate for logging
            "_full_response": response_text,  # Full response for research context
            "_elapsed_seconds": synthesis_elapsed,
            "insight_count": len(insights),
            "analysts_included": list(analyst_reports.keys()),
        }

        return synthesis_result, insights

    async def _query_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        agent_name: str = "unknown",
    ) -> str:
        """Query the LLM via the shared client pool.

        Args:
            system_prompt: System prompt for the agent.
            user_prompt: The user prompt to send.
            agent_name: Name of the agent (for logging).

        Returns:
            Full response text from the LLM.
        """
        return await pool_query_llm(system_prompt, user_prompt, agent_name)

    async def _store_insights(
        self,
        insights_data: list[dict[str, Any]],
        research_context_data: dict[str, Any] | None = None,
    ) -> list[DeepInsight]:
        """Store insights in the database with their research contexts.

        Args:
            insights_data: List of insight dictionaries.
            research_context_data: Optional research context data containing
                analyst_reports, synthesis, market_context, etc.

        Returns:
            List of created DeepInsight objects with research_context attached.
        """
        logger.info(f"Storing {len(insights_data)} insights to database...")
        stored: list[DeepInsight] = []

        async with async_session_factory() as session:
            for data in insights_data:
                try:
                    insight = self._create_deep_insight(data)
                    session.add(insight)

                    # Create and attach research context if data provided
                    if research_context_data:
                        research_context = self._create_research_context(
                            insight, research_context_data
                        )
                        session.add(research_context)
                        insight.research_context = research_context

                    stored.append(insight)
                except Exception as e:
                    logger.error(f"Failed to create DeepInsight: {e}")
                    continue

            if stored:
                await session.commit()
                logger.info(f"Successfully stored {len(stored)} DeepInsight records")

        return stored

    def _create_deep_insight(self, data: dict[str, Any]) -> DeepInsight:
        """Create a DeepInsight model from parsed data.

        Args:
            data: Insight dictionary from synthesis parsing.

        Returns:
            DeepInsight model instance.
        """
        # Validate and normalize insight_type
        insight_type = data.get("insight_type", "opportunity").lower()
        if insight_type not in VALID_INSIGHT_TYPES:
            insight_type = "opportunity"

        # Validate and normalize action
        action = data.get("action", "HOLD").upper()
        if action not in VALID_ACTIONS:
            action = "HOLD"

        # Build supporting evidence list
        supporting_evidence = []
        for e in data.get("supporting_evidence", []):
            if isinstance(e, dict):
                supporting_evidence.append({
                    "analyst": e.get("analyst", "unknown"),
                    "finding": e.get("finding", ""),
                    "confidence": e.get("confidence", 0.5),
                })

        return DeepInsight(
            insight_type=insight_type,
            action=action,
            title=data.get("title", "Untitled")[:200],
            thesis=data.get("thesis", ""),
            primary_symbol=data.get("primary_symbol"),
            related_symbols=data.get("related_symbols", []),
            supporting_evidence=supporting_evidence,
            confidence=float(data.get("confidence", 0.5)),
            time_horizon=data.get("time_horizon", "medium_term"),
            risk_factors=data.get("risk_factors", []),
            invalidation_trigger=data.get("invalidation_trigger"),
            historical_precedent=data.get("historical_precedent"),
            analysts_involved=data.get("analysts_involved", []),
            data_sources=data.get("data_sources", []),
        )

    def _create_research_context(
        self,
        insight: DeepInsight,
        research_data: dict[str, Any],
    ) -> InsightResearchContext:
        """Create an InsightResearchContext from research data.

        Args:
            insight: The parent DeepInsight (will be linked via relationship).
            research_data: Dictionary containing analyst_reports, synthesis,
                market_context, and metadata.

        Returns:
            InsightResearchContext model instance.
        """
        analyst_reports = research_data.get("analyst_reports", {})
        synthesis = research_data.get("synthesis", {})
        market_context = research_data.get("market_context", {})

        # Helper to clean analyst reports (remove internal keys)
        def clean_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
            if not report or "error" in report:
                return None
            # Remove internal keys that start with underscore
            return {k: v for k, v in report.items() if not k.startswith("_")}

        # Build analysts summary for quick context loading
        analysts_summary = self._build_analysts_summary(analyst_reports)

        # Extract key data points from market context
        key_data_points = self._extract_key_data_points(market_context, analyst_reports)

        # Estimate token count (rough estimate: ~4 chars per token)
        total_chars = len(str(analyst_reports)) + len(str(synthesis))
        estimated_tokens = total_chars // 4

        return InsightResearchContext(
            deep_insight=insight,
            schema_version="1.0",
            # Analyst reports
            technical_report=clean_report(analyst_reports.get("technical")),
            macro_report=clean_report(analyst_reports.get("macro")),
            sector_report=clean_report(analyst_reports.get("sector")),
            risk_report=clean_report(analyst_reports.get("risk")),
            correlation_report=clean_report(analyst_reports.get("correlation")),
            # Synthesis data
            synthesis_raw_response=synthesis.get("_full_response"),
            synthesis_summary={
                "insight_count": synthesis.get("insight_count", 0),
                "analysts_included": synthesis.get("analysts_included", []),
            },
            # Market context snapshot
            symbols_analyzed=research_data.get("symbols_analyzed"),
            market_summary_snapshot=market_context.get("market_summary"),
            sector_performance_snapshot=market_context.get("sector_performance"),
            economic_indicators_snapshot=market_context.get("economic_indicators"),
            # Summary fields
            analysts_summary=analysts_summary,
            key_data_points=key_data_points,
            estimated_token_count=estimated_tokens,
            # Metadata
            analysis_duration_seconds=research_data.get("analysis_duration_seconds"),
            successful_analysts=research_data.get("successful_analysts"),
            analyst_errors=research_data.get("analyst_errors"),
        )

    def _build_analysts_summary(self, analyst_reports: dict[str, Any]) -> str:
        """Build a condensed summary of all analyst findings.

        Args:
            analyst_reports: Dictionary mapping analyst names to their reports.

        Returns:
            Condensed summary string (< 2000 chars).
        """
        summaries = []

        for analyst_name, report in analyst_reports.items():
            if not report or "error" in report:
                continue

            # Extract key finding based on analyst type
            if analyst_name == "technical":
                finding = report.get("market_structure", "N/A")
                confidence = report.get("confidence", 0)
                summaries.append(f"Technical: {finding} (conf: {confidence:.0%})")
            elif analyst_name == "macro":
                regime = report.get("regime", {})
                regime_name = (
                    regime.get("name", "N/A") if isinstance(regime, dict) else "N/A"
                )
                summaries.append(f"Macro: {regime_name} regime")
            elif analyst_name == "sector":
                phase = report.get("market_phase", "N/A")
                summaries.append(f"Sector: {phase} phase")
            elif analyst_name == "risk":
                vol_regime = report.get("volatility_regime", {})
                vol_name = (
                    vol_regime.get("name", "N/A")
                    if isinstance(vol_regime, dict)
                    else "N/A"
                )
                summaries.append(f"Risk: {vol_name} volatility")
            elif analyst_name == "correlation":
                divergences = report.get("divergences", [])
                summaries.append(f"Correlation: {len(divergences)} divergences found")

        return " | ".join(summaries)[:2000]

    def _extract_key_data_points(
        self,
        market_context: dict[str, Any],
        analyst_reports: dict[str, Any],
    ) -> list[str]:
        """Extract key data points for quick reference.

        Args:
            market_context: Market context snapshot.
            analyst_reports: Analyst reports with findings.

        Returns:
            List of key data point strings.
        """
        data_points: list[str] = []

        # Extract from market summary
        market_summary = market_context.get("market_summary", {})
        if market_summary:
            spy_data = market_summary.get("SPY", {})
            if spy_data:
                change = spy_data.get("change_percent", 0)
                data_points.append(f"SPY_change={change:+.2f}%")

        # Extract VIX if available
        vix_data = market_context.get("vix", {})
        if vix_data:
            vix_value = vix_data.get("value")
            if vix_value:
                data_points.append(f"VIX={vix_value:.1f}")

        # Extract from technical report
        tech_report = analyst_reports.get("technical", {})
        if tech_report and "error" not in tech_report:
            findings = tech_report.get("findings", [])
            for finding in findings[:3]:  # Limit to first 3
                if isinstance(finding, dict):
                    symbol = finding.get("symbol", "")
                    rsi = finding.get("rsi")
                    if symbol and rsi:
                        data_points.append(f"RSI:{symbol}={rsi:.1f}")

        return data_points[:20]  # Limit to 20 data points

    @property
    def last_analysis_time(self) -> datetime | None:
        """Get timestamp of last completed analysis."""
        return self._last_analysis_time

    async def _prepare_enhanced_context(
        self,
        symbols: list[str],
        db_session: Any,
    ) -> dict[str, Any]:
        """Prepare enhanced context with statistical features and institutional memory.

        Fetches pre-computed statistical features, matching patterns for current
        conditions, and track record summary to enrich the analyst context.

        Args:
            symbols: List of stock symbols to analyze.
            db_session: Active database session for queries.

        Returns:
            Dictionary containing:
            - statistical_features: Dict mapping symbols to their computed features
            - matching_patterns: List of patterns matching current conditions
            - track_record: Summary of historical insight success rates
            - current_conditions: Extracted market conditions for pattern matching
        """
        enhanced_context: dict[str, Any] = {
            "statistical_features": {},
            "matching_patterns": [],
            "track_record": {},
            "current_conditions": {},
        }

        try:
            # Initialize services for this session
            memory_service = InstitutionalMemoryService(db_session)

            # Build current conditions from technical indicators
            current_conditions: dict[str, Any] = {}

            # Get market context to extract conditions
            market_context = await market_context_builder.build_context(
                symbols=symbols,
                include_technical=True,
                include_economic=True,
            )

            # Extract RSI and VIX from technical indicators
            tech_indicators = market_context.get("technical_indicators", {})
            for symbol in symbols:
                if symbol in tech_indicators:
                    indicators = tech_indicators[symbol]
                    if "RSI" in indicators:
                        rsi_value = indicators["RSI"].get("value")
                        if rsi_value is not None:
                            current_conditions["rsi"] = rsi_value
                            break

            # Check for VIX in economic or sector data
            sector_perf = market_context.get("sector_performance", {})
            if "VIX" in sector_perf:
                current_conditions["vix"] = sector_perf["VIX"].get("current_price")

            enhanced_context["current_conditions"] = current_conditions

            # Get matching patterns from institutional memory
            if current_conditions:
                patterns = await memory_service.get_relevant_patterns(
                    symbols=symbols,
                    current_conditions=current_conditions,
                )
                enhanced_context["matching_patterns"] = [
                    {
                        "id": str(p.id),
                        "name": p.pattern_name,
                        "success_rate": p.success_rate,
                        "expected_outcome": p.expected_outcome,
                        "trigger_conditions": p.trigger_conditions,
                        "avg_return": p.avg_return_when_triggered,
                    }
                    for p in patterns
                ]

            # Get track record from institutional memory
            track_record = await memory_service.get_insight_track_record()
            enhanced_context["track_record"] = track_record

            logger.info(
                f"Prepared enhanced context: {len(enhanced_context['matching_patterns'])} patterns, "
                f"track record with {track_record.get('total_insights', 0)} historical insights"
            )

        except Exception as e:
            logger.warning(f"Error preparing enhanced context: {e}")
            # Continue with empty enhanced context on error

        return enhanced_context

    async def _start_insight_tracking(
        self,
        insights: list[DeepInsight],
        db_session: Any,
    ) -> int:
        """Start outcome tracking for generated insights with actionable recommendations.

        For each insight with a directional action (BUY, SELL, SHORT, COVER),
        creates an InsightOutcome record to track price movement and validate
        the thesis over the tracking period.

        Args:
            insights: List of DeepInsight objects to potentially track.
            db_session: Active database session for persistence.

        Returns:
            Number of insights that started tracking.
        """
        # Map actions to predicted directions
        action_to_direction: dict[str, str] = {
            "BUY": "bullish",
            "STRONG_BUY": "bullish",
            "SELL": "bearish",
            "STRONG_SELL": "bearish",
            "SHORT": "bearish",
            "COVER": "bullish",
            "HOLD": "neutral",
            "REDUCE": "bearish",
            "ACCUMULATE": "bullish",
        }

        tracked_count = 0
        outcome_tracker = InsightOutcomeTracker(db_session)

        for insight in insights:
            try:
                # Only track insights with a primary symbol and actionable recommendation
                if not insight.primary_symbol:
                    continue

                action = insight.action.upper() if insight.action else "HOLD"
                predicted_direction = action_to_direction.get(action, "neutral")

                # Skip neutral predictions as they're harder to validate
                if predicted_direction == "neutral":
                    continue

                # Start tracking
                await outcome_tracker.start_tracking(
                    insight_id=insight.id,
                    symbol=insight.primary_symbol,
                    predicted_direction=predicted_direction,
                    tracking_days=20,  # Default ~1 month tracking period
                )
                tracked_count += 1

                logger.info(
                    f"Started tracking insight {insight.id} ({insight.primary_symbol}): "
                    f"action={action}, direction={predicted_direction}"
                )

            except Exception as e:
                logger.warning(
                    f"Failed to start tracking for insight {insight.id}: {e}"
                )
                continue

        logger.info(f"Started tracking for {tracked_count}/{len(insights)} insights")
        return tracked_count


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================


# Module-level singleton instance
_engine_instance: DeepAnalysisEngine | None = None


def get_deep_analysis_engine() -> DeepAnalysisEngine:
    """Get or create the singleton deep analysis engine instance.

    Returns:
        The DeepAnalysisEngine singleton instance.
    """
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = DeepAnalysisEngine()
    return _engine_instance


# Convenience alias for direct import
deep_analysis_engine = get_deep_analysis_engine()
