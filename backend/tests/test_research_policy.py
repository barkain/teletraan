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


def test_normalize_tier_maps_to_policy_names():
    e = AutonomousDeepEngine()
    e._policy = get_preset("aggressive_asymmetric")
    assert e._normalize_tier("Asymmetric") == "asymmetric"
    assert e._normalize_tier("high-conviction asymmetric") in {"asymmetric", "high-conviction asymmetric"}
    assert e._normalize_tier("  ") is None
    assert e._normalize_tier("unknown_bucket") == "unknown_bucket"  # raw passthrough
