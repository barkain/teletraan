"""Tests for the multi-factor screening model.

Focus: a factor that could not be measured must stay *missing*. The audited
defect was that every symbol scored volatility=50, technical=50, value=50 and
quality=50, so a composite built on two real factors was indistinguishable
from one built on six.
"""

from __future__ import annotations

import pytest

from analysis.factor_model import (
    FACTOR_WEIGHTS,
    MIN_FACTOR_COVERAGE,
    FactorModel,
    FactorScore,
    _first_present,
    _zscore_to_percentile,
)


# =============================================================================
# Helpers
# =============================================================================


def full_market_row(
    change_5d: float,
    change_20d: float,
    change_60d: float,
    volume_ratio: float,
    volatility_20d: float,
    rsi_14: float,
) -> dict:
    """A heatmap row with every market-data factor present."""
    return {
        "change_5d": change_5d,
        "change_20d": change_20d,
        "change_60d": change_60d,
        "volume_ratio": volume_ratio,
        "volatility_20d": volatility_20d,
        "rsi_14": rsi_14,
    }


@pytest.fixture
def model() -> FactorModel:
    return FactorModel()


@pytest.fixture
def market_only_universe() -> dict[str, dict]:
    """Two fully-measured symbols plus one that only reports price + volume."""
    return {
        "FULLA": full_market_row(2.0, 6.0, 12.0, 1.4, 22.0, 61.0),
        "FULLB": full_market_row(-1.0, 1.0, 3.0, 0.9, 35.0, 44.0),
        "THIN": {"change_5d": 0.5, "change_20d": 2.0, "volume_ratio": 1.1},
    }


# =============================================================================
# _zscore_to_percentile
# =============================================================================


class TestZscoreToPercentile:
    def test_none_stays_none(self):
        result = _zscore_to_percentile([1.0, 5.0, None])
        assert result[2] is None
        assert result[0] is not None and result[1] is not None

    def test_single_observation_cannot_be_ranked(self):
        assert _zscore_to_percentile([3.0, None, None]) == [None, None, None]

    def test_zero_dispersion_maps_measured_values_to_median(self):
        # Identical values genuinely sit at the median; None still stays None.
        assert _zscore_to_percentile([4.0, 4.0, None]) == [50.0, 50.0, None]


class TestFirstPresent:
    def test_zero_is_a_value_not_a_miss(self):
        # `or` chaining used to skip a legitimate 0.0 and fall through.
        assert _first_present({"return_5d": 0.0, "change_5d": 9.9}, "return_5d", "change_5d") == 0.0

    def test_falls_through_on_none(self):
        assert _first_present({"return_5d": None, "change_5d": 9.9}, "return_5d", "change_5d") == 9.9

    def test_all_missing(self):
        assert _first_present({}, "return_5d", "change_5d") is None


# =============================================================================
# Coverage-aware compositing
# =============================================================================


class TestFactorCoverage:
    async def test_unmeasured_factors_are_none_and_weights_renormalize(
        self, model, market_only_universe
    ):
        """Without fundamentals, value/quality are None — not 50 — and the
        surviving weights are renormalized to sum to 1.0, with the achieved
        coverage reported on the score."""
        scores = await model.compute_factor_scores(market_only_universe)

        fs = scores["FULLA"]
        assert fs.value_score is None
        assert fs.quality_score is None
        assert fs.momentum_score is not None
        assert fs.volatility_score is not None
        assert fs.technical_score is not None

        assert set(fs.missing_factors) == {"value", "quality"}
        assert fs.factors_used == ["momentum", "technical", "volatility", "volume"]

        expected_coverage = (
            FACTOR_WEIGHTS["momentum"]
            + FACTOR_WEIGHTS["volatility"]
            + FACTOR_WEIGHTS["volume"]
            + FACTOR_WEIGHTS["technical"]
        )
        assert fs.coverage == pytest.approx(expected_coverage)
        assert sum(fs.effective_weights.values()) == pytest.approx(1.0)
        # Renormalization scales each surviving weight by 1/coverage.
        assert fs.effective_weights["momentum"] == pytest.approx(
            FACTOR_WEIGHTS["momentum"] / expected_coverage
        )

        # to_dict() reports coverage and omits the unmeasured factors so that
        # `payload.get("value_score", 50)` consumers keep working while
        # missing_factors flags the placeholder.
        payload = fs.to_dict()
        assert "value_score" not in payload
        assert payload["coverage"] == pytest.approx(expected_coverage)
        assert payload["missing_factors"] == fs.missing_factors

    async def test_composite_is_weighted_average_of_measured_percentiles(
        self, model, market_only_universe
    ):
        scores = await model.compute_factor_scores(market_only_universe)
        fs = scores["FULLA"]
        expected = sum(
            getattr(fs, f"{name}_score") * weight
            for name, weight in fs.effective_weights.items()
        )
        assert fs.composite_score == pytest.approx(round(expected, 2))
        # Composite stays on the 0-100 percentile scale after renormalization.
        assert 0.0 <= fs.composite_score <= 100.0

    async def test_symbol_below_coverage_threshold_is_not_ranked(
        self, model, market_only_universe
    ):
        """THIN has only momentum (0.25) + volume (0.10) = 0.35 coverage."""
        scores = await model.compute_factor_scores(market_only_universe)

        assert "THIN" not in scores
        assert model.last_excluded["THIN"] == pytest.approx(
            FACTOR_WEIGHTS["momentum"] + FACTOR_WEIGHTS["volume"]
        )
        assert model.last_excluded["THIN"] < MIN_FACTOR_COVERAGE

        ranked = model.rank_candidates(scores, top_n=10)
        assert "THIN" not in {r["symbol"] for r in ranked}

    def test_rank_candidates_rejects_low_coverage_scores_from_any_source(self, model):
        """Defence in depth: a low-coverage score handed in directly is still
        excluded from the ranking."""
        good = FactorScore(symbol="GOOD", composite_score=61.0, coverage=0.60)
        thin = FactorScore(symbol="THIN", composite_score=99.0, coverage=0.35)

        ranked = model.rank_candidates({"GOOD": good, "THIN": thin}, top_n=10)

        assert [r["symbol"] for r in ranked] == ["GOOD"]

    async def test_missing_60d_return_is_not_treated_as_flat(self, model):
        """A missing 60-day return used to be substituted with 0.0, silently
        asserting the stock went nowhere over three months."""
        with_60d = {
            "A": full_market_row(2.0, 6.0, 30.0, 1.4, 22.0, 61.0),
            "B": full_market_row(-1.0, 1.0, 3.0, 0.9, 35.0, 44.0),
        }
        without_60d = {
            sym: {k: v for k, v in row.items() if k != "change_60d"}
            for sym, row in with_60d.items()
        }

        scored_with = await model.compute_factor_scores(with_60d)
        scored_without = await model.compute_factor_scores(without_60d)

        mom_with = scored_with["A"].factor_details["momentum_composite"]
        mom_without = scored_without["A"].factor_details["momentum_composite"]

        # 5d+20d renormalized: (0.3*2 + 0.5*6) / 0.8 = 4.5, not a 0.0-padded 3.6
        assert mom_without == pytest.approx(4.5)
        assert mom_with != mom_without
        assert scored_without["A"].factor_details["momentum_windows"] == ["20d", "5d"]

    async def test_momentum_needs_more_than_a_lone_5d_return(self, model):
        universe = {
            "A": {"change_5d": 2.0, "volume_ratio": 1.2, "volatility_20d": 20.0, "rsi_14": 55.0},
            "B": {"change_5d": -2.0, "volume_ratio": 0.8, "volatility_20d": 30.0, "rsi_14": 45.0},
        }
        scores = await model.compute_factor_scores(universe)

        # momentum (0.25) dropped -> coverage 0.35 -> below threshold
        assert scores == {}
        assert set(model.last_excluded) == {"A", "B"}

    async def test_fundamentals_restore_full_coverage(self, model):
        universe = {
            "A": full_market_row(2.0, 6.0, 12.0, 1.4, 22.0, 61.0),
            "B": full_market_row(-1.0, 1.0, 3.0, 0.9, 35.0, 44.0),
        }
        fundamentals = {
            "A": {"pe_ratio": 18.0, "pb_ratio": 3.0, "roe": 0.25, "profit_margins": 0.2, "debt_to_equity": 50.0},
            "B": {"pe_ratio": 30.0, "pb_ratio": 6.0, "roe": 0.10, "profit_margins": 0.05, "debt_to_equity": 200.0},
        }
        scores = await model.compute_factor_scores(universe, fundamentals)

        fs = scores["A"]
        assert fs.coverage == pytest.approx(1.0)
        assert fs.missing_factors == []
        assert fs.value_score is not None and fs.quality_score is not None
        assert sum(fs.effective_weights.values()) == pytest.approx(1.0)

    async def test_debt_to_equity_percentage_is_rescaled(self, model):
        """yfinance reports D/E as a percentage; inverting it raw collapsed the
        quality composite toward zero and swamped roe/profit_margins."""
        universe = {
            "A": full_market_row(2.0, 6.0, 12.0, 1.4, 22.0, 61.0),
            "B": full_market_row(-1.0, 1.0, 3.0, 0.9, 35.0, 44.0),
        }
        fundamentals = {
            "A": {"roe": 0.30, "profit_margins": 0.30, "debt_to_equity": 100.0},
            "B": {"roe": 0.30, "profit_margins": 0.30, "debt_to_equity": 0.0},
        }
        scores = await model.compute_factor_scores(universe, fundamentals)

        # D/E of 100 (== 1.0x) -> inv 0.5; average with 0.30/0.30 -> ~0.3667.
        # Unrescaled it would have been 1/101 ≈ 0.0099 -> average ~0.203.
        detail = scores["A"].factor_details
        assert detail["debt_to_equity"] == 100.0
        assert scores["A"].quality_score is not None
        # Zero debt still scores better than 1.0x debt on the quality factor.
        assert scores["B"].quality_score > scores["A"].quality_score

    async def test_empty_universe(self, model):
        assert await model.compute_factor_scores({}) == {}
