"""Trade levels must survive storage intact.

The synthesis prompt asks for a numeric level *plus* its condition
("$830 (below 50-day SMA)", "$180 within 3 months"), but the ORM columns were
`String(50)`/`String(30)` and `_level_text()` sliced every value to that width
before both save paths. The result was live rows like
`"$28-30 (wait for regulatory clarity and sector sta"` -- prose that still reads
like a trade instruction with its condition amputated mid-word.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from analysis.autonomous_engine import (
    LEVEL_TEXT_MAX_LEN,
    TIMEFRAME_TEXT_MAX_LEN,
    _level_text,
)
from models.deep_insight import DeepInsight

# Real synthesis output. Both are longer than the old 50-character column and
# both were stored truncated.
ENTRY_PROSE = "$370-385 (only on confirmation of SMA_50 support holding)"
STOP_PROSE = "$350 (below SMA_50 support and prior pivot)"
LIVE_TRUNCATION = "$28-30 (wait for regulatory clarity and sector sta"


class TestLevelText:
    def test_llm_prose_is_stored_whole(self):
        assert _level_text(ENTRY_PROSE) == ENTRY_PROSE
        assert len(ENTRY_PROSE) > 50, "this example must exceed the old width"

    def test_the_reproduced_live_truncation_no_longer_happens(self):
        full = LIVE_TRUNCATION + "bilisation)"
        assert _level_text(full) == full
        assert not _level_text(full).endswith("sector sta")

    def test_a_timeframe_with_a_qualifier_survives(self):
        value = "swing (2-6 weeks, contingent on the Fed meeting)"
        assert _level_text(value, TIMEFRAME_TEXT_MAX_LEN) == value

    def test_absent_and_blank_values_stay_none(self):
        assert _level_text(None) is None
        assert _level_text("   ") is None

    def test_surrounding_whitespace_is_stripped(self):
        assert _level_text("  $150-155  ") == "$150-155"

    def test_a_runaway_value_is_cut_at_a_word_boundary_and_marked(self):
        runaway = "$150-155 " + ("verbose " * 200)
        result = _level_text(runaway)

        assert result is not None
        assert len(result) <= LEVEL_TEXT_MAX_LEN
        assert result.endswith("…"), "truncation must be visible, not silent"
        # A word boundary, not a slice through the middle of a token.
        assert not result.rstrip("…").endswith("verbos")

    def test_a_value_exactly_at_the_limit_is_untouched(self):
        exact = "x" * LEVEL_TEXT_MAX_LEN
        assert _level_text(exact) == exact


class TestColumnWidths:
    def test_the_columns_are_wide_enough_for_the_prose_the_prompt_asks_for(self):
        columns = DeepInsight.__table__.columns
        for name in ("entry_zone", "target_price", "stop_loss"):
            assert columns[name].type.length == LEVEL_TEXT_MAX_LEN, name
        assert columns["timeframe"].type.length == TIMEFRAME_TEXT_MAX_LEN

    @pytest.mark.asyncio
    async def test_prose_levels_round_trip_through_the_database(
        self, db_session: AsyncSession
    ):
        db_session.add(
            DeepInsight(
                insight_type="opportunity",
                action="BUY",
                title="Test insight",
                thesis="Test thesis",
                primary_symbol="ABCD",
                confidence=0.7,
                time_horizon="1-3 months",
                entry_zone=_level_text(ENTRY_PROSE),
                stop_loss=_level_text(STOP_PROSE),
                target_price=_level_text("$420 within 3 months (post-earnings re-rating)"),
                timeframe=_level_text("swing (2-6 weeks)", TIMEFRAME_TEXT_MAX_LEN),
            )
        )
        await db_session.commit()

        stored = (
            await db_session.execute(
                select(DeepInsight).where(DeepInsight.primary_symbol == "ABCD")
            )
        ).scalar_one()

        assert stored.entry_zone == ENTRY_PROSE
        assert stored.stop_loss == STOP_PROSE
        assert stored.entry_zone.endswith(")"), "the condition must not be cut off"

    @pytest.mark.asyncio
    async def test_stored_prose_still_parses_to_the_right_level(
        self, db_session: AsyncSession
    ):
        """Truncation and parsing are one pipeline: a level cut mid-condition
        can also change what the outcome tracker reads back out of it."""
        from analysis.outcome_tracker import InsightOutcomeTracker

        parsed = InsightOutcomeTracker._parse_price_range(_level_text(ENTRY_PROSE))
        assert parsed == (370.0, 385.0)

        stop = InsightOutcomeTracker._parse_price_range(_level_text(STOP_PROSE))
        assert stop == (350.0, 350.0)
