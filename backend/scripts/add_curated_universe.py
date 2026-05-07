"""Add a curated list of ~300 well-known stocks to reach 400+ symbol universe.

Organized by sector. The backfill step is smart — it queries the DB first and
only backfills symbols not already present.

Usage:
    cd backend && uv run python scripts/add_curated_universe.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import select, distinct
from database import async_session_factory, init_db
from models.stock import Stock
from scheduler.etl import ETLOrchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

CURATED_SYMBOLS: list[str] = [
    # ── Mega-cap tech ──────────────────────────────────────────────────────────
    "ORCL", "IBM", "DELL", "HPE", "NTAP", "STX", "WDC",
    "PSTG", "PANW", "FTNT", "ZS", "CRWD", "OKTA", "SAIL",
    "SNOW", "DDOG", "MDB", "ESTC", "GTLB", "BILL", "HUBS",
    "PCTY", "PAYC", "TOST", "APP", "TTD", "TRADE",
    "AKAM", "FSLY", "CFLT", "DKNG", "HOOD",
    # ── Semiconductors ─────────────────────────────────────────────────────────
    "QCOM", "MCHP", "ON", "SWKS", "QRVO", "WOLF",
    "KLAC", "LRCX", "AMAT", "ASML", "ENTG", "CRUS", "SLAB",
    "SITM", "AMBA", "COHU", "FORM", "ONTO",
    # ── Large-cap Healthcare ────────────────────────────────────────────────────
    "LLY", "ABBV", "BMY", "GILD", "REGN", "MRNA", "VRTX", "BIIB",
    "AZN", "NVO", "RHHBY",
    "MDT", "BSX", "EW", "SYK", "ZBH", "HOLX", "ISRG",
    "DXCM", "VEEV", "OMCL", "PODD", "ALGN",
    "CI", "HUM", "MOH", "ELV", "CNC",
    "CVS", "MCK", "CAH", "ABC",
    "IDXX", "MASI", "TECH",
    # ── Financials ─────────────────────────────────────────────────────────────
    "V", "MA", "AXP", "DFS", "COF", "SYF",
    "GS", "MS", "BAC", "WFC", "USB", "TFC",
    "SCHW", "STT", "BK", "IVZ", "AMG",
    "LPLA", "RJF",
    "AON", "MMC", "WTW", "AJG", "BRO", "MKL",
    "AFL", "PRU", "MET", "LNC",
    "COIN", "MARA", "HOOD",
    # ── Industrials & Infrastructure ───────────────────────────────────────────
    "CAT", "DE", "DOV", "ITW", "PH", "ROK", "EMR", "ETN", "CARR",
    "UPS", "FDX", "XPO", "CHRW", "EXPD", "SAIA", "ODFL",
    "WM", "RSG", "CWST", "SRCL",
    "LMT", "RTX", "GD", "NOC", "L3H", "TDG", "HEICO",
    "ROP", "AMETEK", "HUBB", "AOS", "GGG",
    "TREX", "BLDR", "MAS", "OC",
    # ── Consumer Discretionary ─────────────────────────────────────────────────
    "NKE", "LULU", "TJX", "ROST", "DG", "DLTR", "FIVE",
    "MCD", "YUM", "DPZ", "CMG", "SBUX", "QSR",
    "GM", "F", "RIVN", "LCID",
    "ABNB", "BKNG", "EXPE", "MAR", "HLT", "H", "RCL", "CCL",
    "ORLY", "AZO", "TSCO",
    "WSM", "RH", "ETSY",
    "CHWY", "CHEWY",
    # ── Consumer Staples ───────────────────────────────────────────────────────
    "PG", "KO", "PEP", "MO", "PM", "MDLZ", "HSY", "GIS", "K",
    "CL", "CHD", "ENR", "CLX",
    "WMT", "COST", "TGT",
    # ── Energy ─────────────────────────────────────────────────────────────────
    "XOM", "CVX", "COP", "EOG", "DVN", "MPC", "VLO", "PSX",
    "OXY", "SLB", "HAL", "BKR",
    "ENPH", "FSLR", "RUN",
    "CTRA", "PR", "SM",
    # ── Utilities ──────────────────────────────────────────────────────────────
    "NEE", "DUK", "SO", "AEP", "EXC", "D", "PCG", "SRE", "XEL",
    "AWK", "WEC", "ES",
    # ── REITs ──────────────────────────────────────────────────────────────────
    "AMT", "CCI", "VICI", "O", "STAG", "PLD", "PSA",
    "EXR", "CUBE", "LSI",
    "KIM", "REG", "FRT",
    "WPC", "NNN",
    # ── Materials ──────────────────────────────────────────────────────────────
    "LIN", "APD", "ECL", "PPG", "SHW",
    "NEM", "GOLD", "AEM",
    "FCX", "SCCO", "AA", "NUE", "STLD",
    # ── International ADRs ─────────────────────────────────────────────────────
    "BABA", "JD", "PDD", "BIDU",
    "SONY", "TM", "HMC",
    "SAP", "ASML", "ERIC", "NOK",
    "SE", "MELI", "NU",
    "RIO", "BHP", "VALE",
]

# Deduplicate while preserving order
_seen: set[str] = set()
CURATED_SYMBOLS = [s for s in CURATED_SYMBOLS if not (_seen.add(s) or s in _seen - {s})]


async def main() -> None:
    await init_db()

    async with async_session_factory() as session:
        result = await session.execute(select(distinct(Stock.symbol)))
        existing: set[str] = {row[0].upper() for row in result.fetchall()}

    logger.info("%d symbols already in DB", len(existing))

    new_symbols = [s for s in CURATED_SYMBOLS if s.upper() not in existing]
    logger.info("%d curated symbols, %d already present, %d to backfill",
                len(CURATED_SYMBOLS), len(CURATED_SYMBOLS) - len(new_symbols), len(new_symbols))

    if not new_symbols:
        logger.info("Nothing to do — all curated symbols already in DB")
        return

    orchestrator = ETLOrchestrator()
    results = await orchestrator.backfill_history(new_symbols, days=400)

    success = {s: n for s, n in results.items() if n > 0}
    failed = {s: n for s, n in results.items() if n == 0}

    logger.info("Done. %d succeeded, %d failed/not-found", len(success), len(failed))
    for sym, count in sorted(success.items()):
        logger.info("  + %s: %d records", sym, count)
    if failed:
        logger.warning("  Not found / delisted (%d): %s", len(failed), sorted(failed.keys()))

    logger.info("Universe now ~%d symbols in DB", len(existing) + len(success))


if __name__ == "__main__":
    asyncio.run(main())
