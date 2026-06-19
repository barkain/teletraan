"""Tests for AutonomousDeepEngine._flatten_analyst_reports.

Regression: a discovery run produced only a single insight because the
flattener pre-seeded `macro` and `correlation` analyst buckets at 0.0
confidence even though the engine only runs technical/sector/risk per
symbol. format_synthesis_context then rendered empty "0% confidence"
macro/correlation reports, and the synthesis LLM read that as "incomplete
coverage" and collapsed to one conservative pick. Never-ran analysts must
be dropped so they cannot signal phantom low-confidence coverage.
"""

from analysis.autonomous_engine import AutonomousDeepEngine


def _engine():
    return AutonomousDeepEngine()


def _per_symbol_reports(symbols):
    return {
        sym: {
            "technical": {"findings": [{"symbol": sym}], "confidence": 0.6},
            "sector": {"sector_rankings": [], "confidence": 0.55},
            "risk": {"risk_assessments": [{"symbol": sym}], "confidence": 0.5},
        }
        for sym in symbols
    }


def test_drops_never_run_macro_and_correlation():
    flat = _engine()._flatten_analyst_reports(_per_symbol_reports(["ARM", "ADBE", "T"]))
    assert set(flat.keys()) == {"technical", "sector", "risk"}
    assert "macro" not in flat
    assert "correlation" not in flat


def test_keeps_analyst_with_confidence_but_no_list_data():
    # sector ran (confidence > 0) but produced no rankings — still surfaced.
    flat = _engine()._flatten_analyst_reports(_per_symbol_reports(["NVDA"]))
    assert "sector" in flat
    assert flat["sector"]["confidence"] > 0.0


def test_keeps_macro_when_it_actually_ran():
    reports = {
        "NVDA": {
            "technical": {"findings": [{"symbol": "NVDA"}], "confidence": 0.6},
            "macro": {"market_implications": ["rates falling"], "confidence": 0.7},
        }
    }
    flat = _engine()._flatten_analyst_reports(reports)
    assert "macro" in flat
    assert flat["macro"]["confidence"] > 0.0


def test_empty_reports_surface_no_analysts():
    flat = _engine()._flatten_analyst_reports({})
    assert flat == {}


def test_errored_analyst_is_not_surfaced():
    reports = {
        "NVDA": {
            "technical": {"findings": [{"symbol": "NVDA"}], "confidence": 0.6},
            "risk": {"error": "timeout"},
        }
    }
    flat = _engine()._flatten_analyst_reports(reports)
    assert "technical" in flat
    assert "risk" not in flat
