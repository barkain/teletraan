"""Per-symbol evidence panel: what the synthesis lead is actually shown.

The autonomous deep dive runs three specialists (technical, sector, risk) once
per candidate symbol, then had to hand their work to one synthesis call.  It
used to do that through ``_flatten_analyst_reports``, which aggregated by
*analyst type* across the whole run: one technical bucket, one sector bucket,
one risk bucket, each with a single confidence produced by ``(a + b) / 2``.
Measured on the 2026-08-18 run, that representation delivered 5 of 23 technical
findings (all from 2 of 5 symbols, because the downstream cap takes a prefix in
dict order), 0 of 55 sector rankings, 0 of 27 sector recommendations, and a
market phase of "Unknown" while every analyst had said mid/late expansion at
0.72-0.82 confidence.

This module builds the replacement: a **per-symbol panel** that keeps the
symbol boundary, the analyst boundary, each analyst's own confidence, its
thesis, its supporting and opposing evidence, and its invalidation conditions.
Nothing here merges confidences and nothing here caps across the run — the
budget is per symbol, and any truncation is stated in-band.

The module is pure: dicts in, dicts out, no I/O and no engine imports, so the
panel can be built in a test from stored reports exactly as the engine builds
it in production.

Deviations from the design brief are documented at each site; the summary is:

* The specialists' output contracts do **not** contain a ``decision`` envelope
  (stance/thesis/evidence/invalidation), and the prompts are out of scope for
  this change.  The envelope here is therefore *derived* from what the existing
  parsers really produce, and every derived stance carries a ``stance_basis``
  string naming the derivation.  A derived stance must not be read as the
  analyst's own word.
* The sector strategist is asked for a market-wide table and answers with one;
  it never states a target-symbol view.  Rather than invent one, the panel
  hoists the shared table into a single market-wide block (deduplicated across
  the near-identical per-symbol runs) and keeps only target-naming statements
  in each symbol's block.
* Risk ``BLOCK`` is never derived from prose.  ``PASS``/``CAUTION`` are derived
  from the normalised reward/risk ratio; a veto has to be machine-verifiable,
  which nothing in a free-text risk report is.
"""

from __future__ import annotations

import re
from typing import Any

from analysis.agents.risk_analyst import normalize_risk_report

PANEL_SCHEMA_VERSION = "symbol_panel.v1"

# Per-symbol rendering budget.  Never a run-global cap: a run-global cap is the
# defect being fixed, because it silently drops whole symbols in dict order.
MAX_PANEL_CHARS_PER_SYMBOL = 6000
# The market-wide sector block is rendered once for the whole run, not per
# symbol, so it gets its own budget.
MAX_MARKET_WIDE_CHARS = 5000

# Per-analyst item caps.  These bound one symbol's block; the counts of what was
# kept and what existed travel with the panel so truncation is never silent.
MAX_TECHNICAL_FINDINGS = 3
MAX_EVIDENCE_ITEMS = 6
MAX_COUNTER_EVIDENCE_ITEMS = 5
MAX_DETAIL_OBSERVATIONS = 3

DIRECTIONAL_ANALYSTS = ("technical", "sector")
PANEL_ANALYSTS = ("technical", "sector", "risk")

_BULLISH_BIAS = {"BUY", "STRONG_BUY", "LONG", "ACCUMULATE"}
_BEARISH_BIAS = {"SELL", "STRONG_SELL", "SHORT", "REDUCE", "AVOID"}


# =============================================================================
# Per-symbol selection -- shared with InsightResearchContext persistence
# =============================================================================


def clean_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop a failed report and strip orchestration-private top-level keys.

    Lifted verbatim from ``_create_research_context`` so the synthesis panel and
    the persisted ``InsightResearchContext`` select a symbol's reports by the
    same rule.  ``None`` means "this analyst has nothing usable for this
    symbol", which the panel renders as an explicit missing/failed status rather
    than omitting the analyst (two reports must not look like a unanimous
    three-report panel).
    """
    if not report or "error" in report:
        return None
    return {k: v for k, v in report.items() if not k.startswith("_")}


def select_symbol_reports(
    analyst_reports: dict[str, dict[str, Any]],
    symbol: str | None,
) -> dict[str, dict[str, Any] | None]:
    """Select one symbol's analyst reports, cleaned.

    Args:
        analyst_reports: ``{symbol: {analyst: report}}`` as produced by
            ``_run_analysts_for_symbol``.
        symbol: The symbol to select. ``None`` yields all-``None``.

    Returns:
        ``{analyst_name: cleaned_report_or_None}`` for every analyst the symbol
        has an entry for.
    """
    symbol_reports = analyst_reports.get(symbol, {}) if symbol else {}
    if not isinstance(symbol_reports, dict):
        return {}
    return {name: clean_report(report) for name, report in symbol_reports.items()}


def _report_status(raw: Any) -> tuple[str, str | None]:
    """Classify a raw analyst report as ok / error / missing."""
    if not isinstance(raw, dict) or not raw:
        return "missing", None
    if "error" in raw:
        return "error", str(raw.get("error"))
    return "ok", None


# =============================================================================
# Small tolerant readers -- absent must stay distinguishable from zero
# =============================================================================


def _opt_float(value: Any) -> float | None:
    """Float or ``None``.  Never a 0.0 stand-in for an absent measurement."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opt_str(value: Any) -> str | None:
    """Non-empty string or ``None``."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mentions(text: Any, symbol: str) -> bool:
    """Does this free text name the target ticker?

    Word-ish boundaries so ``NU`` does not match ``NUE``; symbols carrying
    punctuation (``CL=F``, ``BRK.B``) are escaped rather than tokenised.
    """
    if not isinstance(text, str) or not symbol:
        return False
    pattern = rf"(?<![A-Za-z0-9]){re.escape(symbol)}(?![A-Za-z0-9])"
    return re.search(pattern, text) is not None


# Evidence buckets.  These name the *direction of the claim itself*, never its
# agreement with the stance this module derived for the report.  Filing by
# agreement is what put an AMD ``oversold`` finding -- whose own description
# said the selloff was overdone and the recovery may continue -- under a
# heading reading "evidence against", and what printed a neutral sector
# paragraph under "evidence for".  A HOLD/NEUTRAL claim is neither.
EVIDENCE_BUCKETS = ("bullish", "bearish", "neutral_or_mixed", "conflicting")

# The bucket key each one carries in a decision dict.  ``conflicting`` keeps the
# technical analyst's own field name rather than being sorted into a direction:
# ``conflicting_signals`` means "signals that conflict with my read", which is
# the analyst's statement, not the orchestrator's inference.
EVIDENCE_KEYS = {
    "bullish": "bullish_evidence",
    "bearish": "bearish_evidence",
    "neutral_or_mixed": "neutral_or_mixed_evidence",
    "conflicting": "conflicting_signals",
}

_ID_MARKER = {
    "bullish": "bull",
    "bearish": "bear",
    "neutral_or_mixed": "mixed",
    "conflicting": "conflict",
}


def _evidence(symbol: str, analyst: str, claims: list[str], kind: str = "bullish") -> list[dict[str, str]]:
    """Attach stable IDs to claims.

    The ID names the bucket the claim was filed in, so a later citation check
    can verify not merely that an ID exists but that it was cited on the side it
    was actually filed on.  The orchestrator assigns IDs after parsing, never
    the model, so a synthesis citation can be checked mechanically against the
    panel it was given.
    """
    marker = _ID_MARKER[kind]
    return [
        {"id": f"{symbol}:{analyst}:{marker}{index}", "claim": claim}
        for index, claim in enumerate(claims, start=1)
        if claim
    ]


def _buckets(
    symbol: str,
    analyst: str,
    claims: dict[str, list[str]],
) -> dict[str, list[dict[str, str]]]:
    """Render every bucket for one analyst, in the module's canonical order."""
    return {
        EVIDENCE_KEYS[kind]: _evidence(symbol, analyst, claims.get(kind) or [], kind)
        for kind in EVIDENCE_BUCKETS
    }


# =============================================================================
# Technical view
# =============================================================================


def _technical_stance(findings: list[dict[str, Any]]) -> tuple[str | None, str]:
    """Derive a directional stance from the findings' own ``action_bias``.

    The technical prompt does not ask for a stance, so this is confidence-
    weighted arithmetic over the biases it does ask for, and it says so.  A
    report with findings but no usable bias yields ``None`` — not ``MIXED``,
    which would claim the analyst weighed both sides.
    """
    net = 0.0
    total = 0.0
    for finding in findings:
        bias = str(finding.get("action_bias", "")).upper()
        weight = _opt_float(finding.get("confidence")) or 0.5
        if bias in _BULLISH_BIAS:
            net += weight
            total += weight
        elif bias in _BEARISH_BIAS:
            net -= weight
            total += weight
        elif bias in {"HOLD", "NEUTRAL"}:
            total += weight
    if total <= 0:
        return None, "no finding carried a directional action_bias"
    ratio = net / total
    basis = (
        f"derived from {len(findings)} finding(s), confidence-weighted "
        f"action_bias net {ratio:+.2f}"
    )
    if ratio >= 0.34:
        return "FAVORABLE", basis
    if ratio <= -0.34:
        return "UNFAVORABLE", basis
    return "MIXED", basis


def _finding_direction(finding: dict[str, Any]) -> str:
    """Which bucket a finding belongs in, read from its own ``action_bias``.

    ``BUY``/``SELL`` are directional claims; ``HOLD``/``NEUTRAL``, and any
    finding that states no bias at all, are neither for nor against and go to
    ``neutral_or_mixed``.  Nothing here consults the report's derived stance.
    """
    bias = str(finding.get("action_bias", "")).upper()
    if bias in _BULLISH_BIAS:
        return "bullish"
    if bias in _BEARISH_BIAS:
        return "bearish"
    return "neutral_or_mixed"


def _finding_claim(finding: dict[str, Any]) -> str:
    """One technical finding as a single citable claim."""
    signal = _opt_str(finding.get("signal")) or "finding"
    timeframe = _opt_str(finding.get("timeframe"))
    confidence = _opt_float(finding.get("confidence"))
    description = _opt_str(finding.get("description")) or ""
    head = signal
    qualifiers = [q for q in (timeframe, f"{confidence:.0%}" if confidence is not None else None) if q]
    if qualifiers:
        head = f"{signal} ({', '.join(qualifiers)})"
    levels = finding.get("key_levels") or {}
    tail_parts = []
    if isinstance(levels, dict):
        support = _opt_float(levels.get("support"))
        resistance = _opt_float(levels.get("resistance"))
        if support is not None:
            tail_parts.append(f"support ${support:g}")
        if resistance is not None:
            tail_parts.append(f"resistance ${resistance:g}")
    target = _opt_float(finding.get("price_target"))
    if target is not None:
        tail_parts.append(f"target ${target:g}")
    tail = f" [{', '.join(tail_parts)}]" if tail_parts else ""
    return f"{head}: {description}{tail}".strip()


def build_technical_view(symbol: str, raw: Any) -> dict[str, Any]:
    """Build the technical analyst's panel entry for one symbol."""
    status, error = _report_status(raw)
    if status != "ok":
        return {"status": status, "error": error, "decision": None, "details": {}}

    report = clean_report(raw) or {}
    findings = [f for f in (report.get("findings") or []) if isinstance(f, dict)]
    stance, basis = _technical_stance(findings)

    # Bucket by each finding's own action_bias.  The previous rule was
    # "aligned with the stance we derived / not aligned with it", with
    # ``bullish_first = stance != "UNFAVORABLE"`` silently making bullish the
    # default side for a MIXED report.  That filed HOLD/NEUTRAL findings as
    # "evidence against" a stance their own text did not oppose.
    bucketed: dict[str, list[dict[str, Any]]] = {
        "bullish": [],
        "bearish": [],
        "neutral_or_mixed": [],
    }
    for finding in findings:
        bucketed[_finding_direction(finding)].append(finding)

    kept = {kind: items[:MAX_TECHNICAL_FINDINGS] for kind, items in bucketed.items()}
    shown = sum(len(items) for items in kept.values())

    claims = {kind: [_finding_claim(f) for f in items] for kind, items in kept.items()}
    # Every conflicting signal survives, under the analyst's own field name:
    # they are its statement of what argues against its read, and they are cheap.
    claims["conflicting"] = [
        text for text in (_opt_str(c) for c in (report.get("conflicting_signals") or [])) if text
    ]

    invalidation = []
    for finding in findings:
        stop = _opt_float(finding.get("stop_loss"))
        if stop is not None:
            signal = _opt_str(finding.get("signal")) or "setup"
            line = f"Close below ${stop:g} invalidates the {signal} setup"
            if line not in invalidation:
                invalidation.append(line)

    return {
        "status": "ok",
        "error": None,
        "decision": {
            "stance": stance,
            "stance_basis": basis,
            "confidence": _opt_float(report.get("confidence")),
            "thesis": _opt_str(report.get("market_structure")),
            **_buckets(symbol, "technical", claims),
            "invalidation": invalidation,
        },
        "details": {
            "key_observations": [
                o for o in (_opt_str(x) for x in (report.get("key_observations") or [])) if o
            ][:MAX_DETAIL_OBSERVATIONS],
            "timeframes_analyzed": [
                t for t in (_opt_str(x) for x in (report.get("timeframes_analyzed") or [])) if t
            ],
            "findings_shown": shown,
            "findings_total": len(findings),
            "truncated": shown < len(findings),
        },
    }


# =============================================================================
# Sector view
# =============================================================================


def _sector_stance(report: dict[str, Any], symbol: str) -> tuple[str | None, str]:
    """Derive a target view from a market-wide sector answer.

    ``SECTOR_STRATEGIST_PROMPT`` asks for a sector table and never asks whether
    the named stock benefits from it, so there is no stance to read.  The only
    honest derivation is the action on a recommendation that actually names the
    target; when none does, the stance is ``None`` and the basis says why.
    """
    for rec in report.get("recommendations") or []:
        if not isinstance(rec, dict):
            continue
        if not (_mentions(rec.get("rationale"), symbol) or _mentions(rec.get("sector"), symbol)):
            continue
        action = str(rec.get("action", "")).upper()
        sector = _opt_str(rec.get("sector")) or "the target's sector"
        basis = f"derived from the {sector} recommendation, which names {symbol}"
        if action.startswith("OVER"):
            return "FAVORABLE", basis
        if action.startswith("UNDER"):
            return "UNFAVORABLE", basis
        if action:
            return "MIXED", basis
    return None, (
        f"the sector strategist's output contract is market-wide and never names "
        f"{symbol}; read its table under the market-wide block, not as a vote on {symbol}"
    )


def build_sector_view(symbol: str, raw: Any) -> dict[str, Any]:
    """Build the sector strategist's panel entry for one symbol."""
    status, error = _report_status(raw)
    if status != "ok":
        return {"status": status, "error": error, "decision": None, "details": {}}

    report = clean_report(raw) or {}
    stance, basis = _sector_stance(report, symbol)

    # A rotation signal or an observation that merely names the target states no
    # direction on it, so it is neither for nor against: it goes to
    # neutral_or_mixed rather than being printed under a "for" heading.  A
    # recommendation is filed by its own action word.
    claims: dict[str, list[str]] = {"bullish": [], "bearish": [], "neutral_or_mixed": []}
    for signal in report.get("rotation_signals") or []:
        text = _opt_str(signal)
        if text and _mentions(text, symbol):
            claims["neutral_or_mixed"].append(f"rotation: {text}")
    for observation in report.get("key_observations") or []:
        text = _opt_str(observation)
        if text and _mentions(text, symbol):
            claims["neutral_or_mixed"].append(text)
    for rec in report.get("recommendations") or []:
        if isinstance(rec, dict) and _mentions(rec.get("rationale"), symbol):
            sector = _opt_str(rec.get("sector")) or "sector"
            action = _opt_str(rec.get("action")) or "NEUTRAL"
            upper = action.upper()
            kind = (
                "bullish" if upper.startswith("OVER")
                else "bearish" if upper.startswith("UNDER")
                else "neutral_or_mixed"
            )
            claims[kind].append(f"{sector} {action}: {rec.get('rationale')}")
    target_mentions = sum(len(items) for items in claims.values())
    claims = {kind: items[:MAX_EVIDENCE_ITEMS] for kind, items in claims.items()}

    phase = _opt_str(report.get("market_phase"))
    phase_confidence = _opt_float(report.get("phase_confidence"))

    return {
        "status": "ok",
        "error": None,
        "decision": {
            "stance": stance,
            "stance_basis": basis,
            "confidence": _opt_float(report.get("confidence")),
            # The market phase *is* this analyst's thesis; absent stays absent
            # rather than becoming "Unknown (0% confidence)".
            "thesis": (
                f"market phase {phase}"
                + (f" at {phase_confidence:.0%} confidence" if phase_confidence is not None else "")
            )
            if phase
            else None,
            **_buckets(symbol, "sector", claims),
            "invalidation": [],
        },
        "details": {
            "market_phase": phase,
            "phase_confidence": phase_confidence,
            "rankings_reported": len(report.get("sector_rankings") or []),
            "recommendations_reported": len(report.get("recommendations") or []),
            "target_mentions": target_mentions,
            # The sector contract has no for/against field at all, so an empty
            # bearish bucket here is "never asked", not "nothing found".
            "directional_evidence_elicited": False,
        },
    }


# =============================================================================
# Risk view
# =============================================================================


def _risk_stance(assessment: dict[str, Any]) -> tuple[str | None, str]:
    """Derive ``PASS``/``CAUTION`` from the normalised reward/risk ratio.

    Risk is not a directional voter, so it gets its own vocabulary.  ``BLOCK``
    is deliberately never derived here: a veto has to rest on a predicate the
    engine can verify (stale price, invalid geometry, a portfolio constraint),
    and a free-text risk narrative from the same model is not that.
    """
    ratio = assessment.get("risk_reward")
    note = _opt_str(assessment.get("risk_reward_note")) or ""
    if ratio is None:
        if note:
            return "CAUTION", "no reward/risk ratio reported; assessment text only"
        return None, "the risk analyst reported no reward/risk ratio for this symbol"
    basis = f"derived from reward/risk {ratio:.2f}"
    if "unfavorable" in note.lower() or "not compelling" in note.lower():
        return "CAUTION", basis + "; the analyst's own assessment reads unfavourable"
    if ratio >= 1.5:
        return "PASS", basis
    return "CAUTION", basis


def _select_assessment(assessments: list[dict[str, Any]], symbol: str) -> dict[str, Any] | None:
    """The assessment for this symbol, or the sole one if it is unlabelled."""
    for assessment in assessments:
        if assessment.get("symbol") == symbol:
            return assessment
    if len(assessments) == 1:
        return assessments[0]
    return None


def build_risk_view(symbol: str, raw: Any) -> dict[str, Any]:
    """Build the risk analyst's panel entry for one symbol.

    The raw report goes through ``normalize_risk_report`` first: the model's
    real output nests the documented scalars (and nests them differently for
    different symbols in the same run), which is why the old rendering showed
    ``Max Drawdown: 0.0%, R/R: 0.0x, Stop: $0.00`` for every symbol.
    """
    status, error = _report_status(raw)
    if status != "ok":
        return {"status": status, "error": error, "decision": None, "details": {}}

    report = clean_report(raw) or {}
    normalized = normalize_risk_report(report)
    assessment = _select_assessment(normalized.get("risk_assessments") or [], symbol) or {}
    stance, basis = _risk_stance(assessment)

    bullish_claims: list[str] = []
    ratio = assessment.get("risk_reward")
    if ratio is not None and ratio >= 1.5:
        bullish_claims.append(
            f"reward/risk {ratio:.2f} to the analyst's own upside target"
            + (f" -- {assessment['risk_reward_note']}" if assessment.get("risk_reward_note") else "")
        )

    counter_claims: list[str] = []
    for scenario in (assessment.get("downside_scenarios") or [])[:MAX_COUNTER_EVIDENCE_ITEMS]:
        name = _opt_str(scenario.get("name")) or "downside scenario"
        drawdown = scenario.get("drawdown_pct")
        target = scenario.get("target")
        probability = scenario.get("probability")
        bits = []
        if target is not None:
            bits.append(f"to ${target:g}")
        if drawdown is not None:
            bits.append(f"-{drawdown:g}%")
        if probability is not None:
            bits.append(f"p={probability:.0%}")
        note = _opt_str(scenario.get("note"))
        claim = f"{name} ({', '.join(bits)})" if bits else name
        counter_claims.append(f"{claim}: {note}" if note else claim)
    for tail in normalized.get("tail_risks") or []:
        event = _opt_str(tail.get("event"))
        if not event:
            continue
        probability = tail.get("probability")
        impact = _opt_str(tail.get("impact"))
        suffix = ", ".join(
            bit
            for bit in (
                f"p={probability:.0%}" if probability is not None else None,
                f"{impact} impact" if impact else None,
            )
            if bit
        )
        counter_claims.append(f"tail risk -- {event}" + (f" ({suffix})" if suffix else ""))
    counter_claims += [
        text for text in (_opt_str(r) for r in normalized.get("portfolio_risks") or []) if text
    ]

    vol_regime = normalized.get("volatility_regime") or {}

    return {
        "status": "ok",
        "error": None,
        "decision": {
            "stance": stance,
            "stance_basis": basis,
            "confidence": normalized.get("confidence"),
            "thesis": _opt_str(assessment.get("risk_reward_note")),
            # Downside scenarios, tail risks and portfolio risks are bearish
            # claims in their own right -- not "against" some derived stance.
            **_buckets(
                symbol,
                "risk",
                {
                    "bullish": bullish_claims,
                    "bearish": counter_claims[: MAX_COUNTER_EVIDENCE_ITEMS + 3],
                },
            ),
            "invalidation": list(assessment.get("invalidation") or []),
        },
        "details": {
            "current_price": assessment.get("current_price"),
            "max_drawdown_pct": assessment.get("max_drawdown_pct"),
            "risk_reward": assessment.get("risk_reward"),
            "var_95_daily_pct": assessment.get("var_95_daily_pct"),
            "stop_loss": assessment.get("stop_loss"),
            "stop_loss_tier": assessment.get("stop_loss_tier"),
            "position_size": assessment.get("position_size"),
            "volatility": assessment.get("volatility"),
            "vix": vol_regime.get("current_vix"),
            "volatility_regime": _opt_str(vol_regime.get("regime")),
            "key_observations": (normalized.get("key_observations") or [])[:MAX_DETAIL_OBSERVATIONS],
            "unmapped_fields": assessment.get("unmapped_fields") or [],
        },
    }


_VIEW_BUILDERS = {
    "technical": build_technical_view,
    "sector": build_sector_view,
    "risk": build_risk_view,
}


# =============================================================================
# Market-wide sector block
# =============================================================================


def _median(values: list[float]) -> float | None:
    """Median of what was actually reported, or ``None`` if nothing was."""
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _rank_disagreement(values: list[float]) -> bool:
    """Did the analysts report materially different numbers for this sector?"""
    if len(values) < 2:
        return False
    return (max(values) - min(values)) > 1e-9


def build_market_wide_sector(analyst_reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Collapse the near-identical per-symbol sector answers into one block.

    ``format_sector_context`` deliberately keeps sector ETF performance,
    rankings and rotation shared across symbols, so a five-symbol run produces
    five sector reports carrying the same eleven-row table.  Rendering that
    table five times would spend the per-symbol budget on duplication; dropping
    it (what the old flatten did) discarded 55 rankings and 27 recommendations
    per run.

    Hoisting it once is right; the first version's *merge* was not.  It kept
    whichever report had the longest ranking list -- effectively the first, all
    lengths being equal -- and rendered one number with no provenance.  The five
    real 2026-08-18 reports did not agree: Energy relative strength was 1.35
    (AMD), 1.165 (DVN), 4.59 (CL=F), 1.47 (AVGO) and 1.165 (NU).  Presenting one
    of those as *the* table converts stochastic disagreement into an apparent
    shared observation, which is exactly the summary the panel exists to remove,
    and the 4.59 outlier shows the spread is not noise-level.

    So each sector now carries the median, the range, the trend words and the
    symbols whose run reported them, and each recommendation carries
    ``reported_by`` instead of first-rationale-wins.  Where the analysts
    disagree, the block says so in band.
    """
    phases: dict[tuple[str | None, float | None], list[str]] = {}
    # sector -> [{symbol, relative_strength, trend}]
    ranking_reports: dict[str, list[dict[str, Any]]] = {}
    # (sector, action) -> {"reported_by": [...], "rationales": [(symbol, text)]}
    rec_reports: dict[tuple[str, str], dict[str, Any]] = {}
    rotation: list[str] = []
    reporting = 0

    for symbol, reports in analyst_reports.items():
        report = clean_report((reports or {}).get("sector")) if isinstance(reports, dict) else None
        if not report:
            continue
        reporting += 1
        key = (_opt_str(report.get("market_phase")), _opt_float(report.get("phase_confidence")))
        phases.setdefault(key, []).append(symbol)

        for ranking in report.get("sector_rankings") or []:
            if not isinstance(ranking, dict):
                continue
            sector = _opt_str(ranking.get("sector"))
            if not sector:
                continue
            ranking_reports.setdefault(sector, []).append(
                {
                    "symbol": symbol,
                    "relative_strength": _opt_float(ranking.get("relative_strength")),
                    "trend": _opt_str(ranking.get("trend")),
                }
            )
        for rec in report.get("recommendations") or []:
            if not isinstance(rec, dict):
                continue
            sector = _opt_str(rec.get("sector")) or "unnamed sector"
            action = _opt_str(rec.get("action")) or "NOT STATED"
            entry = rec_reports.setdefault(
                (sector, action), {"reported_by": [], "rationales": []}
            )
            if symbol not in entry["reported_by"]:
                entry["reported_by"].append(symbol)
            rationale = _opt_str(rec.get("rationale"))
            if rationale:
                entry["rationales"].append((symbol, rationale))
        for signal in report.get("rotation_signals") or []:
            text = _opt_str(signal)
            # Symbol-specific signals live in that symbol's own block.
            if text and text not in rotation and not any(
                _mentions(text, sym) for sym in analyst_reports
            ):
                rotation.append(text)

    rankings: list[dict[str, Any]] = []
    for sector, entries in ranking_reports.items():
        strengths = [e["relative_strength"] for e in entries if e["relative_strength"] is not None]
        trends: dict[str, list[str]] = {}
        for entry in entries:
            if entry["trend"]:
                trends.setdefault(entry["trend"], []).append(entry["symbol"])
        rankings.append(
            {
                "sector": sector,
                "relative_strength_median": _median(strengths),
                "relative_strength_min": min(strengths) if strengths else None,
                "relative_strength_max": max(strengths) if strengths else None,
                "reported_by": [e["symbol"] for e in entries],
                "reporting_count": len(entries),
                "disagreement": _rank_disagreement(strengths),
                "trends": [
                    {"trend": trend, "reported_by": symbols} for trend, symbols in trends.items()
                ],
                "values": entries,
            }
        )
    # Highest median relative strength first; a sector nobody put a number on
    # sorts last rather than being read as zero.
    rankings.sort(
        key=lambda r: (r["relative_strength_median"] is not None, r["relative_strength_median"] or 0.0),
        reverse=True,
    )
    ranked = [r for r in rankings if r["relative_strength_median"] is not None]

    # Group recommendations by sector so a split vote is visible as a split.
    grouped: dict[str, list[dict[str, Any]]] = {}
    for (sector, action), entry in rec_reports.items():
        grouped.setdefault(sector, []).append(
            {
                "action": action,
                "reported_by": entry["reported_by"],
                "rationale": entry["rationales"][0][1] if entry["rationales"] else None,
                "rationale_reported_by": entry["rationales"][0][0] if entry["rationales"] else None,
                "rationales_reported": len(entry["rationales"]),
            }
        )
    recommendations: list[dict[str, Any]] = []
    for sector, actions in grouped.items():
        actions.sort(key=lambda a: len(a["reported_by"]), reverse=True)
        recommendations.append(
            {
                "sector": sector,
                "actions": actions,
                "reporting_count": sum(len(a["reported_by"]) for a in actions),
                "disagreement": len(actions) > 1,
            }
        )
    recommendations.sort(key=lambda r: (not r["disagreement"], -r["reporting_count"]))

    return {
        "reporting_runs": reporting,
        "total_runs": len(analyst_reports),
        "market_phases": [
            {"phase": phase, "phase_confidence": confidence, "reported_by": sorted(symbols)}
            for (phase, confidence), symbols in phases.items()
        ],
        "sector_rankings": rankings,
        "top_sectors": [
            {"sector": r["sector"], "relative_strength_median": r["relative_strength_median"]}
            for r in ranked[:3]
        ],
        # Never the same rows as ``top_sectors``: a three-sector table has no
        # bottom, and saying it does would invent a spread.
        "bottom_sectors": [
            {"sector": r["sector"], "relative_strength_median": r["relative_strength_median"]}
            for r in ranked[max(3, len(ranked) - 3) :]
        ],
        "recommendations": recommendations,
        "recommendation_disagreements": [r["sector"] for r in recommendations if r["disagreement"]],
        "rotation_signals": rotation,
    }


# =============================================================================
# Panel
# =============================================================================


def build_symbol_panel(
    analyst_reports: dict[str, dict[str, Any]],
    run_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the per-symbol synthesis panel from the raw analyst reports.

    Args:
        analyst_reports: ``{symbol: {analyst: report}}`` straight out of
            ``_run_analysts_for_symbol``.  Not mutated (unlike the flatten it
            replaces, which wrote ``_symbol`` into the caller's finding dicts
            and thereby into the database).
        run_context: Optional run-level facts (as-of date, pipeline, horizon).

    Returns:
        A panel dict.  Every symbol that produced any analyst entry appears,
        every analyst appears for every symbol with an explicit status, and no
        cap spans symbols.
    """
    symbols: list[dict[str, Any]] = []
    for symbol, reports in analyst_reports.items():
        reports = reports if isinstance(reports, dict) else {}
        views: dict[str, Any] = {}
        for analyst in PANEL_ANALYSTS:
            if analyst not in reports and analyst not in _VIEW_BUILDERS:
                continue
            builder = _VIEW_BUILDERS[analyst]
            views[analyst] = builder(symbol, reports.get(analyst))
        # An analyst outside the standard three (a roster change) still shows up
        # with its status rather than vanishing from the panel.
        for analyst, report in reports.items():
            if analyst in views:
                continue
            status, error = _report_status(report)
            views[analyst] = {"status": status, "error": error, "decision": None, "details": {}}
        symbols.append({"symbol": symbol, "reports": views})

    return {
        "schema_version": PANEL_SCHEMA_VERSION,
        "run_context": dict(run_context or {}),
        "market_wide": {"sector": build_market_wide_sector(analyst_reports)},
        "symbols": symbols,
    }
