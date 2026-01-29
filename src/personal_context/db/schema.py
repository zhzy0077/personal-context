"""Database schema definitions."""

import sqlite3
from ..config import settings


def migrate_schema(conn: sqlite3.Connection) -> None:
    """Run schema migrations for existing databases."""

    # Migration: Rename outline_* columns to upstream_*
    cursor = conn.execute("PRAGMA table_info(content)")
    columns = {row[1] for row in cursor.fetchall()}

    if "outline_doc_id" in columns:
        # Rename outline_doc_id to upstream_doc_id
        conn.execute("ALTER TABLE content RENAME COLUMN outline_doc_id TO upstream_doc_id")
        print("Migrated: outline_doc_id → upstream_doc_id")

    if "outline_updated_at" in columns:
        # Rename outline_updated_at to upstream_updated_at
        conn.execute("ALTER TABLE content RENAME COLUMN outline_updated_at TO upstream_updated_at")
        print("Migrated: outline_updated_at → upstream_updated_at")

    # Check sync_log table
    cursor = conn.execute("PRAGMA table_info(sync_log)")
    sync_log_columns = {row[1] for row in cursor.fetchall()}

    if "outline_doc_id" in sync_log_columns:
        # Rename outline_doc_id to upstream_doc_id in sync_log
        conn.execute("ALTER TABLE sync_log RENAME COLUMN outline_doc_id TO upstream_doc_id")
        print("Migrated: sync_log.outline_doc_id → upstream_doc_id")

    # Recreate index with new name if old one exists
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_content_outline_doc'"
    )
    if cursor.fetchone():
        conn.execute("DROP INDEX idx_content_outline_doc")
        conn.execute("CREATE INDEX idx_content_upstream_doc ON content(upstream_doc_id)")
        print("Migrated: idx_content_outline_doc → idx_content_upstream_doc")

    conn.commit()


def create_schema(conn: sqlite3.Connection) -> None:
    """Create database tables and indexes."""

    # Main content storage
    conn.execute("""
        CREATE TABLE IF NOT EXISTS content (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,
            source_id TEXT,
            source_url TEXT,
            collection_id TEXT,
            title TEXT,
            content TEXT NOT NULL,
            metadata TEXT,
            upstream_doc_id TEXT,
            upstream_updated_at REAL,
            created_at REAL DEFAULT (unixepoch('now')),
            updated_at REAL DEFAULT (unixepoch('now')),
            UNIQUE(source_type, source_id)
        )
    """)

    # FTS5 for keyword search
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(
            title, content,
            content='content', content_rowid='id',
            tokenize='porter unicode61'
        )
    """)

    # Triggers to keep FTS in sync
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS content_ai AFTER INSERT ON content BEGIN
            INSERT INTO content_fts(rowid, title, content)
            VALUES (new.id, new.title, new.content);
        END
    """)

    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS content_ad AFTER DELETE ON content BEGIN
            DELETE FROM content_fts WHERE rowid = old.id;
        END
    """)

    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS content_au AFTER UPDATE ON content BEGIN
            UPDATE content_fts SET title = new.title, content = new.content
            WHERE rowid = new.id;
        END
    """)

    # sqlite-vec for semantic search
    embedding_dim = settings.embedding_dimension
    conn.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS content_vec USING vec0(
            content_id INTEGER PRIMARY KEY,
            embedding float[{embedding_dim}]
        )
    """)

    # Tags
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS content_tags (
            content_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            PRIMARY KEY(content_id, tag_id),
            FOREIGN KEY(content_id) REFERENCES content(id) ON DELETE CASCADE,
            FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
        )
    """)

    # Sync state tracking
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sync_state (
            collection_id TEXT PRIMARY KEY,
            last_pull_at REAL,
            status TEXT DEFAULT 'idle',
            error_message TEXT,
            created_at REAL DEFAULT (unixepoch('now')),
            updated_at REAL DEFAULT (unixepoch('now'))
        )
    """)

    # Sync operation log
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            collection_id TEXT,
            operation TEXT NOT NULL,
            content_id INTEGER,
            upstream_doc_id TEXT,
            details TEXT,
            created_at REAL DEFAULT (unixepoch('now')),
            FOREIGN KEY(content_id) REFERENCES content(id) ON DELETE SET NULL
        )
    """)

    # Indexes
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_content_source
        ON content(source_type, source_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_content_upstream_doc
        ON content(upstream_doc_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_content_created
        ON content(created_at DESC)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_content_collection
        ON content(collection_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sync_log_collection
        ON sync_log(collection_id, created_at DESC)
    """)
