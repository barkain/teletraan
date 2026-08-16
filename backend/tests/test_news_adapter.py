"""Tests for the keyless news adapter normalisers + entity validation (no network)."""

from datetime import datetime, timezone

from data.adapters.news import (
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_OK,
    NewsAdapter,
    _dedupe_articles,
    _fetch_status,
    _strip_html,
    _within_days,
    article_relevance,
    company_aliases,
    filter_articles_for_symbol,
)


def test_strip_html_unescapes_before_stripping():
    # Google News encodes tags as entities; they must still be removed.
    assert _strip_html("Big &lt;a href='x'&gt;news&lt;/a&gt; today") == "Big news today"
    assert _strip_html("<b>bold</b> &amp; clean") == "bold & clean"
    assert _strip_html("") == ""


def test_normalize_yf_new_nested_shape():
    item = {
        "content": {
            "id": "abc123",
            "title": "Apple unveils new chip",
            "summary": "<p>The M5 is here.</p>",
            "pubDate": "2026-06-07T12:00:00Z",
            "provider": {"displayName": "Reuters"},
            "canonicalUrl": {"url": "https://ex.com/a"},
        }
    }
    out = NewsAdapter._normalize_yf(item, "AAPL")
    assert out["headline"] == "Apple unveils new chip"
    assert out["summary"] == "The M5 is here."
    assert out["url"] == "https://ex.com/a"
    assert out["source"] == "Reuters"
    assert out["published_at"].startswith("2026-06-07")
    # The normaliser records which feed the item came from but does NOT claim
    # the article is about AAPL — only the relevance filter may do that.
    assert out["symbols"] == []
    assert out["feed_symbol"] == "AAPL"


def test_normalize_yf_old_flat_shape():
    item = {
        "title": "Old style headline",
        "publisher": "Bloomberg",
        "link": "https://ex.com/old",
        "providerPublishTime": 1749200000,
    }
    out = NewsAdapter._normalize_yf(item, "tsla")
    assert out["headline"] == "Old style headline"
    assert out["source"] == "Bloomberg"
    assert out["url"] == "https://ex.com/old"
    assert out["published_at"]  # epoch converted to ISO
    assert out["symbols"] == []
    assert out["feed_symbol"] == "TSLA"


def test_normalize_yf_skips_titleless():
    assert NewsAdapter._normalize_yf({"content": {"summary": "x"}}, "AAPL") is None


def test_parse_rss_splits_publisher_from_title():
    xml = """
    <item>
      <title>Nvidia hits record high - Reuters</title>
      <link>https://news.google.com/x</link>
      <description>&lt;a href="u"&gt;Shares jump&lt;/a&gt;</description>
      <pubDate>Sat, 07 Jun 2026 14:30:00 GMT</pubDate>
      <source url="https://reuters.com">Reuters</source>
    </item>
    """
    items = NewsAdapter._parse_rss_items(xml, "NVDA")
    assert len(items) == 1
    a = items[0]
    assert a["headline"] == "Nvidia hits record high"
    assert a["source"] == "Reuters"
    assert a["summary"] == "Shares jump"
    assert a["published_at"].startswith("2026-06-07")
    # A keyword search is not an attribution: the RSS parser records the query
    # symbol only, and never earns the provider-feed relevance bonus.
    assert a["symbols"] == []
    assert a["feed_symbol"] is None
    assert a["query_symbol"] == "NVDA"


def test_dedupe_by_url_then_headline():
    arts = [
        {"url": "https://x.com/1", "headline": "A"},
        {"url": "https://x.com/1", "headline": "A duplicate url"},
        {"url": "", "headline": "Same Headline!"},
        {"url": "", "headline": "same headline"},  # normalises equal
    ]
    out = _dedupe_articles(arts)
    assert len(out) == 2


def test_within_days_drops_old_keeps_undated_newest_first():
    now = datetime.now(timezone.utc)

    def iso(days_ago):
        from datetime import timedelta
        return (now - timedelta(days=days_ago)).isoformat()

    arts = [
        {"headline": "old", "published_at": iso(30)},
        {"headline": "fresh", "published_at": iso(1)},
        {"headline": "mid", "published_at": iso(3)},
        {"headline": "undated", "published_at": ""},
    ]
    out = _within_days(arts, days=7)
    headlines = [a["headline"] for a in out]
    assert "old" not in headlines
    assert headlines[0] == "fresh"  # newest first
    assert "undated" in headlines   # undated retained


# ---------------------------------------------------------------------------
# Entity validation
# ---------------------------------------------------------------------------

def _art(headline, summary="", feed_symbol=None):
    return {
        "headline": headline,
        "summary": summary,
        "url": f"https://x.com/{abs(hash(headline)) % 10000}",
        "source": "Benzinga",
        "published_at": "",
        "symbols": [],
        "feed_symbol": feed_symbol,
    }


def test_company_aliases_strips_corporate_suffixes():
    assert company_aliases("Caterpillar Inc.") == ["caterpillar inc", "caterpillar"]
    assert company_aliases("Red Cat Holdings, Inc.") == [
        "red cat holdings inc", "red cat"
    ]
    assert company_aliases("Astec Industries, Inc.") == [
        "astec industries inc", "astec industries"
    ]
    assert company_aliases(None) == []
    # A core too generic to identify anyone is dropped, leaving the full name.
    assert company_aliases("Global Corp") == ["global corp"]


def test_cat_regression_red_cat_and_astec_excluded():
    """The measured defect: a CAT request returned RCAT and ASTE articles.

    All 15 articles were tagged symbols=['CAT'] and aggregated to +0.31
    POSITIVE, presented to the analyst as Caterpillar sentiment.
    """
    contaminants = [
        _art("Why Is Red Cat Holdings Stock Lifting Off Friday?",
             "RCAT shares climbed after a drone order."),
        _art("Red Cat (NASDAQ:RCAT) Shares Surge On Army Contract Win"),
        _art("Red Cat Holdings Announces Q2 Results",
             "Red Cat reported revenue growth in its drone segment."),
        _art("Astec Industries (NASDAQ:ASTE) Reports Second-Quarter Earnings Beat"),
        _art("ASTE Stock Moves Higher After Guidance Raise"),
        _art("Astec Industries Declares Quarterly Dividend"),
        _art("Why Astec Industries Stock Is Trading Higher Today"),
    ]
    genuine = [
        # Name only — no ticker token anywhere. This is the common case and the
        # reason name resolution matters.
        _art("Caterpillar profit tops estimates on strong equipment demand"),
        _art("Caterpillar (NYSE:CAT) Raises Quarterly Dividend By 7%"),
        _art("Analysts Boost Price Targets On CAT After Machinery Upcycle Call"),
    ]
    aliases = company_aliases("Caterpillar Inc.")

    kept = filter_articles_for_symbol(contaminants + genuine, "CAT", aliases)
    kept_headlines = [a["headline"] for a in kept]

    assert len(kept) == 3, kept_headlines
    for a in contaminants:
        assert a["headline"] not in kept_headlines
    for a in genuine:
        assert a["headline"] in kept_headlines
    # Only validated articles carry the attribution.
    assert all(a["symbols"] == ["CAT"] for a in kept)
    assert all(a["relevance"] >= 0.5 for a in kept)


def test_rcat_token_is_not_a_cat_token():
    # Substring matching would make every RCAT headline a CAT headline.
    score, _ = article_relevance(
        _art("Red Cat (NASDAQ:RCAT) Shares Surge"), "CAT", ["caterpillar"]
    )
    assert score == 0.0
    # ...while the exchange-qualified form for the real symbol is maximal.
    score, reason = article_relevance(
        _art("Caterpillar (NYSE:CAT) Raises Dividend"), "CAT", ["caterpillar"]
    )
    assert score == 1.0
    assert reason == "exchange_ticker"


def test_common_english_word_ticker_not_matched_on_prose():
    # "key" / "cat" as ordinary words must not be read as the tickers KEY / CAT.
    prose = [
        _art("The key to this rally is liquidity, strategists say"),
        _art("Traders warn of a dead cat bounce in industrials"),
        _art("A cat sanctuary received a surprise endowment"),
    ]
    assert filter_articles_for_symbol(prose, "KEY", ["keycorp"]) == []
    assert filter_articles_for_symbol(prose, "CAT", ["caterpillar"]) == []

    # The ticker written as a ticker still resolves.
    real = [_art("KeyCorp (NYSE:KEY) Lifts Full-Year Guidance")]
    assert len(filter_articles_for_symbol(real, "KEY", ["keycorp"])) == 1


def test_cashtag_and_name_forms_are_accepted():
    aliases = company_aliases("Caterpillar Inc.")
    for headline, expected_reason in [
        ("$CAT breaks out to a new high", "cashtag"),
        ("Caterpillar lifts full-year outlook", "company_name:caterpillar"),
        ("Dealers report record CAT order backlog", "ticker_token"),
    ]:
        score, reason = article_relevance(_art(headline), "CAT", aliases)
        assert score >= 0.5, headline
        assert reason == expected_reason, headline


def test_short_ticker_needs_corroboration():
    # A 1-2 char ticker token is far too weak on its own ("F" matches anything).
    weak = _art("F shares rise as truck demand holds up")
    assert article_relevance(weak, "F", [])[0] < 0.5
    assert filter_articles_for_symbol([weak], "F", []) == []

    # The provider's own per-ticker feed is an entity attribution, not a keyword
    # hit, so it lifts the same article over the bar.
    from_feed = _art("F shares rise as truck demand holds up", feed_symbol="F")
    assert filter_articles_for_symbol([from_feed], "F", []) != []

    # A name match needs no corroboration.
    named = _art("Ford Motor beats on Q2 deliveries")
    assert len(filter_articles_for_symbol([named], "F", ["ford motor", "ford"])) == 1


def test_provider_feed_bonus_cannot_rescue_an_unrelated_article():
    # yfinance attached this to the CAT feed, but nothing in it is about CAT.
    off_topic = _art("Dow Jones Today: Stocks Drift Ahead Of The Jobs Report",
                     feed_symbol="CAT")
    assert filter_articles_for_symbol([off_topic], "CAT", ["caterpillar"]) == []


def test_fetch_status_distinguishes_failure_from_quiet():
    assert _fetch_status(True, 5) == STATUS_OK
    assert _fetch_status(True, 0) == STATUS_EMPTY   # sources answered, no news
    assert _fetch_status(False, 0) == STATUS_ERROR  # every source failed


async def test_get_company_news_with_status_filters_and_reports_ok(monkeypatch):
    adapter = NewsAdapter()

    async def fake_name(_symbol):
        return "Caterpillar Inc."

    async def fake_yf(_symbol):
        return [_art("Caterpillar lifts full-year outlook", feed_symbol="CAT")], True

    async def fake_google(_query, _symbol, _days):
        return [_art("Red Cat (NASDAQ:RCAT) Shares Surge On Army Contract")], True

    monkeypatch.setattr(NewsAdapter, "_company_name", staticmethod(fake_name))
    monkeypatch.setattr(NewsAdapter, "_fetch_yf_news", staticmethod(fake_yf))
    monkeypatch.setattr(NewsAdapter, "_fetch_google_news", staticmethod(fake_google))

    result = await adapter.get_company_news_with_status("CAT", days=7)
    assert result["status"] == STATUS_OK
    assert result["company_name"] == "Caterpillar Inc."
    assert [a["headline"] for a in result["articles"]] == [
        "Caterpillar lifts full-year outlook"
    ]
    assert result["fetched_count"] == 2
    assert result["dropped_count"] == 1


async def test_get_company_news_with_status_reports_error_when_all_sources_fail(monkeypatch):
    adapter = NewsAdapter()

    async def fake_name(_symbol):
        return None

    async def dead_yf(_symbol):
        return [], False

    async def dead_google(_query, _symbol, _days):
        return [], False

    monkeypatch.setattr(NewsAdapter, "_company_name", staticmethod(fake_name))
    monkeypatch.setattr(NewsAdapter, "_fetch_yf_news", staticmethod(dead_yf))
    monkeypatch.setattr(NewsAdapter, "_fetch_google_news", staticmethod(dead_google))

    result = await adapter.get_company_news_with_status("CAT", days=7)
    assert result["status"] == STATUS_ERROR
    assert result["articles"] == []


async def test_get_company_news_with_status_reports_empty_on_a_quiet_day(monkeypatch):
    adapter = NewsAdapter()

    async def fake_name(_symbol):
        return None

    async def quiet_yf(_symbol):
        return [], True

    async def quiet_google(_query, _symbol, _days):
        return [], True

    monkeypatch.setattr(NewsAdapter, "_company_name", staticmethod(fake_name))
    monkeypatch.setattr(NewsAdapter, "_fetch_yf_news", staticmethod(quiet_yf))
    monkeypatch.setattr(NewsAdapter, "_fetch_google_news", staticmethod(quiet_google))

    result = await adapter.get_company_news_with_status("CAT", days=7)
    assert result["status"] == STATUS_EMPTY
    assert result["articles"] == []


async def test_company_query_uses_the_company_name(monkeypatch):
    """The bare-ticker query is what made a CAT search ambiguous."""
    adapter = NewsAdapter()
    seen: list[str] = []

    async def fake_name(_symbol):
        return "Caterpillar Inc."

    async def fake_yf(_symbol):
        return [], True

    async def capture(query, _symbol, _days):
        seen.append(query)
        return [], True

    monkeypatch.setattr(NewsAdapter, "_company_name", staticmethod(fake_name))
    monkeypatch.setattr(NewsAdapter, "_fetch_yf_news", staticmethod(fake_yf))
    monkeypatch.setattr(NewsAdapter, "_fetch_google_news", staticmethod(capture))

    await adapter.get_company_news_with_status("CAT", days=7)
    assert seen == ['"Caterpillar Inc." stock OR "CAT" stock']
