from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _Candidate:
    symbol: str
    rank: int
    overall_score: float
    confidence: float
    thesis_type: str
    bull_case: str
    bear_case: str
    portfolio_relevance: str
    key_drivers: list[str]
    is_portfolio_holding: bool = False
    expected_horizon_days: int = 45
    target_price: float | None = None
    stop_price: float | None = None


def test_build_alpha_candidate_context_mentions_ranked_candidates():
    from analysis.alpha_synthesis import build_alpha_candidate_context

    candidates = [
        _Candidate(
            symbol="AAPL",
            rank=1,
            overall_score=82.5,
            confidence=0.78,
            thesis_type="quality_re_rate",
            bull_case="Strong",
            bear_case="Weak",
            portfolio_relevance="Add",
            key_drivers=["tech:80", "rev:70"],
        )
    ]
    overlay = {"concentration_risk": "moderate", "suggestions": [{"symbol": "AAPL", "action": "add", "score": 82.5, "confidence": 0.78, "reason": "strong"}]}
    text = build_alpha_candidate_context(candidates, overlay, regime=type("R", (), {"name": "risk_on_growth", "confidence": 0.7})())

    assert "Alpha Candidate Ranking" in text
    assert "AAPL" in text
    assert "Portfolio Overlay" in text


def test_action_mapping_prefers_hold_for_middling_holding():
    from analysis.alpha_synthesis import _action_for_candidate

    candidate = _Candidate(
        symbol="MSFT",
        rank=2,
        overall_score=58.0,
        confidence=0.55,
        thesis_type="setup",
        bull_case="",
        bear_case="",
        portfolio_relevance="",
        key_drivers=[],
        is_portfolio_holding=True,
    )

    assert _action_for_candidate(candidate) == "HOLD"
