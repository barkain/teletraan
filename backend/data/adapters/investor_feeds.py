"""Investor feeds data adapter for tracking superinvestor positions and commentary.

Fetches SEC EDGAR 13F filings and financial news to track position changes
and market commentary from notable institutional investors. All data comes
from free, public sources (SEC EDGAR EFTS, RSS feeds).

Sources:
1. SEC EDGAR EFTS — Full-text search of 13F-HR filings by CIK
2. Financial news RSS — Commentary and market views from notable investors
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

DEFAULT_INVESTORS = [
    {"name": "Warren Buffett", "firm": "Berkshire Hathaway", "cik": "0001067983"},
    {"name": "Ray Dalio", "firm": "Bridgewater Associates", "cik": "0001350694"},
    {"name": "Michael Burry", "firm": "Scion Asset Management", "cik": "0001649339"},
    {"name": "Cathie Wood", "firm": "ARK Invest", "cik": "0001803078"},
    {"name": "Bill Ackman", "firm": "Pershing Square", "cik": "0001336528"},
    {"name": "David Tepper", "firm": "Appaloosa Management", "cik": "0001006438"},
    {"name": "Stanley Druckenmiller", "firm": "Duquesne Family Office", "cik": "0001536411"},
    {"name": "Howard Marks", "firm": "Oaktree Capital", "cik": "0001403256"},
    {"name": "Seth Klarman", "firm": "Baupost Group", "cik": "0001061768"},
    {"name": "Chase Coleman", "firm": "Tiger Global", "cik": "0001167483"},
]

# SEC EDGAR base URLs
SEC_EDGAR_EFTS_BASE = "https://efts.sec.gov/LATEST"
SEC_EDGAR_SUBMISSIONS_BASE = "https://data.sec.gov/submissions"

# News RSS sources for investor commentary
NEWS_RSS_SOURCES = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=BRK-B,ARKK&region=US&lang=en-US",
]

# Cache TTLs in seconds
_POSITIONS_TTL = 60 * 60       # 1 hour (13F filings don't change frequently)
_COMMENTARY_TTL = 30 * 60      # 30 minutes
_INTELLIGENCE_TTL = 30 * 60    # 30 minutes

# Request settings
_REQUEST_TIMEOUT = 30
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0
_BACKOFF_FACTOR = 2.0
_CONCURRENCY = 5

# SEC EDGAR requires a User-Agent with a company name and email
_SEC_USER_AGENT = "Teletraan/1.0 (Market Intelligence; teletraan-app@example.com)"


class _CacheEntry:
    """Simple TTL cache entry."""

    __slots__ = ("data", "expires_at")

    def __init__(self, data: Any, ttl: float) -> None:
        self.data = data
        self.expires_at = time.monotonic() + ttl

    @property
    def is_valid(self) -> bool:
        """Check if the cache entry is still within its TTL."""
        return time.monotonic() < self.expires_at


@dataclass
class InvestorPosition:
    """A tracked position change from an institutional investor's 13F filing.

    Attributes:
        investor_name: Name of the investor (e.g., "Warren Buffett").
        investor_firm: Firm name (e.g., "Berkshire Hathaway").
        symbol: Stock ticker symbol if identifiable (e.g., "AAPL").
        action: Position action (buy, sell, increase, decrease, new).
        reported_date: Date the filing was reported (ISO format).
        source: Source of the data (e.g., "SEC EDGAR 13F-HR").
        confidence: Confidence in the parsed data (high, medium, low).
        context: Additional context about the position.
    """

    investor_name: str
    investor_firm: str
    symbol: str
    action: str  # buy, sell, increase, decrease, new
    reported_date: str
    source: str
    confidence: str
    context: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "investor_name": self.investor_name,
            "investor_firm": self.investor_firm,
            "symbol": self.symbol,
            "action": self.action,
            "reported_date": self.reported_date,
            "source": self.source,
            "confidence": self.confidence,
            "context": self.context,
        }


@dataclass
class InvestorCommentary:
    """A tracked commentary or public statement from a notable investor.

    Attributes:
        investor_name: Name of the investor.
        investor_firm: Firm name.
        date: Date of the commentary (ISO format).
        topic: Topic or headline summary.
        summary: Brief summary of the commentary.
        sentiment: Overall sentiment (bullish, bearish, cautious, neutral).
        mentioned_symbols: Ticker symbols mentioned in the commentary.
        source_url: URL to the original source.
    """

    investor_name: str
    investor_firm: str
    date: str
    topic: str
    summary: str
    sentiment: str
    mentioned_symbols: list[str] = field(default_factory=list)
    source_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "investor_name": self.investor_name,
            "investor_firm": self.investor_firm,
            "date": self.date,
            "topic": self.topic,
            "summary": self.summary,
            "sentiment": self.sentiment,
            "mentioned_symbols": self.mentioned_symbols,
            "source_url": self.source_url,
        }


class InvestorFeedAdapter:
    """Adapter for fetching institutional investor positions and commentary.

    Sources (tiered, all free, no auth required):
    1. SEC EDGAR EFTS -- 13F-HR filing search by CIK
    2. Financial news RSS -- Commentary and market views

    All methods return empty list/dict on failure (never raise).
    """

    def __init__(self) -> None:
        """Initialize the investor feed adapter."""
        self._session: aiohttp.ClientSession | None = None
        self._semaphore = asyncio.Semaphore(_CONCURRENCY)

        # TTL cache: key -> _CacheEntry
        self._cache: dict[str, _CacheEntry] = {}

    @property
    def is_configured(self) -> bool:
        """Check if adapter is configured. Always True (no auth needed)."""
        return True

    @property
    def is_available(self) -> bool:
        """Check if adapter is available. Same as is_configured."""
        return self.is_configured

    # ------------------------------------------------------------------
    # Session and cache management
    # ------------------------------------------------------------------

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp client session (lazy init)."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    def _get_cached(self, key: str) -> Any | None:
        """Return cached data if still valid, else None."""
        entry = self._cache.get(key)
        if entry is not None and entry.is_valid:
            return entry.data
        # Evict stale entry
        self._cache.pop(key, None)
        return None

    def _set_cached(self, key: str, data: Any, ttl: float) -> None:
        """Store data in cache with given TTL."""
        self._cache[key] = _CacheEntry(data, ttl)

    # ------------------------------------------------------------------
    # HTTP request helpers with retry and backoff
    # ------------------------------------------------------------------

    async def _fetch_with_retry(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any | None:
        """Make an HTTP GET request with rate limiting and exponential backoff.

        Args:
            url: Full request URL.
            headers: Optional HTTP headers.
            params: Optional query parameters.

        Returns:
            Parsed JSON response, or None on failure.
        """
        session = await self._ensure_session()
        delay = _BACKOFF_BASE

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with self._semaphore:
                    async with session.get(
                        url, headers=headers, params=params
                    ) as resp:
                        if resp.status == 200:
                            return await resp.json(content_type=None)
                        if resp.status == 429:
                            logger.warning(
                                "Rate limited by %s (attempt %d/%d), "
                                "backing off %.1fs",
                                url,
                                attempt,
                                _MAX_RETRIES,
                                delay,
                            )
                            await asyncio.sleep(delay)
                            delay *= _BACKOFF_FACTOR
                            continue
                        logger.warning(
                            "HTTP %d from %s (attempt %d/%d)",
                            resp.status,
                            url,
                            attempt,
                            _MAX_RETRIES,
                        )
                        if attempt < _MAX_RETRIES:
                            await asyncio.sleep(delay)
                            delay *= _BACKOFF_FACTOR
            except asyncio.TimeoutError:
                logger.warning(
                    "Timeout fetching %s (attempt %d/%d)",
                    url,
                    attempt,
                    _MAX_RETRIES,
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(delay)
                    delay *= _BACKOFF_FACTOR
            except Exception:
                logger.exception(
                    "Error fetching %s (attempt %d/%d)",
                    url,
                    attempt,
                    _MAX_RETRIES,
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(delay)
                    delay *= _BACKOFF_FACTOR

        return None

    async def _fetch_text_with_retry(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> str | None:
        """Make an HTTP GET request returning raw text with retry and backoff.

        Args:
            url: Full request URL.
            headers: Optional HTTP headers.
            params: Optional query parameters.

        Returns:
            Raw text response, or None on failure.
        """
        session = await self._ensure_session()
        delay = _BACKOFF_BASE

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with self._semaphore:
                    async with session.get(
                        url, headers=headers, params=params
                    ) as resp:
                        if resp.status == 200:
                            return await resp.text()
                        if resp.status == 429:
                            logger.warning(
                                "Rate limited by %s (attempt %d/%d), "
                                "backing off %.1fs",
                                url,
                                attempt,
                                _MAX_RETRIES,
                                delay,
                            )
                            await asyncio.sleep(delay)
                            delay *= _BACKOFF_FACTOR
                            continue
                        logger.warning(
                            "HTTP %d from %s (attempt %d/%d)",
                            resp.status,
                            url,
                            attempt,
                            _MAX_RETRIES,
                        )
                        if attempt < _MAX_RETRIES:
                            await asyncio.sleep(delay)
                            delay *= _BACKOFF_FACTOR
            except asyncio.TimeoutError:
                logger.warning(
                    "Timeout fetching %s (attempt %d/%d)",
                    url,
                    attempt,
                    _MAX_RETRIES,
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(delay)
                    delay *= _BACKOFF_FACTOR
            except Exception:
                logger.exception(
                    "Error fetching %s (attempt %d/%d)",
                    url,
                    attempt,
                    _MAX_RETRIES,
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(delay)
                    delay *= _BACKOFF_FACTOR

        return None

    # ------------------------------------------------------------------
    # SEC EDGAR 13F positions
    # ------------------------------------------------------------------

    async def get_recent_positions(
        self,
        investors: list[dict[str, str]] | None = None,
    ) -> list[InvestorPosition]:
        """Fetch recent 13F-HR filing data from SEC EDGAR for tracked investors.

        Queries the SEC EDGAR submissions endpoint for each investor's CIK,
        parses the filing metadata, and extracts top holdings.

        Args:
            investors: List of investor dicts with keys: name, firm, cik.
                Defaults to DEFAULT_INVESTORS.

        Returns:
            List of InvestorPosition dataclasses. Empty list on failure.
        """
        cache_key = "positions:all"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        if investors is None:
            investors = DEFAULT_INVESTORS

        all_positions: list[InvestorPosition] = []

        # Fetch filings for each investor concurrently
        tasks = [
            self._fetch_investor_positions(inv)
            for inv in investors
        ]

        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            logger.exception("Error gathering investor positions")
            return []

        for result in results:
            if isinstance(result, list):
                all_positions.extend(result)
            elif isinstance(result, Exception):
                logger.warning("Position fetch task failed: %s", result)

        self._set_cached(cache_key, all_positions, _POSITIONS_TTL)
        return all_positions

    async def _fetch_investor_positions(
        self,
        investor: dict[str, str],
    ) -> list[InvestorPosition]:
        """Fetch 13F-HR filings for a single investor from SEC EDGAR.

        Args:
            investor: Dict with keys: name, firm, cik.

        Returns:
            List of InvestorPosition for this investor. Empty list on failure.
        """
        cik = investor.get("cik", "")
        name = investor.get("name", "Unknown")
        firm = investor.get("firm", "Unknown")

        if not cik:
            return []

        try:
            headers = {
                "User-Agent": _SEC_USER_AGENT,
                "Accept": "application/json",
            }

            # Query SEC EDGAR submissions endpoint for structured filing data
            submissions_url = (
                f"{SEC_EDGAR_SUBMISSIONS_BASE}/CIK{cik}.json"
            )

            data = await self._fetch_with_retry(
                submissions_url, headers=headers
            )

            if not data:
                logger.warning(
                    "SEC EDGAR returned no data for %s (CIK: %s)", name, cik
                )
                return []

            positions: list[InvestorPosition] = []

            # Parse the submissions response for recent filings
            recent_filings = data.get("filings", {}).get("recent", {})
            forms = recent_filings.get("form", [])
            dates = recent_filings.get("filingDate", [])
            accession_numbers = recent_filings.get("accessionNumber", [])

            for i, form_type in enumerate(forms):
                if form_type not in ("13F-HR", "13F-HR/A"):
                    continue
                if i >= len(dates):
                    break

                filing_date = dates[i] if i < len(dates) else ""
                accession = (
                    accession_numbers[i] if i < len(accession_numbers) else ""
                )

                # Create a position entry for the filing itself
                positions.append(
                    InvestorPosition(
                        investor_name=name,
                        investor_firm=firm,
                        symbol="",
                        action="filing",
                        reported_date=filing_date,
                        source=f"SEC EDGAR 13F-HR (CIK: {cik})",
                        confidence="high",
                        context=(
                            f"13F-HR filing by {firm} on {filing_date}. "
                            f"Accession: {accession}"
                        ),
                    )
                )

                # Limit to most recent 3 filings per investor
                if len(positions) >= 3:
                    break

            return positions

        except Exception:
            logger.exception(
                "Error fetching positions for %s (CIK: %s)", name, cik
            )
            return []

    # ------------------------------------------------------------------
    # Investor commentary from news
    # ------------------------------------------------------------------

    async def get_recent_commentary(
        self,
        investors: list[dict[str, str]] | None = None,
    ) -> list[InvestorCommentary]:
        """Fetch recent commentary and news mentions for tracked investors.

        Searches financial news RSS feeds for mentions of tracked investors
        and extracts summaries, sentiment, and mentioned symbols.

        Args:
            investors: List of investor dicts with keys: name, firm, cik.
                Defaults to DEFAULT_INVESTORS.

        Returns:
            List of InvestorCommentary dataclasses. Empty list on failure.
        """
        cache_key = "commentary:all"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        if investors is None:
            investors = DEFAULT_INVESTORS

        all_commentary: list[InvestorCommentary] = []

        try:
            # Fetch from each RSS source
            for rss_url in NEWS_RSS_SOURCES:
                commentaries = await self._fetch_commentary_from_rss(
                    rss_url, investors
                )
                all_commentary.extend(commentaries)

            # Also search SEC EDGAR for investor letters/commentary filings
            tasks = [
                self._fetch_investor_news(inv)
                for inv in investors
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, list):
                    all_commentary.extend(result)
                elif isinstance(result, Exception):
                    logger.warning("Commentary fetch task failed: %s", result)

        except Exception:
            logger.exception("Error fetching investor commentary")

        self._set_cached(cache_key, all_commentary, _COMMENTARY_TTL)
        return all_commentary

    async def _fetch_commentary_from_rss(
        self,
        rss_url: str,
        investors: list[dict[str, str]],
    ) -> list[InvestorCommentary]:
        """Fetch and parse commentary from a financial news RSS feed.

        Args:
            rss_url: URL of the RSS feed.
            investors: List of investor dicts to match against.

        Returns:
            List of InvestorCommentary found in the feed. Empty list on failure.
        """
        try:
            headers = {
                "User-Agent": _SEC_USER_AGENT,
                "Accept": "application/rss+xml, application/xml, text/xml",
            }
            text = await self._fetch_text_with_retry(rss_url, headers=headers)

            if not text:
                return []

            commentaries: list[InvestorCommentary] = []

            # Simple XML parsing -- extract items from RSS
            items = re.findall(
                r"<item>(.*?)</item>", text, re.DOTALL
            )

            investor_names_lower = {
                inv["name"].lower(): inv for inv in investors
            }
            investor_firms_lower = {
                inv["firm"].lower(): inv for inv in investors
            }

            for item_xml in items:
                title_match = re.search(
                    r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>",
                    item_xml,
                    re.DOTALL,
                )
                link_match = re.search(
                    r"<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>",
                    item_xml,
                    re.DOTALL,
                )
                desc_match = re.search(
                    r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>",
                    item_xml,
                    re.DOTALL,
                )
                pub_date_match = re.search(
                    r"<pubDate>(.*?)</pubDate>", item_xml
                )

                title = title_match.group(1).strip() if title_match else ""
                link = link_match.group(1).strip() if link_match else ""
                description = (
                    desc_match.group(1).strip() if desc_match else ""
                )
                pub_date = (
                    pub_date_match.group(1).strip() if pub_date_match else ""
                )

                combined_text = f"{title} {description}".lower()

                # Check if any tracked investor is mentioned
                matched_investor: dict[str, str] | None = None
                for inv_name, inv in investor_names_lower.items():
                    if inv_name in combined_text:
                        matched_investor = inv
                        break
                if matched_investor is None:
                    for inv_firm, inv in investor_firms_lower.items():
                        if inv_firm in combined_text:
                            matched_investor = inv
                            break

                if matched_investor is None:
                    continue

                # Derive simple sentiment from title keywords
                sentiment = "neutral"
                bullish_kw = [
                    "buy", "bull", "optimistic", "upgrade", "growth",
                    "opportunity", "accumulate", "positive",
                ]
                bearish_kw = [
                    "sell", "bear", "pessimistic", "downgrade", "risk",
                    "warning", "caution", "negative", "bubble",
                ]
                if any(kw in combined_text for kw in bullish_kw):
                    sentiment = "bullish"
                if any(kw in combined_text for kw in bearish_kw):
                    sentiment = (
                        "bearish" if sentiment != "bullish" else "cautious"
                    )

                # Extract mentioned ticker symbols (uppercase 1-5 letter words)
                symbols = re.findall(
                    r"\b([A-Z]{1,5})\b",
                    f"{title} {description}",
                )
                # Filter out common English words
                common_words = {
                    "A", "I", "THE", "AND", "OR", "FOR", "IN", "ON",
                    "AT", "TO", "OF", "IS", "IT", "AS", "BY", "AN",
                    "BE", "IF", "UP", "DO", "SO", "NO", "HE", "WE",
                    "US", "AM", "PM", "CEO", "NEW", "ALL", "HAS",
                    "SEC", "RSS", "ETF", "IPO",
                }
                mentioned_symbols = list(
                    dict.fromkeys(
                        s for s in symbols if s not in common_words
                    )
                )[:10]

                commentaries.append(
                    InvestorCommentary(
                        investor_name=matched_investor["name"],
                        investor_firm=matched_investor["firm"],
                        date=pub_date,
                        topic=title[:200],
                        summary=description[:500],
                        sentiment=sentiment,
                        mentioned_symbols=mentioned_symbols,
                        source_url=link,
                    )
                )

            return commentaries

        except Exception:
            logger.exception("Error parsing RSS feed %s", rss_url)
            return []

    async def _fetch_investor_news(
        self,
        investor: dict[str, str],
    ) -> list[InvestorCommentary]:
        """Fetch recent news for a single investor from SEC EDGAR EFTS search.

        Uses full-text search to find recent filings mentioning the investor
        that may contain letters to shareholders or commentary.

        Args:
            investor: Dict with keys: name, firm, cik.

        Returns:
            List of InvestorCommentary. Empty list on failure.
        """
        name = investor.get("name", "Unknown")
        firm = investor.get("firm", "Unknown")
        cik = investor.get("cik", "")

        if not cik:
            return []

        try:
            now = datetime.now(timezone.utc)
            start_date = (now - timedelta(days=90)).strftime("%Y-%m-%d")
            end_date = now.strftime("%Y-%m-%d")

            url = f"{SEC_EDGAR_EFTS_BASE}/search-index"
            params = {
                "q": f'"{firm}"',
                "dateRange": "custom",
                "startdt": start_date,
                "enddt": end_date,
                "from": "0",
                "size": "3",
            }
            headers = {
                "User-Agent": _SEC_USER_AGENT,
                "Accept": "application/json",
            }

            data = await self._fetch_with_retry(
                url, headers=headers, params=params
            )

            if not data:
                return []

            commentaries: list[InvestorCommentary] = []
            hits = data.get("hits", {}).get("hits", [])

            for hit in hits[:3]:
                source = hit.get("_source", {})
                filing_date = source.get("file_date", "")
                form_type = source.get("form_type", "")
                entity_name = source.get("entity_name", firm)

                commentaries.append(
                    InvestorCommentary(
                        investor_name=name,
                        investor_firm=entity_name,
                        date=filing_date,
                        topic=f"{form_type} filing by {entity_name}",
                        summary=(
                            f"SEC filing ({form_type}) by {entity_name} "
                            f"on {filing_date}."
                        ),
                        sentiment="neutral",
                        mentioned_symbols=[],
                        source_url=(
                            f"https://www.sec.gov/cgi-bin/browse-edgar"
                            f"?action=getcompany&CIK={cik}&type=&dateb="
                            f"&owner=include&count=10"
                        ),
                    )
                )

            return commentaries

        except Exception:
            logger.exception(
                "Error fetching news for %s (CIK: %s)", name, cik
            )
            return []

    # ------------------------------------------------------------------
    # Combined intelligence
    # ------------------------------------------------------------------

    async def get_all_intelligence(
        self,
        investors: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Fetch all investor intelligence: positions and commentary.

        Calls both get_recent_positions() and get_recent_commentary()
        concurrently and returns a combined dict with metadata.

        Args:
            investors: List of investor dicts. Defaults to DEFAULT_INVESTORS.

        Returns:
            Dict with keys: positions, commentary, metadata.
            Returns empty structure on failure.
        """
        cache_key = "intelligence:all"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        if investors is None:
            investors = DEFAULT_INVESTORS

        try:
            positions_task = self.get_recent_positions(investors)
            commentary_task = self.get_recent_commentary(investors)

            results = await asyncio.gather(
                positions_task, commentary_task, return_exceptions=True
            )

            positions = results[0] if isinstance(results[0], list) else []
            commentary = results[1] if isinstance(results[1], list) else []

            # Collect unique investors that returned data
            investors_with_data: set[str] = set()
            for pos in positions:
                investors_with_data.add(pos.investor_name)
            for comm in commentary:
                investors_with_data.add(comm.investor_name)

            # Collect unique symbols across all data
            all_symbols: set[str] = set()
            for pos in positions:
                if pos.symbol:
                    all_symbols.add(pos.symbol)
            for comm in commentary:
                all_symbols.update(comm.mentioned_symbols)

            result: dict[str, Any] = {
                "positions": [p.to_dict() for p in positions],
                "commentary": [c.to_dict() for c in commentary],
                "metadata": {
                    "fetch_time": datetime.now(timezone.utc).isoformat(),
                    "investor_count": len(investors),
                    "investors_with_data": len(investors_with_data),
                    "total_positions": len(positions),
                    "total_commentary": len(commentary),
                    "unique_symbols": sorted(all_symbols),
                },
            }

            self._set_cached(cache_key, result, _INTELLIGENCE_TTL)
            return result

        except Exception:
            logger.exception("Error aggregating investor intelligence")
            return {
                "positions": [],
                "commentary": [],
                "metadata": {
                    "fetch_time": datetime.now(timezone.utc).isoformat(),
                    "investor_count": 0,
                    "investors_with_data": 0,
                    "total_positions": 0,
                    "total_commentary": 0,
                    "unique_symbols": [],
                    "error": "Failed to fetch investor intelligence",
                },
            }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the aiohttp client session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> InvestorFeedAdapter:
        """Async context manager entry."""
        return self

    async def __aexit__(
        self, exc_type: Any, exc_val: Any, exc_tb: Any
    ) -> None:
        """Async context manager exit."""
        await self.close()


# Singleton instance
_adapter_instance: InvestorFeedAdapter | None = None


def get_investor_feed_adapter() -> InvestorFeedAdapter:
    """Get or create the singleton InvestorFeedAdapter instance."""
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = InvestorFeedAdapter()
    return _adapter_instance
