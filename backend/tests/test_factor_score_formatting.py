"""Honest `None` factor scores must render, not crash the pipeline.

`FactorScore` deliberately keeps an unmeasured factor as `None` rather than a
fabricated 50. Both prompt formatters then applied `:.0f` unconditionally, so
the coverage-honesty change raised `TypeError` on exactly the rows it was
introduced to describe -- and the autonomous orchestrator caught that, dropping
the run into the legacy path, which does not apply the freshness partition.
A rendering bug therefore disabled a safety control.
"""

from __future__ import annotations

import pytest

from analysis.agents.opportunity_hunter import format_opportunity_context
from analysis.factor_model import FactorScore, format_factor_value


def _partial_coverage_score(symbol: str) -> FactorScore:
    """A stock with 5d/20d/volume/volatility but no RSI: exactly 50% coverage,
    which the model admits, with `technical_score=None`."""
    return FactorScore(
        symbol=symbol,
        composite_score=62.5,
        coverage=0.5,
        momentum_score=71.0,
        volatility_score=48.0,
        volume_score=55.0,
        technical_score=None,
        value_score=None,
        quality_score=None,
        factors_used=["momentum", "volatility", "volume"],
        missing_factors=["value", "quality", "technical"],
    )


class TestFormatFactorValue:
    def test_a_measured_score_renders_as_a_number(self):
        assert format_factor_value(71.4) == "71"
        assert format_factor_value(71.4, ".1f") == "71.4"

    def test_an_unmeasured_score_renders_as_an_explicit_absence(self):
        assert format_factor_value(None) == "n/a"

    def test_absence_is_never_rendered_as_a_neutral_number(self):
        """A 0 or a 50 here would put a fabricated measurement in the prompt."""
        rendered = format_factor_value(None)
        assert rendered not in {"0", "50", "0.0", "50.0"}


class TestOpportunityHunterTable:
    def test_partial_coverage_row_renders_instead_of_raising(self):
        candidates = [
            {
                "symbol": "ABCD",
                "sector": "Technology",
                "price": 100.0,
                "return_5d": 2.5,
                "return_20d": 8.0,
                "volume_ratio": 1.4,
                "screen_score": 62.5,
            }
        ]
        # Pre-fix this raised:
        #   TypeError: unsupported format string passed to NoneType.__format__
        text = format_opportunity_context(
            {}, {}, candidates,
            factor_scores={"ABCD": _partial_coverage_score("ABCD")},
        )

        assert "ABCD" in text
        assert "n/a" in text, "the unmeasured technical factor must show as missing"
        assert "71" in text, "the measured momentum factor must still show"


class TestAutonomousHeatmapSummary:
    def test_factor_summary_line_tolerates_unmeasured_factors(self):
        from analysis import autonomous_engine as ae

        fs = _partial_coverage_score("ABCD")
        line = (
            f"- {fs.symbol}: "
            f"Composite={ae.format_factor_value(fs.composite_score, '.1f')} "
            f"(Mom={ae.format_factor_value(fs.momentum_score)} "
            f"Vol={ae.format_factor_value(fs.volatility_score)} "
            f"Tech={ae.format_factor_value(fs.technical_score)})"
        )
        assert line == "- ABCD: Composite=62.5 (Mom=71 Vol=48 Tech=n/a)"

    def test_the_formatter_the_engine_imports_is_the_shared_one(self):
        from analysis import autonomous_engine as ae

        assert ae.format_factor_value is format_factor_value


@pytest.mark.parametrize(
    "field",
    ["momentum_score", "value_score", "quality_score",
     "volatility_score", "volume_score", "technical_score"],
)
def test_every_optional_factor_can_be_none_without_breaking_the_table(field):
    """All six are optional in the model, so all six must survive rendering --
    the earlier fix only covered the three the summary line happened to use."""
    fs = FactorScore(symbol="ABCD", composite_score=50.0, coverage=0.5)
    setattr(fs, field, None)

    text = format_opportunity_context(
        {}, {},
        [{"symbol": "ABCD", "price": 10.0, "return_5d": 0.0,
          "return_20d": 0.0, "volume_ratio": 1.0, "screen_score": 50.0}],
        factor_scores={"ABCD": fs},
    )
    assert "ABCD" in text
