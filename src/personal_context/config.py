"""Configuration management using pydantic-settings."""

from pathlib import Path
from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="PERSONAL_CONTEXT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    db_path: Path = Field(
        default=Path.home() / ".personal-context" / "context.db",
        description="SQLite database path",
    )

    # Embeddings API (OpenAI-compatible)
    embedding_api_base: str = Field(
        default="https://api.openai.com/v1",
        description="OpenAI-compatible API base URL",
    )
    embedding_api_key: str = Field(
        default="",
        description="API key for embeddings",
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="Embedding model name",
    )
    embedding_dimension: int = Field(
        default=1536,
        description="Vector dimension for embeddings",
    )

    # Outline API
    outline_api_base: str = Field(
        default="https://app.getoutline.com/api",
        description="Outline API base URL",
    )
    outline_api_key: str = Field(
        default="",
        description="Outline API key",
    )
    outline_collection_id: str = Field(
        default="",
        description="Default collection ID for new documents",
    )
    prompts_collection_id: str = Field(
        default="",
        description="Collection ID for personal prompts",
    )

    # Trilium Notes ETAPI
    trilium_api_base: str = Field(
        default="http://localhost:8080/etapi",
        description="Trilium ETAPI base URL",
    )
    trilium_api_token: str = Field(
        default="",
        description="Trilium ETAPI token",
    )
    trilium_parent_note_id: str = Field(
        default="root",
        description="Default parent note ID for new notes",
    )

    # Upstream provider configuration
    upstream_provider: str = Field(
        default="outline",
        description="DEPRECATED: Default upstream provider for add_content (e.g., 'outline', 'trilium'). Sync will use all configured providers.",
    )

    # Sync configuration
    sync_enabled: bool = Field(
        default=True,
        description="Enable automatic background sync",
    )
    sync_interval: int = Field(
        default=300,
        description="Sync interval in seconds (default: 5 minutes)",
    )
    sync_collections: List[str] = Field(
        default_factory=list,
        description="List of collection IDs to sync (empty = sync default collection only)",
    )

    # HTTP Server
    http_host: str = Field(
        default="127.0.0.1",
        description="HTTP server host",
    )
    http_port: int = Field(
        default=8000,
        description="HTTP server port",
    )
    http_auth_username: str = Field(
        default="",
        description="HTTP basic auth username (leave empty to disable auth)",
    )
    http_auth_password: str = Field(
        default="",
        description="HTTP basic auth password (leave empty to disable auth)",
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure database directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def is_outline_configured(self) -> bool:
        """Check if Outline is configured."""
        return bool(self.outline_api_key and self.outline_api_base)

    def is_trilium_configured(self) -> bool:
        """Check if Trilium is configured."""
        return bool(self.trilium_api_token and self.trilium_api_base)

    def get_configured_providers(self) -> list[str]:
        """
        Get list of configured upstream providers.

        Returns:
            List of provider names (e.g., ['outline', 'trilium'])
        """
        providers = []
        if self.is_outline_configured():
            providers.append('outline')
        if self.is_trilium_configured():
            providers.append('trilium')
        return providers

    def is_http_auth_enabled(self) -> bool:
        """Check if HTTP basic authentication is enabled."""
        return bool(self.http_auth_username and self.http_auth_password)


# Global settings instance
settings = Settings()
