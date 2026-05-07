"""Bulk universe expansion: discover all ETF constituents and backfill missing ones.

Calls get_screening_universe() to fetch top-40 holdings from all configured
sector + innovation ETFs (400-600 symbols), then backfills price history for
any symbol not already in the DB. Safe to re-run — already-present symbols
are skipped.

Usage:
    cd backend && uv run python scripts/expand_universe_bulk.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import select, distinct, text
from database import async_session_factory, init_db
from models.stock import Stock
from scheduler.etl import ETLOrchestrator
from analysis.agents.universe_builder import get_screening_universe, _is_equity_symbol

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    await init_db()

    logger.info("Fetching screening universe from ETF constituents...")
    universe = await get_screening_universe()

    # Collect all equity symbols discovered
    discovered: set[str] = set()
    for category, symbols in universe.items():
        for sym in symbols:
            if _is_equity_symbol(sym):
                discovered.add(sym.upper())

    logger.info("Universe builder discovered %d unique equity symbols", len(discovered))

    # Find which are already in the DB
    async with async_session_factory() as session:
        result = await session.execute(select(distinct(Stock.symbol)))
        existing: set[str] = {row[0].upper() for row in result.fetchall()}

    logger.info("%d symbols already in DB, %d new to backfill",
                len(existing), len(discovered - existing))

    new_symbols = sorted(discovered - existing)
    if not new_symbols:
        logger.info("Nothing to do — all discovered symbols are already in DB")
        return

    logger.info("Backfilling %d new symbols: %s", len(new_symbols), new_symbols[:20],)
    orchestrator = ETLOrchestrator()
    results = await orchestrator.backfill_history(new_symbols, days=400)

    success = {s: n for s, n in results.items() if n > 0}
    failed = {s: n for s, n in results.items() if n == 0}

    logger.info("Done. %d succeeded, %d failed", len(success), len(failed))
    for sym, count in sorted(success.items()):
        logger.info("  + %s: %d price records", sym, count)
    if failed:
        logger.warning("  Failed (%d): %s", len(failed), sorted(failed.keys()))

    logger.info("Universe now has approximately %d symbols in DB",
                len(existing) + len(success))


if __name__ == "__main__":
    asyncio.run(main())
