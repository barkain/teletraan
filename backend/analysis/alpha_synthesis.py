"""LLM synthesis and outcome seeding for the alpha engine.

Phase 4: explain ranked candidates rather than scoring them.
Phase 5: seed outcome tracking from the synthesized outputs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime
from typing import Any

from sqlalchemy import update as _sa_update

from llm.client_pool import pool_query_llm
from models.alpha_engine import CandidateIdea
from models.deep_insight import DeepInsight, InsightAction, InsightType
from analysis.outcome_tracker import InsightOutcomeTracker

logger = logging.getLogger(__name__)

ALPHA_SYNTHESIS_SYSTEM_PROMPT = """You are the Teletraan alpha synthesis lead.
Your job is to explain already-ranked candidates, not to invent the ranking.

Rules:
- Do not rescore or reorder the candidates.
- Explain why each candidate matters now using the supplied evidence.
- Separate market-wide ideas from portfolio-aware suggestions.
- Keep the output concise, concrete, and tradeable.
- If evidence is weak, say so plainly.
- For upside_pct: derive your own estimate from the thesis narrative — do NOT use analyst
  consensus targets. Reason from the hypothesis: TAM expansion, revenue growth trajectory,
  margin improvement, moat strengthening, or catalyst crystallisation. Be intellectually
  honest — if the thesis is weak, say so with a low upside_pct and low confidence.

Return valid JSON with keys:
- summary: short paragraph
- candidate_notes: array of {
    symbol,
    title,
    thesis,
    action,
    confidence,
    horizon_days,
    risk_factors,
    invalidation_trigger,
    upside_pct: your estimated % upside over the horizon derived from the thesis (float, not analyst targets),
    upside_rationale: one sentence explaining how you derived the upside estimate
  }
- portfolio_notes: array of strings
- data_gaps: array of strings
"""


def _action_for_candidate(candidate: Any) -> str:
    score = float(getattr(candidate, "overall_score", 0.0) or 0.0)
    if getattr(candidate, "is_portfolio_holding", False):
        if score >= 70:
            return InsightAction.BUY.value
        if score <= 50:
            return InsightAction.SELL.value
        return InsightAction.HOLD.value
    if score >= 75:
        return InsightAction.STRONG_BUY.value
    if score >= 60:
        return InsightAction.BUY.value
    if score <= 40:
        return InsightAction.WATCH.value
    return InsightAction.HOLD.value


def _time_horizon_label(days: int | None) -> str:
    if days is None:
        return "unknown"
    if days <= 21:
        return "short-term"
    if days <= 60:
        return "swing"
    if days <= 120:
        return "position"
    return "long-term"


def build_alpha_candidate_context(
    candidates: list[Any],
    portfolio_overlay: dict[str, Any],
    regime: Any,
    market_snapshot: dict[str, Any] | None = None,
) -> str:
    """Build a compact markdown block for the alpha explainer LLM."""
    lines: list[str] = [
        "## Alpha Candidate Ranking",
        f"Regime: {getattr(regime, 'name', 'unknown')} (confidence {getattr(regime, 'confidence', 0.0):.2f})",
        "",
    ]

    if market_snapshot:
        lines.append("### Market Snapshot")
        for key, value in market_snapshot.items():
            if isinstance(value, dict):
                continue
            lines.append(f"- {key}: {value}")
        lines.append("")

    lines.append("### Ranked Candidates")
    for candidate in candidates[:10]:
        # Extract current price from setup_trigger ("Close 123.45")
        price_str = ""
        if getattr(candidate, "setup_trigger", "") and str(candidate.setup_trigger).startswith("Close "):
            price_str = f" | current_price=${candidate.setup_trigger.replace('Close ', '')}"
        lines.append(
            f"- #{candidate.rank} {candidate.symbol} | score {candidate.overall_score:.2f} | "
            f"confidence {candidate.confidence:.2f} | thesis {candidate.thesis_type} | "
            f"holding={candidate.is_portfolio_holding}{price_str}"
        )
        # Strip analyst target from bull_case so LLM forms its own view
        bull = str(getattr(candidate, "bull_case", "") or "")
        bull_clean = bull.split(" Street upside")[0].strip()
        lines.append(f"  - Scores: {bull_clean}")
        lines.append(f"  - Risk: {candidate.bear_case}")
        if candidate.portfolio_relevance:
            lines.append(f"  - Portfolio: {candidate.portfolio_relevance}")
        if candidate.key_drivers:
            lines.append(f"  - Drivers: {', '.join(candidate.key_drivers)}")

    lines.append("")
    lines.append("### Portfolio Overlay")
    lines.append(f"- Concentration risk: {portfolio_overlay.get('concentration_risk', 'unknown')}")
    top_sector = portfolio_overlay.get("top_sector", {}) or {}
    if top_sector:
        lines.append(f"- Top sector: {top_sector.get('sector')} ({top_sector.get('weight', 0):.2%})")
    suggestions = portfolio_overlay.get("suggestions", []) or []
    for suggestion in suggestions[:10]:
        lines.append(
            f"- {suggestion.get('symbol')}: {suggestion.get('action')} "
            f"(score {suggestion.get('score')}, confidence {suggestion.get('confidence')})"
        )
        if suggestion.get("reason"):
            lines.append(f"  - Reason: {suggestion['reason']}")

    return "\n".join(lines)


async def synthesize_alpha_run(
    db,
    *,
    run,
    candidates: list[Any],
    portfolio_overlay: dict[str, Any],
    regime: Any,
    market_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Explain the ranked candidates and seed tracking records."""
    if not candidates:
        return {"summary": "No candidates", "deep_insights": [], "tracked": 0}

    user_prompt = build_alpha_candidate_context(
        candidates=candidates,
        portfolio_overlay=portfolio_overlay,
        regime=regime,
        market_snapshot=market_snapshot,
    )

    llm_response: dict[str, Any] | None = None
    try:
        result = await pool_query_llm(
            ALPHA_SYNTHESIS_SYSTEM_PROMPT,
            user_prompt,
            "alpha_synthesis",
        )
        raw = (result.text or "").strip()
        if raw:
            try:
                llm_response = json.loads(raw)
            except Exception:
                llm_response = {
                    "summary": raw[:1000],
                    "candidate_notes": [],
                    "portfolio_notes": [],
                    "data_gaps": [],
                }
    except Exception as exc:
        logger.warning("Alpha synthesis LLM failed, falling back to deterministic summary: %s", exc)

    if llm_response is None:
        llm_response = {
            "summary": "Ranked candidate explanations generated deterministically.",
            "candidate_notes": [],
            "portfolio_notes": [],
            "data_gaps": [],
        }

    candidate_notes = {item.get("symbol"): item for item in llm_response.get("candidate_notes", []) if isinstance(item, dict)}
    tracked = 0
    deep_insights: list[DeepInsight] = []
    outcome_tracker = InsightOutcomeTracker(db)

    for candidate in candidates[:5]:
        note = candidate_notes.get(candidate.symbol, {})
        action = str(note.get("action") or _action_for_candidate(candidate)).upper()
        if action not in {a.value for a in InsightAction}:
            action = _action_for_candidate(candidate)

        thesis = note.get("thesis") or candidate.bull_case
        title = note.get("title") or f"{candidate.symbol} {candidate.thesis_type.replace('_', ' ').title()}"
        risk_factors = note.get("risk_factors") or candidate.invalidations
        invalidation = note.get("invalidation_trigger") or candidate.setup_trigger
        horizon_days = int(note.get("horizon_days") or candidate.expected_horizon_days or 45)

        # Write LLM-derived upside back to CandidateIdea (replacing analyst target)
        upside_pct = note.get("upside_pct")
        upside_rationale = note.get("upside_rationale", "")
        if upside_pct is not None and thesis:
            llm_bull = thesis
            if upside_rationale:
                llm_bull += f" | Upside estimate: +{float(upside_pct):.0f}% — {upside_rationale}"
            try:
                await db.execute(
                    _sa_update(CandidateIdea)
                    .where(
                        CandidateIdea.analysis_run_id == run.id,
                        CandidateIdea.symbol == candidate.symbol,
                    )
                    .values(bull_case=llm_bull)
                )
            except Exception as exc:
                logger.warning("Failed to update CandidateIdea bull_case for %s: %s", candidate.symbol, exc)

        deep_insight = DeepInsight(
            insight_type=InsightType.OPPORTUNITY.value,
            action=action,
            title=title[:200],
            thesis=thesis,
            primary_symbol=candidate.symbol,
            related_symbols=[],
            secondary_plays=candidate.portfolio_relevance or None,
            supporting_evidence=[
                {
                    "source": "alpha_engine",
                    "overall_score": candidate.overall_score,
                    "confidence": candidate.confidence,
                    "subscores": candidate.subscores,
                    "portfolio_holding": candidate.is_portfolio_holding,
                    "expected_horizon_days": candidate.expected_horizon_days,
                }
            ],
            confidence=float(candidate.confidence),
            time_horizon=_time_horizon_label(horizon_days),
            risk_factors=risk_factors,
            invalidation_trigger=invalidation,
            historical_precedent=None,
            analysts_involved=["alpha_engine"],
            data_sources=["alpha_engine", "fundamentals", "options_flow", "short_interest", "analyst_revisions"],
            entry_zone=candidate.setup_trigger,
            target_price=f"{candidate.target_price:.2f}" if candidate.target_price is not None else None,
            stop_loss=f"{candidate.stop_price:.2f}" if candidate.stop_price is not None else None,
            timeframe=_time_horizon_label(horizon_days),
            discovery_context={
                "analysis_run_id": run.id,
                "market_regime": getattr(regime, "name", None),
                "market_confidence": getattr(regime, "confidence", None),
                "portfolio_overlay": portfolio_overlay,
            },
            technical_analysis_data={"subscores": candidate.subscores},
            prediction_market_data={"boost": candidate.evidence.get("prediction_boost") if candidate.evidence else None},
            sentiment_data=candidate.evidence.get("sentiment") if candidate.evidence else None,
            lifecycle_state="active",
            last_evaluated_at=datetime.utcnow(),
            staleness_score=0.0,
            conviction_decay_factor=1.0,
            effective_confidence=candidate.confidence,
        )
        db.add(deep_insight)
        await db.flush()
        deep_insights.append(deep_insight)

        predicted_direction = "bullish" if action in {InsightAction.BUY.value, InsightAction.STRONG_BUY.value} else "bearish" if action in {InsightAction.SELL.value, InsightAction.STRONG_SELL.value} else "neutral"
        if predicted_direction != "neutral":
            await outcome_tracker.start_tracking(
                insight_id=deep_insight.id,  # type: ignore[arg-type]
                symbol=candidate.symbol,
                predicted_direction=predicted_direction,
                tracking_days=candidate.expected_horizon_days or 20,
            )
            tracked += 1

    llm_response["deep_insights_seeded"] = len(deep_insights)
    llm_response["tracked"] = tracked
    llm_response["generated_at"] = datetime.utcnow().isoformat()
    return llm_response
