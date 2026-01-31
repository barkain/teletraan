"""Deep Analysis Engine - Orchestrates parallel multi-agent market analysis.

This module provides the DeepAnalysisEngine class that:
1. Spawns 5 specialist analyst agents in parallel using asyncio.gather()
2. Collects their findings and passes them to the Synthesis Lead
3. Generates unified DeepInsight recommendations
4. Stores insights in the database

Uses the Claude Agent SDK (ClaudeSDKClient) for LLM interactions.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    AssistantMessage,
    TextBlock,
)

from database import async_session_factory
from models.deep_insight import DeepInsight, InsightType, InsightAction

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
        logger.info(f"Starting deep analysis for symbols: {symbols or 'all'}")

        # Step 1: Build market context
        logger.debug("Building market context...")
        market_context = await market_context_builder.build_context(symbols=symbols)

        # Step 2: Run all analysts in parallel
        logger.info("Spawning 5 analyst agents in parallel...")
        analyst_tasks = [
            self._run_analyst(analyst_name, config, market_context, symbols)
            for analyst_name, config in self.ANALYSTS.items()
        ]

        analyst_results = await asyncio.gather(*analyst_tasks, return_exceptions=True)

        # Collect results, handling any exceptions
        analyst_reports: dict[str, Any] = {}
        for (analyst_name, _), result in zip(self.ANALYSTS.items(), analyst_results):
            if isinstance(result, Exception):
                logger.error(f"Analyst {analyst_name} failed: {result}")
                analyst_reports[analyst_name] = {
                    "error": str(result),
                    "confidence": 0.0,
                }
            else:
                analyst_reports[analyst_name] = result

        # Step 3: Run synthesis lead (if enabled)
        synthesis_result: dict[str, Any] = {}
        insights: list[dict[str, Any]] = []

        if include_synthesis:
            logger.info("Running synthesis lead to aggregate findings...")
            try:
                synthesis_result, insights = await self._run_synthesis(analyst_reports)
            except Exception as e:
                logger.error(f"Synthesis failed: {e}")
                synthesis_result = {"error": str(e)}

        self._last_analysis_time = datetime.utcnow()
        elapsed = (self._last_analysis_time - start_time).total_seconds()

        result = {
            "analyst_reports": analyst_reports,
            "synthesis": synthesis_result,
            "insights": insights,
            "metadata": {
                "timestamp": start_time.isoformat(),
                "elapsed_seconds": round(elapsed, 2),
                "symbols": symbols,
                "analysts_run": list(self.ANALYSTS.keys()),
                "successful_analysts": [
                    k for k, v in analyst_reports.items() if "error" not in v
                ],
            },
        }

        logger.info(
            f"Deep analysis complete in {elapsed:.1f}s. "
            f"Generated {len(insights)} insights."
        )

        return result

    async def run_and_store(
        self,
        symbols: list[str] | None = None,
    ) -> list[DeepInsight]:
        """Run analysis and store insights in database.

        Executes full multi-agent analysis and persists the resulting
        DeepInsight records to the database.

        Args:
            symbols: Optional list of symbols to focus on.

        Returns:
            List of created DeepInsight database objects.
        """
        # Run the analysis
        result = await self.run_analysis(symbols=symbols, include_synthesis=True)
        insights_data = result.get("insights", [])

        if not insights_data:
            logger.warning("No insights generated to store")
            return []

        # Store in database
        stored_insights = await self._store_insights(insights_data)

        logger.info(f"Stored {len(stored_insights)} DeepInsight records")
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
            Parsed analyst output dictionary.

        Raises:
            Exception: If analyst fails after all retries.
        """
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

        # Create SDK options
        options = ClaudeAgentOptions(
            system_prompt=prompt,
        )

        # Run with retries
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response_text = await self._query_llm(
                    options, formatted_context, analyst_name
                )

                # Parse the response
                parsed = parse_func(response_text)

                # Handle different return types from parse functions
                if hasattr(parsed, "to_dict"):
                    return parsed.to_dict()
                elif isinstance(parsed, dict):
                    return parsed
                else:
                    return {"raw": str(parsed), "confidence": 0.5}

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
        """
        # Format analyst reports for synthesis
        synthesis_context = format_synthesis_context(analyst_reports)

        # Create SDK options for synthesis
        options = ClaudeAgentOptions(
            system_prompt=SYNTHESIS_LEAD_PROMPT,
        )

        # Query LLM
        response_text = await self._query_llm(options, synthesis_context, "synthesis")

        # Parse synthesis response
        insights = parse_synthesis_response(response_text)

        # Build synthesis result
        synthesis_result = {
            "raw_response": response_text[:500],  # Truncate for safety
            "insight_count": len(insights),
            "analysts_included": list(analyst_reports.keys()),
        }

        return synthesis_result, insights

    async def _query_llm(
        self,
        options: ClaudeAgentOptions,
        prompt: str,
        agent_name: str,
    ) -> str:
        """Query the LLM using ClaudeSDKClient.

        Args:
            options: Claude agent options with system prompt.
            prompt: The user prompt to send.
            agent_name: Name of the agent (for logging).

        Returns:
            Full response text from the LLM.
        """
        logger.debug(f"Querying LLM for {agent_name}...")

        response_text = ""

        try:
            async with ClaudeSDKClient(options=options) as client:
                await client.query(prompt)

                async for msg in client.receive_response():
                    if isinstance(msg, AssistantMessage):
                        for block in msg.content:
                            if isinstance(block, TextBlock):
                                response_text += block.text

        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for {agent_name} response")
            raise
        except Exception as e:
            logger.error(f"LLM query failed for {agent_name}: {e}")
            raise

        logger.debug(f"Received {len(response_text)} chars from {agent_name}")
        return response_text

    async def _store_insights(
        self,
        insights_data: list[dict[str, Any]],
    ) -> list[DeepInsight]:
        """Store insights in the database.

        Args:
            insights_data: List of insight dictionaries.

        Returns:
            List of created DeepInsight objects.
        """
        stored: list[DeepInsight] = []

        async with async_session_factory() as session:
            for data in insights_data:
                try:
                    insight = self._create_deep_insight(data)
                    session.add(insight)
                    stored.append(insight)
                except Exception as e:
                    logger.error(f"Failed to create DeepInsight: {e}")
                    continue

            if stored:
                await session.commit()
                logger.debug(f"Committed {len(stored)} DeepInsight records")

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

    @property
    def last_analysis_time(self) -> datetime | None:
        """Get timestamp of last completed analysis."""
        return self._last_analysis_time


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
