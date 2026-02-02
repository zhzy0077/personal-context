"""Outline API client for upstream knowledge base integration."""

import httpx
from datetime import datetime
from typing import Optional, Dict, Any, List

from ..config import settings
from .base import UpstreamDocument, UpstreamCollection, DocumentPage


class OutlineClient:
    """Client for Outline API."""

    def __init__(self):
        self.api_base = settings.outline_api_base.rstrip("/")
        self.api_key = settings.outline_api_key
        self.default_collection_id = settings.outline_collection_id
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

    async def create_document(
        self,
        title: str,
        content: str,
        collection_id: Optional[str] = None,
    ) -> str:
        """
        Create a new document in Outline.

        Args:
            title: Document title
            content: Document content (markdown)
            collection_id: Collection ID (uses default if not provided)

        Returns:
            Document ID
        """
        collection = collection_id or self.default_collection_id
        if not collection:
            raise ValueError("No collection_id provided and no default configured")

        response = await self.client.post(
            f"{self.api_base}/documents.create",
            json={
                "title": title,
                "text": content,
                "collectionId": collection,
                "publish": True,
            },
        )
        response.raise_for_status()

        data = response.json()
        return data["data"]["id"]

    async def update_document(self, doc_id: str, content: str) -> None:
        """
        Update an existing document in Outline.

        Args:
            doc_id: Document ID
            content: New content
        """
        payload: Dict[str, Any] = {"id": doc_id, "text": content}

        response = await self.client.post(
            f"{self.api_base}/documents.update",
            json=payload,
        )
        response.raise_for_status()

    async def list_collections(self) -> List[UpstreamCollection]:
        """
        List all collections.

        Returns:
            List of normalized UpstreamCollection objects
        """
        response = await self.client.post(
            f"{self.api_base}/collections.list",
            json={},
        )
        response.raise_for_status()

        data = response.json()
        return [
            UpstreamCollection(
                id=col["id"],
                name=col["name"],
                description=col.get("description", ""),
            )
            for col in data["data"]
        ]

    async def get_document(self, doc_id: str) -> UpstreamDocument:
        """
        Retrieve a single document by ID.

        Args:
            doc_id: Document ID

        Returns:
            Normalized UpstreamDocument
        """
        response = await self.client.post(
            f"{self.api_base}/documents.info",
            json={"id": doc_id},
        )
        response.raise_for_status()

        data = response.json()
        doc = data["data"]

        # Parse ISO timestamps to Unix timestamps
        updated_at = datetime.fromisoformat(
            doc["updatedAt"].replace("Z", "+00:00")
        ).timestamp()
        created_at = datetime.fromisoformat(
            doc["createdAt"].replace("Z", "+00:00")
        ).timestamp()

        return UpstreamDocument(
            id=doc["id"],
            title=doc["title"],
            content=doc["text"],  # Normalize 'text' to 'content'
            updated_at=updated_at,
            created_at=created_at,
        )

    async def list_documents(
        self,
        collection_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> DocumentPage:
        """
        List documents in a collection with pagination.

        Args:
            collection_id: Collection ID
            limit: Number of documents per page
            offset: Pagination offset

        Returns:
            DocumentPage with normalized documents and pagination info
        """
        response = await self.client.post(
            f"{self.api_base}/documents.list",
            json={
                "collectionId": collection_id,
                "limit": limit,
                "offset": offset,
                "sort": "updatedAt",
                "direction": "DESC",
            },
        )
        response.raise_for_status()

        data = response.json()
        page_docs = data.get("data", [])

        # Normalize documents
        documents = []
        for doc in page_docs:
            updated_at = datetime.fromisoformat(
                doc["updatedAt"].replace("Z", "+00:00")
            ).timestamp()
            created_at = datetime.fromisoformat(
                doc["createdAt"].replace("Z", "+00:00")
            ).timestamp()

            documents.append(
                UpstreamDocument(
                    id=doc["id"],
                    title=doc["title"],
                    content=doc.get("text", ""),  # May be empty in list view
                    updated_at=updated_at,
                    created_at=created_at,
                )
            )

        # Check if there are more pages
        has_more = bool(data.get("pagination", {}).get("nextPath"))

        return DocumentPage(documents=documents, has_more=has_more)

    async def list_documents_updated_since(
        self,
        collection_id: str,
        since_timestamp: float,
    ) -> List[Dict[str, Any]]:
        """
        Fetch documents updated after a specific timestamp.

        DEPRECATED: This method is Outline-specific and will be removed.
        Use list_documents() with filtering in the sync logic instead.

        Args:
            collection_id: Collection ID
            since_timestamp: Unix timestamp

        Returns:
            List of document summaries updated since the timestamp
        """
        documents = []
        offset = 0
        limit = 100

        while True:
            page = await self.list_documents(
                collection_id=collection_id,
                limit=limit,
                offset=offset,
            )

            if not page.documents:
                break

            for doc in page.documents:
                if doc.updated_at > since_timestamp:
                    # Return raw dict for backwards compatibility
                    documents.append(
                        {
                            "id": doc.id,
                            "title": doc.title,
                            "text": doc.content,
                            "updatedAt": datetime.fromtimestamp(
                                doc.updated_at
                            ).isoformat()
                            + "Z",
                            "createdAt": datetime.fromtimestamp(
                                doc.created_at
                            ).isoformat()
                            + "Z"
                            if doc.created_at
                            else None,
                        }
                    )
                else:
                    # Since sorted by updatedAt DESC, we can stop here
                    return documents

            # Check if there are more pages
            if not page.has_more:
                break

            offset += limit

        return documents

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
