"""One-time backfill script to extract patterns and start outcome tracking.

Since pattern extraction was broken (KeyError on curly braces in prompt templates,
fixed in commit 4f3bb9d), all previous analysis runs produced no patterns.
This script re-runs PatternExtractor on all existing DeepInsight records and
also starts outcome tracking for insights that have primary symbols but no outcomes.

Usage:
    cd backend && uv run python scripts/backfill_patterns.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add backend to path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # type: ignore[import-not-found]  # noqa: E402

from database import async_session_factory, init_db  # type: ignore[import-not-found]  # noqa: E402
from models.deep_insight import DeepInsight  # type: ignore[import-not-found]  # noqa: E402
from models.insight_outcome import InsightOutcome  # type: ignore[import-not-found]  # noqa: E402
from models.knowledge_pattern import KnowledgePattern  # type: ignore[import-not-found]  # noqa: E402
from analysis.pattern_extractor import PatternExtractor  # type: ignore[import-not-found]  # noqa: E402
from analysis.outcome_tracker import InsightOutcomeTracker  # type: ignore[import-not-found]  # noqa: E402

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backfill_patterns")

# Suppress noisy loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def _action_to_direction(action: str) -> str:
    """Map DeepInsight action to predicted direction for outcome tracking."""
    action_upper = action.upper() if action else ""
    if action_upper in ("STRONG_BUY", "BUY"):
        return "bullish"
    elif action_upper in ("STRONG_SELL", "SELL"):
        return "bearish"
    else:
        return "neutral"


async def backfill_patterns() -> None:
    """Extract patterns from all existing DeepInsight records."""
    await init_db()

    async with async_session_factory() as session:
        # Load all insights
        result = await session.execute(
            select(DeepInsight).order_by(DeepInsight.id.asc())
        )
        insights = list(result.scalars().all())
        logger.info(f"Found {len(insights)} total DeepInsight records")

        if not insights:
            logger.info("No insights to process. Exiting.")
            return

        # Check existing patterns
        pattern_count_result = await session.execute(
            select(KnowledgePattern)
        )
        existing_patterns = len(list(pattern_count_result.scalars().all()))
        logger.info(f"Existing patterns in DB: {existing_patterns}")

        extractor = PatternExtractor(session)
        created = 0
        skipped = 0
        failed = 0

        for insight in insights:
            insight_dict = {
                "id": insight.id,
                "title": insight.title,
                "insight_type": insight.insight_type,
                "action": insight.action,
                "thesis": insight.thesis,
                "confidence": insight.confidence,
                "time_horizon": insight.time_horizon,
                "primary_symbol": insight.primary_symbol,
                "related_symbols": insight.related_symbols,
                "risk_factors": insight.risk_factors,
                "sector": None,
            }

            # Try to extract sector from discovery_context if available
            if insight.discovery_context and isinstance(insight.discovery_context, dict):
                sector_data = insight.discovery_context.get("sector_signals", {})
                if isinstance(sector_data, dict):
                    # Pick first sector mentioned
                    sectors = list(sector_data.keys())
                    if sectors:
                        insight_dict["sector"] = sectors[0]

            logger.info(
                f"[{insight.id}/{insights[-1].id}] Processing: {insight.title[:60]}..."
            )

            try:
                pattern = await extractor.extract_from_insight(insight_dict)
                if pattern:
                    created += 1
                    logger.info(
                        f"  -> Pattern created: {pattern.pattern_name} "
                        f"(type={pattern.pattern_type})"
                    )
                else:
                    skipped += 1
                    logger.info("  -> No pattern identified")
            except Exception as e:
                failed += 1
                logger.error(f"  -> Failed: {e}")

        # Commit all patterns
        await session.commit()
        logger.info(
            f"\nPattern extraction complete: "
            f"{created} created, {skipped} skipped, {failed} failed"
        )


async def backfill_outcomes() -> None:
    """Start outcome tracking for insights with symbols but no outcomes."""
    async with async_session_factory() as session:
        # Find insights with primary_symbol but no outcome
        result = await session.execute(
            select(DeepInsight)
            .outerjoin(InsightOutcome, DeepInsight.id == InsightOutcome.insight_id)
            .where(DeepInsight.primary_symbol.isnot(None))
            .where(DeepInsight.primary_symbol != "")
            .where(InsightOutcome.id.is_(None))
            .order_by(DeepInsight.id.asc())
        )
        insights_needing_outcomes = list(result.scalars().all())
        logger.info(
            f"Found {len(insights_needing_outcomes)} insights needing outcome tracking"
        )

        if not insights_needing_outcomes:
            logger.info("No outcomes to backfill. Exiting.")
            return

        tracker = InsightOutcomeTracker(session)
        started = 0
        failed = 0

        for insight in insights_needing_outcomes:
            symbol = insight.primary_symbol
            # Skip generic/non-tradable symbols
            if symbol and symbol.upper() in ("PORTFOLIO", "MARKET", "INDEX", "N/A"):
                logger.info(
                    f"  Skipping non-tradable symbol: {symbol} "
                    f"(insight {insight.id})"
                )
                continue

            direction = _action_to_direction(insight.action)
            logger.info(
                f"[{insight.id}] Starting tracking: {symbol} ({direction}) - "
                f"{insight.title[:50]}..."
            )

            try:
                await tracker.start_tracking(
                    insight_id=insight.id,
                    symbol=symbol,
                    predicted_direction=direction,
                    tracking_days=20,
                )
                started += 1
            except Exception as e:
                failed += 1
                logger.warning(f"  -> Failed to start tracking for {symbol}: {e}")

        logger.info(
            f"\nOutcome tracking backfill complete: "
            f"{started} started, {failed} failed"
        )


async def main() -> None:
    """Run all backfill operations."""
    logger.info("=" * 60)
    logger.info("BACKFILL: Pattern Extraction & Outcome Tracking")
    logger.info("=" * 60)

    logger.info("\n--- Phase 1: Pattern Extraction ---")
    await backfill_patterns()

    logger.info("\n--- Phase 2: Outcome Tracking ---")
    await backfill_outcomes()

    logger.info("\n--- Backfill Complete ---")


if __name__ == "__main__":
    asyncio.run(main())
