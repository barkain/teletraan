"""Data management API endpoints for refreshing stock data."""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from analysis.engine import AnalysisEngine
from analysis.deep_engine import deep_analysis_engine
from api.deps import get_db
from data.adapters.yahoo import YahooFinanceAdapter, YahooFinanceError
from models.stock import Stock
from models.price import PriceHistory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data", tags=["data"])

# Default symbols to refresh when none provided
DEFAULT_SYMBOLS = ["SPY", "QQQ", "AAPL", "MSFT", "GOOGL", "NVDA", "META", "AMZN"]


class RefreshRequest(BaseModel):
    """Request body for the data refresh endpoint."""

    symbols: list[str] | None = Field(
        default=None,
        description="List of stock symbols to refresh. If not provided, defaults to major symbols.",
        examples=[["AAPL", "MSFT", "GOOGL"]],
    )


class RefreshResponse(BaseModel):
    """Response body for the data refresh endpoint."""

    status: str = Field(description="Status of the refresh operation")
    symbols_updated: list[str] = Field(description="List of symbols successfully updated")
    records_added: int = Field(description="Total number of price records added/updated")
    insights_generated: int = Field(
        default=0, description="Number of insights generated from analysis"
    )
    deep_insights_generated: int = Field(
        default=0, description="Number of deep insights generated from multi-agent analysis"
    )
    errors: list[dict[str, str]] | None = Field(
        default=None, description="List of errors encountered, if any"
    )
    analysis_error: str | None = Field(
        default=None, description="Error message if analysis failed"
    )


async def refresh_single_symbol(
    adapter: YahooFinanceAdapter,
    symbol: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """Fetch and store data for a single stock.

    Args:
        adapter: Yahoo Finance adapter instance
        symbol: Stock ticker symbol
        db: Database session

    Returns:
        Dict with results: symbol, success, prices_stored, error
    """
    result: dict[str, Any] = {
        "symbol": symbol.upper(),
        "success": False,
        "prices_stored": 0,
        "error": None,
    }

    try:
        # Step 1: Fetch stock info
        logger.info(f"Fetching info for {symbol}...")
        info = await adapter.get_stock_info(symbol)

        # Step 2: Insert or update stock record
        stmt = sqlite_insert(Stock).values(
            symbol=info["symbol"],
            name=info.get("name", symbol),
            sector=info.get("sector"),
            industry=info.get("industry"),
            market_cap=info.get("market_cap"),
            is_active=True,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol"],
            set_={
                "name": stmt.excluded.name,
                "sector": stmt.excluded.sector,
                "industry": stmt.excluded.industry,
                "market_cap": stmt.excluded.market_cap,
            },
        )
        await db.execute(stmt)
        await db.commit()

        # Get the stock ID
        stock_result = await db.execute(
            select(Stock).where(Stock.symbol == symbol.upper())
        )
        stock = stock_result.scalar_one()

        logger.info(f"  -> Stock record: {stock.name} (ID: {stock.id})")

        # Step 3: Fetch 30 days of price history
        logger.info(f"Fetching price history for {symbol}...")
        prices = await adapter.get_price_history(symbol, period="1mo")

        # Step 4: Store price history
        for price_data in prices:
            if price_data.get("close") is None or price_data.get("date") is None:
                continue

            stmt = sqlite_insert(PriceHistory).values(
                stock_id=stock.id,
                date=price_data["date"],
                open=price_data.get("open", 0),
                high=price_data.get("high", 0),
                low=price_data.get("low", 0),
                close=price_data["close"],
                volume=price_data.get("volume", 0),
                adjusted_close=price_data.get("adjusted_close"),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["stock_id", "date"],
                set_={
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                    "adjusted_close": stmt.excluded.adjusted_close,
                },
            )
            await db.execute(stmt)
            result["prices_stored"] += 1

        await db.commit()
        result["success"] = True
        logger.info(f"  -> Stored {result['prices_stored']} price records for {symbol}")

    except YahooFinanceError as e:
        result["error"] = str(e)
        logger.error(f"  -> Yahoo Finance error for {symbol}: {e}")
        await db.rollback()
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"  -> Unexpected error for {symbol}: {e}")
        await db.rollback()

    return result


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_data(
    request: RefreshRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> RefreshResponse:
    """Refresh stock data from Yahoo Finance.

    Fetches stock info and recent price history (30 days) for the specified symbols.
    If no symbols are provided, refreshes data for default major symbols.

    Args:
        request: Optional request body with symbols list
        db: Database session

    Returns:
        RefreshResponse with status, updated symbols, and record counts
    """
    # Determine which symbols to refresh
    symbols = DEFAULT_SYMBOLS
    if request and request.symbols:
        # Validate and normalize symbols
        symbols = [s.upper().strip() for s in request.symbols if s.strip()]
        if not symbols:
            raise HTTPException(
                status_code=400,
                detail="At least one valid symbol must be provided",
            )

    logger.info(f"Starting data refresh for {len(symbols)} symbols: {symbols}")

    # Create adapter
    adapter = YahooFinanceAdapter()

    # Process each symbol
    symbols_updated: list[str] = []
    errors: list[dict[str, str]] = []
    total_records = 0

    for symbol in symbols:
        result = await refresh_single_symbol(adapter, symbol, db)

        if result["success"]:
            symbols_updated.append(result["symbol"])
            total_records += result["prices_stored"]
        else:
            errors.append({
                "symbol": result["symbol"],
                "error": result["error"] or "Unknown error",
            })

        # Small delay to avoid rate limiting
        await asyncio.sleep(0.5)

    # Determine overall status
    if not symbols_updated:
        status = "failed"
    elif errors:
        status = "partial"
    else:
        status = "success"

    logger.info(
        f"Data refresh complete: {len(symbols_updated)}/{len(symbols)} symbols updated, "
        f"{total_records} records added"
    )

    # Run analysis on successfully updated symbols
    insights_generated = 0
    deep_insights_generated = 0
    analysis_error: str | None = None

    if symbols_updated:
        try:
            logger.info(f"Running analysis for {len(symbols_updated)} symbols...")
            engine = AnalysisEngine()
            analysis_results = await engine.run_full_analysis(symbols_updated)
            insights_generated = analysis_results.get("insights_generated", 0)
            logger.info(f"Analysis complete: {insights_generated} insights generated")
        except Exception as e:
            analysis_error = str(e)
            logger.error(f"Analysis failed: {e}")

        # Run deep multi-agent analysis
        try:
            logger.info(f"Running deep analysis for {len(symbols_updated)} symbols...")
            deep_insights = await deep_analysis_engine.run_and_store(symbols_updated)
            deep_insights_generated = len(deep_insights.get("insights", []))
            logger.info(f"Deep analysis generated {deep_insights_generated} insights")
        except Exception as e:
            logger.error(f"Deep analysis failed: {e}")
            # Don't fail the whole request, just log

    return RefreshResponse(
        status=status,
        symbols_updated=symbols_updated,
        records_added=total_records,
        insights_generated=insights_generated,
        deep_insights_generated=deep_insights_generated,
        errors=errors if errors else None,
        analysis_error=analysis_error,
    )


@router.post("/deep-analysis")
async def run_deep_analysis(
    symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Trigger deep multi-agent analysis.

    Runs the deep analysis engine which uses multiple AI analysts
    to generate comprehensive market insights.

    Args:
        symbols: Optional list of symbols to analyze. If not provided,
                 analyzes all active symbols in the database.

    Returns:
        Dict with analysis results including insights count and elapsed time.
    """
    try:
        result = await deep_analysis_engine.run_and_store(symbols)
        return {
            "status": "success",
            "insights_generated": len(result.get("insights", [])),
            "analysts_used": result.get("analysts_completed", []),
            "elapsed_time": result.get("elapsed_time"),
        }
    except Exception as e:
        logger.error(f"Deep analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
