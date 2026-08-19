"""Defect B -- the specialists must be blind to the selection rationale.

All three deep-dive specialists (technical, sector, risk) used to receive the
run's ``discovery_context`` string as a prefix, ahead of any data.  That string
carries Phase 1-3's *conclusions*: the macro regime call, the heatmap reading
and the reason the name was nominated, the thematic call, the factor/quant
screen and a correlation narrative.  Three analysts handed one conclusion do
not corroborate each other, and the synthesis prompt then read their agreement
as corroboration.  The 2026-08-18 run is the fingerprint: every symbol's risk
report came back with the same ``current_vix`` and the same "SKEW at 138"
narrative.

What replaces it is a neutral decision brief -- the market *state* without the
market *call* -- so that dropping the prefix de-anchors the panel instead of
lobotomising it.  The rationale itself is not deleted from the system: it
reaches synthesis once, labelled ``NOMINATOR PROPOSAL -- NOT INDEPENDENT
CONFIRMATION``, after the private reports already exist.

Everything below inspects the **real assembled prompt strings** captured out of
a real ``_run_heatmap_pipeline`` run with only the LLM and the data adapters
stubbed.  Nothing here asserts against a mock of the thing under test.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from analysis.agents.heatmap_interfaces import (
    HeatmapAnalysis,
    HeatmapData,
    HeatmapPattern,
    HeatmapStockSelection,
)
from analysis.agents.macro_scanner import MacroScanResult, MacroTheme
from analysis.agents.synthesis_lead import SYNTHESIS_LEAD_PROMPT
from analysis.agents.thematic_analyst import ThematicAnalysisResult
from analysis.autonomous_engine import (
    PIPELINE_VERSION,
    AutonomousAnalysisResult,
    AutonomousDeepEngine,
)
from analysis.decision_brief import (
    BRIEF_HEADING,
    MARKET_STATE_HEADING,
    neutral_decision_brief,
)
from analysis.price_freshness import build_freshness, last_weekday
from tests.conftest import TestSessionFactory

SPECIALISTS = ("technical", "sector", "risk")

# ---------------------------------------------------------------------------
# Marker strings.  Each one is a *conclusion* the discovery phase reached, and
# each is planted in the exact field the production builder reads, so a leak
# shows up as the marker appearing in a specialist prompt.
# ---------------------------------------------------------------------------
REGIME_LABEL = "Risk-On"
MACRO_THEME = "AI Capex Supercycle"
MACRO_THEME_RATIONALE = "Hyperscaler capex guidance keeps rising into 2027"
HEATMAP_OVERVIEW = "Classic defensive rotation with Energy leading while megacap semis diverge"
HEATMAP_PATTERN = "Energy leads while semis diverge"
HEATMAP_IMPLICATION = "Late-cycle rotation underway"
SELECTION_REASON = "{sym} was picked because its AI datacenter buildout is accelerating"
SECTOR_TO_WATCH = "Energy"
THEMATIC_META = "The compute supply chain is the only place capex is still rising"
THEMATIC_PROFILE = "{sym} is a GPU supplier levered to the datacenter buildout"
QUANT_NOMINATION = "AMD flagged by the IC-calibrated bottom-up screen at decile 1"

LEAK_MARKERS = (
    REGIME_LABEL,
    MACRO_THEME,
    MACRO_THEME_RATIONALE,
    HEATMAP_OVERVIEW,
    HEATMAP_PATTERN,
    HEATMAP_IMPLICATION,
    SELECTION_REASON.format(sym="AMD"),
    SELECTION_REASON.format(sym="NVDA"),
    THEMATIC_META,
    THEMATIC_PROFILE.format(sym="AMD"),
    THEMATIC_PROFILE.format(sym="NVDA"),
    QUANT_NOMINATION,
    "AUTONOMOUS DISCOVERY CONTEXT",
    "Market Regime",
    "Stock Selection Rationale",
    "Sectors to Watch",
    "Factor Model Scores",
    "IC-Calibrated Quant Signals",
    "THEMATIC ANALYSIS",
)

LAST_BAR = last_weekday(date.today())


def _macro_result() -> MacroScanResult:
    """A macro scan whose conclusions and observations are both populated.

    ``raw_data`` is the pre-LLM fetch -- measurements only -- and is the single
    part of this object the specialists are still allowed to see.
    """
    return MacroScanResult(
        market_regime=REGIME_LABEL,
        regime_confidence=0.76,
        regime_evidence=["Credit spreads at cycle tights"],
        themes=[
            MacroTheme(
                name=MACRO_THEME,
                direction="bullish",
                rationale=MACRO_THEME_RATIONALE,
            )
        ],
        raw_data={
            "volatility": {
                "^VIX": {
                    "name": "CBOE Volatility Index (30-day)",
                    "data": {
                        "current": 14.25,
                        "change_20d_pct": -8.3,
                        "trend": "down",
                        "low_20d": 12.1,
                        "high_20d": 19.4,
                    },
                }
            },
            "treasuries": {
                "^TNX": {
                    "name": "10-Year Treasury Yield",
                    "data": {
                        "current": 4.213,
                        "change_20d_pct": 1.1,
                        "trend": "up",
                        "low_20d": 4.0,
                        "high_20d": 4.4,
                    },
                }
            },
            "us_indices": {
                "^GSPC": {
                    "name": "S&P 500",
                    "data": {
                        "current": 6412.1,
                        "change_20d_pct": 2.14,
                        "trend": "up",
                        "low_20d": 6200.0,
                        "high_20d": 6450.0,
                    },
                }
            },
        },
    )


def _heatmap_analysis(symbols: list[str]) -> HeatmapAnalysis:
    return HeatmapAnalysis(
        overview=HEATMAP_OVERVIEW,
        confidence=0.74,
        sectors_to_watch=[SECTOR_TO_WATCH, "Technology"],
        patterns=[
            HeatmapPattern(
                description=HEATMAP_PATTERN,
                implication=HEATMAP_IMPLICATION,
                sectors=["Energy"],
            )
        ],
        selected_stocks=[
            HeatmapStockSelection(
                symbol=sym,
                sector="Technology",
                priority="high",
                reason=SELECTION_REASON.format(sym=sym),
                opportunity_type="momentum",
            )
            for sym in symbols
        ],
    )


def _two_symbol_context(symbols: list[str]) -> dict[str, Any]:
    """A market context rich enough for all three formatters to render."""
    names = {"AMD": "Advanced Micro Devices", "NVDA": "NVIDIA Corp"}
    prices = {"AMD": 514.39, "NVDA": 187.2}

    def _bars(base: float) -> list[dict[str, Any]]:
        return [
            {
                "date": LAST_BAR.isoformat(),
                "open": base - 2,
                "high": base + 3,
                "low": base - 4,
                "close": base - i * 0.5,
                "volume": 25_000_000 + i * 1000,
            }
            for i in range(30)
        ]

    return {
        "timestamp": LAST_BAR.isoformat(),
        "stocks": [
            {"symbol": s, "name": names[s], "sector": "Technology", "industry": "Semiconductors"}
            for s in symbols
        ],
        "price_history": {s: _bars(prices[s]) for s in symbols},
        "price_freshness": {
            s: build_freshness(s, LAST_BAR, prices[s], "db_close") for s in symbols
        },
        "technical_indicators": {
            s: {"rsi": {"value": 58.2}, "atr": {"value": 6.4}} for s in symbols
        },
        "rich_technical": {
            s: {
                "signal_summary": {
                    "composite_score": 62.0,
                    "rating": "bullish",
                    "confidence": 0.6,
                    "breakdown": {},
                    "key_levels": {
                        "support": [prices[s] * 0.93],
                        "resistance": [prices[s] * 1.07],
                    },
                    "signals": [],
                }
            }
            for s in symbols
        },
        "fundamentals": {s: {"pe_ratio": 31.2, "market_cap": 300_000_000_000} for s in symbols},
        "economic_indicators": [{"name": "Fed Funds Rate", "value": 4.25, "unit": "%"}],
        "sector_performance": {
            "XLK": {
                "sector": "Technology",
                "name": "Technology Select Sector SPDR",
                "current_price": 250.0,
                "as_of": LAST_BAR.isoformat(),
                "daily_change_pct": 0.5,
                "weekly_change_pct": 1.2,
                "monthly_change_pct": 3.4,
                "volume": 9_000_000,
            },
        },
        "market_summary": {
            "market_index": {
                "symbol": "SPY",
                "current": 600.0,
                "date": LAST_BAR.isoformat(),
                "change_pct": 0.3,
                "volume": 80_000_000,
                "high": 601.0,
                "low": 598.0,
            },
        },
    }


@pytest.fixture()
async def captured(monkeypatch, db_session):
    """Run the real heatmap pipeline; return every prompt it built.

    Returns ``{"specialists": {(symbol, analyst): user_prompt},
    "synthesis": user_prompt, "engine": engine}``.  Only the LLM boundary and
    the external data fetches are stubbed -- the discovery context, the
    decision brief, the specialist payload assembly and the synthesis context
    assembly are all the shipped code.
    """
    monkeypatch.setattr(
        "analysis.autonomous_engine.async_session_factory", TestSessionFactory
    )

    catalyst_tracker = MagicMock()
    catalyst_tracker.build_catalyst_context = AsyncMock(return_value=None)
    catalyst_tracker.earnings_adapter.get_upcoming_catalysts = AsyncMock(return_value=[])
    monkeypatch.setattr(
        "analysis.catalyst_tracker.get_catalyst_tracker", lambda: catalyst_tracker
    )

    symbols = ["AMD", "NVDA"]
    engine = AutonomousDeepEngine()

    # The quant nomination and the thematic call, as the live pipeline holds them.
    engine._quant_context = QUANT_NOMINATION
    engine._thematic_result = ThematicAnalysisResult(
        meta_narrative=THEMATIC_META, confidence=0.7
    )

    specialists: dict[tuple[str, str], str] = {}
    synthesis_prompts: list[str] = []

    async def _fake_query_llm(
        system_prompt: str,
        user_prompt: str,
        agent_name: str = "unknown",
        phase: str = "unknown",
        symbol: str = "",
        prompt_preview: str | None = None,
    ) -> str:
        if phase == "deep_dive":
            specialists[(symbol, agent_name)] = user_prompt
            return json.dumps({"confidence": 0.6, "findings": []})
        if phase == "synthesis":
            synthesis_prompts.append(user_prompt)
            return json.dumps({"insights": []})
        return "{}"

    monkeypatch.setattr(engine, "_query_llm", _fake_query_llm)
    monkeypatch.setattr(engine, "_update_task_progress", AsyncMock(return_value=None))
    monkeypatch.setattr(
        engine, "_get_portfolio_holdings",
        AsyncMock(
            return_value={
                "AMD": {"shares": 10, "cost_basis": 400.0, "total_cost": 4000.0}
            }
        ),
    )
    monkeypatch.setattr(engine, "_compute_factor_scores", AsyncMock(return_value={}))
    monkeypatch.setattr(
        engine, "_run_heatmap_analysis",
        AsyncMock(return_value=_heatmap_analysis(symbols)),
    )
    monkeypatch.setattr(
        engine, "_fetch_business_summaries",
        AsyncMock(return_value={s: "Semiconductor company." for s in symbols}),
    )
    monkeypatch.setattr(
        engine, "_enrich_stock_descriptions",
        AsyncMock(
            return_value=(
                {s: THEMATIC_PROFILE.format(sym=s) for s in symbols}, []
            )
        ),
    )
    monkeypatch.setattr(
        engine.context_builder, "build_context",
        AsyncMock(return_value=_two_symbol_context(symbols)),
    )
    monkeypatch.setattr(
        engine, "_build_news_and_sentiment_context", AsyncMock(return_value="")
    )
    monkeypatch.setattr(
        engine, "_build_heatmap_discovery_summary", MagicMock(return_value="")
    )

    await engine._run_heatmap_pipeline(
        result=AutonomousAnalysisResult(analysis_id="blinding-test"),
        macro_result=_macro_result(),
        heatmap_data=HeatmapData(),
        deep_dive_count=2,
        max_insights=2,
        task_id=None,
    )

    assert synthesis_prompts, "the pipeline never reached synthesis"
    return {
        "specialists": specialists,
        "synthesis": synthesis_prompts[0],
        "engine": engine,
        "symbols": symbols,
    }


# ---------------------------------------------------------------------------
# 1. The headline: no upstream conclusion reaches any specialist
# ---------------------------------------------------------------------------


class TestSpecialistsAreBlind:
    async def test_all_three_specialists_ran_for_every_symbol(self, captured):
        """Guard for the rest of the class: absence must mean blinded, not unrun."""
        assert set(captured["specialists"]) == {
            (sym, analyst)
            for sym in captured["symbols"]
            for analyst in SPECIALISTS
        }

    @pytest.mark.parametrize("marker", LEAK_MARKERS)
    async def test_no_specialist_prompt_carries_an_upstream_conclusion(
        self, captured, marker
    ):
        """Zero occurrences, in the real assembled string, for all three.

        Against the pre-fix code every one of these markers appeared in all six
        prompts: ``full_context`` was
        ``target_banner + discovery_context + formatted_context``.
        """
        for (symbol, analyst), prompt in captured["specialists"].items():
            assert marker not in prompt, (
                f"{analyst} analyst for {symbol} was shown '{marker}' -- that is "
                f"an upstream conclusion, not an observation"
            )

    async def test_the_selection_rationale_is_absent_but_was_really_built(
        self, captured
    ):
        """The rationale exists this run; it simply never reached the analysts."""
        assert SELECTION_REASON.format(sym="AMD") in captured["synthesis"]
        for prompt in captured["specialists"].values():
            assert SELECTION_REASON.format(sym="AMD") not in prompt
            assert SELECTION_REASON.format(sym="NVDA") not in prompt

    async def test_blinding_is_all_three_not_just_technical(self, captured):
        """The fallback design blinds technical only. This is not that."""
        for analyst in SPECIALISTS:
            for symbol in captured["symbols"]:
                prompt = captured["specialists"][(symbol, analyst)]
                assert REGIME_LABEL not in prompt
                assert HEATMAP_OVERVIEW not in prompt


# ---------------------------------------------------------------------------
# 2. What the specialists DO get: target, as-of, horizon, mandate, macro state
# ---------------------------------------------------------------------------


class TestTheDecisionBriefReplacesTheAnchor:
    async def test_target_as_of_and_horizon_reach_all_three(self, captured):
        for (symbol, analyst), prompt in captured["specialists"].items():
            assert prompt.startswith(f"TARGET SYMBOL: {symbol}"), analyst
            assert BRIEF_HEADING in prompt
            assert f"Target: {symbol}" in prompt
            assert f"As of: {date.today().isoformat()}" in prompt
            assert "Decision horizon: medium_term -- 30 trading days" in prompt

    async def test_the_long_only_mandate_reaches_all_three(self, captured):
        for prompt in captured["specialists"].values():
            assert "Mandate: long-only" in prompt

    async def test_held_and_not_held_are_distinguished(self, captured):
        """AMD is in the portfolio for this run; NVDA is not."""
        for analyst in SPECIALISTS:
            assert "AMD is ALREADY HELD" in captured["specialists"][("AMD", analyst)]
            assert "NVDA is NOT currently held" in captured["specialists"][("NVDA", analyst)]

    async def test_the_macro_state_still_reaches_all_three(self, captured):
        """The second trap: de-anchoring must not remove the macro input.

        The macro economist was dropped from the deep-dive roster *because*
        every analyst was fed the macro context.  Withdrawing the prefix and
        putting nothing back would leave these three with no macro input at all.
        """
        for (symbol, analyst), prompt in captured["specialists"].items():
            assert MARKET_STATE_HEADING in prompt, analyst
            assert "CBOE Volatility Index (30-day) (^VIX): 14.25" in prompt
            assert "10-Year Treasury Yield (^TNX): 4.213%" in prompt
            assert "S&P 500 (^GSPC): 6,412.10" in prompt
            assert "20D change -8.30%" in prompt

    async def test_the_state_is_shared_but_the_call_is_not(self, captured):
        """The distinction the whole change rests on, asserted on one string."""
        prompt = captured["specialists"][("AMD", "risk")]
        assert "14.25" in prompt                      # the level: shared
        assert "not a regime call" in prompt          # said in-band
        assert REGIME_LABEL not in prompt             # the call: withheld
        assert "regime_evidence" not in prompt
        assert "Credit spreads at cycle tights" not in prompt

    async def test_the_brief_tells_the_analyst_it_is_blinded(self, captured):
        for prompt in captured["specialists"].values():
            assert "PRIVATE, INDEPENDENT reports" in prompt
            assert "deliberately not" in prompt


# ---------------------------------------------------------------------------
# 3. The rationale is retained once, for synthesis, as a proposal
# ---------------------------------------------------------------------------


class TestTheNominatorProposalReachesSynthesisOnce:
    async def test_the_proposal_is_labelled_as_not_confirmation(self, captured):
        synthesis = captured["synthesis"]
        assert "## NOMINATOR PROPOSAL -- NOT INDEPENDENT CONFIRMATION" in synthesis
        assert "It is ONE source making a proposal." in synthesis
        assert "not as a fourth vote" in synthesis

    async def test_synthesis_is_told_the_specialists_did_not_see_it(self, captured):
        assert "did NOT see any of it" in captured["synthesis"]

    @pytest.mark.parametrize(
        "marker",
        [
            REGIME_LABEL,
            MACRO_THEME,
            HEATMAP_OVERVIEW,
            HEATMAP_PATTERN,
            SELECTION_REASON.format(sym="AMD"),
            THEMATIC_META,
            QUANT_NOMINATION,
            THEMATIC_PROFILE.format(sym="AMD"),
        ],
    )
    async def test_each_piece_of_the_proposal_reaches_synthesis_exactly_once(
        self, captured, marker
    ):
        """Retained, not deleted -- and not duplicated into two apparent sources.

        The pre-fix prompt rendered the thematic block and the quant block
        twice: once inside the discovery context and once as their own
        synthesis sections.
        """
        assert captured["synthesis"].count(marker) == 1, (
            f"'{marker}' appears {captured['synthesis'].count(marker)} times in "
            f"the synthesis prompt; it must appear exactly once"
        )

    async def test_the_proposal_precedes_the_panel_but_the_reports_already_exist(
        self, captured
    ):
        """Ordering claim, stated precisely.

        The proposal is shown to synthesis only after the three private reports
        have been produced -- that is a claim about *when*, and the evidence is
        that every specialist prompt was captured before the synthesis prompt
        was, in the same run.
        """
        assert len(captured["specialists"]) == 6
        assert "[TECHNICAL]" in captured["synthesis"]

    async def test_the_proposal_is_not_prefixed_to_any_specialist(self, captured):
        assert "NOMINATOR PROPOSAL" not in "".join(captured["specialists"].values())


# ---------------------------------------------------------------------------
# 4. The synthesis prompt no longer asserts a shared prior
# ---------------------------------------------------------------------------


class TestSynthesisPromptNoLongerClaimsASharedPrior:
    def test_the_shared_prior_sentence_is_gone(self):
        assert "share a prior" not in SYNTHESIS_LEAD_PROMPT
        assert "same discovery context" not in SYNTHESIS_LEAD_PROMPT
        assert "measures common priming" not in SYNTHESIS_LEAD_PROMPT

    def test_the_replacement_states_what_is_now_true(self):
        assert "run blind" in SYNTHESIS_LEAD_PROMPT
        assert "facts-only decision brief" in SYNTHESIS_LEAD_PROMPT
        assert "why the symbol was nominated" in SYNTHESIS_LEAD_PROMPT

    def test_agreement_is_still_not_a_confidence_bonus(self):
        """De-anchoring must not become a licence to count votes."""
        assert "Analyst agreement is NOT a justification" in SYNTHESIS_LEAD_PROMPT
        assert "different observable data" in SYNTHESIS_LEAD_PROMPT
        assert "separately elicited views from one underlying model" in SYNTHESIS_LEAD_PROMPT
        assert "errors stay correlated" in SYNTHESIS_LEAD_PROMPT

    def test_the_prompt_does_not_claim_the_specialists_are_independent(self):
        assert "independent experts" not in SYNTHESIS_LEAD_PROMPT.replace(
            "it does not make them independent experts", ""
        )

    async def test_the_agreement_priority_is_gone_from_both_context_builders(
        self, captured
    ):
        """'- Multiple analyst agreement' was a raw instruction to count votes."""
        assert "Multiple analyst agreement" not in captured["synthesis"]
        assert "different* observable data" in captured["synthesis"]


# ---------------------------------------------------------------------------
# 5. The brief itself, unit level
# ---------------------------------------------------------------------------


class TestNeutralDecisionBrief:
    def test_absent_market_state_is_stated_not_faked(self):
        brief = neutral_decision_brief("AMD", market_state=None)
        assert "Market state was not available" in brief
        assert "0.00" not in brief

    def test_a_level_without_a_number_is_dropped_not_zeroed(self):
        brief = neutral_decision_brief(
            "AMD",
            market_state={
                "volatility": {
                    "^VIX": {"name": "VIX", "data": {"current": None}},
                    "^SKEW": {"name": "SKEW", "data": {"current": 138.0}},
                }
            },
        )
        assert "SKEW (^SKEW): 138.00" in brief
        assert "VIX (^VIX): 0" not in brief
        assert "VIX (^VIX):" not in brief

    def test_an_unresolvable_horizon_is_not_invented(self):
        brief = neutral_decision_brief("AMD", horizon="unknown")
        assert "window unresolvable" in brief
        assert "trading days" not in brief.split("Mandate")[0].split("horizon:")[1]

    def test_the_sector_etf_table_is_not_duplicated_into_the_brief(self):
        """The sector strategist already receives one from its own formatter."""
        brief = neutral_decision_brief(
            "AMD",
            market_state={
                "sector_etfs": {"XLK": {"name": "Technology", "data": {"current": 250.0}}},
                "volatility": {"^VIX": {"name": "VIX", "data": {"current": 14.25}}},
            },
        )
        assert "XLK" not in brief
        assert "VIX (^VIX): 14.25" in brief

    def test_the_brief_is_small_enough_to_be_a_prefix(self):
        """It replaced a multi-kilobyte prefix; it must not become one."""
        brief = neutral_decision_brief("AMD", market_state=_macro_result().raw_data)
        assert len(brief) < 3000


# ---------------------------------------------------------------------------
# 6. Cohorting -- this run's recommendations are not comparable with the last
# ---------------------------------------------------------------------------


class TestPipelineVersionCohort:
    def test_the_version_names_this_change(self):
        assert PIPELINE_VERSION == "v6-blind-specialists"

    async def test_stored_insights_carry_the_cohort_stamp(self, db_session):
        engine = AutonomousDeepEngine()
        stored = await engine._store_insights_from_heatmap(
            session=db_session,
            insights_data=[
                {
                    "insight_type": "opportunity",
                    "action": "HOLD",
                    "title": "AMD setup",
                    "thesis": "Body.",
                    "primary_symbol": "AMD",
                    "confidence": 0.4,
                    "time_horizon": "medium_term",
                    "entry_zone": "$514",
                }
            ],
            macro_result=MacroScanResult(),
            heatmap_analysis=HeatmapAnalysis(),
            pre_context={
                "price_freshness": {
                    "AMD": build_freshness("AMD", LAST_BAR, 514.39, "db_close")
                }
            },
        )
        assert len(stored) == 1
        assert stored[0].discovery_context == {"pipeline_version": PIPELINE_VERSION}

    def test_the_stamp_is_the_key_the_harness_reads(self):
        from analysis.eval_insights import pipeline_version_for

        assert pipeline_version_for(
            None, {"pipeline_version": PIPELINE_VERSION}
        ) == PIPELINE_VERSION
