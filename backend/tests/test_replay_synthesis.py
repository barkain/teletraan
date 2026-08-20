"""The replay harness, tested without a single LLM call.

``analysis.replay_synthesis`` answers one question: shown the *same* stored
analyst evidence, does the synthesis lead decide differently under the old
run-global aggregate than under the new per-symbol panel?  The answer is only
worth reading if the harness itself is honest, so what is pinned here is the
harness's own machinery:

* the two arms really do render different text from identical input;
* ARM A really does reproduce the historical ``findings[:5]`` truncation, and
  ARM B really does not (that truncation is the defect under measurement -- a
  reproduction that silently repaired it would measure nothing);
* the vendored historical flatten does not leak its ``_symbol`` mutation into
  the caller's dicts, which is what would let ARM A contaminate ARM B;
* grading goes through ``analysis.eval_insights`` rather than any local
  arithmetic, checked against that module on a known case;
* ``--scope-to-symbol`` moves both arms or neither;
* the response cache prevents a second call, which is what makes a re-run free.

Every test here is deterministic and offline: the LLM is a counting stub.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from analysis import eval_insights
from analysis.agent_panel import build_symbol_panel
from analysis.agents.synthesis_lead import format_synthesis_context
from analysis.replay_synthesis import (
    ARM_NEW,
    ARM_OLD,
    CLI_OVERHEAD_INPUT_TOKENS,
    ArmResult,
    ReplayCase,
    _scope_reports_to_symbol,
    _selection_breakdown,
    build_prompt,
    estimate_cost,
    evidence_shape,
    flatten_analyst_reports_historical,
    grade_arm,
    panel_evidence_ids,
    prompt_hash,
    render_arm_context,
    run_arm,
    sample_cases,
)

# ---------------------------------------------------------------------------
# Fixtures -- shaped like the real stored rows: a basket-wide technical report
# ---------------------------------------------------------------------------

TARGET = "NVDA"
BASKET = ["AAPL", "MSFT", "AMZN", "META", "TSLA", "GOOG", TARGET, "AMD"]


def _technical_report(symbols: list[str] = BASKET) -> dict:
    """A basket-wide technical report: eight findings, the target seventh.

    Seventh matters.  ``format_synthesis_context`` renders ``findings[:5]``, so
    the target's own finding falls outside the prefix -- exactly the production
    condition measured in ``evidence_shape``.
    """
    return {
        "analyst": "technical",
        "confidence": 0.7,
        "market_structure": "Mixed tape, breadth narrowing",
        "key_observations": ["Breadth narrowing", "Semis leading"],
        "timeframes_analyzed": ["daily", "weekly"],
        "conflicting_signals": ["Volume not confirming the move"],
        "findings": [
            {
                "symbol": symbol,
                "signal": f"signal_{index}",
                "description": f"{symbol} setup number {index}",
                "timeframe": "daily",
                "confidence": 0.6 + index / 100,
                "key_levels": {"support": 100 + index, "resistance": 120 + index},
                "action_bias": "BUY" if index % 2 else "HOLD",
                "price_target": 130 + index,
                "stop_loss": 95 + index,
            }
            for index, symbol in enumerate(symbols)
        ],
    }


def _sector_report() -> dict:
    return {
        "analyst": "sector",
        "confidence": 0.66,
        "market_phase": "mid_expansion",
        "phase_confidence": 0.74,
        "sector_rankings": [
            {"sector": "Technology", "relative_strength": 1.32, "trend": "improving"},
            {"sector": "Energy", "relative_strength": 1.16, "trend": "flat"},
        ],
        "recommendations": [
            {
                "sector": "Technology",
                "action": "OVERWEIGHT",
                "rationale": f"{TARGET} leads the group on relative strength",
            },
        ],
        "rotation_signals": ["Money rotating from staples into semis"],
        "key_observations": ["Tech relative strength at a 6-month high"],
    }


def _risk_report(symbols: list[str] = BASKET) -> dict:
    return {
        "analyst": "risk",
        "confidence": 0.62,
        "volatility_regime": {"current_vix": 14.25, "regime": "low", "term_structure": "contango"},
        "risk_assessments": [
            {
                "symbol": symbol,
                "current_price": 200.0 + index,
                "max_drawdown_pct": 20.0 + index,
                "risk_reward": 1.8,
                "stop_loss": 180.0 + index,
                "risk_reward_note": f"{symbol} reward outweighs modelled downside",
                "downside_scenarios": [
                    {"name": "macro shock", "drawdown_pct": 18.0, "probability": 0.2},
                ],
            }
            for index, symbol in enumerate(symbols)
        ],
        "tail_risks": [{"event": "rate shock", "probability": 0.15, "impact": "high"}],
        "portfolio_risks": ["Concentration in semis"],
        "key_observations": ["Vol is cheap relative to realised"],
    }


def _reports() -> dict:
    return {
        "technical": _technical_report(),
        "sector": _sector_report(),
        "risk": _risk_report(),
    }


def _case(insight_id: int = 1, symbol: str = TARGET, day: str = "2026-05-04") -> ReplayCase:
    return ReplayCase(
        insight_id=insight_id,
        symbol=symbol,
        created_at=datetime.fromisoformat(f"{day}T20:00:00"),
        time_horizon="medium_term",
        stored_action="BUY",
        stored_confidence=0.71,
        pipeline_version="test",
        reports=_reports(),
    )


def _series(start: date, days: int, first: float, step: float) -> list[tuple[date, float]]:
    """A gapless daily close series -- enough bars for a 30-bar window to close."""
    return [(start + timedelta(days=offset), first + step * offset) for offset in range(days)]


# ---------------------------------------------------------------------------
# The two arms render different text
# ---------------------------------------------------------------------------


class TestArmsDiffer:
    def test_identical_reports_render_differently(self):
        case = _case()
        old = render_arm_context(ARM_OLD, case)
        new = render_arm_context(ARM_NEW, case)

        assert old != new
        assert "MULTI-ANALYST MARKET ANALYSIS REPORT" in old
        assert "PER-SYMBOL ANALYST PANEL" in new
        assert "PER-SYMBOL ANALYST PANEL" not in old

    def test_only_the_new_arm_issues_citable_evidence_ids(self):
        case = _case()
        ids = panel_evidence_ids(build_symbol_panel({case.symbol: case.reports}))
        assert ids, "the panel must issue citable IDs or the citation check is vacuous"
        new = render_arm_context(ARM_NEW, case)
        old = render_arm_context(ARM_OLD, case)
        assert any(evidence_id in new for evidence_id in ids)
        assert not any(evidence_id in old for evidence_id in ids)

    def test_both_arms_get_the_same_task_block(self):
        case = _case()
        old_system, old_user = build_prompt(ARM_OLD, case)
        new_system, new_user = build_prompt(ARM_NEW, case)

        assert old_system == new_system, "the system prompt must not differ between arms"
        task = old_user.split("=" * 60)[0]
        assert task and new_user.startswith(task), (
            "any asymmetry in the task block is indistinguishable from a "
            "representation effect in the result"
        )
        assert case.as_of in task and case.symbol in task


# ---------------------------------------------------------------------------
# The historical truncation
# ---------------------------------------------------------------------------


class TestHistoricalTruncation:
    def test_old_arm_drops_all_but_five_findings(self):
        case = _case()
        rendered = render_arm_context(ARM_OLD, case)

        shown = [s for s in BASKET if f"[{s}]" in rendered]
        assert len(shown) == 5, (
            "format_synthesis_context renders findings[:5]; reproducing that cap "
            f"is the point of ARM A, but {len(shown)} symbols appeared"
        )
        assert shown == BASKET[:5]
        assert TARGET not in shown, (
            "the fixture puts the target seventh precisely so the prefix cap "
            "drops it, as it did in production"
        )

    def test_new_arm_does_not_apply_a_run_global_cap(self):
        case = _case()
        rendered = render_arm_context(ARM_NEW, case)
        panel_view = build_symbol_panel({case.symbol: case.reports})
        details = panel_view["symbols"][0]["reports"]["technical"]["details"]

        assert details["findings_total"] == len(BASKET)
        assert f"{details['findings_total']}" in rendered, (
            "the panel states how many findings existed, so truncation is never silent"
        )
        # Every risk assessment reaches the panel's own accounting rather than
        # being cut to a prefix of five before it is ever seen.
        assert "PER-SYMBOL ANALYST PANEL" in rendered

    def test_evidence_shape_counts_the_dropped_target_finding(self):
        shape = evidence_shape([_case()])
        assert shape["basket_wide_technical_reports"] == 1
        assert shape["cases_whose_basket_names_the_target"] == 1
        assert shape["target_finding_dropped_by_old_arm_cap"] == 1
        assert shape["target_finding_survives_old_arm_cap"] == 0


# ---------------------------------------------------------------------------
# The vendored flatten must not leak into the other arm
# ---------------------------------------------------------------------------


class TestVendoredFlatten:
    def test_reproduces_the_running_average_confidence(self):
        # (0.0 + 0.7) / 2 -- the defect, kept verbatim.  The technical analyst
        # said 0.70; the flatten reported 0.35.
        flat = flatten_analyst_reports_historical({TARGET: _reports()})
        assert flat["technical"]["confidence"] == pytest.approx(0.35)

    def test_has_no_sector_branch(self):
        # The keys were initialised and never written, which is why 55 sector
        # rankings per run reached synthesis as an empty list.
        flat = flatten_analyst_reports_historical({TARGET: _reports()})
        assert flat["sector"]["sector_rankings"] == []
        assert flat["sector"]["confidence"] == pytest.approx(0.33)

    def test_does_not_mutate_the_callers_reports(self):
        reports = _reports()
        flatten_analyst_reports_historical({TARGET: reports})
        assert all(
            "_symbol" not in finding for finding in reports["technical"]["findings"]
        ), "ARM A's in-place mutation must not reach the dicts ARM B renders"

    def test_still_performs_the_mutation_on_its_own_copy(self):
        flat = flatten_analyst_reports_historical({TARGET: _reports()})
        assert all(f["_symbol"] == TARGET for f in flat["technical"]["findings"])


# ---------------------------------------------------------------------------
# Symmetric scoping
# ---------------------------------------------------------------------------


class TestScopeToSymbol:
    def test_scoping_filters_both_arms(self):
        case = _case()
        old_plain = render_arm_context(ARM_OLD, case)
        new_plain = render_arm_context(ARM_NEW, case)
        old_scoped = render_arm_context(ARM_OLD, case, scope_to_symbol=True)
        new_scoped = render_arm_context(ARM_NEW, case, scope_to_symbol=True)

        assert old_scoped != old_plain
        assert new_scoped != new_plain
        assert f"[{TARGET}]" in old_scoped, "scoping must let the target survive the cap"
        assert "AAPL" not in old_scoped
        assert "AAPL" not in new_scoped

    def test_scoping_leaves_a_report_that_names_nothing_alone(self):
        # Emptying a report would be a different experiment ("what does
        # synthesis do with nothing"), not a scoped one.
        reports = {"technical": _technical_report(["AAPL", "MSFT"])}
        scoped = _scope_reports_to_symbol(reports, TARGET)
        assert len(scoped["technical"]["findings"]) == 2

    def test_scoping_does_not_mutate_the_input(self):
        reports = _reports()
        _scope_reports_to_symbol(reports, TARGET)
        assert len(reports["technical"]["findings"]) == len(BASKET)


# ---------------------------------------------------------------------------
# Grading goes through eval_insights
# ---------------------------------------------------------------------------


class TestGrading:
    def test_matches_eval_insights_build_record_on_a_known_case(self):
        start = date(2026, 5, 1)
        symbol_series = _series(start, 90, 100.0, 0.5)   # steadily up
        benchmark_series = _series(start, 90, 400.0, 0.4)
        case = _case(day="2026-05-04")
        result = ArmResult(
            arm=ARM_NEW, insight_id=case.insight_id, symbol=case.symbol,
            prompt_sha="x", context_chars=0, from_cache=False,
            parsed=True, action="BUY", confidence=0.8, time_horizon="medium_term",
        )

        record, reason = grade_arm(
            case, result,
            {case.symbol: symbol_series}, benchmark_series,
        )
        assert reason is None and record is not None

        expected, expected_reason = eval_insights.build_record(
            insight_id=case.insight_id,
            symbol=case.symbol,
            action="BUY",
            direction=1,
            confidence=0.8,
            created_at=case.created_at,
            pipeline_version=case.pipeline_version,
            horizon_bars=eval_insights.horizon_trading_days("medium_term"),
            symbol_series=symbol_series,
            benchmark_series=benchmark_series,
            price_source="price_history",
            entry_lag=eval_insights.ENTRY_LAG_TRADING_DAYS,
        )
        assert expected_reason is None
        assert record == expected, "grading must be eval_insights' arithmetic, not a local copy"

    def test_horizon_override_grades_both_arms_over_the_same_window(self):
        start = date(2026, 5, 1)
        symbol_series = _series(start, 200, 100.0, 0.5)
        benchmark_series = _series(start, 200, 400.0, 0.4)
        case = _case(day="2026-05-04")
        result = ArmResult(
            arm=ARM_NEW, insight_id=1, symbol=case.symbol, prompt_sha="x",
            context_chars=0, from_cache=False, parsed=True,
            action="BUY", confidence=0.8, time_horizon="long_term",
        )

        own, _ = grade_arm(case, result, {case.symbol: symbol_series}, benchmark_series)
        fixed, _ = grade_arm(
            case, result, {case.symbol: symbol_series}, benchmark_series,
            horizon_override=case.time_horizon,
        )
        assert own.horizon_trading_days == eval_insights.horizon_trading_days("long_term")
        assert fixed.horizon_trading_days == eval_insights.horizon_trading_days("medium_term")
        assert own.exit_date != fixed.exit_date

    def test_a_hold_answer_is_excluded_not_scored_as_a_miss(self):
        case = _case()
        result = ArmResult(
            arm=ARM_OLD, insight_id=1, symbol=case.symbol, prompt_sha="x",
            context_chars=0, from_cache=False, parsed=True,
            action="HOLD", confidence=0.5, time_horizon="medium_term",
        )
        record, reason = grade_arm(case, result, {case.symbol: []}, [])
        assert record is None
        assert reason == "non_directional_action"


# ---------------------------------------------------------------------------
# The cache
# ---------------------------------------------------------------------------


_RESPONSE = """{
  "analyst": "synthesis",
  "insights": [
    {
      "insight_type": "opportunity",
      "action": "BUY",
      "title": "NVDA continuation",
      "thesis": "Trend intact with sector support.",
      "primary_symbol": "NVDA",
      "confidence": 0.72,
      "time_horizon": "medium_term",
      "analysts_involved": ["technical", "sector"]
    }
  ]
}"""


class _CountingQuery:
    """Stands in for ``pool_query_llm`` and counts how often it was called."""

    def __init__(self, text: str = _RESPONSE):
        self.calls = 0
        self.text = text

    async def __call__(self, system_prompt: str, user_prompt: str, agent_name: str):
        self.calls += 1

        class _Result:
            text = self.text
            input_tokens = 1000
            output_tokens = 200
            cost_usd = 0.01
            model = "test-model"

        return _Result()


class TestCache:
    async def test_second_run_is_served_from_disk(self, tmp_path):
        case = _case()
        query = _CountingQuery()

        first = await run_arm(ARM_NEW, case, allow_llm=True, cache_dir=tmp_path, query=query)
        second = await run_arm(ARM_NEW, case, allow_llm=True, cache_dir=tmp_path, query=query)

        assert query.calls == 1, "a cached prompt must never be sent a second time"
        assert first.from_cache is False
        assert second.from_cache is True
        assert second.action == first.action == "BUY"
        assert second.confidence == pytest.approx(0.72)

    async def test_the_two_arms_do_not_share_a_cache_entry(self, tmp_path):
        case = _case()
        query = _CountingQuery()
        await run_arm(ARM_OLD, case, allow_llm=True, cache_dir=tmp_path, query=query)
        await run_arm(ARM_NEW, case, allow_llm=True, cache_dir=tmp_path, query=query)
        assert query.calls == 2

    async def test_a_changed_prompt_invalidates_the_entry(self, tmp_path):
        case = _case()
        query = _CountingQuery()
        await run_arm(ARM_NEW, case, allow_llm=True, cache_dir=tmp_path, query=query)

        # Same case, different rendered evidence -> different hash -> new call.
        await run_arm(
            ARM_NEW, case, allow_llm=True, cache_dir=tmp_path, query=query,
            scope_to_symbol=True,
        )
        assert query.calls == 2

    async def test_no_llm_mode_never_calls_out(self, tmp_path):
        case = _case()
        query = _CountingQuery()
        result = await run_arm(
            ARM_NEW, case, allow_llm=False, cache_dir=tmp_path, query=query
        )
        assert query.calls == 0
        assert result.action is None
        assert "not cached" in (result.error or "")

    async def test_off_target_answers_are_recorded_not_silently_accepted(self, tmp_path):
        case = _case()
        query = _CountingQuery(_RESPONSE.replace('"NVDA"', '"AMD"'))
        result = await run_arm(ARM_NEW, case, allow_llm=True, cache_dir=tmp_path, query=query)
        assert result.off_target is True
        assert result.primary_symbol == "AMD"

    async def test_an_unparseable_response_is_an_error_not_a_default_action(self, tmp_path):
        case = _case()
        query = _CountingQuery("I am afraid I cannot help with that.")
        result = await run_arm(ARM_OLD, case, allow_llm=True, cache_dir=tmp_path, query=query)
        assert result.parsed is False
        assert result.action is None
        assert result.error


# ---------------------------------------------------------------------------
# Cost control
# ---------------------------------------------------------------------------


class TestCostControl:
    def test_estimate_sends_nothing(self, tmp_path, monkeypatch):
        def _explode(*args, **kwargs):  # pragma: no cover -- must never run
            raise AssertionError("the estimate must not touch the LLM")

        monkeypatch.setattr("llm.client_pool.pool_query_llm", _explode, raising=False)
        estimate = estimate_cost([_case(1), _case(2, "AMD")], cache_dir=tmp_path)

        assert estimate["calls"] == 4
        assert estimate["to_send"] == 4
        assert estimate["est_cost_usd"] > 0
        assert estimate["rates"]["input_usd_per_mtok"] > 0

    async def test_cached_calls_leave_the_estimate(self, tmp_path):
        case = _case()
        await run_arm(ARM_OLD, case, allow_llm=True, cache_dir=tmp_path, query=_CountingQuery())
        estimate = estimate_cost([case], cache_dir=tmp_path)
        assert estimate["already_cached"] == 1
        assert estimate["to_send"] == 1
        assert estimate["per_arm"][ARM_OLD]["est_cost_usd_uncached"] == 0.0

    def test_prompt_hash_is_stable_and_content_addressed(self):
        case = _case()
        system_prompt, user_prompt = build_prompt(ARM_NEW, case)
        assert prompt_hash(system_prompt, user_prompt) == prompt_hash(system_prompt, user_prompt)
        assert prompt_hash(system_prompt, user_prompt) != prompt_hash(system_prompt, user_prompt + " ")


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------


class TestSampling:
    def test_sample_is_spread_across_dates_and_reproducible(self):
        cases = [
            _case(insight_id=index, symbol=f"S{index}", day=f"2026-05-{1 + index // 5:02d}")
            for index in range(20)
        ]
        first = sample_cases(cases, 8, seed=7)
        second = sample_cases(cases, 8, seed=7)

        assert [c.insight_id for c in first] == [c.insight_id for c in second]
        assert len(first) == 8
        assert len({c.as_of for c in first}) == len({c.as_of for c in cases}), (
            "a head slice would sample one or two runs; the clustered bootstrap "
            "needs the sample to span the dates"
        )

    def test_no_limit_returns_everything(self):
        cases = [_case(insight_id=index) for index in range(5)]
        assert len(sample_cases(cases, None)) == 5
        assert len(sample_cases(cases, 99)) == 5


# ---------------------------------------------------------------------------
# Phantom analysts -- the old representation invents a five-analyst panel
# ---------------------------------------------------------------------------


class TestPhantomAnalysts:
    def test_old_arm_renders_analysts_that_never_reported(self):
        """One analyst in, five analyst headings out.

        ``flatten_analyst_reports_historical`` initialises ``macro``, ``sector``
        and ``correlation`` keys it then never writes, and
        ``format_synthesis_context`` renders every key that is present.  So a
        run with a single technical report is shown to synthesis as a
        five-analyst panel whose other four members reported nothing -- printed
        as ``Analyst Confidence: 0%`` and ``Market Phase: Unknown (0%
        confidence)``, which read as measurements.
        """
        flat = flatten_analyst_reports_historical(
            {TARGET: {"technical": {"confidence": 0.7, "findings": []}}}
        )
        rendered = format_synthesis_context(flat)
        for heading in (
            "MACRO ECONOMIST REPORT",
            "SECTOR STRATEGIST REPORT",
            "RISK ANALYST REPORT",
            "CORRELATION DETECTIVE REPORT",
        ):
            assert heading in rendered
        assert "Market Phase: Unknown (0% confidence)" in rendered

    def test_new_arm_shows_only_the_analysts_that_ran(self):
        case = _case()
        case.reports.pop("sector")
        rendered = render_arm_context(ARM_NEW, case)
        assert "MACRO ECONOMIST REPORT" not in rendered
        assert "CORRELATION DETECTIVE REPORT" not in rendered
        assert "Analyst Confidence: 0%" not in rendered
        # The sector analyst is in the panel roster, so its absence is stated
        # rather than dropped -- two reports must not look like three.
        assert "[SECTOR] status: MISSING -- no report returned" in rendered

    async def test_a_citation_of_an_unsupplied_analyst_is_recorded(self, tmp_path):
        case = _case()
        case.reports.pop("sector")
        response = _RESPONSE.replace(
            '"analysts_involved": ["technical", "sector"]',
            '"analysts_involved": ["technical", "macro", "correlation"]',
        )
        result = await run_arm(
            ARM_OLD, case, allow_llm=True, cache_dir=tmp_path,
            query=_CountingQuery(response),
        )
        assert result.phantom_analysts == ["correlation", "macro"]

    async def test_a_supplied_analyst_is_never_counted_as_phantom(self, tmp_path):
        result = await run_arm(
            ARM_NEW, _case(), allow_llm=True, cache_dir=tmp_path,
            query=_CountingQuery(),
        )
        assert result.analysts_cited == ["sector", "technical"]
        assert result.phantom_analysts == []


# ---------------------------------------------------------------------------
# Selection -- the two cohorts are not the same cases
# ---------------------------------------------------------------------------


class TestSelectionBreakdown:
    def test_splits_shared_cases_from_single_arm_cases(self):
        pairs = [
            {"symbol": "A", "as_of": "2026-05-01", "both_graded": True,
             "old_graded": True, "new_graded": True, "alpha_delta": 0.0,
             "old_action": "BUY", "new_action": "BUY",
             "old_correct": True, "new_correct": True,
             "old_alpha_pct": 4.0, "new_alpha_pct": 4.0},
            {"symbol": "B", "as_of": "2026-05-02", "both_graded": False,
             "old_graded": True, "new_graded": False,
             "old_action": "BUY", "new_action": "WATCH",
             "old_correct": False, "old_alpha_pct": -6.0},
            {"symbol": "C", "as_of": "2026-05-03", "both_graded": False,
             "old_graded": False, "new_graded": True,
             "old_action": "WATCH", "new_action": "BUY",
             "new_correct": True, "new_alpha_pct": 9.0},
        ]
        block = _selection_breakdown(pairs)
        assert block["both_traded"]["n"] == 1
        assert block["both_traded"]["identical_outcome"] == 1
        assert block["old_arm_only"]["n"] == 1
        assert block["old_arm_only"]["hit_rate"] == 0.0
        assert block["new_arm_only"]["n"] == 1
        assert block["new_arm_only"]["hit_rate"] == 1.0
        assert block["new_arm_only"]["mean_alpha_pct"] == 9.0

    def test_reports_nothing_rather_than_zero_for_an_empty_side(self):
        block = _selection_breakdown([])
        assert block["old_arm_only"] == {"n": 0}
        assert "hit_rate" not in block["new_arm_only"]


# ---------------------------------------------------------------------------
# The cost estimate, after it was caught being 3.75x light
# ---------------------------------------------------------------------------


class TestCalibratedEstimate:
    def test_prompt_alone_is_not_the_bill(self, tmp_path):
        """The CLI overhead must dominate, or the estimate repeats its old miss.

        The first estimator priced the prompt only and predicted $1.33 against
        $4.99 actually spent on 40 calls.
        """
        estimate = estimate_cost([_case()], cache_dir=tmp_path)
        block = estimate["per_arm"][ARM_OLD]
        assert block["basis"] == "modelled"
        assert block["est_input_tokens"] == (
            block["est_prompt_tokens"] + CLI_OVERHEAD_INPUT_TOKENS
        )
        prompt_only = (
            block["est_prompt_tokens"] * 3.0 / 1_000_000
            + block["est_output_tokens"] * 15.0 / 1_000_000
        )
        assert block["est_cost_usd_per_call"] > 3 * prompt_only, (
            "the CLI overhead must dominate, or the estimate repeats its 3.75x miss"
        )

    async def test_a_populated_cache_prices_from_what_was_really_charged(self, tmp_path):
        cases = [_case(index, f"S{index}") for index in range(4)]
        query = _CountingQuery()
        for case in cases:
            await run_arm(ARM_OLD, case, allow_llm=True, cache_dir=tmp_path, query=query)

        estimate = estimate_cost(cases, cache_dir=tmp_path)
        block = estimate["per_arm"][ARM_OLD]
        assert block["basis"] == "observed_median_from_cache"
        assert block["est_cost_usd_per_call"] == pytest.approx(0.01)
        assert block["est_cost_usd_uncached"] == 0.0, "all four are cached"

    async def test_one_outlier_call_cannot_move_the_estimate(self, tmp_path):
        cases = [_case(index, f"S{index}") for index in range(5)]
        for index, case in enumerate(cases):
            query = _CountingQuery()
            await run_arm(ARM_NEW, case, allow_llm=True, cache_dir=tmp_path, query=query)
        # Forge one entry 100x the others, as a retried long turn really did.
        import json as _json
        path = sorted(tmp_path.glob(f"{ARM_NEW}__*.json"))[0]
        payload = _json.loads(path.read_text())
        payload["cost_usd"] = 1.0
        path.write_text(_json.dumps(payload))

        block = estimate_cost(cases, cache_dir=tmp_path)["per_arm"][ARM_NEW]
        assert block["est_cost_usd_per_call"] == pytest.approx(0.01), (
            "the median must absorb the outlier; a mean would report 0.208"
        )
