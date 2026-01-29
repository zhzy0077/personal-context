"""OpenAI-compatible embedding API client."""

import httpx
from typing import List

from ..config import settings


class EmbeddingClient:
    """Client for OpenAI-compatible embedding API."""

    def __init__(self):
        self.api_base = settings.embedding_api_base.rstrip("/")
        self.api_key = settings.embedding_api_key
        self.model = settings.embedding_model
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

    async def embed(self, text: str) -> List[float]:
        """Generate embedding for a single text."""
        embeddings = await self.embed_batch([text])
        return embeddings[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts."""
        if not texts:
            return []

        response = await self.client.post(
            f"{self.api_base}/embeddings",
            json={
                "input": texts,
                "model": self.model,
            },
        )
        response.raise_for_status()

        data = response.json()
        # Sort by index to ensure correct order
        embeddings = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in embeddings]

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
