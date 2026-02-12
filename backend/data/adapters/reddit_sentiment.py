"""Multi-source Reddit sentiment data adapter.

Aggregates data from three free, no-auth sources:
1. ApeWisdom — Pre-aggregated trending tickers with mention counts
2. Arctic Shift — Historical full-text search across Reddit
3. Reddit JSON — Real-time subreddit posts (rate-limited)
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

MARKET_SUBREDDITS = [
    "wallstreetbets",
    "stocks",
    "investing",
    "options",
    "StockMarket",
    "SecurityAnalysis",
    "economy",
]

# Source base URLs
APEWISDOM_BASE = "https://apewisdom.io/api/v1.0"
ARCTIC_SHIFT_BASE = "https://arctic-shift.photon-reddit.com/api"
REDDIT_JSON_BASE = "https://www.reddit.com"

# Rate limit semaphore capacities per source
_APEWISDOM_CONCURRENCY = 10
_ARCTIC_SHIFT_CONCURRENCY = 10
_REDDIT_JSON_CONCURRENCY = 2

# Cache TTLs in seconds
_APEWISDOM_TTL = 15 * 60     # 15 minutes
_ARCTIC_SHIFT_TTL = 60 * 60  # 1 hour
_REDDIT_JSON_TTL = 5 * 60    # 5 minutes

# Request timeout
_REQUEST_TIMEOUT = 30

# Backoff settings
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0
_BACKOFF_FACTOR = 2.0

# User-Agent for Reddit JSON endpoints
_USER_AGENT = "Teletraan/1.0 (Market Intelligence)"


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


class RedditSentimentAdapter:
    """Multi-source Reddit sentiment data adapter.

    Sources (tiered, all free, no auth required):
    1. ApeWisdom (primary) — Pre-aggregated trending tickers
    2. Arctic Shift (secondary) — Historical full-text Reddit search
    3. Reddit JSON (fallback) — Real-time subreddit posts

    All methods return empty list/dict on failure (never raise).
    """

    def __init__(self) -> None:
        """Initialize the Reddit sentiment adapter."""
        self._session: aiohttp.ClientSession | None = None

        # Per-source rate limit semaphores
        self._sem_apewisdom = asyncio.Semaphore(_APEWISDOM_CONCURRENCY)
        self._sem_arctic = asyncio.Semaphore(_ARCTIC_SHIFT_CONCURRENCY)
        self._sem_reddit = asyncio.Semaphore(_REDDIT_JSON_CONCURRENCY)

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

    async def _get_session(self) -> aiohttp.ClientSession:
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

    async def _request_with_backoff(
        self,
        url: str,
        semaphore: asyncio.Semaphore,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any | None:
        """Make an HTTP GET request with rate limiting and exponential backoff.

        Args:
            url: Full request URL.
            semaphore: Source-specific concurrency semaphore.
            headers: Optional HTTP headers.
            params: Optional query parameters.

        Returns:
            Parsed JSON response, or None on failure.
        """
        session = await self._get_session()
        delay = _BACKOFF_BASE

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with semaphore:
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

    # ------------------------------------------------------------------
    # ApeWisdom (primary)
    # ------------------------------------------------------------------

    async def get_trending_tickers(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get top trending tickers from ApeWisdom.

        Args:
            limit: Maximum number of tickers to return.

        Returns:
            List of dicts with keys: ticker, name, mentions, upvotes, rank.
            Empty list on failure.
        """
        cache_key = f"apewisdom:trending:{limit}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        url = f"{APEWISDOM_BASE}/filter/all-stocks"
        data = await self._request_with_backoff(url, self._sem_apewisdom)

        if not data or "results" not in data:
            logger.warning("ApeWisdom returned no results for trending tickers")
            return []

        results: list[dict[str, Any]] = []
        for item in data["results"][:limit]:
            results.append(
                {
                    "ticker": item.get("ticker", ""),
                    "name": item.get("name", ""),
                    "mentions": item.get("mentions", 0),
                    "upvotes": item.get("upvotes", 0),
                    "rank": item.get("rank", 0),
                }
            )

        self._set_cached(cache_key, results, _APEWISDOM_TTL)
        return results

    # ------------------------------------------------------------------
    # Arctic Shift (secondary)
    # ------------------------------------------------------------------

    async def search_mentions(
        self,
        ticker: str,
        subreddit: str = "wallstreetbets",
        days_back: int = 7,
    ) -> list[dict[str, Any]]:
        """Search Reddit mentions of a ticker via Arctic Shift.

        Args:
            ticker: Stock ticker symbol (e.g. 'AAPL').
            subreddit: Subreddit to search within.
            days_back: Number of days to look back.

        Returns:
            List of dicts with keys: title, body, score, num_comments,
            created_utc, subreddit, url. Empty list on failure.
        """
        cache_key = f"arctic:mentions:{ticker}:{subreddit}:{days_back}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        after_epoch = int(
            (datetime.now(timezone.utc) - timedelta(days=days_back)).timestamp()
        )
        url = f"{ARCTIC_SHIFT_BASE}/posts/search"
        params = {
            "q": ticker.upper(),
            "subreddit": subreddit,
            "after": str(after_epoch),
            "limit": "100",
        }

        data = await self._request_with_backoff(
            url, self._sem_arctic, params=params
        )

        if not data:
            logger.warning(
                "Arctic Shift returned no data for %s in r/%s",
                ticker,
                subreddit,
            )
            return []

        # Arctic Shift wraps posts in a "data" key
        posts = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(posts, list):
            posts = []

        results: list[dict[str, Any]] = []
        for post in posts:
            results.append(
                {
                    "title": post.get("title", ""),
                    "body": post.get("selftext", post.get("body", "")),
                    "score": post.get("score", 0),
                    "num_comments": post.get("num_comments", 0),
                    "created_utc": post.get("created_utc", 0),
                    "subreddit": post.get("subreddit", subreddit),
                    "url": post.get("url", post.get("permalink", "")),
                }
            )

        self._set_cached(cache_key, results, _ARCTIC_SHIFT_TTL)
        return results

    async def get_mention_trend(
        self,
        ticker: str,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """Get daily mention trend for a ticker across market subreddits.

        Uses Arctic Shift to search day-by-day and count mentions.

        Args:
            ticker: Stock ticker symbol.
            days: Number of days to aggregate.

        Returns:
            List of dicts with keys: date (YYYY-MM-DD), mention_count.
            Empty list on failure.
        """
        cache_key = f"arctic:trend:{ticker}:{days}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        now = datetime.now(timezone.utc)

        async def _count_day(day_offset: int) -> dict[str, Any]:
            """Count mentions for a single day across all market subreddits."""
            day_start = now - timedelta(days=day_offset)
            day_end = day_start + timedelta(days=1)
            after_epoch = int(day_start.timestamp())
            before_epoch = int(day_end.timestamp())
            date_str = day_start.strftime("%Y-%m-%d")

            total = 0
            for sub in MARKET_SUBREDDITS:
                url = f"{ARCTIC_SHIFT_BASE}/posts/search"
                params = {
                    "q": ticker.upper(),
                    "subreddit": sub,
                    "after": str(after_epoch),
                    "before": str(before_epoch),
                    "limit": "0",
                }
                data = await self._request_with_backoff(
                    url, self._sem_arctic, params=params
                )
                if data and isinstance(data, dict):
                    count = data.get(
                        "total_results",
                        len(data.get("data", [])) if "data" in data else 0,
                    )
                    total += count

            return {"date": date_str, "mention_count": total}

        # Run day counts concurrently (capped by semaphore)
        tasks = [_count_day(d) for d in range(days, 0, -1)]
        try:
            day_results = await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            logger.exception("Error gathering mention trend for %s", ticker)
            return []

        results: list[dict[str, Any]] = []
        for res in day_results:
            if isinstance(res, dict):
                results.append(res)
            # Skip exceptions silently — partial data is still useful

        self._set_cached(cache_key, results, _ARCTIC_SHIFT_TTL)
        return results

    # ------------------------------------------------------------------
    # Reddit JSON (fallback)
    # ------------------------------------------------------------------

    async def get_subreddit_hot(
        self,
        subreddit: str = "wallstreetbets",
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Get hot posts from a subreddit via Reddit JSON API.

        Args:
            subreddit: Subreddit name.
            limit: Maximum number of posts.

        Returns:
            List of dicts with keys: title, selftext, score, num_comments,
            created_utc, url. Empty list on failure.
        """
        cache_key = f"reddit:hot:{subreddit}:{limit}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        url = f"{REDDIT_JSON_BASE}/r/{subreddit}/hot.json"
        params = {"limit": str(limit)}
        headers = {"User-Agent": _USER_AGENT}

        data = await self._request_with_backoff(
            url, self._sem_reddit, headers=headers, params=params
        )

        if not data or "data" not in data:
            logger.warning(
                "Reddit JSON returned no data for r/%s", subreddit
            )
            return []

        results: list[dict[str, Any]] = []
        for child in data["data"].get("children", []):
            post = child.get("data", {})
            results.append(
                {
                    "title": post.get("title", ""),
                    "selftext": post.get("selftext", ""),
                    "score": post.get("score", 0),
                    "num_comments": post.get("num_comments", 0),
                    "created_utc": post.get("created_utc", 0),
                    "url": post.get("url", ""),
                }
            )

        self._set_cached(cache_key, results, _REDDIT_JSON_TTL)
        return results

    # ------------------------------------------------------------------
    # Aggregated sentiment
    # ------------------------------------------------------------------

    async def get_market_sentiment(self) -> dict[str, Any]:
        """Aggregate market sentiment from multiple sources.

        Combines trending tickers from ApeWisdom, hot posts from top
        subreddits, and derives an overall mood indicator.

        Returns:
            Dict with keys: trending, overall_mood, top_mentioned.
            Empty dict on failure.
        """
        cache_key = "sentiment:market"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            # Fetch trending tickers and hot posts concurrently
            trending_task = self.get_trending_tickers(limit=25)
            hot_tasks = [
                self.get_subreddit_hot(sub, limit=10)
                for sub in MARKET_SUBREDDITS[:3]  # Top 3 subreddits
            ]

            all_results = await asyncio.gather(
                trending_task, *hot_tasks, return_exceptions=True
            )

            # Extract trending tickers
            trending = all_results[0] if isinstance(all_results[0], list) else []

            # Aggregate hot posts
            all_posts: list[dict[str, Any]] = []
            for res in all_results[1:]:
                if isinstance(res, list):
                    all_posts.extend(res)

            # Derive overall mood from post scores
            if all_posts:
                avg_score = sum(p.get("score", 0) for p in all_posts) / len(
                    all_posts
                )
                if avg_score > 500:
                    overall_mood = "very bullish"
                elif avg_score > 100:
                    overall_mood = "bullish"
                elif avg_score > 20:
                    overall_mood = "neutral"
                else:
                    overall_mood = "bearish"
            else:
                overall_mood = "unknown"

            # Top mentioned tickers
            top_mentioned = [
                {"ticker": t["ticker"], "mentions": t["mentions"]}
                for t in trending[:10]
            ]

            result: dict[str, Any] = {
                "trending": trending[:15],
                "overall_mood": overall_mood,
                "top_mentioned": top_mentioned,
            }

            self._set_cached(cache_key, result, _REDDIT_JSON_TTL)
            return result

        except Exception:
            logger.exception("Error aggregating market sentiment")
            return {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the aiohttp client session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> RedditSentimentAdapter:
        """Async context manager entry."""
        return self

    async def __aexit__(
        self, exc_type: Any, exc_val: Any, exc_tb: Any
    ) -> None:
        """Async context manager exit."""
        await self.close()


# Singleton instance
_instance: RedditSentimentAdapter | None = None


def get_reddit_sentiment_adapter() -> RedditSentimentAdapter:
    """Get or create the singleton RedditSentimentAdapter instance."""
    global _instance
    if _instance is None:
        _instance = RedditSentimentAdapter()
    return _instance
