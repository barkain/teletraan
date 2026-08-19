"""The long-only rule: this system takes long positions in stocks and never shorts.

The owner's decision, and the measurement behind it. An independent review
graded 209 directional calls:

===========================================  ==========  ===========
rule                                          hit rate    mean alpha
===========================================  ==========  ===========
the system's own BUY/SELL direction             44.98%       +0.40%
always long the same selected names             54.55%       +1.47%
===========================================  ==========  ===========

The long calls are identical between the two rules. The entire 9.6-point gap
is the short book, which was right 13 times out of 46 (28.3%).

``SELL`` and ``STRONG_SELL`` were always meant to mean "exit a position you
hold" -- a long-only action -- and the synthesis prompt has said so since it
was written. Nothing checked it, so every portfolio-only call in the database
was issued on a symbol the (empty) portfolio never held: naked shorts by
accident.

This module is the single statement of the rule in code. Both engines import
it -- ``AutonomousDeepEngine`` and ``DeepAnalysisEngine`` -- so the two store
paths cannot drift apart. It is a leaf: nothing here imports an engine, and
the database is reached only through a function-local import, so it can be
imported from anywhere in ``analysis/``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

logger = logging.getLogger(__name__)


# What each action that presupposes an existing position becomes when the
# portfolio does not hold the symbol.
#
# SELL/STRONG_SELL fall to WATCH rather than being discarded: the observation
# behind a bearish call is often worth reading even when the action is not
# permitted, and WATCH is non-directional, so it starts no outcome tracking and
# is never graded as a trade. BUY_MORE is not a short -- it is a new long
# wearing the wrong label -- so it becomes the BUY it actually describes.
LONG_ONLY_ACTION_FALLBACK = {
    "SELL": "WATCH",
    "STRONG_SELL": "WATCH",
    "BUY_MORE": "BUY",
}


def coerce_long_only_action(
    action: str,
    symbol: str | None,
    held_symbols: set[str],
) -> tuple[str, str | None]:
    """Apply the long-only rule to one action, returning what may be stored.

    SELL, STRONG_SELL and BUY_MORE all presuppose an existing position. On a
    symbol the portfolio does not hold, SELL/STRONG_SELL is a naked short --
    which this system does not take -- and BUY_MORE is a new long under the
    wrong name.

    Args:
        action: Proposed action, already upper-cased and validated.
        symbol: Primary symbol of the insight, or None for basket insights.
        held_symbols: Upper-cased symbols the portfolio currently holds.

    Returns:
        ``(action, violation)`` where *action* is what may be stored and
        *violation* is a short ``"SYMBOL SELL->WATCH"`` note when the action
        was changed, or None when it was already permitted.
    """
    replacement = LONG_ONLY_ACTION_FALLBACK.get(action)
    if replacement is None:
        return action, None
    if symbol and symbol.upper() in held_symbols:
        # A genuine exit (or add) on a position that actually exists.
        return action, None
    return replacement, f"{symbol or '<no symbol>'} {action}->{replacement}"


async def held_symbols_for_actions(
    actions: Iterable[str],
    loader: Callable[[], Awaitable[Any]],
) -> set[str]:
    """Portfolio symbols the guard checks against, loaded only when needed.

    Reading the portfolio costs a query, and a run of ordinary BUY/WATCH
    insights has nothing to check it against, so *loader* is awaited only when
    at least one action actually presupposes a position.

    Args:
        actions: The proposed actions in the batch about to be stored.
        loader: Awaitable returning the portfolio holdings -- any iterable of
            symbols, including the ``{symbol: {...}}`` mapping the engines use.

    Returns:
        Upper-cased held symbols, empty when none are needed or held.
    """
    if not any((a or "").upper() in LONG_ONLY_ACTION_FALLBACK for a in actions):
        return set()
    return {str(s).upper() for s in await loader()}


def log_long_only_violation(prefix: str, violation: str, symbol: str | None) -> None:
    """Emit the standard warning for a downgraded action.

    Args:
        prefix: Log tag identifying the pipeline, e.g. ``"[LONG-ONLY]"``.
        violation: The note returned by :func:`coerce_long_only_action`.
        symbol: Primary symbol of the insight, for the message body.
    """
    logger.warning(
        "%s %s: %s is not a held position, so the action is not available to a "
        "long-only system",
        prefix, violation, symbol or "<no symbol>",
    )
