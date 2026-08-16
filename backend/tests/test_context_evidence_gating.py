"""The analyst-facing context formatters must not render unusable evidence as a number.

An unavailable adapter record is still a fully-populated dict -- it carries
``symbol``, ``as_of``, ``available`` and a placeholder score -- so the old
"does any field have a value" guard let it through and the LLM read
``Revision Score 0.0/100`` as a measurement.
"""

from data.adapters.analyst_revisions import AnalystRevisionAdapter
from analysis.context_builder import (
    format_analyst_revision_context,
    format_fundamental_context,
)


def _unavailable_revision(symbol: str = "ARM") -> dict:
    """The exact record the adapter emits for a symbol with no analyst coverage."""
    return AnalystRevisionAdapter._empty_signal(symbol, note="no_analyst_coverage").to_dict()


def test_unavailable_revision_record_renders_no_score():
    record = _unavailable_revision()
    assert record["revision_score"] == 0.0, "fixture must carry the placeholder score"

    rendered = format_analyst_revision_context({"ARM": record})

    assert "Revision Score" not in rendered
    assert "0.0/100" not in rendered
    assert "UNAVAILABLE" in rendered
    assert "no_analyst_coverage" in rendered


def test_usable_revision_record_still_renders_its_score():
    """No regression for real evidence."""
    rendered = format_analyst_revision_context({
        "NVDA": {
            "symbol": "NVDA", "as_of": "2026-08-07T00:00:00Z", "available": True,
            "status": "ok", "coverage": 1.0, "revision_score": 78.5,
            "recommendation_key": "buy", "recommendation_mean": 1.8,
            "target_upside_pct": 12.4, "trend_history": [{}, {}], "notes": [],
        }
    })

    assert "Revision Score 78.5/100" in rendered
    assert "Rating Buy" in rendered
    assert "UNAVAILABLE" not in rendered


def test_mixed_symbols_gate_independently():
    rendered = format_analyst_revision_context({
        "ARM": _unavailable_revision("ARM"),
        "NVDA": {
            "symbol": "NVDA", "as_of": "2026-08-07T00:00:00Z", "available": True,
            "status": "ok", "coverage": 1.0, "revision_score": 78.5, "notes": [],
        },
    })

    arm_block = rendered.split("=== ANALYST REVISIONS: ARM ===")[1].split("===")[0]
    assert "UNAVAILABLE" in arm_block
    assert "Revision Score" not in arm_block
    assert "Revision Score 78.5/100" in rendered


def test_fundamentals_without_an_evidence_contract_are_unaffected():
    """The yahoo fundamentals payload has no status/available; gating is inert there."""
    rendered = format_fundamental_context({
        "AAPL": {"trailing_pe": 28.4, "forward_pe": 25.1, "profit_margins": 0.24},
    })

    assert "P/E 28.4" in rendered
    assert "UNAVAILABLE" not in rendered


def test_fundamentals_marked_unavailable_render_no_metrics():
    """And it engages the moment that payload gains the contract."""
    rendered = format_fundamental_context({
        "AAPL": {
            "status": "unavailable", "coverage": 0.0, "available": False,
            "notes": ["no_fundamental_coverage"], "trailing_pe": 0.0,
        },
    })

    assert "P/E" not in rendered
    assert "UNAVAILABLE" in rendered
    assert "no_fundamental_coverage" in rendered
