"""Migration script to add new columns to deep_insights and create analysis_tasks table.

This migration adds:
1. New columns to deep_insights table:
   - entry_zone
   - target_price
   - stop_loss
   - timeframe
   - discovery_context

2. Creates the analysis_tasks table if it doesn't exist

SQLite ALTER TABLE only supports adding columns, not modifying or dropping them.
This script safely handles the case where columns/tables already exist.

Usage:
    cd backend && uv run python scripts/migrate_add_insight_columns.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add backend directory to path for imports
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import text  # type: ignore[import-not-found]
from sqlalchemy.exc import OperationalError  # type: ignore[import-not-found]

from database import engine, init_db  # type: ignore[import-not-found]

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Columns to add to deep_insights table
# Format: (column_name, column_type)
NEW_COLUMNS = [
    ("entry_zone", "VARCHAR(50)"),
    ("target_price", "VARCHAR(50)"),
    ("stop_loss", "VARCHAR(50)"),
    ("timeframe", "VARCHAR(30)"),
    ("discovery_context", "JSON"),
]


async def column_exists(conn, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
    columns = result.fetchall()
    column_names = [col[1] for col in columns]
    return column_name in column_names


async def table_exists(conn, table_name: str) -> bool:
    """Check if a table exists in the database."""
    result = await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table_name}
    )
    return result.fetchone() is not None


async def add_column_if_not_exists(
    conn, table_name: str, column_name: str, column_type: str
) -> bool:
    """Add a column to a table if it doesn't already exist.

    Returns True if column was added, False if it already existed.
    """
    if await column_exists(conn, table_name, column_name):
        logger.info(f"  Column '{column_name}' already exists in '{table_name}' - skipping")
        return False

    # SQLite ALTER TABLE ADD COLUMN syntax
    alter_sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
    await conn.execute(text(alter_sql))
    logger.info(f"  Added column '{column_name}' ({column_type}) to '{table_name}'")
    return True


async def migrate_deep_insights_columns() -> dict:
    """Add new columns to the deep_insights table.

    Returns dict with migration results.
    """
    results = {
        "columns_added": [],
        "columns_skipped": [],
        "errors": [],
    }

    async with engine.begin() as conn:
        # Check if table exists first
        if not await table_exists(conn, "deep_insights"):
            logger.warning("Table 'deep_insights' does not exist - will be created by init_db")
            return results

        for column_name, column_type in NEW_COLUMNS:
            try:
                added = await add_column_if_not_exists(
                    conn, "deep_insights", column_name, column_type
                )
                if added:
                    results["columns_added"].append(column_name)
                else:
                    results["columns_skipped"].append(column_name)
            except OperationalError as e:
                error_msg = f"Failed to add '{column_name}': {e}"
                logger.error(f"  {error_msg}")
                results["errors"].append(error_msg)

    return results


async def create_analysis_tasks_table() -> bool:
    """Create analysis_tasks table using SQLAlchemy's create_all.

    This relies on the AnalysisTask model being imported and registered
    with Base.metadata. create_all() will only create tables that don't exist.

    Returns True if table was created or already existed.
    """
    # Import the model to ensure it's registered with Base
    from models.analysis_task import AnalysisTask  # type: ignore[import-not-found]  # noqa: F401

    async with engine.begin() as conn:
        if await table_exists(conn, "analysis_tasks"):
            logger.info("Table 'analysis_tasks' already exists - skipping creation")
            return True

    # Use init_db to create the table - it will only create missing tables
    await init_db()
    logger.info("Table 'analysis_tasks' created successfully")
    return True


async def verify_schema() -> dict:
    """Verify the schema after migration.

    Returns dict with table info.
    """
    results = {}

    async with engine.begin() as conn:
        # Check deep_insights columns
        if await table_exists(conn, "deep_insights"):
            result = await conn.execute(text("PRAGMA table_info(deep_insights)"))
            columns = result.fetchall()
            results["deep_insights"] = {
                "exists": True,
                "columns": [col[1] for col in columns],
            }
        else:
            results["deep_insights"] = {"exists": False}

        # Check analysis_tasks table
        if await table_exists(conn, "analysis_tasks"):
            result = await conn.execute(text("PRAGMA table_info(analysis_tasks)"))
            columns = result.fetchall()
            results["analysis_tasks"] = {
                "exists": True,
                "columns": [col[1] for col in columns],
            }
        else:
            results["analysis_tasks"] = {"exists": False}

    return results


async def main() -> None:
    """Main entry point for the migration script."""
    logger.info("=" * 60)
    logger.info("Market Analyzer - Database Migration Script")
    logger.info("=" * 60)
    logger.info("")

    # Step 1: Ensure base tables exist
    logger.info("Step 1: Initializing database (creating any missing tables)...")
    await init_db()
    logger.info("Done.")
    logger.info("")

    # Step 2: Add new columns to deep_insights
    logger.info("Step 2: Adding new columns to deep_insights table...")
    column_results = await migrate_deep_insights_columns()

    if column_results["columns_added"]:
        logger.info(f"  Added {len(column_results['columns_added'])} columns: {column_results['columns_added']}")
    if column_results["columns_skipped"]:
        logger.info(f"  Skipped {len(column_results['columns_skipped'])} existing columns: {column_results['columns_skipped']}")
    if column_results["errors"]:
        logger.error(f"  Errors: {column_results['errors']}")
    logger.info("")

    # Step 3: Create analysis_tasks table
    logger.info("Step 3: Creating analysis_tasks table (if needed)...")
    await create_analysis_tasks_table()
    logger.info("")

    # Step 4: Verify schema
    logger.info("Step 4: Verifying final schema...")
    schema = await verify_schema()

    logger.info("")
    logger.info("=" * 60)
    logger.info("MIGRATION RESULTS")
    logger.info("=" * 60)

    if schema["deep_insights"]["exists"]:
        logger.info(f"deep_insights table: {len(schema['deep_insights']['columns'])} columns")
        # Check for new columns
        new_col_names = [c[0] for c in NEW_COLUMNS]
        present = [c for c in new_col_names if c in schema["deep_insights"]["columns"]]
        missing = [c for c in new_col_names if c not in schema["deep_insights"]["columns"]]
        logger.info(f"  New columns present: {present}")
        if missing:
            logger.warning(f"  New columns MISSING: {missing}")
    else:
        logger.error("deep_insights table does not exist!")

    if schema["analysis_tasks"]["exists"]:
        logger.info(f"analysis_tasks table: {len(schema['analysis_tasks']['columns'])} columns")
        logger.info(f"  Columns: {schema['analysis_tasks']['columns']}")
    else:
        logger.error("analysis_tasks table does not exist!")

    logger.info("")
    logger.info("Migration complete!")


if __name__ == "__main__":
    asyncio.run(main())
