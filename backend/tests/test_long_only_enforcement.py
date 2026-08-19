"""Tests that the system cannot store a short.

The owner's decision: long positions on stocks only, no shorting. The measured
case for it, on 209 graded directional calls: the system's own BUY/SELL
direction hit 44.98% for +0.40% mean alpha, while going long the same selected
names hit 54.55% for +1.47%. The long calls are identical between the two
rules -- the whole gap is the short book, which was right 13 times out of 46.

The synthesis prompt has always said SELL/STRONG_SELL/BUY_MORE/HOLD are for
held positions only, so a SELL was only ever meant to mean "exit a long you
own". Nothing checked it: all 60 such calls in the database were issued on
symbols the (empty) portfolio never held, which makes them naked shorts.

These tests cover the enforcement, not the prompt's persuasiveness -- except
for one assertion that the constraint is actually stated to the model.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from analysis.agents.heatmap_interfaces import HeatmapAnalysis
from analysis.agents.macro_scanner import MacroScanResult
from analysis.agents.opportunity_hunter import OpportunityList
from analysis.agents.sector_rotator import SectorRotationResult
from analysis.autonomous_engine import AutonomousDeepEngine
from analysis.price_freshness import build_freshness, last_weekday


LIVE_PRICE = 100.0


def _insight(symbol: str, action: str) -> dict[str, Any]:
    """A synthesis-shaped insight whose levels sit at the live price.

    The entry sanity gate is a separate concern, so every insight here is
    priced at the market and passes it -- anything dropped in these tests was
    dropped by the long-only guard.
    """
    return {
        "insight_type": "opportunity",
        "action": action,
        "title": f"{symbol} thesis",
        "thesis": "Thesis body.",
        "primary_symbol": symbol,
        "confidence": 0.6,
        "time_horizon": "medium_term",
        "entry_zone": f"${LIVE_PRICE:.0f}",
        "target_price": f"${LIVE_PRICE * 1.1:.0f}",
        "stop_loss": f"${LIVE_PRICE * 0.9:.0f}",
        "timeframe": "position",
    }


def _fresh_context(symbols: list[str]) -> dict[str, Any]:
    """Context fresh enough that the entry gate prices against it, not a quote."""
    return {
        "price_freshness": {
            sym.upper(): build_freshness(
                sym.upper(), last_weekday(date.today()), LIVE_PRICE, "db_close"
            )
            for sym in symbols
        }
    }


def _engine(held: dict[str, dict[str, float]] | None = None) -> AutonomousDeepEngine:
    """An engine whose portfolio holdings are stubbed to *held*."""
    engine = AutonomousDeepEngine()
    engine._get_portfolio_holdings = AsyncMock(return_value=held or {})  # type: ignore[method-assign]
    return engine


async def _store_heatmap(
    engine: AutonomousDeepEngine, session: Any, insights: list[dict[str, Any]]
) -> list[Any]:
    return await engine._store_insights_from_heatmap(
        session=session,
        insights_data=insights,
        macro_result=MacroScanResult(),
        heatmap_analysis=HeatmapAnalysis(),
        pre_context=_fresh_context([i["primary_symbol"] for i in insights]),
    )


async def _store_legacy(
    engine: AutonomousDeepEngine, session: Any, insights: list[dict[str, Any]]
) -> list[Any]:
    return await engine._store_insights(
        session=session,
        insights_data=insights,
        macro_result=MacroScanResult(),
        sector_result=SectorRotationResult(),
        candidates=OpportunityList(),
        pre_context=_fresh_context([i["primary_symbol"] for i in insights]),
    )


# ---------------------------------------------------------------------------
# A short on a symbol nobody holds never reaches the database
# ---------------------------------------------------------------------------


class TestShortOnUnheldSymbolIsBlocked:
    async def test_heatmap_sell_on_unheld_symbol_is_downgraded(self, db_session):
        engine = _engine(held={})

        stored = await _store_heatmap(engine, db_session, [_insight("TSLA", "SELL")])

        assert [i.action for i in stored] == ["WATCH"]

    async def test_legacy_sell_on_unheld_symbol_is_downgraded(self, db_session):
        engine = _engine(held={})

        stored = await _store_legacy(engine, db_session, [_insight("TSLA", "SELL")])

        assert [i.action for i in stored] == ["WATCH"]

    async def test_downgrade_is_reported_in_run_errors(self, db_session):
        engine = _engine(held={})

        await _store_heatmap(engine, db_session, [_insight("TSLA", "SELL")])

        outcome = engine._last_store_outcome
        assert outcome is not None
        assert outcome.long_only_downgraded == ["TSLA SELL->WATCH"]
        errors = outcome.error_entries()
        assert any("TSLA SELL->WATCH" in e for e in errors)
        assert any("long-only" in e.lower() for e in errors)

    async def test_downgrade_appears_in_the_phase_summary(self, db_session):
        engine = _engine(held={})

        await _store_heatmap(engine, db_session, [_insight("TSLA", "SELL")])

        outcome = engine._last_store_outcome
        assert outcome is not None
        assert any("TSLA SELL->WATCH" in p for p in outcome.summary_parts())

    @pytest.mark.parametrize("action", ["SELL", "STRONG_SELL", "BUY_MORE"])
    async def test_empty_portfolio_can_never_store_a_portfolio_only_action(
        self, db_session, action
    ):
        """With nothing held, no action that presupposes a position survives."""
        engine = _engine(held={})

        stored = await _store_heatmap(engine, db_session, [_insight("TSLA", action)])

        assert len(stored) == 1
        assert stored[0].action not in ("SELL", "STRONG_SELL", "BUY_MORE")

    async def test_bearish_downgrade_lands_on_watch_not_a_buy(self, db_session):
        """A blocked short must not become a long by accident."""
        engine = _engine(held={})

        stored = await _store_heatmap(
            engine, db_session, [_insight("TSLA", "STRONG_SELL")]
        )

        assert [i.action for i in stored] == ["WATCH"]


# ---------------------------------------------------------------------------
# A genuine exit on a position that exists still works
# ---------------------------------------------------------------------------


class TestExitOnHeldPositionSurvives:
    async def test_sell_on_held_symbol_is_stored_unchanged(self, db_session):
        engine = _engine(held={"TSLA": {"shares": 10.0, "total_cost": 1000.0}})

        stored = await _store_heatmap(engine, db_session, [_insight("TSLA", "SELL")])

        assert [i.action for i in stored] == ["SELL"]
        outcome = engine._last_store_outcome
        assert outcome is not None
        assert outcome.long_only_downgraded == []
        assert outcome.error_entries() == []

    async def test_held_symbol_matches_case_insensitively(self, db_session):
        engine = _engine(held={"TSLA": {"shares": 10.0, "total_cost": 1000.0}})

        stored = await _store_heatmap(engine, db_session, [_insight("tsla", "SELL")])

        assert [i.action for i in stored] == ["SELL"]

    @pytest.mark.parametrize("action", ["SELL", "STRONG_SELL", "BUY_MORE"])
    async def test_every_portfolio_action_survives_on_a_held_symbol(
        self, db_session, action
    ):
        engine = _engine(held={"TSLA": {"shares": 10.0, "total_cost": 1000.0}})

        stored = await _store_heatmap(engine, db_session, [_insight("TSLA", action)])

        assert [i.action for i in stored] == [action]

    async def test_only_the_unheld_leg_of_a_mixed_batch_is_downgraded(self, db_session):
        engine = _engine(held={"TSLA": {"shares": 10.0, "total_cost": 1000.0}})

        stored = await _store_heatmap(
            engine,
            db_session,
            [_insight("TSLA", "SELL"), _insight("NVDA", "SELL")],
        )

        assert [(i.primary_symbol, i.action) for i in stored] == [
            ("TSLA", "SELL"),
            ("NVDA", "WATCH"),
        ]
        outcome = engine._last_store_outcome
        assert outcome is not None
        assert outcome.long_only_downgraded == ["NVDA SELL->WATCH"]
        assert outcome.stored == 2


# ---------------------------------------------------------------------------
# Long actions are untouched
# ---------------------------------------------------------------------------


class TestLongActionsAreUnaffected:
    @pytest.mark.parametrize("action", ["BUY", "STRONG_BUY", "HOLD", "WATCH"])
    async def test_action_passes_through_with_an_empty_portfolio(
        self, db_session, action
    ):
        engine = _engine(held={})

        stored = await _store_heatmap(engine, db_session, [_insight("NVDA", action)])

        assert [i.action for i in stored] == [action]
        outcome = engine._last_store_outcome
        assert outcome is not None
        assert outcome.long_only_downgraded == []

    async def test_a_batch_of_longs_never_reads_the_portfolio(self, db_session):
        """The guard costs no query when no insight needs a position."""
        engine = _engine(held={})

        await _store_heatmap(
            engine, db_session, [_insight("NVDA", "BUY"), _insight("AMD", "WATCH")]
        )

        engine._get_portfolio_holdings.assert_not_awaited()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# The synthesis-time normaliser states the same rule
# ---------------------------------------------------------------------------


class TestSynthesisNormaliser:
    def test_bearish_call_on_unheld_symbol_becomes_watch_not_avoid(self):
        """AVOID is not a storable action -- it silently became HOLD.

        ``InsightAction`` has no AVOID member, so the store path's
        ``action not in VALID_ACTIONS`` fallback rewrote every AVOID to HOLD.
        A bearish view was thereby filed as "keep holding it".
        """
        insights = [{"action": "SELL", "primary_symbol": "TSLA"}]

        AutonomousDeepEngine._enforce_portfolio_action_rules(insights, {})

        assert insights[0]["action"] == "WATCH"

    def test_buy_more_on_unheld_symbol_becomes_a_plain_buy(self):
        insights = [{"action": "BUY_MORE", "primary_symbol": "TSLA"}]

        AutonomousDeepEngine._enforce_portfolio_action_rules(insights, {})

        assert insights[0]["action"] == "BUY"

    def test_held_position_keeps_its_exit(self):
        insights = [{"action": "STRONG_SELL", "primary_symbol": "TSLA"}]

        AutonomousDeepEngine._enforce_portfolio_action_rules(
            insights, {"TSLA": {"shares": 10.0, "total_cost": 1000.0}}
        )

        assert insights[0]["action"] == "STRONG_SELL"


# ---------------------------------------------------------------------------
# The model is told
# ---------------------------------------------------------------------------


class TestPromptStatesTheConstraint:
    def test_prompt_declares_the_system_long_only(self):
        from analysis.agents.synthesis_lead import SYNTHESIS_LEAD_PROMPT

        assert "LONG-ONLY SYSTEM" in SYNTHESIS_LEAD_PROMPT
        assert "DOES NOT SHORT" in SYNTHESIS_LEAD_PROMPT

    def test_prompt_says_the_portfolio_only_actions_need_a_position(self):
        from analysis.agents.synthesis_lead import SYNTHESIS_LEAD_PROMPT

        assert (
            "EXCLUSIVELY for stocks listed in\n   Portfolio Holdings"
            in SYNTHESIS_LEAD_PROMPT
        )
        assert "shorting is not permitted" in SYNTHESIS_LEAD_PROMPT

    def test_prompt_closes_the_empty_portfolio_case(self):
        from analysis.agents.synthesis_lead import SYNTHESIS_LEAD_PROMPT

        assert (
            "Portfolio Holdings section below is empty or absent"
            in SYNTHESIS_LEAD_PROMPT
        )

    def test_prompt_no_longer_offers_avoid_as_an_action(self):
        """AVOID was the laundering channel: a short under a different name."""
        from analysis.agents.synthesis_lead import SYNTHESIS_LEAD_PROMPT

        assert "**AVOID**" not in SYNTHESIS_LEAD_PROMPT


# ---------------------------------------------------------------------------
# The other engine. DeepAnalysisEngine is reachable from three production
# routes (api/routes/deep_insights.py:231, api/routes/data.py:251 and :297) and
# had no guard at all: it shares SYNTHESIS_LEAD_PROMPT so it inherited the
# prompt layer, but its store path never called the normaliser, and its own
# action_to_direction maps SELL/STRONG_SELL to "bearish" and starts outcome
# tracking on them. The rule was half true until this closed.
# ---------------------------------------------------------------------------


@pytest.fixture()
def deep_engine(monkeypatch, db_session):
    """A DeepAnalysisEngine whose store path is wired to the test database.

    ``_store_insights`` opens its own session and, once anything is stored,
    runs confidence adjustment and pattern extraction -- both of which call the
    LLM. Those are stubbed out so these tests exercise the guard and nothing
    else.
    """
    from contextlib import asynccontextmanager

    import analysis.deep_engine as deep_engine_mod

    @asynccontextmanager
    async def _session_factory():
        yield db_session

    monkeypatch.setattr(deep_engine_mod, "async_session_factory", _session_factory)
    monkeypatch.setattr(
        deep_engine_mod, "ConfidenceAdjuster", MagicMock(side_effect=RuntimeError)
    )
    monkeypatch.setattr(
        deep_engine_mod, "PatternExtractor", MagicMock(side_effect=RuntimeError)
    )
    return deep_engine_mod.DeepAnalysisEngine()


def _deep_engine_held(engine, held: set[str]) -> None:
    engine._get_held_symbols = AsyncMock(return_value=held)  # type: ignore[method-assign]


class TestDeepEngineIsAlsoGuarded:
    async def test_sell_on_unheld_symbol_is_downgraded(self, deep_engine):
        _deep_engine_held(deep_engine, set())

        stored = await deep_engine._store_insights([_insight("TSLA", "SELL")])

        assert [i.action for i in stored] == ["WATCH"]

    @pytest.mark.parametrize("action", ["SELL", "STRONG_SELL", "BUY_MORE"])
    async def test_empty_portfolio_can_never_store_a_portfolio_only_action(
        self, deep_engine, action
    ):
        _deep_engine_held(deep_engine, set())

        stored = await deep_engine._store_insights([_insight("TSLA", action)])

        assert len(stored) == 1
        assert stored[0].action not in ("SELL", "STRONG_SELL", "BUY_MORE")

    async def test_sell_on_held_symbol_still_exits(self, deep_engine):
        _deep_engine_held(deep_engine, {"TSLA"})

        stored = await deep_engine._store_insights([_insight("TSLA", "SELL")])

        assert [i.action for i in stored] == ["SELL"]

    @pytest.mark.parametrize("action", ["BUY", "STRONG_BUY", "HOLD", "WATCH"])
    async def test_long_actions_pass_through(self, deep_engine, action):
        _deep_engine_held(deep_engine, set())

        stored = await deep_engine._store_insights([_insight("NVDA", action)])

        assert [i.action for i in stored] == [action]

    async def test_a_batch_of_longs_never_reads_the_portfolio(self, deep_engine):
        _deep_engine_held(deep_engine, set())

        await deep_engine._store_insights(
            [_insight("NVDA", "BUY"), _insight("AMD", "WATCH")]
        )

        deep_engine._get_held_symbols.assert_not_awaited()  # type: ignore[attr-defined]

    async def test_downgraded_insight_is_never_tracked_as_bearish(
        self, deep_engine, db_session
    ):
        """The whole point: a blocked short must not enter the graded population.

        ``_start_insight_tracking`` maps SELL/STRONG_SELL to "bearish" and
        starts an InsightOutcome for them. After the downgrade the action is
        WATCH, which is not in its direction map, so it resolves to "neutral"
        and is skipped.
        """
        _deep_engine_held(deep_engine, set())
        stored = await deep_engine._store_insights([_insight("TSLA", "SELL")])

        tracked = await deep_engine._start_insight_tracking(stored, db_session)

        assert tracked == 0

    async def test_a_real_exit_on_a_held_position_is_still_tracked(
        self, deep_engine, db_session, monkeypatch
    ):
        """The guard must not disable tracking for genuine exits."""
        import analysis.deep_engine as deep_engine_mod

        tracker = MagicMock()
        tracker.start_tracking = AsyncMock()
        monkeypatch.setattr(
            deep_engine_mod, "InsightOutcomeTracker", MagicMock(return_value=tracker)
        )
        _deep_engine_held(deep_engine, {"TSLA"})
        stored = await deep_engine._store_insights([_insight("TSLA", "SELL")])

        tracked = await deep_engine._start_insight_tracking(stored, db_session)

        assert tracked == 1
        assert tracker.start_tracking.await_args.kwargs["predicted_direction"] == (
            "bearish"
        )


class TestTheRuleHasOneHome:
    def test_both_engines_import_the_same_function(self):
        """The rule lives in analysis/long_only.py; nothing reimplements it."""
        import analysis.autonomous_engine as auto_mod
        import analysis.deep_engine as deep_mod
        from analysis.long_only import coerce_long_only_action as canonical

        assert auto_mod.coerce_long_only_action is canonical
        assert deep_mod.coerce_long_only_action is canonical
