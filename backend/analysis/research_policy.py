"""Research policy — the declarative objective function for autonomous discovery.

A ``ResearchPolicy`` defines *what the pipeline is optimizing for* (asymmetric
upside vs. balanced vs. capital preservation) and the guardrails around it. The
objective lives here as data, not hardcoded in agent prompts, so the same engine
can produce very different idea sheets by swapping the active policy.

The policy drives the pipeline two ways:
  1. Rendered directives — ``render_policy_directives(policy, phase)`` produces a
     mandate block injected into the selection and synthesis contexts, so every
     agent shares one objective.
  2. Numeric gates — fields like ``min_reward_risk``, ``tiers`` and
     ``tail_risk_override_pct`` are read directly in engine code.

Resolution order (see ``build_policy``): per-run override → active policy stored
in ``user_settings['research_policy']`` → built-in default preset (env-selectable).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PolicyTier(BaseModel):
    """One output bucket. Insights are labeled with a tier ``name``."""

    name: str
    label: str
    min_reward_risk: float = 0.0  # min upside:downside to qualify for this tier
    max_count: int = 5
    position_size_pct: str = "1-3%"
    note: str = ""


class ResearchPolicy(BaseModel):
    """Declarative objective + guardrails for an autonomous discovery run."""

    name: str = "balanced"
    description: str = ""

    # --- Objective: what we optimize for ---
    objective: str = "balanced"  # asymmetric_upside | balanced | capital_preservation | income
    risk_appetite: float = Field(0.5, ge=0.0, le=1.0)  # variance tolerance
    min_reward_risk: float = 2.0  # floor R:R to call something an "opportunity"
    target_upside_pct: float = 25.0  # min bull-case upside for the top tier

    # --- Universe: where we hunt ---
    include_small_mid_cap: bool = False
    market_cap_floor_b: float | None = None  # $B floor; None = no floor
    asset_classes: list[str] = Field(default_factory=lambda: ["equity", "adr", "commodity"])
    candidate_sources: list[str] = Field(default_factory=lambda: ["heatmap"])
    exclude_sectors: list[str] = Field(default_factory=list)

    # --- Conviction & output shape ---
    conviction_model: str = "consensus"  # consensus | payoff_weighted | barbell
    allow_contested_ideas: bool = False  # let high-upside/low-agreement ideas survive
    require_quantified_levels: bool = True  # force entry/target/stop on every insight
    tiers: list[PolicyTier] = Field(default_factory=list)

    # --- Guardrails ---
    tail_risk_override_pct: float = 15.0  # risk veto only above this tail-risk prob
    max_position_pct: float = 7.0

    def tier_names(self) -> list[str]:
        return [t.name for t in self.tiers]


# ---------------------------------------------------------------------------
# Built-in presets
# ---------------------------------------------------------------------------

_BALANCED = ResearchPolicy(
    name="balanced",
    description="Mix of asymmetric opportunities and steady core ideas. Default.",
    objective="balanced",
    risk_appetite=0.5,
    min_reward_risk=2.0,
    target_upside_pct=25.0,
    include_small_mid_cap=False,
    asset_classes=["equity", "adr", "commodity"],
    candidate_sources=["heatmap"],
    conviction_model="payoff_weighted",
    allow_contested_ideas=False,
    require_quantified_levels=True,
    tail_risk_override_pct=15.0,
    max_position_pct=7.0,
    tiers=[
        PolicyTier(name="high_conviction", label="High-Conviction", min_reward_risk=2.5,
                   max_count=4, position_size_pct="4-6%", note="Strong multi-signal setups."),
        PolicyTier(name="opportunistic", label="Opportunistic", min_reward_risk=1.5,
                   max_count=4, position_size_pct="2-4%", note="Promising but earlier or contested."),
        PolicyTier(name="core", label="Defensive Core", min_reward_risk=0.0,
                   max_count=3, position_size_pct="3-5%", note="Lower-variance ballast / income."),
    ],
)

_AGGRESSIVE = ResearchPolicy(
    name="aggressive_asymmetric",
    description="Hunt high-stakes, high-upside asymmetric bets. Variance is the price of convexity.",
    objective="asymmetric_upside",
    risk_appetite=0.9,
    min_reward_risk=3.0,
    target_upside_pct=50.0,
    include_small_mid_cap=True,
    market_cap_floor_b=None,
    asset_classes=["equity", "adr", "commodity"],
    candidate_sources=["heatmap", "catalyst_calendar", "high_short_interest",
                       "unusual_volume", "52w_extremes", "movers"],
    conviction_model="barbell",
    allow_contested_ideas=True,
    require_quantified_levels=True,
    tail_risk_override_pct=30.0,  # tolerate more tail risk for convexity
    max_position_pct=5.0,
    tiers=[
        PolicyTier(name="asymmetric", label="High-Conviction Asymmetric", min_reward_risk=3.0,
                   max_count=5, position_size_pct="2-4%",
                   note="Small-sized, high-variance bets with a credible 2-5x / sharp re-rating path."),
        PolicyTier(name="thematic", label="Thematic / Swing", min_reward_risk=2.0,
                   max_count=4, position_size_pct="2-3%",
                   note="Catalyst-driven swings riding a live theme."),
        PolicyTier(name="core", label="Defensive Core", min_reward_risk=0.0,
                   max_count=2, position_size_pct="3-5%",
                   note="Minimal ballast only — this mandate is about the satellites, not the core."),
    ],
)

_DEFENSIVE = ResearchPolicy(
    name="defensive_income",
    description="Capital preservation and income; favor low-variance, quality, dividend names.",
    objective="capital_preservation",
    risk_appetite=0.2,
    min_reward_risk=1.5,
    target_upside_pct=12.0,
    include_small_mid_cap=False,
    market_cap_floor_b=10.0,
    asset_classes=["equity", "commodity"],
    candidate_sources=["heatmap"],
    conviction_model="consensus",
    allow_contested_ideas=False,
    require_quantified_levels=True,
    tail_risk_override_pct=10.0,  # quick to veto on tail risk
    max_position_pct=8.0,
    tiers=[
        PolicyTier(name="core", label="Quality Core", min_reward_risk=1.5,
                   max_count=6, position_size_pct="4-7%", note="Durable, lower-beta compounders."),
        PolicyTier(name="income", label="Income", min_reward_risk=0.0,
                   max_count=4, position_size_pct="3-6%", note="Yield with capital stability."),
    ],
)

PRESETS: dict[str, ResearchPolicy] = {
    p.name: p for p in (_BALANCED, _AGGRESSIVE, _DEFENSIVE)
}

DEFAULT_POLICY_NAME = "balanced"


def get_preset(name: str | None) -> ResearchPolicy:
    """Return a copy of a named preset, falling back to the default."""
    preset = PRESETS.get((name or "").strip()) or PRESETS[DEFAULT_POLICY_NAME]
    return preset.model_copy(deep=True)


def build_policy(
    override: str | dict[str, Any] | None = None,
    active_setting: str | dict[str, Any] | None = None,
    env_default: str | None = None,
) -> ResearchPolicy:
    """Resolve the effective policy (pure; no I/O).

    Precedence: ``override`` (per-run) → ``active_setting`` (user_settings) →
    ``env_default`` preset name → built-in default.

    Each of ``override`` / ``active_setting`` may be:
      * a preset name (str), or
      * a dict of field overrides, optionally with ``{"base": "<preset>"}`` to
        choose the preset the overrides are layered onto.
    """
    chosen = override if override is not None else active_setting

    if isinstance(chosen, str) and chosen.strip():
        return get_preset(chosen)

    if isinstance(chosen, dict) and chosen:
        base_name = chosen.get("base") or env_default or DEFAULT_POLICY_NAME
        base = get_preset(base_name)
        patch = {k: v for k, v in chosen.items() if k != "base" and v is not None}
        return base.model_copy(update=patch, deep=True)

    return get_preset(env_default or DEFAULT_POLICY_NAME)


# ---------------------------------------------------------------------------
# Rendered directives — injected into agent contexts
# ---------------------------------------------------------------------------

def render_policy_directives(policy: ResearchPolicy, phase: str) -> str:
    """Render the policy into a markdown mandate block for a pipeline phase.

    Args:
        policy: The resolved research policy.
        phase: ``"selection"`` (heatmap stock picking) or ``"synthesis"``.

    Returns:
        Markdown directive block (never empty).
    """
    if phase == "selection":
        return _render_selection(policy)
    return _render_synthesis(policy)


def _render_selection(policy: ResearchPolicy) -> str:
    lines = [
        f"## Research Mandate: {policy.name} ({policy.objective})",
        policy.description,
        "",
        "Apply this mandate when choosing which names to deep-dive:",
        f"- Risk appetite: {policy.risk_appetite:.0%}. "
        + (
            "Favor high-variance, catalyst-rich names with large potential moves over tidy, low-beta setups."
            if policy.risk_appetite >= 0.66
            else "Favor durable, lower-variance quality names."
            if policy.risk_appetite <= 0.33
            else "Balance opportunity against stability."
        ),
        f"- Score candidates primarily by POTENTIAL MOVE SIZE and catalyst proximity, "
        f"targeting setups with at least ~{policy.target_upside_pct:.0f}% upside to a credible target — "
        f"not merely by how analytically interesting the pattern is.",
        f"- Asset classes in scope: {', '.join(policy.asset_classes)}.",
    ]
    if policy.include_small_mid_cap:
        lines.append(
            "- Small- and mid-cap names are IN SCOPE and encouraged — that is where "
            "asymmetric upside often lives. Do not restrict to mega-caps."
        )
    else:
        lines.append("- Prefer liquid large-cap names.")
    if policy.market_cap_floor_b:
        lines.append(f"- Avoid names below ~${policy.market_cap_floor_b:.0f}B market cap.")
    if policy.exclude_sectors:
        lines.append(f"- Exclude sectors: {', '.join(policy.exclude_sectors)}.")
    if "catalyst_calendar" in policy.candidate_sources:
        lines.append("- Prioritize names with a known catalyst (earnings, regulatory, product) on the horizon.")
    return "\n".join(lines)


def _render_synthesis(policy: ResearchPolicy) -> str:
    model_line = {
        "barbell": (
            "Construct a BARBELL: a handful of genuinely asymmetric, small-sized high-upside "
            "bets alongside a thin defensive core. Do NOT blend them into one mushy middle."
        ),
        "payoff_weighted": (
            "Rank ideas by asymmetric payoff (upside-to-target ÷ downside-to-stop), "
            "not by how many analysts agree."
        ),
        "consensus": (
            "Favor ideas with strong multi-analyst agreement and clear risk/reward."
        ),
    }.get(policy.conviction_model, "Rank ideas by risk-adjusted payoff.")

    lines = [
        f"## Research Mandate: {policy.name} ({policy.objective})",
        policy.description,
        "",
        f"**Objective:** {model_line}",
        f"**Payoff floor:** An idea only qualifies as a top-tier opportunity when its "
        f"reward:risk ≥ {policy.min_reward_risk:.1f} and the bull-case upside ≥ "
        f"{policy.target_upside_pct:.0f}%.",
    ]
    if policy.require_quantified_levels:
        lines.append(
            "**Quantified levels are REQUIRED:** every insight MUST include `entry_zone`, "
            "`target` (with an explicit % to target), and `stop_loss`. Express the payoff. "
            "An insight without quantified levels is incomplete."
        )
    if policy.allow_contested_ideas:
        lines.append(
            "**Contested ideas are welcome:** a high-upside thesis that some analysts doubt is "
            "still valid — the edge lives where there is disagreement. Do NOT demote it to WATCH "
            "for lack of consensus; reflect the doubt in `risk_factors` and size it smaller instead."
        )
    lines.append(
        f"**Risk veto:** only let a risk warning override a bullish thesis when tail-risk "
        f"probability exceeds {policy.tail_risk_override_pct:.0f}%."
    )

    if policy.tiers:
        lines.append("")
        lines.append(
            "**Assign every insight a `tier`** (string field) from the buckets below, "
            "and size per the tier guidance:"
        )
        for t in policy.tiers:
            rr = f" — requires reward:risk ≥ {t.min_reward_risk:.1f}" if t.min_reward_risk else ""
            lines.append(
                f"- `{t.name}` ({t.label}, up to {t.max_count}, size {t.position_size_pct}){rr}: {t.note}"
            )
    lines.append(
        f"\nKeep position sizes at or below {policy.max_position_pct:.0f}% of portfolio per name."
    )
    return "\n".join(lines)
