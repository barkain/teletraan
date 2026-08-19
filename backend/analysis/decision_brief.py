"""The neutral decision brief handed to every blinded specialist analyst.

Until this module existed, all three specialists (technical, sector, risk)
received the run's ``discovery_context`` string *before* they saw any data.
That string carries the macro regime call, the heatmap rationale for why the
symbol entered the funnel, the thematic call, the factor/quant nomination and a
correlation narrative -- i.e. Phase 1-3's **conclusions**.  Three analysts
primed on one conclusion do not corroborate each other; their agreement
measures the priming.  Every symbol's risk report in the 2026-08-18 run came
back with the same ``current_vix`` and the same "SKEW at 138" narrative, which
is that signature.

Withholding the prefix outright would have been a different bug: the macro
economist was dropped from the deep-dive roster precisely *because* its context
was prepended to every analyst, so removing the prefix and putting nothing in
its place leaves the specialists with no macro input at all.

This module is the answer to both.  It shares the market **state** -- dated,
observed levels with no interpretation -- and withholds the market **call**.
The specialists still know what day it is, what horizon the decision is for,
that the mandate is long-only, whether the name is already held, and where the
volatility/rates/index/commodity/FX complex actually sits.  They are not told
what any of it means, why this symbol was nominated, or what anyone else
concluded.

Deliberately excluded, and why -- each is a conclusion, not an observation:

* ``MacroScanResult.market_regime`` / ``regime_confidence`` / ``regime_evidence``
  -- the regime call.
* ``MacroScanResult.themes`` and ``key_risks`` -- LLM narratives built on that call.
* ``MacroScanResult.actionable_implications`` -- sector preferences and risk
  posture, i.e. the recommendation itself.
* ``HeatmapAnalysis.overview`` / ``patterns`` / ``sectors_to_watch`` /
  ``selected_stocks[].reason`` -- the selection rationale.
* Factor-model composite scores and the IC-calibrated quant block -- the
  bottom-up nomination.
* The thematic result and stock thematic profiles -- the thematic call.
* The pairwise correlation matrix -- a cross-symbol view that belongs to
  synthesis, and whose narrative framing is a conclusion about the universe.

All of that is retained: it reaches synthesis once, labelled as the nominator
proposal, *after* the private specialist reports already exist.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from analysis.horizons import (  # type: ignore[import-not-found]
    resolve_horizon_days,
    trading_to_calendar_days,
    window_end_date,
)

# The horizon the autonomous pipeline decides over.  ``medium_term`` is the
# default written to ``DeepInsight.time_horizon`` by both engines
# (``synthesis_lead.DeepInsightDraft.time_horizon``), so it is the horizon the
# specialists are in fact being asked about.
DEFAULT_DECISION_HORIZON = "medium_term"

# Heading the leakage test greps for, and the marker that separates the brief
# from the analyst's own data blocks.
BRIEF_HEADING = "## DECISION BRIEF"
MARKET_STATE_HEADING = "### MARKET STATE"

# raw_data category -> (rendered label, value format).  Order is the render
# order.  ``sector_etfs`` and ``global_indices`` are intentionally absent: the
# sector strategist already receives a sector performance table from its own
# formatter, and a second differently-sourced one would invite the two to be
# read as confirmation of each other.
_STATE_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("volatility", "Volatility", "{:.2f}"),
    ("treasuries", "Treasury yields", "{:.3f}%"),
    ("us_indices", "US equity indices", "{:,.2f}"),
    ("commodities", "Commodities", "{:,.2f}"),
    ("currencies", "Currencies", "{:,.2f}"),
)


def _as_date(value: Any) -> date:
    """Coerce a date/datetime/ISO string to a ``date``; today on failure."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    return datetime.now().date()


def _format_state_row(symbol: str, info: Any, value_fmt: str) -> str | None:
    """One observed instrument, or ``None`` when there is nothing to report.

    Absent is rendered as absent.  A missing level is never printed as ``0``,
    which is the fabrication discipline the rest of the codebase already keeps
    (``format_factor_value``, the ``Evidence`` contract, ``price_freshness``).
    """
    if not isinstance(info, dict):
        return None
    data = info.get("data")
    if not isinstance(data, dict):
        return None

    current = data.get("current")
    if not isinstance(current, (int, float)):
        return None

    name = info.get("name") or symbol
    parts = [f"  {name} ({symbol}): {value_fmt.format(current)}"]

    change = data.get("change_20d_pct")
    if isinstance(change, (int, float)):
        parts.append(f"20D change {change:+.2f}%")
    else:
        parts.append("20D change not reported")

    trend = data.get("trend")
    if isinstance(trend, str) and trend:
        parts.append(f"trend vs 10D average: {trend}")

    low = data.get("low_20d")
    high = data.get("high_20d")
    if isinstance(low, (int, float)) and isinstance(high, (int, float)):
        parts.append(
            f"20D range {value_fmt.format(low)}-{value_fmt.format(high)}"
        )

    return " | ".join(parts)


def format_market_state(market_state: dict[str, Any] | None) -> list[str]:
    """Render the observed macro complex as lines, conclusions stripped.

    Input is ``MacroScanResult.raw_data`` -- the pre-LLM fetch, so it contains
    measurements only and no part of the regime call.

    Args:
        market_state: ``MacroScanResult.raw_data``, or ``None``.

    Returns:
        Lines for the brief.  When no state is available the caller is told so
        rather than shown an empty heading.
    """
    lines = [
        MARKET_STATE_HEADING + " (observed levels, no interpretation)",
    ]

    if not isinstance(market_state, dict) or not market_state:
        lines.append(
            "  Market state was not available for this run. Work from your own "
            "data blocks and say so if that limits the call."
        )
        return lines

    rendered_any = False
    for key, label, value_fmt in _STATE_CATEGORIES:
        block = market_state.get(key)
        if not isinstance(block, dict) or not block:
            continue
        rows = [
            row
            for symbol, info in block.items()
            if (row := _format_state_row(symbol, info, value_fmt)) is not None
        ]
        if not rows:
            continue
        lines.append(label + ":")
        lines.extend(rows)
        rendered_any = True

    if not rendered_any:
        lines.append(
            "  Market state was not available for this run. Work from your own "
            "data blocks and say so if that limits the call."
        )
        return lines

    lines.append(
        "  These are measurements over a 20 trading-day window, not a regime "
        "call. Any reading of them is yours to make and to justify."
    )
    return lines


def neutral_decision_brief(
    symbol: str,
    *,
    as_of: Any = None,
    horizon: str = DEFAULT_DECISION_HORIZON,
    long_only: bool = True,
    held: bool = False,
    market_state: dict[str, Any] | None = None,
) -> str:
    """The facts-only brief that replaced ``discovery_context`` for specialists.

    Args:
        symbol: The target symbol this specialist is analysing.
        as_of: Run date (``date``/``datetime``/ISO string). Defaults to today.
        horizon: The decision horizon label, resolved through
            :mod:`analysis.horizons` so the brief and the outcome grader can
            never state different windows.
        long_only: Whether the mandate forbids short expressions.
        held: Whether the portfolio already holds this symbol.
        market_state: ``MacroScanResult.raw_data``.

    Returns:
        The rendered brief.  It states the target, the date, the horizon in
        both trading days and wall-clock, the mandate, the holding status, the
        blinding itself, and the observed market state -- and nothing about why
        this symbol was selected or what anyone else concluded.
    """
    run_date = _as_date(as_of)

    try:
        trading_days = resolve_horizon_days(horizon)
    except ValueError:
        trading_days = None

    if trading_days is not None:
        calendar_days = trading_to_calendar_days(trading_days)
        end = window_end_date(run_date, horizon)
        horizon_line = (
            f"Decision horizon: {horizon} -- {trading_days} trading days "
            f"(~{calendar_days} calendar days), i.e. through {end.isoformat()}. "
            f"A claim that cannot resolve inside that window is not actionable here."
        )
    else:
        horizon_line = (
            f"Decision horizon: {horizon} (window unresolvable -- state the "
            f"horizon your own evidence actually supports)."
        )

    mandate_line = (
        "Mandate: long-only. The book can buy, add, hold or stand aside; it "
        "cannot short. A bearish read is still worth reporting -- it is "
        "expressed as standing aside, not as a short."
        if long_only
        else "Mandate: long and short expressions are both permitted."
    )

    holding_line = (
        f"Position: {symbol} is ALREADY HELD in the portfolio, so the live "
        f"question is add / hold / trim, not initiate."
        if held
        else f"Position: {symbol} is NOT currently held. The live question is "
        f"whether to initiate."
    )

    lines = [
        f"{BRIEF_HEADING} (facts only -- no house view)",
        f"Target: {symbol}",
        f"As of: {run_date.isoformat()} (your data blocks run through the most "
        f"recent close available on that date)",
        horizon_line,
        mandate_line,
        holding_line,
        "",
        "You are one of three specialists (technical, sector, risk) writing "
        "PRIVATE, INDEPENDENT reports on this symbol. You have deliberately not "
        "been told why this symbol was selected, what regime or thematic call "
        "the discovery phase made, or what the other two specialists think. "
        "That is by design: a shared conclusion handed to all three would make "
        "your agreement worthless as evidence. Report what your own data "
        "supports, name the evidence against your own view, and state what "
        "would invalidate it.",
        "",
    ]
    lines.extend(format_market_state(market_state))

    return "\n".join(lines)
