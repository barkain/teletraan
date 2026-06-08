"""Tests for news intelligence scoring, trend, vacuum, events, formatting."""

from datetime import datetime, timedelta, timezone

from analysis.news_intelligence import (
    _MACRO_TOPIC_LABELS,
    classify_event,
    compute_symbol_news_intelligence,
    detect_news_vacuum,
    format_macro_news_context,
    format_news_context,
    score_articles,
)
from data.adapters.news import NewsAdapter


def _article(headline, summary="", days_ago=1):
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "headline": headline,
        "summary": summary,
        "url": f"https://x.com/{abs(hash(headline)) % 10000}",
        "source": "Test",
        "published_at": dt.isoformat(),
        "symbols": ["TEST"],
    }


def test_classify_event_multi():
    assert "earnings" in classify_event("Q3 revenue beats guidance")
    assert "analyst_action" in classify_event("Goldman upgrade, price target raised")
    assert "regulatory" in classify_event("FDA approval granted after probe")
    assert "m_and_a" in classify_event("announces acquisition to buy rival")
    assert classify_event("nothing notable here") == []


def test_score_articles_attaches_sentiment_and_events():
    arts = [_article("Company beats earnings, stock soars to record high")]
    scored = score_articles(arts)
    assert scored[0]["sentiment_score"] > 0.2
    assert scored[0]["sentiment_label"] == "POSITIVE"
    assert "earnings" in scored[0]["events"]
    # original not mutated
    assert "sentiment_score" not in arts[0]


def test_compute_intelligence_positive_vs_negative():
    pos = compute_symbol_news_intelligence(
        "AAA", [_article("stock soars to record high on strong profit beat")]
    )
    neg = compute_symbol_news_intelligence(
        "BBB", [_article("shares plunge on fraud lawsuit and bankruptcy fears")]
    )
    assert pos["label"] == "POSITIVE" and pos["sentiment_score"] > 0
    assert neg["label"] == "NEGATIVE" and neg["sentiment_score"] < 0
    assert pos["top_article"]["headline"]


def test_empty_coverage_is_neutral_stable():
    intel = compute_symbol_news_intelligence("ZZZ", [])
    assert intel["sentiment_score"] == 0.0
    assert intel["label"] == "NEUTRAL"
    assert intel["trend"] == "STABLE"
    assert intel["article_count"] == 0
    assert intel["top_article"] is None


def test_trend_improving_when_recent_more_positive():
    # Older half negative, recent half positive -> IMPROVING.
    arts = [
        _article("disaster plunge loss crash", days_ago=6),
        _article("terrible decline miss weak", days_ago=5),
        _article("record high soars beats strong", days_ago=1),
        _article("surges rally gains upgrade profit", days_ago=0),
    ]
    intel = compute_symbol_news_intelligence("AAA", arts, days=7)
    assert intel["trend"] == "IMPROVING"


def test_trend_stable_with_too_few_articles():
    intel = compute_symbol_news_intelligence("AAA", [_article("soars high")], days=7)
    assert intel["trend"] == "STABLE"


def test_detect_news_vacuum():
    by_symbol = {
        "AAA": {"article_count": 5},
        "BBB": {"article_count": 1},
        "CCC": {"article_count": 0},
    }
    assert detect_news_vacuum(by_symbol) == ["BBB", "CCC"]


def test_every_macro_query_topic_has_a_label():
    # The adapter tags articles with macro_topic keys; the intelligence layer
    # must have a display label for each, or topics silently vanish from output.
    for topic in NewsAdapter._MACRO_QUERIES:
        assert topic in _MACRO_TOPIC_LABELS


def test_format_macro_news_context_renders_and_empties():
    assert format_macro_news_context(None) == ""
    assert format_macro_news_context({"article_count": 0}) == ""
    macro = {
        "sentiment_score": -0.2, "label": "NEGATIVE", "article_count": 25,
        "by_topic": {
            "monetary_policy": {"label": "Monetary Policy / Fed", "article_count": 6,
                                 "sentiment_score": -0.3, "sentiment_label": "NEGATIVE",
                                 "top_headline": {"headline": "Fed signals more hikes", "source": "WSJ"}},
            "geopolitical": {"label": "Geopolitical", "article_count": 4,
                              "sentiment_score": -0.5, "sentiment_label": "NEGATIVE",
                              "top_headline": {"headline": "Conflict escalates", "source": "Reuters"}},
        },
    }
    out = format_macro_news_context(macro)
    assert "## Macro-Economic News" in out
    assert "Monetary Policy / Fed: -0.30 (NEGATIVE)" in out
    assert "Fed signals more hikes" in out
    assert "Geopolitical: -0.50 (NEGATIVE)" in out


def test_format_news_context_renders_and_empties():
    assert format_news_context(None) == ""
    assert format_news_context({"per_symbol": [], "market": {}, "vacuum": []}) == ""
    intel = {
        "market": {"sentiment_score": 0.3, "label": "POSITIVE", "article_count": 10,
                   "trend": "IMPROVING", "top_headlines": []},
        "per_symbol": [{
            "symbol": "NVDA", "sentiment_score": 0.5, "label": "POSITIVE",
            "article_count": 8, "trend": "IMPROVING", "events": ["earnings"],
            "top_article": {"headline": "NVDA beats", "source": "Reuters"},
        }],
        "vacuum": ["XYZ"],
    }
    out = format_news_context(intel)
    assert "## News Sentiment" in out
    assert "NVDA: +0.50 (POSITIVE)" in out
    assert "News Vacuum" in out and "XYZ" in out
    assert "Market News Tone" in out
