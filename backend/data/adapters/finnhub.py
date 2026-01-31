"""Finnhub API adapter for news and sentiment data."""

import asyncio
import time
from datetime import date
from typing import Any, Dict, List, Optional

import httpx

from config import get_settings


class RateLimiter:
    """Simple token bucket rate limiter for API calls.

    Finnhub free tier allows 60 API calls per minute.
    This limiter ensures we don't exceed that threshold.
    """

    def __init__(self, calls_per_minute: int = 60):
        """Initialize the rate limiter.

        Args:
            calls_per_minute: Maximum number of calls allowed per minute.
        """
        self.calls_per_minute = calls_per_minute
        self.min_interval = 60.0 / calls_per_minute
        self._last_call: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait if necessary to respect rate limits."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self.min_interval:
                await asyncio.sleep(self.min_interval - elapsed)
            self._last_call = time.monotonic()


class FinnhubAdapter:
    """Adapter for Finnhub API - news and sentiment.

    Free tier: 60 API calls/minute
    Premium plans available with higher limits.

    API Documentation: https://finnhub.io/docs/api
    """

    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self) -> None:
        """Initialize the Finnhub adapter."""
        self.api_key = get_settings().FINNHUB_API_KEY
        self._client: Optional[httpx.AsyncClient] = None
        self._rate_limiter = RateLimiter(calls_per_minute=60)

    @property
    def is_configured(self) -> bool:
        """Check if API key is configured."""
        return bool(self.api_key)

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                params={"token": self.api_key} if self.api_key else {},
                timeout=30.0,
            )
        return self._client

    async def _request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Make a rate-limited request to the API.

        Args:
            endpoint: API endpoint path
            params: Query parameters

        Returns:
            JSON response data

        Raises:
            httpx.HTTPStatusError: On API errors
        """
        if not self.is_configured:
            return []  # Graceful degradation without API key

        await self._rate_limiter.acquire()
        client = await self._get_client()
        response = await client.get(endpoint, params=params or {})
        response.raise_for_status()
        return response.json()

    async def get_company_news(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
    ) -> List[Dict[str, Any]]:
        """Get company-specific news articles.

        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            from_date: Start date for news
            to_date: End date for news

        Returns:
            List of news articles with fields:
            - category: News category
            - datetime: Unix timestamp
            - headline: Article headline
            - id: Unique article ID
            - image: Image URL
            - related: Related symbols
            - source: News source
            - summary: Article summary
            - url: Article URL
        """
        return await self._request(
            "/company-news",
            params={
                "symbol": symbol.upper(),
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
            },
        )

    async def get_market_news(
        self,
        category: str = "general",
    ) -> List[Dict[str, Any]]:
        """Get general market news.

        Args:
            category: News category - 'general', 'forex', 'crypto', 'merger'

        Returns:
            List of market news articles with fields:
            - category: News category
            - datetime: Unix timestamp
            - headline: Article headline
            - id: Unique article ID
            - image: Image URL
            - related: Related symbols
            - source: News source
            - summary: Article summary
            - url: Article URL
        """
        return await self._request(
            "/news",
            params={"category": category},
        )

    async def get_sentiment(self, symbol: str) -> Dict[str, Any]:
        """Get social sentiment for a symbol.

        Uses Finnhub's social sentiment endpoint which aggregates
        sentiment from Reddit and Twitter.

        Args:
            symbol: Stock symbol (e.g., 'AAPL')

        Returns:
            Sentiment data with fields:
            - reddit: List of Reddit sentiment scores
            - twitter: List of Twitter sentiment scores
            Each containing atTime, mention, positiveScore, etc.
        """
        result = await self._request(
            "/stock/social-sentiment",
            params={"symbol": symbol.upper()},
        )
        # Return empty dict structure if no API key
        if not result:
            return {"reddit": [], "twitter": []}
        return result

    async def get_recommendation_trends(
        self,
        symbol: str,
    ) -> List[Dict[str, Any]]:
        """Get analyst recommendation trends.

        Args:
            symbol: Stock symbol (e.g., 'AAPL')

        Returns:
            List of monthly recommendation data with fields:
            - buy: Number of buy recommendations
            - hold: Number of hold recommendations
            - period: Month (YYYY-MM-DD)
            - sell: Number of sell recommendations
            - strongBuy: Number of strong buy recommendations
            - strongSell: Number of strong sell recommendations
            - symbol: Stock symbol
        """
        return await self._request(
            "/stock/recommendation",
            params={"symbol": symbol.upper()},
        )

    async def get_basic_financials(
        self,
        symbol: str,
        metric: str = "all",
    ) -> Dict[str, Any]:
        """Get basic financials and metrics.

        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            metric: Metric type - 'all', 'price', 'valuation', 'margin',
                   'profitability', 'growth', 'leverage', 'efficiency'

        Returns:
            Financial metrics data with fields:
            - metric: Dictionary of financial metrics
            - metricType: Type of metrics returned
            - series: Historical data series
            - symbol: Stock symbol
        """
        result = await self._request(
            "/stock/metric",
            params={"symbol": symbol.upper(), "metric": metric},
        )
        if not result:
            return {"metric": {}, "series": {}}
        return result

    async def get_earnings_calendar(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get earnings calendar.

        Args:
            from_date: Start date (optional)
            to_date: End date (optional)
            symbol: Filter by symbol (optional)

        Returns:
            Earnings calendar data with field 'earningsCalendar' containing:
            - date: Earnings date
            - epsActual: Actual EPS
            - epsEstimate: Estimated EPS
            - hour: Before market (bmo), after market close (amc), or during (dmh)
            - quarter: Fiscal quarter
            - revenueActual: Actual revenue
            - revenueEstimate: Estimated revenue
            - symbol: Stock symbol
            - year: Fiscal year
        """
        params: Dict[str, str] = {}
        if from_date:
            params["from"] = from_date.isoformat()
        if to_date:
            params["to"] = to_date.isoformat()
        if symbol:
            params["symbol"] = symbol.upper()

        result = await self._request("/calendar/earnings", params=params)
        if not result:
            return {"earningsCalendar": []}
        return result

    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """Get real-time quote data.

        Args:
            symbol: Stock symbol (e.g., 'AAPL')

        Returns:
            Quote data with fields:
            - c: Current price
            - d: Change
            - dp: Percent change
            - h: High price of the day
            - l: Low price of the day
            - o: Open price of the day
            - pc: Previous close price
            - t: Unix timestamp
        """
        result = await self._request(
            "/quote",
            params={"symbol": symbol.upper()},
        )
        if not result:
            return {}
        return result

    async def get_peers(self, symbol: str) -> List[str]:
        """Get company peers/competitors.

        Args:
            symbol: Stock symbol (e.g., 'AAPL')

        Returns:
            List of peer stock symbols
        """
        result = await self._request(
            "/stock/peers",
            params={"symbol": symbol.upper()},
        )
        return result if result else []

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "FinnhubAdapter":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()


# Export singleton
finnhub_adapter = FinnhubAdapter()
