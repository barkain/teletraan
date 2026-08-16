"""Per-symbol slicing of the shared market context.

The autonomous deep dive builds one market context covering every candidate
symbol and then hands *that same object* to each symbol's analysts.  The symbol
under analysis was passed alongside the context as logging metadata only, so
the formatted prompt was byte-identical for every target: a run over
``AAPL, MSFT`` produced one technical body containing both stocks and asked the
model to analyse "the" stock.  Attribution on every deep-dive recommendation
was therefore a coin flip.

This module builds the per-symbol view:

* :func:`slice_context_for_symbol` — narrow every symbol-keyed block to the
  target, keep the market-wide blocks shared, and summarise the other symbols
  into an explicitly labelled comparison block.
* :func:`target_banner` / :func:`format_peer_comparison` — the two strings the
  analyst formatters wrap their output in, so the target is stated in-band
  rather than inferred.
* :func:`partition_by_freshness` — split a candidate list into the symbols whose
  price snapshot may be analysed and the ones whose data is stale or missing.

The slice is always a **new dict**: ``build_context`` serves a TTL-cached
object, so mutating the context in place would corrupt every other symbol's
view and poison the cache for the next five minutes.

Only ``price_freshness`` is imported here — this module is pulled in by the
``analysis.agents.*`` formatters and must not create an import cycle.
"""

from __future__ import annotations

import logging
from typing import Any

from analysis.price_freshness import describe, is_usable, resolve_snapshot

logger = logging.getLogger(__name__)

# Context blocks keyed by symbol.  Each is narrowed to the target; the record
# for a symbol is self-contained, so slicing loses nothing.
SYMBOL_KEYED_BLOCKS = (
    "price_history",
    "price_freshness",
    "technical_indicators",
    "rich_technical",
    "fundamentals",
    "analyst_revisions",
    "options_flow",
    "short_interest",
)

# Heading the peer/benchmark block is rendered under.  Formatters emit it
# verbatim so a reader (human or model) can tell target data from context data.
PEER_HEADING = "PEER / BENCHMARK COMPARISON -- CONTEXT ONLY, NOT THE TARGET'S DATA"

# Number of newest bars used for the peer trend figure.
PEER_TREND_BARS = 20


def _lookup(block: Any, symbol: str) -> Any:
    """Case-insensitive fetch of *symbol* from a symbol-keyed mapping."""
    if not isinstance(block, dict):
        return None
    if symbol in block:
        return block[symbol]
    upper = symbol.upper()
    if upper in block:
        return block[upper]
    for key, value in block.items():
        if isinstance(key, str) and key.upper() == upper:
            return value
    return None


def _same_symbol(candidate: Any, symbol: str) -> bool:
    return isinstance(candidate, str) and candidate.upper() == symbol.upper()


def target_banner(symbol: str) -> str:
    """The in-band statement of which symbol the analyst is working on.

    Every analyst payload starts with this.  The symbol used to travel only in
    the LLM call's metadata, which the model never sees.
    """
    return (
        f"TARGET SYMBOL: {symbol}\n"
        f"Every data block below describes {symbol}, except the section headed "
        f"'{PEER_HEADING}'. Analyse {symbol} and no other ticker; do not "
        f"attribute any figure from the comparison section to {symbol}."
    )


def _peer_summary(context: dict[str, Any], symbol: str) -> dict[str, Any]:
    """Compact, clearly-attributed facts about one non-target symbol."""
    stocks = context.get("stocks") or []
    meta = next(
        (
            s for s in stocks
            if isinstance(s, dict) and _same_symbol(s.get("symbol"), symbol)
        ),
        {},
    )

    freshness = resolve_snapshot(context, symbol)
    bars = _lookup(context.get("price_history"), symbol) or []

    trend_pct: float | None = None
    window = bars[:PEER_TREND_BARS]
    if len(window) >= 2:
        newest = window[0].get("close")
        oldest = window[-1].get("close")
        if newest and oldest:
            trend_pct = ((newest - oldest) / oldest) * 100

    return {
        "symbol": symbol,
        "name": meta.get("name") or symbol,
        "sector": meta.get("sector"),
        "price": (freshness or {}).get("price"),
        "status": (freshness or {}).get("status"),
        "as_of": (freshness or {}).get("latest_bar_date"),
        "provenance": describe(freshness),
        "trend_pct": trend_pct,
        "trend_bars": len(window),
    }


def _peer_symbols(context: dict[str, Any], target: str) -> list[str]:
    """Every symbol carried by the context other than *target*, in a stable order."""
    seen: dict[str, None] = {}
    for block_name in ("price_history", "price_freshness", "rich_technical"):
        block = context.get(block_name)
        if isinstance(block, dict):
            for key in block:
                if isinstance(key, str) and not _same_symbol(key, target):
                    seen.setdefault(key, None)
    for stock in context.get("stocks") or []:
        if isinstance(stock, dict):
            key = stock.get("symbol")
            if isinstance(key, str) and not _same_symbol(key, target):
                seen.setdefault(key, None)
    return list(seen)


def _slice_news(news: Any, symbol: str) -> Any:
    """Keep the market-wide news read, narrow ``per_symbol`` to the target."""
    if not isinstance(news, dict):
        return news
    sliced = dict(news)
    per_symbol = news.get("per_symbol")
    if isinstance(per_symbol, dict):
        record = _lookup(per_symbol, symbol)
        sliced["per_symbol"] = {symbol: record} if record is not None else {}
    vacuum = news.get("vacuum")
    if isinstance(vacuum, list):
        sliced["vacuum"] = [v for v in vacuum if _vacuum_matches(v, symbol)]
    return sliced


def _vacuum_matches(entry: Any, symbol: str) -> bool:
    if isinstance(entry, str):
        return _same_symbol(entry, symbol)
    if isinstance(entry, dict):
        return _same_symbol(entry.get("symbol"), symbol)
    return False


def _slice_sentiment(sentiment: Any, symbol: str) -> Any:
    """Keep the overall mood, narrow the per-symbol list to the target."""
    if not isinstance(sentiment, dict):
        return sentiment
    per_symbol = sentiment.get("per_symbol")
    if not isinstance(per_symbol, list):
        return sentiment
    sliced = dict(sentiment)
    sliced["per_symbol"] = [
        entry for entry in per_symbol
        if isinstance(entry, dict) and _same_symbol(entry.get("symbol"), symbol)
    ]
    return sliced


def slice_context_for_symbol(context: dict[str, Any], symbol: str) -> dict[str, Any]:
    """Return a **new** context describing *symbol* only.

    Symbol-keyed blocks are narrowed to the target, market-wide blocks
    (timestamp, economic indicators, sector performance, market summary,
    portfolio and macro blocks) are carried through unchanged, and the other
    symbols are summarised under :data:`PEER_HEADING`.

    Copy depth, stated precisely: the returned dict is new, so rebinding or
    inserting a key on a slice cannot reach the shared context.  Nested values
    are otherwise **shared by reference** -- ``slice["price_history"][SYM]`` is
    the caller's own bar list, and mutating it in place would corrupt every
    other symbol's slice and poison the ``build_context`` TTL cache for five
    minutes.  The one exception is the ``price_freshness`` record, which is
    copied: it is a small flat dict, it is the block a formatter is most likely
    to want to annotate (``resolve_snapshot`` already reconciles it against
    ``rich_technical``), and slices are consumed concurrently under
    ``asyncio.gather``.  Treat every other block as read-only.

    Slicing an already-sliced context is a no-op: an existing
    ``peer_comparison`` for the same target is carried through rather than
    recomputed from the (peer-free) slice.
    """
    if not isinstance(context, dict):
        return {"target_symbol": symbol}

    sliced: dict[str, Any] = {}

    for key, value in context.items():
        if key in SYMBOL_KEYED_BLOCKS:
            continue
        if key in ("stocks", "news", "sentiment", "peer_comparison"):
            continue
        sliced[key] = value

    for block_name in SYMBOL_KEYED_BLOCKS:
        if block_name not in context:
            continue
        block = context[block_name]
        if not isinstance(block, dict):
            sliced[block_name] = block
            continue
        record = _lookup(block, symbol)
        if record is None:
            sliced[block_name] = {}
        elif block_name == "price_freshness" and isinstance(record, dict):
            # Flat dict of scalars, so a shallow copy is a full one.
            sliced[block_name] = {symbol: dict(record)}
        else:
            sliced[block_name] = {symbol: record}

    stocks = context.get("stocks")
    if isinstance(stocks, list):
        sliced["stocks"] = [
            s for s in stocks
            if isinstance(s, dict) and _same_symbol(s.get("symbol"), symbol)
        ]
    elif stocks is not None:
        sliced["stocks"] = stocks

    if "news" in context:
        sliced["news"] = _slice_news(context["news"], symbol)
    if "sentiment" in context:
        sliced["sentiment"] = _slice_sentiment(context["sentiment"], symbol)

    sliced["target_symbol"] = symbol

    existing_peers = context.get("peer_comparison")
    if (
        isinstance(existing_peers, dict)
        and _same_symbol(existing_peers.get("target"), symbol)
    ):
        sliced["peer_comparison"] = existing_peers
    else:
        sliced["peer_comparison"] = {
            "target": symbol,
            "peers": [
                _peer_summary(context, peer)
                for peer in _peer_symbols(context, symbol)
            ],
        }

    return sliced


def format_peer_comparison(context: dict[str, Any]) -> str:
    """Render the labelled comparison block, or ``""`` when there are no peers.

    Cross-symbol context stays available to the analyst -- relative strength is
    genuinely useful -- but under a heading that makes misattribution a reading
    error rather than an honest mistake.
    """
    block = context.get("peer_comparison")
    if not isinstance(block, dict):
        return ""
    peers = block.get("peers") or []
    if not peers:
        return ""

    target = block.get("target", "the target")
    lines = [
        f"## {PEER_HEADING}",
        f"The rows below are OTHER symbols analysed in the same run. They are "
        f"provided for relative-strength context only. None of these figures "
        f"belong to {target}.",
        "",
    ]
    for peer in peers:
        if not isinstance(peer, dict):
            continue
        symbol = peer.get("symbol", "?")
        name = peer.get("name") or symbol
        sector = f" [{peer['sector']}]" if peer.get("sector") else ""
        price = peer.get("price")
        price_str = (
            f"${price:,.2f} {peer.get('provenance', '')}".strip()
            if isinstance(price, (int, float))
            else "price unavailable"
        )
        if peer.get("status") and peer["status"] not in ("fresh", "refreshed"):
            price_str += f" [{str(peer['status']).upper()}]"
        trend = peer.get("trend_pct")
        trend_str = (
            f", {trend:+.2f}% over its last {peer.get('trend_bars', 0)} bars"
            if isinstance(trend, (int, float))
            else ""
        )
        lines.append(f"- {symbol} ({name}){sector}: {price_str}{trend_str}")

    return "\n".join(lines)


def partition_by_freshness(
    symbols: list[str],
    context: dict[str, Any],
) -> tuple[list[str], list[tuple[str, str]]]:
    """Split *symbols* into ones safe to analyse and ones to drop.

    A symbol whose reconciled snapshot is not ``fresh``/``refreshed`` cannot
    support entry, stop or target levels, so it is dropped from the deep dive
    rather than analysed on months-old prices.

    Returns:
        ``(usable, dropped)`` where *dropped* is a list of
        ``(symbol, reason)`` pairs suitable for logging.
    """
    usable: list[str] = []
    dropped: list[tuple[str, str]] = []

    for symbol in symbols:
        freshness = resolve_snapshot(context, symbol)
        if is_usable(freshness):
            usable.append(symbol)
            continue
        if not freshness:
            reason = "no price snapshot in context"
        else:
            status = freshness.get("status", "unknown")
            detail = freshness.get("reason") or "no reason recorded"
            age = freshness.get("age_days")
            age_str = f", {age}d old" if age is not None else ""
            bar = freshness.get("latest_bar_date") or "unknown date"
            reason = f"status={status} (last bar {bar}{age_str}): {detail}"
        logger.warning(
            "Dropping %s from analysis -- unusable price data: %s", symbol, reason,
        )
        dropped.append((symbol, reason))

    return usable, dropped
