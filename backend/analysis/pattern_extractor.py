"""PatternExtractor - Extracts repeatable trading patterns from conversations and insights.

This module provides the PatternExtractor service that:
1. Analyzes conversation summaries to identify repeatable patterns
2. Extracts patterns from individual insights
3. Merges similar patterns to avoid duplication
4. Validates pattern quality before activation

Uses LLM-based analysis to identify patterns with clear trigger conditions
and expected outcomes that can be tracked over time.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from llm.client_pool import pool_query_llm

from models.knowledge_pattern import KnowledgePattern, PatternType


logger = logging.getLogger(__name__)


# =============================================================================
# EXTRACTION PROMPT TEMPLATE
# =============================================================================


PATTERN_EXTRACTION_PROMPT = """Analyze this market conversation and identify repeatable trading patterns:

CONVERSATION SUMMARY:
{summary}

KEY INSIGHTS:
{insights}

For each pattern found, provide:
1. pattern_name: Short descriptive name
2. pattern_type: One of [TECHNICAL_SETUP, MACRO_CORRELATION, SECTOR_ROTATION, EARNINGS_PATTERN, SEASONALITY, CROSS_ASSET]
3. trigger_conditions: JSON object with measurable conditions
4. expected_outcome: What typically happens when triggered
5. confidence: 0.0-1.0 initial confidence

Respond in JSON array format.

## Example Output Format
```json
[
  {{
    "pattern_name": "RSI Oversold Bounce",
    "pattern_type": "TECHNICAL_SETUP",
    "trigger_conditions": {{
      "rsi_below": 30,
      "volume_surge_pct": 150,
      "price_at_support": true
    }},
    "expected_outcome": "Price rebounds 2-5% within 5 trading days",
    "confidence": 0.7,
    "description": "When RSI drops below 30 with volume surge at key support, expect a short-term bounce."
  }}
]
```

Important guidelines:
- Only identify patterns with CLEAR, MEASURABLE trigger conditions
- Expected outcomes should be specific and testable
- Focus on patterns that could repeat in similar market conditions
- If no clear patterns are found, return an empty array []"""


INSIGHT_PATTERN_PROMPT = """Analyze this market insight to determine if it contains a repeatable trading pattern:

INSIGHT:
Title: {title}
Type: {insight_type}
Action: {action}
Thesis: {thesis}
Confidence: {confidence}
Time Horizon: {time_horizon}
Symbol: {symbol}
Risk Factors: {risk_factors}

Determine if this insight contains an actionable pattern with:
1. Clear trigger conditions (what market state triggers this setup)
2. Expected outcome (what should happen when triggered)
3. Testable criteria (can we verify if it worked)

If a pattern exists, provide:
```json
{{
  "pattern_name": "Short descriptive name",
  "pattern_type": "One of [TECHNICAL_SETUP, MACRO_CORRELATION, SECTOR_ROTATION, EARNINGS_PATTERN, SEASONALITY, CROSS_ASSET]",
  "trigger_conditions": {{
    "condition_key": "value"
  }},
  "expected_outcome": "What typically happens",
  "confidence": 0.5,
  "description": "Full description of the pattern"
}}
```

If NO clear repeatable pattern exists, respond with:
```json
null
```"""


# =============================================================================
# PATTERN EXTRACTOR SERVICE
# =============================================================================


class PatternExtractor:
    """Service for extracting and managing trading patterns from conversations.

    This service uses LLM analysis to identify repeatable patterns from:
    - Conversation summaries with multiple insights
    - Individual insight analyses

    It also handles pattern merging and quality validation.

    Example:
        ```python
        from database import async_session_factory
        from claude_agent_sdk import ClaudeSDKClient

        async with async_session_factory() as session:
            extractor = PatternExtractor(session, llm_client)

            # Extract patterns from a conversation
            patterns = await extractor.extract_from_conversation_summary(
                conversation_id=uuid4(),
                summary="User discussed RSI oversold conditions...",
                insights=[{"title": "Buy AAPL", "thesis": "..."}]
            )

            # Merge similar patterns
            merged_count = await extractor.merge_similar_patterns(threshold=0.85)
        ```
    """

    def __init__(
        self,
        db_session: AsyncSession,
        llm_client: Any | None = None,
        timeout_seconds: int = 120,
    ) -> None:
        """Initialize the pattern extractor.

        Args:
            db_session: Async SQLAlchemy database session for queries.
            llm_client: Optional LLM client. If not provided, uses ClaudeSDKClient.
            timeout_seconds: Timeout for LLM queries.
        """
        self.db = db_session
        self.llm_client = llm_client
        self.timeout_seconds = timeout_seconds

    async def extract_from_conversation_summary(
        self,
        conversation_id: UUID,
        summary: str,
        insights: list[dict[str, Any]],
    ) -> list[KnowledgePattern]:
        """Extract patterns from a conversation summary using LLM analysis.

        Uses the LLM to analyze the conversation summary and identify
        repeatable trading patterns with clear trigger conditions and
        expected outcomes.

        Args:
            conversation_id: UUID of the source conversation.
            summary: Text summary of the conversation.
            insights: List of insight dictionaries from the conversation.

        Returns:
            List of created KnowledgePattern objects linked to the conversation.
        """
        logger.info(
            f"Extracting patterns from conversation {conversation_id}, "
            f"{len(insights)} insights"
        )

        # Build extraction prompt
        prompt = self._build_extraction_prompt(summary, insights)

        # Run LLM analysis
        response = await self._run_llm_extraction(prompt)

        # Parse patterns from response
        pattern_data_list = self._parse_pattern_response(response)

        if not pattern_data_list:
            logger.info("No patterns identified in conversation")
            return []

        # Create KnowledgePattern objects
        created_patterns: list[KnowledgePattern] = []

        for pattern_data in pattern_data_list:
            try:
                pattern = await self._create_pattern(
                    pattern_data=pattern_data,
                    source_conversation_id=conversation_id,
                    extraction_source="conversation",
                )
                created_patterns.append(pattern)
            except Exception as e:
                logger.warning(f"Failed to create pattern: {e}")
                continue

        logger.info(
            f"Created {len(created_patterns)} patterns from conversation {conversation_id}"
        )
        return created_patterns

    async def extract_from_insight(
        self,
        insight: dict[str, Any],
    ) -> KnowledgePattern | None:
        """Extract a pattern from a single insight if it contains actionable setup.

        Analyzes the insight to determine if it contains a repeatable pattern
        with clear trigger conditions. If found, creates a new KnowledgePattern
        with initial success_rate of 0.5 (neutral prior).

        Args:
            insight: Dictionary containing insight data with keys like
                title, thesis, insight_type, action, confidence, etc.

        Returns:
            Created KnowledgePattern if pattern found, None otherwise.
        """
        logger.info(f"Analyzing insight for pattern: {insight.get('title', 'Unknown')}")

        # Build insight analysis prompt
        prompt = self._build_insight_prompt(insight)

        # Run LLM analysis
        response = await self._run_llm_extraction(prompt)

        # Parse single pattern from response
        pattern_data = self._parse_single_pattern_response(response)

        if not pattern_data:
            logger.info("No pattern identified in insight")
            return None

        # Create pattern with neutral prior
        pattern_data["success_rate"] = 0.5
        pattern_data["occurrences"] = 1

        # Enrich pattern_data with symbols from the source insight
        symbols: list[str] = list(pattern_data.get("related_symbols") or [])
        primary_symbol = insight.get("primary_symbol")
        if primary_symbol and primary_symbol not in symbols:
            symbols.insert(0, primary_symbol)
        insight_related = insight.get("related_symbols")
        if isinstance(insight_related, list):
            for sym in insight_related:
                if isinstance(sym, str) and sym and sym not in symbols:
                    symbols.append(sym)
        if symbols:
            pattern_data["related_symbols"] = symbols

        # Enrich pattern_data with sector from the source insight
        insight_sector = insight.get("sector")
        if insight_sector:
            existing_sectors: list[str] = list(pattern_data.get("related_sectors") or [])
            if insight_sector not in existing_sectors:
                existing_sectors.append(insight_sector)
            pattern_data["related_sectors"] = existing_sectors

        try:
            # Get insight_id if available
            source_insight_id = insight.get("id")

            pattern = await self._create_pattern(
                pattern_data=pattern_data,
                source_insight_id=source_insight_id,
                extraction_source="insight",
            )

            logger.info(f"Created pattern from insight: {pattern.pattern_name}")
            return pattern

        except Exception as e:
            logger.warning(f"Failed to create pattern from insight: {e}")
            return None

    async def merge_similar_patterns(
        self,
        threshold: float = 0.85,
    ) -> int:
        """Find and merge patterns with similar conditions and outcomes.

        Uses semantic similarity based on keyword overlap between
        trigger_conditions and expected_outcome to identify duplicates.
        Merges by combining source lists, averaging success_rates weighted
        by occurrences, and keeping the higher-occurrence pattern as primary.

        Args:
            threshold: Similarity threshold (0.0-1.0) for merging. Defaults to 0.85.

        Returns:
            Count of patterns that were merged (deleted).
        """
        logger.info(f"Starting pattern merge with threshold {threshold}")

        # Load all active patterns
        query = select(KnowledgePattern).where(KnowledgePattern.is_active == True)  # noqa: E712
        result = await self.db.execute(query)
        patterns = list(result.scalars().all())

        if len(patterns) < 2:
            logger.info("Not enough patterns to merge")
            return 0

        merged_count = 0
        patterns_to_delete: set[uuid.UUID] = set()

        # Compare each pair of patterns
        for i, pattern_a in enumerate(patterns):
            if pattern_a.id in patterns_to_delete:
                continue

            for pattern_b in patterns[i + 1:]:
                if pattern_b.id in patterns_to_delete:
                    continue

                # Calculate similarity
                similarity = self._calculate_pattern_similarity(pattern_a, pattern_b)

                if similarity >= threshold:
                    logger.info(
                        f"Merging patterns: {pattern_a.pattern_name} <-> {pattern_b.pattern_name} "
                        f"(similarity: {similarity:.2f})"
                    )

                    # Determine primary pattern (higher occurrences)
                    if pattern_b.occurrences > pattern_a.occurrences:
                        primary, secondary = pattern_b, pattern_a
                    else:
                        primary, secondary = pattern_a, pattern_b

                    # Merge into primary
                    self._merge_pattern_data(primary, secondary)

                    # Mark secondary for deletion
                    patterns_to_delete.add(secondary.id)
                    merged_count += 1

        # Delete merged patterns
        for pattern_id in patterns_to_delete:
            query = select(KnowledgePattern).where(KnowledgePattern.id == pattern_id)
            result = await self.db.execute(query)
            pattern = result.scalar_one_or_none()
            if pattern:
                await self.db.delete(pattern)

        await self.db.commit()

        logger.info(f"Merged {merged_count} patterns")
        return merged_count

    async def validate_pattern_quality(
        self,
        pattern: KnowledgePattern,
    ) -> bool:
        """Validate that a pattern meets quality requirements.

        Checks that the pattern has:
        - Clear, measurable trigger_conditions (at least 1 condition)
        - Specific expected_outcome (at least 20 characters)
        - Minimum data points (occurrences >= 2)

        Args:
            pattern: The KnowledgePattern to validate.

        Returns:
            True if pattern passes quality checks, False otherwise.
        """
        issues: list[str] = []

        # Check trigger conditions
        if not pattern.trigger_conditions:
            issues.append("No trigger conditions defined")
        elif len(pattern.trigger_conditions) == 0:
            issues.append("Empty trigger conditions")
        else:
            # Check if conditions are measurable (have numeric or boolean values)
            has_measurable = False
            for value in pattern.trigger_conditions.values():
                if isinstance(value, (int, float, bool)):
                    has_measurable = True
                    break
            if not has_measurable:
                issues.append("Trigger conditions lack measurable values")

        # Check expected outcome
        if not pattern.expected_outcome:
            issues.append("No expected outcome defined")
        elif len(pattern.expected_outcome) < 20:
            issues.append("Expected outcome too vague (< 20 chars)")

        # Check data points
        if pattern.occurrences < 2:
            issues.append(f"Insufficient data points ({pattern.occurrences} < 2)")

        if issues:
            logger.info(
                f"Pattern {pattern.pattern_name} failed quality check: {', '.join(issues)}"
            )
            return False

        logger.info(f"Pattern {pattern.pattern_name} passed quality check")
        return True

    def _build_extraction_prompt(
        self,
        summary: str,
        insights: list[dict[str, Any]],
    ) -> str:
        """Build structured prompt for LLM pattern extraction.

        Args:
            summary: Conversation summary text.
            insights: List of insight dictionaries.

        Returns:
            Formatted prompt string with examples.
        """
        # Format insights for prompt
        insights_text = ""
        for i, insight in enumerate(insights, 1):
            insights_text += f"\n{i}. {insight.get('title', 'Untitled')}\n"
            insights_text += f"   Type: {insight.get('insight_type', 'unknown')}\n"
            insights_text += f"   Action: {insight.get('action', 'unknown')}\n"
            if insight.get("thesis"):
                thesis = insight["thesis"][:300]
                insights_text += f"   Thesis: {thesis}...\n"
            if insight.get("primary_symbol"):
                insights_text += f"   Symbol: {insight['primary_symbol']}\n"

        return PATTERN_EXTRACTION_PROMPT.format(
            summary=summary,
            insights=insights_text or "No specific insights provided.",
        )

    def _build_insight_prompt(self, insight: dict[str, Any]) -> str:
        """Build prompt for single insight pattern analysis.

        Args:
            insight: Insight dictionary.

        Returns:
            Formatted prompt string.
        """
        risk_factors = insight.get("risk_factors", [])
        if isinstance(risk_factors, list):
            risk_factors_text = "\n".join(f"- {rf}" for rf in risk_factors)
        else:
            risk_factors_text = str(risk_factors)

        return INSIGHT_PATTERN_PROMPT.format(
            title=insight.get("title", "Unknown"),
            insight_type=insight.get("insight_type", "unknown"),
            action=insight.get("action", "unknown"),
            thesis=insight.get("thesis", "No thesis provided")[:1000],
            confidence=insight.get("confidence", 0.5),
            time_horizon=insight.get("time_horizon", "unknown"),
            symbol=insight.get("primary_symbol", "N/A"),
            risk_factors=risk_factors_text or "None specified",
        )

    async def _run_llm_extraction(self, prompt: str) -> str:
        """Run LLM extraction with the given prompt.

        Args:
            prompt: The formatted prompt for pattern extraction.

        Returns:
            Raw LLM response text.
        """
        logger.debug("Running LLM pattern extraction")

        system_prompt = (
            "You are an expert market analyst specializing in identifying "
            "repeatable trading patterns. Analyze the provided market discussion "
            "and extract structured pattern data in JSON format. Focus on patterns "
            "with clear, measurable conditions that could be used for systematic trading."
        )

        try:
            response_text = await pool_query_llm(system_prompt, prompt, "pattern_extractor")
            logger.debug(f"LLM extraction response: {len(response_text)} chars")
        except Exception as e:
            logger.exception(f"LLM extraction failed: {e}")
            raise

        return response_text

    def _parse_pattern_response(self, response: str) -> list[dict[str, Any]]:
        """Parse JSON array of patterns from LLM response.

        Args:
            response: Raw LLM response text.

        Returns:
            List of pattern data dictionaries.
        """
        # Try full text as JSON array
        try:
            data = json.loads(response.strip())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

        # Try code blocks
        code_block_pattern = r"```(?:json)?\s*([\s\S]*?)```"
        matches = re.findall(code_block_pattern, response)
        for match in matches:
            try:
                data = json.loads(match.strip())
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                continue

        # Try finding JSON array
        start_idx = response.find("[")
        end_idx = response.rfind("]")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            try:
                data = json.loads(response[start_idx:end_idx + 1])
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass

        logger.warning("Could not parse pattern array from response")
        return []

    def _parse_single_pattern_response(self, response: str) -> dict[str, Any] | None:
        """Parse single pattern or null from LLM response.

        Args:
            response: Raw LLM response text.

        Returns:
            Pattern data dictionary or None.
        """
        # Check for explicit null
        if "null" in response.lower() and "{" not in response:
            return None

        # Try full text as JSON object
        try:
            data = json.loads(response.strip())
            if data is None:
                return None
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        # Try code blocks
        code_block_pattern = r"```(?:json)?\s*([\s\S]*?)```"
        matches = re.findall(code_block_pattern, response)
        for match in matches:
            content = match.strip()
            if content.lower() == "null":
                return None
            try:
                data = json.loads(content)
                if data is None:
                    return None
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                continue

        # Try finding JSON object
        start_idx = response.find("{")
        end_idx = response.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            try:
                data = json.loads(response[start_idx:end_idx + 1])
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass

        logger.warning("Could not parse single pattern from response")
        return None

    async def _create_pattern(
        self,
        pattern_data: dict[str, Any],
        source_conversation_id: UUID | None = None,
        source_insight_id: int | None = None,
        extraction_source: str | None = None,
    ) -> KnowledgePattern:
        """Create and store a KnowledgePattern from extracted data.

        Args:
            pattern_data: Dictionary with pattern fields from LLM.
            source_conversation_id: Optional conversation UUID to link.
            source_insight_id: Optional insight ID to link.
            extraction_source: Origin of the pattern (e.g. "insight", "conversation", "manual").

        Returns:
            Created KnowledgePattern record.
        """
        # Validate and map pattern type
        pattern_type_str = pattern_data.get("pattern_type", "TECHNICAL_SETUP").upper()
        valid_types = {t.value for t in PatternType}
        if pattern_type_str not in valid_types:
            pattern_type_str = "TECHNICAL_SETUP"

        # Build source lists
        source_conversations: list[str] = []
        if source_conversation_id:
            source_conversations.append(str(source_conversation_id))

        source_insights: list[int] = []
        if source_insight_id:
            source_insights.append(source_insight_id)

        # Build related_symbols from pattern data
        related_symbols_set: set[str] = set()
        for key in ("related_symbols", "symbols"):
            val = pattern_data.get(key)
            if isinstance(val, list):
                for s in val:
                    if isinstance(s, str) and s:
                        related_symbols_set.add(s.upper())
        related_symbols: list[str] | None = sorted(related_symbols_set) if related_symbols_set else None

        # Build related_sectors from pattern data
        related_sectors_set: set[str] = set()
        for key in ("related_sectors", "sectors"):
            val = pattern_data.get(key)
            if isinstance(val, list):
                for s in val:
                    if isinstance(s, str) and s:
                        related_sectors_set.add(s)
        related_sectors: list[str] | None = sorted(related_sectors_set) if related_sectors_set else None

        # Create pattern
        pattern = KnowledgePattern(
            pattern_name=pattern_data.get("pattern_name", "Unnamed Pattern")[:200],
            pattern_type=pattern_type_str,
            description=pattern_data.get("description", pattern_data.get("expected_outcome", "")),
            trigger_conditions=pattern_data.get("trigger_conditions", {}),
            expected_outcome=pattern_data.get("expected_outcome", ""),
            success_rate=float(pattern_data.get("confidence", pattern_data.get("success_rate", 0.5))),
            occurrences=int(pattern_data.get("occurrences", 1)),
            successful_outcomes=0,
            source_insights=source_insights if source_insights else None,
            source_conversations=source_conversations if source_conversations else None,
            is_active=True,
            lifecycle_status="draft",
            extraction_source=extraction_source,
            related_symbols=related_symbols,
            related_sectors=related_sectors,
        )

        self.db.add(pattern)
        await self.db.flush()
        await self.db.refresh(pattern)

        logger.info(f"Created pattern: {pattern.pattern_name} (id={pattern.id})")
        return pattern

    def _calculate_pattern_similarity(
        self,
        pattern_a: KnowledgePattern,
        pattern_b: KnowledgePattern,
    ) -> float:
        """Calculate semantic similarity between two patterns.

        Uses keyword overlap between trigger_conditions and expected_outcome
        to determine how similar two patterns are.

        Args:
            pattern_a: First pattern to compare.
            pattern_b: Second pattern to compare.

        Returns:
            Similarity score between 0.0 and 1.0.
        """
        # Must be same pattern type
        if pattern_a.pattern_type != pattern_b.pattern_type:
            return 0.0

        # Extract keywords from trigger conditions
        def get_condition_keys(pattern: KnowledgePattern) -> set[str]:
            keys = set()
            if pattern.trigger_conditions:
                for key in pattern.trigger_conditions.keys():
                    keys.add(key.lower())
            return keys

        keys_a = get_condition_keys(pattern_a)
        keys_b = get_condition_keys(pattern_b)

        # Jaccard similarity for condition keys
        if not keys_a and not keys_b:
            condition_similarity = 1.0
        elif not keys_a or not keys_b:
            condition_similarity = 0.0
        else:
            intersection = len(keys_a & keys_b)
            union = len(keys_a | keys_b)
            condition_similarity = intersection / union if union > 0 else 0.0

        # Extract keywords from expected outcome
        def get_outcome_words(pattern: KnowledgePattern) -> set[str]:
            words = set()
            if pattern.expected_outcome:
                # Simple word extraction
                for word in re.findall(r"\b\w+\b", pattern.expected_outcome.lower()):
                    if len(word) > 3:  # Skip short words
                        words.add(word)
            return words

        words_a = get_outcome_words(pattern_a)
        words_b = get_outcome_words(pattern_b)

        # Jaccard similarity for outcome words
        if not words_a and not words_b:
            outcome_similarity = 1.0
        elif not words_a or not words_b:
            outcome_similarity = 0.0
        else:
            intersection = len(words_a & words_b)
            union = len(words_a | words_b)
            outcome_similarity = intersection / union if union > 0 else 0.0

        # Weight conditions more heavily (60% conditions, 40% outcome)
        similarity = 0.6 * condition_similarity + 0.4 * outcome_similarity

        return similarity

    def _merge_pattern_data(
        self,
        primary: KnowledgePattern,
        secondary: KnowledgePattern,
    ) -> None:
        """Merge secondary pattern data into primary pattern.

        Combines source lists, averages success_rates weighted by occurrences,
        and updates the primary pattern in-place.

        Args:
            primary: Pattern to keep (modified in-place).
            secondary: Pattern to merge from (will be deleted).
        """
        # Combine source_insights
        primary_insights = set(primary.source_insights or [])
        secondary_insights = set(secondary.source_insights or [])
        combined_insights = list(primary_insights | secondary_insights)
        primary.source_insights = combined_insights if combined_insights else None

        # Combine source_conversations
        primary_convs = set(primary.source_conversations or [])
        secondary_convs = set(secondary.source_conversations or [])
        combined_convs = list(primary_convs | secondary_convs)
        primary.source_conversations = combined_convs if combined_convs else None

        # Weighted average of success_rates
        total_occurrences = primary.occurrences + secondary.occurrences
        if total_occurrences > 0:
            weighted_success = (
                primary.success_rate * primary.occurrences
                + secondary.success_rate * secondary.occurrences
            ) / total_occurrences
            primary.success_rate = weighted_success

        # Sum successful outcomes
        primary.successful_outcomes += secondary.successful_outcomes

        # Sum occurrences
        primary.occurrences = total_occurrences

        # Merge trigger conditions (keep primary's, add any new from secondary)
        if secondary.trigger_conditions:
            combined_conditions = dict(primary.trigger_conditions or {})
            for key, value in secondary.trigger_conditions.items():
                if key not in combined_conditions:
                    combined_conditions[key] = value
            primary.trigger_conditions = combined_conditions

        # Keep primary's description but append note about merge
        if secondary.description and secondary.description != primary.description:
            primary.description = f"{primary.description}\n[Merged from: {secondary.pattern_name}]"

        logger.debug(
            f"Merged pattern {secondary.pattern_name} into {primary.pattern_name}"
        )


# =============================================================================
# FACTORY FUNCTION
# =============================================================================


async def get_pattern_extractor(db_session: AsyncSession) -> PatternExtractor:
    """Factory function to create a PatternExtractor.

    Args:
        db_session: Async SQLAlchemy database session.

    Returns:
        Configured PatternExtractor instance.
    """
    return PatternExtractor(db_session)
