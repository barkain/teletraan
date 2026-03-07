"""Database dialect utilities for cross-dialect upsert support."""


def dialect_insert(bind):
    """Return the dialect-specific ``insert`` function for upsert support.

    Uses ``postgresql.insert`` when connected to PostgreSQL (production)
    and ``sqlite.insert`` when connected to SQLite (tests).
    """
    dialect_name = bind.dialect.name
    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
        return insert
    else:
        from sqlalchemy.dialects.sqlite import insert
        return insert
