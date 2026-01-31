"""FRED (Federal Reserve Economic Data) adapter for economic indicators."""

import asyncio
from datetime import date, timedelta
from functools import partial
from typing import Any, Optional

import pandas as pd  # type: ignore[import-untyped]
from fredapi import Fred  # type: ignore[import-untyped]

from config import get_settings


class FREDAdapter:
    """Adapter for FRED API - economic indicators."""

    # Key economic series to track
    SERIES = {
        "GDP": "Gross Domestic Product",
        "UNRATE": "Unemployment Rate",
        "CPIAUCSL": "Consumer Price Index",
        "FEDFUNDS": "Federal Funds Rate",
        "T10Y2Y": "10Y-2Y Treasury Spread (yield curve)",
        "VIXCLS": "VIX Volatility Index",
        "DGS10": "10-Year Treasury Rate",
        "DGS2": "2-Year Treasury Rate",
        "DTWEXBGS": "Trade Weighted Dollar Index",
        "UMCSENT": "Consumer Sentiment",
    }

    # Treasury maturities for yield curve (in months)
    TREASURY_SERIES = {
        1: "DGS1MO",  # 1 month
        3: "DGS3MO",  # 3 months
        6: "DGS6MO",  # 6 months
        12: "DGS1",   # 1 year
        24: "DGS2",   # 2 years
        60: "DGS5",   # 5 years
        84: "DGS7",   # 7 years
        120: "DGS10", # 10 years
        240: "DGS20", # 20 years
        360: "DGS30", # 30 years
    }

    def __init__(self):
        """Initialize the FRED adapter."""
        api_key = get_settings().FRED_API_KEY
        self._fred = Fred(api_key=api_key) if api_key else None

    @property
    def is_available(self) -> bool:
        """Check if the adapter is configured and available."""
        return self._fred is not None

    async def get_series(
        self,
        series_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict[str, Any]]:
        """Fetch a FRED data series.

        Args:
            series_id: The FRED series identifier (e.g., "GDP", "UNRATE")
            start_date: Start date for the data range
            end_date: End date for the data range

        Returns:
            List of dictionaries with date and value keys
        """
        if not self._fred:
            return []  # Graceful degradation

        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(
                None,
                partial(
                    self._fred.get_series,
                    series_id,
                    observation_start=start_date,
                    observation_end=end_date,
                ),
            )

            return [
                {"date": idx.date(), "value": float(val)}
                for idx, val in data.items()
                if not pd.isna(val)
            ]
        except Exception:
            return []  # Graceful degradation on error

    async def get_series_info(self, series_id: str) -> dict[str, Any]:
        """Get metadata about a series.

        Args:
            series_id: The FRED series identifier

        Returns:
            Dictionary with series metadata
        """
        if not self._fred:
            return {}

        loop = asyncio.get_event_loop()
        try:
            info = await loop.run_in_executor(
                None,
                partial(self._fred.get_series_info, series_id),
            )
            return {
                "id": info.get("id", series_id),
                "title": info.get("title", ""),
                "units": info.get("units", ""),
                "frequency": info.get("frequency", ""),
                "seasonal_adjustment": info.get("seasonal_adjustment", ""),
                "last_updated": str(info.get("last_updated", "")),
                "notes": info.get("notes", ""),
            }
        except Exception:
            return {}

    async def get_key_indicators(self) -> dict[str, dict[str, Any]]:
        """Fetch latest values for all key economic indicators.

        Returns:
            Dictionary mapping series ID to latest value and metadata
        """
        if not self._fred:
            return {}

        results: dict[str, dict[str, Any]] = {}
        # Get data from last 30 days to ensure we get latest value
        end_date = date.today()
        start_date = end_date - timedelta(days=90)

        for series_id, description in self.SERIES.items():
            data = await self.get_series(series_id, start_date, end_date)
            if data:
                latest = data[-1]
                results[series_id] = {
                    "description": description,
                    "value": latest["value"],
                    "date": latest["date"].isoformat(),
                }

        return results

    async def get_yield_curve(self) -> dict[str, float]:
        """Get current treasury yields for yield curve analysis.

        Returns:
            Dictionary mapping maturity (in months) to yield rate
        """
        if not self._fred:
            return {}

        # Get data from last 7 days
        end_date = date.today()
        start_date = end_date - timedelta(days=7)

        yields: dict[str, float] = {}
        for maturity_months, series_id in self.TREASURY_SERIES.items():
            data = await self.get_series(series_id, start_date, end_date)
            if data:
                # Get the most recent non-null value
                yields[str(maturity_months)] = data[-1]["value"]

        return yields

    async def get_latest_value(self, series_id: str) -> Optional[float]:
        """Get the latest value for a series.

        Args:
            series_id: The FRED series identifier

        Returns:
            The latest value or None if not available
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=30)
        data = await self.get_series(series_id, start_date, end_date)
        return data[-1]["value"] if data else None

    async def is_yield_curve_inverted(self) -> Optional[bool]:
        """Check if the yield curve is inverted (10Y < 2Y).

        Returns:
            True if inverted, False if not, None if data unavailable
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=7)

        dgs10 = await self.get_series("DGS10", start_date, end_date)
        dgs2 = await self.get_series("DGS2", start_date, end_date)

        if dgs10 and dgs2:
            return dgs10[-1]["value"] < dgs2[-1]["value"]
        return None


# Export singleton
fred_adapter = FREDAdapter()
