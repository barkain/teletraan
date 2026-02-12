"""Polymarket API adapter for prediction market data.

Uses two free, unauthenticated APIs:
- Gamma API (https://gamma-api.polymarket.com) -- Market discovery, event browsing
- CLOB API (https://clob.polymarket.com) -- Token prices, order books
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level TTL cache
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 1800  # 30 minutes


def _get_cached(key: str) -> Any | None:
    """Return cached value if still within TTL, else None."""
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return data
        del _cache[key]
    return None


def _set_cache(key: str, data: Any) -> None:
    """Store a value in the TTL cache."""
    _cache[key] = (time.time(), data)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GAMMA_BASE = "https://gamma-api.polymarket.com"
_CLOB_BASE = "https://clob.polymarket.com"

_FINANCE_TAG_ID = 120
_ECONOMY_TAG_SLUG = "economy"

_MIN_VOLUME_USD = 10_000  # Filter: minimum $10K volume
_MAX_RESOLVE_DAYS = 365  # Filter: resolves within 365 days

_REQUEST_TIMEOUT = 30.0
_MAX_RETRIES = 3
_BACKOFF_SCHEDULE = [1, 2, 4, 8]  # seconds
_MAX_CONCURRENT = 30


class PolymarketAdapter:
    """Adapter for Polymarket Gamma + CLOB APIs.

    Both APIs are free and require no authentication for read operations.

    Gamma API: Event/market discovery and browsing.
    CLOB API:  Token prices and order book data.
    """

    def __init__(self) -> None:
        """Initialize the Polymarket adapter."""
        self._gamma_client: Optional[httpx.AsyncClient] = None
        self._clob_client: Optional[httpx.AsyncClient] = None
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

    # ------------------------------------------------------------------
    # Configuration / availability
    # ------------------------------------------------------------------

    @property
    def is_configured(self) -> bool:
        """Check if the adapter is configured.

        Always True -- Polymarket APIs are free and require no auth.
        """
        return True

    @property
    def is_available(self) -> bool:
        """Check if the adapter is available for use."""
        return self.is_configured

    # ------------------------------------------------------------------
    # Lazy HTTP clients
    # ------------------------------------------------------------------

    async def _get_gamma_client(self) -> httpx.AsyncClient:
        """Get or create the Gamma API HTTP client."""
        if self._gamma_client is None:
            self._gamma_client = httpx.AsyncClient(
                base_url=_GAMMA_BASE,
                timeout=_REQUEST_TIMEOUT,
                headers={"Accept": "application/json"},
            )
        return self._gamma_client

    async def _get_clob_client(self) -> httpx.AsyncClient:
        """Get or create the CLOB API HTTP client."""
        if self._clob_client is None:
            self._clob_client = httpx.AsyncClient(
                base_url=_CLOB_BASE,
                timeout=_REQUEST_TIMEOUT,
                headers={"Accept": "application/json"},
            )
        return self._clob_client

    # ------------------------------------------------------------------
    # Internal request helpers
    # ------------------------------------------------------------------

    async def _request(
        self,
        client_getter: Any,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Make a rate-limited request with exponential backoff.

        Args:
            client_getter: Coroutine that returns the httpx.AsyncClient.
            endpoint: API endpoint path.
            params: Optional query parameters.

        Returns:
            Parsed JSON response, or None on failure.
        """
        cache_key = f"{endpoint}|{sorted((params or {}).items())}"
        cached = _get_cached(cache_key)
        if cached is not None:
            return cached

        async with self._semaphore:
            last_exc: Optional[Exception] = None
            for attempt in range(_MAX_RETRIES):
                try:
                    client = await client_getter()
                    response = await client.get(endpoint, params=params or {})

                    if response.status_code == 429 or response.status_code >= 500:
                        wait = _BACKOFF_SCHEDULE[min(attempt, len(_BACKOFF_SCHEDULE) - 1)]
                        logger.warning(
                            "Polymarket %s returned %s, retrying in %ss (attempt %d/%d)",
                            endpoint,
                            response.status_code,
                            wait,
                            attempt + 1,
                            _MAX_RETRIES,
                        )
                        await asyncio.sleep(wait)
                        continue

                    response.raise_for_status()
                    data = response.json()
                    _set_cache(cache_key, data)
                    return data

                except httpx.TimeoutException as exc:
                    last_exc = exc
                    wait = _BACKOFF_SCHEDULE[min(attempt, len(_BACKOFF_SCHEDULE) - 1)]
                    logger.warning(
                        "Polymarket %s timed out, retrying in %ss (attempt %d/%d)",
                        endpoint,
                        wait,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(wait)
                except Exception as exc:
                    last_exc = exc
                    logger.error(
                        "Polymarket %s request failed: %s",
                        endpoint,
                        exc,
                    )
                    break

            logger.error(
                "Polymarket %s failed after %d attempts: %s",
                endpoint,
                _MAX_RETRIES,
                last_exc,
            )
            return None

    async def _gamma_request(
        self,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Make a request to the Gamma API."""
        return await self._request(self._get_gamma_client, endpoint, params)

    async def _clob_request(
        self,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Make a request to the CLOB API."""
        return await self._request(self._get_clob_client, endpoint, params)

    # ------------------------------------------------------------------
    # Filtering helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_markets(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter markets by volume and resolution date.

        Keeps markets with:
        - Volume > $10K
        - End date within 90 days from now (if end_date_iso is present)
        """
        cutoff = datetime.now(timezone.utc) + timedelta(days=_MAX_RESOLVE_DAYS)
        filtered: list[dict[str, Any]] = []

        for m in markets:
            # Volume filter
            try:
                volume = float(m.get("volume", 0) or 0)
            except (TypeError, ValueError):
                volume = 0.0
            if volume < _MIN_VOLUME_USD:
                continue

            # Resolution date filter
            end_str = m.get("end_date_iso") or m.get("endDate") or m.get("end_date")
            if end_str:
                try:
                    end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                    if end_dt > cutoff:
                        continue
                except (ValueError, AttributeError):
                    pass  # Keep market if date is unparseable

            filtered.append(m)

        return filtered

    @staticmethod
    def _format_market(m: dict[str, Any]) -> dict[str, Any]:
        """Normalise a raw market/event dict into a consistent shape."""
        return {
            "id": m.get("id") or m.get("condition_id") or m.get("conditionId"),
            "question": m.get("question") or m.get("title") or "",
            "description": (m.get("description") or "")[:500],
            "volume": float(m.get("volume", 0) or 0),
            "liquidity": float(m.get("liquidity", 0) or 0),
            "end_date": m.get("end_date_iso") or m.get("endDate") or m.get("end_date"),
            "outcome_prices": m.get("outcomePrices") or m.get("outcome_prices"),
            "outcomes": m.get("outcomes"),
            "active": m.get("active", True),
            "closed": m.get("closed", False),
            "slug": m.get("slug") or m.get("market_slug"),
            "url": f"https://polymarket.com/event/{m.get('slug', '')}" if m.get("slug") else None,
        }

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def get_finance_events(self) -> list[dict[str, Any]]:
        """Get active finance-tagged events (tag_id=120).

        Returns:
            List of formatted event dicts. Empty list on failure.
        """
        data = await self._gamma_request(
            "/events",
            params={"tag_id": _FINANCE_TAG_ID, "closed": "false", "limit": 100},
        )
        if not data or not isinstance(data, list):
            return []

        # Events contain nested markets; flatten and filter
        all_markets: list[dict[str, Any]] = []
        for event in data:
            markets = event.get("markets", [])
            if markets:
                filtered = self._filter_markets(markets)
                all_markets.extend(self._format_market(m) for m in filtered)
            else:
                # Event-level entry (no nested markets)
                all_markets.append(self._format_market(event))

        return all_markets

    async def get_economy_events(self) -> list[dict[str, Any]]:
        """Get active economy-tagged events.

        Returns:
            List of formatted event dicts. Empty list on failure.
        """
        data = await self._gamma_request(
            "/events",
            params={"closed": "false", "tag": _ECONOMY_TAG_SLUG, "limit": 100},
        )
        if not data or not isinstance(data, list):
            return []

        all_markets: list[dict[str, Any]] = []
        for event in data:
            markets = event.get("markets", [])
            if markets:
                filtered = self._filter_markets(markets)
                all_markets.extend(self._format_market(m) for m in filtered)
            else:
                all_markets.append(self._format_market(event))

        return all_markets

    async def get_market_price(self, token_id: str) -> float | None:
        """Get the current price (implied probability) for a token.

        Args:
            token_id: The CLOB token ID.

        Returns:
            Price as a float (0.0 - 1.0), or None on failure.
        """
        data = await self._clob_request(
            "/price",
            params={"token_id": token_id, "side": "buy"},
        )
        if data is None:
            return None
        try:
            return float(data.get("price", data) if isinstance(data, dict) else data)
        except (TypeError, ValueError):
            logger.warning("Could not parse price for token %s: %s", token_id, data)
            return None

    async def search_markets(self, query: str) -> list[dict[str, Any]]:
        """Search markets by keyword.

        Args:
            query: Search string (e.g. 'Fed rate', 'Bitcoin', 'S&P 500').

        Returns:
            List of formatted market dicts matching the query. Empty list on failure.
        """
        data = await self._gamma_request(
            "/markets",
            params={"closed": "false", "limit": 100},
        )
        if not data or not isinstance(data, list):
            return []

        # Client-side keyword filter (Gamma API doesn't have a search param)
        query_lower = query.lower()
        matched = [
            m
            for m in data
            if query_lower in (m.get("question", "") or "").lower()
            or query_lower in (m.get("description", "") or "").lower()
            or query_lower in (m.get("title", "") or "").lower()
        ]

        filtered = self._filter_markets(matched)
        return [self._format_market(m) for m in filtered]

    async def get_relevant_predictions(self) -> dict[str, Any]:
        """Get aggregated finance + economy prediction market data.

        Returns:
            Dict with keys:
            - finance: list of finance-tagged market dicts
            - economy: list of economy-tagged market dicts
            - fetched_at: ISO timestamp
            - total_count: total number of markets returned
        """
        finance_events, economy_events = await asyncio.gather(
            self.get_finance_events(),
            self.get_economy_events(),
            return_exceptions=True,
        )

        # Gracefully handle exceptions from gather
        if isinstance(finance_events, BaseException):
            logger.error("Failed to fetch finance events: %s", finance_events)
            finance_events = []
        if isinstance(economy_events, BaseException):
            logger.error("Failed to fetch economy events: %s", economy_events)
            economy_events = []

        return {
            "finance": finance_events,
            "economy": economy_events,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "total_count": len(finance_events) + len(economy_events),
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close HTTP clients and release resources."""
        if self._gamma_client:
            await self._gamma_client.aclose()
            self._gamma_client = None
        if self._clob_client:
            await self._clob_client.aclose()
            self._clob_client = None

    async def __aenter__(self) -> "PolymarketAdapter":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[PolymarketAdapter] = None


def get_polymarket_adapter() -> PolymarketAdapter:
    """Get or create the singleton PolymarketAdapter instance."""
    global _instance
    if _instance is None:
        _instance = PolymarketAdapter()
    return _instance
