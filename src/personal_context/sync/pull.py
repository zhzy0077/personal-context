"""Pull sync logic for syncing from upstream knowledge bases to local database."""

import sqlite3
import time
from typing import Optional, List
from dataclasses import dataclass

from ..embeddings.client import EmbeddingClient
from ..upstream.base import UpstreamClient, UpstreamDocument


@dataclass
class PullResult:
    """Result of a pull sync operation."""
    created: int
    updated: int
    skipped: int
    errors: List[str]


async def pull_from_upstream(
    conn: sqlite3.Connection,
    upstream_client: UpstreamClient,
    embedding_client: EmbeddingClient,
    collection_id: str,
    upstream_provider: str = "upstream",
    last_pull_at: Optional[float] = None,
) -> PullResult:
    """
    Pull changes from upstream knowledge base to local database.

    Algorithm:
    1. Fetch documents from upstream (all if first sync, or updated since last_pull_at)
    2. For each document:
       - Check if exists locally (SELECT WHERE upstream_doc_id = ?)
       - If not exists: INSERT + generate embedding
       - If exists and upstream_updated_at > local upstream_updated_at: UPDATE + regenerate embedding
       - If exists and unchanged: SKIP
    3. Log operations to sync_log
    4. Update sync_state with new last_pull_at

    Args:
        conn: SQLite connection
        upstream_client: Upstream knowledge base client (protocol)
        embedding_client: Embedding API client
        collection_id: Collection ID to sync
        upstream_provider: Provider type for source_type field (e.g., 'outline', 'notion')
        last_pull_at: Unix timestamp of last successful pull (None for first sync)

    Returns:
        PullResult with statistics
    """
    created = 0
    updated = 0
    skipped = 0
    errors = []

    # Fetch documents with pagination
    offset = 0
    limit = 100
    should_continue = True

    while should_continue:
        try:
            # Fetch page of documents
            page = await upstream_client.list_documents(
                collection_id=collection_id,
                limit=limit,
                offset=offset,
            )

            if not page.documents:
                break  # No more documents

            for doc_summary in page.documents:
                doc_id = doc_summary.id
                upstream_updated_at = doc_summary.updated_at

                # Early termination optimization
                if last_pull_at and upstream_updated_at <= last_pull_at:
                    should_continue = False
                    break  # All remaining docs are older

                # Check if document exists locally
                local_doc = conn.execute(
                    "SELECT id, upstream_updated_at, collection_id FROM content WHERE upstream_doc_id = ?",
                    (doc_id,)
                ).fetchone()

                # Determine if we need to fetch full content
                needs_update = False
                if not local_doc:
                    needs_update = True  # New document
                elif not local_doc["upstream_updated_at"] or upstream_updated_at > local_doc["upstream_updated_at"]:
                    needs_update = True  # Updated document

                if local_doc and not local_doc["collection_id"]:
                    conn.execute(
                        "UPDATE content SET collection_id = ?, updated_at = unixepoch('now') WHERE id = ?",
                        (collection_id, local_doc["id"]),
                    )

                if not needs_update:
                    skipped += 1
                    continue

                # Fetch full document content
                try:
                    full_doc = await upstream_client.get_document(doc_id)

                    if not local_doc:
                        # Create new document
                        await _create_local_document(
                            conn, embedding_client, full_doc, collection_id, upstream_provider
                        )
                        created += 1
                    else:
                        # Update existing document
                        await _update_local_document(
                            conn,
                            embedding_client,
                            local_doc["id"],
                            full_doc,
                            collection_id,
                        )
                        updated += 1

                    # Log operation
                    conn.execute(
                        "INSERT INTO sync_log (collection_id, operation, upstream_doc_id) "
                        "VALUES (?, ?, ?)",
                        (collection_id, "create" if not local_doc else "update", doc_id)
                    )

                except Exception as e:
                    errors.append(f"Failed to sync {doc_id}: {str(e)}")
                    continue

            # Move to next page
            offset += limit

            # Check if there are more pages
            if not page.has_more:
                break

        except Exception as e:
            errors.append(f"Failed to fetch documents at offset {offset}: {str(e)}")
            break

    # Update sync state
    try:
        conn.execute(
            "INSERT OR REPLACE INTO sync_state (collection_id, last_pull_at, status, updated_at) "
            "VALUES (?, ?, 'idle', unixepoch('now'))",
            (collection_id, time.time())
        )
        conn.commit()
    except Exception as e:
        errors.append(f"Failed to update sync state: {str(e)}")

    return PullResult(created=created, updated=updated, skipped=skipped, errors=errors)


async def _create_local_document(
    conn: sqlite3.Connection,
    embedding_client: EmbeddingClient,
    doc: UpstreamDocument,
    collection_id: str,
    upstream_provider: str,
) -> None:
    """Create a new document in local database with embedding."""
    # Generate embedding
    embedding = await embedding_client.embed(doc.content)

    # Insert content
    cursor = conn.execute(
        """
        INSERT INTO content (
            source_type, source_id, collection_id, title, content,
            upstream_doc_id, upstream_updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            upstream_provider,
            doc.id,
            collection_id,
            doc.title,
            doc.content,
            doc.id,
            doc.updated_at,
        )
    )
    content_id = cursor.lastrowid

    # Store embedding
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
    conn.execute(
        "INSERT INTO content_vec (content_id, embedding) VALUES (?, ?)",
        (content_id, embedding_str)
    )

    conn.commit()


async def _update_local_document(
    conn: sqlite3.Connection,
    embedding_client: EmbeddingClient,
    content_id: int,
    doc: UpstreamDocument,
    collection_id: Optional[str] = None,
) -> None:
    """Update an existing document in local database with new embedding."""
    # Generate new embedding
    embedding = await embedding_client.embed(doc.content)

    # Update content
    conn.execute(
        """
        UPDATE content
        SET title = ?, content = ?, upstream_updated_at = ?, collection_id = ?, updated_at = unixepoch('now')
        WHERE id = ?
        """,
        (doc.title, doc.content, doc.updated_at, collection_id, content_id)
    )

    # Update embedding
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
    conn.execute(
        "INSERT OR REPLACE INTO content_vec (content_id, embedding) VALUES (?, ?)",
        (content_id, embedding_str)
    )

    conn.commit()
