"""Price freshness contract shared by the context builder and analyst formatters.

Analyst prompts used to print stored closing prices under the label
``Current Price`` with no date attached.  When the ETL had not run for weeks the
analysts were handed a price that was months old and had no way to tell.  This
module defines the single vocabulary both sides use:

* ``build_freshness`` — construct a per-symbol freshness record.
* ``resolve_snapshot`` — read the reconciled snapshot back out of a market-data
  context (deriving one on the fly when the context predates this contract).
* ``price_line`` / ``describe`` — render a price with its date, age and source
  so a stale number can never masquerade as a current one.

The records live in ``context["price_freshness"]``, keyed by symbol, mirroring
``price_history`` / ``rich_technical`` / ``fundamentals`` so a per-symbol slice
of the context carries the freshness along with the data it describes.

Only stdlib imports here — this module is imported by both ``context_builder``
and the ``analysis.agents.*`` formatters and must not create an import cycle.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

# A bar is considered current if it is no more than this many *trading* days
# behind the evaluation date.  Two days tolerates a same-day run before the
# close plus one missed overnight ETL cycle; anything older is a data outage.
STALE_AFTER_TRADING_DAYS = 2

# Status values (also documented in the module docstring of context_builder).
STATUS_FRESH = "fresh"
STATUS_REFRESHED = "refreshed"
STATUS_STALE = "stale"
STATUS_MISSING = "missing"

# Human-readable names for the provenance of a price snapshot.
SOURCE_LABELS = {
    "db_close": "DB close",
    "live_quote": "live quote",
    "yfinance_history": "yfinance daily bar",
}


def lookup_symbol(block: Any, symbol: str) -> Any:
    """Case-insensitive fetch of *symbol* from a symbol-keyed context block.

    Ticker case is not carried consistently across the pipeline: the context
    builder stores every block under the upper-case symbol, while candidate
    lists can arrive straight out of an LLM's JSON in whatever case the model
    chose.  An exact-key lookup here reads a healthy context as "no price data"
    and drops the symbol, so every read of a symbol-keyed block normalises.
    """
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


def coerce_date(value: Any) -> date | None:
    """Best-effort conversion of a bar/quote date into a ``date``.

    Accepts ``date``, ``datetime``, and ISO-ish strings (``YYYY-MM-DD`` with an
    optional time suffix).  Returns ``None`` when the value cannot be parsed.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def last_weekday(day: date) -> date:
    """Return *day* itself, or the preceding Friday when *day* is a weekend.

    A live quote pulled on a Saturday reflects Friday's close; dating it
    "today" would overstate its freshness.
    """
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def trading_days_between(start: date, end: date) -> int:
    """Count weekdays in the half-open interval ``(start, end]``.

    Exchange holidays are not modelled — this is a staleness heuristic, and
    over-counting by a holiday only makes it marginally more conservative.
    """
    if end <= start:
        return 0
    total_days = (end - start).days
    full_weeks, remainder = divmod(total_days, 7)
    count = full_weeks * 5
    cursor = start + timedelta(days=full_weeks * 7)
    for _ in range(remainder):
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            count += 1
    return count


def build_freshness(
    symbol: str,
    snapshot_date: Any,
    price: float | None,
    source: str,
    as_of: date | None = None,
    refreshed: bool = False,
    reason: str | None = None,
) -> dict[str, Any]:
    """Build a freshness record for one symbol.

    Args:
        symbol: Ticker symbol.
        snapshot_date: Date the price is valid for (bar date or quote date).
        price: The price the snapshot carries, if any.
        source: One of the keys of :data:`SOURCE_LABELS`.
        as_of: Evaluation date; defaults to today (UTC).
        refreshed: True when the snapshot came from a live refresh triggered
            because the stored history was behind.
        reason: Optional explanation, surfaced in prompts for stale/missing.

    Returns:
        Dict with ``symbol``, ``status``, ``latest_bar_date``, ``age_days``,
        ``trading_age_days``, ``price``, ``source``, ``as_of`` and ``reason``.
    """
    as_of = as_of or datetime.utcnow().date()
    bar_date = coerce_date(snapshot_date)

    if bar_date is None or price is None:
        return {
            "symbol": symbol,
            "status": STATUS_MISSING,
            "latest_bar_date": bar_date.isoformat() if bar_date else None,
            "age_days": None,
            "trading_age_days": None,
            "price": price,
            "source": source,
            "as_of": as_of.isoformat(),
            "reason": reason or "no price data available",
        }

    age_days = max((as_of - bar_date).days, 0)
    trading_age = trading_days_between(bar_date, as_of)

    if trading_age > STALE_AFTER_TRADING_DAYS:
        status = STATUS_STALE
    elif refreshed:
        status = STATUS_REFRESHED
    else:
        status = STATUS_FRESH

    return {
        "symbol": symbol,
        "status": status,
        "latest_bar_date": bar_date.isoformat(),
        "age_days": age_days,
        "trading_age_days": trading_age,
        "price": price,
        "source": source,
        "as_of": as_of.isoformat(),
        "reason": reason,
    }


def missing_freshness(symbol: str, reason: str, as_of: date | None = None) -> dict[str, Any]:
    """Freshness record for a symbol with no usable price data at all."""
    return build_freshness(symbol, None, None, "db_close", as_of=as_of, reason=reason)


def is_usable(freshness: dict[str, Any] | None) -> bool:
    """True when the snapshot may be presented to an analyst as the current price."""
    return bool(freshness) and freshness.get("status") in (STATUS_FRESH, STATUS_REFRESHED)


def describe(freshness: dict[str, Any] | None) -> str:
    """Render the parenthetical provenance suffix, e.g.
    ``(as of 2026-08-08, 1d old, source: DB close)``."""
    if not freshness:
        return "(date unknown)"
    bar_date = freshness.get("latest_bar_date")
    if not bar_date:
        return "(no price data)"
    age = freshness.get("age_days")
    source = SOURCE_LABELS.get(freshness.get("source", ""), freshness.get("source") or "unknown")
    age_str = f"{age}d old" if age is not None else "age unknown"
    return f"(as of {bar_date}, {age_str}, source: {source})"


def price_line(
    freshness: dict[str, Any] | None,
    label: str = "Last Close",
    price: float | None = None,
) -> str:
    """Render one dated price line.

    Fresh/refreshed snapshots read ``Last Close: $123.45 (as of ..., 1d old,
    source: ...)``.  Stale snapshots keep the number but carry an explicit
    warning so the LLM cannot read it as the live price; missing snapshots say
    so outright.  Never emits the bare words "Current Price" or "Today's".
    """
    if not freshness:
        return f"{label}: unavailable (no price data)"

    value = price if price is not None else freshness.get("price")
    status = freshness.get("status")

    if status == STATUS_MISSING or value is None:
        reason = freshness.get("reason") or "no price data available"
        return f"{label}: UNAVAILABLE -- {reason}"

    base = f"{label}: ${value:,.2f} {describe(freshness)}"
    if status == STATUS_STALE:
        reason = freshness.get("reason") or "live quote unavailable"
        return (
            f"{base} [STALE -- this is NOT the current price; {reason}. "
            "Do not derive entry, stop or target levels from it]"
        )
    return base


def stale_warning(freshness: dict[str, Any] | None) -> str:
    """One-line banner for a stale/missing symbol, or ``""`` when usable."""
    if not freshness or is_usable(freshness):
        return ""
    status = freshness.get("status")
    symbol = freshness.get("symbol", "symbol")
    if status == STATUS_MISSING:
        return f"!! {symbol}: NO PRICE DATA -- do not quote price levels for this symbol."
    age = freshness.get("age_days")
    age_str = f"{age} days" if age is not None else "an unknown period"
    return (
        f"!! {symbol}: PRICE DATA IS STALE by {age_str} and could not be refreshed. "
        "Treat every price below as historical, not current."
    )


def derive_freshness(market_data: dict[str, Any], symbol: str) -> dict[str, Any] | None:
    """Derive a snapshot from raw context when no freshness record exists.

    Formatters are also called with hand-built market-data dicts (legacy call
    sites and tests) that never went through the context builder.  Rather than
    fall back to an undated price, reconstruct the record from whatever dated
    data is present, preferring the most recent of the stored bar and the
    yfinance-sourced rich-TA snapshot.
    """
    candidates: list[dict[str, Any]] = []

    bars = lookup_symbol(market_data.get("price_history"), symbol) or []
    if bars:
        latest = bars[0]
        bar_date = coerce_date(latest.get("date"))
        close = latest.get("close")
        if bar_date is not None and close is not None:
            candidates.append({
                "date": bar_date,
                "price": float(close),
                "source": latest.get("source") or "db_close",
            })

    rich = lookup_symbol(market_data.get("rich_technical"), symbol) or {}
    rich_date = coerce_date(rich.get("latest_date"))
    rich_price = rich.get("latest_price")
    if rich_date is not None and rich_price is not None:
        candidates.append({
            "date": rich_date,
            "price": float(rich_price),
            "source": "yfinance_history",
        })

    if not candidates:
        return None

    best = max(candidates, key=lambda c: c["date"])
    return build_freshness(symbol, best["date"], best["price"], best["source"])


def resolve_snapshot(market_data: dict[str, Any], symbol: str) -> dict[str, Any] | None:
    """Return the reconciled price snapshot for *symbol*.

    Reads ``market_data["price_freshness"][symbol]`` when the context builder
    produced one, otherwise derives it from the dated data in the context.

    The recorded value is still checked against the yfinance-sourced rich-TA
    snapshot: a caller can attach ``rich_technical`` to a context the builder
    already reconciled, and the formatters must not end up quoting the older
    of the two prices in one section and the newer one in the next.
    """
    recorded = lookup_symbol(market_data.get("price_freshness"), symbol)
    if not recorded:
        return derive_freshness(market_data, symbol)

    rich = lookup_symbol(market_data.get("rich_technical"), symbol) or {}
    return reconcile(
        recorded, symbol, rich.get("latest_date"), rich.get("latest_price"),
        "yfinance_history",
    )


def snapshot_price(market_data: dict[str, Any], symbol: str) -> tuple[float, dict[str, Any] | None]:
    """Return ``(price, freshness)`` for *symbol*; price is ``0.0`` when unknown.

    This is the single price every derived technical (ATR %, distance to moving
    average, risk sizing) should be computed against, so the prompt cannot show
    a DB-sourced price next to a yfinance-sourced one.
    """
    freshness = resolve_snapshot(market_data, symbol)
    if not freshness:
        return 0.0, None
    price = freshness.get("price")
    return (float(price) if price is not None else 0.0), freshness


def reconcile(
    freshness: dict[str, Any] | None,
    symbol: str,
    snapshot_date: Any,
    price: float | None,
    source: str,
) -> dict[str, Any] | None:
    """Return whichever of *freshness* and the offered snapshot is more recent.

    Used to fold the yfinance-sourced rich-TA price into the record built from
    the stored bars so a single snapshot feeds the whole prompt.
    """
    candidate_date = coerce_date(snapshot_date)
    if candidate_date is None or price is None:
        return freshness

    existing_date = coerce_date(freshness.get("latest_bar_date")) if freshness else None
    if existing_date is not None and existing_date >= candidate_date:
        return freshness

    return build_freshness(
        symbol,
        candidate_date,
        float(price),
        source,
        refreshed=bool(freshness) and freshness.get("status") in (STATUS_STALE, STATUS_REFRESHED),
    )
