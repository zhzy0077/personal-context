"""MCP server implementation with FastMCP."""

import base64
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.templating import Jinja2Templates

from .config import settings
from .db import get_connection
from .embeddings import EmbeddingClient
from .search import hybrid_search
from .upstream import UpstreamRegistry
from .sync.orchestrator import SyncOrchestrator


# Global instances
embedding_client: Optional[EmbeddingClient] = None
upstream_registry: Optional[UpstreamRegistry] = None
sync_orchestrator: Optional[SyncOrchestrator] = None

# Set up Jinja2 templates
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

# Add base64 filter for template
def base64_encode(value: str) -> str:
    """Encode a string to base64."""
    return base64.b64encode(value.encode()).decode()

templates.env.filters['base64'] = base64_encode


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Middleware for HTTP Basic Authentication."""

    async def dispatch(self, request: Request, call_next):
        # Check if auth is enabled
        if not settings.is_http_auth_enabled():
            return await call_next(request)

        # Get Authorization header
        auth_header = request.headers.get("Authorization")

        if not auth_header or not auth_header.startswith("Basic "):
            return Response(
                content="Unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Personal Context Store"'},
            )

        try:
            # Decode credentials
            encoded_credentials = auth_header.split(" ")[1]
            decoded_credentials = base64.b64decode(encoded_credentials).decode("utf-8")
            username, password = decoded_credentials.split(":", 1)

            # Verify credentials
            if (
                username == settings.http_auth_username
                and password == settings.http_auth_password
            ):
                return await call_next(request)
            else:
                return Response(
                    content="Unauthorized",
                    status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="Personal Context Store"'},
                )
        except Exception:
            return Response(
                content="Unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Personal Context Store"'},
            )


# Create FastMCP server (lifespan will be managed by main.py)
mcp = FastMCP(
    "personal-context",
    host=settings.http_host,
    port=settings.http_port,
)


# Helper functions for index page
def format_timestamp(ts: float | None) -> str:
    """Convert Unix epoch timestamp to human-readable format."""
    if ts is None:
        return "Never"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def get_index_stats() -> dict:
    """Gather statistics for the index page."""
    conn = get_connection()

    # Total document count
    total_docs = conn.execute("SELECT COUNT(*) as count FROM content").fetchone()["count"]

    # Documents by source type
    by_source = conn.execute(
        """
        SELECT source_type, COUNT(*) as count
        FROM content
        GROUP BY source_type
        ORDER BY count DESC
        """
    ).fetchall()

    # Documents by collection
    by_collection = conn.execute(
        """
        SELECT collection_id, COUNT(*) as count
        FROM content
        WHERE collection_id IS NOT NULL
        GROUP BY collection_id
        ORDER BY count DESC
        """
    ).fetchall()

    # Get configured providers
    configured_providers = settings.get_configured_providers()

    # Get active providers from registry
    active_providers = []
    if upstream_registry:
        active_providers = upstream_registry.get_providers()

    # Sync status for all collections
    sync_status = conn.execute(
        """
        SELECT collection_id, last_pull_at, status, error_message, updated_at
        FROM sync_state
        ORDER BY updated_at DESC
        """
    ).fetchall()

    # Recent documents
    recent_docs = conn.execute(
        """
        SELECT id, title, source_type, collection_id, created_at
        FROM content
        ORDER BY created_at DESC
        LIMIT 5
        """
    ).fetchall()

    # Total tags
    total_tags = conn.execute("SELECT COUNT(*) as count FROM tags").fetchone()["count"]

    return {
        "total_docs": total_docs,
        "by_source": [{"source_type": row["source_type"], "count": row["count"]} for row in by_source],
        "by_collection": [{"collection_id": row["collection_id"], "count": row["count"]} for row in by_collection],
        "sync_status": [
            {
                "collection_id": row["collection_id"],
                "last_pull_at": row["last_pull_at"],
                "status": row["status"],
                "error_message": row["error_message"],
                "updated_at": row["updated_at"],
            }
            for row in sync_status
        ],
        "recent_docs": [
            {
                "id": row["id"],
                "title": row["title"],
                "source_type": row["source_type"],
                "collection_id": row["collection_id"],
                "created_at": row["created_at"],
            }
            for row in recent_docs
        ],
        "total_tags": total_tags,
        "configured_providers": configured_providers,
        "active_providers": active_providers,
    }


# Custom routes
@mcp.custom_route("/", methods=["GET"])
async def index_page(request: Request) -> HTMLResponse:
    """HTML index page showing document statistics and sync status."""
    stats = get_index_stats()

    # Prepare template context
    context = {
        "request": request,
        "stats": stats,
        "format_timestamp": format_timestamp,
        "auth_enabled": settings.is_http_auth_enabled(),
        "auth_username": settings.http_auth_username if settings.is_http_auth_enabled() else None,
        "auth_password": settings.http_auth_password if settings.is_http_auth_enabled() else None,
    }

    return templates.TemplateResponse("index.html", context)


@mcp.custom_route("/api/stats", methods=["GET"])
async def stats_api(request: Request) -> JSONResponse:
    """JSON API endpoint for statistics."""
    stats = get_index_stats()

    # Format timestamps for JSON
    for item in stats['sync_status']:
        item['last_pull_at_formatted'] = format_timestamp(item['last_pull_at'])
        item['updated_at_formatted'] = format_timestamp(item['updated_at'])

    for doc in stats['recent_docs']:
        doc['created_at_formatted'] = format_timestamp(doc['created_at'])

    return JSONResponse(content=stats)


@mcp.custom_route("/api/reindex", methods=["POST"])
async def reindex_api(request: Request) -> JSONResponse:
    """API endpoint to trigger reindexing of all embeddings."""
    try:
        # Check if embedding client is initialized
        if not embedding_client:
            return JSONResponse(
                content={
                    "error": "Embedding client not initialized. Server may still be starting up. Please wait a moment and try again."
                },
                status_code=503
            )

        result = await reindex_embeddings()
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            content={"error": str(e)},
            status_code=500
        )


@mcp.custom_route("/api/resync", methods=["POST"])
async def resync_api(request: Request) -> JSONResponse:
    """API endpoint to trigger full resync from upstream."""
    try:
        # Check if clients are initialized
        if not embedding_client or not upstream_registry or not sync_orchestrator:
            return JSONResponse(
                content={
                    "error": "Server not fully initialized. Please wait a moment and try again."
                },
                status_code=503
            )

        result = await full_resync()
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            content={"error": str(e)},
            status_code=500
        )


@mcp.tool()
async def search(
    query: str,
    limit: int = 10,
    source_types: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Search content using hybrid semantic and keyword search.

    Args:
        query: Search query text
        limit: Maximum number of results (default: 10)
        source_types: Optional list of source types to filter by (e.g., ['web', 'manual'])

    Returns:
        List of matching content with scores
    """
    if not embedding_client:
        raise RuntimeError("Embedding client not initialized")

    # Generate query embedding
    query_embedding = await embedding_client.embed(query)

    # Perform hybrid search
    conn = get_connection()
    results = hybrid_search(
        conn=conn,
        query=query,
        query_embedding=query_embedding,
        limit=limit,
        source_types=source_types,
    )

    # Format results for output
    formatted_results = []
    for result in results:
        formatted_results.append({
            "id": result["id"],
            "title": result["title"],
            "content": result["content"][:500] + "..." if len(result["content"]) > 500 else result["content"],
            "source_type": result["source_type"],
            "source_url": result["source_url"],
            "score": round(result["score"], 4),
            "upstream_doc_id": result["upstream_doc_id"],
            "collection_id": result["collection_id"],
        })

    return formatted_results


@mcp.tool()
async def add_content(
    content: str,
    title: str,
    source_type: str = "manual",
    tags: Optional[List[str]] = None,
    collection_id: Optional[str] = None,
    source_url: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Add content to the store and sync to upstream knowledge base.

    Args:
        content: Content text
        title: Content title
        source_type: Type of source (default: 'manual')
        tags: Optional list of tags
        collection_id: Optional collection ID
        source_url: Optional source URL
        metadata: Optional metadata dictionary
        provider: Optional provider name (e.g., 'outline', 'trilium'). Uses default if not specified.

    Returns:
        Dictionary with content_id and upstream_doc_id
    """
    if not embedding_client or not upstream_registry:
        raise RuntimeError("Clients not initialized")

    # Determine which provider to use
    if provider:
        upstream_client = upstream_registry.get(provider)
        if not upstream_client:
            raise ValueError(f"Provider '{provider}' not configured. Available: {upstream_registry.get_providers()}")
        provider_name = provider
    else:
        # Use default provider from settings
        provider_name = settings.upstream_provider
        upstream_client = upstream_registry.get(provider_name)
        if not upstream_client:
            # Fall back to first available provider
            providers = upstream_registry.get_providers()
            if not providers:
                raise RuntimeError("No upstream providers configured")
            provider_name = providers[0]
            upstream_client = upstream_registry.get(provider_name)

    conn = get_connection()

    # Generate embedding
    embedding = await embedding_client.embed(content)

    # Create document in upstream knowledge base
    upstream_doc_id = await upstream_client.create_document(
        title=title,
        content=content,
        collection_id=collection_id,
    )

    # Store in local database
    cursor = conn.execute(
        """
        INSERT INTO content (source_type, source_url, collection_id, title, content, metadata, upstream_doc_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            provider_name,  # Use provider name as source_type
            source_url,
            collection_id,
            title,
            content,
            json.dumps(metadata) if metadata else None,
            upstream_doc_id,
        ),
    )
    content_id = cursor.lastrowid

    # Store embedding
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
    conn.execute(
        "INSERT INTO content_vec (content_id, embedding) VALUES (?, ?)",
        (content_id, embedding_str),
    )

    # Add tags if provided
    if tags:
        for tag_name in tags:
            # Get or create tag
            cursor = conn.execute(
                "INSERT OR IGNORE INTO tags (name) VALUES (?)",
                (tag_name,),
            )
            tag_id = cursor.lastrowid
            if tag_id == 0:
                tag_id = conn.execute(
                    "SELECT id FROM tags WHERE name = ?",
                    (tag_name,),
                ).fetchone()[0]

            # Link tag to content
            conn.execute(
                "INSERT OR IGNORE INTO content_tags (content_id, tag_id) VALUES (?, ?)",
                (content_id, tag_id),
            )

    conn.commit()

    return {
        "content_id": content_id,
        "upstream_doc_id": upstream_doc_id,
        "provider": provider_name,
        "message": f"Content added successfully to {provider_name}",
    }


@mcp.tool()
async def get_content(content_id: int) -> Dict[str, Any]:
    """
    Retrieve content by ID.

    Args:
        content_id: Content ID

    Returns:
        Content details
    """
    conn = get_connection()

    row = conn.execute(
        """
        SELECT id, source_type, source_url, title, content, metadata,
               upstream_doc_id, collection_id, created_at, updated_at
        FROM content
        WHERE id = ?
        """,
        (content_id,),
    ).fetchone()

    if not row:
        raise ValueError(f"Content with ID {content_id} not found")

    # Get tags
    tags = conn.execute(
        """
        SELECT t.name
        FROM tags t
        JOIN content_tags ct ON t.id = ct.tag_id
        WHERE ct.content_id = ?
        """,
        (content_id,),
    ).fetchall()

    return {
        "id": row["id"],
        "source_type": row["source_type"],
        "source_url": row["source_url"],
        "title": row["title"],
        "content": row["content"],
        "metadata": json.loads(row["metadata"]) if row["metadata"] else None,
        "upstream_doc_id": row["upstream_doc_id"],
        "collection_id": row["collection_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "tags": [tag["name"] for tag in tags],
    }


@mcp.tool()
async def load_personal_prompts() -> str:
    """
    Load personal prompts from the configured collection.

    Returns:
        Concatenated prompt text
    """
    collection_id = settings.prompts_collection_id
    if not collection_id:
        raise ValueError("PERSONAL_CONTEXT_PROMPTS_COLLECTION_ID is not configured")

    conn = get_connection()
    rows = conn.execute(
        """
        SELECT content
        FROM content
        WHERE collection_id = ?
        ORDER BY upstream_updated_at DESC, created_at DESC
        """,
        (collection_id,),
    ).fetchall()

    if not rows:
        raise ValueError(f"No prompts found for collection_id={collection_id}")

    return "\n\n".join(row["content"] for row in rows)


# Helper functions for API endpoints (not exposed as MCP tools)
async def reindex_embeddings() -> Dict[str, Any]:
    """
    Regenerate embeddings for all content in the database.

    Use this when you change the embedding model or dimension.
    This will recreate the content_vec table with the current dimension
    and regenerate embeddings using the current model.

    Returns:
        Statistics about the reindexing operation (total, success, errors)
    """
    if not embedding_client:
        raise RuntimeError("Embedding client not initialized")

    conn = get_connection()

    # Drop and recreate content_vec table with current dimension
    try:
        conn.execute("DROP TABLE IF EXISTS content_vec")

        embedding_dim = settings.embedding_dimension
        conn.execute(f"""
            CREATE VIRTUAL TABLE content_vec USING vec0(
                content_id INTEGER PRIMARY KEY,
                embedding float[{embedding_dim}]
            )
        """)
        conn.commit()
    except Exception as e:
        raise RuntimeError(f"Failed to recreate content_vec table: {str(e)}")

    # Get all content
    rows = conn.execute(
        "SELECT id, content FROM content ORDER BY id"
    ).fetchall()

    total = len(rows)
    success = 0
    errors = 0
    error_details = []

    for row in rows:
        content_id = row["id"]
        content_text = row["content"]

        try:
            # Generate new embedding
            embedding = await embedding_client.embed(content_text)
            embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

            # Insert new embedding (table was just recreated, so no need to update)
            conn.execute(
                "INSERT INTO content_vec (content_id, embedding) VALUES (?, ?)",
                (content_id, embedding_str),
            )

            success += 1

        except Exception as e:
            errors += 1
            error_details.append(f"Content ID {content_id}: {str(e)}")

    conn.commit()

    return {
        "total": total,
        "success": success,
        "errors": errors,
        "error_details": error_details[:10] if error_details else [],  # Limit to first 10 errors
        "message": f"Reindexing complete: {success}/{total} successful, {errors} errors",
    }


async def full_resync(collection_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Clear all local content and resync from upstream.

    This will:
    1. Delete all content, embeddings, and tags from local database
    2. Reset sync state
    3. Pull all documents from specified collections (or all configured collections)

    Args:
        collection_ids: Optional list of collection IDs to sync (uses configured collections if not provided)

    Returns:
        Statistics about the resync operation (collections synced, documents created, errors)
    """
    if not sync_orchestrator:
        raise RuntimeError("Sync orchestrator not initialized")

    return await sync_orchestrator.full_resync(collection_ids)
