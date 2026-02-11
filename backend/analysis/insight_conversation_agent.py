"""InsightConversationAgent - AI agent for contextual insight conversations.

This module provides an AI agent that can engage in conversations about
DeepInsights, leveraging the full research context including:
- 5 analyst reports (technical, macro, sector, risk, correlation)
- Synthesis reasoning and key findings
- Market context snapshot at analysis time

The agent can:
- Answer questions about the insight and underlying research
- Detect user intent to modify insight fields
- Detect user intent for follow-up research

Uses the Claude Agent SDK for streaming responses.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    TextBlock,
)
from llm.client_pool import get_client_pool

from database import async_session_factory
from models.deep_insight import DeepInsight
from models.insight_research_context import InsightResearchContext
from models.insight_conversation import (
    InsightConversation,
    InsightConversationMessage,
    MessageRole,
    ContentType,
    ModificationType,
    ResearchType,
)
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES FOR STRUCTURED OUTPUTS
# =============================================================================


@dataclass
class ModificationProposal:
    """Proposal to modify an insight field based on conversation.

    Attributes:
        field: Name of the field to modify (e.g., "confidence", "thesis", "risk_factors")
        old_value: Current value of the field
        new_value: Proposed new value
        reasoning: Justification for the modification
        modification_type: Type classification for the modification
    """

    field: str
    old_value: Any
    new_value: Any
    reasoning: str
    modification_type: ModificationType = field(default=ModificationType.THESIS_UPDATE)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "field": self.field,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "reasoning": self.reasoning,
            "modification_type": self.modification_type.value,
        }


@dataclass
class ResearchRequest:
    """Request for follow-up research spawned from conversation.

    Attributes:
        focus_area: The area to research (e.g., "correlation with bonds")
        specific_questions: List of questions to investigate
        related_symbols: Symbols relevant to this research
        research_type: Type classification for the research
    """

    focus_area: str
    specific_questions: list[str]
    related_symbols: list[str] = field(default_factory=list)
    research_type: ResearchType = field(default=ResearchType.DEEP_DIVE)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "focus_area": self.focus_area,
            "specific_questions": self.specific_questions,
            "related_symbols": self.related_symbols,
            "research_type": self.research_type.value,
        }


@dataclass
class ConversationResponse:
    """Complete response from the conversation agent.

    Attributes:
        content: The text response content
        modification_proposal: Optional proposal to modify the insight
        research_request: Optional request for follow-up research
    """

    content: str
    modification_proposal: ModificationProposal | None = None
    research_request: ResearchRequest | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "content": self.content,
            "modification_proposal": (
                self.modification_proposal.to_dict()
                if self.modification_proposal
                else None
            ),
            "research_request": (
                self.research_request.to_dict() if self.research_request else None
            ),
        }


# =============================================================================
# SYSTEM PROMPT TEMPLATE
# =============================================================================


INSIGHT_CONVERSATION_SYSTEM_PROMPT = """You are an AI assistant specialized in discussing market insights and trading analysis. You have deep knowledge of the specific insight being discussed and all the underlying research that led to it.

## Your Role
You help users understand, question, and refine market insights. You can:
1. Explain the reasoning behind the insight
2. Discuss the supporting evidence from each analyst
3. Address questions about risk factors and market conditions
4. Help identify if the insight should be modified based on new information
5. Suggest follow-up research when deeper investigation is needed

## Insight Being Discussed

### Overview
- **Title:** {title}
- **Type:** {insight_type}
- **Action:** {action}
- **Confidence:** {confidence:.0%}
- **Time Horizon:** {time_horizon}
- **Primary Symbol:** {primary_symbol}
- **Related Symbols:** {related_symbols}

### Thesis
{thesis}

### Risk Factors
{risk_factors}

### Invalidation Trigger
{invalidation_trigger}

## Analyst Research Context

### Technical Analysis Report
{technical_report}

### Macro Economic Report
{macro_report}

### Sector Strategy Report
{sector_report}

### Risk Analysis Report
{risk_report}

### Correlation Analysis Report
{correlation_report}

### Synthesis Summary
{synthesis_summary}

## Key Data Points
{key_data_points}

## Market Context at Analysis Time
{market_context}

## Response Guidelines

1. **Be specific and data-driven:** Reference the actual numbers, indicators, and findings from the analyst reports.

2. **Acknowledge uncertainty:** When data is unclear or conflicting, say so honestly.

3. **Detect modification intent:** If the user suggests the insight should be updated (e.g., "I think the confidence should be lower" or "We should add a new risk factor"), acknowledge this and structure your response to indicate the proposed change.

4. **Detect research intent:** If the user asks for deeper investigation (e.g., "Can you analyze how this correlates with bonds?" or "What would happen if the Fed raises rates?"), acknowledge this and indicate a follow-up research request.

5. **Structured signals:** When you detect modification or research intent, include these markers in your response:

For modifications, include at the end:
```
[MODIFICATION_DETECTED]
field: <field_name>
old_value: <current_value>
new_value: <proposed_value>
reasoning: <why this change makes sense>
type: <THESIS_UPDATE|CONFIDENCE_CHANGE|RISK_ADDED|RISK_REMOVED|ACTION_CHANGED|TIME_HORIZON_CHANGED>
[/MODIFICATION_DETECTED]
```

For research requests, include at the end:
```
[RESEARCH_REQUESTED]
focus_area: <area to investigate>
questions: <question 1>|<question 2>|<question 3>
symbols: <SYM1>|<SYM2>
type: <SCENARIO_ANALYSIS|DEEP_DIVE|CORRELATION_CHECK|WHAT_IF>
[/RESEARCH_REQUESTED]
```

6. **Conversational tone:** Be helpful and educational, explaining technical concepts when needed.

Remember: You are helping users make better investment decisions by deeply understanding this specific insight and its supporting research."""


# =============================================================================
# INSIGHT CONVERSATION AGENT
# =============================================================================


class InsightConversationAgent:
    """AI agent for contextual conversations about DeepInsights.

    This agent loads the full research context for an insight and engages
    in informed conversations, detecting user intent for modifications
    or follow-up research.

    Example:
        ```python
        agent = InsightConversationAgent()

        # Stream a response
        async for chunk in agent.chat("Why is the confidence so high?", conversation_id=1):
            print(chunk, end="")

        # Get full structured response
        response = await agent.chat_complete("Should we add interest rate risk?", conversation_id=1)
        if response.modification_proposal:
            print(f"Detected modification: {response.modification_proposal}")
        ```
    """

    def __init__(self, timeout_seconds: int = 120) -> None:
        """Initialize the conversation agent.

        Args:
            timeout_seconds: Timeout for LLM queries.
        """
        self.timeout_seconds = timeout_seconds
        self._cache: dict[int, tuple[DeepInsight, InsightResearchContext | None]] = {}

    async def chat(
        self,
        message: str,
        conversation_id: int,
    ) -> AsyncGenerator[str, None]:
        """Stream a response to a user message.

        Args:
            message: The user's message.
            conversation_id: ID of the InsightConversation.

        Yields:
            Text chunks as they stream from the LLM.

        Raises:
            ValueError: If conversation not found.
        """
        # Load conversation and insight context
        conversation, insight, research_context = await self._load_conversation_context(
            conversation_id
        )

        # Build system prompt with research context
        system_prompt = await self._build_system_prompt(insight, research_context)

        # Load conversation history for context
        messages = await self._load_conversation_history(conversation_id)

        # Format messages for the agent
        formatted_history = self._format_conversation_history(messages)

        # Build full prompt with history and new message
        user_prompt = f"{formatted_history}\n\nUser: {message}" if formatted_history else message

        # Stream response via shared client pool
        logger.info(f"[CONV] Starting chat for conversation {conversation_id}")

        # Pool clients have no system prompt -- prepend to user prompt
        combined_prompt = f"""<system_instructions>
{system_prompt}
</system_instructions>

{user_prompt}"""

        pool = get_client_pool()
        async with pool.checkout() as client:
            await client.query(combined_prompt)

            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            yield block.text

    async def chat_complete(
        self,
        message: str,
        conversation_id: int,
    ) -> ConversationResponse:
        """Get a complete response with structured output detection.

        Args:
            message: The user's message.
            conversation_id: ID of the InsightConversation.

        Returns:
            ConversationResponse with content and optional modification/research proposals.

        Raises:
            ValueError: If conversation not found.
        """
        # Collect full response
        full_response = ""
        async for chunk in self.chat(message, conversation_id):
            full_response += chunk

        # Detect intents in response
        modification_proposal = self._detect_modification_intent(full_response)
        research_request = self._detect_research_intent(full_response)

        # Clean response (remove markers)
        clean_content = self._clean_response(full_response)

        return ConversationResponse(
            content=clean_content,
            modification_proposal=modification_proposal,
            research_request=research_request,
        )

    async def save_message(
        self,
        conversation_id: int,
        role: MessageRole,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> InsightConversationMessage:
        """Save a message to the conversation.

        Args:
            conversation_id: ID of the InsightConversation.
            role: Message role (USER, ASSISTANT).
            content: Message content.
            metadata: Optional metadata (token usage, etc.).

        Returns:
            The created message.
        """
        async with async_session_factory() as session:
            message = InsightConversationMessage(
                conversation_id=conversation_id,
                role=role,
                content=content,
                content_type=ContentType.TEXT,
                metadata_=metadata,
            )
            session.add(message)
            await session.commit()
            await session.refresh(message)
            return message

    async def _load_conversation_context(
        self,
        conversation_id: int,
    ) -> tuple[InsightConversation, DeepInsight, InsightResearchContext | None]:
        """Load conversation and its insight context.

        Args:
            conversation_id: ID of the InsightConversation.

        Returns:
            Tuple of (conversation, insight, research_context).

        Raises:
            ValueError: If conversation not found.
        """
        async with async_session_factory() as session:
            # Load conversation with insight
            stmt = (
                select(InsightConversation)
                .options(selectinload(InsightConversation.messages))
                .where(InsightConversation.id == conversation_id)
            )
            result = await session.execute(stmt)
            conversation = result.scalar_one_or_none()

            if not conversation:
                raise ValueError(f"Conversation {conversation_id} not found")

            # Check cache
            insight_id = conversation.deep_insight_id
            if insight_id in self._cache:
                insight, research_context = self._cache[insight_id]
                return conversation, insight, research_context

            # Load insight with research context
            stmt = (
                select(DeepInsight)
                .options(selectinload(DeepInsight.research_context))
                .where(DeepInsight.id == insight_id)
            )
            result = await session.execute(stmt)
            insight = result.scalar_one_or_none()

            if not insight:
                raise ValueError(f"Insight {insight_id} not found")

            research_context = insight.research_context

            # Cache for reuse
            self._cache[insight_id] = (insight, research_context)

            return conversation, insight, research_context

    async def _load_conversation_history(
        self,
        conversation_id: int,
        limit: int = 20,
    ) -> list[InsightConversationMessage]:
        """Load recent conversation history.

        Args:
            conversation_id: ID of the InsightConversation.
            limit: Maximum number of messages to load.

        Returns:
            List of recent messages.
        """
        async with async_session_factory() as session:
            stmt = (
                select(InsightConversationMessage)
                .where(InsightConversationMessage.conversation_id == conversation_id)
                .order_by(InsightConversationMessage.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            messages = list(result.scalars().all())
            # Reverse to get chronological order
            return list(reversed(messages))

    async def _build_system_prompt(
        self,
        insight: DeepInsight,
        research_context: InsightResearchContext | None,
    ) -> str:
        """Build the system prompt with insight and research context.

        Args:
            insight: The DeepInsight being discussed.
            research_context: Optional research context with analyst reports.

        Returns:
            Formatted system prompt string.
        """
        # Format analyst reports
        def format_report(report: dict[str, Any] | None, name: str) -> str:
            if not report:
                return f"*{name} report not available*"
            try:
                # Remove internal keys
                clean = {k: v for k, v in report.items() if not k.startswith("_")}
                return json.dumps(clean, indent=2, default=str)[:3000]  # Limit size
            except Exception:
                return f"*Error formatting {name} report*"

        # Get research context data
        technical_report = ""
        macro_report = ""
        sector_report = ""
        risk_report = ""
        correlation_report = ""
        synthesis_summary = ""
        key_data_points = ""
        market_context = ""

        if research_context:
            technical_report = format_report(research_context.technical_report, "Technical")
            macro_report = format_report(research_context.macro_report, "Macro")
            sector_report = format_report(research_context.sector_report, "Sector")
            risk_report = format_report(research_context.risk_report, "Risk")
            correlation_report = format_report(research_context.correlation_report, "Correlation")

            if research_context.synthesis_summary:
                synthesis_summary = json.dumps(research_context.synthesis_summary, indent=2)

            if research_context.key_data_points:
                key_data_points = "\n".join(f"- {dp}" for dp in research_context.key_data_points)

            if research_context.market_summary_snapshot:
                market_context = json.dumps(research_context.market_summary_snapshot, indent=2)

        # Format insight data
        risk_factors = ""
        if insight.risk_factors:
            risk_factors = "\n".join(f"- {rf}" for rf in insight.risk_factors)

        related_symbols = ", ".join(insight.related_symbols or []) or "None"

        return INSIGHT_CONVERSATION_SYSTEM_PROMPT.format(
            title=insight.title,
            insight_type=insight.insight_type,
            action=insight.action,
            confidence=insight.confidence,
            time_horizon=insight.time_horizon,
            primary_symbol=insight.primary_symbol or "N/A",
            related_symbols=related_symbols,
            thesis=insight.thesis,
            risk_factors=risk_factors or "*No risk factors listed*",
            invalidation_trigger=insight.invalidation_trigger or "*No invalidation trigger specified*",
            technical_report=technical_report or "*Not available*",
            macro_report=macro_report or "*Not available*",
            sector_report=sector_report or "*Not available*",
            risk_report=risk_report or "*Not available*",
            correlation_report=correlation_report or "*Not available*",
            synthesis_summary=synthesis_summary or "*Not available*",
            key_data_points=key_data_points or "*No key data points*",
            market_context=market_context or "*No market context snapshot*",
        )

    def _format_conversation_history(
        self,
        messages: list[InsightConversationMessage],
    ) -> str:
        """Format conversation history for the prompt.

        Args:
            messages: List of conversation messages.

        Returns:
            Formatted history string.
        """
        if not messages:
            return ""

        history_parts = []
        for msg in messages:
            role = "User" if msg.role == MessageRole.USER else "Assistant"
            history_parts.append(f"{role}: {msg.content}")

        return "## Previous Conversation\n" + "\n\n".join(history_parts)

    def _detect_modification_intent(
        self,
        response: str,
    ) -> ModificationProposal | None:
        """Detect if the response contains a modification proposal.

        Args:
            response: The full response text.

        Returns:
            ModificationProposal if detected, None otherwise.
        """
        # Look for modification markers
        pattern = r"\[MODIFICATION_DETECTED\](.*?)\[/MODIFICATION_DETECTED\]"
        match = re.search(pattern, response, re.DOTALL)

        if not match:
            return None

        try:
            block = match.group(1).strip()

            # Parse fields
            field_match = re.search(r"field:\s*(.+?)(?:\n|$)", block)
            old_match = re.search(r"old_value:\s*(.+?)(?:\n|$)", block)
            new_match = re.search(r"new_value:\s*(.+?)(?:\n|$)", block)
            reason_match = re.search(r"reasoning:\s*(.+?)(?:\n|$)", block)
            type_match = re.search(r"type:\s*(.+?)(?:\n|$)", block)

            if not all([field_match, new_match, reason_match]):
                return None

            # Parse modification type
            mod_type = ModificationType.THESIS_UPDATE
            if type_match:
                type_str = type_match.group(1).strip().upper()
                try:
                    mod_type = ModificationType(type_str)
                except ValueError:
                    pass

            return ModificationProposal(
                field=field_match.group(1).strip(),
                old_value=old_match.group(1).strip() if old_match else None,
                new_value=new_match.group(1).strip(),
                reasoning=reason_match.group(1).strip(),
                modification_type=mod_type,
            )

        except Exception as e:
            logger.warning(f"Failed to parse modification intent: {e}")
            return None

    def _detect_research_intent(
        self,
        response: str,
    ) -> ResearchRequest | None:
        """Detect if the response contains a research request.

        Args:
            response: The full response text.

        Returns:
            ResearchRequest if detected, None otherwise.
        """
        # Look for research markers
        pattern = r"\[RESEARCH_REQUESTED\](.*?)\[/RESEARCH_REQUESTED\]"
        match = re.search(pattern, response, re.DOTALL)

        if not match:
            return None

        try:
            block = match.group(1).strip()

            # Parse fields
            focus_match = re.search(r"focus_area:\s*(.+?)(?:\n|$)", block)
            questions_match = re.search(r"questions:\s*(.+?)(?:\n|$)", block)
            symbols_match = re.search(r"symbols:\s*(.+?)(?:\n|$)", block)
            type_match = re.search(r"type:\s*(.+?)(?:\n|$)", block)

            if not all([focus_match, questions_match]):
                return None

            # Parse questions (pipe-separated)
            questions = [q.strip() for q in questions_match.group(1).split("|") if q.strip()]

            # Parse symbols (pipe-separated)
            symbols = []
            if symbols_match:
                symbols = [s.strip() for s in symbols_match.group(1).split("|") if s.strip()]

            # Parse research type
            research_type = ResearchType.DEEP_DIVE
            if type_match:
                type_str = type_match.group(1).strip().upper()
                try:
                    research_type = ResearchType(type_str)
                except ValueError:
                    pass

            return ResearchRequest(
                focus_area=focus_match.group(1).strip(),
                specific_questions=questions,
                related_symbols=symbols,
                research_type=research_type,
            )

        except Exception as e:
            logger.warning(f"Failed to parse research intent: {e}")
            return None

    def _clean_response(self, response: str) -> str:
        """Remove structured markers from response.

        Args:
            response: The full response text.

        Returns:
            Cleaned response without markers.
        """
        # Remove modification block
        response = re.sub(
            r"\[MODIFICATION_DETECTED\].*?\[/MODIFICATION_DETECTED\]",
            "",
            response,
            flags=re.DOTALL,
        )

        # Remove research block
        response = re.sub(
            r"\[RESEARCH_REQUESTED\].*?\[/RESEARCH_REQUESTED\]",
            "",
            response,
            flags=re.DOTALL,
        )

        return response.strip()

    def clear_cache(self, insight_id: int | None = None) -> None:
        """Clear cached insight data.

        Args:
            insight_id: Optional specific insight to clear. If None, clears all.
        """
        if insight_id is not None:
            self._cache.pop(insight_id, None)
        else:
            self._cache.clear()


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================


_agent_instance: InsightConversationAgent | None = None


def get_insight_conversation_agent() -> InsightConversationAgent:
    """Get or create the singleton conversation agent instance.

    Returns:
        The InsightConversationAgent singleton instance.
    """
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = InsightConversationAgent()
    return _agent_instance


# Convenience alias
insight_conversation_agent = get_insight_conversation_agent()
