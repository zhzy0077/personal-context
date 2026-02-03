"""Entry point for the personal context MCP server with proper lifespan management."""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount

from src.personal_context.config import settings
from src.personal_context.db import init_db, close_connection
from src.personal_context.embeddings import EmbeddingClient
from src.personal_context.upstream import OutlineClient, TriliumClient, UpstreamRegistry
from src.personal_context.sync.orchestrator import SyncOrchestrator
from src.personal_context.server import mcp, BasicAuthMiddleware

# Custom logging format
LOG_FORMAT = "[%(asctime)s] %(levelname)-8s %(message)s"
DATE_FORMAT = "%m/%d/%y %H:%M:%S"

# Global instances
embedding_client = None
upstream_registry = None
sync_orchestrator = None


@asynccontextmanager
async def lifespan(app):
    """Lifespan context manager for the main Starlette app."""
    global embedding_client, upstream_registry, sync_orchestrator

    logger = logging.getLogger(__name__)

    # Startup
    logger.info("Initializing database...")
    init_db()

    logger.info("Initializing embedding client...")
    embedding_client = EmbeddingClient()

    logger.info("Initializing upstream clients...")
    upstream_registry = UpstreamRegistry()

    # Register all configured upstream providers
    configured_providers = settings.get_configured_providers()
    if not configured_providers:
        logger.warning(
            "No upstream providers configured! Please configure at least one provider."
        )
    else:
        logger.info(f"Configured providers: {', '.join(configured_providers)}")

    if settings.is_outline_configured():
        logger.info("Registering Outline client...")
        outline_client = OutlineClient()
        upstream_registry.register("outline", outline_client)

    if settings.is_trilium_configured():
        logger.info("Registering Trilium client...")
        trilium_client = TriliumClient(
            api_base=settings.trilium_api_base,
            api_token=settings.trilium_api_token,
        )
        upstream_registry.register("trilium", trilium_client)

    # Set the clients in the mcp server module
    import src.personal_context.server as server_module

    server_module.embedding_client = embedding_client
    server_module.upstream_registry = upstream_registry

    # Start sync orchestrator in background
    if settings.sync_enabled and len(upstream_registry) > 0:
        logger.info("Starting background sync orchestrator...")
        sync_orchestrator = SyncOrchestrator(
            upstream_registry=upstream_registry,
            embedding_client=embedding_client,
            sync_interval=settings.sync_interval,
        )
        server_module.sync_orchestrator = sync_orchestrator
        # Start in background without blocking
        asyncio.create_task(sync_orchestrator.start())
    elif settings.sync_enabled:
        logger.warning("Sync enabled but no upstream providers configured")

    logger.info("Server initialization complete!")

    yield

    # Shutdown
    logger.info("Shutting down server...")
    orchestrator = sync_orchestrator
    if orchestrator is not None:
        await orchestrator.stop()
    if embedding_client:
        await embedding_client.close()
    if upstream_registry:
        await upstream_registry.close_all()
    close_connection()
    logger.info("Server shutdown complete")


def configure_logging():
    """Configure unified logging format for all loggers."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))

    # Configure root logger
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [handler]

    # Reduce noise from httpx
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main():
    """Run the MCP server with proper lifespan management."""
    configure_logging()

    # Get the FastMCP Starlette app (without lifespan)
    mcp_app = mcp.streamable_http_app()

    # Create main Starlette app with our lifespan
    app = Starlette(
        debug=False,
        lifespan=lifespan,
        routes=[
            Mount("/", app=mcp_app),
        ],
    )

    # Add basic auth middleware
    app.add_middleware(BasicAuthMiddleware)

    logging.info(
        f"Starting Personal Context MCP server on http://{settings.http_host}:{settings.http_port}"
    )
    logging.info(
        "MCP endpoint: http://%s:%s%s",
        settings.http_host,
        settings.http_port,
        mcp.settings.streamable_http_path,
    )

    # Configure uvicorn to use our logging format
    log_config = uvicorn.config.LOGGING_CONFIG.copy()
    log_config["formatters"]["default"]["fmt"] = LOG_FORMAT
    log_config["formatters"]["default"]["datefmt"] = DATE_FORMAT
    log_config["formatters"]["access"]["fmt"] = LOG_FORMAT
    log_config["formatters"]["access"]["datefmt"] = DATE_FORMAT

    # Run with uvicorn
    uvicorn.run(
        app,
        host=settings.http_host,
        port=settings.http_port,
        log_level="info",
        log_config=log_config,
    )


if __name__ == "__main__":
    main()
