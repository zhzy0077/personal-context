"""MCP server implementation with FastMCP."""

import base64
import json
from datetime import datetime
from typing import List, Optional, Dict, Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

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

    # Build HTML
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Personal Context Store</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                background: #f5f5f5;
                color: #333;
                line-height: 1.6;
                padding: 20px;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
                background: white;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            h1 {{
                color: #2c3e50;
                margin-bottom: 10px;
                font-size: 2em;
            }}
            .subtitle {{
                color: #7f8c8d;
                margin-bottom: 30px;
                font-size: 1.1em;
            }}
            .summary-cards {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 20px;
                margin-bottom: 30px;
            }}
            .card {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 20px;
                border-radius: 8px;
                text-align: center;
            }}
            .card.secondary {{
                background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            }}
            .card.tertiary {{
                background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            }}
            .card-value {{
                font-size: 2.5em;
                font-weight: bold;
                margin-bottom: 5px;
            }}
            .card-label {{
                font-size: 0.9em;
                opacity: 0.9;
            }}
            h2 {{
                color: #2c3e50;
                margin: 30px 0 15px 0;
                font-size: 1.5em;
                border-bottom: 2px solid #667eea;
                padding-bottom: 5px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 30px;
            }}
            th, td {{
                padding: 12px;
                text-align: left;
                border-bottom: 1px solid #e0e0e0;
            }}
            th {{
                background: #f8f9fa;
                font-weight: 600;
                color: #2c3e50;
            }}
            tr:hover {{
                background: #f8f9fa;
            }}
            .status {{
                display: inline-block;
                padding: 4px 12px;
                border-radius: 12px;
                font-size: 0.85em;
                font-weight: 600;
            }}
            .status.idle {{
                background: #d4edda;
                color: #155724;
            }}
            .status.syncing {{
                background: #fff3cd;
                color: #856404;
            }}
            .status.error {{
                background: #f8d7da;
                color: #721c24;
            }}
            .truncate {{
                max-width: 300px;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }}
            .footer {{
                margin-top: 40px;
                padding-top: 20px;
                border-top: 1px solid #e0e0e0;
                color: #7f8c8d;
                font-size: 0.9em;
            }}
            .footer a {{
                color: #667eea;
                text-decoration: none;
            }}
            .footer a:hover {{
                text-decoration: underline;
            }}
            code {{
                background: #f4f4f4;
                padding: 2px 6px;
                border-radius: 3px;
                font-family: 'Courier New', monospace;
            }}
            .actions {{
                margin: 30px 0;
                padding: 20px;
                background: #f8f9fa;
                border-radius: 8px;
                border-left: 4px solid #667eea;
            }}
            .btn {{
                display: inline-block;
                padding: 10px 20px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                font-size: 14px;
                font-weight: 600;
                transition: transform 0.2s, box-shadow 0.2s;
            }}
            .btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
            }}
            .btn:active {{
                transform: translateY(0);
            }}
            .btn:disabled {{
                opacity: 0.6;
                cursor: not-allowed;
                transform: none;
            }}
            .btn.warning {{
                background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            }}
            .btn.warning:hover {{
                box-shadow: 0 4px 12px rgba(245, 87, 108, 0.4);
            }}
            #reindex-status {{
                margin-top: 10px;
                padding: 10px;
                border-radius: 5px;
                display: none;
            }}
            #reindex-status.success {{
                background: #d4edda;
                color: #155724;
                display: block;
            }}
            #reindex-status.error {{
                background: #f8d7da;
                color: #721c24;
                display: block;
            }}
            #reindex-status.loading {{
                background: #fff3cd;
                color: #856404;
                display: block;
            }}
            #resync-status {{
                margin-top: 10px;
                padding: 10px;
                border-radius: 5px;
                display: none;
            }}
            #resync-status.success {{
                background: #d4edda;
                color: #155724;
                display: block;
            }}
            #resync-status.error {{
                background: #f8d7da;
                color: #721c24;
                display: block;
            }}
            #resync-status.loading {{
                background: #fff3cd;
                color: #856404;
                display: block;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Personal Context Store</h1>
            <p class="subtitle">AI-powered knowledge management with semantic search</p>

            <div class="summary-cards">
                <div class="card">
                    <div class="card-value">{stats['total_docs']}</div>
                    <div class="card-label">Total Documents</div>
                </div>
                <div class="card secondary">
                    <div class="card-value">{stats['total_tags']}</div>
                    <div class="card-label">Total Tags</div>
                </div>
                <div class="card tertiary">
                    <div class="card-value">{len(stats['sync_status'])}</div>
                    <div class="card-label">Synced Collections</div>
                </div>
            </div>

            <h2>Configured Upstream Providers</h2>
            <table>
                <thead>
                    <tr>
                        <th>Provider</th>
                        <th>Status</th>
                        <th>Documents</th>
                    </tr>
                </thead>
                <tbody>
    """

    # Show configured providers
    if stats['configured_providers']:
        for provider in stats['configured_providers']:
            is_active = provider in stats['active_providers']
            status_badge = '<span class="status idle">✓ Active</span>' if is_active else '<span class="status error">✗ Inactive</span>'

            # Count documents from this provider
            doc_count = next((item['count'] for item in stats['by_source'] if item['source_type'] == provider), 0)

            html += f"""
                    <tr>
                        <td><strong>{provider.capitalize()}</strong></td>
                        <td>{status_badge}</td>
                        <td>{doc_count} documents</td>
                    </tr>
            """
    else:
        html += """
                    <tr>
                        <td colspan="3" style="text-align: center; color: #7f8c8d;">
                            No upstream providers configured. Add API credentials to .env to enable sync.
                        </td>
                    </tr>
        """

    html += """
                </tbody>
            </table>

            <div class="actions">
                <h3 style="margin-top: 0; margin-bottom: 10px; color: #2c3e50;">Actions</h3>
                <p style="margin-bottom: 15px; color: #7f8c8d; font-size: 0.9em;">
                    Regenerate embeddings for all documents when you change the embedding model or dimension.
                    This will automatically recreate the vector table with the current settings.
                </p>
                <button id="reindex-btn" class="btn" onclick="reindexEmbeddings()">
                    Reindex All Embeddings
                </button>
                <div id="reindex-status"></div>

                <hr style="margin: 25px 0; border: none; border-top: 1px solid #e0e0e0;">

                <p style="margin-bottom: 15px; color: #7f8c8d; font-size: 0.9em;">
                    <strong>⚠️ Warning:</strong> Full resync will delete all local content and re-download from upstream.
                    Use this to recover from sync issues or data corruption.
                </p>
                <button id="resync-btn" class="btn warning" onclick="fullResync()">
                    Full Resync from Upstream
                </button>
                <div id="resync-status"></div>
            </div>

            <h2>Documents by Source Type</h2>
            <table>
                <thead>
                    <tr>
                        <th>Source Type</th>
                        <th>Count</th>
                    </tr>
                </thead>
                <tbody>
    """

    if stats['by_source']:
        for item in stats['by_source']:
            html += f"""
                    <tr>
                        <td>{item['source_type']}</td>
                        <td>{item['count']}</td>
                    </tr>
            """
    else:
        html += """
                    <tr>
                        <td colspan="2" style="text-align: center; color: #7f8c8d;">No documents yet</td>
                    </tr>
        """

    html += """
                </tbody>
            </table>

            <h2>Sync Status</h2>
            <table>
                <thead>
                    <tr>
                        <th>Collection ID</th>
                        <th>Last Sync</th>
                        <th>Status</th>
                        <th>Error</th>
                    </tr>
                </thead>
                <tbody>
    """

    if stats['sync_status']:
        for item in stats['sync_status']:
            status_class = item['status']
            collection_id_short = item['collection_id'][:16] + "..." if len(item['collection_id']) > 16 else item['collection_id']
            error_msg = item['error_message'] if item['error_message'] else "-"
            html += f"""
                    <tr>
                        <td class="truncate" title="{item['collection_id']}">{collection_id_short}</td>
                        <td>{format_timestamp(item['last_pull_at'])}</td>
                        <td><span class="status {status_class}">{item['status']}</span></td>
                        <td class="truncate" title="{error_msg}">{error_msg}</td>
                    </tr>
            """
    else:
        html += """
                    <tr>
                        <td colspan="4" style="text-align: center; color: #7f8c8d;">No sync status available</td>
                    </tr>
        """

    html += """
                </tbody>
            </table>

            <h2>Recent Documents</h2>
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Title</th>
                        <th>Source</th>
                        <th>Created</th>
                    </tr>
                </thead>
                <tbody>
    """

    if stats['recent_docs']:
        for doc in stats['recent_docs']:
            title_short = doc['title'][:50] + "..." if len(doc['title']) > 50 else doc['title']
            html += f"""
                    <tr>
                        <td>{doc['id']}</td>
                        <td class="truncate" title="{doc['title']}">{title_short}</td>
                        <td>{doc['source_type']}</td>
                        <td>{format_timestamp(doc['created_at'])}</td>
                    </tr>
            """
    else:
        html += """
                    <tr>
                        <td colspan="4" style="text-align: center; color: #7f8c8d;">No documents yet</td>
                    </tr>
        """

    html += """
                </tbody>
            </table>

            <div class="footer">
                <p><strong>API Endpoints:</strong></p>
                <ul style="margin-top: 10px; margin-left: 20px;">
                    <li><code>GET /</code> - This page</li>
                    <li><code>GET /api/stats</code> - JSON statistics</li>
                    <li><code>POST /api/reindex</code> - Reindex all embeddings</li>
                    <li><code>POST /api/resync</code> - Full resync from upstream</li>
                    <li><code>GET /sse</code> - MCP Server-Sent Events endpoint</li>
                </ul>
                <p style="margin-top: 15px;">
                    Personal Context Store v1.0 |
                    <a href="https://github.com/modelcontextprotocol/servers" target="_blank">MCP Documentation</a>
                </p>
            </div>
        </div>
        <script>
            async function reindexEmbeddings() {
                const btn = document.getElementById('reindex-btn');
                const status = document.getElementById('reindex-status');

                // Disable button and show loading
                btn.disabled = true;
                status.className = 'loading';
                status.textContent = 'Reindexing embeddings... This may take a while.';

                try {
                    const response = await fetch('/api/reindex', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        }
                    });

                    const result = await response.json();

                    if (response.ok) {
                        status.className = 'success';
                        status.textContent = result.message;
                        if (result.error_details && result.error_details.length > 0) {
                            status.textContent += '\\n\\nErrors:\\n' + result.error_details.join('\\n');
                        }
                    } else if (response.status === 503) {
                        status.className = 'error';
                        status.textContent = 'Server is still starting up. Please wait a moment and try again.';
                        // Re-enable button for retry
                        setTimeout(() => { btn.disabled = false; }, 2000);
                        return;
                    } else {
                        status.className = 'error';
                        status.textContent = 'Error: ' + (result.error || 'Unknown error');
                    }
                } catch (error) {
                    status.className = 'error';
                    status.textContent = 'Error: ' + error.message;
                } finally {
                    if (!status.className.includes('error') || status.textContent.includes('Unknown error')) {
                        btn.disabled = false;
                    }
                }
            }

            async function fullResync() {
                const btn = document.getElementById('resync-btn');
                const status = document.getElementById('resync-status');

                // Confirm action
                if (!confirm('⚠️ WARNING: This will delete all local content and resync from upstream.\\n\\nAre you sure you want to continue?')) {
                    return;
                }

                // Disable button and show loading
                btn.disabled = true;
                status.className = 'loading';
                status.textContent = 'Clearing local data and resyncing from upstream... This may take several minutes.';

                try {
                    const response = await fetch('/api/resync', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        }
                    });

                    const result = await response.json();

                    if (response.ok) {
                        status.className = 'success';
                        status.textContent = result.message;
                        // Reload page after 2 seconds to show updated stats
                        setTimeout(() => { window.location.reload(); }, 2000);
                    } else if (response.status === 503) {
                        status.className = 'error';
                        status.textContent = 'Server is still starting up. Please wait a moment and try again.';
                        setTimeout(() => { btn.disabled = false; }, 2000);
                        return;
                    } else {
                        status.className = 'error';
                        status.textContent = 'Error: ' + (result.error || 'Unknown error');
                    }
                } catch (error) {
                    status.className = 'error';
                    status.textContent = 'Error: ' + error.message;
                } finally {
                    if (!status.className.includes('success')) {
                        btn.disabled = false;
                    }
                }
            }
        </script>
    </body>
    </html>
    """

    return HTMLResponse(content=html)


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
