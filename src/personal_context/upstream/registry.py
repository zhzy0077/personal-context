"""Registry for managing multiple upstream clients."""

from typing import Dict, Optional
from .base import UpstreamClient


class UpstreamRegistry:
    """Registry for managing multiple upstream knowledge base clients."""

    def __init__(self):
        """Initialize empty registry."""
        self._clients: Dict[str, UpstreamClient] = {}

    def register(self, provider_name: str, client: UpstreamClient) -> None:
        """
        Register an upstream client.

        Args:
            provider_name: Provider name (e.g., 'outline', 'trilium')
            client: UpstreamClient instance
        """
        self._clients[provider_name] = client

    def get(self, provider_name: str) -> Optional[UpstreamClient]:
        """
        Get a registered client by provider name.

        Args:
            provider_name: Provider name

        Returns:
            UpstreamClient instance or None if not found
        """
        return self._clients.get(provider_name)

    def get_all(self) -> Dict[str, UpstreamClient]:
        """
        Get all registered clients.

        Returns:
            Dictionary mapping provider names to clients
        """
        return self._clients.copy()

    def get_providers(self) -> list[str]:
        """
        Get list of registered provider names.

        Returns:
            List of provider names
        """
        return list(self._clients.keys())

    async def close_all(self) -> None:
        """Close all registered clients."""
        for client in self._clients.values():
            await client.close()
        self._clients.clear()

    def __len__(self) -> int:
        """Return number of registered clients."""
        return len(self._clients)
