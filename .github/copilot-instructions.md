# Copilot Instructions

Personal Context Store for AI Agents - An MCP server providing hybrid semantic/keyword search over content synced with Outline knowledge base.

## Development Commands

```bash
# Install dependencies
uv sync

# Run MCP server (stdio mode)
uv run main.py

# Run HTTP/SSE server
uv run http_server.py

# Test with MCP Inspector
mcp dev main.py
```

No test suite exists yet.

## Architecture

**Dual-storage design**: Content is stored locally in SQLite (with sqlite-vec for vectors, FTS5 for keywords) AND synced to Outline for centralized access.

**Data flow**: User Input → Generate Embedding → Store in SQLite + Create in Outline → Background Sync pulls updates

**Key modules**:
- `server.py` - FastMCP server with 8 MCP tools (search, add_content, get_content, list_sources, fetch_url, sync_now, get_sync_status, list_sync_history)
- `db/` - SQLite connection (singleton) with sqlite-vec extension
- `embeddings/client.py` - OpenAI-compatible embedding API
- `search/hybrid.py` - Hybrid search combining 60% vector + 40% FTS5 scores
- `sync/` - Background pull sync from Outline (5 min default interval)
- `upstream/outline.py` - Outline API client

**Hybrid search algorithm**: Both vector and FTS searches fetch `limit * 2` results, normalize scores, merge, and re-rank by combined score.

## Conventions

**Environment variables**: All settings use `PERSONAL_CONTEXT_` prefix (e.g., `PERSONAL_CONTEXT_DB_PATH`). Configure via `.env` file.

**Prompts collection**: `PERSONAL_CONTEXT_PROMPTS_COLLECTION_ID` points to the collection whose documents are concatenated by `load-personal-prompts`.

**Embedding storage**: Stored as JSON array strings in sqlite-vec:
```python
embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
```

**Tag insertion pattern**: Use INSERT OR IGNORE with fallback SELECT to handle duplicates:
```python
cursor = conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag_name,))
tag_id = cursor.lastrowid
if tag_id == 0:  # Tag already existed
    tag_id = conn.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()[0]
```

**Async HTTP**: Use httpx for all async HTTP requests.

**Lifespan management**: FastMCP server uses async context manager for startup/shutdown of clients and sync orchestrator.

**Database**: Foreign keys enabled. Auto-initialized on first run. Triggers auto-sync content changes to FTS5 table.
