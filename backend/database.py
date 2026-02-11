"""Async SQLAlchemy database configuration."""

import logging
from collections.abc import AsyncGenerator

from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Create async engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
)

# Create async session factory
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""

    pass


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to get database session."""
    async with async_session_factory() as session:
        yield session


# Alias for FastAPI dependency injection
get_db = get_session


def _get_column_sql_type(column) -> str:
    """Get a SQLite-compatible type string for a SQLAlchemy column."""
    try:
        return column.type.compile(dialect=engine.dialect)
    except Exception:
        # Fallback for types that don't compile cleanly
        type_name = type(column.type).__name__.upper()
        type_map = {
            "STRING": f"VARCHAR({column.type.length})" if hasattr(column.type, "length") and column.type.length else "VARCHAR",
            "TEXT": "TEXT",
            "INTEGER": "INTEGER",
            "FLOAT": "FLOAT",
            "BOOLEAN": "BOOLEAN",
            "DATETIME": "DATETIME",
            "JSON": "JSON",
        }
        return type_map.get(type_name, "TEXT")


def _sync_migrate_missing_columns(connection) -> None:
    """Add any columns defined in models but missing from existing DB tables.

    SQLite's ``CREATE TABLE IF NOT EXISTS`` (used by ``create_all``) will
    never alter an existing table.  This helper inspects every registered
    model table, compares its columns against what SQLite actually has, and
    issues ``ALTER TABLE ... ADD COLUMN`` for each gap.
    """
    inspector = sa_inspect(connection)
    db_tables = set(inspector.get_table_names())

    for table_name, table in Base.metadata.tables.items():
        if table_name not in db_tables:
            # Table doesn't exist yet — create_all will handle it
            continue

        existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
        for column in table.columns:
            if column.name not in existing_cols:
                col_type = _get_column_sql_type(column)
                default_clause = ""
                if column.default is not None and column.default.arg is not None:
                    default_val = column.default.arg
                    if isinstance(default_val, str):
                        default_clause = f" DEFAULT '{default_val}'"
                    elif isinstance(default_val, (int, float)):
                        default_clause = f" DEFAULT {default_val}"
                nullable = "" if column.nullable else " NOT NULL"
                # SQLite ALTER TABLE ADD COLUMN requires nullable or a default
                # for existing rows, so force nullable if no default is set.
                if nullable and not default_clause:
                    nullable = ""
                ddl = f"ALTER TABLE {table_name} ADD COLUMN {column.name} {col_type}{nullable}{default_clause}"
                logger.info("Migrating: %s", ddl)
                connection.execute(text(ddl))


async def init_db() -> None:
    """Initialize database tables and migrate missing columns."""
    async with engine.begin() as conn:
        # First, add any missing columns to existing tables
        await conn.run_sync(_sync_migrate_missing_columns)
        # Then create any entirely new tables
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close database connections."""
    await engine.dispose()
