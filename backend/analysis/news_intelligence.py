"""News intelligence — score financial news headlines into per-symbol signals.

Turns raw articles (from ``data.adapters.news``) into the structured news
sentiment the analysis pipeline consumes, per issue #20:

- per-symbol sentiment score + label (FinVADER via the existing SentimentScorer)
- sentiment momentum/trend (IMPROVING / STABLE / DETERIORATING)
- event classification (earnings / analyst_action / regulatory / M&A / product / macro)
- news-vacuum detection (symbols with sparse coverage — potential surprises)
- ``format_news_context`` renders the LLM-prompt block the synthesis agents read

This is a scoring augmentation for the deep analysis, not a user-facing feed.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from analysis.sentiment.scorer import get_sentiment_scorer
from data.adapters.news import get_news_adapter

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


def compute_symbol_news_intelligence(
    symbol: str,
    articles: list[dict[str, Any]],
    days: int = 7,
) -> dict[str, Any]:
    """Aggregate a symbol's articles into a news-intelligence record.

    Returns keys: symbol, sentiment_score, label, article_count, trend,
    events, top_article, articles (scored, newest first). Empty coverage
    yields a zeroed record with trend STABLE.
    """
    symbol = symbol.upper()
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
    """Symbols with sparse coverage (< threshold articles) — surprise risk."""
    return sorted(
        sym for sym, intel in intelligence_by_symbol.items()
        if intel.get("article_count", 0) < threshold
    )


async def get_news_intelligence(
    symbols: list[str],
    days: int = 7,
    limit_per_symbol: int = 15,
) -> dict[str, Any]:
    """Fetch + score news for *symbols* and the market. The pipeline entry point.

    Returns a persistable dict: {as_of, market, per_symbol, vacuum}.
    """
    adapter = get_news_adapter()
    uniq = list(dict.fromkeys(s.upper().strip() for s in symbols if s and s.strip()))

    news_by_symbol, market_articles = await _gather(adapter, uniq, days, limit_per_symbol)

    per_symbol: dict[str, dict[str, Any]] = {
        sym: compute_symbol_news_intelligence(sym, articles, days=days)
        for sym, articles in news_by_symbol.items()
    }
    vacuum = detect_news_vacuum(per_symbol)
    market_intel = compute_symbol_news_intelligence("MARKET", market_articles, days=days)

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "market": {
            "sentiment_score": market_intel["sentiment_score"],
            "label": market_intel["label"],
            "article_count": market_intel["article_count"],
            "trend": market_intel["trend"],
            "top_headlines": [
                {"headline": a["headline"], "source": a["source"],
                 "sentiment_label": a["sentiment_label"]}
                for a in market_intel["articles"][:5]
            ],
        },
        "per_symbol": [per_symbol[s] for s in uniq if s in per_symbol],
        "vacuum": vacuum,
    }


async def _gather(adapter: Any, symbols: list[str], days: int, limit_per_symbol: int):
    import asyncio
    news_by_symbol, market_articles = await asyncio.gather(
        adapter.get_company_news_batch(symbols, days=days, limit_per_symbol=limit_per_symbol)
        if symbols else _empty_dict(),
        adapter.get_market_news(days=min(days, 3)),
    )
    return news_by_symbol, market_articles


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
    if market.get("article_count"):
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
    per_symbol = [s for s in raw_per_symbol if isinstance(s, dict) and s.get("article_count")]
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

    vacuum = intelligence.get("vacuum") or []
    if vacuum:
        lines.append("")
        lines.append(
            "**News Vacuum (sparse coverage — potential catalyst surprise):** "
            + ", ".join(vacuum[:20])
        )

    if not lines:
        return ""
    return "## News Sentiment (financial headlines)\n" + "\n".join(lines)
