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

Two properties this module is responsible for:

**Entity validation.** A ticker search is ambiguous ("CAT" retrieves Red Cat
and Astec articles), so a retrieved article is *not* attributed to the
requested symbol until its text is checked against that symbol's ticker forms
and company-name aliases — see ``article_relevance`` /
``filter_articles_for_symbol``. Normalisers therefore emit ``symbols: []`` and
record the feed they came from in ``feed_symbol``; only the relevance filter
may populate ``symbols``.

**Fetch status.** The ``*_with_status`` methods report ``ok`` / ``empty`` /
``error`` so callers can tell "the feed failed" from "there was genuinely no
news" — the list-returning methods collapse both to ``[]``.
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

# Company-name resolution cache TTLs. Negative results expire quickly so a
# transient Yahoo hiccup does not disable name matching for the whole process.
_NAME_TTL = 24 * 60 * 60
_NAME_FAIL_TTL = 10 * 60

# Fetch outcomes reported by the ``*_with_status`` methods.
STATUS_OK = "ok"          # a source responded and at least one article survived
STATUS_EMPTY = "empty"    # a source responded, but there was nothing to report
STATUS_ERROR = "error"    # every source failed — coverage is UNKNOWN, not zero

# Minimum entity-relevance confidence for an article to be attributed to the
# requested symbol. 0.5 admits a standalone uppercase ticker token (0.6) and
# any company-name match, but rejects a bare 1-2 character ticker token (0.3)
# unless it is corroborated by the symbol's own provider feed.
_RELEVANCE_THRESHOLD = 0.5

# Relevance weights, strongest evidence first.
_R_EXCHANGE = 1.0   # "(NASDAQ:CAT)" — an unambiguous, exchange-qualified ticker
_R_CASHTAG = 0.95   # "$CAT" — explicit ticker notation
_R_NAME = 0.9       # "Caterpillar" — company name or a distinctive alias
_R_TICKER = 0.6     # "CAT" as a standalone uppercase token (>= 3 chars)
_R_SHORT_TICKER = 0.3  # same, but 1-2 chars ("F", "C") — too weak on its own
_R_FEED_BONUS = 0.2    # article came from this symbol's own provider feed

# Corporate suffixes stripped when deriving a distinctive company alias.
_CORPORATE_SUFFIXES = frozenset({
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd",
    "limited", "llc", "lp", "plc", "sa", "nv", "ag", "se", "holdings",
    "holding", "group", "class", "the", "trust", "reit", "adr", "nnn",
})

# Alias cores too generic to identify a company on their own.
_GENERIC_NAME_CORES = frozenset({
    "american", "general", "global", "industries", "international", "national",
    "systems", "technologies", "technology", "united", "first", "new", "world",
})

# Exchange prefixes seen in headlines like "Red Cat (NASDAQ:RCAT)".
_EXCHANGES = (
    "NASDAQ", "NYSE", "NYSEAMERICAN", "NYSEARCA", "AMEX", "ARCA", "OTC",
    "OTCMKTS", "CBOE", "BATS", "TSX", "LSE", "ASX", "EPA", "ETR",
)


def company_aliases(name: str | None) -> list[str]:
    """Lowercase name forms to match an article against, longest first.

    ``"Caterpillar Inc."`` -> ``["caterpillar inc", "caterpillar"]``;
    ``"Red Cat Holdings, Inc."`` -> ``["red cat holdings", "red cat"]``.

    The suffix-stripped core is what actually does the work — headlines say
    "Caterpillar", not "Caterpillar Inc." The core is dropped when it is too
    short or too generic to identify a company ("Global", "The"), leaving only
    the full name, because a bad alias is worse than no alias.
    """
    cleaned = re.sub(r"[^\w&\s-]", " ", (name or "").lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return []

    aliases = [cleaned]
    tokens = cleaned.split()
    while tokens and tokens[-1] in _CORPORATE_SUFFIXES:
        tokens.pop()
    while tokens and tokens[0] in _CORPORATE_SUFFIXES:
        tokens.pop(0)
    core = " ".join(tokens)
    if (
        core
        and core != cleaned
        and len(core) >= 4
        and core not in _GENERIC_NAME_CORES
    ):
        aliases.append(core)
    return aliases


def _is_shouting(text: str) -> bool:
    """True when text is mostly uppercase, making a ticker-token match unreliable."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 12:
        return False
    return sum(1 for c in letters if c.isupper()) / len(letters) > 0.7


def article_relevance(
    article: dict[str, Any], symbol: str, aliases: list[str] | None = None
) -> tuple[float, str]:
    """Score how confidently *article* is about *symbol*: ``(confidence, reason)``.

    Matching is token-based, never substring-based: "Red Cat (NASDAQ:RCAT)"
    contains the token ``RCAT``, not ``CAT``, and the word "cat" in prose is not
    the ticker. Bare ticker tokens must appear in the ticker's own uppercase
    form, which is how financial headlines write them and which keeps common
    English words ("key", "cat") from being read as ``KEY`` or ``CAT``.

    Confidence is the strongest single piece of evidence found, plus a small
    bonus when the article arrived on the symbol's own provider feed (an
    entity attribution made by the provider rather than by keyword search).
    """
    symbol = (symbol or "").upper().strip()
    if not symbol:
        return 0.0, "no_symbol"

    text = f"{article.get('headline', '')} {article.get('summary', '')}".strip()
    if not text:
        return 0.0, "no_text"

    sym = re.escape(symbol)
    upper = text.upper()
    score, reason = 0.0, "no_match"

    if re.search(rf"\b(?:{'|'.join(_EXCHANGES)})\s*:\s*{sym}\b", upper):
        score, reason = _R_EXCHANGE, "exchange_ticker"
    elif re.search(rf"\${sym}\b", upper):
        score, reason = _R_CASHTAG, "cashtag"
    else:
        lowered = text.lower()
        matched_alias = next(
            (
                a for a in (aliases or [])
                if a and re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", lowered)
            ),
            None,
        )
        if matched_alias:
            score, reason = _R_NAME, f"company_name:{matched_alias}"
        elif re.search(rf"(?<![A-Za-z0-9]){sym}(?![A-Za-z0-9])", text) and not _is_shouting(text):
            if len(symbol) >= 3:
                score, reason = _R_TICKER, "ticker_token"
            else:
                score, reason = _R_SHORT_TICKER, "short_ticker_token"

    if article.get("feed_symbol") == symbol:
        score = min(1.0, score + _R_FEED_BONUS)
        reason = f"{reason}+provider_feed"
    return round(score, 2), reason


def filter_articles_for_symbol(
    articles: list[dict[str, Any]],
    symbol: str,
    aliases: list[str] | None = None,
    threshold: float = _RELEVANCE_THRESHOLD,
) -> list[dict[str, Any]]:
    """Keep only the articles that are actually about *symbol*, and tag them.

    Kept articles get ``relevance`` / ``relevance_reason`` and are the only
    ones whose ``symbols`` list names *symbol* — an article that failed the
    check is dropped rather than passed downstream with a false attribution.
    """
    symbol = (symbol or "").upper().strip()
    if not symbol:
        return list(articles)

    kept: list[dict[str, Any]] = []
    for a in articles:
        score, reason = article_relevance(a, symbol, aliases)
        if score < threshold:
            logger.debug(
                "News: dropped %r for %s (relevance %.2f, %s)",
                (a.get("headline") or "")[:80], symbol, score, reason,
            )
            continue
        symbols = [s for s in (a.get("symbols") or []) if s != symbol]
        kept.append({**a, "symbols": [symbol, *symbols], "relevance": score,
                     "relevance_reason": reason})
    return kept


def _fetch_status(any_source_ok: bool, article_count: int) -> str:
    """Map source outcomes to a status the intelligence layer can act on."""
    if not any_source_ok:
        return STATUS_ERROR
    return STATUS_OK if article_count else STATUS_EMPTY


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
        """Normalise a yfinance Ticker.news item (old flat or new nested shape).

        *symbol* is recorded as ``feed_symbol`` (which feed the article came
        from), not as ``symbols`` — attributing the article to the symbol is
        ``filter_articles_for_symbol``'s job, after the text has been checked.
        """
        raw_content = item.get("content")
        content: dict[str, Any] = raw_content if isinstance(raw_content, dict) else item
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
            "symbols": [],
            "feed_symbol": symbol.upper() if symbol else None,
        }

    @staticmethod
    def _parse_rss_items(text: str, symbol: str | None) -> list[dict[str, Any]]:
        """Parse Google News RSS XML into normalised articles (regex, no deps).

        As with ``_normalize_yf``, *symbol* only records which query produced
        the item — it is never treated as a verified attribution.
        """
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
                "symbols": [],
                # A keyword search is not a provider entity attribution, so RSS
                # items never earn the provider-feed relevance bonus.
                "feed_symbol": None,
                "query_symbol": symbol.upper() if symbol else None,
            })
        return articles

    # ------------------------------------------------------------------
    # Source fetchers
    # ------------------------------------------------------------------

    async def _fetch_yf_news(self, symbol: str) -> tuple[list[dict[str, Any]], bool]:
        """yfinance Ticker.news is blocking — run in the default executor.

        Returns ``(articles, ok)``; ``ok`` is False only when the call raised,
        so an empty-but-successful feed stays distinguishable from a failure.
        """
        def _blocking() -> tuple[list[Any], bool]:
            try:
                import yfinance as yf  # type: ignore[import-not-found]  # local import; heavy module
                return (yf.Ticker(symbol).news or [], True)
            except Exception as exc:  # noqa: BLE001 - yfinance raises many types
                logger.debug("yfinance news failed for %s: %s", symbol, exc)
                return ([], False)

        loop = asyncio.get_running_loop()
        raw, ok = await loop.run_in_executor(None, _blocking)
        out: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict):
                norm = self._normalize_yf(item, symbol)
                if norm:
                    out.append(norm)
        return out, ok

    async def _fetch_google_news(
        self, query: str, symbol: str | None, days: int
    ) -> tuple[list[dict[str, Any]], bool]:
        """Returns ``(articles, ok)``; ``ok`` is False when the HTTP fetch failed."""
        params = {
            "q": f"{query} when:{days}d",
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        }
        text = await self._fetch_text(_GOOGLE_NEWS_RSS, params=params)
        if text is None:
            return [], False
        return self._parse_rss_items(text, symbol), True

    async def _company_name(self, symbol: str) -> str | None:
        """Resolve *symbol* to its company long name, TTL-cached.

        Reuses ``YahooFinanceAdapter.get_stock_info`` (the only ticker -> name
        resolver in the backend). Returns None when the name is unknown or is
        just the ticker echoed back, in which case relevance matching falls
        back to ticker forms alone.
        """
        cache_key = f"name:{symbol}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached.get("name")

        name: str | None = None
        try:
            from data.adapters.yahoo import yahoo_adapter  # type: ignore[import-not-found]

            info = await yahoo_adapter.get_stock_info(symbol)
            raw = str((info or {}).get("name") or "").strip()
            if raw and raw.upper() != symbol:
                name = raw
        except Exception as exc:  # noqa: BLE001 - name lookup must never break news
            logger.debug("Company-name lookup failed for %s: %s", symbol, exc)

        self._set_cached(cache_key, {"name": name}, _NAME_TTL if name else _NAME_FAIL_TTL)
        return name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_company_news_with_status(
        self, symbol: str, days: int = 7, limit: int = 20
    ) -> dict[str, Any]:
        """Entity-validated news for *symbol*, with the fetch outcome attached.

        Returns ``{symbol, articles, status, company_name, fetched_count,
        dropped_count}``. ``status`` is ``ok`` / ``empty`` / ``error`` — the
        last meaning every source failed, so coverage is unknown rather than
        zero. ``dropped_count`` is how many retrieved articles failed entity
        validation (a search for "CAT" routinely returns Red Cat articles).
        """
        symbol = symbol.upper().strip()
        if not symbol:
            return {"symbol": symbol, "articles": [], "status": STATUS_EMPTY,
                    "company_name": None, "fetched_count": 0, "dropped_count": 0}
        cache_key = f"company:{symbol}:{days}:{limit}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        name = await self._company_name(symbol)
        aliases = company_aliases(name)
        # Search on the company name as well as the ticker: a bare ticker query
        # is what pulled Red Cat and Astec articles into a CAT request.
        query = f'"{name}" stock OR "{symbol}" stock' if name else f'"{symbol}" stock'

        (yf_news, yf_ok), (google_news, google_ok) = await asyncio.gather(
            self._fetch_yf_news(symbol),
            self._fetch_google_news(query, symbol, days),
        )
        merged = _dedupe_articles(yf_news + google_news)
        fetched = len(merged)
        relevant = filter_articles_for_symbol(merged, symbol, aliases)
        articles = _within_days(relevant, days)[:limit]

        dropped = fetched - len(relevant)
        if dropped:
            logger.info(
                "News entity filter: %s kept %d/%d articles (company=%s)",
                symbol, len(relevant), fetched, name or "unknown",
            )
        result = {
            "symbol": symbol,
            "articles": articles,
            "status": _fetch_status(yf_ok or google_ok, len(articles)),
            "company_name": name,
            "fetched_count": fetched,
            "dropped_count": dropped,
        }
        self._set_cached(cache_key, result, _COMPANY_TTL)
        return result

    async def get_company_news(
        self, symbol: str, days: int = 7, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Entity-validated news for *symbol*, articles only.

        Collapses a fetch failure and a quiet news day to the same ``[]`` —
        use ``get_company_news_with_status`` when that distinction matters.
        """
        result = await self.get_company_news_with_status(symbol, days=days, limit=limit)
        return result["articles"]

    async def get_company_news_batch_with_status(
        self, symbols: list[str], days: int = 7, limit_per_symbol: int = 15
    ) -> dict[str, dict[str, Any]]:
        """Per-symbol news + fetch status, fetched concurrently. {SYMBOL: record}."""
        uniq = list(dict.fromkeys(s.upper().strip() for s in symbols if s and s.strip()))
        results = await asyncio.gather(
            *(
                self.get_company_news_with_status(s, days=days, limit=limit_per_symbol)
                for s in uniq
            ),
            return_exceptions=True,
        )
        out: dict[str, dict[str, Any]] = {}
        for sym, res in zip(uniq, results):
            if isinstance(res, dict):
                out[sym] = res
            else:
                # An exception here is itself a fetch failure, not a quiet day.
                logger.warning("News fetch raised for %s: %s", sym, res)
                out[sym] = {"symbol": sym, "articles": [], "status": STATUS_ERROR,
                            "company_name": None, "fetched_count": 0, "dropped_count": 0}
        return out

    async def get_company_news_batch(
        self, symbols: list[str], days: int = 7, limit_per_symbol: int = 15
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch news for many symbols concurrently. Returns {SYMBOL: [articles]}."""
        records = await self.get_company_news_batch_with_status(
            symbols, days=days, limit_per_symbol=limit_per_symbol
        )
        return {sym: rec["articles"] for sym, rec in records.items()}

    async def get_market_news_with_status(
        self, days: int = 2, limit: int = 30
    ) -> dict[str, Any]:
        """Broad market headlines (Google News) with the fetch outcome attached."""
        cache_key = f"market:{days}:{limit}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached
        queries = ["stock market", "S&P 500", "Federal Reserve interest rates"]
        batches = await asyncio.gather(
            *(self._fetch_google_news(q, None, days) for q in queries)
        )
        merged = _dedupe_articles([a for arts, _ in batches for a in arts])
        merged = _within_days(merged, days)[:limit]
        result = {
            "articles": merged,
            "status": _fetch_status(any(ok for _, ok in batches), len(merged)),
        }
        self._set_cached(cache_key, result, _MARKET_TTL)
        return result

    async def get_market_news(self, days: int = 2, limit: int = 30) -> list[dict[str, Any]]:
        """Return broad market headlines (Google News, market-wide query)."""
        result = await self.get_market_news_with_status(days=days, limit=limit)
        return result["articles"]

    # Macro-economic news queries, grouped by topic. The topic label is
    # attached to each returned article under "macro_topic" so the
    # intelligence layer can build a per-topic breakdown without re-classifying.
    _MACRO_QUERIES: dict[str, tuple[str, ...]] = {
        "monetary_policy": ("Federal Reserve interest rate decision", "FOMC rate cut hike"),
        "inflation": ("inflation CPI report", "PCE price index"),
        "employment": ("jobs report nonfarm payrolls", "unemployment rate"),
        "growth": ("GDP economic growth", "recession risk outlook"),
        "trade": ("tariffs trade policy", "trade war"),
        "rates": ("Treasury yields bond market",),
        "geopolitical": ("geopolitical risk markets",),
    }

    async def get_macro_news_with_status(
        self, days: int = 3, limit: int = 40
    ) -> dict[str, Any]:
        """Macro-economic headlines tagged with ``macro_topic``, plus fetch status.

        Covers monetary policy, inflation, employment, growth, trade, rates and
        geopolitics — the drivers of market regime — for the MacroScanner.
        """
        cache_key = f"macro:{days}:{limit}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        async def _topic(
            topic: str, queries: tuple[str, ...]
        ) -> tuple[list[dict[str, Any]], bool]:
            batches = await asyncio.gather(
                *(self._fetch_google_news(q, None, days) for q in queries)
            )
            arts = [a for b, _ in batches for a in b]
            for a in arts:
                a["macro_topic"] = topic
            return arts, any(ok for _, ok in batches)

        per_topic = await asyncio.gather(
            *(_topic(t, qs) for t, qs in self._MACRO_QUERIES.items())
        )
        merged = _dedupe_articles([a for arts, _ in per_topic for a in arts])
        merged = _within_days(merged, days)[:limit]
        result = {
            "articles": merged,
            "status": _fetch_status(any(ok for _, ok in per_topic), len(merged)),
        }
        self._set_cached(cache_key, result, _MARKET_TTL)
        return result

    async def get_macro_news(self, days: int = 3, limit: int = 40) -> list[dict[str, Any]]:
        """Return macro-economic headlines tagged with a ``macro_topic``."""
        result = await self.get_macro_news_with_status(days=days, limit=limit)
        return result["articles"]

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
