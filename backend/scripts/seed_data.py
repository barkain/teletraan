"""Seed script to populate the Teletraan database with initial stock data.

This script fetches data for a small set of symbols to verify the database
and data pipeline are working correctly.

Usage:
    cd backend && uv run python scripts/seed_data.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add backend directory to path for imports
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import select, func  # type: ignore[import-not-found]
from sqlalchemy.dialects.sqlite import insert as sqlite_insert  # type: ignore[import-not-found]

from config import get_settings  # type: ignore[import-not-found]
from database import async_session_factory, init_db  # type: ignore[import-not-found]
from data.adapters.yahoo import YahooFinanceAdapter, YahooFinanceError  # type: ignore[import-not-found]
from models.stock import Stock  # type: ignore[import-not-found]
from models.price import PriceHistory  # type: ignore[import-not-found]

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Symbols to seed
SYMBOLS = [
    # Index ETFs
    "SPY", "QQQ", "DIA", "IWM",
    # Sector ETFs
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLI",
    # Tech stocks
    "AAPL", "MSFT", "GOOGL", "NVDA", "META", "AMZN", "TSLA",
    # Diversified
    "JPM", "JNJ", "XOM", "WMT"
]
SEED_SYMBOLS = SYMBOLS  # Keep backward compatibility


async def seed_stock(
    adapter: YahooFinanceAdapter,
    symbol: str,
) -> dict:
    """Fetch and store data for a single stock.

    Args:
        adapter: Yahoo Finance adapter instance
        symbol: Stock ticker symbol

    Returns:
        Dict with results: symbol, stock_created, prices_stored, error
    """
    result = {
        "symbol": symbol,
        "stock_created": False,
        "prices_stored": 0,
        "error": None,
    }

    async with async_session_factory() as session:
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
            await session.execute(stmt)
            await session.commit()
            result["stock_created"] = True

            # Get the stock ID
            stock_result = await session.execute(
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
                await session.execute(stmt)
                result["prices_stored"] += 1

            await session.commit()
            logger.info(f"  -> Stored {result['prices_stored']} price records")

        except YahooFinanceError as e:
            result["error"] = str(e)
            logger.error(f"  -> Error: {e}")
            await session.rollback()
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"  -> Unexpected error: {e}")
            await session.rollback()

    return result


async def get_table_counts() -> dict:
    """Get record counts from database tables.

    Returns:
        Dict with table names and counts
    """
    async with async_session_factory() as session:
        stock_count = await session.execute(
            select(func.count()).select_from(Stock)
        )
        price_count = await session.execute(
            select(func.count()).select_from(PriceHistory)
        )

        return {
            "stocks": stock_count.scalar(),
            "price_history": price_count.scalar(),
        }


async def main() -> None:
    """Main entry point for the seed script."""
    logger.info("=" * 60)
    logger.info("Teletraan - Database Seed Script")
    logger.info("=" * 60)

    settings = get_settings()
    logger.info(f"Database URL: {settings.DATABASE_URL}")
    logger.info(f"Symbols to seed: {SEED_SYMBOLS}")
    logger.info("")

    # Initialize database tables
    logger.info("Initializing database tables...")
    await init_db()
    logger.info("Database tables ready.")
    logger.info("")

    # Create adapter
    adapter = YahooFinanceAdapter()

    # Seed each symbol
    results = []
    for symbol in SEED_SYMBOLS:
        logger.info(f"Processing {symbol}...")
        result = await seed_stock(adapter, symbol)
        results.append(result)
        # Small delay to avoid rate limiting
        await asyncio.sleep(0.5)
        logger.info("")

    # Print summary
    logger.info("=" * 60)
    logger.info("SEED RESULTS SUMMARY")
    logger.info("=" * 60)

    successful = [r for r in results if r["error"] is None]
    failed = [r for r in results if r["error"] is not None]

    logger.info(f"Successful: {len(successful)}/{len(results)}")
    for r in successful:
        logger.info(f"  - {r['symbol']}: {r['prices_stored']} prices")

    if failed:
        logger.info(f"Failed: {len(failed)}/{len(results)}")
        for r in failed:
            logger.info(f"  - {r['symbol']}: {r['error']}")

    logger.info("")

    # Get final counts
    counts = await get_table_counts()
    logger.info("DATABASE RECORD COUNTS:")
    logger.info(f"  - stocks table: {counts['stocks']} records")
    logger.info(f"  - price_history table: {counts['price_history']} records")
    logger.info("")
    logger.info("Seed complete!")


if __name__ == "__main__":
    asyncio.run(main())
