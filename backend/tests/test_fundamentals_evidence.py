"""An all-`None` yfinance fundamentals payload is not evidence.

`ticker.info` answers "did the fetch return an object" and "is there anything
worth scoring" with the same non-empty dict: for a thin or non-equity ticker it
comes back with every scoring key set to `None`. Daily alpha tested
`bool(fundamental_data)`, so those placeholders enabled the fundamental,
valuation, catalyst and liquidity factors on `_score_fundamentals()`'s neutral
50/50/45/50 -- the same "unavailable becomes neutral evidence" defect the
options-flow, short-interest and analyst-revision adapters already closed.
"""

from __future__ import annotations

from data.adapters.evidence import evidence_is_usable
from data.adapters.yahoo import FUNDAMENTAL_SCORING_FIELDS, _fundamental_evidence

from analysis.alpha_engine import _score_fundamentals, _score_with_evidence


def _yfinance_shaped(**populated: float | str) -> dict:
    """A payload in the adapter's real shape: every scoring key present, only
    the named ones populated. `sector`/`industry` come back for nearly every
    ticker and must not count as evidence."""
    metrics: dict[str, object] = {key: None for key in FUNDAMENTAL_SCORING_FIELDS}
    metrics.update({"sector": "Technology", "industry": "Software"})
    metrics.update(populated)
    return _fundamental_evidence(metrics)


class TestFundamentalEvidenceContract:
    def test_all_none_scoring_fields_are_unavailable(self):
        record = _yfinance_shaped()
        assert record["status"] == "unavailable"
        assert record["coverage"] == 0.0
        assert record["available"] is False
        assert not evidence_is_usable(record)

    def test_sector_and_industry_alone_do_not_make_it_usable(self):
        """They are context, not measurement -- yfinance returns them always."""
        assert not evidence_is_usable(_yfinance_shaped())

    def test_some_populated_fields_are_partial_and_usable(self):
        record = _yfinance_shaped(trailing_pe=28.4, market_cap=3_000_000_000)
        assert record["status"] == "partial"
        assert record["coverage"] > 0.0
        assert evidence_is_usable(record)

    def test_the_metrics_themselves_are_preserved(self):
        record = _yfinance_shaped(trailing_pe=28.4)
        assert record["trailing_pe"] == 28.4
        assert record["sector"] == "Technology"


class TestAlphaScoringGate:
    def _score(self, fundamental_data: dict) -> object:
        return _score_with_evidence(
            tech_score=60.0,
            fundamental_score=50.0,
            valuation_score=50.0,
            flow_proxy=50.0,
            sentiment_score=50.0,
            macro_score=50.0,
            catalyst_score=45.0,
            liquidity_score=50.0,
            fundamental_notes=[],
            fundamental_data=fundamental_data,
            options_flow_data={},
            short_interest_data={},
            analyst_revision_data={},
            has_technical=True,
            has_rich_technical=False,
            has_volume_ratio=True,
            has_sentiment=False,
        )

    def test_all_none_fundamentals_enable_no_fundamental_factors(self):
        scoring = self._score(_yfinance_shaped())
        enabled = set(scoring.applied_weights)

        # Pre-fix these four activated on placeholder scores, taking the usable
        # set from three families to seven.
        for factor in ("fundamental", "valuation", "catalyst", "liquidity"):
            assert factor not in enabled, f"{factor} scored from placeholders"

    def test_all_none_fundamentals_score_the_same_as_no_fundamentals_at_all(self):
        """The evidence contract's stated consequence: for a given source, an
        *unavailable* record and an *absent* record produce the same output."""
        absent = self._score({})
        placeholder = self._score(_yfinance_shaped())

        assert placeholder.positive == absent.positive
        assert placeholder.data_completeness == absent.data_completeness
        assert set(placeholder.applied_weights) == set(absent.applied_weights)

    def test_real_fundamentals_still_enable_those_factors(self):
        scoring = self._score(
            _yfinance_shaped(
                trailing_pe=22.0, forward_pe=18.0, revenue_growth=0.18,
                gross_margins=0.61, profit_margins=0.22, market_cap=8_000_000_000,
                target_mean_price=150.0, recommendation_key="buy",
            )
        )
        enabled = set(scoring.applied_weights)
        for factor in ("fundamental", "valuation", "catalyst", "liquidity"):
            assert factor in enabled

    def test_score_fundamentals_reports_placeholders_as_unavailable(self):
        _f, _v, _c, _l, notes = _score_fundamentals(_yfinance_shaped(), 100.0)
        assert notes == ["fundamentals unavailable"]
