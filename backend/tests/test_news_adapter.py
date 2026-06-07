"""Tests for the keyless news adapter normalisers (no network)."""

from datetime import datetime, timezone

from data.adapters.news import (
    NewsAdapter,
    _dedupe_articles,
    _strip_html,
    _within_days,
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
    assert out["symbols"] == ["AAPL"]


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
    assert out["symbols"] == ["TSLA"]


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
    assert a["symbols"] == ["NVDA"]


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
