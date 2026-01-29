# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Personal Context Store for AI Agents - A lightweight, self-hosted knowledge management system that acts as a transparent layer for upstream knowledge bases. It stores content locally with embeddings for semantic search AND syncs to Outline for centralized knowledge management.

**Key Technology Stack:**
- Python 3.13+ with uv package manager
- FastMCP framework for MCP server implementation
- SQLite with sqlite-vec extension for vector search
- FTS5 for full-text keyword search
- OpenAI-compatible embedding API
- Outline knowledge base integration

## Development Commands

### Setup and Installation
```bash
# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your API keys and settings
```

### Running the Server
```bash
# Run MCP server (stdio mode)
uv run main.py

# Run with custom host/port (override .env settings)
PERSONAL_CONTEXT_HTTP_HOST=0.0.0.0 PERSONAL_CONTEXT_HTTP_PORT=3000 uv run main.py

# Test with MCP Inspector (for development/debugging)
mcp dev main.py
```

### Testing
No test suite currently exists in the repository.

## Architecture

### Core Design Pattern
The system uses a **dual-storage architecture**:
1. **Local SQLite database** - Fast hybrid search (vector + keyword)
2. **Outline knowledge base** - Centralized, upstream storage

Content flows: User Input → Local DB + Embeddings → Outline Sync

### Module Structure

```
src/personal_context/
├── server.py              # FastMCP server with 4 MCP tools
├── config.py              # Pydantic settings (prefix: PERSONAL_CONTEXT_)
├── db/
│   ├── connection.py      # Singleton SQLite connection with sqlite-vec
│   └── schema.py          # Schema creation with triggers
├── embeddings/
│   └── client.py          # OpenAI-compatible embedding API client
├── search/
│   └── hybrid.py          # Hybrid search (60% vector, 40% FTS)
├── sync/
│   ├── orchestrator.py    # Background sync task coordinator
│   └── pull.py            # Upstream → Local sync logic
├── upstream/
│   └── outline.py         # Outline API client for sync
└── connectors/
    └── web.py             # Web content fetcher with BeautifulSoup
```

### Database Schema

**Tables:**
- `content` - Main storage (id, source_type, source_url, title, content, metadata, outline_doc_id, outline_updated_at, timestamps)
- `content_fts` - FTS5 virtual table (porter tokenizer, auto-synced via triggers)
- `content_vec` - sqlite-vec virtual table (configurable dimension)
- `tags` - Tag definitions
- `content_tags` - Many-to-many relationship
- `sync_state` - Sync status per collection (collection_id, last_pull_at, status, error_message, timestamps)
- `sync_log` - Audit trail of sync operations (id, collection_id, operation, content_id, outline_doc_id, details, created_at)

**Key Indexes:**
- `idx_content_source` on (source_type, source_id)
- `idx_content_outline_doc` on (outline_doc_id)
- `idx_content_created` on (created_at DESC)
- `idx_sync_log_collection` on (collection_id, created_at DESC)

**Triggers:** Auto-sync content changes to FTS5 table (insert, update, delete)

### MCP Tools (server.py)

1. **`search(query, limit, source_types)`** - Hybrid semantic + keyword search
2. **`add_content(content, title, ...)`** - Add content locally and sync to Outline
3. **`get_content(content_id)`** - Retrieve content by ID with tags
4. **`load_personal_prompts()`** - Concatenate prompt content from configured collection

**Note:** Additional functionality like `reindex_embeddings()` and `full_resync()` are available as helper functions for API endpoints but not exposed as MCP tools.

### Hybrid Search Algorithm (search/hybrid.py)

The search combines two strategies:
- **Vector Search**: sqlite-vec with distance-based ranking (normalized: `1.0 / (1.0 + distance)`)
- **FTS Search**: FTS5 with rank-based scoring (normalized: `abs(rank) / 100.0`)
- **Combined Score**: `0.6 * vec_score + 0.4 * fts_score`

Both searches fetch `limit * 2` results, then merge and re-rank by combined score.

### Configuration (config.py)

All settings use `PERSONAL_CONTEXT_` prefix:
- `DB_PATH` - Database location (default: `~/.personal-context/context.db`)
- `EMBEDDING_API_BASE` - OpenAI-compatible API endpoint
- `EMBEDDING_API_KEY` - API key
- `EMBEDDING_MODEL` - Model name (e.g., text-embedding-3-small)
- `EMBEDDING_DIMENSION` - Vector dimension (e.g., 1536)
- `OUTLINE_API_BASE` - Outline API endpoint
- `OUTLINE_API_KEY` - Outline API key
- `OUTLINE_COLLECTION_ID` - Default collection ID
- `PROMPTS_COLLECTION_ID` - Collection ID used by load-personal-prompts tool
- `SYNC_ENABLED` - Enable automatic background sync (default: true)
- `SYNC_INTERVAL` - Sync interval in seconds (default: 300)
- `SYNC_COLLECTIONS` - Comma-separated list of collection IDs to sync (empty = sync default collection only)
- `HTTP_HOST` - HTTP server host (default: 127.0.0.1)
- `HTTP_PORT` - HTTP server port (default: 8000)
- `HTTP_AUTH_USERNAME` - HTTP basic auth username (leave empty to disable auth)
- `HTTP_AUTH_PASSWORD` - HTTP basic auth password (leave empty to disable auth)
- `OUTLINE_API_BASE` - Outline API endpoint
- `OUTLINE_API_KEY` - Outline API key
- `OUTLINE_COLLECTION_ID` - Default collection ID
- `PROMPTS_COLLECTION_ID` - Collection ID used by load-personal-prompts tool
- `SYNC_ENABLED` - Enable automatic background sync (default: true)
- `SYNC_INTERVAL` - Sync interval in seconds (default: 300)
- `SYNC_COLLECTIONS` - Comma-separated list of collection IDs to sync (empty = sync default collection only)

The config auto-creates the database directory on initialization.

### Lifespan Management (server.py)

The FastMCP server uses an async lifespan context manager:
- **Startup**: Initialize DB, create EmbeddingClient and OutlineClient, start SyncOrchestrator (if enabled)
- **Shutdown**: Stop SyncOrchestrator, close clients and database connection

Global instances: `embedding_client`, `outline_client`, and `sync_orchestrator`

### Background Sync System (sync/)

The system implements **unidirectional pull sync** from Outline to local database:

**SyncOrchestrator** (`sync/orchestrator.py`):
- Manages background sync tasks with configurable interval (default: 5 minutes)
- Prevents concurrent syncs using `sync_state.status` field
- Handles graceful shutdown with timeout

**Pull Sync Logic** (`sync/pull.py`):
- Fetches documents from Outline with pagination (100 docs per page)
- Uses timestamp-based incremental sync with early termination optimization
- For each document:
  - Checks if exists locally by `outline_doc_id`
  - Compares `outline_updated_at` timestamps
  - Creates new or updates existing content with regenerated embeddings
- Logs all operations to `sync_log` table
- Updates `sync_state` with last successful pull timestamp

**Sync Algorithm**:
1. Fetch documents sorted by `updatedAt DESC` (newest first)
2. Compare Outline's `updatedAt` with local `outline_updated_at`
3. Stop pagination when encountering documents older than `last_pull_at`
4. Only fetch full document content for new/updated documents
5. Generate embeddings and update local database
6. Log operations and update sync state

### Web Content Extraction (connectors/web.py)

The web fetcher:
1. Fetches URL with redirects
2. Extracts title from `<title>`, `<h1>`, or defaults to "Untitled"
3. Removes script, style, nav, footer, header elements
4. Finds main content area (main, article, [role="main"], .content, #content)
5. Cleans whitespace and returns structured content

## Important Implementation Details

### Embedding Storage Format
Embeddings are stored as JSON array strings in sqlite-vec:
```python
embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
```

### Tag Management
Tags use INSERT OR IGNORE pattern with fallback SELECT to handle duplicates:
```python
cursor = conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag_name,))
tag_id = cursor.lastrowid
if tag_id == 0:  # Tag already existed
    tag_id = conn.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()[0]
```

### Search Result Truncation
Search results truncate content to 500 characters for display:
```python
"content": result["content"][:500] + "..." if len(result["content"]) > 500 else result["content"]
```

### Outline Sync Flow
When adding content:
1. Generate embedding from content
2. Create document in Outline (get doc_id)
3. Store in local DB with outline_doc_id
4. Store embedding in content_vec
5. Add tags if provided

### Background Sync from Outline
The system automatically pulls changes from Outline every 5 minutes (configurable):

**First Sync (Initial Pull)**:
- Fetches all documents from configured collections
- Creates local copies with embeddings
- May take time for large collections

**Incremental Sync**:
- Only fetches documents updated since last sync
- Uses early termination optimization (stops when encountering old documents)
- Two-phase fetch: lightweight summaries first, full content only when needed

**Sync State Management**:
- `sync_state` table tracks last pull timestamp and status per collection
- Status values: `idle`, `syncing`, `error`
- Prevents concurrent syncs for the same collection

**Error Handling**:
- Network/API errors are logged but don't block entire sync
- Failed documents are logged to `sync_log` with error details
- Sync continues with remaining documents
- Next sync cycle will retry failed documents

## Claude Desktop Integration

Add to `claude_desktop_config.json`:

**Stdio Transport (recommended for local use):**
```json
{
  "mcpServers": {
    "personal-context": {
      "command": "uv",
      "args": ["--directory", "/path/to/personal-context", "run", "main.py"]
    }
  }
}
```

**HTTP/SSE Transport (for remote servers):**
```json
{
  "mcpServers": {
    "personal-context": {
      "url": "http://127.0.0.1:8000/sse"
    }
  }
}
```

For remote access, set `PERSONAL_CONTEXT_HTTP_HOST=0.0.0.0` in `.env` and connect via `http://YOUR_SERVER_IP:8000/sse`

## HTTP Basic Authentication

The web server supports HTTP Basic Authentication to protect all endpoints. When enabled:

- **All endpoints require authentication**: `/` (homepage), `/api/*` (API endpoints), and `/sse` (MCP endpoint)
- Authentication uses standard HTTP Basic Auth headers

**To enable authentication:**

1. Set credentials in `.env`:
```bash
PERSONAL_CONTEXT_HTTP_AUTH_USERNAME=your-username
PERSONAL_CONTEXT_HTTP_AUTH_PASSWORD=your-password
```

2. Restart the server:
```bash
uv run main.py
```

3. Access endpoints with credentials:
```bash
# Using curl
curl -u username:password http://localhost:8000/

# For MCP clients, configure authentication in claude_desktop_config.json
```

**MCP Client Configuration with Authentication:**

When authentication is enabled, you need to include credentials in the SSE URL:

```json
{
  "mcpServers": {
    "personal-context": {
      "url": "http://username:password@127.0.0.1:8000/sse"
    }
  }
}
```

**To disable authentication:**

Leave `HTTP_AUTH_USERNAME` and `HTTP_AUTH_PASSWORD` empty in `.env` (default behavior).

## Changing Embedding Models

When you change the embedding model or dimension, you need to regenerate all embeddings. The system provides a `reindex_embeddings()` tool that automatically:

1. Drops the existing `content_vec` table
2. Recreates it with the current `EMBEDDING_DIMENSION` setting
3. Regenerates embeddings for all content using the current `EMBEDDING_MODEL`

**How to change embedding models:**

1. Update your `.env` file:
```bash
PERSONAL_CONTEXT_EMBEDDING_MODEL=text-embedding-3-large
PERSONAL_CONTEXT_EMBEDDING_DIMENSION=3072
```

2. Restart the server:
```bash
uv run main.py
```

3. Trigger reindexing (choose one method):
   - **Web UI**: Open http://localhost:8000 and click "Reindex All Embeddings"
   - **MCP Tool**: Use the `reindex_embeddings()` tool from Claude Desktop
   - **API**: `curl -X POST http://localhost:8000/api/reindex`

The reindex operation will process all documents and return statistics (total, success, errors).

## Development Notes

- The project uses uv for dependency management (no requirements.txt)
- Python 3.13+ is required (specified in .python-version)
- Database is auto-initialized on first run via `init_db()`
- All async operations use httpx for HTTP requests
- Foreign key constraints are enabled in SQLite
- The sqlite-vec extension must be available (installed via uv)
