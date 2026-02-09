"""Follow-up Research Launcher - Spawns focused research based on conversation discoveries.

This module provides the FollowUpResearchLauncher class that:
1. Takes a parent insight and research request from a conversation
2. Runs focused analysis targeting specific questions
3. Creates new DeepInsights linked to the parent
4. Stores FollowUpResearch records tracking the relationship

Supports multiple research types:
- sector_deep_dive: Deep analysis of a specific sector
- correlation_analysis: Focus on specific asset correlations
- risk_scenario: Analyze specific "what if" scenarios
- technical_focus: Detailed technical analysis of a symbol
- macro_impact: Analyze specific macro factor impacts
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from llm.client_pool import pool_query_llm

from database import async_session_factory
from models.deep_insight import DeepInsight, InsightType, InsightAction
from models.insight_conversation import (
    FollowUpResearch,
    ResearchStatus,
    ResearchType,
)
from models.insight_research_context import InsightResearchContext

from analysis.context_builder import market_context_builder


logger = logging.getLogger(__name__)


# =============================================================================
# RESEARCH TYPES AND PROMPTS
# =============================================================================


class FocusedResearchType(str, Enum):
    """Types of focused follow-up research."""

    SECTOR_DEEP_DIVE = "sector_deep_dive"
    CORRELATION_ANALYSIS = "correlation_analysis"
    RISK_SCENARIO = "risk_scenario"
    TECHNICAL_FOCUS = "technical_focus"
    MACRO_IMPACT = "macro_impact"


# Map from ResearchType enum to FocusedResearchType
RESEARCH_TYPE_MAPPING = {
    ResearchType.DEEP_DIVE: FocusedResearchType.SECTOR_DEEP_DIVE,
    ResearchType.CORRELATION_CHECK: FocusedResearchType.CORRELATION_ANALYSIS,
    ResearchType.WHAT_IF: FocusedResearchType.RISK_SCENARIO,
    ResearchType.SCENARIO_ANALYSIS: FocusedResearchType.RISK_SCENARIO,
}


FOCUSED_RESEARCH_PROMPTS = {
    FocusedResearchType.SECTOR_DEEP_DIVE: """You are a Sector Specialist conducting a deep-dive analysis.

## Your Task
Conduct an in-depth analysis of the specified sector, examining:
1. **Sector Leadership** - Which companies are leading/lagging and why
2. **Sub-sector Dynamics** - Performance within the sector
3. **Competitive Positioning** - Market share shifts, moats, disruption risks
4. **Valuation Analysis** - Relative valuations within the sector
5. **Catalyst Assessment** - Near-term and medium-term catalysts

## Context
You are following up on a previous insight to provide deeper sector analysis.

## Output Format
Return JSON:
{
  "insight_type": "opportunity",
  "action": "BUY",
  "title": "Your insight title",
  "thesis": "Detailed thesis explaining your analysis...",
  "primary_symbol": "XLK",
  "related_symbols": ["AAPL", "MSFT"],
  "supporting_evidence": [
    {"analyst": "sector_deep_dive", "finding": "...", "confidence": 0.8}
  ],
  "confidence": 0.75,
  "time_horizon": "medium_term",
  "risk_factors": ["Risk 1", "Risk 2"],
  "invalidation_trigger": "What would invalidate this thesis",
  "analysts_involved": ["sector_deep_dive"]
}
""",
    FocusedResearchType.CORRELATION_ANALYSIS: """You are a Correlation Analyst specializing in cross-asset relationships.

## Your Task
Analyze the correlation dynamics between specified assets:
1. **Current Correlation State** - How correlated are the assets now?
2. **Historical Correlation** - How has this relationship evolved?
3. **Correlation Drivers** - What factors drive this correlation?
4. **Divergence Detection** - Are there unusual divergences?
5. **Trading Implications** - What does this mean for positioning?

## Context
You are following up on a previous insight to examine specific correlation patterns.

## Output Format
Return JSON:
{
  "insight_type": "correlation",
  "action": "WATCH",
  "title": "Your insight title",
  "thesis": "Detailed thesis explaining correlation dynamics...",
  "primary_symbol": "SPY",
  "related_symbols": ["TLT", "GLD"],
  "supporting_evidence": [
    {"analyst": "correlation_analysis", "finding": "...", "confidence": 0.8}
  ],
  "confidence": 0.7,
  "time_horizon": "short_term",
  "risk_factors": ["Risk 1", "Risk 2"],
  "invalidation_trigger": "What would invalidate this thesis",
  "analysts_involved": ["correlation_analysis"]
}
""",
    FocusedResearchType.RISK_SCENARIO: """You are a Risk Scenario Analyst specializing in "what if" analysis.

## Your Task
Analyze the specific risk scenario and its market implications:
1. **Scenario Description** - What exactly would happen in this scenario?
2. **Probability Assessment** - How likely is this scenario?
3. **First-Order Effects** - Immediate market impacts
4. **Second-Order Effects** - Ripple effects across markets
5. **Positioning Recommendations** - How to position for/against this scenario

## Context
You are analyzing a specific "what if" scenario raised during insight discussion.

## Output Format
Return JSON:
{
  "insight_type": "risk",
  "action": "WATCH",
  "title": "Your scenario analysis title",
  "thesis": "Detailed analysis of the scenario and implications...",
  "primary_symbol": null,
  "related_symbols": ["SPY", "TLT", "VIX"],
  "supporting_evidence": [
    {"analyst": "risk_scenario", "finding": "...", "confidence": 0.7}
  ],
  "confidence": 0.6,
  "time_horizon": "short_term",
  "risk_factors": ["Risk 1", "Risk 2"],
  "invalidation_trigger": "What would change this analysis",
  "analysts_involved": ["risk_scenario"]
}
""",
    FocusedResearchType.TECHNICAL_FOCUS: """You are a Technical Analysis Specialist conducting focused price analysis.

## Your Task
Perform detailed technical analysis on the specified symbol(s):
1. **Chart Pattern Analysis** - Key patterns forming or completing
2. **Indicator Deep Dive** - RSI, MACD, Bollinger Bands, volume analysis
3. **Multi-Timeframe Confluence** - Daily, weekly, monthly alignment
4. **Key Levels** - Critical support/resistance zones
5. **Trade Setup** - Entry, stop-loss, and target recommendations

## Context
You are following up on a previous insight to provide focused technical analysis.

## Output Format
Return JSON:
{
  "insight_type": "opportunity",
  "action": "BUY",
  "title": "Your technical analysis title",
  "thesis": "Detailed technical thesis with specific levels...",
  "primary_symbol": "AAPL",
  "related_symbols": [],
  "supporting_evidence": [
    {"analyst": "technical_focus", "finding": "...", "confidence": 0.8}
  ],
  "confidence": 0.75,
  "time_horizon": "short_term",
  "risk_factors": ["Technical risk 1", "Risk 2"],
  "invalidation_trigger": "Close below $X on high volume",
  "analysts_involved": ["technical_focus"]
}
""",
    FocusedResearchType.MACRO_IMPACT: """You are a Macro Impact Analyst examining specific economic factors.

## Your Task
Analyze how a specific macro factor impacts markets:
1. **Factor Analysis** - Current state and trajectory of the macro factor
2. **Transmission Mechanism** - How does this factor affect markets?
3. **Sector Sensitivity** - Which sectors are most affected?
4. **Historical Precedent** - What happened in similar situations?
5. **Positioning Implications** - How to position given this factor

## Context
You are analyzing a specific macro factor's market impact raised during insight discussion.

## Output Format
Return JSON:
{
  "insight_type": "macro",
  "action": "HOLD",
  "title": "Your macro impact analysis title",
  "thesis": "Detailed macro impact analysis...",
  "primary_symbol": null,
  "related_symbols": ["SPY", "XLF", "TLT"],
  "supporting_evidence": [
    {"analyst": "macro_impact", "finding": "...", "confidence": 0.7}
  ],
  "confidence": 0.65,
  "time_horizon": "medium_term",
  "risk_factors": ["Macro risk 1", "Risk 2"],
  "invalidation_trigger": "What would change this macro outlook",
  "analysts_involved": ["macro_impact"]
}
""",
}


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class ResearchRequest:
    """Request for follow-up research."""

    parent_insight_id: int
    conversation_id: int
    message_id: int | None = None
    research_type: ResearchType = ResearchType.DEEP_DIVE
    query: str = ""
    symbols: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    scenario: str | None = None  # For risk_scenario type
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "parent_insight_id": self.parent_insight_id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "research_type": self.research_type.value,
            "query": self.query,
            "symbols": self.symbols,
            "questions": self.questions,
            "scenario": self.scenario,
            "parameters": self.parameters,
        }


@dataclass
class ResearchResult:
    """Result of follow-up research."""

    success: bool
    follow_up_research: FollowUpResearch | None = None
    new_insight: DeepInsight | None = None
    error_message: str | None = None
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "follow_up_research_id": (
                self.follow_up_research.id if self.follow_up_research else None
            ),
            "new_insight_id": self.new_insight.id if self.new_insight else None,
            "error_message": self.error_message,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
        }


# =============================================================================
# FOLLOW-UP RESEARCH LAUNCHER
# =============================================================================


class FollowUpResearchLauncher:
    """Launches focused follow-up research based on conversation discoveries.

    This class handles the full lifecycle of follow-up research:
    1. Receives a research request linked to a parent insight
    2. Builds focused context based on the research type
    3. Runs a specialized analyst agent
    4. Creates a new DeepInsight linked to the parent
    5. Records the FollowUpResearch relationship

    Example:
        ```python
        launcher = FollowUpResearchLauncher()

        request = ResearchRequest(
            parent_insight_id=42,
            conversation_id=7,
            research_type=ResearchType.WHAT_IF,
            query="What if rates rise 50bps?",
            scenario="Federal Reserve raises rates by 50 basis points",
        )

        result = await launcher.launch(request)
        if result.success:
            print(f"New insight created: {result.new_insight.id}")
        ```
    """

    def __init__(self, timeout_seconds: int = 120) -> None:
        """Initialize the research launcher.

        Args:
            timeout_seconds: Timeout for LLM queries.
        """
        self.timeout_seconds = timeout_seconds

    async def launch(self, request: ResearchRequest) -> ResearchResult:
        """Launch follow-up research and create new insight.

        Args:
            request: ResearchRequest with parent insight, questions, etc.

        Returns:
            ResearchResult with success status, new insight, and FollowUpResearch record.
        """
        start_time = datetime.utcnow()
        logger.info(
            f"Launching follow-up research: type={request.research_type.value}, "
            f"parent_insight={request.parent_insight_id}"
        )

        # Load parent insight
        parent_insight = await self._load_parent_insight(request.parent_insight_id)
        if not parent_insight:
            return ResearchResult(
                success=False,
                error_message=f"Parent insight {request.parent_insight_id} not found",
            )

        # Create FollowUpResearch record (status: RUNNING)
        follow_up = await self._create_follow_up_record(request)

        try:
            # Build focused prompt based on research type
            prompt = await self._build_focused_prompt(
                request=request,
                parent_insight=parent_insight,
            )

            # Run the focused analyst
            response = await self._run_focused_analyst(
                research_type=request.research_type,
                prompt=prompt,
            )

            # Synthesize findings into a new DeepInsight
            new_insight = await self._synthesize_focused_findings(
                response=response,
                parent_insight=parent_insight,
                request=request,
            )

            # Update FollowUpResearch record with result
            follow_up = await self._complete_research(
                follow_up_id=follow_up.id,
                new_insight_id=new_insight.id,
                status=ResearchStatus.COMPLETED,
            )

            elapsed = (datetime.utcnow() - start_time).total_seconds()
            logger.info(
                f"Follow-up research complete: new_insight={new_insight.id}, "
                f"elapsed={elapsed:.1f}s"
            )

            return ResearchResult(
                success=True,
                follow_up_research=follow_up,
                new_insight=new_insight,
                elapsed_seconds=elapsed,
            )

        except Exception as e:
            logger.exception(f"Follow-up research failed: {e}")
            elapsed = (datetime.utcnow() - start_time).total_seconds()

            # Update FollowUpResearch record with failure
            await self._complete_research(
                follow_up_id=follow_up.id,
                new_insight_id=None,
                status=ResearchStatus.FAILED,
                error_message=str(e),
            )

            return ResearchResult(
                success=False,
                follow_up_research=follow_up,
                error_message=str(e),
                elapsed_seconds=elapsed,
            )

    async def _build_focused_prompt(
        self,
        request: ResearchRequest,
        parent_insight: DeepInsight,
    ) -> str:
        """Build a focused analysis prompt based on research type.

        Args:
            request: The research request with query, questions, symbols.
            parent_insight: The parent DeepInsight for context.

        Returns:
            Formatted prompt string for the focused analyst.
        """
        parts: list[str] = []

        # Add parent context summary
        parts.append("=" * 60)
        parts.append("PARENT INSIGHT CONTEXT")
        parts.append("=" * 60)
        parts.append(f"\nTitle: {parent_insight.title}")
        parts.append(f"Type: {parent_insight.insight_type}")
        parts.append(f"Action: {parent_insight.action}")
        parts.append(f"Confidence: {parent_insight.confidence:.0%}")
        parts.append(f"\nThesis:\n{parent_insight.thesis}")

        if parent_insight.primary_symbol:
            parts.append(f"\nPrimary Symbol: {parent_insight.primary_symbol}")
        if parent_insight.related_symbols:
            parts.append(f"Related Symbols: {', '.join(parent_insight.related_symbols)}")
        if parent_insight.risk_factors:
            parts.append("\nRisk Factors:")
            for rf in parent_insight.risk_factors:
                parts.append(f"  - {rf}")

        # Add research-specific context
        parts.append("\n" + "=" * 60)
        parts.append("RESEARCH REQUEST")
        parts.append("=" * 60)

        parts.append(f"\nResearch Type: {request.research_type.value}")
        parts.append(f"Query: {request.query}")

        if request.symbols:
            parts.append(f"\nSymbols to Focus On: {', '.join(request.symbols)}")

        if request.questions:
            parts.append("\nSpecific Questions to Address:")
            for i, q in enumerate(request.questions, 1):
                parts.append(f"  {i}. {q}")

        if request.scenario:
            parts.append(f"\nScenario to Analyze:\n{request.scenario}")

        # Add market context if available
        try:
            symbols = request.symbols or (
                [parent_insight.primary_symbol] if parent_insight.primary_symbol else None
            )
            if symbols:
                market_context = await market_context_builder.build_context(
                    symbols=symbols,
                    include_price_history=True,
                    include_technical=True,
                    include_economic=True,
                    include_sectors=True,
                )

                parts.append("\n" + "=" * 60)
                parts.append("CURRENT MARKET DATA")
                parts.append("=" * 60)
                parts.append(self._format_market_context(market_context))
        except Exception as e:
            logger.warning(f"Could not build market context: {e}")

        parts.append("\n" + "=" * 60)
        parts.append("INSTRUCTIONS")
        parts.append("=" * 60)
        parts.append(
            "\nPlease analyze the above context and provide your focused analysis "
            "in the specified JSON format. Be specific, quantitative where possible, "
            "and reference the parent insight context in your analysis."
        )

        return "\n".join(parts)

    def _format_market_context(self, context: dict[str, Any]) -> str:
        """Format market context for prompt inclusion.

        Args:
            context: Market context from context builder.

        Returns:
            Formatted string summary of market data.
        """
        parts: list[str] = []

        # Market summary
        summary = context.get("market_summary", {})
        market_index = summary.get("market_index", {})
        if market_index:
            parts.append(f"\nSPY: ${market_index.get('current', 0):.2f}")
            parts.append(f"Change: {market_index.get('change_pct', 0):+.2f}%")

        # Price history summary
        price_history = context.get("price_history", {})
        for symbol, prices in list(price_history.items())[:5]:
            if prices:
                latest = prices[0]
                parts.append(f"\n{symbol}: ${latest.get('close', 0):.2f}")

        # Technical indicators summary
        tech_indicators = context.get("technical_indicators", {})
        for symbol, indicators in list(tech_indicators.items())[:5]:
            rsi = indicators.get("rsi", {})
            if isinstance(rsi, dict) and rsi.get("value"):
                parts.append(f"  RSI: {rsi['value']:.1f}")

        return "\n".join(parts) if parts else "No market data available"

    async def _run_focused_analyst(
        self,
        research_type: ResearchType,
        prompt: str,
    ) -> str:
        """Run a focused analyst agent with the given prompt.

        Args:
            research_type: Type of research to determine which prompt to use.
            prompt: The formatted context prompt.

        Returns:
            Raw response text from the LLM.
        """
        # Map to focused research type
        focused_type = RESEARCH_TYPE_MAPPING.get(
            research_type, FocusedResearchType.SECTOR_DEEP_DIVE
        )

        # Get the system prompt for this research type
        system_prompt = FOCUSED_RESEARCH_PROMPTS.get(
            focused_type, FOCUSED_RESEARCH_PROMPTS[FocusedResearchType.SECTOR_DEEP_DIVE]
        )

        logger.info(f"Running focused analyst: {focused_type.value}")

        try:
            response_text = await pool_query_llm(
                system_prompt=system_prompt,
                user_prompt=prompt,
                agent_name=f"followup_{focused_type.value}",
            )

            logger.info(
                f"Focused analyst response: {len(response_text)} chars"
            )

        except asyncio.TimeoutError:
            logger.error("Focused analyst timed out")
            raise
        except Exception as e:
            logger.exception(f"Focused analyst failed: {e}")
            raise

        return response_text

    async def _synthesize_focused_findings(
        self,
        response: str,
        parent_insight: DeepInsight,
        request: ResearchRequest,
    ) -> DeepInsight:
        """Parse findings and create a new DeepInsight linked to parent.

        Args:
            response: Raw LLM response text.
            parent_insight: The parent insight for linking.
            request: The original research request.

        Returns:
            New DeepInsight record stored in database.
        """
        # Parse JSON from response
        insight_data = self._extract_insight_json(response)

        if not insight_data:
            # Create minimal insight from raw response
            insight_data = {
                "insight_type": "opportunity",
                "action": "WATCH",
                "title": f"Follow-up: {request.query[:100]}",
                "thesis": response[:2000],
                "confidence": 0.5,
                "time_horizon": "medium_term",
                "analysts_involved": ["focused_research"],
            }

        # Ensure we have the research context reference
        insight_data["data_sources"] = [
            f"parent_insight:{parent_insight.id}",
            f"research_type:{request.research_type.value}",
        ]

        # Merge symbols from request if not specified
        if not insight_data.get("primary_symbol") and request.symbols:
            insight_data["primary_symbol"] = request.symbols[0]
        if not insight_data.get("related_symbols") and len(request.symbols) > 1:
            insight_data["related_symbols"] = request.symbols[1:]

        # Create and store the new insight
        new_insight = await self._store_new_insight(insight_data, parent_insight, request)

        return new_insight

    def _extract_insight_json(self, text: str) -> dict[str, Any] | None:
        """Extract JSON insight data from response text.

        Args:
            text: Raw LLM response.

        Returns:
            Parsed insight dictionary or None.
        """
        import json
        import re

        # Try full text as JSON
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        # Try code blocks
        code_block_pattern = r"```(?:json)?\s*([\s\S]*?)```"
        matches = re.findall(code_block_pattern, text)
        for match in matches:
            try:
                return json.loads(match.strip())
            except json.JSONDecodeError:
                continue

        # Try finding JSON object
        start_idx = text.find("{")
        end_idx = text.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            try:
                return json.loads(text[start_idx : end_idx + 1])
            except json.JSONDecodeError:
                pass

        return None

    async def _load_parent_insight(self, insight_id: int) -> DeepInsight | None:
        """Load parent insight from database.

        Args:
            insight_id: ID of the parent insight.

        Returns:
            DeepInsight or None if not found.
        """
        from sqlalchemy import select

        async with async_session_factory() as session:
            result = await session.execute(
                select(DeepInsight).where(DeepInsight.id == insight_id)
            )
            return result.scalar_one_or_none()

    async def _create_follow_up_record(
        self,
        request: ResearchRequest,
    ) -> FollowUpResearch:
        """Create initial FollowUpResearch record in RUNNING status.

        Args:
            request: The research request.

        Returns:
            Created FollowUpResearch record.
        """
        async with async_session_factory() as session:
            follow_up = FollowUpResearch(
                conversation_id=request.conversation_id,
                source_message_id=request.message_id,
                research_type=request.research_type,
                query=request.query,
                parameters=request.to_dict(),
                status=ResearchStatus.RUNNING,
            )
            session.add(follow_up)
            await session.commit()
            await session.refresh(follow_up)

            logger.info(f"Created FollowUpResearch record: {follow_up.id}")
            return follow_up

    async def _complete_research(
        self,
        follow_up_id: int,
        new_insight_id: int | None,
        status: ResearchStatus,
        error_message: str | None = None,
    ) -> FollowUpResearch:
        """Update FollowUpResearch record with completion status.

        Args:
            follow_up_id: ID of the FollowUpResearch record.
            new_insight_id: ID of the new insight (if successful).
            status: Final status (COMPLETED or FAILED).
            error_message: Error message if failed.

        Returns:
            Updated FollowUpResearch record.
        """
        from sqlalchemy import select

        async with async_session_factory() as session:
            result = await session.execute(
                select(FollowUpResearch).where(FollowUpResearch.id == follow_up_id)
            )
            follow_up = result.scalar_one()

            follow_up.status = status
            follow_up.result_insight_id = new_insight_id
            follow_up.error_message = error_message
            follow_up.completed_at = datetime.utcnow()

            await session.commit()
            await session.refresh(follow_up)

            return follow_up

    async def _store_new_insight(
        self,
        insight_data: dict[str, Any],
        parent_insight: DeepInsight,
        request: ResearchRequest,
    ) -> DeepInsight:
        """Store new DeepInsight in database.

        Args:
            insight_data: Parsed insight data dictionary.
            parent_insight: Parent insight for reference.
            request: Original research request.

        Returns:
            Created DeepInsight record.
        """
        # Validate insight_type
        valid_types = {t.value for t in InsightType}
        insight_type = insight_data.get("insight_type", "opportunity").lower()
        if insight_type not in valid_types:
            insight_type = "opportunity"

        # Validate action
        valid_actions = {a.value for a in InsightAction}
        action = insight_data.get("action", "HOLD").upper()
        if action not in valid_actions:
            action = "HOLD"

        # Build supporting evidence
        supporting_evidence = []
        for e in insight_data.get("supporting_evidence", []):
            if isinstance(e, dict):
                supporting_evidence.append({
                    "analyst": e.get("analyst", "focused_research"),
                    "finding": e.get("finding", ""),
                    "confidence": float(e.get("confidence", 0.5)),
                })

        # Create the new insight with parent linking
        new_insight = DeepInsight(
            insight_type=insight_type,
            action=action,
            title=insight_data.get("title", "Follow-up Research")[:200],
            thesis=insight_data.get("thesis", ""),
            primary_symbol=insight_data.get("primary_symbol"),
            related_symbols=insight_data.get("related_symbols", []),
            supporting_evidence=supporting_evidence,
            confidence=float(insight_data.get("confidence", 0.5)),
            time_horizon=insight_data.get("time_horizon", "medium_term"),
            risk_factors=insight_data.get("risk_factors", []),
            invalidation_trigger=insight_data.get("invalidation_trigger"),
            historical_precedent=insight_data.get("historical_precedent"),
            analysts_involved=insight_data.get("analysts_involved", ["focused_research"]),
            data_sources=insight_data.get("data_sources", []),
            # Link to parent insight and source conversation
            parent_insight_id=parent_insight.id,
            source_conversation_id=request.conversation_id,
        )

        # Create research context linking to parent
        research_context = InsightResearchContext(
            schema_version="1.0",
            analysts_summary=f"Follow-up research from insight #{parent_insight.id}",
            key_data_points=[
                f"parent_insight_id={parent_insight.id}",
                f"research_type={request.research_type.value}",
                f"query={request.query[:100]}",
            ],
        )

        async with async_session_factory() as session:
            session.add(new_insight)
            await session.flush()  # Get the ID

            research_context.deep_insight_id = new_insight.id
            session.add(research_context)
            new_insight.research_context = research_context

            await session.commit()
            await session.refresh(new_insight)

            logger.info(f"Stored new insight: {new_insight.id}")
            return new_insight


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================


_launcher_instance: FollowUpResearchLauncher | None = None


def get_followup_research_launcher() -> FollowUpResearchLauncher:
    """Get or create the singleton launcher instance.

    Returns:
        The FollowUpResearchLauncher singleton instance.
    """
    global _launcher_instance
    if _launcher_instance is None:
        _launcher_instance = FollowUpResearchLauncher()
    return _launcher_instance


# Convenience alias
followup_research_launcher = get_followup_research_launcher()
