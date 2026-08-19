"""Calibration tests for ConfidenceAdjuster and the synthesis confidence prompt.

Two defects are covered here:

A. `ConfidenceAdjuster` blended components with raw weights that summed to 0.8
   (or less), which is not a weighted average — it was a systematic haircut that
   capped even unanimous high-confidence inputs near 0.8 and deflated mid-range
   ones. The blend must now normalize over whichever components are present.

B. The synthesis prompt defined confidence as "how many analysts agree" rather
   than the probability the thesis is validated. Confidence must be anchored to
   the measured base rate instead.

   The prompt's stated *reason* moved with the pipeline. It used to be that all
   analysts received the same discovery context, so agreement measured common
   priming. The specialists are now run blind (``analysis/decision_brief.py``),
   so that sentence became false; the prompt now says they are run blind and
   that agreement is still weak evidence because three calls to one model share
   their errors. Both the old claim's absence and the new claim's presence are
   asserted below.
"""

from __future__ import annotations

import math

import pytest

from analysis.agents.synthesis_lead import SYNTHESIS_LEAD_PROMPT
from analysis.confidence_adjuster import ConfidenceAdjuster


class _StubMemoryService:
    """Minimal stand-in for InstitutionalMemoryService."""

    def __init__(self, success_rate: float, total_insights: int) -> None:
        self._success_rate = success_rate
        self._total_insights = total_insights

    async def get_insight_track_record(self, insight_type: str, action_type: str) -> dict:
        return {
            "success_rate": self._success_rate,
            "total_insights": self._total_insights,
        }


class _StubAdjuster(ConfidenceAdjuster):
    """ConfidenceAdjuster with the DB-backed lookups stubbed out."""

    def __init__(
        self,
        *,
        historical_accuracy: float = 0.5,
        historical_total: int = 0,
        symbol_accuracy: float = 0.5,
        symbol_total: int = 0,
        thematic_accuracy: float = 0.5,
        thematic_total: int = 0,
    ) -> None:
        super().__init__(
            db_session=None,  # type: ignore[arg-type]
            memory_service=_StubMemoryService(historical_accuracy, historical_total),
        )
        self._symbol_accuracy = symbol_accuracy
        self._symbol_total = symbol_total
        self._thematic_accuracy = thematic_accuracy
        self._thematic_total = thematic_total

    async def get_symbol_accuracy(self, symbol: str, lookback_days: int = 180) -> dict:
        return {"total": self._symbol_total, "accuracy": self._symbol_accuracy}

    async def get_thematic_accuracy(
        self, category: str | None = None, lookback_days: int = 180
    ) -> dict:
        return {"total": self._thematic_total, "accuracy": self._thematic_accuracy}


# =============================================================================
# Defect A — the blend must be a normalized weighted average
# =============================================================================


class TestWeightNormalization:
    async def test_unanimous_high_confidence_reaches_top_of_range(self):
        """Strong analyst confidence + strong track record must not cap near 0.8.

        Pre-fix this returned ~0.828 because the raw weights summed to 0.8.
        """
        adjuster = _StubAdjuster(
            historical_accuracy=0.90,
            historical_total=40,
            thematic_accuracy=0.88,
            thematic_total=10,
            symbol_accuracy=0.90,
            symbol_total=8,
        )

        result = await adjuster.adjust_confidence(
            base_confidence=0.92,
            insight_type="opportunity",
            action_type="BUY",
            symbols=["NVDA"],
        )

        assert result["adjusted_confidence"] >= 0.90
        assert math.isclose(result["adjusted_confidence"], 0.91, abs_tol=1e-4)

    async def test_applied_weights_sum_to_one_with_all_components(self):
        adjuster = _StubAdjuster(
            historical_accuracy=0.6,
            historical_total=40,
            thematic_accuracy=0.6,
            thematic_total=10,
            symbol_accuracy=0.6,
            symbol_total=8,
        )

        result = await adjuster.adjust_confidence(
            base_confidence=0.7,
            insight_type="opportunity",
            action_type="BUY",
            symbols=["NVDA"],
        )

        weights = result["applied_weights"]
        assert set(weights) == {"base", "historical", "thematic", "symbol"}
        assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-6)

    async def test_applied_weights_sum_to_one_without_thematic_or_symbol(self):
        """Absent components must be renormalized away, not silently drop mass."""
        adjuster = _StubAdjuster(
            historical_accuracy=0.6,
            historical_total=40,
            thematic_total=0,
            symbol_total=0,
        )

        result = await adjuster.adjust_confidence(
            base_confidence=0.7,
            insight_type="opportunity",
            action_type="BUY",
            symbols=["NVDA"],
        )

        weights = result["applied_weights"]
        assert set(weights) == {"base", "historical"}
        assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-6)
        # 0.6/0.8 and 0.2/0.8
        assert math.isclose(weights["base"], 0.75, abs_tol=1e-6)
        assert math.isclose(weights["historical"], 0.25, abs_tol=1e-6)

    async def test_base_only_applied_weight_is_one(self):
        adjuster = _StubAdjuster(historical_total=0, thematic_total=0, symbol_total=0)

        result = await adjuster.adjust_confidence(
            base_confidence=0.61,
            insight_type="opportunity",
            action_type="BUY",
        )

        assert result["applied_weights"] == {"base": 1.0}
        assert math.isclose(result["adjusted_confidence"], 0.61, abs_tol=1e-6)

    async def test_mid_range_input_is_not_deflated(self):
        """A weighted average of identical inputs must return that input.

        Pre-fix a 0.55 analyst call with a 0.55 track record came back at 0.5005.
        """
        adjuster = _StubAdjuster(
            historical_accuracy=0.55,
            historical_total=30,
            thematic_accuracy=0.55,
            thematic_total=6,
            symbol_accuracy=0.55,
            symbol_total=5,
        )

        result = await adjuster.adjust_confidence(
            base_confidence=0.55,
            insight_type="opportunity",
            action_type="BUY",
            symbols=["AAPL"],
        )

        assert math.isclose(result["adjusted_confidence"], 0.55, abs_tol=1e-4)

    async def test_weak_track_record_still_pulls_confidence_down(self):
        """Normalization must not neuter the adjuster — bad history still bites."""
        adjuster = _StubAdjuster(
            historical_accuracy=0.20,
            historical_total=40,
            thematic_total=0,
            symbol_total=0,
        )

        result = await adjuster.adjust_confidence(
            base_confidence=0.80,
            insight_type="opportunity",
            action_type="STRONG_BUY",
        )

        # 0.75 * 0.80 + 0.25 * 0.20
        assert math.isclose(result["adjusted_confidence"], 0.65, abs_tol=1e-4)
        assert result["adjusted_confidence"] < 0.80

    @pytest.mark.parametrize(
        "components,expected",
        [
            ([("base", 0.8, 0.6)], 0.8),
            ([("base", 0.8, 0.6), ("historical", 0.4, 0.2)], 0.7),
            ([], 0.0),
            ([("base", 0.8, 0.0)], 0.0),
        ],
    )
    def test_weighted_average_helper(self, components, expected):
        value, weights = ConfidenceAdjuster._weighted_average(components)
        assert math.isclose(value, expected, abs_tol=1e-6)
        if weights:
            assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-6)

    async def test_decay_variant_blend_is_normalized(self):
        """adjust_confidence_with_decay shared the same un-normalized formula.

        Pre-fix a 0.60 call with a 0.60 track record and zero staleness
        returned 0.48.
        """
        adjuster = _StubAdjuster()

        adjusted = adjuster.adjust_confidence_with_decay(
            base_confidence=0.60,
            symbol="AAPL",
            staleness_score=0.0,
            track_record={"success_rate": 0.60, "total_insights": 20},
        )

        assert math.isclose(adjusted, 0.60, abs_tol=1e-4)


class TestConfidenceBounds:
    async def test_upper_bound_still_enforced(self):
        adjuster = _StubAdjuster(
            historical_accuracy=1.0,
            historical_total=50,
            thematic_accuracy=1.0,
            thematic_total=10,
            symbol_accuracy=1.0,
            symbol_total=10,
        )

        result = await adjuster.adjust_confidence(
            base_confidence=0.99,
            insight_type="opportunity",
            action_type="BUY",
            symbols=["NVDA"],
        )

        assert result["adjusted_confidence"] == ConfidenceAdjuster.MAX_CONFIDENCE

    async def test_lower_bound_still_enforced(self):
        adjuster = _StubAdjuster(
            historical_accuracy=0.0,
            historical_total=50,
            thematic_accuracy=0.0,
            thematic_total=10,
            symbol_accuracy=0.0,
            symbol_total=10,
        )

        result = await adjuster.adjust_confidence(
            base_confidence=0.0,
            insight_type="opportunity",
            action_type="BUY",
            symbols=["NVDA"],
        )

        assert result["adjusted_confidence"] == ConfidenceAdjuster.MIN_CONFIDENCE


# =============================================================================
# Defect B — the prompt must define confidence as probability, not agreement
# =============================================================================


class TestConfidencePromptGuidance:
    def test_synthesis_prompt_no_longer_defines_confidence_as_agreement(self):
        assert "Multiple analysts agree with high individual confidence" not in SYNTHESIS_LEAD_PROMPT
        assert "Majority agreement or strong single-analyst signal" not in SYNTHESIS_LEAD_PROMPT

    def test_synthesis_prompt_states_base_rate_anchor(self):
        assert "35%" in SYNTHESIS_LEAD_PROMPT
        assert "beat SPY by more than 2%" in SYNTHESIS_LEAD_PROMPT
        assert "probability that this specific thesis is validated" in SYNTHESIS_LEAD_PROMPT

    def test_synthesis_prompt_rejects_agreement_as_justification(self):
        assert "Analyst agreement is NOT a justification" in SYNTHESIS_LEAD_PROMPT
        # and says why.  The reason changed when the specialists were blinded:
        # they no longer share a discovery prior, so claiming they do would be a
        # false statement that suppresses legitimate corroboration signal.
        assert "share a prior" not in SYNTHESIS_LEAD_PROMPT
        assert "same discovery context" not in SYNTHESIS_LEAD_PROMPT
        assert "run blind" in SYNTHESIS_LEAD_PROMPT
        assert "separately elicited views from one underlying model" in SYNTHESIS_LEAD_PROMPT
        assert "errors stay correlated" in SYNTHESIS_LEAD_PROMPT
        # The rule that survives unchanged: agreement counts only from
        # different observable data.
        assert "different observable data" in SYNTHESIS_LEAD_PROMPT

    def test_synthesis_prompt_warns_about_high_confidence_band(self):
        assert "above 0.70 have hit LESS often" in SYNTHESIS_LEAD_PROMPT
