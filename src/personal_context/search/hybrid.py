"""Hybrid search combining semantic and keyword search."""

import sqlite3
from typing import List, Dict, Any, Optional
import json


def hybrid_search(
    conn: sqlite3.Connection,
    query: str,
    query_embedding: List[float],
    limit: int = 10,
    source_types: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Perform hybrid search combining vector similarity and FTS keyword search.

    Args:
        conn: Database connection
        query: Search query text
        query_embedding: Query embedding vector
        limit: Maximum number of results
        source_types: Optional filter by source types

    Returns:
        List of search results with combined scores
    """
    # Vector search using sqlite-vec
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
    k_limit = limit * 2

    vector_query = """
        SELECT
            c.id,
            c.source_type,
            c.source_url,
            c.title,
            c.content,
            c.metadata,
            c.upstream_doc_id,
            c.collection_id,
            c.created_at,
            vec.distance as vec_distance
        FROM content_vec vec
        JOIN content c ON vec.content_id = c.id
        WHERE vec.embedding MATCH ? AND k = ?
    """

    if source_types:
        placeholders = ",".join("?" * len(source_types))
        vector_query += f" AND c.source_type IN ({placeholders})"

    vector_query += " ORDER BY vec.distance"

    # Execute vector search
    if source_types:
        vector_results = conn.execute(vector_query, [embedding_str, k_limit] + source_types).fetchall()
    else:
        vector_results = conn.execute(vector_query, [embedding_str, k_limit]).fetchall()

    # FTS keyword search
    fts_query = """
        SELECT
            c.id,
            c.source_type,
            c.source_url,
            c.title,
            c.content,
            c.metadata,
            c.upstream_doc_id,
            c.collection_id,
            c.created_at,
            fts.rank as fts_rank
        FROM content_fts fts
        JOIN content c ON fts.rowid = c.id
        WHERE content_fts MATCH ?
    """

    if source_types:
        placeholders = ",".join("?" * len(source_types))
        fts_query += f" AND c.source_type IN ({placeholders})"

    fts_query += f" ORDER BY fts.rank LIMIT {limit * 2}"

    # Execute FTS search
    if source_types:
        fts_results = conn.execute(fts_query, [query] + source_types).fetchall()
    else:
        fts_results = conn.execute(fts_query, [query]).fetchall()

    # Combine results with scoring
    results_map = {}

    # Add vector results (lower distance = better)
    for row in vector_results:
        content_id = row["id"]
        # Normalize distance to 0-1 score (invert so higher is better)
        vec_score = 1.0 / (1.0 + row["vec_distance"])
        results_map[content_id] = {
            "id": row["id"],
            "source_type": row["source_type"],
            "source_url": row["source_url"],
            "title": row["title"],
            "content": row["content"],
            "metadata": json.loads(row["metadata"]) if row["metadata"] else None,
            "upstream_doc_id": row["upstream_doc_id"],
            "collection_id": row["collection_id"],
            "created_at": row["created_at"],
            "vec_score": vec_score,
            "fts_score": 0.0,
        }

    # Add/update with FTS results (rank is negative, higher is better)
    for row in fts_results:
        content_id = row["id"]
        # Normalize FTS rank to 0-1 score
        fts_score = abs(row["fts_rank"]) / 100.0  # Rough normalization

        if content_id in results_map:
            results_map[content_id]["fts_score"] = fts_score
        else:
            results_map[content_id] = {
                "id": row["id"],
                "source_type": row["source_type"],
                "source_url": row["source_url"],
                "title": row["title"],
                "content": row["content"],
                "metadata": json.loads(row["metadata"]) if row["metadata"] else None,
                "upstream_doc_id": row["upstream_doc_id"],
                "collection_id": row["collection_id"],
                "created_at": row["created_at"],
                "vec_score": 0.0,
                "fts_score": fts_score,
            }

    # Calculate combined score (weighted average)
    for result in results_map.values():
        result["score"] = 0.6 * result["vec_score"] + 0.4 * result["fts_score"]

    # Sort by combined score and return top results
    sorted_results = sorted(
        results_map.values(),
        key=lambda x: x["score"],
        reverse=True
    )

    return sorted_results[:limit]
