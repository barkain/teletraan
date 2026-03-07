"""Fix PostgreSQL primary key sequences for tables with auto-increment Integer IDs.

This script resets the auto-increment sequences to match the maximum ID in each table.
It's useful when you get "duplicate key value violates unique constraint" errors.

Usage:
    cd backend
    uv run python scripts/fix_pk_sequences.py
"""

import asyncio
import logging
import re

from sqlalchemy import text  # type: ignore[import-untyped]

from config import get_settings
from database import engine

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# Tables with Integer primary keys that need sequence fixing
TABLES_WITH_INT_PK = [
    "deep_insights",
    "economic",
    "indicator",
    "insight_conversations",
    "follow_up_research",
    "insight_research_contexts",
    "insights",
    "insight_items",
    "portfolios",
    "portfolio_holdings",
    "prices",
    "settings",
    "stocks",
]


def _validate_identifier(identifier: str) -> bool:
    """Validate that an identifier is safe (alphanumeric and underscores only)."""
    return bool(re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", identifier))


async def _get_max_id_raw(conn, table_name: str) -> int:
    """Get the maximum ID from a table using raw execution.

    Args:
        conn: AsyncSession connection
        table_name: Pre-validated table name (already validated with _validate_identifier)

    Returns:
        Maximum ID value or 0 if table is empty
    """
    # Table name is already validated by _validate_identifier() to contain only
    # alphanumeric characters and underscores, making it safe for SQL construction.
    raw_sql = f"SELECT COALESCE(MAX(id), 0) FROM {table_name}"  # noqa: S608
    result = await conn.exec_driver_sql(raw_sql)
    row = result.fetchone()
    return row[0] if row else 0


async def _get_sequence_name(conn, table_name: str) -> str | None:
    """Get the sequence name for a table's id column.

    Args:
        conn: AsyncSession connection
        table_name: Pre-validated table name

    Returns:
        Sequence name or None if not found
    """
    query = text(
        "SELECT pg_get_serial_sequence(:table_name, 'id')"
    )
    result = await conn.execute(query, {"table_name": table_name})
    return result.scalar()


async def _table_exists(conn, table_name: str) -> bool:
    """Check if a table exists.

    Args:
        conn: AsyncSession connection
        table_name: Pre-validated table name

    Returns:
        True if table exists, False otherwise
    """
    check_table = text(
        "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = :table_name)"
    )
    result = await conn.execute(check_table, {"table_name": table_name})
    return bool(result.scalar())


async def _fix_single_sequence(conn, table_name: str) -> None:
    """Fix a single sequence for a table.

    Args:
        conn: AsyncSession connection
        table_name: Pre-validated table name
    """
    try:
        # Check if the table exists
        exists = await _table_exists(conn, table_name)
        if not exists:
            logger.info("Table does not exist: %s. Skipping...", table_name)
            return

        # Get the sequence name
        seq_name = await _get_sequence_name(conn, table_name)
        if not seq_name:
            logger.info("No sequence found for table: %s. Skipping...", table_name)
            return

        # Get the current max ID
        max_id = await _get_max_id_raw(conn, table_name)
        next_val = max_id + 1

        # Use pg_catalog.setval with parameterized sequence name
        reset_seq = text("SELECT setval(:seq_name, :next_val)")
        await conn.execute(reset_seq, {"seq_name": seq_name, "next_val": next_val})

        logger.info(
            "Fixed sequence '%s' to %s (max existing id: %s)",
            seq_name,
            next_val,
            max_id,
        )

    except Exception as e:
        logger.warning(
            "Could not fix sequence for %s: %s. (The sequence or table may not exist, which is OK.)",
            table_name,
            e,
        )


async def fix_sequences() -> None:
    """Fix all auto-increment sequences for tables with Integer primary keys."""
    settings = get_settings()

    # Only works with PostgreSQL
    if not settings.DATABASE_URL.startswith("postgresql"):
        logger.warning("This script only works with PostgreSQL. Skipping...")
        return

    async with engine.begin() as conn:
        for table_name in TABLES_WITH_INT_PK:
            # Validate identifiers to prevent SQL injection
            if not _validate_identifier(table_name):
                logger.warning("Invalid table name: %s. Skipping...", table_name)
                continue

            await _fix_single_sequence(conn, table_name)

    logger.info("All sequences fixed successfully!")


async def main() -> None:
    """Main entry point."""
    try:
        await fix_sequences()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
