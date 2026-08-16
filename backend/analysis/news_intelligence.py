"""News intelligence — score financial news headlines into per-symbol signals.

Turns raw articles (from ``data.adapters.news``) into the structured news
sentiment the analysis pipeline consumes, per issue #20:

- per-symbol sentiment score + label (FinVADER via the existing SentimentScorer)
- sentiment momentum/trend (IMPROVING / STABLE / DETERIORATING)
- event classification (earnings / analyst_action / regulatory / M&A / product / macro)
- news-vacuum detection (symbols with sparse coverage — potential surprises)
- ``format_news_context`` renders the LLM-prompt block the synthesis agents read

Records carry a ``data_status`` (``ok`` / ``empty`` / ``error``) and an
``available`` flag propagated from the adapter, because "the feed failed" and
"there was genuinely no news" are different facts: only the second is a quiet
tape. A failed fetch must never surface as NEUTRAL sentiment and must never be
counted as a news vacuum — that would turn an outage into a tradeable signal.

This is a scoring augmentation for the deep analysis, not a user-facing feed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from analysis.sentiment.scorer import get_sentiment_scorer  # type: ignore[import-not-found]
from data.adapters.news import (  # type: ignore[import-not-found]
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_OK,
    get_news_adapter,
)

logger = logging.getLogger(__name__)

# Sentiment label thresholds on the [-1, +1] compound score.
_POSITIVE = 0.15
_NEGATIVE = -0.15

# A symbol with fewer than this many articles in-window is a "news vacuum".
_VACUUM_THRESHOLD = 2

# Recency weighting: an article's weight decays linearly to this floor over the
# window, so fresh headlines dominate the aggregate score.
_RECENCY_FLOOR = 0.3

# Keyword → event-type classifier. Order matters only for readability; an
# article can carry multiple event types.
_EVENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "earnings": (
        "earnings", "revenue", "eps", "quarterly results", "guidance", "beats",
        "misses", "profit", "q1", "q2", "q3", "q4", "outlook", "forecast",
    ),
    "analyst_action": (
        "upgrade", "downgrade", "price target", "initiates coverage", "rating",
        "overweight", "underweight", "outperform", "underperform", "buy rating",
        "sell rating", "analyst", "raised to", "cut to",
    ),
    "regulatory": (
        "sec ", "fda ", "investigation", "lawsuit", "antitrust", "regulator",
        "probe", "fine", "settlement", "approval", "subpoena", "recall", "ftc",
    ),
    "m_and_a": (
        "acquisition", "acquire", "merger", "takeover", "buyout", "to buy",
        "stake in", "deal to", "bid for", "spin-off", "spinoff",
    ),
    "product": (
        "launch", "unveil", "announces", "rollout", "partnership", "contract",
        "new product", "release", "debut", "expands",
    ),
    "macro": (
        "federal reserve", "fed ", "inflation", "interest rate", "tariff",
        "gdp", "jobs report", "cpi", "recession", "yields",
    ),
}


def classify_event(text: str) -> list[str]:
    """Return the event types a headline/summary matches (possibly several)."""
    lowered = f" {text.lower()} "
    types: list[str] = []
    for event_type, keywords in _EVENT_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            types.append(event_type)
    return types


def _label(score: float) -> str:
    if score >= _POSITIVE:
        return "POSITIVE"
    if score <= _NEGATIVE:
        return "NEGATIVE"
    return "NEUTRAL"


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _recency_weight(published_at: str | None, now: datetime, days: int) -> float:
    """Linear-decay weight in [_RECENCY_FLOOR, 1.0]; undated articles get the floor."""
    dt = _parse_dt(published_at)
    if dt is None or days <= 0:
        return _RECENCY_FLOOR
    age_days = max((now - dt).total_seconds() / 86400, 0.0)
    frac = max(0.0, 1.0 - age_days / days)
    return _RECENCY_FLOOR + (1.0 - _RECENCY_FLOOR) * frac


def score_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach sentiment_score, sentiment_label and events to each article.

    Returns a new list (input dicts are not mutated). Articles are scored on
    headline + summary text via the shared FinVADER scorer.
    """
    scorer = get_sentiment_scorer()
    scored: list[dict[str, Any]] = []
    for a in articles:
        text = f"{a.get('headline', '')}. {a.get('summary', '')}".strip()
        score = round(scorer.score_text(text), 4)
        scored.append({
            **a,
            "sentiment_score": score,
            "sentiment_label": _label(score),
            "events": classify_event(text),
        })
    return scored


def unavailable_record(symbol: str, reason: str = "fetch failed") -> dict[str, Any]:
    """A record meaning "we could not read the news", not "the news was neutral".

    ``sentiment_score`` is None rather than 0.0 so no consumer can average or
    threshold an outage into a signal, and the label is UNAVAILABLE rather than
    NEUTRAL. ``available`` is the flag callers should branch on.
    """
    return {
        "symbol": symbol.upper(),
        "sentiment_score": None,
        "label": "UNAVAILABLE",
        "article_count": 0,
        "trend": "UNKNOWN",
        "events": [],
        "top_article": None,
        "articles": [],
        "data_status": STATUS_ERROR,
        "available": False,
        "unavailable_reason": reason,
    }


def compute_symbol_news_intelligence(
    symbol: str,
    articles: list[dict[str, Any]],
    days: int = 7,
    status: str = STATUS_OK,
) -> dict[str, Any]:
    """Aggregate a symbol's articles into a news-intelligence record.

    Returns keys: symbol, sentiment_score, label, article_count, trend,
    events, top_article, articles (scored, newest first), plus data_status and
    available. Empty *successful* coverage yields a zeroed record with trend
    STABLE; a *failed* fetch (``status=STATUS_ERROR``) yields an unavailable
    record instead — see ``unavailable_record``.
    """
    symbol = symbol.upper()
    if status == STATUS_ERROR:
        return unavailable_record(symbol)

    scored = score_articles(articles)
    if not scored:
        return {
            "symbol": symbol,
            "sentiment_score": 0.0,
            "label": "NEUTRAL",
            "article_count": 0,
            "trend": "STABLE",
            "events": [],
            "top_article": None,
            "articles": [],
            "data_status": STATUS_EMPTY,
            "available": True,
        }

    now = datetime.now(timezone.utc)
    weights = [_recency_weight(a.get("published_at"), now, days) for a in scored]
    total_w = sum(weights) or 1.0
    agg_score = round(
        sum(a["sentiment_score"] * w for a, w in zip(scored, weights)) / total_w, 4
    )

    # Aggregate distinct event types across all articles.
    events: list[str] = []
    for a in scored:
        for ev in a["events"]:
            if ev not in events:
                events.append(ev)

    # Top article = strongest-signal headline (largest |sentiment|), tie-break newest.
    def _top_key(a: dict[str, Any]) -> tuple[float, datetime]:
        dt = _parse_dt(a.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc)
        return (abs(a["sentiment_score"]), dt)

    top = max(scored, key=_top_key)

    return {
        "symbol": symbol,
        "sentiment_score": agg_score,
        "label": _label(agg_score),
        "article_count": len(scored),
        "trend": _compute_trend(scored, now),
        "events": events,
        "top_article": {
            "headline": top["headline"],
            "source": top["source"],
            "url": top["url"],
            "sentiment_score": top["sentiment_score"],
        },
        "articles": scored,
        "data_status": STATUS_OK,
        "available": True,
    }


def _compute_trend(scored: list[dict[str, Any]], now: datetime) -> str:
    """Sentiment momentum: recent-half avg vs older-half avg.

    Splits dated articles at the window midpoint by age and compares mean
    sentiment. Needs >=2 dated articles on each side to call a direction;
    otherwise STABLE.
    """
    dated = [(a, _parse_dt(a.get("published_at"))) for a in scored]
    dated = [(a, dt) for a, dt in dated if dt is not None]
    if len(dated) < 4:
        return "STABLE"
    dated.sort(key=lambda t: t[1], reverse=True)  # newest first
    mid = len(dated) // 2
    recent = [a["sentiment_score"] for a, _ in dated[:mid]]
    older = [a["sentiment_score"] for a, _ in dated[mid:]]
    if len(recent) < 2 or len(older) < 2:
        return "STABLE"
    delta = (sum(recent) / len(recent)) - (sum(older) / len(older))
    if delta > 0.1:
        return "IMPROVING"
    if delta < -0.1:
        return "DETERIORATING"
    return "STABLE"


def detect_news_vacuum(
    intelligence_by_symbol: dict[str, dict[str, Any]],
    threshold: int = _VACUUM_THRESHOLD,
) -> list[str]:
    """Symbols with sparse coverage (< threshold articles) — surprise risk.

    Symbols whose feed failed are excluded: a vacuum is a claim about the world
    (nobody is writing about this name), and an outage is no evidence for it.
    Records without a status are assumed fetched, so pre-status callers are
    unaffected.
    """
    return sorted(
        sym for sym, intel in intelligence_by_symbol.items()
        if intel.get("available", True)
        and intel.get("data_status", STATUS_OK) != STATUS_ERROR
        and intel.get("article_count", 0) < threshold
    )


def _is_unavailable(record: dict[str, Any] | None) -> bool:
    """True when *record* represents a failed fetch rather than a reading."""
    if not record:
        return False
    return record.get("data_status") == STATUS_ERROR or record.get("available") is False


def unavailable_symbols(
    intelligence_by_symbol: dict[str, dict[str, Any]],
) -> list[str]:
    """Symbols whose news feed failed — coverage unknown, not zero."""
    return sorted(
        sym for sym, intel in intelligence_by_symbol.items()
        if intel.get("data_status") == STATUS_ERROR or intel.get("available") is False
    )


async def get_news_intelligence(
    symbols: list[str],
    days: int = 7,
    limit_per_symbol: int = 15,
) -> dict[str, Any]:
    """Fetch + score news for *symbols* and the market. The pipeline entry point.

    Returns a persistable dict: {as_of, market, per_symbol, vacuum, unavailable}.
    ``vacuum`` lists only symbols we successfully checked; ``unavailable`` lists
    symbols whose feed failed.
    """
    adapter = get_news_adapter()
    uniq = list(dict.fromkeys(s.upper().strip() for s in symbols if s and s.strip()))

    news_by_symbol, market = await _gather(adapter, uniq, days, limit_per_symbol)

    per_symbol: dict[str, dict[str, Any]] = {
        sym: compute_symbol_news_intelligence(
            sym,
            record.get("articles") or [],
            days=days,
            status=record.get("status", STATUS_OK),
        )
        for sym, record in news_by_symbol.items()
    }
    vacuum = detect_news_vacuum(per_symbol)
    unavailable = unavailable_symbols(per_symbol)
    if unavailable:
        logger.warning("News feed unavailable for %s", ", ".join(unavailable))
    market_intel = compute_symbol_news_intelligence(
        "MARKET",
        market.get("articles") or [],
        days=days,
        status=market.get("status", STATUS_OK),
    )

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "market": {
            "sentiment_score": market_intel["sentiment_score"],
            "label": market_intel["label"],
            "article_count": market_intel["article_count"],
            "trend": market_intel["trend"],
            "data_status": market_intel["data_status"],
            "available": market_intel["available"],
            "top_headlines": [
                {"headline": a["headline"], "source": a["source"],
                 "sentiment_label": a["sentiment_label"]}
                for a in market_intel["articles"][:5]
            ],
        },
        "per_symbol": [per_symbol[s] for s in uniq if s in per_symbol],
        "vacuum": vacuum,
        "unavailable": unavailable,
    }


_MACRO_TOPIC_LABELS: dict[str, str] = {
    "monetary_policy": "Monetary Policy / Fed",
    "inflation": "Inflation",
    "employment": "Employment",
    "growth": "Growth / Recession",
    "trade": "Trade / Tariffs",
    "rates": "Rates / Yields",
    "geopolitical": "Geopolitical",
}


async def get_macro_news_intelligence(days: int = 3, limit: int = 40) -> dict[str, Any]:
    """Fetch + score macro-economic news into a regime-relevant signal.

    Returns {as_of, sentiment_score, label, article_count, by_topic,
    top_headlines, data_status, available}. by_topic maps each macro topic ->
    {label, article_count, sentiment_score, sentiment_label, top_headline}.
    Best-effort: the adapter never raises. A failed fetch returns an
    UNAVAILABLE record (score None) rather than a NEUTRAL zero, so an outage
    cannot be read as a calm macro backdrop.
    """
    adapter = get_news_adapter()
    fetched = await adapter.get_macro_news_with_status(days=days, limit=limit)
    status = fetched.get("status", STATUS_OK)

    if status == STATUS_ERROR:
        logger.warning("Macro news feed unavailable — reporting UNAVAILABLE, not neutral")
        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "sentiment_score": None,
            "label": "UNAVAILABLE",
            "article_count": 0,
            "by_topic": {},
            "top_headlines": [],
            "data_status": STATUS_ERROR,
            "available": False,
        }

    scored = score_articles(fetched.get("articles") or [])

    if not scored:
        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "sentiment_score": 0.0,
            "label": "NEUTRAL",
            "article_count": 0,
            "by_topic": {},
            "top_headlines": [],
            "data_status": STATUS_EMPTY,
            "available": True,
        }

    now = datetime.now(timezone.utc)
    weights = [_recency_weight(a.get("published_at"), now, days) for a in scored]
    total_w = sum(weights) or 1.0
    agg = round(sum(a["sentiment_score"] * w for a, w in zip(scored, weights)) / total_w, 4)

    by_topic: dict[str, Any] = {}
    for topic, label in _MACRO_TOPIC_LABELS.items():
        topic_arts = [a for a in scored if a.get("macro_topic") == topic]
        if not topic_arts:
            continue
        t_score = round(sum(a["sentiment_score"] for a in topic_arts) / len(topic_arts), 4)
        top = max(topic_arts, key=lambda a: abs(a["sentiment_score"]))
        by_topic[topic] = {
            "label": label,
            "article_count": len(topic_arts),
            "sentiment_score": t_score,
            "sentiment_label": _label(t_score),
            "top_headline": {"headline": top["headline"], "source": top["source"]},
        }

    top_headlines = sorted(scored, key=lambda a: abs(a["sentiment_score"]), reverse=True)[:6]
    return {
        "as_of": now.isoformat(),
        "sentiment_score": agg,
        "label": _label(agg),
        "article_count": len(scored),
        "by_topic": by_topic,
        "data_status": STATUS_OK,
        "available": True,
        "top_headlines": [
            {"headline": a["headline"], "source": a["source"],
             "sentiment_label": a["sentiment_label"],
             "topic": _MACRO_TOPIC_LABELS.get(a.get("macro_topic", ""), "")}
            for a in top_headlines
        ],
    }


def format_macro_news_context(macro: dict[str, Any] | None) -> str:
    """Render macro-news intelligence into a markdown block for the MacroScanner.

    Returns '' when there is no usable data so the caller can omit the section,
    except on a fetch failure, which is stated explicitly — silently rendering
    nothing there would let the model assume a quiet macro tape.
    """
    if not macro:
        return ""
    if macro.get("data_status") == STATUS_ERROR or macro.get("available") is False:
        return (
            "## Macro-Economic News\n"
            "**Macro news feed UNAVAILABLE** — the headline fetch failed for this run. "
            "Macro-news tone is UNKNOWN, not neutral: do not infer a calm news "
            "backdrop from its absence, and do not let it move regime confidence."
        )
    if not macro.get("article_count"):
        return ""
    lines = [
        "## Macro-Economic News",
        f"**Overall macro-news tone:** {macro.get('label', 'NEUTRAL')} "
        f"(score {macro.get('sentiment_score', 0):+.2f}, {macro.get('article_count', 0)} articles)",
    ]
    by_topic = macro.get("by_topic") or {}
    if by_topic:
        lines.append("**By topic:**")
        for topic in _MACRO_TOPIC_LABELS:
            t = by_topic.get(topic)
            if not t:
                continue
            line = (
                f"- {t['label']}: {t['sentiment_score']:+.2f} ({t['sentiment_label']}) | "
                f"{t['article_count']} articles"
            )
            head = (t.get("top_headline") or {}).get("headline")
            if head:
                line += f" | \"{head}\""
            lines.append(line)
    return "\n".join(lines)


async def _gather(adapter: Any, symbols: list[str], days: int, limit_per_symbol: int):
    """Fetch per-symbol and market news as status-bearing records."""
    import asyncio
    news_by_symbol, market = await asyncio.gather(
        adapter.get_company_news_batch_with_status(
            symbols, days=days, limit_per_symbol=limit_per_symbol
        )
        if symbols else _empty_dict(),
        adapter.get_market_news_with_status(days=min(days, 3)),
    )
    return news_by_symbol, market


async def _empty_dict() -> dict[str, Any]:
    return {}


# ---------------------------------------------------------------------------
# LLM context formatting (issue #20 output format)
# ---------------------------------------------------------------------------

def format_news_context(intelligence: dict[str, Any] | None, max_symbols: int = 12) -> str:
    """Render a news-intelligence dict into a markdown block for analyst prompts.

    Matches the issue #20 spec: per-symbol sentiment + trend + top headline,
    plus a news-vacuum callout. Returns '' when there is no usable data so
    callers can omit the section.
    """
    if not intelligence:
        return ""

    lines: list[str] = []
    market = intelligence.get("market") or {}
    if _is_unavailable(market):
        lines.append(
            "**Market News Tone:** UNAVAILABLE — the market-news fetch failed. "
            "Tone is unknown, not neutral; do not weigh it either way."
        )
    elif market.get("article_count"):
        lines.append(
            f"**Market News Tone:** {market.get('label', 'NEUTRAL')} "
            f"(score {market.get('sentiment_score', 0):+.2f}, "
            f"{market.get('article_count', 0)} articles, trend {market.get('trend', 'STABLE')})"
        )
        for h in market.get("top_headlines", [])[:3]:
            lines.append(f"  - [{h.get('sentiment_label', 'NEUTRAL')}] {h.get('headline', '')} ({h.get('source', '')})")

    # Accept per_symbol as a list (pipeline shape) or a {SYMBOL: record} dict
    # (context_builder re-keys it for O(1) lookup) so either caller is safe.
    raw_per_symbol = intelligence.get("per_symbol", [])
    if isinstance(raw_per_symbol, dict):
        raw_per_symbol = list(raw_per_symbol.values())
    records = [s for s in raw_per_symbol if isinstance(s, dict)]
    unavailable = [str(s.get("symbol") or "?") for s in records if _is_unavailable(s)]
    per_symbol = [
        s for s in records if not _is_unavailable(s) and s.get("article_count")
    ]
    if per_symbol:
        lines.append("")
        lines.append("**Per-Symbol News Sentiment (recent window):**")
        for intel in per_symbol[:max_symbols]:
            ev = f" | events: {', '.join(intel['events'])}" if intel.get("events") else ""
            lines.append(
                f"- {intel['symbol']}: {intel['sentiment_score']:+.2f} ({intel['label']}) | "
                f"{intel['article_count']} articles | trend: {intel['trend']}{ev}"
            )
            top = intel.get("top_article")
            if top and top.get("headline"):
                lines.append(f"    Top: \"{top['headline']}\" ({top.get('source', '')})")

    if unavailable:
        lines.append("")
        lines.append(
            "**News Feed UNAVAILABLE (fetch failed — coverage unknown, NOT a news "
            "vacuum):** " + ", ".join(unavailable[:20])
        )

    # Never present an unavailable symbol as a vacuum, even if a caller passed a
    # vacuum list built before the statuses were known.
    vacuum = [s for s in (intelligence.get("vacuum") or []) if s not in unavailable]
    if vacuum:
        lines.append("")
        lines.append(
            "**News Vacuum (sparse coverage — potential catalyst surprise):** "
            + ", ".join(vacuum[:20])
        )

    if not lines:
        return ""
    return "## News Sentiment (financial headlines)\n" + "\n".join(lines)
