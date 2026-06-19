"""Tests for live-price verification of synthesis insights.

Regression: best_bets surfaced SE with a "$215 (+35%)" target while SE traded
~$91 — the upside % was LLM-asserted against a hallucinated base and never
recomputed. _verify_insight_economics recomputes upside/R:R from the live price,
relabels honestly, and (for concentrated policies) drops sub-floor or
mis-anchored picks and ranks best-first.
"""

from analysis.autonomous_engine import AutonomousDeepEngine, _parse_price_level
from analysis.research_policy import get_preset


def _ins(sym, target, stop="$10", **extra):
    return {"primary_symbol": sym, "target_price": target, "stop_loss": stop,
            "title": "t", "thesis": "y", "confidence": 0.5, **extra}


def test_parse_price_level():
    assert _parse_price_level("$215 (35% upside)") == 215.0
    assert _parse_price_level("$140 (below support)") == 140.0
    assert _parse_price_level("$1,250 target") == 1250.0
    assert _parse_price_level("$880-900") == 880.0       # first of a range
    assert _parse_price_level("N/A - bearish") is None
    assert _parse_price_level(None) is None


def test_relabels_upside_from_live_price():
    e = AutonomousDeepEngine()
    e._policy = get_preset("balanced")  # not concentrated -> no gating, just relabel
    out = e._verify_insight_economics([_ins("ARM", "$270 (28% upside)", "$188")], {"ARM": 150.0})
    assert out[0]["_verified_upside_pct"] == 80.0   # 270/150 - 1
    assert "live $150" in out[0]["target_price"]


def test_concentrated_drops_mis_anchored_short_horizon():
    e = AutonomousDeepEngine()
    e._policy = get_preset("best_bets")  # short_term, cap 3, floor 25%
    out = e._verify_insight_economics(
        [_ins("SE", "$215 (35% upside)", "$140")], {"SE": 91.28}
    )
    # 215 vs 91.28 = +135%, implausible for a ~2-week window -> dropped
    assert out == []


def test_concentrated_drops_below_floor_and_ranks():
    e = AutonomousDeepEngine()
    e._policy = get_preset("best_bets")  # floor 25%, drop below ~15%
    ins = [
        _ins("LOW", "$104", "$95"),    # +4% vs 100 -> below floor, dropped
        _ins("MID", "$130", "$90"),    # +30% vs 100 -> kept
        _ins("HIGH", "$150", "$92"),   # +50% vs 100 -> kept, ranks first
    ]
    out = e._verify_insight_economics(ins, {"LOW": 100.0, "MID": 100.0, "HIGH": 100.0})
    assert [i["primary_symbol"] for i in out] == ["HIGH", "MID"]


def test_missing_live_price_is_kept_not_dropped():
    e = AutonomousDeepEngine()
    e._policy = get_preset("best_bets")
    out = e._verify_insight_economics([_ins("XYZ", "$50")], {})  # no price -> can't verify
    assert [i["primary_symbol"] for i in out] == ["XYZ"]
    assert "_verified_upside_pct" not in out[0]
