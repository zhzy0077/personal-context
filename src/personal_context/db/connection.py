"""SQLite database connection with sqlite-vec support."""

import sqlite3
from typing import Optional

import sqlite_vec

from ..config import settings


_connection: Optional[sqlite3.Connection] = None


def get_connection() -> sqlite3.Connection:
    """Get or create the database connection."""
    global _connection

    if _connection is None:
        db_path = settings.db_path
        _connection = sqlite3.connect(str(db_path), check_same_thread=False)
        _connection.row_factory = sqlite3.Row

        # Enable foreign keys
        _connection.execute("PRAGMA foreign_keys = ON")

        _connection.enable_load_extension(True)
        sqlite_vec.load(_connection)
        _connection.enable_load_extension(False)

    return _connection


def init_db() -> None:
    """Initialize the database schema."""
    from .schema import create_schema, migrate_schema

    conn = get_connection()

    # Run migrations first (for existing databases)
    migrate_schema(conn)

    # Then create/update schema
    create_schema(conn)
    conn.commit()


def close_connection() -> None:
    """Close the database connection."""
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None
