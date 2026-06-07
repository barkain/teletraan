"""Keyless financial-news adapter.

Aggregates company and market headlines from two free, no-auth sources:

1. **yfinance** ``Ticker.news`` — per-symbol articles from Yahoo Finance.
2. **Google News RSS** — broad recency-ranked headlines via the public
   ``news.google.com/rss/search`` endpoint (no API key).

If ``FINNHUB_API_KEY`` is configured, Finnhub company news is folded in as a
bonus source; otherwise the two keyless sources are used. All methods return
an empty list on failure (never raise) and results are TTL-cached.

Output is a normalised ``NewsArticle`` dict — see ``_normalize_*`` — so the
sentiment layer (``analysis.news_intelligence``) can score any source
uniformly.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus

import aiohttp  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# Cache TTLs (seconds)
_COMPANY_TTL = 30 * 60   # 30 minutes
_MARKET_TTL = 20 * 60    # 20 minutes

_REQUEST_TIMEOUT = 20
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0
_BACKOFF_FACTOR = 2.0
_CONCURRENCY = 8

_USER_AGENT = "Teletraan/1.0 (Market Intelligence)"
_GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"


class _CacheEntry:
    """Simple TTL cache entry."""

    __slots__ = ("data", "expires_at")

    def __init__(self, data: Any, ttl: float) -> None:
        self.data = data
        self.expires_at = time.monotonic() + ttl

    @property
    def is_valid(self) -> bool:
        return time.monotonic() < self.expires_at


def _iso(dt: datetime | None) -> str:
    """Render a tz-aware UTC ISO string, or '' if unknown."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _strip_html(text: str) -> str:
    """Remove tags/entities from an RSS description snippet.

    Unescape FIRST: Google News encodes tags as entities (``&lt;a href=...&gt;``),
    so stripping before unescaping would leave the markup behind. A second
    unescape catches any double-encoding.
    """
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


class NewsAdapter:
    """Keyless financial-news aggregator (yfinance + Google News RSS).

    All methods degrade gracefully to ``[]`` on failure. Results are
    TTL-cached per (symbol, window).
    """

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._sem = asyncio.Semaphore(_CONCURRENCY)
        self._cache: dict[str, _CacheEntry] = {}

    @property
    def is_configured(self) -> bool:
        """Always available — the keyless sources need no auth."""
        return True

    # ------------------------------------------------------------------
    # HTTP + cache plumbing
    # ------------------------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    def _get_cached(self, key: str) -> Any | None:
        entry = self._cache.get(key)
        if entry is not None and entry.is_valid:
            return entry.data
        self._cache.pop(key, None)
        return None

    def _set_cached(self, key: str, data: Any, ttl: float) -> None:
        self._cache[key] = _CacheEntry(data, ttl)

    async def _fetch_text(self, url: str, params: dict[str, Any] | None = None) -> str | None:
        """GET text with rate limiting + exponential backoff."""
        session = await self._get_session()
        headers = {"User-Agent": _USER_AGENT}
        delay = _BACKOFF_BASE
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with self._sem:
                    async with session.get(url, headers=headers, params=params) as resp:
                        if resp.status == 200:
                            return await resp.text()
                        if 400 <= resp.status < 500 and resp.status != 429:
                            logger.warning("HTTP %d from %s — skipping retries", resp.status, url)
                            return None
                        logger.warning(
                            "HTTP %d from %s (attempt %d/%d)", resp.status, url, attempt, _MAX_RETRIES
                        )
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                logger.warning("News fetch error %s (attempt %d/%d): %s", url, attempt, _MAX_RETRIES, exc)
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(delay)
                delay *= _BACKOFF_FACTOR
        return None

    # ------------------------------------------------------------------
    # Normalisers — every source maps to the same NewsArticle dict
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_yf(item: dict[str, Any], symbol: str | None) -> dict[str, Any] | None:
        """Normalise a yfinance Ticker.news item (old flat or new nested shape)."""
        content = item.get("content") if isinstance(item.get("content"), dict) else item
        headline = (content.get("title") or "").strip()
        if not headline:
            return None
        summary = (content.get("summary") or content.get("description") or "").strip()

        # URL: new shape nests under canonicalUrl/clickThroughUrl; old uses 'link'
        url = ""
        for key in ("canonicalUrl", "clickThroughUrl"):
            val = content.get(key)
            if isinstance(val, dict) and val.get("url"):
                url = val["url"]
                break
        if not url:
            url = content.get("link") or item.get("link") or ""

        # Source
        provider = content.get("provider")
        if isinstance(provider, dict):
            source = provider.get("displayName") or "Yahoo Finance"
        else:
            source = item.get("publisher") or "Yahoo Finance"

        # Published time: new 'pubDate' ISO string, old 'providerPublishTime' epoch
        published = ""
        pub = content.get("pubDate") or content.get("displayTime")
        if isinstance(pub, str) and pub:
            published = pub
        else:
            epoch = item.get("providerPublishTime") or content.get("providerPublishTime")
            if isinstance(epoch, (int, float)) and epoch > 0:
                published = _iso(datetime.fromtimestamp(epoch, tz=timezone.utc))

        return {
            "id": (content.get("id") or url or headline)[:200],
            "headline": headline,
            "summary": _strip_html(summary),
            "url": url,
            "source": source,
            "published_at": published,
            "symbols": [symbol.upper()] if symbol else [],
        }

    @staticmethod
    def _parse_rss_items(text: str, symbol: str | None) -> list[dict[str, Any]]:
        """Parse Google News RSS XML into normalised articles (regex, no deps)."""
        articles: list[dict[str, Any]] = []
        for item_xml in re.findall(r"<item>(.*?)</item>", text, re.DOTALL):
            title_m = re.search(
                r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", item_xml, re.DOTALL
            )
            link_m = re.search(
                r"<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>", item_xml, re.DOTALL
            )
            desc_m = re.search(
                r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", item_xml, re.DOTALL
            )
            date_m = re.search(r"<pubDate>(.*?)</pubDate>", item_xml)
            source_m = re.search(r"<source[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</source>", item_xml, re.DOTALL)

            raw_title = _strip_html(title_m.group(1)) if title_m else ""
            if not raw_title:
                continue
            source = _strip_html(source_m.group(1)) if source_m else ""
            # Google News titles end with " - Publisher"; split it out.
            headline = raw_title
            if not source and " - " in raw_title:
                headline, _, source = raw_title.rpartition(" - ")
            elif source and raw_title.endswith(f" - {source}"):
                headline = raw_title[: -(len(source) + 3)]

            published = ""
            if date_m:
                try:
                    published = _iso(parsedate_to_datetime(date_m.group(1).strip()))
                except (TypeError, ValueError):
                    published = ""

            url = link_m.group(1).strip() if link_m else ""
            articles.append({
                "id": (url or headline)[:200],
                "headline": headline.strip(),
                "summary": _strip_html(desc_m.group(1)) if desc_m else "",
                "url": url,
                "source": source or "Google News",
                "published_at": published,
                "symbols": [symbol.upper()] if symbol else [],
            })
        return articles

    # ------------------------------------------------------------------
    # Source fetchers
    # ------------------------------------------------------------------

    async def _fetch_yf_news(self, symbol: str) -> list[dict[str, Any]]:
        """yfinance Ticker.news is blocking — run in the default executor."""
        def _blocking() -> list[Any]:
            try:
                import yfinance as yf  # local import; heavy module
                return yf.Ticker(symbol).news or []
            except Exception as exc:  # noqa: BLE001 - yfinance raises many types
                logger.debug("yfinance news failed for %s: %s", symbol, exc)
                return []

        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, _blocking)
        out: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict):
                norm = self._normalize_yf(item, symbol)
                if norm:
                    out.append(norm)
        return out

    async def _fetch_google_news(self, query: str, symbol: str | None, days: int) -> list[dict[str, Any]]:
        params = {
            "q": f"{query} when:{days}d",
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        }
        text = await self._fetch_text(_GOOGLE_NEWS_RSS, params=params)
        if not text:
            return []
        return self._parse_rss_items(text, symbol)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_company_news(
        self, symbol: str, days: int = 7, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return recent news for *symbol* (yfinance + Google News), deduped."""
        symbol = symbol.upper().strip()
        if not symbol:
            return []
        cache_key = f"company:{symbol}:{days}:{limit}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        yf_news, google_news = await asyncio.gather(
            self._fetch_yf_news(symbol),
            self._fetch_google_news(f'"{symbol}" stock', symbol, days),
        )
        merged = _dedupe_articles(yf_news + google_news)
        merged = _within_days(merged, days)[:limit]
        self._set_cached(cache_key, merged, _COMPANY_TTL)
        return merged

    async def get_company_news_batch(
        self, symbols: list[str], days: int = 7, limit_per_symbol: int = 15
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch news for many symbols concurrently. Returns {SYMBOL: [articles]}."""
        uniq = list(dict.fromkeys(s.upper().strip() for s in symbols if s and s.strip()))
        results = await asyncio.gather(
            *(self.get_company_news(s, days=days, limit=limit_per_symbol) for s in uniq),
            return_exceptions=True,
        )
        out: dict[str, list[dict[str, Any]]] = {}
        for sym, res in zip(uniq, results):
            out[sym] = res if isinstance(res, list) else []
        return out

    async def get_market_news(self, days: int = 2, limit: int = 30) -> list[dict[str, Any]]:
        """Return broad market headlines (Google News, market-wide query)."""
        cache_key = f"market:{days}:{limit}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached
        queries = ["stock market", "S&P 500", "Federal Reserve interest rates"]
        batches = await asyncio.gather(
            *(self._fetch_google_news(q, None, days) for q in queries)
        )
        merged = _dedupe_articles([a for b in batches for a in b])
        merged = _within_days(merged, days)[:limit]
        self._set_cached(cache_key, merged, _MARKET_TTL)
        return merged

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


def _dedupe_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe by URL then normalised headline; preserve first occurrence."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for a in articles:
        key = (a.get("url") or "").strip().lower() or re.sub(
            r"[^a-z0-9]", "", (a.get("headline") or "").lower()
        )
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


def _within_days(articles: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    """Keep articles published within *days* (undated kept), newest first."""
    now = datetime.now(timezone.utc)

    def _dt(a: dict[str, Any]) -> datetime | None:
        raw = a.get("published_at")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    kept: list[tuple[datetime | None, dict[str, Any]]] = []
    for a in articles:
        dt = _dt(a)
        if dt is None:
            kept.append((None, a))
            continue
        age_days = (now - dt).total_seconds() / 86400
        if age_days <= days + 0.5:
            kept.append((dt, a))
    # Newest first; undated sink to the bottom.
    kept.sort(key=lambda t: t[0] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return [a for _, a in kept]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_news_adapter: NewsAdapter | None = None


def get_news_adapter() -> NewsAdapter:
    """Return the module-level NewsAdapter singleton."""
    global _news_adapter
    if _news_adapter is None:
        _news_adapter = NewsAdapter()
    return _news_adapter
