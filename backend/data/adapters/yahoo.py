"""Yahoo Finance data adapter for fetching stock data.

This module provides an async adapter for fetching stock data from Yahoo Finance
using the yfinance library. Since yfinance is blocking, all calls are wrapped
with asyncio.run_in_executor to maintain async compatibility.
"""

import asyncio
import logging
from datetime import date
from functools import partial
from typing import Any

import yfinance as yf  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


class YahooFinanceError(Exception):
    """Custom exception for Yahoo Finance adapter errors."""

    pass


class YahooFinanceAdapter:
    """Adapter for fetching stock data from Yahoo Finance.

    This adapter provides async methods for retrieving stock data from Yahoo Finance.
    All yfinance calls are blocking, so they are run in a thread pool executor
    to maintain async compatibility.

    Example:
        ```python
        adapter = YahooFinanceAdapter()
        info = await adapter.get_stock_info("AAPL")
        prices = await adapter.get_price_history("AAPL", period="1mo")
        ```
    """

    # Major indices and their ETF proxies
    INDICES = {
        "SPY": "S&P 500",
        "QQQ": "NASDAQ 100",
        "DIA": "Dow Jones",
        "IWM": "Russell 2000",
        "VTI": "Total Market",
    }

    # Sector ETFs
    SECTOR_ETFS = {
        "XLK": "Technology",
        "XLV": "Healthcare",
        "XLF": "Financials",
        "XLE": "Energy",
        "XLY": "Consumer Discretionary",
        "XLI": "Industrials",
        "XLB": "Materials",
        "XLU": "Utilities",
        "XLRE": "Real Estate",
        "XLC": "Communication Services",
        "XLP": "Consumer Staples",
    }

    # Valid periods for yfinance
    VALID_PERIODS = ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"]

    # Rate limiting: recommended delay between requests (seconds)
    REQUEST_DELAY = 0.1

    def __init__(self) -> None:
        """Initialize the Yahoo Finance adapter."""
        self._last_request_time: float = 0

    async def _run_blocking(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Run a blocking function in the thread pool executor.

        Args:
            func: The blocking function to run.
            *args: Positional arguments to pass to the function.
            **kwargs: Keyword arguments to pass to the function.

        Returns:
            The result of the function call.
        """
        loop = asyncio.get_event_loop()
        if kwargs:
            func_with_args = partial(func, *args, **kwargs)
            return await loop.run_in_executor(None, func_with_args)
        return await loop.run_in_executor(None, partial(func, *args))

    async def get_stock_info(self, symbol: str) -> dict[str, Any]:
        """Get stock metadata (name, sector, industry, market cap).

        Args:
            symbol: The stock ticker symbol (e.g., "AAPL").

        Returns:
            A dictionary containing stock metadata:
            - symbol: The stock symbol
            - name: Company name
            - sector: Business sector (e.g., "Technology")
            - industry: Specific industry
            - market_cap: Market capitalization in USD

        Raises:
            YahooFinanceError: If there's an error fetching the data.
        """
        try:
            logger.debug(f"Fetching stock info for {symbol}")
            ticker = await self._run_blocking(yf.Ticker, symbol)
            info = await self._run_blocking(lambda: ticker.info)

            # Check if we got valid data
            if not info or info.get("regularMarketPrice") is None:
                # Check if it's a valid ticker by looking for any price data
                if info.get("previousClose") is None and info.get("ask") is None:
                    raise YahooFinanceError(f"No data found for symbol: {symbol}")

            return {
                "symbol": symbol.upper(),
                "name": info.get("longName") or info.get("shortName", symbol),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "market_cap": info.get("marketCap"),
            }
        except YahooFinanceError:
            raise
        except Exception as e:
            logger.error(f"Error fetching info for {symbol}: {e}")
            raise YahooFinanceError(f"Failed to fetch info for {symbol}: {e}") from e

    async def get_price_history(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
        period: str = "1y",
    ) -> list[dict[str, Any]]:
        """Fetch historical OHLCV data.

        Args:
            symbol: The stock ticker symbol.
            start_date: Start date for historical data. If provided, period is ignored.
            end_date: End date for historical data. Defaults to today if start_date is provided.
            period: Time period for historical data (e.g., "1d", "1mo", "1y").
                   Ignored if start_date is provided.

        Returns:
            A list of dictionaries, each containing:
            - date: The trading date
            - open: Opening price
            - high: High price
            - low: Low price
            - close: Closing price
            - volume: Trading volume
            - adjusted_close: Adjusted closing price

        Raises:
            YahooFinanceError: If there's an error fetching the data.
        """
        try:
            logger.debug(f"Fetching price history for {symbol}")
            ticker = await self._run_blocking(yf.Ticker, symbol)

            # Determine how to fetch data
            if start_date:
                end = end_date or date.today()
                history = await self._run_blocking(
                    lambda: ticker.history(start=start_date.isoformat(), end=end.isoformat())
                )
            else:
                if period not in self.VALID_PERIODS:
                    logger.warning(f"Invalid period '{period}', defaulting to '1y'")
                    period = "1y"
                history = await self._run_blocking(lambda: ticker.history(period=period))

            if history.empty:
                logger.warning(f"No price history found for {symbol}")
                return []

            # Convert DataFrame to list of dicts
            result = []
            for idx, row in history.iterrows():
                result.append({
                    "date": idx.date() if hasattr(idx, "date") else idx,
                    "open": float(row["Open"]) if row["Open"] == row["Open"] else None,  # NaN check
                    "high": float(row["High"]) if row["High"] == row["High"] else None,
                    "low": float(row["Low"]) if row["Low"] == row["Low"] else None,
                    "close": float(row["Close"]) if row["Close"] == row["Close"] else None,
                    "volume": int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,
                    "adjusted_close": float(row.get("Adj Close", row["Close"]))
                        if row.get("Adj Close", row["Close"]) == row.get("Adj Close", row["Close"])
                        else None,
                })

            logger.info(f"Fetched {len(result)} price records for {symbol}")
            return result
        except YahooFinanceError:
            raise
        except Exception as e:
            logger.error(f"Error fetching price history for {symbol}: {e}")
            raise YahooFinanceError(f"Failed to fetch price history for {symbol}: {e}") from e

    async def get_current_price(self, symbol: str) -> dict[str, Any]:
        """Get current/latest price data.

        Args:
            symbol: The stock ticker symbol.

        Returns:
            A dictionary containing:
            - symbol: The stock symbol
            - price: Current price
            - previous_close: Previous day's closing price
            - change: Price change from previous close
            - change_percent: Percentage change from previous close
            - day_high: Today's high
            - day_low: Today's low
            - volume: Today's volume
            - timestamp: Time of the quote

        Raises:
            YahooFinanceError: If there's an error fetching the data.
        """
        try:
            logger.debug(f"Fetching current price for {symbol}")
            ticker = await self._run_blocking(yf.Ticker, symbol)
            info = await self._run_blocking(lambda: ticker.info)

            price = info.get("regularMarketPrice") or info.get("currentPrice")
            previous_close = info.get("previousClose") or info.get("regularMarketPreviousClose")

            if price is None:
                raise YahooFinanceError(f"No price data available for {symbol}")

            change = None
            change_percent = None
            if price and previous_close:
                change = price - previous_close
                change_percent = (change / previous_close) * 100

            return {
                "symbol": symbol.upper(),
                "price": price,
                "previous_close": previous_close,
                "change": change,
                "change_percent": change_percent,
                "day_high": info.get("dayHigh") or info.get("regularMarketDayHigh"),
                "day_low": info.get("dayLow") or info.get("regularMarketDayLow"),
                "volume": info.get("volume") or info.get("regularMarketVolume"),
                "timestamp": info.get("regularMarketTime"),
            }
        except YahooFinanceError:
            raise
        except Exception as e:
            logger.error(f"Error fetching current price for {symbol}: {e}")
            raise YahooFinanceError(f"Failed to fetch current price for {symbol}: {e}") from e

    async def get_multiple_prices(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        """Batch fetch current prices for multiple symbols.

        Uses asyncio.gather to fetch prices concurrently while respecting
        rate limits.

        Args:
            symbols: List of stock ticker symbols.

        Returns:
            A dictionary mapping symbols to their price data.
            Failed symbols will have an "error" key instead of price data.
        """
        logger.debug(f"Fetching prices for {len(symbols)} symbols")

        async def fetch_with_error_handling(symbol: str) -> tuple[str, dict[str, Any]]:
            try:
                # Add small delay to avoid rate limiting
                await asyncio.sleep(self.REQUEST_DELAY)
                data = await self.get_current_price(symbol)
                return symbol, data
            except YahooFinanceError as e:
                logger.warning(f"Failed to fetch {symbol}: {e}")
                return symbol, {"error": str(e), "symbol": symbol}

        tasks = [fetch_with_error_handling(symbol) for symbol in symbols]
        results = await asyncio.gather(*tasks)

        return {symbol: data for symbol, data in results}

    async def get_sector_performance(self) -> dict[str, dict[str, Any]]:
        """Get performance data for all sector ETFs.

        Returns:
            A dictionary mapping sector names to their performance data:
            - symbol: ETF symbol
            - name: Sector name
            - price: Current price
            - change_percent: Daily change percentage
            - ytd_return: Year-to-date return (if available)
        """
        logger.debug("Fetching sector performance data")

        results = {}
        prices = await self.get_multiple_prices(list(self.SECTOR_ETFS.keys()))

        for symbol, sector_name in self.SECTOR_ETFS.items():
            price_data = prices.get(symbol, {})

            if "error" in price_data:
                results[sector_name] = {
                    "symbol": symbol,
                    "name": sector_name,
                    "error": price_data["error"],
                }
            else:
                results[sector_name] = {
                    "symbol": symbol,
                    "name": sector_name,
                    "price": price_data.get("price"),
                    "change_percent": price_data.get("change_percent"),
                }

        return results

    async def get_index_performance(self) -> dict[str, dict[str, Any]]:
        """Get performance data for major market indices.

        Returns:
            A dictionary mapping index names to their performance data.
        """
        logger.debug("Fetching index performance data")

        results = {}
        prices = await self.get_multiple_prices(list(self.INDICES.keys()))

        for symbol, index_name in self.INDICES.items():
            price_data = prices.get(symbol, {})

            if "error" in price_data:
                results[index_name] = {
                    "symbol": symbol,
                    "name": index_name,
                    "error": price_data["error"],
                }
            else:
                results[index_name] = {
                    "symbol": symbol,
                    "name": index_name,
                    "price": price_data.get("price"),
                    "change_percent": price_data.get("change_percent"),
                    "previous_close": price_data.get("previous_close"),
                }

        return results

    async def search_symbols(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search for stock symbols matching a query.

        Args:
            query: Search query (company name or partial symbol).
            limit: Maximum number of results to return.

        Returns:
            A list of matching symbols with their metadata.
        """
        try:
            logger.debug(f"Searching for symbols matching: {query}")

            # yfinance doesn't have a direct search API, but we can use
            # the Ticker.info to validate a symbol
            # For now, just try the query as a symbol
            try:
                info = await self.get_stock_info(query.upper())
                return [info] if info.get("name") else []
            except YahooFinanceError:
                return []

        except Exception as e:
            logger.error(f"Error searching for symbols: {e}")
            return []


# Export singleton instance for convenience
yahoo_adapter = YahooFinanceAdapter()
