# AGENTS.md

This file provides guidance for AI agents working on the Personal Context Store codebase.

## Project Overview

Personal Context Store is an MCP server providing hybrid semantic/keyword search over content synced with Outline knowledge base. Uses SQLite with sqlite-vec for vectors and FTS5 for keyword search.

## Build/Lint/Test Commands

```bash
# Install dependencies
uv sync

# Run MCP server (stdio mode)
uv run main.py

# Run HTTP/SSE server
uv run http_server.py

# Test with MCP Inspector
mcp dev main.py

# Lint with ruff (configured in pyproject.toml)
uv run ruff check .
uv run ruff check --fix .  # Auto-fix issues

# Type checking (ty is installed as dev dependency)
uv run ty check .
```

**No test suite exists yet.** If adding tests, use `pytest` with `pytest-asyncio` for async tests.

## Code Style Guidelines

### General Principles
- Python 3.13+ required (specified in `.python-version`)
- Use ruff for linting and formatting
- Prefer explicit over implicit
- Keep functions focused and small (< 50 lines where possible)
- Add docstrings to all public functions and classes

### Imports
- Use absolute imports: `from personal_context.config import settings`
- Group imports in this order: stdlib → third-party → local
- Sort imports within groups alphabetically
- Do not use wildcard imports (`from x import *`)

### Type Hints
- Use type hints for all function signatures
- Use `Optional[T]` instead of `T | None` for consistency with Pydantic
- Use `List[T]`, `Dict[K, V]` from `typing` (not built-in `list`, `dict`)
- Use `Any` when type is genuinely unknown
- Return types must be explicit for public functions

```python
def get_content(content_id: int) -> Dict[str, Any]:
    """Retrieve content by ID."""
    ...

async def search(
    query: str,
    limit: int = 10,
    source_types: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    ...
```

### Naming Conventions
- **Classes**: PascalCase (`class SyncOrchestrator`)
- **Functions/variables**: snake_case (`def get_connection()`)
- **Constants**: UPPER_SNAKE_CASE (`DB_PATH`, `DEFAULT_LIMIT`)
- **Private methods**: prefix with `_` (`_init_clients()`)
- **Private attributes**: prefix with `_` (`self._client`)
- **Async functions**: prefix with `async_` or use `async def` naturally (`async def fetch_url()`)

### Pydantic Patterns
- Use `pydantic-settings` for configuration (`BaseSettings`)
- Use `Field()` with `description` for all settings fields
- Use `model_config = SettingsConfigDict(...)` for settings config
- All settings use `PERSONAL_CONTEXT_` prefix

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PERSONAL_CONTEXT_",
        env_file=".env",
        extra="ignore",
    )

    db_path: Path = Field(
        default=Path.home() / ".personal-context" / "context.db",
        description="SQLite database path",
    )
```

### Database Operations
- Use parameterized queries to prevent SQL injection
- Use context managers for transactions (`with conn:`)
- SQLite: use `conn.execute()` for queries, `cursor.lastrowid` for insert IDs
- Tag insertion: use INSERT OR IGNORE with fallback SELECT

```python
cursor = conn.execute(
    "INSERT OR IGNORE INTO tags (name) VALUES (?)",
    (tag_name,),
)
tag_id = cursor.lastrowid
if tag_id == 0:  # Tag already existed
    tag_id = conn.execute(
        "SELECT id FROM tags WHERE name = ?",
        (tag_name,),
    ).fetchone()[0]
```

### Async/Await
- Use `httpx` for all async HTTP requests
- Prefix async helper functions with `async_` in naming if used as helpers
- Use `asyncio` for async operations when needed
- Always handle exceptions in async context managers

### Error Handling
- Use specific exceptions (`ValueError`, `RuntimeError`, `KeyError`)
- Don't suppress errors with bare `except:` or empty `except Exception:`
- Provide meaningful error messages
- Raise `ValueError` for invalid input arguments
- Raise `RuntimeError` for initialization/configuration failures

```python
if not embedding_client:
    raise RuntimeError("Embedding client not initialized")

if not row:
    raise ValueError(f"Content with ID {content_id} not found")
```

### SQL Conventions
- UPPERCASE SQL keywords
- Use `IF NOT EXISTS` and `IF EXISTS` for DDL
- Use `PRIMARY KEY`, `FOREIGN KEY`, `UNIQUE` constraints
- Create indexes on frequently queried columns
- Use `unixepoch('now')` for SQLite timestamps

### File Organization
- One module per concern (config, server, db, embeddings, search, sync, upstream, connectors)
- Use `__init__.py` for module exports
- Keep related functionality together
- Private implementation details in `_private.py` or prefix with `_`

### Documentation
- Use Google-style docstrings
- Document all parameters with types and descriptions
- Document return values
- Include usage examples for complex functions

```python
def hybrid_search(
    conn: sqlite3.Connection,
    query: str,
    query_embedding: List[float],
    limit: int = 10,
    source_types: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Perform hybrid search combining vector and FTS5 results.

    Args:
        conn: SQLite database connection
        query: Search query text
        query_embedding: Pre-computed query embedding vector
        limit: Maximum number of results
        source_types: Optional filter by source types

    Returns:
        List of matching content with combined scores
    """
```

### Misc
- **Embedding storage**: Store as JSON array strings: `"[" + ",".join(str(x) for x in embedding) + "]"`
- **JSON handling**: Use `json.dumps()` / `json.loads()` for metadata
- **HTTP responses**: Use `JSONResponse` from `starlette.responses`
- **Foreign keys**: Always enable in SQLite (`PRAGMA foreign_keys = ON`)
