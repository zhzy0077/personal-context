# Personal Context Store for AI Agents

A lightweight personal context store that acts as a transparent layer for upstream knowledge bases. Content is stored locally with embeddings for semantic search AND synced to your choice of upstream provider (Outline, Trilium Notes, etc.) for centralized knowledge management.

## Features

- **Hybrid Search**: Combines semantic (vector) and keyword (FTS5) search
- **Multiple Upstream Providers**:
  - ✅ Sync from multiple providers simultaneously (just configure API keys!)
  - ✅ Outline (wiki-style knowledge base)
  - ✅ Trilium Notes (hierarchical note-taking)
  - 🔄 More coming soon (Notion, Confluence, etc.)
- **Auto-Detection**: Automatically detects and syncs from all configured providers
- **MCP Interface**: Exposes tools for AI agents via Model Context Protocol
- **Lightweight**: Uses SQLite with sqlite-vec for vector search
- **Flexible Embeddings**: Supports any OpenAI-compatible embedding API
- **Background Sync**: Automatic incremental sync from upstream sources

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd personal-context

# Install dependencies
uv sync

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your API keys and settings
```

## Configuration

Create a `.env` file with the following variables:

```bash
# Database path
PERSONAL_CONTEXT_DB_PATH=/home/user/.personal-context/context.db

# Embeddings API (OpenAI-compatible)
PERSONAL_CONTEXT_EMBEDDING_API_BASE=https://api.openai.com/v1
PERSONAL_CONTEXT_EMBEDDING_API_KEY=your-api-key-here
PERSONAL_CONTEXT_EMBEDDING_MODEL=text-embedding-3-small
PERSONAL_CONTEXT_EMBEDDING_DIMENSION=1536

# Upstream Provider (choose one: outline, trilium)
PERSONAL_CONTEXT_UPSTREAM_PROVIDER=outline

# Outline API (if using Outline)
PERSONAL_CONTEXT_OUTLINE_API_BASE=https://app.getoutline.com/api
PERSONAL_CONTEXT_OUTLINE_API_KEY=your-outline-api-key-here
PERSONAL_CONTEXT_OUTLINE_COLLECTION_ID=your-collection-id-here
PERSONAL_CONTEXT_PROMPTS_COLLECTION_ID=your-prompts-collection-id-here

# Trilium Notes ETAPI (if using Trilium)
PERSONAL_CONTEXT_TRILIUM_API_BASE=http://localhost:8080/etapi
PERSONAL_CONTEXT_TRILIUM_API_TOKEN=your-etapi-token-here
PERSONAL_CONTEXT_TRILIUM_PARENT_NOTE_ID=root

# Sync Configuration
PERSONAL_CONTEXT_SYNC_ENABLED=true
PERSONAL_CONTEXT_SYNC_INTERVAL=300
PERSONAL_CONTEXT_SYNC_COLLECTIONS=collection_id_1,collection_id_2

# HTTP Server (optional, for MCP over HTTP/SSE)
PERSONAL_CONTEXT_HTTP_HOST=127.0.0.1
PERSONAL_CONTEXT_HTTP_PORT=8000
```

## Upstream Providers

Personal Context Store supports multiple upstream knowledge base providers **simultaneously**. Just configure the API credentials for each provider you want to use - the system automatically detects and syncs from all configured providers!

### How Multi-Provider Support Works

**Automatic Detection:**
- **Outline**: Detected if `PERSONAL_CONTEXT_OUTLINE_API_KEY` and `PERSONAL_CONTEXT_OUTLINE_API_BASE` are set
- **Trilium**: Detected if `PERSONAL_CONTEXT_TRILIUM_API_TOKEN` and `PERSONAL_CONTEXT_TRILIUM_API_BASE` are set

**Background Sync:**
- Every 5 minutes (configurable via `PERSONAL_CONTEXT_SYNC_INTERVAL`)
- For each collection in `PERSONAL_CONTEXT_SYNC_COLLECTIONS`, tries each configured provider
- Documents are tagged with their source provider (e.g., `source_type='outline'` or `source_type='trilium'`)

**Example - Sync from both Outline AND Trilium:**
```bash
# Configure both providers in .env
PERSONAL_CONTEXT_OUTLINE_API_KEY=your_outline_key
PERSONAL_CONTEXT_OUTLINE_API_BASE=https://app.getoutline.com/api
PERSONAL_CONTEXT_TRILIUM_API_TOKEN=your_trilium_token
PERSONAL_CONTEXT_TRILIUM_API_BASE=http://localhost:8080/etapi
PERSONAL_CONTEXT_SYNC_COLLECTIONS=outline_collection_1,trilium_note_1
```

That's it! The system will automatically sync from both providers.

### Outline

Wiki-style knowledge base with collections and documents.

**Setup:**
1. Get your API key from Outline settings (Settings → API Tokens)
2. Find your collection ID from the URL when viewing a collection
3. Configure in `.env`:
   ```bash
   PERSONAL_CONTEXT_OUTLINE_API_BASE=https://app.getoutline.com/api
   PERSONAL_CONTEXT_OUTLINE_API_KEY=your_outline_key
   PERSONAL_CONTEXT_OUTLINE_COLLECTION_ID=your_default_collection_id
   PERSONAL_CONTEXT_SYNC_COLLECTIONS=collection_id_1,collection_id_2
   ```

**Features:**
- Collection-based organization
- Rich markdown support
- Team collaboration
- Document versioning

**Provider-Specific Operations:**
```python
# Add content to Outline specifically
await add_content(
    title="Work Note",
    content="...",
    provider="outline"
)

# Search only Outline documents
results = await search(
    query="project timeline",
    source_types=["outline"]
)
```

### Trilium Notes

Hierarchical note-taking application with powerful features via ETAPI.

**Setup:**
1. Enable ETAPI in Trilium (Options → ETAPI)
2. Generate an ETAPI token
3. Find note IDs:
   - Right-click on a note → "Note Info" → Copy Note ID
   - Or use ETAPI: `curl -H "Authorization: YOUR_TOKEN" http://localhost:8080/etapi/notes/root/children`
4. Configure in `.env`:
   ```bash
   PERSONAL_CONTEXT_TRILIUM_API_BASE=http://localhost:8080/etapi
   PERSONAL_CONTEXT_TRILIUM_API_TOKEN=your_etapi_token
   PERSONAL_CONTEXT_TRILIUM_PARENT_NOTE_ID=root
   PERSONAL_CONTEXT_SYNC_COLLECTIONS=note_id_1,note_id_2
   ```

**Features:**
- Hierarchical note organization
- Local-first with optional sync
- Rich note types and attributes
- Powerful scripting capabilities

**Data Mapping:**
| Trilium | Personal Context Store |
|---------|------------------------|
| Note ID | `upstream_doc_id` |
| Title | `title` |
| Content | `content` |
| utcDateModified | `upstream_updated_at` |
| Parent Note | `collection_id` |

**Provider-Specific Operations:**
```python
# Add content to Trilium specifically
await add_content(
    title="Personal Note",
    content="...",
    provider="trilium",
    collection_id="parent_note_id"
)

# Search only Trilium notes
results = await search(
    query="meeting notes",
    source_types=["trilium"]
)
```

**Troubleshooting:**
```bash
# Test ETAPI connection
curl -H "Authorization: YOUR_TOKEN" http://localhost:8080/etapi/notes/root

# Check sync status
curl http://localhost:8000/api/stats
```

### Use Cases

**Work + Personal Separation:**
```bash
# Outline for work documentation
PERSONAL_CONTEXT_OUTLINE_API_KEY=work_key
# Trilium for personal notes
PERSONAL_CONTEXT_TRILIUM_API_TOKEN=personal_token
PERSONAL_CONTEXT_SYNC_COLLECTIONS=work_collection_id,personal_note_id
```

Search work docs only: `await search(query="API design", source_types=["outline"])`

**Local + Cloud:**
- Trilium running locally for private notes
- Outline in the cloud for team collaboration
- All content synced locally with embeddings for fast hybrid search

### Adding More Providers

The system uses a protocol-based architecture that makes it easy to add new providers:

1. Implement the `UpstreamClient` protocol in `src/personal_context/upstream/`
2. Return normalized `UpstreamDocument`, `UpstreamCollection`, `DocumentPage` types
3. Add configuration detection in `config.py`
4. Register in `main.py`

See `src/personal_context/upstream/outline.py` and `trilium.py` for examples.

**References:**
- [Outline API Documentation](https://www.getoutline.com/developers)
- [Trilium ETAPI Documentation](https://github.com/zadam/trilium/wiki/ETAPI)

## Usage

### Running the MCP Server

```bash
# Run the server (provides both stdio and HTTP/SSE endpoints)
uv run main.py

# Override host/port via environment variables
PERSONAL_CONTEXT_HTTP_HOST=0.0.0.0 PERSONAL_CONTEXT_HTTP_PORT=3000 uv run main.py
```

The server provides:
- HTTP/SSE endpoint at `http://127.0.0.1:8000/sse` (or your configured host/port)
- Web UI at `http://127.0.0.1:8000/`
- API endpoints at `http://127.0.0.1:8000/api/*`

### Testing with MCP Inspector

```bash
mcp dev main.py
```

### Claude Desktop Integration

**Stdio Transport (recommended for local use)**

Add to your `claude_desktop_config.json`:

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

**HTTP/SSE Transport (for remote servers)**

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "personal-context": {
      "url": "http://127.0.0.1:8000/sse"
    }
  }
}
```

### Connecting from Other Devices

To connect from other devices on your network:

1. Set `PERSONAL_CONTEXT_HTTP_HOST=0.0.0.0` in your `.env` file

2. Start the server:
```bash
uv run main.py
```

3. Find your server's IP address:
```bash
# On Linux/Mac
ip addr show | grep inet

# On Windows
ipconfig
```

4. Connect using: `http://YOUR_SERVER_IP:8000/sse`

## MCP Tools

### `search`
Search content using hybrid semantic and keyword search.

**Parameters:**
- `query` (string): Search query text
- `limit` (int, optional): Maximum number of results (default: 10)
- `source_types` (list, optional): Filter by source types (e.g., ['web', 'manual'])

### `add_content`
Add content to the store and sync to upstream provider.

**Parameters:**
- `content` (string): Content text
- `title` (string): Content title
- `provider` (string, optional): Specific provider to use ('outline', 'trilium', etc.). Defaults to `PERSONAL_CONTEXT_UPSTREAM_PROVIDER`
- `source_type` (string, optional): Type of source (default: 'manual')
- `tags` (list, optional): List of tags
- `collection_id` (string, optional): Collection/parent note ID
- `source_url` (string, optional): Source URL
- `metadata` (dict, optional): Additional metadata

### `fetch_url`
Fetch content from a URL and add it to the store.

**Parameters:**
- `url` (string): URL to fetch
- `provider` (string, optional): Specific provider to use
- `tags` (list, optional): List of tags
- `collection_id` (string, optional): Collection/parent note ID

### `get_content`
Retrieve content by ID.

**Parameters:**
- `content_id` (int): Content ID

### `list_sources`
List content statistics by source type.

### `load-personal-prompts`
Load concatenated personal prompts from the configured prompts collection.

**Parameters:** none

## Architecture

```
personal-context/
├── src/personal_context/
│   ├── config.py              # Configuration management
│   ├── server.py              # MCP server and tools
│   ├── db/
│   │   ├── connection.py      # SQLite + sqlite-vec setup
│   │   └── schema.py          # Database schema
│   ├── embeddings/
│   │   └── client.py          # OpenAI-compatible embedding client
│   ├── search/
│   │   └── hybrid.py          # Hybrid search implementation
│   ├── sync/
│   │   ├── orchestrator.py    # Background sync coordinator
│   │   └── pull.py            # Upstream → Local sync logic
│   ├── upstream/
│   │   ├── base.py            # UpstreamClient protocol
│   │   ├── registry.py        # Multi-provider registry
│   │   ├── outline.py         # Outline API client
│   │   └── trilium.py         # Trilium ETAPI client
│   └── connectors/
│       └── web.py             # Web content fetcher
└── main.py                    # Entry point
```

## Database Schema

- **content**: Main content storage with metadata and upstream sync tracking
- **content_fts**: FTS5 virtual table for keyword search
- **content_vec**: sqlite-vec virtual table for semantic search
- **tags**: Tag definitions
- **content_tags**: Many-to-many relationship between content and tags
- **sync_state**: Sync status per collection (last_pull_at, status, error_message)
- **sync_log**: Audit trail of sync operations

## License

MIT
