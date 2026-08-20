"""Replay the synthesis lead on stored evidence: old representation vs new panel.

Commit ``e7e6d36`` replaced the run-global ``_flatten_analyst_reports`` with a
per-symbol evidence panel (:mod:`analysis.agent_panel`).  Nobody knows whether
that produces better *decisions*.  Waiting for live outcomes takes about a year,
because 20-30 day calls issued daily overlap almost completely.

The evidence, though, is already on disk.  ``insight_research_contexts`` stores
the real technical, sector and risk reports behind each ``DeepInsight``, and the
outcomes are graded.  So synthesis can be replayed on identical evidence -- old
representation against new panel -- without rerunning a single analyst.

    ARM A (``old_flatten``)   the vendored pre-``e7e6d36`` flatten, rendered
                              through the then-current (and still current, byte
                              for byte) ``format_synthesis_context``.
    ARM B (``symbol_panel``)  the live ``build_symbol_panel`` rendered through
                              the live ``format_symbol_panel_context``.

Both arms are handed the *same* stored reports, the same system prompt
(``SYNTHESIS_LEAD_PROMPT``, unmodified), and the same task block.  One symbol
per call; batching would let one arm's answer for symbol X be shaped by symbol
Y and the arms would stop being comparable.

==============================================================================
WHAT THIS MEASURES, AND WHAT IT DOES NOT
==============================================================================

1.  **The model knows 2026.**  These calls are dated 2026-02-23 to 2026-06-24
    and the model's training data may contain what actually happened to these
    symbols.  That is look-ahead *through the weights* and no amount of
    engineering removes it.  The as-of instruction in the task block asks the
    model not to use it; nothing verifies that it complied.  So this measures
    whether synthesis **reasons better on identical evidence**.  It does not
    measure market edge, and no number it produces is a forecast of live
    performance.

2.  **It cannot test the de-anchoring shipped in ``a12cf0b``.**  Every stored
    report was produced by an analyst that had already been primed with the
    shared ``discovery_context`` prefix.  Blinding changes what the analysts
    *write*; replay only changes how what they wrote is *shown*.  Nothing
    retro-fits a blinded analyst onto a primed report.

3.  **The stored reports are basket-wide, not per-symbol.**  This is the
    biggest limitation and it was discovered while building the harness, not
    designed in.  Of the 88 gradeable cases, 87 carry a technical report whose
    ``findings`` cover many tickers (11.1 on average, up to 17), because the
    per-symbol analyst era only begins around 2026-06-24 -- after the last
    gradeable call.  Consequences:

      * ARM A's ``findings[:5]`` truncation is reproduced **faithfully**: the
        stored report already *is* the run-global basket, so the prefix cap
        drops the same evidence it dropped in production.  In 25 of the 78
        cases whose basket contains a finding on the target symbol, that
        finding does not survive the cap.

      * ARM B's per-symbol boundary is **not exercised** as it is in
        production.  The panel is handed one symbol key whose reports describe
        many symbols, so its buckets mix tickers and its header's claim that
        "an ID belongs to exactly one symbol" is true of the IDs but not of the
        claims behind them.  The panel's largest production win -- keeping five
        symbols from collapsing into one bucket -- has no room to show up here.

    ``--scope-to-symbol`` filters findings and risk assessments to the target
    **for both arms symmetrically** before either renders, which isolates
    representation from evidence volume.  It is off by default because it is
    not what either arm did in production.

4.  **The effective sample is far below 88.**  18 distinct dates, 43 distinct
    symbols, and one symbol (``GC=F``) appears 9 times.  Calls issued days
    apart on 20-30 trading-day horizons share most of their window, so the
    pairs are not independent draws.  The comparison is therefore paired on
    (symbol, date, evidence) and the uncertainty is estimated by a bootstrap
    that resamples **whole dates**, not individual pairs.

5.  **If the arms agree, that is the finding.**  A high action-agreement rate
    means the representation did not change the decision on this evidence.
    Nothing here is tuned to manufacture a difference.

==============================================================================

Read-only against the database.  Snapshot to ``data/synthesis_replay.json``,
following the ``insight_eval.json`` convention.  Every LLM response is cached to
disk under ``data/synthesis_replay_cache/`` keyed by arm, insight id and prompt
hash, so a re-run costs nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import logging
import random
import re
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from analysis.agent_panel import build_symbol_panel
from analysis.agents.synthesis_lead import (
    SYNTHESIS_LEAD_PROMPT,
    format_symbol_panel_context,
    format_synthesis_context,
    parse_synthesis_response,
)
from analysis.eval_insights import (
    BENCHMARK_SYMBOL,
    _git_sha,
    ENTRY_LAG_TRADING_DAYS,
    DEFAULT_RELIABILITY_BINS,
    EvalRecord,
    Series,
    build_record,
    cohort_metrics,
    decision_rule,
    decision_rule_tag,
    direction_for_action,
    horizon_trading_days,
    load_local_series,
    pipeline_version_for,
)

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"
REPLAY_SNAPSHOT_PATH = _DATA_DIR / "synthesis_replay.json"
CACHE_DIR = _DATA_DIR / "synthesis_replay_cache"

HARNESS_VERSION = "1.0.0"

ARM_OLD = "old_flatten"
ARM_NEW = "symbol_panel"
ARMS = (ARM_OLD, ARM_NEW)

DIRECTIONAL_ACTIONS = ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL")
COMPLETED_STATUS = "COMPLETED"

# Default sample.  196 calls at full size is real money; the full run is opt-in
# behind ``--all`` and the estimate is printed before anything is spent.
DEFAULT_LIMIT = 20
DEFAULT_SEED = 20260819
DEFAULT_CONCURRENCY = 4

# ---------------------------------------------------------------------------
# Cost model
# ---------------------------------------------------------------------------
# Published Sonnet-class rates.
INPUT_USD_PER_MTOK = 3.0
OUTPUT_USD_PER_MTOK = 15.0
# ~4 chars per token is the usual English approximation; only the estimate uses
# it, never a recorded number.
CHARS_PER_TOKEN = 4.0
# One insight, with thesis, evidence and risk factors.  Production synthesis
# emitted 1165-8646 output tokens for 3-5 insights; ~900 for one is the middle
# of that per-insight range, and the first 40 real replay calls came in at
# 942-1427, so this holds.
ESTIMATED_OUTPUT_TOKENS = 900
# The prompt is NOT the whole bill.  ``pool_query_llm`` goes through the bundled
# Claude Code CLI, which prepends its own system prompt and tool definitions to
# every turn.  The first 40 replay calls carried a 3.4k-11.6k char prompt and
# were billed 41.3k-44.3k input tokens; pricing the prompt alone therefore
# under-estimated by 3.75x ($1.33 estimated against $4.99 actually spent).  That
# fixed floor is charged per call whatever the prompt says.
#
# 41306 measured input tokens on a 3390-char prompt gives 41306 - 3390/4 = 40458;
# the same arithmetic across all 40 calls lands in a narrow band, so 40000 is the
# calibrated overhead rather than a guess.  ``estimate_cost`` prefers the cache's
# own recorded costs over this constant whenever the cache holds any.
CLI_OVERHEAD_INPUT_TOKENS = 40_000
# Below this many cached calls for an arm, the cache mean is noise; use the
# calibrated model instead.
MIN_CACHED_FOR_CALIBRATION = 3


# =============================================================================
# HISTORICAL REPRODUCTION -- NOT LIVE CODE
# =============================================================================


def flatten_analyst_reports_historical(
    analyst_reports: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Vendored copy of ``AutonomousDeepEngine._flatten_analyst_reports``.

    **This is a historical reproduction, not live code.**  It was deleted in
    ``e7e6d36`` and exists here only so ARM A can reconstruct what synthesis was
    shown before that commit.  Recovered with::

        git show e7e6d36~1:backend/analysis/autonomous_engine.py

    Two deliberate deviations from the original, both non-behavioural:

    * The original was a bound method; this is a free function.
    * The original mutated the caller's finding and assessment dicts in place
      (``f["_symbol"] = symbol``), which is how ``_symbol`` reached the
      database.  A replay must not let ARM A's rendering contaminate ARM B's
      input, so the input is deep-copied first.  The mutation still happens --
      on the copy -- because the rendered text depends on nothing else.

    Everything else, including the ``(current + report["confidence"]) / 2``
    running average seeded from 0.0 and the missing sector branch, is verbatim.
    Those are the defects being measured; repairing them here would measure
    nothing.
    """
    analyst_reports = copy.deepcopy(analyst_reports)

    # Aggregate reports by analyst type
    aggregated: dict[str, Any] = {
        "technical": {"findings": [], "confidence": 0.0},
        "macro": {"market_implications": [], "confidence": 0.0},
        "sector": {"sector_rankings": [], "confidence": 0.0},
        "risk": {"risk_assessments": [], "confidence": 0.0},
        "correlation": {"divergences": [], "confidence": 0.0},
    }

    for symbol, reports in analyst_reports.items():
        for analyst_name, report in reports.items():
            if analyst_name not in aggregated:
                continue
            if "error" in report:
                continue

            # Merge findings/data
            if analyst_name == "technical":
                findings = report.get("findings", [])
                for f in findings:
                    f["_symbol"] = symbol
                aggregated["technical"]["findings"].extend(findings)
            elif analyst_name == "risk":
                assessments = report.get("risk_assessments", [])
                for a in assessments:
                    a["_symbol"] = symbol
                aggregated["risk"]["risk_assessments"].extend(assessments)

            # Average confidence
            if "confidence" in report:
                current = aggregated[analyst_name].get("confidence", 0.0)
                aggregated[analyst_name]["confidence"] = (
                    current + report["confidence"]
                ) / 2

    return aggregated


# =============================================================================
# Cases
# =============================================================================


@dataclass
class ReplayCase:
    """One gradeable insight with the stored evidence that produced it."""

    insight_id: int
    symbol: str
    created_at: datetime
    time_horizon: str
    stored_action: str
    stored_confidence: float
    pipeline_version: str
    reports: dict[str, dict[str, Any]]

    @property
    def as_of(self) -> str:
        return self.created_at.date().isoformat()

    @property
    def analyst_reports(self) -> dict[str, dict[str, Any]]:
        """The ``{symbol: {analyst: report}}`` shape both arms consume."""
        return {self.symbol: self.reports}


def _scope_reports_to_symbol(
    reports: dict[str, dict[str, Any]], symbol: str
) -> dict[str, dict[str, Any]]:
    """Keep only the rows a basket-wide report states about ``symbol``.

    Applied to **both** arms or neither -- it changes the evidence, not the
    representation, so an asymmetric application would confound the comparison
    it exists to clean up.  A report that names no row for the target keeps its
    rows unchanged rather than being emptied: an empty report is a different
    experiment ("what does synthesis do with nothing") than a scoped one.
    """
    scoped = copy.deepcopy(reports)

    technical = scoped.get("technical")
    if isinstance(technical, dict):
        findings = [
            f for f in (technical.get("findings") or [])
            if isinstance(f, dict) and f.get("symbol") == symbol
        ]
        if findings:
            technical["findings"] = findings

    risk = scoped.get("risk")
    if isinstance(risk, dict):
        assessments = risk.get("risk_assessments")
        if isinstance(assessments, list):
            mine = [
                a for a in assessments
                if isinstance(a, dict) and a.get("symbol") == symbol
            ]
            if mine:
                risk["risk_assessments"] = mine

    return scoped


async def load_replay_cases(
    db: AsyncSession,
    *,
    actions: Sequence[str] = DIRECTIONAL_ACTIONS,
) -> list[ReplayCase]:
    """Load every directional insight that has stored reports and a graded outcome.

    Only SELECTs are issued.  ``InsightResearchContext.deep_insight_id`` is the
    foreign key -- not ``insight_id``, which is what ``insight_outcomes`` uses.

    98 rows satisfy the SQL predicate but only 88 are loadable: ``SELECT ...
    WHERE technical_report IS NOT NULL`` passes rows whose JSON payload is the
    literal ``null`` (36 such rows exist table-wide, 10 of them here), and a
    ``null`` report is no evidence at all.  The gradeable population is 88.
    """
    from models.deep_insight import DeepInsight
    from models.insight_outcome import InsightOutcome
    from models.insight_research_context import InsightResearchContext

    rows = (await db.execute(
        select(
            DeepInsight.id,
            DeepInsight.action,
            DeepInsight.primary_symbol,
            DeepInsight.confidence,
            DeepInsight.time_horizon,
            DeepInsight.created_at,
            DeepInsight.discovery_context,
            InsightResearchContext.technical_report,
            InsightResearchContext.sector_report,
            InsightResearchContext.risk_report,
        )
        .join(
            InsightResearchContext,
            InsightResearchContext.deep_insight_id == DeepInsight.id,
        )
        .join(InsightOutcome, InsightOutcome.insight_id == DeepInsight.id)
        .where(
            DeepInsight.action.in_([a.upper() for a in actions]),
            DeepInsight.primary_symbol.isnot(None),
            InsightResearchContext.technical_report.isnot(None),
            InsightOutcome.tracking_status == COMPLETED_STATUS,
        )
        .order_by(DeepInsight.created_at, DeepInsight.id)
    )).all()

    cases: list[ReplayCase] = []
    seen: set[int] = set()
    for row in rows:
        if row.id in seen:
            continue
        seen.add(row.id)
        symbol = (row.primary_symbol or "").strip().upper()
        if not symbol or row.confidence is None:
            continue
        if horizon_trading_days(row.time_horizon) is None:
            continue
        reports = {
            name: report
            for name, report in (
                ("technical", row.technical_report),
                ("sector", row.sector_report),
                ("risk", row.risk_report),
            )
            if isinstance(report, dict) and report
        }
        if "technical" not in reports:
            continue
        cases.append(ReplayCase(
            insight_id=row.id,
            symbol=symbol,
            created_at=row.created_at,
            time_horizon=row.time_horizon,
            stored_action=(row.action or "").strip().upper(),
            stored_confidence=float(row.confidence),
            pipeline_version=pipeline_version_for(row.created_at, row.discovery_context),
            reports=reports,
        ))
    return cases


def sample_cases(
    cases: Sequence[ReplayCase], limit: int | None, seed: int = DEFAULT_SEED
) -> list[ReplayCase]:
    """Take a date-stratified sample so a small run still spans the period.

    A naive head/tail slice would sample one or two runs; round-robin over dates
    keeps the sample spread across all 18 of them, which is what the clustered
    bootstrap needs to have anything to resample.
    """
    if limit is None or limit >= len(cases):
        return list(cases)

    by_date: dict[str, list[ReplayCase]] = {}
    for case in cases:
        by_date.setdefault(case.as_of, []).append(case)

    # Reproducible shuffling for a research sample -- not a security context.
    rng = random.Random(seed)  # noqa: S311
    for bucket in by_date.values():
        rng.shuffle(bucket)

    picked: list[ReplayCase] = []
    dates = sorted(by_date)
    while len(picked) < limit and any(by_date[d] for d in dates):
        for day in dates:
            if not by_date[day]:
                continue
            picked.append(by_date[day].pop())
            if len(picked) >= limit:
                break
    picked.sort(key=lambda c: (c.created_at, c.insight_id))
    return picked


# =============================================================================
# Prompts
# =============================================================================

# Identical for both arms, byte for byte.  Any asymmetry here would be
# indistinguishable from a representation effect in the result.
REPLAY_TASK_BLOCK = """## REPLAY TASK

You are being asked for ONE recommendation on ONE symbol.

  Target symbol: {symbol}
  As of date:    {as_of}
  Long-only:     yes (SELL means exit or avoid, never establish a short)

Treat today as {as_of}. Reason only from the analyst evidence printed below and
from what was knowable on that date. Do not use knowledge of what happened to
{symbol} after {as_of}.

Return the documented JSON envelope with EXACTLY ONE object in "insights", whose
"primary_symbol" is "{symbol}". Do not recommend any other symbol as the primary
position. Every other field keeps its documented meaning, including "confidence"
(your probability the thesis is validated within its horizon) and "time_horizon".
"""


def render_arm_context(
    arm: str,
    case: ReplayCase,
    *,
    scope_to_symbol: bool = False,
) -> str:
    """Render one arm's view of one case's stored reports."""
    reports = case.reports
    if scope_to_symbol:
        reports = _scope_reports_to_symbol(reports, case.symbol)
    analyst_reports = {case.symbol: reports}

    if arm == ARM_OLD:
        return format_synthesis_context(
            flatten_analyst_reports_historical(analyst_reports)
        )
    if arm == ARM_NEW:
        return format_symbol_panel_context(
            build_symbol_panel(
                analyst_reports,
                run_context={
                    "as_of": case.as_of,
                    "pipeline": "replay",
                    "long_only": True,
                    "symbols_analyzed": case.symbol,
                },
            )
        )
    raise ValueError(f"unknown arm {arm!r}")


def build_prompt(
    arm: str, case: ReplayCase, *, scope_to_symbol: bool = False
) -> tuple[str, str]:
    """``(system_prompt, user_prompt)`` for one arm of one case."""
    context = render_arm_context(arm, case, scope_to_symbol=scope_to_symbol)
    task = REPLAY_TASK_BLOCK.format(symbol=case.symbol, as_of=case.as_of)
    return SYNTHESIS_LEAD_PROMPT, f"{task}\n{context}"


def prompt_hash(system_prompt: str, user_prompt: str) -> str:
    """Content hash of the exact bytes sent, so a prompt edit invalidates the cache."""
    digest = hashlib.sha256()
    digest.update(system_prompt.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(user_prompt.encode("utf-8"))
    return digest.hexdigest()[:16]


# =============================================================================
# Response cache
# =============================================================================


def cache_path(arm: str, insight_id: int, sha: str, cache_dir: Path = CACHE_DIR) -> Path:
    return cache_dir / f"{arm}__{insight_id}__{sha}.json"


def read_cache(
    arm: str, insight_id: int, sha: str, cache_dir: Path = CACHE_DIR
) -> dict[str, Any] | None:
    path = cache_path(arm, insight_id, sha, cache_dir)
    if not path.exists():
        return None
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:  # pragma: no cover -- a corrupt entry re-queries
        logger.warning("Corrupt replay cache entry at %s; ignoring", path)
        return None


def write_cache(
    arm: str,
    insight_id: int,
    sha: str,
    payload: dict[str, Any],
    cache_dir: Path = CACHE_DIR,
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    with open(cache_path(arm, insight_id, sha, cache_dir), "w") as fh:
        json.dump(payload, fh, indent=2)


# =============================================================================
# One arm of one case
# =============================================================================

_EVIDENCE_ID_RE = re.compile(r"[A-Za-z0-9._=\-^]{1,12}:(technical|sector|risk):(bull|bear|mixed|conflict)\d+")


def panel_evidence_ids(panel: dict[str, Any]) -> set[str]:
    """Every citable evidence ID the panel actually issued."""
    ids: set[str] = set()
    for entry in panel.get("symbols") or []:
        for view in (entry.get("reports") or {}).values():
            decision = (view or {}).get("decision") or {}
            for key, value in decision.items():
                if not key.endswith("evidence") and key != "conflicting_signals":
                    continue
                for item in value or []:
                    if isinstance(item, dict) and item.get("id"):
                        ids.add(item["id"])
    return ids


@dataclass
class ArmResult:
    """One arm's answer for one case."""

    arm: str
    insight_id: int
    symbol: str
    prompt_sha: str
    context_chars: int
    from_cache: bool
    parsed: bool = False
    action: str | None = None
    confidence: float | None = None
    time_horizon: str | None = None
    title: str | None = None
    thesis: str | None = None
    primary_symbol: str | None = None
    analysts_cited: list[str] = field(default_factory=list)
    phantom_analysts: list[str] = field(default_factory=list)
    evidence_ids_cited: list[str] = field(default_factory=list)
    evidence_ids_valid: int = 0
    evidence_ids_invalid: int = 0
    insights_returned: int = 0
    off_target: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    error: str | None = None


def parse_arm_response(
    arm: str, case: ReplayCase, response: str, valid_ids: set[str]
) -> dict[str, Any]:
    """Parse one raw response with the live parser and record what it cited."""
    insights = parse_synthesis_response(response)
    out: dict[str, Any] = {
        "parsed": False,
        "insights_returned": len(insights),
        "analysts_cited": [],
        "phantom_analysts": [],
        "evidence_ids_cited": [],
        "evidence_ids_valid": 0,
        "evidence_ids_invalid": 0,
        "off_target": False,
    }
    if not insights:
        return out

    # The task block asks for exactly one insight on the target.  If the model
    # returned several, take the one on the target; that it needed picking is
    # recorded rather than hidden.
    on_target = [i for i in insights if (i.get("primary_symbol") or "").upper() == case.symbol]
    chosen = on_target[0] if on_target else insights[0]
    out["off_target"] = not on_target

    analysts: list[str] = [str(a) for a in (chosen.get("analysts_involved") or [])]
    for item in chosen.get("supporting_evidence") or []:
        if isinstance(item, dict) and item.get("analyst"):
            analysts.append(str(item["analyst"]))

    # Citations are checked against the IDs the panel actually issued, so an
    # invented ID is counted rather than accepted.  ARM A has no IDs to cite;
    # its counts are structurally zero and the snapshot says so.
    cited = sorted({match.group(0) for match in _EVIDENCE_ID_RE.finditer(response)})
    # An analyst the synthesis attributes a finding to that was never in the
    # evidence at all.  ARM A's flatten initialises macro/sector/correlation
    # keys it then never writes, and format_synthesis_context renders every key
    # present -- so a one-analyst run still prints a five-analyst report, with
    # "Market Phase: Unknown (0% confidence)" and "Analyst Confidence: 0%"
    # under headings for analysts that produced nothing.  Whether synthesis
    # then cites them is measurable, and it is measured here.
    supplied = set(case.reports) | {"synthesis"}
    phantom = sorted({a.strip().lower() for a in analysts} - supplied)

    out.update({
        "parsed": True,
        "phantom_analysts": phantom,
        "action": (chosen.get("action") or "").strip().upper() or None,
        "confidence": float(chosen.get("confidence", 0.5)),
        "time_horizon": chosen.get("time_horizon"),
        "title": chosen.get("title"),
        "thesis": chosen.get("thesis"),
        "primary_symbol": (chosen.get("primary_symbol") or "").upper() or None,
        "analysts_cited": sorted(set(analysts)),
        "evidence_ids_cited": cited,
        "evidence_ids_valid": sum(1 for c in cited if c in valid_ids),
        "evidence_ids_invalid": sum(1 for c in cited if c not in valid_ids),
    })
    return out


async def run_arm(
    arm: str,
    case: ReplayCase,
    *,
    allow_llm: bool,
    scope_to_symbol: bool = False,
    cache_dir: Path = CACHE_DIR,
    query: Any = None,
) -> ArmResult:
    """Run (or replay from cache) one arm of one case.

    ``query`` defaults to :func:`llm.client_pool.pool_query_llm`; it is a
    parameter so the deterministic tests never touch the pool.
    """
    system_prompt, user_prompt = build_prompt(arm, case, scope_to_symbol=scope_to_symbol)
    sha = prompt_hash(system_prompt, user_prompt)

    valid_ids: set[str] = set()
    if arm == ARM_NEW:
        reports = _scope_reports_to_symbol(case.reports, case.symbol) if scope_to_symbol else case.reports
        valid_ids = panel_evidence_ids(build_symbol_panel({case.symbol: reports}))

    result = ArmResult(
        arm=arm,
        insight_id=case.insight_id,
        symbol=case.symbol,
        prompt_sha=sha,
        context_chars=len(user_prompt),
        from_cache=False,
    )

    cached = read_cache(arm, case.insight_id, sha, cache_dir)
    if cached is not None:
        result.from_cache = True
        response = cached.get("response") or ""
        result.input_tokens = int(cached.get("input_tokens") or 0)
        result.output_tokens = int(cached.get("output_tokens") or 0)
        result.cost_usd = float(cached.get("cost_usd") or 0.0)
    else:
        if not allow_llm:
            result.error = "not cached and LLM calls are disabled"
            return result
        if query is None:
            from llm.client_pool import pool_query_llm  # local: keeps import cost off tests

            query = pool_query_llm
        try:
            llm_result = await query(system_prompt, user_prompt, f"replay_{arm}")
        except Exception as err:  # pragma: no cover -- network/timeout path
            result.error = f"{type(err).__name__}: {err}"
            return result
        response = getattr(llm_result, "text", "") or ""
        result.input_tokens = int(getattr(llm_result, "input_tokens", 0) or 0)
        result.output_tokens = int(getattr(llm_result, "output_tokens", 0) or 0)
        result.cost_usd = float(getattr(llm_result, "cost_usd", 0.0) or 0.0)
        write_cache(arm, case.insight_id, sha, {
            "arm": arm,
            "insight_id": case.insight_id,
            "symbol": case.symbol,
            "prompt_sha": sha,
            "as_of": case.as_of,
            "response": response,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cost_usd": result.cost_usd,
            "model": getattr(llm_result, "model", "") or "",
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }, cache_dir)

    for key, value in parse_arm_response(arm, case, response, valid_ids).items():
        setattr(result, key, value)
    if not result.parsed and not result.error:
        result.error = "synthesis response could not be parsed into an insight"
    return result


# =============================================================================
# Grading -- every metric comes from analysis.eval_insights
# =============================================================================


def grade_arm(
    case: ReplayCase,
    result: ArmResult,
    series_map: dict[str, Series],
    benchmark_series: Series,
    *,
    horizon_override: str | None = None,
    entry_lag: int = ENTRY_LAG_TRADING_DAYS,
) -> tuple[EvalRecord | None, str | None]:
    """Grade one arm's answer with the shared harness.

    ``horizon_override`` grades both arms over the *same* window (the stored
    insight's own horizon) so a paired difference cannot be an artefact of one
    arm choosing a longer horizon.  Left ``None``, each arm is graded on the
    horizon it actually chose, which is the arm's real prediction.
    """
    if result.action is None:
        return None, "no_action"
    direction = direction_for_action(result.action)
    if direction is None:
        return None, "non_directional_action"
    bars = horizon_trading_days(horizon_override or result.time_horizon or case.time_horizon)
    if bars is None:
        return None, "unknown_horizon"
    series = series_map.get(case.symbol)
    if not series:
        return None, "no_price_series"
    return build_record(
        insight_id=case.insight_id,
        symbol=case.symbol,
        action=result.action,
        direction=direction,
        confidence=float(result.confidence if result.confidence is not None else 0.5),
        created_at=case.created_at,
        pipeline_version=case.pipeline_version,
        horizon_bars=bars,
        symbol_series=series,
        benchmark_series=benchmark_series,
        price_source="price_history",
        entry_lag=entry_lag,
    )


# =============================================================================
# Paired comparison
# =============================================================================


def _mcnemar_exact(b: int, c: int) -> float | None:
    """Two-sided exact McNemar p-value on the discordant counts.

    ``b`` = old right / new wrong, ``c`` = old wrong / new right.  ``None`` when
    there are no discordant pairs at all -- the arms agreed on every case they
    were both graded on, and there is nothing to test.
    """
    n = b + c
    if n == 0:
        return None
    try:
        from scipy.stats import binomtest  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover -- scipy is a hard dependency
        return None
    return float(binomtest(c, n, 0.5, alternative="two-sided").pvalue)


def _wilcoxon(diffs: Sequence[float]) -> float | None:
    """Two-sided Wilcoxon signed-rank p-value on paired alpha differences."""
    nonzero = [d for d in diffs if abs(d) > 1e-12]
    if len(nonzero) < 6:
        # Below ~6 nonzero pairs the exact test cannot reach 0.05 at all, so a
        # p-value would be a number with no power behind it.
        return None
    try:
        from scipy.stats import wilcoxon  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover
        return None
    return float(wilcoxon(nonzero).pvalue)


def _date_clustered_bootstrap(
    pairs: Sequence[dict[str, Any]],
    key: str,
    *,
    iterations: int = 4000,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any] | None:
    """Percentile CI for the mean paired difference, resampling whole dates.

    Calls issued days apart on 20-30 bar horizons share most of their window, so
    resampling individual pairs would treat one market move as many independent
    observations and produce a CI several times too tight.  The resampling unit
    is therefore the date.
    """
    if not pairs:
        return None
    by_date: dict[str, list[float]] = {}
    for pair in pairs:
        by_date.setdefault(pair["as_of"], []).append(float(pair[key]))
    dates = sorted(by_date)
    if len(dates) < 2:
        return None

    # Reproducible resampling for a bootstrap -- not a security context.
    rng = random.Random(seed)  # noqa: S311
    means: list[float] = []
    for _ in range(iterations):
        drawn: list[float] = []
        for _ in dates:
            drawn.extend(by_date[dates[rng.randrange(len(dates))]])
        if drawn:
            means.append(statistics.fmean(drawn))
    means.sort()
    lo = means[int(0.025 * len(means))]
    hi = means[min(len(means) - 1, int(0.975 * len(means)))]
    observed = statistics.fmean(float(p[key]) for p in pairs)
    return {
        "mean_difference": round(observed, 4),
        "ci95_low": round(lo, 4),
        "ci95_high": round(hi, 4),
        "resample_unit": "date",
        "clusters": len(dates),
        "iterations": iterations,
        "excludes_zero": bool(lo > 0 or hi < 0),
    }


def _selection_breakdown(pairs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Split the outcome difference into "same call" and "different call".

    Necessary because the two per-arm cohorts are not the same cases.  When one
    arm answers WATCH it is excluded from grading, so a headline hit-rate gap
    between the arms can come entirely from *which* cases each chose to trade
    rather than from being right more often on the same one.  Reporting the
    cohorts without this split would attribute a selection effect to skill.
    """
    shared = [p for p in pairs if p.get("both_graded")]
    old_only = [p for p in pairs if p.get("old_graded") and not p.get("new_graded")]
    new_only = [p for p in pairs if p.get("new_graded") and not p.get("old_graded")]

    def _block(rows: Sequence[dict[str, Any]], side: str) -> dict[str, Any]:
        if not rows:
            return {"n": 0}
        return {
            "n": len(rows),
            "hit_rate": round(
                sum(1 for r in rows if r[f"{side}_correct"]) / len(rows), 4),
            "mean_alpha_pct": round(
                statistics.fmean(r[f"{side}_alpha_pct"] for r in rows), 3),
            "cases": [
                {"symbol": r["symbol"], "as_of": r["as_of"],
                 "action": r[f"{side}_action"], "correct": r[f"{side}_correct"],
                 "alpha_pct": r[f"{side}_alpha_pct"]}
                for r in rows
            ],
        }

    identical = sum(
        1 for p in shared
        if abs(float(p.get("alpha_delta") or 0.0)) < 1e-9
    )
    return {
        "note": (
            "The per-arm cohort blocks are NOT the same cases. Where both arms "
            "took a direction the graded outcome is identical by construction "
            "unless they took opposite directions; the cohort gap therefore "
            "measures which cases each arm chose to trade, not who was right "
            "more often on the same case."
        ),
        "both_traded": {
            "n": len(shared),
            "identical_outcome": identical,
            "old": _block(shared, "old"),
            "new": _block(shared, "new"),
        },
        "old_arm_only": _block(old_only, "old"),
        "new_arm_only": _block(new_only, "new"),
    }


def effective_sample(cases: Sequence[ReplayCase]) -> dict[str, Any]:
    """The honest denominator: what is actually independent here, and what is not."""
    if not cases:
        return {"pairs": 0}
    by_symbol: dict[str, int] = {}
    for case in cases:
        by_symbol[case.symbol] = by_symbol.get(case.symbol, 0) + 1
    top = sorted(by_symbol.items(), key=lambda kv: (-kv[1], kv[0]))
    dates = sorted({c.as_of for c in cases})
    return {
        "pairs": len(cases),
        "distinct_dates": len(dates),
        "distinct_symbols": len(by_symbol),
        "distinct_symbol_dates": len({(c.symbol, c.as_of) for c in cases}),
        "most_repeated_symbol": {"symbol": top[0][0], "count": top[0][1]},
        "top_symbols": [{"symbol": s, "count": n} for s, n in top[:5]],
        "date_range": {"first": dates[0], "last": dates[-1]},
        "median_pairs_per_date": statistics.median(
            [sum(1 for c in cases if c.as_of == d) for d in dates]
        ),
        "independence_note": (
            "Pairs are neither independent of each other nor identically "
            "distributed: 20-30 trading-day horizons issued days apart overlap "
            "almost completely, and single symbols recur. Every interval below "
            "resamples whole dates for that reason; treat the pair count as an "
            "upper bound on information, never as a sample size."
        ),
    }


# =============================================================================
# Cost estimate
# =============================================================================


def observed_cost_per_call(arm: str, cache_dir: Path = CACHE_DIR) -> float | None:
    """Median cost the SDK actually charged for this arm, from cached calls.

    Median, not mean: one 88k-token turn among the first 20 panel calls pulls
    the mean 20% above every other call, and an estimate that a single retry can
    move is not an estimate.
    """
    costs: list[float] = []
    for path in sorted(cache_dir.glob(f"{arm}__*.json")):
        try:
            with open(path) as fh:
                entry = json.load(fh)
        except Exception:  # pragma: no cover -- a corrupt entry is skipped
            continue
        if entry.get("arm") == arm and entry.get("cost_usd"):
            costs.append(float(entry["cost_usd"]))
    if len(costs) < MIN_CACHED_FOR_CALIBRATION:
        return None
    return statistics.median(costs)


def estimate_cost(
    cases: Sequence[ReplayCase],
    *,
    scope_to_symbol: bool = False,
    cache_dir: Path = CACHE_DIR,
) -> dict[str, Any]:
    """Price the run before spending anything.  Prompts are built, never sent.

    Two models, and the cheaper-to-trust one wins.  If the cache already holds
    real calls for an arm, their median recorded cost prices the run directly.
    Otherwise the prompt is measured and ``CLI_OVERHEAD_INPUT_TOKENS`` is added,
    because the prompt is only ~2-7% of the input actually billed.
    """
    per_arm: dict[str, dict[str, Any]] = {}
    total_cost = 0.0
    total_calls = 0
    cached_calls = 0

    for arm in ARMS:
        chars = 0
        arm_cached = 0
        for case in cases:
            system_prompt, user_prompt = build_prompt(
                arm, case, scope_to_symbol=scope_to_symbol
            )
            chars += len(system_prompt) + len(user_prompt)
            if read_cache(arm, case.insight_id,
                          prompt_hash(system_prompt, user_prompt), cache_dir) is not None:
                arm_cached += 1

        prompt_tokens = int(chars / CHARS_PER_TOKEN)
        input_tokens = prompt_tokens + CLI_OVERHEAD_INPUT_TOKENS * len(cases)
        output_tokens = ESTIMATED_OUTPUT_TOKENS * len(cases)
        modelled = (
            input_tokens * INPUT_USD_PER_MTOK / 1_000_000
            + output_tokens * OUTPUT_USD_PER_MTOK / 1_000_000
        )
        observed = observed_cost_per_call(arm, cache_dir)
        per_call = observed if observed is not None else (
            modelled / len(cases) if cases else 0.0)
        uncached = len(cases) - arm_cached
        billable = per_call * uncached

        per_arm[arm] = {
            "calls": len(cases),
            "cached": arm_cached,
            "to_send": uncached,
            "prompt_chars": chars,
            "est_prompt_tokens": prompt_tokens,
            "est_input_tokens": input_tokens,
            "est_output_tokens": output_tokens,
            "basis": "observed_median_from_cache" if observed is not None else "modelled",
            "est_cost_usd_per_call": round(per_call, 4),
            "est_cost_usd_all": round(per_call * len(cases), 4),
            "est_cost_usd_uncached": round(billable, 4),
        }
        total_cost += billable
        total_calls += len(cases)
        cached_calls += arm_cached

    return {
        "cases": len(cases),
        "calls": total_calls,
        "already_cached": cached_calls,
        "to_send": total_calls - cached_calls,
        "per_arm": per_arm,
        "est_cost_usd": round(total_cost, 4),
        "rates": {
            "input_usd_per_mtok": INPUT_USD_PER_MTOK,
            "output_usd_per_mtok": OUTPUT_USD_PER_MTOK,
            "chars_per_token": CHARS_PER_TOKEN,
            "assumed_output_tokens_per_call": ESTIMATED_OUTPUT_TOKENS,
            "cli_overhead_input_tokens_per_call": CLI_OVERHEAD_INPUT_TOKENS,
            "note": (
                "The first version of this estimator priced the prompt alone and "
                "was 3.75x light: $1.33 predicted against $4.99 spent on 40 calls. "
                "The bundled Claude Code CLI prepends its own system prompt and "
                "tool definitions, so a 3.4k-char prompt was billed ~41.6k input "
                "tokens. Both the fixed overhead and the cache-median basis exist "
                "because of that miss."
            ),
        },
    }


# =============================================================================
# Runner
# =============================================================================


async def run_replay(
    db: AsyncSession,
    *,
    limit: int | None = DEFAULT_LIMIT,
    seed: int = DEFAULT_SEED,
    allow_llm: bool = True,
    scope_to_symbol: bool = False,
    concurrency: int = DEFAULT_CONCURRENCY,
    cache_dir: Path = CACHE_DIR,
    save: bool = True,
    entry_lag: int = ENTRY_LAG_TRADING_DAYS,
    benchmark: str = BENCHMARK_SYMBOL,
    n_bins: int = DEFAULT_RELIABILITY_BINS,
    query: Any = None,
) -> dict[str, Any]:
    """Replay both arms over the sampled cases and return a snapshot dict."""
    population = await load_replay_cases(db)
    cases = sample_cases(population, limit, seed)
    estimate = estimate_cost(cases, scope_to_symbol=scope_to_symbol, cache_dir=cache_dir)

    series_map = await load_local_series(db, {c.symbol for c in cases} | {benchmark})
    benchmark_series = series_map.get(benchmark.upper(), [])
    if not benchmark_series:
        return {
            "error": f"benchmark {benchmark} has no price history -- cannot compute alpha",
            "harness_version": HARNESS_VERSION,
            "cases": len(cases),
        }

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _one(arm: str, case: ReplayCase) -> ArmResult:
        async with semaphore:
            return await run_arm(
                arm, case,
                allow_llm=allow_llm,
                scope_to_symbol=scope_to_symbol,
                cache_dir=cache_dir,
                query=query,
            )

    results = await asyncio.gather(*[
        _one(arm, case) for case in cases for arm in ARMS
    ])
    by_key = {(r.arm, r.insight_id): r for r in results}

    # ---- grade -----------------------------------------------------------
    records: dict[str, list[EvalRecord]] = {arm: [] for arm in ARMS}
    fixed_records: dict[str, list[EvalRecord]] = {arm: [] for arm in ARMS}
    graded: dict[str, dict[int, EvalRecord]] = {arm: {} for arm in ARMS}
    fixed_graded: dict[str, dict[int, EvalRecord]] = {arm: {} for arm in ARMS}
    exclusions: dict[str, dict[str, int]] = {arm: {} for arm in ARMS}

    for case in cases:
        for arm in ARMS:
            result = by_key[(arm, case.insight_id)]
            record, reason = grade_arm(
                case, result, series_map, benchmark_series, entry_lag=entry_lag
            )
            if record is not None:
                records[arm].append(record)
                graded[arm][case.insight_id] = record
            else:
                exclusions[arm][reason or "unknown"] = (
                    exclusions[arm].get(reason or "unknown", 0) + 1
                )
            fixed, _ = grade_arm(
                case, result, series_map, benchmark_series,
                horizon_override=case.time_horizon, entry_lag=entry_lag,
            )
            if fixed is not None:
                fixed_records[arm].append(fixed)
                fixed_graded[arm][case.insight_id] = fixed

    basis = decision_rule_tag(benchmark, entry_lag)

    # ---- paired rows -----------------------------------------------------
    pairs: list[dict[str, Any]] = []
    for case in cases:
        old = by_key[(ARM_OLD, case.insight_id)]
        new = by_key[(ARM_NEW, case.insight_id)]
        old_fixed = fixed_graded[ARM_OLD].get(case.insight_id)
        new_fixed = fixed_graded[ARM_NEW].get(case.insight_id)
        row: dict[str, Any] = {
            "insight_id": case.insight_id,
            "symbol": case.symbol,
            "as_of": case.as_of,
            "stored_action": case.stored_action,
            "stored_confidence": case.stored_confidence,
            "old_action": old.action,
            "new_action": new.action,
            "old_confidence": old.confidence,
            "new_confidence": new.confidence,
            "old_horizon": old.time_horizon,
            "new_horizon": new.time_horizon,
            "same_action": old.action is not None and old.action == new.action,
            "confidence_delta": (
                round(new.confidence - old.confidence, 4)
                if old.confidence is not None and new.confidence is not None else None
            ),
            "old_graded": old_fixed is not None,
            "new_graded": new_fixed is not None,
            "both_graded": old_fixed is not None and new_fixed is not None,
        }
        # A single-arm row still carries that arm's grade, because the cases
        # only one arm chose to trade are where the two cohorts diverge and
        # dropping them would hide the selection effect entirely.
        for side, record in (("old", old_fixed), ("new", new_fixed)):
            if record is not None:
                row[f"{side}_alpha_pct"] = record.alpha_pct * record.direction
                row[f"{side}_correct"] = record.correct
        if old_fixed is not None and new_fixed is not None:
            row.update({
                "alpha_delta": round(
                    new_fixed.alpha_pct * new_fixed.direction
                    - old_fixed.alpha_pct * old_fixed.direction, 4),
                "correct_delta": int(new_fixed.correct) - int(old_fixed.correct),
            })
        pairs.append(row)

    both = [p for p in pairs if p["both_graded"]]
    b = sum(1 for p in both if p["old_correct"] and not p["new_correct"])
    c = sum(1 for p in both if p["new_correct"] and not p["old_correct"])
    answered = [p for p in pairs if p["old_action"] and p["new_action"]]

    paired = {
        "definition": (
            "Same symbol, same date, same stored analyst reports, two "
            "representations. Graded over the stored insight's own horizon for "
            "both arms so a horizon choice cannot masquerade as a skill "
            "difference; the per-arm cohort blocks above instead use each arm's "
            "own chosen horizon."
        ),
        "pairs_attempted": len(pairs),
        "pairs_both_answered": len(answered),
        "pairs_both_graded": len(both),
        "action_agreement": (
            round(sum(1 for p in answered if p["same_action"]) / len(answered), 4)
            if answered else None
        ),
        "action_flips": [
            {"insight_id": p["insight_id"], "symbol": p["symbol"], "as_of": p["as_of"],
             "old": p["old_action"], "new": p["new_action"]}
            for p in answered if not p["same_action"]
        ],
        "mean_confidence_delta": (
            round(statistics.fmean(
                p["confidence_delta"] for p in pairs if p["confidence_delta"] is not None), 4)
            if any(p["confidence_delta"] is not None for p in pairs) else None
        ),
        "selection": _selection_breakdown(pairs),
        "discordant": {"old_right_new_wrong": b, "new_right_old_wrong": c},
        "mcnemar_exact_p": _mcnemar_exact(b, c),
        "hit_rate_delta": (
            round(statistics.fmean(p["correct_delta"] for p in both), 4) if both else None
        ),
        "hit_rate_delta_ci": _date_clustered_bootstrap(both, "correct_delta", seed=seed),
        "alpha_delta_pct": (
            round(statistics.fmean(p["alpha_delta"] for p in both), 4) if both else None
        ),
        "alpha_delta_ci": _date_clustered_bootstrap(both, "alpha_delta", seed=seed),
        "wilcoxon_alpha_p": _wilcoxon([p["alpha_delta"] for p in both]),
    }

    actual_cost = round(sum(r.cost_usd for r in results if not r.from_cache), 4)
    snapshot: dict[str, Any] = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "harness_version": HARNESS_VERSION,
        "git_sha": _git_sha(),
        "what_this_measures": WHAT_THIS_MEASURES,
        "params": {
            "arms": {
                ARM_OLD: "vendored pre-e7e6d36 _flatten_analyst_reports -> format_synthesis_context",
                ARM_NEW: "live build_symbol_panel -> format_symbol_panel_context",
            },
            "system_prompt": "analysis.agents.synthesis_lead.SYNTHESIS_LEAD_PROMPT (unmodified)",
            "one_symbol_per_call": True,
            "scope_to_symbol": scope_to_symbol,
            "limit": limit,
            "seed": seed,
            "benchmark": benchmark,
            "entry_lag_trading_days": entry_lag,
            "decision_rule": decision_rule(benchmark, entry_lag),
            "grading": "analysis.eval_insights.build_record / cohort_metrics",
        },
        "population": {
            "gradeable_total": len(population),
            "replayed": len(cases),
            "sampled": limit is not None and limit < len(population),
        },
        "effective_sample": effective_sample(cases),
        "cost": {
            "estimate": estimate,
            "actual_usd": actual_cost,
            "calls_made": sum(1 for r in results if not r.from_cache),
            "calls_from_cache": sum(1 for r in results if r.from_cache),
            "actual_input_tokens": sum(r.input_tokens for r in results if not r.from_cache),
            "actual_output_tokens": sum(r.output_tokens for r in results if not r.from_cache),
        },
        "evidence_shape": evidence_shape(cases),
        "arms": {
            arm: {
                "answered": sum(1 for case in cases if by_key[(arm, case.insight_id)].action),
                "parse_failures": sum(
                    1 for case in cases if not by_key[(arm, case.insight_id)].parsed),
                "off_target_answers": sum(
                    1 for case in cases if by_key[(arm, case.insight_id)].off_target),
                "action_mix": _count(
                    by_key[(arm, case.insight_id)].action or "NONE" for case in cases),
                "mean_context_chars": round(statistics.fmean(
                    by_key[(arm, case.insight_id)].context_chars for case in cases), 1)
                    if cases else None,
                "evidence_ids_cited": sum(
                    len(by_key[(arm, case.insight_id)].evidence_ids_cited) for case in cases),
                "evidence_ids_invalid": sum(
                    by_key[(arm, case.insight_id)].evidence_ids_invalid for case in cases),
                "analyst_citation_mix": _count(
                    a for case in cases
                    for a in by_key[(arm, case.insight_id)].analysts_cited),
                "analysts_supplied": sorted({
                    name for case in cases for name in case.reports}),
                "answers_citing_a_phantom_analyst": sum(
                    1 for case in cases if by_key[(arm, case.insight_id)].phantom_analysts),
                "phantom_analyst_mix": _count(
                    a for case in cases
                    for a in by_key[(arm, case.insight_id)].phantom_analysts),
                "exclusions": exclusions[arm],
                "own_horizon": cohort_metrics(records[arm], n_bins, True, basis),
                "stored_horizon": cohort_metrics(fixed_records[arm], n_bins, True, basis),
            }
            for arm in ARMS
        },
        "paired": paired,
        "pairs": pairs,
        "results": [asdict(r) for r in results],
    }

    if save:
        REPLAY_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(REPLAY_SNAPSHOT_PATH, "w") as fh:
            json.dump(snapshot, fh, indent=2, default=str)
        logger.info("Synthesis replay snapshot saved to %s", REPLAY_SNAPSHOT_PATH)
    return snapshot


WHAT_THIS_MEASURES = {
    "claim": (
        "Whether the synthesis lead reasons better when the same stored analyst "
        "evidence is shown as a per-symbol panel instead of a run-global "
        "aggregate."
    ),
    "not_a_claim": [
        "Not market edge. The model's training data may contain what actually "
        "happened to these symbols between 2026-02 and 2026-06, so the outcome "
        "is potentially visible through the weights. That look-ahead cannot be "
        "engineered away and the as-of instruction cannot be verified.",
        "Not a test of the a12cf0b de-anchoring. Every stored report was written "
        "by an analyst that had already seen the shared discovery_context "
        "prefix; replay changes the rendering, never the analyst.",
        "Not an independent sample. Overlapping horizons and repeated symbols "
        "mean the pair count overstates the information present.",
        "Not the production panel. Most stored reports are basket-wide, so the "
        "panel's per-symbol boundary -- its main production benefit -- has no "
        "room to show up. See evidence_shape.",
    ],
}


def evidence_shape(cases: Sequence[ReplayCase]) -> dict[str, Any]:
    """Measure the basket-vs-per-symbol shape of the stored reports.

    Free (no LLM), and it is the number that decides how much of the result is
    even interpretable, so it travels inside the snapshot rather than a comment.
    """
    basket = 0
    findings_total = 0
    with_own = 0
    own_survives_cap = 0
    for case in cases:
        technical = case.reports.get("technical") or {}
        findings = [f for f in (technical.get("findings") or []) if isinstance(f, dict)]
        findings_total += len(findings)
        if len({f.get("symbol") for f in findings}) > 1:
            basket += 1
        mine = [f for f in findings if f.get("symbol") == case.symbol]
        if mine:
            with_own += 1
            if any(f.get("symbol") == case.symbol for f in findings[:5]):
                own_survives_cap += 1
    return {
        "cases": len(cases),
        "basket_wide_technical_reports": basket,
        "mean_findings_per_report": (
            round(findings_total / len(cases), 2) if cases else None),
        "cases_whose_basket_names_the_target": with_own,
        "target_finding_survives_old_arm_cap": own_survives_cap,
        "target_finding_dropped_by_old_arm_cap": with_own - own_survives_cap,
        "note": (
            "format_synthesis_context renders findings[:5]. Where the stored "
            "report is basket-wide -- the norm before 2026-06-24 -- that prefix "
            "cap is the production defect, reproduced exactly. It also means the "
            "new arm's per-symbol boundary is untested here: the panel is handed "
            "one symbol key whose reports describe many symbols."
        ),
    }


def _count(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        out[str(value)] = out.get(str(value), 0) + 1
    return dict(sorted(out.items()))


# =============================================================================
# Report
# =============================================================================


def format_replay_summary(snapshot: dict[str, Any]) -> str:
    """Render a snapshot as a plain-text report."""
    if "error" in snapshot:
        return f"replay failed: {snapshot['error']}"

    lines: list[str] = []
    add = lines.append
    add("=" * 72)
    add("SYNTHESIS REPLAY -- old run-global aggregate vs new per-symbol panel")
    add("=" * 72)
    add(snapshot["what_this_measures"]["claim"])
    add("")
    add("This does NOT show:")
    for item in snapshot["what_this_measures"]["not_a_claim"]:
        add(f"  - {item}")
    add("")

    eff = snapshot["effective_sample"]
    pop = snapshot["population"]
    add(f"Population: {pop['gradeable_total']} gradeable, {pop['replayed']} replayed"
        + (" (SAMPLE)" if pop["sampled"] else " (full)"))
    add(f"Effective sample: {eff.get('pairs')} pairs over "
        f"{eff.get('distinct_dates')} dates and {eff.get('distinct_symbols')} symbols; "
        f"most repeated {eff.get('most_repeated_symbol', {}).get('symbol')} "
        f"x{eff.get('most_repeated_symbol', {}).get('count')}")
    add("")

    shape = snapshot["evidence_shape"]
    add(f"Evidence shape: {shape['basket_wide_technical_reports']}/{shape['cases']} "
        f"technical reports are basket-wide "
        f"({shape['mean_findings_per_report']} findings each); the old arm's "
        f"findings[:5] cap drops the target's own finding in "
        f"{shape['target_finding_dropped_by_old_arm_cap']} of "
        f"{shape['cases_whose_basket_names_the_target']} cases that have one.")
    add("")

    cost = snapshot["cost"]
    add(f"Cost: estimated ${cost['estimate']['est_cost_usd']:.2f} for "
        f"{cost['estimate']['to_send']} uncached calls; actual "
        f"${cost['actual_usd']:.2f} over {cost['calls_made']} calls "
        f"({cost['calls_from_cache']} served from cache).")
    add("")

    for arm in ARMS:
        block = snapshot["arms"][arm]
        own = block["stored_horizon"]
        add(f"[{arm}] answered {block['answered']}, "
            f"parse failures {block['parse_failures']}, "
            f"off-target {block['off_target_answers']}")
        add(f"    actions: {block['action_mix']}")
        add(f"    context {block['mean_context_chars']} chars; "
            f"evidence IDs cited {block['evidence_ids_cited']} "
            f"({block['evidence_ids_invalid']} invented); "
            f"answers citing an analyst that never reported: "
            f"{block['answers_citing_a_phantom_analyst']} {block['phantom_analyst_mix'] or ''}")
        if own.get("n"):
            add(f"    graded n={own['n']}  hit_rate={own['hit_rate']:.3f}  "
                f"mean_alpha={own['mean_alpha_pct']:+.2f}%  "
                f"brier={own['brier']:.4f}  ece={own['ece']:.4f}  "
                f"slope={own.get('calibration_slope')}")
        else:
            add("    graded n=0")
    add("")

    paired = snapshot["paired"]
    add("PAIRED (same symbol, same date, same evidence, stored horizon for both)")
    add(f"  pairs both answered: {paired['pairs_both_answered']}, "
        f"both graded: {paired['pairs_both_graded']}")
    add(f"  action agreement: {paired['action_agreement']}")
    add(f"  mean confidence delta (new - old): {paired['mean_confidence_delta']}")
    add(f"  hit-rate delta: {paired['hit_rate_delta']}  "
        f"CI95 {_ci(paired.get('hit_rate_delta_ci'))}")
    add(f"  alpha delta: {paired['alpha_delta_pct']}%  "
        f"CI95 {_ci(paired.get('alpha_delta_ci'))}")
    selection = paired.get("selection") or {}
    both_traded = selection.get("both_traded") or {}
    add(f"  both arms traded: {both_traded.get('n')} "
        f"({both_traded.get('identical_outcome')} with an identical outcome)")
    add(f"  old arm alone: n={selection.get('old_arm_only', {}).get('n')} "
        f"hit={selection.get('old_arm_only', {}).get('hit_rate')} "
        f"alpha={selection.get('old_arm_only', {}).get('mean_alpha_pct')}%")
    add(f"  new arm alone: n={selection.get('new_arm_only', {}).get('n')} "
        f"hit={selection.get('new_arm_only', {}).get('hit_rate')} "
        f"alpha={selection.get('new_arm_only', {}).get('mean_alpha_pct')}%")
    add(f"  discordant: {paired['discordant']}  "
        f"McNemar exact p = {paired['mcnemar_exact_p']}")
    add(f"  Wilcoxon on paired alpha p = {paired['wilcoxon_alpha_p']}")
    add("")
    add(effective_sample_note(eff))
    return "\n".join(lines)


def _ci(block: dict[str, Any] | None) -> str:
    if not block:
        return "n/a"
    return f"[{block['ci95_low']}, {block['ci95_high']}] ({block['clusters']} date clusters)"


def effective_sample_note(eff: dict[str, Any]) -> str:
    return eff.get("independence_note", "")


# =============================================================================
# CLI
# =============================================================================


async def _main() -> None:  # pragma: no cover -- CLI
    parser = argparse.ArgumentParser(
        description="Replay the synthesis lead on stored evidence: old aggregate vs new panel",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"cases to replay (default {DEFAULT_LIMIT}); 2 LLM calls each")
    parser.add_argument("--all", action="store_true",
                        help="replay every gradeable case -- opt-in, this is the expensive run")
    parser.add_argument("--estimate-only", action="store_true",
                        help="build every prompt, print the cost, send nothing")
    parser.add_argument("--no-llm", action="store_true",
                        help="serve only from the response cache; never call the model")
    parser.add_argument("--scope-to-symbol", action="store_true",
                        help="filter basket-wide reports to the target for BOTH arms")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--bins", type=int, default=DEFAULT_RELIABILITY_BINS)
    parser.add_argument("--no-save", action="store_true", help="do not write the snapshot")
    args = parser.parse_args()

    limit = None if args.all else args.limit

    from database import async_session_factory

    async with async_session_factory() as session:
        population = await load_replay_cases(session)
        cases = sample_cases(population, limit, args.seed)
        estimate = estimate_cost(cases, scope_to_symbol=args.scope_to_symbol)
        print(  # noqa: T201 -- CLI report
            f"{len(population)} gradeable cases; replaying {len(cases)} "
            f"({estimate['calls']} calls, {estimate['already_cached']} cached, "
            f"{estimate['to_send']} to send)\n"
            f"ESTIMATED COST: ${estimate['est_cost_usd']:.2f} "
            f"(floor -- see rates.note in the snapshot)"
        )
        if args.estimate_only:
            print(json.dumps(estimate, indent=2))  # noqa: T201
            return

        snapshot = await run_replay(
            session,
            limit=limit,
            seed=args.seed,
            allow_llm=not args.no_llm,
            scope_to_symbol=args.scope_to_symbol,
            concurrency=args.concurrency,
            save=not args.no_save,
            n_bins=args.bins,
        )
    print(format_replay_summary(snapshot))  # noqa: T201 -- CLI report


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(_main())
