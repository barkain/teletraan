"""Add data-center adjacent and quality compounder stocks to the universe.

These are the Category-2 stocks that Scorer B (mean-reversion) structurally
misses — industrial enablers of AI infrastructure and quality compounders with
secular tailwinds. The Quality/Growth scorer will surface them.

Usage:
    cd backend && uv run python scripts/expand_universe.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from database import async_session_factory, init_db
from scheduler.etl import ETLOrchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Data-center adjacent industrials + quality compounders missing from the universe
NEW_SYMBOLS = [
    # Data-center construction / power / cooling
    "FIX",   # Comfort Systems USA — HVAC/mechanical for data centers
    "VRT",   # Vertiv Holdings — data center power & thermal management
    "TT",    # Trane Technologies — HVAC leader
    "EME",   # EMCOR Group — electrical/mechanical contracting
    "IESC",  # IES Holdings — electrical infrastructure for data centers
    "GEV",   # GE Vernova — power grid / generation
    "HUBB",  # Hubbell Inc — electrical products
    "POWL",  # Powell Industries — electrical switchgear
    # Quality compounders (secular growth, not tech)
    "MSCI",  # MSCI Inc — financial data & analytics
    "ICE",   # Intercontinental Exchange — financial infrastructure
    "CME",   # CME Group — derivatives exchange
    "WSO",   # Watsco — HVAC distribution
    "FAST",  # Fastenal — industrial distribution
    "NVR",   # NVR Inc — homebuilder (quality, low debt)
    "DECK",  # Deckers (HOKA/UGG) — footwear compounder
]


async def main() -> None:
    await init_db()
    orchestrator = ETLOrchestrator()

    end_date = date.today()
    start_date = end_date - timedelta(days=400)  # ~16 months for scorer warmup

    logger.info("Expanding universe with %d new symbols...", len(NEW_SYMBOLS))
    results = await orchestrator.backfill_history(NEW_SYMBOLS, days=400)

    success = {s: n for s, n in results.items() if n > 0}
    failed = {s: n for s, n in results.items() if n == 0}

    logger.info("Done. %d succeeded, %d failed", len(success), len(failed))
    for sym, count in sorted(success.items()):
        logger.info("  ✓ %s: %d price records", sym, count)
    for sym in sorted(failed):
        logger.warning("  ✗ %s: 0 records (check symbol)", sym)


if __name__ == "__main__":
    asyncio.run(main())
