"""Kalshi prediction market API adapter for economic event probabilities.

Kalshi is a regulated prediction market (CFTC-regulated) that offers
markets on economic events like Fed rate decisions, CPI releases,
GDP prints, unemployment data, and S&P 500 targets.

Read-only market data endpoints require no authentication.

API Documentation: https://trading-api.readme.io/reference/getmarkets
"""

import asyncio
import logging
import time
from typing import Any

import httpx  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level cache (30-minute TTL)
# ---------------------------------------------------------------------------
_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 1800  # 30 minutes


def _get_cached(key: str) -> Any | None:
    """Get cached data if within TTL."""
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return data
        del _cache[key]
    return None


def _set_cache(key: str, data: Any) -> None:
    """Cache data with current timestamp."""
    _cache[key] = (time.time(), data)


# ---------------------------------------------------------------------------
# Series tickers for economic event categories
# ---------------------------------------------------------------------------
SERIES_FED = "FED"
SERIES_CPI = "CPI"
SERIES_GDP = "GDP"
SERIES_UNRATE = "UNRATE"
SERIES_SP500 = "SP500"

ALL_ECONOMIC_SERIES = [SERIES_FED, SERIES_CPI, SERIES_GDP, SERIES_UNRATE, SERIES_SP500]


def _parse_market(raw: dict[str, Any]) -> dict[str, Any]:
    """Parse a Kalshi market object into a standardised dict.

    Kalshi prices are in cents (0-100). Dividing by 100 gives probability.

    Args:
        raw: Raw market dict from the Kalshi API.

    Returns:
        Parsed market dict with ticker, title, probability, volume,
        close_time, yes_bid, yes_ask, no_bid, no_ask, and status.
    """
    yes_bid = raw.get("yes_bid", 0) or 0
    yes_ask = raw.get("yes_ask", 0) or 0
    no_bid = raw.get("no_bid", 0) or 0
    no_ask = raw.get("no_ask", 0) or 0

    return {
        "ticker": raw.get("ticker", ""),
        "title": raw.get("title", ""),
        "probability": yes_bid / 100.0 if yes_bid else 0.0,
        "volume": raw.get("volume", 0) or 0,
        "close_time": raw.get("close_time", ""),
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "no_bid": no_bid,
        "no_ask": no_ask,
        "status": raw.get("status", ""),
    }


class KalshiAdapter:
    """Adapter for Kalshi prediction market API -- economic event probabilities.

    Free tier: read-only market data, no authentication required.
    Rate limit: 20 requests per second.

    API Documentation: https://trading-api.readme.io/reference/getmarkets
    """

    BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

    def __init__(self) -> None:
        """Initialize the Kalshi adapter."""
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(20)

    # -- Properties ----------------------------------------------------------

    @property
    def is_configured(self) -> bool:
        """Check if adapter is configured. Always True (no auth needed)."""
        return True

    @property
    def is_available(self) -> bool:
        """Check if adapter is available. Same as is_configured."""
        return self.is_configured

    # -- HTTP layer ----------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client (lazy initialization)."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                timeout=30.0,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "market-analyzer/1.0",
                },
            )
        return self._client

    async def _request(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        max_retries: int = 3,
    ) -> Any:
        """Make a rate-limited request with exponential backoff on 429/5xx.

        Args:
            endpoint: API endpoint path (e.g. ``/markets``).
            params: Query parameters.
            max_retries: Maximum retry attempts on transient errors.

        Returns:
            Parsed JSON response body, or ``None`` on unrecoverable failure.
        """
        async with self._semaphore:
            client = await self._get_client()
            last_exc: Exception | None = None

            for attempt in range(max_retries):
                try:
                    response = await client.get(endpoint, params=params or {})
                    if response.status_code == 429 or response.status_code >= 500:
                        backoff = (2 ** attempt) + 0.5
                        logger.warning(
                            "Kalshi %s returned %d, retrying in %.1fs (attempt %d/%d)",
                            endpoint,
                            response.status_code,
                            backoff,
                            attempt + 1,
                            max_retries,
                        )
                        await asyncio.sleep(backoff)
                        continue
                    response.raise_for_status()
                    return response.json()
                except httpx.HTTPStatusError as exc:
                    logger.warning(
                        "Kalshi HTTP error on %s: %s", endpoint, exc
                    )
                    last_exc = exc
                    break
                except (httpx.RequestError, httpx.TimeoutException) as exc:
                    backoff = (2 ** attempt) + 0.5
                    logger.warning(
                        "Kalshi request error on %s: %s, retrying in %.1fs (attempt %d/%d)",
                        endpoint,
                        exc,
                        backoff,
                        attempt + 1,
                        max_retries,
                    )
                    last_exc = exc
                    await asyncio.sleep(backoff)

            logger.error(
                "Kalshi request to %s failed after %d attempts: %s",
                endpoint,
                max_retries,
                last_exc,
            )
            return None

    # -- Series helpers ------------------------------------------------------

    async def _get_series_markets(self, series_ticker: str) -> list[dict[str, Any]]:
        """Fetch open markets for a given series ticker.

        Results are cached with a 30-minute TTL.

        Args:
            series_ticker: The Kalshi series ticker (e.g. ``FED``, ``CPI``).

        Returns:
            List of parsed market dicts. Empty list on failure.
        """
        cache_key = f"kalshi:series:{series_ticker}"
        cached = _get_cached(cache_key)
        if cached is not None:
            logger.debug("Kalshi cache hit for series %s", series_ticker)
            return cached

        data = await self._request(
            "/markets",
            params={"series_ticker": series_ticker, "status": "open"},
        )

        if data is None:
            return []

        # Kalshi wraps markets in a "markets" key
        raw_markets = data.get("markets", []) if isinstance(data, dict) else []
        parsed = [_parse_market(m) for m in raw_markets]

        _set_cache(cache_key, parsed)
        logger.info(
            "Fetched %d open %s markets from Kalshi", len(parsed), series_ticker
        )
        return parsed

    # -- Public methods ------------------------------------------------------

    async def get_fed_markets(self) -> list[dict[str, Any]]:
        """Get open Fed rate decision markets with probabilities.

        Returns:
            List of parsed Fed market dicts. Empty list on failure.
        """
        return await self._get_series_markets(SERIES_FED)

    async def get_cpi_markets(self) -> list[dict[str, Any]]:
        """Get open CPI / inflation markets.

        Returns:
            List of parsed CPI market dicts. Empty list on failure.
        """
        return await self._get_series_markets(SERIES_CPI)

    async def get_gdp_markets(self) -> list[dict[str, Any]]:
        """Get open GDP markets.

        Returns:
            List of parsed GDP market dicts. Empty list on failure.
        """
        return await self._get_series_markets(SERIES_GDP)

    async def get_sp500_markets(self) -> list[dict[str, Any]]:
        """Get open S&P 500 target markets.

        Returns:
            List of parsed S&P 500 market dicts. Empty list on failure.
        """
        return await self._get_series_markets(SERIES_SP500)

    async def get_unemployment_markets(self) -> list[dict[str, Any]]:
        """Get open unemployment rate markets.

        Returns:
            List of parsed unemployment market dicts. Empty list on failure.
        """
        return await self._get_series_markets(SERIES_UNRATE)

    async def get_market_orderbook(self, ticker: str) -> dict[str, Any]:
        """Get order book data for a specific market.

        Args:
            ticker: The Kalshi market ticker (e.g. ``FED-26MAR-T4.50``).

        Returns:
            Order book dict with ``yes`` and ``no`` arrays, or empty dict
            on failure.
        """
        cache_key = f"kalshi:orderbook:{ticker}"
        cached = _get_cached(cache_key)
        if cached is not None:
            return cached

        data = await self._request(f"/markets/{ticker}/orderbook")
        if data is None:
            return {}

        orderbook = data.get("orderbook", data) if isinstance(data, dict) else {}
        _set_cache(cache_key, orderbook)
        return orderbook

    async def get_all_economic_markets(self) -> dict[str, list[dict[str, Any]]]:
        """Fetch all economic series markets in parallel.

        Returns:
            Dict mapping series name to list of parsed markets, e.g.::

                {
                    "fed": [...],
                    "cpi": [...],
                    "gdp": [...],
                    "sp500": [...],
                    "unemployment": [...]
                }
        """
        results = await asyncio.gather(
            self.get_fed_markets(),
            self.get_cpi_markets(),
            self.get_gdp_markets(),
            self.get_sp500_markets(),
            self.get_unemployment_markets(),
            return_exceptions=True,
        )

        series_keys = ["fed", "cpi", "gdp", "sp500", "unemployment"]
        aggregated: dict[str, list[dict[str, Any]]] = {}

        for key, result in zip(series_keys, results):
            if isinstance(result, BaseException):
                logger.error("Kalshi %s fetch failed: %s", key, result)
                aggregated[key] = []
            else:
                aggregated[key] = list(result)

        total = sum(len(v) for v in aggregated.values())
        logger.info(
            "Fetched %d total economic markets from Kalshi across %d series",
            total,
            len(series_keys),
        )
        return aggregated

    # -- Lifecycle -----------------------------------------------------------

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "KalshiAdapter":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_instance: KalshiAdapter | None = None


def get_kalshi_adapter() -> KalshiAdapter:
    """Get the singleton KalshiAdapter instance."""
    global _instance
    if _instance is None:
        _instance = KalshiAdapter()
    return _instance
