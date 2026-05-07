"""Backfill 2 years of daily price history for all stocks in the DB.

Run once to give the backtester sufficient data:
    uv run python scripts/seed_price_history_2y.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import date, timedelta

import yfinance as yf

sys.path.insert(0, "/workspace/extra/teletraan/backend")

from database import async_session_factory, init_db
from models.price import PriceHistory
from models.stock import Stock
from sqlalchemy import select, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

END_DATE = date.today()
START_DATE = END_DATE - timedelta(days=730)  # 2 years


async def get_symbols(db) -> list[tuple[int, str]]:
    result = await db.execute(select(Stock.id, Stock.symbol).where(Stock.is_active == True))
    return result.fetchall()


async def get_existing_dates(db, stock_id: int) -> set[str]:
    result = await db.execute(
        text("SELECT date FROM price_history WHERE stock_id = :sid AND date >= :start"),
        {"sid": stock_id, "start": START_DATE.isoformat()},
    )
    return {str(row[0]) for row in result.fetchall()}


async def seed_symbol(stock_id: int, symbol: str) -> int:
    """Each symbol gets its own session to isolate failures."""
    ticker = yf.Ticker(symbol)
    df = ticker.history(start=START_DATE.isoformat(), end=END_DATE.isoformat(), auto_adjust=True)
    if df.empty:
        logger.warning("%s: no data from yfinance", symbol)
        return 0

    rows_to_insert: list[dict] = []
    for ts, row in df.iterrows():
        d = ts.date() if hasattr(ts, "date") else ts
        rows_to_insert.append({
            "stock_id": stock_id,
            "date": d,
            "open": float(row.get("Open", 0) or 0),
            "high": float(row.get("High", 0) or 0),
            "low": float(row.get("Low", 0) or 0),
            "close": float(row.get("Close", 0) or 0),
            "volume": int(row.get("Volume", 0) or 0),
            "adjusted_close": None,
        })

    if not rows_to_insert:
        return 0

    async with async_session_factory() as db:
        existing = await get_existing_dates(db, stock_id)
        new_rows = [r for r in rows_to_insert if str(r["date"]) not in existing]
        if not new_rows:
            return 0
        for r in new_rows:
            db.add(PriceHistory(**r))
        try:
            await db.commit()
            return len(new_rows)
        except Exception as exc:
            await db.rollback()
            logger.warning("%s: commit failed — %s", symbol, exc)
            return 0


async def main() -> None:
    await init_db()
    async with async_session_factory() as db:
        symbols = await get_symbols(db)

    logger.info("Seeding 2-year history for %d symbols (%s → %s)", len(symbols), START_DATE, END_DATE)

    total = 0
    for i, (stock_id, symbol) in enumerate(symbols):
        try:
            n = await seed_symbol(stock_id, symbol)
            total += n
            if (i + 1) % 10 == 0:
                logger.info("Progress: %d/%d symbols, %d rows inserted so far", i + 1, len(symbols), total)
        except Exception as exc:
            logger.warning("Failed %s: %s", symbol, exc)

    logger.info("Done. Total rows inserted: %d", total)


if __name__ == "__main__":
    asyncio.run(main())
