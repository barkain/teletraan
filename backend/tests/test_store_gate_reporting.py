"""Tests that store-time rejections are reported, not just logged.

The entry sanity gate drops insights whose entry zone cannot be verified
against a live price.  Before this cover the drop incremented a local counter
and emitted a log line: ``result.errors`` stayed empty and the synthesis phase
summary was built from the *generated* count, so a run could report
"Generated 3 insights" while ``result.insights`` was empty.  A caller could not
tell "no opportunities found" from "every opportunity was unverifiable".

Nothing here asserts on log text, and nothing here changes what the gate
rejects -- these tests cover reporting only.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from analysis.agents.heatmap_interfaces import (
    HeatmapAnalysis,
    HeatmapData,
    HeatmapStockSelection,
)
from analysis.agents.macro_scanner import MacroScanResult
from analysis.autonomous_engine import (
    AutonomousAnalysisResult,
    AutonomousDeepEngine,
    InsightStoreOutcome,
)
from analysis.price_freshness import build_freshness, last_weekday
from tests.conftest import TestSessionFactory


# The 2026-06-19 numbers behind the gate: a STRONG_BUY on ARM quoting an entry
# of $205-215 while ARM traded at $439.46.
STALE_ENTRY = "$205-215"
LIVE_PRICE = 439.46


def _insight(symbol: str, entry_zone: str) -> dict[str, Any]:
    """A synthesis-shaped insight dict carrying trading levels."""
    return {
        "insight_type": "opportunity",
        "action": "HOLD",  # HOLD keeps the store path off outcome tracking
        "title": f"{symbol} setup",
        "thesis": "Thesis body.",
        "primary_symbol": symbol,
        "confidence": 0.7,
        "time_horizon": "medium_term",
        "entry_zone": entry_zone,
        "target_price": "$260",
        "stop_loss": "$195",
        "timeframe": "position",
    }


def _fresh_context(prices: dict[str, float]) -> dict[str, Any]:
    """Context whose snapshots are fresh enough to pass the freshness partition."""
    return {
        "price_freshness": {
            sym.upper(): build_freshness(
                sym.upper(), last_weekday(date.today()), price, "db_close"
            )
            for sym, price in prices.items()
        }
    }


# ---------------------------------------------------------------------------
# The store method records what it dropped
# ---------------------------------------------------------------------------


class TestStoreOutcomeRecording:
    async def test_gate_rejections_are_recorded_with_symbols(self, db_session):
        engine = AutonomousDeepEngine()

        stored = await engine._store_insights_from_heatmap(
            session=db_session,
            insights_data=[
                _insight("ARM", STALE_ENTRY),
                _insight("NVDA", STALE_ENTRY),
            ],
            macro_result=MacroScanResult(),
            heatmap_analysis=HeatmapAnalysis(),
            pre_context=_fresh_context({"ARM": LIVE_PRICE, "NVDA": LIVE_PRICE}),
        )

        assert stored == []
        outcome = engine._last_store_outcome
        assert outcome is not None
        assert outcome.generated == 2
        assert outcome.stored == 0
        assert sorted(outcome.gate_rejected) == ["ARM", "NVDA"]

    async def test_partial_rejection_records_both_counts(self, db_session):
        engine = AutonomousDeepEngine()

        stored = await engine._store_insights_from_heatmap(
            session=db_session,
            insights_data=[
                _insight("ARM", STALE_ENTRY),          # 53% away -- rejected
                _insight("NVDA", f"${LIVE_PRICE:.0f}"),  # at the money -- kept
            ],
            macro_result=MacroScanResult(),
            heatmap_analysis=HeatmapAnalysis(),
            pre_context=_fresh_context({"ARM": LIVE_PRICE, "NVDA": LIVE_PRICE}),
        )

        assert [i.primary_symbol for i in stored] == ["NVDA"]
        outcome = engine._last_store_outcome
        assert outcome is not None
        assert outcome.generated == 2
        assert outcome.stored == 1
        assert outcome.gate_rejected == ["ARM"]

    async def test_clean_run_reports_nothing(self, db_session):
        engine = AutonomousDeepEngine()

        stored = await engine._store_insights_from_heatmap(
            session=db_session,
            insights_data=[_insight("NVDA", f"${LIVE_PRICE:.0f}")],
            macro_result=MacroScanResult(),
            heatmap_analysis=HeatmapAnalysis(),
            pre_context=_fresh_context({"NVDA": LIVE_PRICE}),
        )

        assert len(stored) == 1
        outcome = engine._last_store_outcome
        assert outcome is not None
        assert outcome.error_entries() == []
        assert outcome.summary_parts() == []


class TestOutcomeMessages:
    def test_total_rejection_is_stated_outright(self):
        outcome = InsightStoreOutcome(
            generated=3, stored=0, gate_rejected=["ARM", "NVDA", "AMD"]
        )

        entries = outcome.error_entries()
        assert any(e.startswith("REJECTED:") and "entry sanity gate" in e for e in entries)
        assert any("ARM, NVDA, AMD" in e for e in entries)
        assert any(e.startswith("NO INSIGHTS STORED:") for e in entries)

    def test_commit_failure_is_reported(self):
        outcome = InsightStoreOutcome(generated=2, stored=0, commit_failed=True)

        entries = outcome.error_entries()
        assert any("commit failed" in e for e in entries)
        assert any(e.startswith("NO INSIGHTS STORED:") for e in entries)

    def test_build_failures_are_reported(self):
        outcome = InsightStoreOutcome(generated=2, stored=1, build_failures=1)

        entries = outcome.error_entries()
        assert any("could not be built" in e for e in entries)
        # One insight survived, so this is not a total loss.
        assert not any(e.startswith("NO INSIGHTS STORED:") for e in entries)


# ---------------------------------------------------------------------------
# A full pipeline run that generates N and stores 0 says so
# ---------------------------------------------------------------------------


async def _run_pipeline_with_stale_entries(
    monkeypatch, insights: list[dict[str, Any]], prices: dict[str, float]
) -> AutonomousAnalysisResult:
    """Drive _run_heatmap_pipeline with every external phase stubbed out.

    Only synthesis output and the price snapshot are real inputs; the entry
    gate then runs for real against them.
    """
    monkeypatch.setattr(
        "analysis.autonomous_engine.async_session_factory", TestSessionFactory
    )

    catalyst_tracker = MagicMock()
    catalyst_tracker.earnings_adapter.get_upcoming_catalysts = AsyncMock(return_value=[])
    monkeypatch.setattr(
        "analysis.catalyst_tracker.get_catalyst_tracker", lambda: catalyst_tracker
    )

    engine = AutonomousDeepEngine()
    symbols = list(prices)

    monkeypatch.setattr(engine, "_get_portfolio_holdings", AsyncMock(return_value={}))
    monkeypatch.setattr(engine, "_compute_factor_scores", AsyncMock(return_value={}))
    monkeypatch.setattr(engine, "_update_task_progress", AsyncMock(return_value=None))
    monkeypatch.setattr(engine, "_fetch_business_summaries", AsyncMock(return_value={}))
    monkeypatch.setattr(
        engine,
        "_run_heatmap_analysis",
        AsyncMock(
            return_value=HeatmapAnalysis(
                selected_stocks=[
                    HeatmapStockSelection(symbol=sym, sector="Technology", priority="high")
                    for sym in symbols
                ],
                confidence=0.8,
            )
        ),
    )
    monkeypatch.setattr(
        engine.context_builder,
        "build_context",
        AsyncMock(return_value=_fresh_context(prices)),
    )
    monkeypatch.setattr(
        engine,
        "_run_analysts_for_symbol",
        AsyncMock(return_value={"technical": {"confidence": 0.6, "findings": []}}),
    )
    monkeypatch.setattr(
        engine,
        "_run_synthesis_with_heatmap",
        AsyncMock(return_value=(insights, "raw synthesis response")),
    )
    monkeypatch.setattr(
        engine, "_build_heatmap_discovery_summary", MagicMock(return_value="")
    )

    return await engine._run_heatmap_pipeline(
        result=AutonomousAnalysisResult(analysis_id="test-run"),
        macro_result=MacroScanResult(),
        heatmap_data=HeatmapData(),
        deep_dive_count=2,
        max_insights=2,
        task_id=None,
    )


class TestPipelineReporting:
    async def test_run_that_stores_nothing_says_so(self, db_session, monkeypatch):
        """Generated 2, stored 0 -- unambiguous from the run summary alone."""
        result = await _run_pipeline_with_stale_entries(
            monkeypatch,
            insights=[_insight("ARM", STALE_ENTRY), _insight("NVDA", STALE_ENTRY)],
            prices={"ARM": LIVE_PRICE, "NVDA": LIVE_PRICE},
        )

        assert result.insights == []

        # The rejection reaches result.errors with a count and a reason.
        gate_errors = [e for e in result.errors if "entry sanity gate" in e]
        assert len(gate_errors) == 1
        assert gate_errors[0].startswith("REJECTED: 2 of 2 synthesised insight(s)")
        assert "ARM" in gate_errors[0] and "NVDA" in gate_errors[0]

        # ...and the total loss is called out as its own entry.
        assert any(e.startswith("NO INSIGHTS STORED:") for e in result.errors)

        # The phase summary reports the stored count, not just the generated one.
        summary = result.phase_summaries["synthesis"]
        assert "Generated 2 insights, stored 0" in summary
        assert "NO INSIGHTS STORED" in summary
        assert "Dropped 2 at the entry sanity gate: ARM, NVDA." in summary

    async def test_partial_rejection_reports_both_counts(self, db_session, monkeypatch):
        result = await _run_pipeline_with_stale_entries(
            monkeypatch,
            insights=[
                _insight("ARM", STALE_ENTRY),
                _insight("NVDA", f"${LIVE_PRICE:.0f}"),
            ],
            prices={"ARM": LIVE_PRICE, "NVDA": LIVE_PRICE},
        )

        assert [i.primary_symbol for i in result.insights] == ["NVDA"]

        gate_errors = [e for e in result.errors if "entry sanity gate" in e]
        assert len(gate_errors) == 1
        assert gate_errors[0].startswith("REJECTED: 1 of 2 synthesised insight(s)")
        assert not any(e.startswith("NO INSIGHTS STORED:") for e in result.errors)

        summary = result.phase_summaries["synthesis"]
        assert "Generated 2 insights, stored 1" in summary
        assert "Dropped 1 at the entry sanity gate: ARM." in summary

    async def test_clean_run_adds_no_errors(self, db_session, monkeypatch):
        result = await _run_pipeline_with_stale_entries(
            monkeypatch,
            insights=[_insight("NVDA", f"${LIVE_PRICE:.0f}")],
            prices={"NVDA": LIVE_PRICE},
        )

        assert len(result.insights) == 1
        assert not any("REJECTED" in e or "NO INSIGHTS STORED" in e for e in result.errors)
        assert "Generated 1 insights, stored 1" in result.phase_summaries["synthesis"]
