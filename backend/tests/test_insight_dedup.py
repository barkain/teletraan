"""Tests for AutonomousDeepEngine._dedupe_insights.

Regression: a discovery run produced two insights both anchored on GLW
(a single-stock 'rotation' thesis and a portfolio-basket 'macro' insight),
because no insight-level dedup existed between synthesis parsing and
persistence.
"""

from analysis.autonomous_engine import AutonomousDeepEngine

dedupe = AutonomousDeepEngine._dedupe_insights


def _insight(symbol, confidence, title="t", related=None, **extra):
    return {
        "primary_symbol": symbol,
        "confidence": confidence,
        "title": title,
        "related_symbols": related or [],
        **extra,
    }


def test_empty_list_passthrough():
    assert dedupe([]) == []


def test_unique_symbols_untouched():
    insights = [_insight("NVDA", 0.7), _insight("META", 0.5), _insight("UNH", 0.6)]
    assert dedupe(insights) == insights


def test_duplicate_symbol_keeps_higher_confidence():
    # The observed GLW case: rotation insight (0.65) + macro basket (0.67).
    rotation = _insight(
        "GLW", 0.65, title="GLW Optical Connectivity", related=["LITE", "COHR", "AAOI", "II-VI"],
        insight_type="rotation",
    )
    basket = _insight(
        "GLW", 0.67, title="Portfolio Optical Basket", related=["LITE", "COHR", "AAOI", "MRVL"],
        insight_type="macro",
    )
    result = dedupe([rotation, basket])
    assert len(result) == 1
    assert result[0]["title"] == "Portfolio Optical Basket"
    # Loser's related symbols merged in, deduped, order preserved.
    assert result[0]["related_symbols"] == ["LITE", "COHR", "AAOI", "MRVL", "II-VI"]


def test_duplicate_keeps_first_on_confidence_tie():
    a = _insight("GLW", 0.6, title="first")
    b = _insight("GLW", 0.6, title="second")
    result = dedupe([a, b])
    assert len(result) == 1
    assert result[0]["title"] == "first"


def test_symbol_match_is_case_insensitive():
    result = dedupe([_insight("glw", 0.5), _insight("GLW", 0.9)])
    assert len(result) == 1
    assert result[0]["confidence"] == 0.9


def test_null_primary_symbol_never_collapsed():
    # Basket/theme insights without a primary symbol must all survive.
    insights = [
        _insight(None, 0.6, title="theme a"),
        _insight(None, 0.7, title="theme b"),
        _insight("", 0.5, title="theme c"),
    ]
    assert dedupe(insights) == insights


def test_winner_position_preserves_original_order():
    insights = [
        _insight("GLW", 0.65, title="loser"),
        _insight("NVDA", 0.7, title="nvda"),
        _insight("GLW", 0.9, title="winner"),
    ]
    result = dedupe(insights)
    assert [i["title"] for i in result] == ["winner", "nvda"]


def test_merged_related_excludes_primary_itself():
    a = _insight("GLW", 0.9, related=["LITE"])
    b = _insight("GLW", 0.5, related=["GLW", "COHR"])
    result = dedupe([a, b])
    assert result[0]["related_symbols"] == ["LITE", "COHR"]


def test_missing_confidence_treated_as_zero():
    a = _insight("GLW", None, title="no-conf")
    b = _insight("GLW", 0.4, title="scored")
    result = dedupe([a, b])
    assert len(result) == 1
    assert result[0]["title"] == "scored"
