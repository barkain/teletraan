"""Single source of truth for insight time horizons.

Both the outcome grader (``analysis/outcome_tracker.py``) and the evaluation
harness (``analysis/eval_insights.py``) turn a ``DeepInsight.time_horizon``
label into a tracking window. They were built independently and diverged on
``medium_term`` — 30 trading days versus 63 — which is a 2x split on the most
common label in the database. This module exists so that can never happen
again: change the number here and every consumer moves together.

The horizon constant is not a free parameter. Because a shorter window closes
sooner, changing it changes *which* insights are gradeable at a given moment,
not merely how the same insights score. See ``is_window_closed`` and the note
on comparing populations below.
"""

from __future__ import annotations

from datetime import date, timedelta

# Horizon label -> tracking window in TRADING days.
#
# Keys are the values actually written to DeepInsight.time_horizon. An earlier
# version of this table was keyed on freeform phrases ("1-2 weeks", ...) that
# the column never contains, so every lookup missed and fell through to a
# 30-day default, making the horizon effectively constant. The legacy phrasings
# are retained below the canonical keys so historical or hand-written values
# still resolve rather than falling through.
#
# medium_term = 30 was set by team decision on 2026-08-16: sampled medium_term
# theses state 4-6 / 6-8 / 8-10 week views (~20-50 bars, median ~35) and cite
# 20D momentum, and 30 reconciles the grader's and harness's independently
# measured benchmark returns, which 63 did not.
HORIZON_TRADING_DAYS: dict[str, int] = {
    # Canonical values written by the engines
    "immediate": 5,
    "near_term": 10,
    "short_term": 15,
    "swing": 20,
    "medium_term": 30,
    "position": 60,
    "long_term": 125,
    # Legacy / freeform phrasings
    "1-2 weeks": 10,
    "2-4 weeks": 21,
    "1-3 months": 60,
    "3-6 months": 120,
    "6-12 months": 270,
}

# Horizon values that carry no information. Refusing to map these is
# deliberate: a made-up window produces a made-up grade.
UNKNOWN_HORIZONS = frozenset({"", "unknown", "n/a", "na", "none", "tbd"})

# Trading days per calendar week, used to convert a window into wall-clock time.
_TRADING_DAYS_PER_WEEK = 5


def trading_to_calendar_days(trading_days: int) -> int:
    """Convert trading days to calendar days at ~5 trading days per week."""
    return int(trading_days * 7 / _TRADING_DAYS_PER_WEEK)


def resolve_horizon_days(time_horizon: str | None) -> int:
    """Map a ``DeepInsight.time_horizon`` onto a window in trading days.

    Args:
        time_horizon: The insight's own stated horizon (e.g. "medium_term")

    Returns:
        Number of trading days to track.

    Raises:
        ValueError: If the horizon is missing, unknown, or unmappable. Callers
            must not invent a window — an insight whose horizon cannot be read
            cannot be graded on a horizon.
    """
    key = (time_horizon or "").lower().strip()
    if key in UNKNOWN_HORIZONS:
        raise ValueError(
            f"Cannot derive a tracking window from time_horizon={time_horizon!r}"
        )

    if key in HORIZON_TRADING_DAYS:
        return HORIZON_TRADING_DAYS[key]

    # Freeform text such as "2-4 weeks (medium_term)" — accept a substring
    # match against a known key rather than silently defaulting.
    for known, days in HORIZON_TRADING_DAYS.items():
        if known in key:
            return days

    raise ValueError(
        f"Unrecognised time_horizon={time_horizon!r}; "
        f"expected one of {sorted(HORIZON_TRADING_DAYS)}"
    )


def window_end_date(start: date, time_horizon: str | None) -> date:
    """The calendar date on which an insight's tracking window closes."""
    return start + timedelta(
        days=trading_to_calendar_days(resolve_horizon_days(time_horizon))
    )


def is_window_closed(
    start: date, time_horizon: str | None, as_of: date | None = None
) -> bool:
    """Whether an insight's window has closed by ``as_of`` (default today).

    Use this to build the *intersection* when comparing two horizon settings or
    two version cohorts. A shorter horizon closes sooner and therefore admits
    insights a longer horizon cannot see yet: at 30 trading days a window
    closes in 42 calendar days, at 63 it takes 88, so on any given day a block
    of the newest insights is gradeable under one setting and invisible under
    the other. Comparing headline metrics across settings without restricting
    to the insights closed under *both* measures which insights happened to
    become gradeable — differing in sample size, calendar period and market
    regime at once — rather than measuring analysis quality.
    """
    return (as_of or date.today()) >= window_end_date(start, time_horizon)
