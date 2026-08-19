"""What the synthesis lead is actually shown.

Before this change the autonomous engine handed synthesis a dict aggregated by
analyst *type*: one technical bucket, one sector bucket, one risk bucket. On the
2026-08-18 run that delivered 5 of 23 technical findings (from 2 of 5 symbols,
because the downstream cap takes a prefix in dict order), 0 of 55 sector
rankings, 0 of 27 recommendations, ``Market Phase: Unknown (0% confidence)``
while every analyst had said mid/late expansion at 0.72-0.82, and this, five
times over, for the risk analyst::

    [AMD] @ $514.39
      Max Drawdown: 0.0%, R/R: 0.0x
      Position Size: N/A, Stop: $0.00

None of those zeros were measurements. The risk analyst had reported a 27.5%
modelled drawdown, a 0.52 reward/risk ratio and a $482 stop -- nested one level
deeper than the names ``_format_risk_report`` read, and nested *differently* for
different symbols in the same run.

The fixtures below are trimmed copies of real stored reports (rows 233-237 of
``insight_research_contexts``), including both observed shapes of
``downside_scenarios``: a list of scenario objects for AMD, a dict keyed by
scenario name for DVN.

Note on the two guard tests at the bottom (``TestDeepAnalysisEngineGuard`` and
``TestResearchContextContract``): those pass before the change as well as after
-- that is their job. They fail only if this change breaks a path it was not
supposed to touch.
"""

from __future__ import annotations

import pytest

from analysis.agent_panel import (
    MAX_PANEL_CHARS_PER_SYMBOL,
    build_symbol_panel,
    select_symbol_reports,
)
from analysis.agents.risk_analyst import (
    normalize_risk_assessment,
    normalize_risk_report,
)
from analysis.agents.synthesis_lead import (
    format_symbol_panel_context,
    format_synthesis_context,
)

# ---------------------------------------------------------------------------
# Fixtures -- trimmed from real stored analyst reports
# ---------------------------------------------------------------------------


def _technical(symbol: str, count: int, bias: str = "BUY") -> dict:
    return {
        "analyst": "technical",
        "findings": [
            {
                "symbol": symbol,
                "signal": f"signal_{index}",
                "description": f"{symbol} finding {index} description",
                "timeframe": "daily",
                "confidence": 0.7,
                "key_levels": {"support": 10.0 + index, "resistance": 20.0 + index},
                "action_bias": bias,
                "indicators_used": ["price_action"],
                "pattern_name": "breakout",
                "price_target": 25.0,
                "stop_loss": 9.0,
            }
            for index in range(1, count + 1)
        ],
        "market_structure": f"{symbol} breakout from consolidation",
        "key_observations": [f"{symbol} observation"],
        "confidence": 0.72,
        "timeframes_analyzed": ["daily"],
        "conflicting_signals": [f"{symbol} MACD histogram still negative"],
    }


def _sector(mentions: str | None = None) -> dict:
    report = {
        "analyst": "sector",
        "market_phase": "mid_expansion",
        "phase_confidence": 0.72,
        "sector_rankings": [
            {"sector": "Energy", "relative_strength": 1.165, "trend": "accelerating"},
            {"sector": "Financials", "relative_strength": 1.036, "trend": "stable"},
            {"sector": "Technology", "relative_strength": 1.035, "trend": "narrowing_breadth"},
        ],
        "recommendations": [
            {
                "sector": "Energy",
                "action": "OVERWEIGHT",
                "rationale": "80% breadth with accelerating momentum. XLE +16.53% monthly.",
            },
            {
                "sector": "Utilities",
                "action": "UNDERWEIGHT",
                "rationale": "Ranks last on RS score with -2.19% monthly return.",
            },
        ],
        "rotation_signals": ["Money flowing from defensives to cyclicals"],
        "key_observations": ["Financials is the #2 ranked sector by relative strength"],
        "confidence": 0.78,
    }
    if mentions:
        report["recommendations"].append(
            {
                "sector": "Financials (EM Exposure)",
                "action": "OVERWEIGHT",
                "rationale": f"{mentions}'s +9.33% surge exemplifies EM fintech catching a bid.",
            }
        )
        report["rotation_signals"].append(
            f"Institutional accumulation confirmed by {mentions} volume surge"
        )
    return report


# AMD: downside_scenarios as a LIST of scenario objects.
RISK_LIST_SHAPE = {
    "analyst": "risk",
    "volatility_regime": {
        "current_vix": 14.25,
        "regime": "low",
        "term_structure": "contango",
        "implication": "Complacent tape",
    },
    "risk_assessments": [
        {
            "symbol": "AMD",
            "current_price": 514.39,
            "realized_vol_20d": "80.4% (EXTREME - top decile for large-cap tech)",
            "atr_14": 32.42,
            "downside_scenarios": [
                {
                    "scenario": "Technical Retest of Support",
                    "target": 424.03,
                    "drawdown_pct": 17.6,
                    "probability": 0.25,
                    "trigger": "Failure to hold squeeze breakout",
                },
                {
                    "scenario": "Max Drawdown Repeat",
                    "target": 373.2,
                    "drawdown_pct": 27.5,
                    "probability": 0.1,
                    "trigger": "Systemic vol spike to 30+",
                },
            ],
            "var_estimates": {"var_95_daily_pct": 5.1, "var_99_daily_pct": 7.2},
            "risk_reward_analysis": {
                "upside_target": 561.47,
                "risk_reward_ratio_moderate": 1.36,
                "risk_reward_ratio_support": 0.52,
                "assessment": "UNFAVORABLE R/R for new positions at current levels.",
            },
            "position_sizing": {
                "conservative": "0.5-1.0% of portfolio",
                "moderate": "1.0-1.5% of portfolio",
                "aggressive": "2.0% maximum",
            },
            "stop_loss_recommendations": {
                "tight_stop": {"level": 495.0, "distance_pct": 3.8},
                "moderate_stop": {"level": 482.0, "distance_pct": 6.3},
            },
            "invalidation_triggers": ["Close below $482 on volume >30M"],
        }
    ],
    "portfolio_risks": ["Semiconductor concentration"],
    "tail_risks": [{"event": "AI narrative reversal", "probability": 0.1, "impact": "high"}],
    "key_observations": ["80.4% realized vol is top decile"],
    "confidence": 0.78,
}

# DVN: downside_scenarios as a DICT keyed by scenario name, stop levels under a
# different key, stop values as {"level": ...} rather than a scalar.
RISK_DICT_SHAPE = {
    "analyst": "risk",
    "volatility_regime": {"current_vix": 14.25, "regime": "low"},
    "risk_assessments": [
        {
            "symbol": "DVN",
            "current_price": 45.85,
            "downside_scenarios": {
                "technical_support": {"level": 42.04, "drawdown_pct": 8.3},
                "oil_collapse_scenario": {
                    "level": 38.0,
                    "drawdown_pct": 17.1,
                    "scenario": "Crude drops to $70",
                },
            },
            "var_95_daily": {"value_pct": 3.5, "value_usd": 1.6},
            "risk_reward_analysis": {
                "upside_target": 50.0,
                "risk_reward_ratio": 1.07,
                "assessment": "Near-term R:R marginally positive.",
            },
            "position_size_recommendations": {
                "conservative": {"allocation": "1.5-2.0% of portfolio"},
                "moderate": {"allocation": "2.5-3.0% of portfolio"},
            },
            "stop_loss_levels": {
                "tight": {"level": 44.51, "pct_risk": 2.9},
                "standard": {"level": 42.0, "pct_risk": 8.4},
            },
            "invalidation_triggers": ["Close below $42.00 on volume >1.5x average"],
        }
    ],
    "portfolio_risks": [],
    "tail_risks": [],
    "key_observations": [],
    "confidence": 0.74,
}


@pytest.fixture
def five_symbol_run() -> dict[str, dict]:
    """One run: five symbols, three analysts each -- the real fan-out shape."""
    return {
        "AMD": {"technical": _technical("AMD", 4), "sector": _sector(), "risk": RISK_LIST_SHAPE},
        "DVN": {"technical": _technical("DVN", 5), "sector": _sector(), "risk": RISK_DICT_SHAPE},
        "CL=F": {"technical": _technical("CL=F", 4), "sector": _sector(), "risk": RISK_DICT_SHAPE},
        "AVGO": {"technical": _technical("AVGO", 5), "sector": _sector(), "risk": RISK_LIST_SHAPE},
        "NU": {"technical": _technical("NU", 5), "sector": _sector(mentions="NU"), "risk": RISK_DICT_SHAPE},
    }


# ---------------------------------------------------------------------------
# Every successful per-symbol report reaches the panel
# ---------------------------------------------------------------------------


class TestNoRunGlobalTruncation:
    def test_every_symbol_and_every_analyst_appears_in_the_panel(self, five_symbol_run):
        panel = build_symbol_panel(five_symbol_run)

        assert [entry["symbol"] for entry in panel["symbols"]] == list(five_symbol_run)
        for entry in panel["symbols"]:
            assert set(entry["reports"]) == {"technical", "sector", "risk"}
            for analyst, view in entry["reports"].items():
                assert view["status"] == "ok", f"{entry['symbol']}/{analyst}"

    def test_every_symbol_contributes_technical_evidence_to_the_prompt(self, five_symbol_run):
        """The old renderer capped findings at 5 across the whole run.

        Symbols three, four and five contributed nothing, and which ones lost
        depended on dict ordering rather than on the analysis.
        """
        rendered = format_symbol_panel_context(build_symbol_panel(five_symbol_run))

        for symbol in five_symbol_run:
            assert f"[{symbol}:technical:1]" in rendered, f"{symbol} lost its technical work"

    def test_the_last_symbol_is_as_visible_as_the_first(self, five_symbol_run):
        rendered = format_symbol_panel_context(build_symbol_panel(five_symbol_run))

        first = rendered.index("SYMBOL: AMD")
        last = rendered.index("SYMBOL: NU")
        # Both blocks carry a stance, a thesis and evidence -- not a header only.
        for start, end in ((first, last), (last, len(rendered))):
            block = rendered[start:end]
            assert "stance:" in block
            assert "thesis:" in block
            assert "evidence for:" in block

    def test_each_analyst_keeps_its_own_confidence(self, five_symbol_run):
        """``(current + new) / 2`` turned five 0.72s into 0.6765625.

        There is no merge here at all: each analyst's number stays attached to
        the analyst and the symbol that produced it.
        """
        panel = build_symbol_panel(five_symbol_run)

        for entry in panel["symbols"]:
            assert entry["reports"]["technical"]["decision"]["confidence"] == 0.72
            assert entry["reports"]["sector"]["decision"]["confidence"] == 0.78
            assert entry["reports"]["risk"]["decision"]["confidence"] in (0.78, 0.74)

    def test_a_failed_analyst_stays_in_the_panel_with_its_status(self, five_symbol_run):
        """Silently omitting a failure makes two reports look like three."""
        five_symbol_run["AMD"]["sector"] = {"analyst": "sector", "error": "timeout after 120s"}

        panel = build_symbol_panel(five_symbol_run)
        amd = next(e for e in panel["symbols"] if e["symbol"] == "AMD")
        assert amd["reports"]["sector"]["status"] == "error"
        assert amd["reports"]["sector"]["error"] == "timeout after 120s"

        rendered = format_symbol_panel_context(panel)
        assert "[SECTOR] status: ERROR -- timeout after 120s" in rendered

    def test_the_builder_does_not_mutate_the_reports_it_is_given(self, five_symbol_run):
        """The flatten wrote ``_symbol`` into findings that were later persisted."""
        import copy

        before = copy.deepcopy(five_symbol_run)
        build_symbol_panel(five_symbol_run)
        assert five_symbol_run == before


# ---------------------------------------------------------------------------
# The sector analyst's work reaches synthesis
# ---------------------------------------------------------------------------


class TestSectorWorkReachesSynthesis:
    def test_rankings_and_recommendations_are_rendered(self, five_symbol_run):
        """``_flatten_analyst_reports`` had no sector branch at all.

        ``sector_rankings`` was initialised to ``[]`` and never written, so a run
        that produced 55 rankings and 27 recommendations rendered three lines,
        one of which was a fabricated default.
        """
        rendered = format_symbol_panel_context(build_symbol_panel(five_symbol_run))

        assert "Energy: RS=1.165 (accelerating)" in rendered
        assert "Financials: RS=1.036 (stable)" in rendered
        assert "Energy: OVERWEIGHT" in rendered
        assert "Utilities: UNDERWEIGHT" in rendered
        assert "80% breadth with accelerating momentum" in rendered
        assert "Money flowing from defensives to cyclicals" in rendered

    def test_the_market_phase_the_analysts_reported_is_the_one_synthesis_sees(
        self, five_symbol_run
    ):
        rendered = format_symbol_panel_context(build_symbol_panel(five_symbol_run))

        assert "Market Phase: mid_expansion (72% confidence)" in rendered
        assert "Unknown (0% confidence)" not in rendered

    def test_a_recommendation_naming_the_target_becomes_that_symbols_stance(
        self, five_symbol_run
    ):
        panel = build_symbol_panel(five_symbol_run)
        nu = next(e for e in panel["symbols"] if e["symbol"] == "NU")

        decision = nu["reports"]["sector"]["decision"]
        assert decision["stance"] == "FAVORABLE"
        assert "names NU" in decision["stance_basis"]
        assert any("EM fintech" in item["claim"] for item in decision["evidence"])

    def test_a_market_wide_answer_is_not_reported_as_a_vote_on_the_symbol(
        self, five_symbol_run
    ):
        """The sector prompt never asks whether the named stock benefits.

        Where the report does not name the target, the panel says so instead of
        inventing a target view.
        """
        panel = build_symbol_panel(five_symbol_run)
        amd = next(e for e in panel["symbols"] if e["symbol"] == "AMD")

        decision = amd["reports"]["sector"]["decision"]
        assert decision["stance"] is None
        assert "never names AMD" in decision["stance_basis"]

    def test_the_shared_table_is_rendered_once_not_once_per_symbol(self, five_symbol_run):
        rendered = format_symbol_panel_context(build_symbol_panel(five_symbol_run))

        assert rendered.count("Sector Rankings (by relative strength):") == 1
        assert rendered.count("Energy: RS=1.165 (accelerating)") == 1


# ---------------------------------------------------------------------------
# The risk report normalises -- both nestings
# ---------------------------------------------------------------------------


class TestRiskNormalisation:
    def test_the_list_shape_of_downside_scenarios_normalises(self):
        assessment = normalize_risk_assessment(RISK_LIST_SHAPE["risk_assessments"][0])

        assert assessment["symbol"] == "AMD"
        assert assessment["current_price"] == 514.39
        assert assessment["max_drawdown_pct"] == 27.5
        assert assessment["risk_reward"] == 0.52  # worst of the two reported ratios
        assert assessment["var_95_daily_pct"] == 5.1
        assert assessment["stop_loss"] == 482.0
        assert assessment["stop_loss_tier"] == "moderate_stop"
        assert assessment["position_size"] == "moderate: 1.0-1.5% of portfolio"
        assert assessment["invalidation"] == ["Close below $482 on volume >30M"]
        assert len(assessment["downside_scenarios"]) == 2
        assert assessment["downside_scenarios"][0]["target"] == 424.03
        assert assessment["downside_scenarios"][0]["probability"] == 0.25

    def test_the_dict_shape_of_downside_scenarios_normalises(self):
        assessment = normalize_risk_assessment(RISK_DICT_SHAPE["risk_assessments"][0])

        assert assessment["symbol"] == "DVN"
        assert assessment["max_drawdown_pct"] == 17.1
        assert assessment["risk_reward"] == 1.07
        assert assessment["var_95_daily_pct"] == 3.5
        assert assessment["stop_loss"] == 42.0
        assert assessment["stop_loss_tier"] == "standard"
        assert assessment["position_size"] == "moderate: 2.5-3.0% of portfolio"
        assert {s["name"] for s in assessment["downside_scenarios"]} == {
            "technical_support",
            "oil_collapse_scenario",
        }

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ({"drawdown_pct": "-12.2%"}, 12.2),
            ({"drawdown_pct": 17.6}, 17.6),
            ({"pct_loss": "-8.1%"}, 8.1),
        ],
    )
    def test_drawdowns_read_the_same_whichever_way_the_model_wrote_them(self, raw, expected):
        assessment = normalize_risk_assessment({"downside_scenarios": [raw]})
        assert assessment["downside_scenarios"][0]["drawdown_pct"] == expected

    def test_prose_numbers_are_read_out_of_their_units(self):
        assessment = normalize_risk_assessment(
            {
                "symbol": "NU",
                "current_price": 15.23,
                "var_estimates": {"daily_var_95": "7.3% (~$1.11)"},
                "stop_loss_levels": {"moderate": "$14.00 (-8.1%, psychological level)"},
            }
        )
        assert assessment["var_95_daily_pct"] == 7.3
        assert assessment["stop_loss"] == 14.0

    def test_fields_the_normaliser_did_not_consume_are_named_not_hidden(self):
        assessment = normalize_risk_assessment(RISK_LIST_SHAPE["risk_assessments"][0])
        assert "atr_14" in assessment["unmapped_fields"]

    def test_the_normalised_numbers_reach_the_rendered_panel(self, five_symbol_run):
        """The measured before-picture: ``Max Drawdown: 0.0%, R/R: 0.0x, Stop: $0.00``."""
        rendered = format_symbol_panel_context(build_symbol_panel(five_symbol_run))

        assert "worst modelled drawdown: 27.5%" in rendered
        assert "reward/risk: 0.52x" in rendered
        assert "stop: $482.00 (moderate_stop)" in rendered
        assert "Max Drawdown: 0.0%" not in rendered
        assert "R/R: 0.0x" not in rendered
        assert "Stop: $0.00" not in rendered

    def test_report_level_normalisation_keeps_tail_and_portfolio_risks(self):
        normalized = normalize_risk_report(RISK_LIST_SHAPE)

        assert normalized["confidence"] == 0.78
        assert normalized["volatility_regime"]["current_vix"] == 14.25
        assert normalized["tail_risks"][0]["event"] == "AI narrative reversal"
        assert normalized["portfolio_risks"] == ["Semiconductor concentration"]


# ---------------------------------------------------------------------------
# Absent is not zero
# ---------------------------------------------------------------------------


class TestAbsentIsNotZero:
    def test_a_risk_report_without_numbers_renders_them_as_absent(self):
        run = {
            "XYZ": {
                "technical": _technical("XYZ", 1),
                "sector": {"analyst": "sector", "confidence": 0.5},
                "risk": {
                    "analyst": "risk",
                    "risk_assessments": [{"symbol": "XYZ"}],
                    "confidence": 0.5,
                },
            }
        }
        panel = build_symbol_panel(run)
        details = panel["symbols"][0]["reports"]["risk"]["details"]
        assert details["current_price"] is None
        assert details["max_drawdown_pct"] is None
        assert details["risk_reward"] is None
        assert details["stop_loss"] is None

        rendered = format_symbol_panel_context(panel)
        assert "price: not reported" in rendered
        assert "worst modelled drawdown: not reported%" in rendered
        assert "stop: not reported" in rendered
        assert "$0.00" not in rendered
        assert "0.0x" not in rendered

    def test_a_missing_market_phase_is_not_reported_as_unknown_at_zero_confidence(self):
        """``Market Phase: Unknown (0% confidence)`` was not absence -- it read
        as a measurement, and it contradicted every analyst in the run."""
        run = {"XYZ": {"sector": {"analyst": "sector", "confidence": 0.5}}}
        panel = build_symbol_panel(run)

        details = panel["symbols"][0]["reports"]["sector"]["details"]
        assert details["market_phase"] is None
        assert details["phase_confidence"] is None

        rendered = format_symbol_panel_context(panel)
        assert "market phase: not reported (not reported phase confidence)" in rendered
        assert "Unknown" not in rendered
        assert "0% confidence" not in rendered

    def test_an_analyst_that_never_ran_says_so_rather_than_reporting_zero(self):
        """The old renderer printed ``MACRO ECONOMIST REPORT / Analyst
        Confidence: 0%`` for an analyst the autonomous pipeline never runs."""
        run = {"XYZ": {"technical": _technical("XYZ", 1)}}
        rendered = format_symbol_panel_context(build_symbol_panel(run))

        assert "[SECTOR] status: MISSING" in rendered
        assert "[RISK] status: MISSING" in rendered
        assert "Analyst Confidence: 0%" not in rendered

    def test_a_stance_that_cannot_be_derived_is_not_stated(self):
        run = {
            "XYZ": {
                "technical": {"analyst": "technical", "findings": [], "confidence": 0.4},
            }
        }
        panel = build_symbol_panel(run)
        decision = panel["symbols"][0]["reports"]["technical"]["decision"]

        assert decision["stance"] is None
        assert "NOT STATED" in format_symbol_panel_context(panel)


# ---------------------------------------------------------------------------
# Evidence IDs and the per-symbol budget
# ---------------------------------------------------------------------------


class TestEvidenceAndBudget:
    def test_every_evidence_id_resolves_to_its_own_symbol_and_analyst(self, five_symbol_run):
        panel = build_symbol_panel(five_symbol_run)

        for entry in panel["symbols"]:
            symbol = entry["symbol"]
            for analyst, view in entry["reports"].items():
                decision = view["decision"] or {}
                for item in (decision.get("evidence") or []) + (
                    decision.get("counter_evidence") or []
                ):
                    assert item["id"].startswith(f"{symbol}:{analyst}:")

    def test_the_budget_is_per_symbol_and_truncation_announces_itself(self):
        """Codex's brief allows a cap; it does not allow a silent one."""
        wordy = _technical("AMD", 4)
        wordy["conflicting_signals"] = [f"conflict {i} " + "x" * 400 for i in range(20)]
        run = {"AMD": {"technical": wordy}, "NU": {"technical": _technical("NU", 2)}}

        rendered = format_symbol_panel_context(build_symbol_panel(run))
        amd_block = rendered[rendered.index("SYMBOL: AMD") : rendered.index("SYMBOL: NU")]

        assert "[truncated:" in amd_block
        assert f"{MAX_PANEL_CHARS_PER_SYMBOL}-character per-symbol budget" in amd_block
        # The other symbol is untouched: the cap does not span symbols.
        assert "[NU:technical:1]" in rendered

    def test_technical_finding_counts_are_stated_when_capped(self, five_symbol_run):
        rendered = format_symbol_panel_context(build_symbol_panel(five_symbol_run))
        assert "findings shown: 3 of 5 (truncated)" in rendered
        assert "findings shown: 3 of 4 (truncated)" in rendered

    def test_conflicting_signals_are_never_dropped_from_the_panel(self, five_symbol_run):
        panel = build_symbol_panel(five_symbol_run)
        amd = next(e for e in panel["symbols"] if e["symbol"] == "AMD")
        claims = [c["claim"] for c in amd["reports"]["technical"]["decision"]["counter_evidence"]]
        assert "AMD MACD histogram still negative" in claims


# ---------------------------------------------------------------------------
# Guard: DeepAnalysisEngine's shared formatter is untouched (recon 7.4)
# ---------------------------------------------------------------------------


class TestDeepAnalysisEngineGuard:
    """``format_synthesis_context`` is also called by ``deep_engine.py:524``
    with an **analyst-keyed** dict, from four production routes. Replacing it in
    place would make those routes render nothing. This test passes before and
    after this change; it fails only if the shared formatter is reshaped."""

    def test_the_analyst_keyed_shape_still_renders_every_section(self):
        rendered = format_synthesis_context(
            {
                "technical": {"findings": [], "confidence": 0.6, "market_structure": "range"},
                "macro": {"confidence": 0.5, "regime": {"growth": "slowing"}},
                "sector": {"confidence": 0.7, "market_phase": "mid_expansion"},
                "risk": {"confidence": 0.65, "risk_assessments": []},
                "correlation": {"confidence": 0.55, "divergences": []},
            }
        )

        assert "TECHNICAL ANALYST REPORT" in rendered
        assert "MACRO ECONOMIST REPORT" in rendered
        assert "SECTOR STRATEGIST REPORT" in rendered
        assert "RISK ANALYST REPORT" in rendered
        assert "CORRELATION DETECTIVE REPORT" in rendered
        assert "Market Structure: range" in rendered

    def test_the_two_formatters_are_separate_entry_points(self):
        assert format_synthesis_context is not format_symbol_panel_context


# ---------------------------------------------------------------------------
# Guard: the per-insight persistence contract (recon 7.2)
# ---------------------------------------------------------------------------


class TestResearchContextContract:
    """198 of 238 stored research contexts carry a real ``sector_report``, and
    ``insight_conversation_agent.py:510`` reads it into every insight
    conversation. This test passes before and after this change; it fails only
    if the selection logic the panel now shares with it changed behaviour."""

    def test_the_conversation_agent_still_gets_the_symbols_three_reports(
        self, five_symbol_run
    ):
        from analysis.agents.macro_scanner import MacroScanResult
        from analysis.autonomous_engine import AutonomousDeepEngine
        from models.deep_insight import DeepInsight

        engine = AutonomousDeepEngine()
        insight = DeepInsight(title="t", thesis="t", primary_symbol="NU")

        context = engine._create_research_context(
            insight=insight,
            analyst_reports=five_symbol_run,
            macro_result=MacroScanResult(),
        )

        assert context.sector_report == five_symbol_run["NU"]["sector"]
        assert context.technical_report == five_symbol_run["NU"]["technical"]
        assert context.risk_report == five_symbol_run["NU"]["risk"]
        assert context.symbols_analyzed == list(five_symbol_run)

    def test_a_failed_report_is_still_persisted_as_none(self, five_symbol_run):
        from analysis.agents.macro_scanner import MacroScanResult
        from analysis.autonomous_engine import AutonomousDeepEngine
        from models.deep_insight import DeepInsight

        five_symbol_run["NU"]["sector"] = {"analyst": "sector", "error": "timeout"}
        engine = AutonomousDeepEngine()

        context = engine._create_research_context(
            insight=DeepInsight(title="t", thesis="t", primary_symbol="NU"),
            analyst_reports=five_symbol_run,
            macro_result=MacroScanResult(),
        )

        assert context.sector_report is None

    def test_the_panel_and_the_persisted_context_select_the_same_reports(
        self, five_symbol_run
    ):
        selected = select_symbol_reports(five_symbol_run, "NU")
        assert selected["sector"] == five_symbol_run["NU"]["sector"]
        assert set(selected) == {"technical", "sector", "risk"}


# ---------------------------------------------------------------------------
# Wiring: both synthesis sites, and the flatten is gone
# ---------------------------------------------------------------------------


class TestSynthesisWiring:
    def test_both_synthesis_sites_build_the_panel(self):
        """There are two synthesis call sites -- heatmap and legacy fallback.

        Fixing only the live one leaves a silent regression on the fallback.
        """
        from pathlib import Path

        source = Path("analysis/autonomous_engine.py").read_text()
        assert source.count("build_symbol_panel(") == 2
        assert source.count("format_symbol_panel_context(") == 2

    def test_the_aggregate_by_analyst_type_flatten_is_gone(self):
        from analysis.autonomous_engine import AutonomousDeepEngine

        assert not hasattr(AutonomousDeepEngine, "_flatten_analyst_reports")
