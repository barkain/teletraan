"""Evidence gating in the alpha engine composite.

The property under test: an *unavailable* source must be indistinguishable from
an *absent* source. Before the fix, an unavailable analyst-revisions record
carried a hardcoded 50.0 that passed a `> 0` gate and pulled `fundamental_score`
toward neutral, while `bool(record)` counted the same record as complete data.
"""

from __future__ import annotations

import pytest


def _base_kwargs(**overrides):
    kwargs = {
        "tech_score": 72.0,
        "fundamental_score": 64.0,
        "valuation_score": 58.0,
        "flow_proxy": 61.0,
        "sentiment_score": 55.0,
        "macro_score": 60.0,
        "catalyst_score": 52.0,
        "liquidity_score": 88.0,
        "fundamental_notes": ["growth", "margins"],
        "fundamental_data": {"target_mean_price": 210.0, "market_cap": 3_000_000_000},
        "options_flow_data": {},
        "short_interest_data": {},
        "analyst_revision_data": {},
        "has_technical": True,
        "has_rich_technical": True,
        "has_volume_ratio": True,
        "has_sentiment": True,
    }
    kwargs.update(overrides)
    return kwargs


def _unavailable_records():
    """The exact payloads the three adapters emit when they have nothing."""
    from data.adapters.analyst_revisions import AnalystRevisionAdapter
    from data.adapters.options_flow import OptionsFlowAdapter
    from data.adapters.short_interest import ShortInterestAdapter

    return {
        "options_flow_data": OptionsFlowAdapter._empty_signal(
            "TEST", status="error", note="all_chains_failed", chains_failed=2
        ).to_dict(),
        "short_interest_data": ShortInterestAdapter._empty_signal(
            "TEST", note="no_short_interest_fields"
        ).to_dict(),
        "analyst_revision_data": AnalystRevisionAdapter._empty_signal(
            "TEST", note="no_analyst_coverage"
        ).to_dict(),
    }


def test_unavailable_records_score_identically_to_omitted_sources():
    from analysis import alpha_engine as ae

    omitted = ae._score_with_evidence(**_base_kwargs())
    unavailable = ae._score_with_evidence(**_base_kwargs(**_unavailable_records()))

    assert unavailable == omitted
    assert unavailable.positive == omitted.positive
    assert unavailable.data_completeness == omitted.data_completeness
    assert unavailable.adapter_scores == {
        "options_flow": None,
        "short_interest": None,
        "analyst_revisions": None,
    }


def test_unavailable_revisions_record_does_not_move_fundamental_score():
    """The specific regression: revision_score=50.0 on an unavailable record."""
    from analysis import alpha_engine as ae

    records = _unavailable_records()
    result = ae._score_with_evidence(
        **_base_kwargs(analyst_revision_data=records["analyst_revision_data"])
    )

    assert result.fundamental_score == 64.0  # untouched, not blended toward 50
    assert result.catalyst_score == 52.0


def test_unavailable_record_does_not_inflate_completeness():
    from analysis import alpha_engine as ae

    records = _unavailable_records()
    partial = ae._score_with_evidence(**_base_kwargs(**records))
    with_options = ae._score_with_evidence(
        **_base_kwargs(
            **{**records, "options_flow_data": {"available": True, "status": "ok", "coverage": 1.0, "signal_score": 70.0}}
        )
    )

    assert with_options.data_completeness > partial.data_completeness


def test_available_records_still_feed_the_score():
    """Guards against the gate being so strict that real evidence is dropped."""
    from analysis import alpha_engine as ae

    usable = {
        "options_flow_data": {"available": True, "status": "ok", "coverage": 1.0, "signal_score": 80.0},
        "short_interest_data": {"available": True, "status": "ok", "coverage": 1.0, "squeeze_score": 70.0},
        "analyst_revision_data": {"available": True, "status": "partial", "coverage": 0.66, "revision_score": 90.0},
    }
    baseline = ae._score_with_evidence(**_base_kwargs())
    enriched = ae._score_with_evidence(**_base_kwargs(**usable))

    assert enriched.flow_proxy > baseline.flow_proxy
    assert enriched.catalyst_score > baseline.catalyst_score
    assert enriched.fundamental_score > baseline.fundamental_score
    assert enriched.adapter_scores["analyst_revisions"] == 90.0


def test_applied_weights_always_sum_to_one():
    from analysis import alpha_engine as ae

    full = ae._score_with_evidence(**_base_kwargs())
    sparse = ae._score_with_evidence(
        **_base_kwargs(fundamental_data={}, has_sentiment=False, has_rich_technical=False)
    )

    for result in (full, sparse):
        assert sum(result.applied_weights.values()) == pytest.approx(1.0)

    # With no fundamentals and no sentiment, those factors are dropped rather
    # than blended in at their neutral placeholder values.
    assert set(full.applied_weights) == set(ae._FACTOR_WEIGHTS)
    assert "valuation" not in sparse.applied_weights
    assert "sentiment" not in sparse.applied_weights
    assert sparse.applied_weights.keys() == {"technical", "flow", "macro"}


def test_full_coverage_matches_the_original_weight_table():
    """When every factor is usable, renormalization is a no-op."""
    from analysis import alpha_engine as ae

    kwargs = _base_kwargs()
    result = ae._score_with_evidence(**kwargs)
    argument_for = {
        "technical": "tech_score",
        "fundamental": "fundamental_score",
        "valuation": "valuation_score",
        "flow": "flow_proxy",
        "sentiment": "sentiment_score",
        "macro": "macro_score",
        "catalyst": "catalyst_score",
        "liquidity": "liquidity_score",
    }
    expected = sum(
        weight * kwargs[argument_for[name]] for name, weight in ae._FACTOR_WEIGHTS.items()
    )

    assert result.positive == pytest.approx(expected)
