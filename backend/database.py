"""Async SQLAlchemy database configuration."""

import logging
import os
from collections.abc import AsyncGenerator

from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


def _ensure_sqlite_dir(database_url: str) -> None:
    """Create the parent directory for a SQLite database file if it doesn't exist."""
    if not database_url.startswith("sqlite"):
        return

    prefix = ":///"
    idx = database_url.find(prefix)
    if idx == -1:
        return
    file_path = database_url[idx + len(prefix):]

    if not file_path:
        return

    parent = os.path.dirname(file_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
        logger.info("Ensured database directory exists: %s", parent)


def _create_engine(database_url: str, debug: bool = False):
    """Create the async engine with dialect-appropriate settings."""
    if database_url.startswith("postgresql"):
        return create_async_engine(
            database_url,
            echo=debug,
            connect_args={"statement_cache_size": 0, "ssl": "require"},
            pool_size=3,
            max_overflow=2,
            pool_pre_ping=True,
        )
    else:
        # SQLite (tests or local dev fallback)
        _ensure_sqlite_dir(database_url)
        return create_async_engine(
            database_url,
            echo=debug,
        )


# Create async engine
engine = _create_engine(settings.DATABASE_URL, settings.DEBUG)

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
    """Get a SQL type string for a SQLAlchemy column."""
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
            "DATETIME": "TIMESTAMP" if engine.dialect.name == "postgresql" else "DATETIME",
            "JSON": "JSONB" if engine.dialect.name == "postgresql" else "JSON",
        }
        return type_map.get(type_name, "TEXT")


def _sync_migrate_missing_columns(connection) -> None:
    """Add any columns defined in models but missing from existing DB tables.

    Works for both PostgreSQL and SQLite. Uses SQLAlchemy inspector which
    is dialect-agnostic. The only difference is that SQLite requires columns
    added via ALTER TABLE to be nullable (or have a default) for existing rows,
    while PostgreSQL handles NOT NULL + DEFAULT properly.
    """
    dialect_name = connection.dialect.name
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
                if dialect_name == "sqlite":
                    # SQLite ALTER TABLE ADD COLUMN requires nullable or a
                    # default for existing rows, so force nullable if no default.
                    if nullable and not default_clause:
                        nullable = ""
                else:
                    # PostgreSQL handles NOT NULL + DEFAULT properly, but if
                    # there's no default and column is NOT NULL, we still need
                    # to allow NULL for existing rows.
                    if nullable and not default_clause:
                        nullable = ""
                ddl = f"ALTER TABLE {table_name} ADD COLUMN {column.name} {col_type}{nullable}{default_clause}"
                logger.info("Migrating: %s", ddl)
                connection.execute(text(ddl))


def _sync_fix_postgres_sequences(connection) -> None:
    """Reset PostgreSQL sequences to MAX(id)+1 to prevent primary key collisions.

    This handles cases where data was imported/migrated without updating
    the auto-increment sequences (e.g., after a SQLite→PostgreSQL migration).
    Only processes tables known to the ORM (Base.metadata) to avoid injection risk.
    """
    if connection.dialect.name != "postgresql":
        return

    for table_name, table in Base.metadata.tables.items():
        if "id" not in table.columns:
            continue
        seq_name = f"{table_name}_id_seq"
        # Use parameterized query via pg_sequences catalog to verify sequence exists
        seq_exists = connection.execute(
            text("SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = :seq"),
            {"seq": seq_name},
        ).scalar()
        if not seq_exists:
            continue
        try:
            # table_name is from Base.metadata (hardcoded ORM definitions), not user input
            result = connection.execute(
                text(f"SELECT setval('{seq_name}', COALESCE((SELECT MAX(id) FROM \"{table_name}\"), 0) + 1, false)")  # noqa: S608
            )
            new_val = result.scalar()
            if new_val and new_val > 1:
                logger.info("Fixed sequence %s → %s", seq_name, new_val)
        except Exception as seq_err:
            logger.debug("Could not fix sequence %s: %s", seq_name, seq_err)


async def init_db() -> None:
    """Initialize database tables and migrate missing columns."""
    async with engine.begin() as conn:
        # First, add any missing columns to existing tables
        await conn.run_sync(_sync_migrate_missing_columns)
        # Then create any entirely new tables
        await conn.run_sync(Base.metadata.create_all)
        # Fix PostgreSQL sequences to prevent primary key collisions
        await conn.run_sync(_sync_fix_postgres_sequences)


async def close_db() -> None:
    """Close database connections."""
    await engine.dispose()
