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
    unavailable_symbols,
)
from data.adapters.news import STATUS_EMPTY, STATUS_ERROR, STATUS_OK, NewsAdapter


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
    """A genuine zero-news day: sources answered, there was simply nothing."""
    intel = compute_symbol_news_intelligence("ZZZ", [], status=STATUS_EMPTY)
    assert intel["sentiment_score"] == 0.0
    assert intel["label"] == "NEUTRAL"
    assert intel["trend"] == "STABLE"
    assert intel["article_count"] == 0
    assert intel["top_article"] is None
    assert intel["available"] is True
    assert intel["data_status"] == STATUS_EMPTY
    # A quiet tape is still a news vacuum — that behaviour is unchanged.
    assert detect_news_vacuum({"ZZZ": intel}) == ["ZZZ"]


def test_fetch_failure_is_not_a_neutral_reading_and_not_a_vacuum():
    """A failed fetch and a quiet day must not be the same record.

    Before this, an outage returned score 0.0 / NEUTRAL / 0 articles, which
    also tripped detect_news_vacuum — silently turning downtime into a
    tradeable "no coverage, surprise risk" signal.
    """
    failed = compute_symbol_news_intelligence("ZZZ", [], status=STATUS_ERROR)
    quiet = compute_symbol_news_intelligence("ZZZ", [], status=STATUS_EMPTY)

    assert failed != quiet
    assert failed["available"] is False
    assert failed["data_status"] == STATUS_ERROR
    assert failed["label"] == "UNAVAILABLE"     # not NEUTRAL
    assert failed["label"] != quiet["label"]
    assert failed["sentiment_score"] is None    # no number to average or threshold
    assert failed["trend"] == "UNKNOWN"         # not STABLE

    # The outage must not be reported as a news vacuum...
    assert detect_news_vacuum({"ZZZ": failed}) == []
    # ...but must be reported as unavailable.
    assert unavailable_symbols({"ZZZ": failed}) == ["ZZZ"]


def test_error_status_wins_over_any_articles_handed_in():
    # Defensive: if a partial/stale batch arrives with an error status, the
    # status is authoritative — we do not score data we could not verify.
    intel = compute_symbol_news_intelligence(
        "ZZZ", [_article("stock soars to record high")], status=STATUS_ERROR
    )
    assert intel["available"] is False
    assert intel["article_count"] == 0


def test_detect_news_vacuum_ignores_status_free_records():
    # Callers that predate the status field must keep working.
    assert detect_news_vacuum({"AAA": {"article_count": 0}}) == ["AAA"]


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


def test_format_news_context_says_unavailable_instead_of_neutral():
    """An unreadable feed must read as UNAVAILABLE, never as a quiet tape."""
    intel = {
        "market": {"sentiment_score": None, "label": "UNAVAILABLE", "article_count": 0,
                   "trend": "UNKNOWN", "data_status": STATUS_ERROR, "available": False,
                   "top_headlines": []},
        "per_symbol": [
            {"symbol": "AAA", "sentiment_score": 0.4, "label": "POSITIVE",
             "article_count": 6, "trend": "STABLE", "events": [],
             "data_status": STATUS_OK, "available": True},
            {"symbol": "BBB", "sentiment_score": None, "label": "UNAVAILABLE",
             "article_count": 0, "trend": "UNKNOWN",
             "data_status": STATUS_ERROR, "available": False},
        ],
        # A vacuum list built before statuses were known must not leak BBB.
        "vacuum": ["BBB", "CCC"],
    }
    out = format_news_context(intel)
    assert "Market News Tone:** UNAVAILABLE" in out
    assert "NEUTRAL" not in out
    assert "News Feed UNAVAILABLE" in out and "BBB" in out
    assert "AAA: +0.40 (POSITIVE)" in out
    vacuum_line = next(line for line in out.splitlines() if "News Vacuum" in line)
    assert "CCC" in vacuum_line
    assert "BBB" not in vacuum_line


def test_format_macro_news_context_states_an_unavailable_feed():
    out = format_macro_news_context(
        {"article_count": 0, "data_status": STATUS_ERROR, "available": False,
         "sentiment_score": None, "label": "UNAVAILABLE"}
    )
    assert "UNAVAILABLE" in out
    assert "not neutral" in out
    # A genuinely empty (but successful) macro fetch still renders nothing.
    assert format_macro_news_context(
        {"article_count": 0, "data_status": STATUS_EMPTY, "available": True}
    ) == ""


async def test_get_news_intelligence_separates_failed_symbols_from_quiet_ones(monkeypatch):
    """End-to-end: one symbol fails, one is genuinely quiet, one has news."""
    import analysis.news_intelligence as ni

    class _FakeAdapter:
        async def get_company_news_batch_with_status(self, symbols, days, limit_per_symbol):
            return {
                "AAA": {"articles": [_article("record profit beat, shares soar"),
                                     _article("upgraded on strong demand, target raised")],
                        "status": STATUS_OK},
                "BBB": {"articles": [], "status": STATUS_EMPTY},
                "CCC": {"articles": [], "status": STATUS_ERROR},
            }

        async def get_market_news_with_status(self, days):
            return {"articles": [], "status": STATUS_ERROR}

    monkeypatch.setattr(ni, "get_news_adapter", lambda: _FakeAdapter())

    intel = await ni.get_news_intelligence(["AAA", "BBB", "CCC"], days=7)
    by_symbol = {r["symbol"]: r for r in intel["per_symbol"]}

    assert intel["unavailable"] == ["CCC"]
    assert intel["vacuum"] == ["BBB"]          # quiet, and only quiet
    assert by_symbol["CCC"]["label"] == "UNAVAILABLE"
    assert by_symbol["BBB"]["label"] == "NEUTRAL"
    assert by_symbol["AAA"]["label"] == "POSITIVE"
    # A failed market fetch is not a neutral market.
    assert intel["market"]["available"] is False
    assert intel["market"]["label"] == "UNAVAILABLE"


async def test_get_macro_news_intelligence_reports_an_unavailable_feed(monkeypatch):
    import analysis.news_intelligence as ni

    class _DeadAdapter:
        async def get_macro_news_with_status(self, days, limit):
            return {"articles": [], "status": STATUS_ERROR}

    monkeypatch.setattr(ni, "get_news_adapter", lambda: _DeadAdapter())

    macro = await ni.get_macro_news_intelligence(days=3)
    assert macro["label"] == "UNAVAILABLE"
    assert macro["sentiment_score"] is None
    assert macro["available"] is False
    assert "UNAVAILABLE" in format_macro_news_context(macro)
