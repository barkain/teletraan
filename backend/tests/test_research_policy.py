"""Tests for the research-policy objective layer."""

from analysis.research_policy import (
    PRESETS,
    DEFAULT_POLICY_NAME,
    build_policy,
    get_preset,
    render_policy_directives,
)
from analysis.autonomous_engine import AutonomousDeepEngine


def test_presets_exist():
    assert {"balanced", "aggressive_asymmetric", "defensive_income"} <= set(PRESETS)


def test_get_preset_returns_copy_and_falls_back():
    a = get_preset("aggressive_asymmetric")
    a.min_reward_risk = 99.0
    assert get_preset("aggressive_asymmetric").min_reward_risk == 3.0  # original untouched
    assert get_preset("does_not_exist").name == DEFAULT_POLICY_NAME


def test_build_policy_precedence_override_wins():
    p = build_policy(override="aggressive_asymmetric", active_setting="defensive_income", env_default="balanced")
    assert p.name == "aggressive_asymmetric"


def test_build_policy_active_setting_when_no_override():
    p = build_policy(override=None, active_setting="defensive_income", env_default="balanced")
    assert p.name == "defensive_income"


def test_build_policy_env_default_when_nothing_set():
    assert build_policy(None, None, "aggressive_asymmetric").name == "aggressive_asymmetric"
    assert build_policy(None, None, None).name == DEFAULT_POLICY_NAME


def test_build_policy_dict_override_layers_on_base():
    p = build_policy(override={"base": "balanced", "target_upside_pct": 40, "allow_contested_ideas": True})
    assert p.name == "balanced"  # base preset identity preserved
    assert p.target_upside_pct == 40
    assert p.allow_contested_ideas is True


def test_aggressive_directives_carry_asymmetry_language():
    p = get_preset("aggressive_asymmetric")
    sel = render_policy_directives(p, "selection")
    syn = render_policy_directives(p, "synthesis")
    assert "asymmetric" in syn.lower()
    assert "barbell" in syn.lower()
    assert "reward:risk" in syn.lower()
    assert "small- and mid-cap" in sel.lower()
    # required quantified levels surfaced
    assert "entry_zone" in syn


def test_best_bets_is_concentrated_short_horizon():
    p = get_preset("best_bets")
    assert p.max_total_insights == 3
    assert p.time_horizon_bias == "short_term"
    syn = render_policy_directives(p, "synthesis")
    sel = render_policy_directives(p, "selection")
    assert "AT MOST 3" in syn          # hard ceiling, not a floor
    assert "1-2 week" in syn           # short holding window
    assert "1-2 week" in sel


def test_count_guidance_concentrated_vs_floor():
    e = AutonomousDeepEngine()
    e._policy = get_preset("best_bets")
    target, count = e._synthesis_count_guidance(10, 3)
    assert "TOP 3" in target
    assert "Returning fewer is fine" in count and "AT LEAST" not in count
    # default policy keeps the floor behavior
    e._policy = get_preset("balanced")
    _, count2 = e._synthesis_count_guidance(7, 10)
    assert "AT LEAST" in count2


def test_concentrated_clamp_logic():
    p = get_preset("best_bets")
    assert min(10, p.max_total_insights) == 3
    assert min(2, p.max_total_insights) == 2  # caller asking for fewer wins


def test_normalize_tier_maps_to_policy_names():
    e = AutonomousDeepEngine()
    e._policy = get_preset("aggressive_asymmetric")
    assert e._normalize_tier("Asymmetric") == "asymmetric"
    assert e._normalize_tier("high-conviction asymmetric") in {"asymmetric", "high-conviction asymmetric"}
    assert e._normalize_tier("  ") is None
    assert e._normalize_tier("unknown_bucket") == "unknown_bucket"  # raw passthrough
