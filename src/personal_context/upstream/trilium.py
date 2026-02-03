"""Trilium Notes ETAPI client for upstream knowledge base integration."""

import httpx
from datetime import datetime
from typing import Optional, List

from .base import UpstreamDocument, UpstreamCollection, DocumentPage


class TriliumClient:
    """Client for Trilium Notes ETAPI."""

    def __init__(self, api_base: str, api_token: str):
        """
        Initialize Trilium client.

        Args:
            api_base: Trilium ETAPI base URL (e.g., http://localhost:8080/etapi)
            api_token: ETAPI token
        """
        self.api_base = api_base.rstrip("/")
        self.api_token = api_token
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Authorization": self.api_token,
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
        Create a new note in Trilium.

        Args:
            title: Note title
            content: Note content (text or HTML)
            collection_id: Parent note ID (uses root if not provided)

        Returns:
            Note ID
        """
        parent_note_id = collection_id or "root"

        # Create note
        response = await self.client.post(
            f"{self.api_base}/create-note",
            json={
                "parentNoteId": parent_note_id,
                "title": title,
                "type": "text",
                "content": content,
            },
        )
        response.raise_for_status()

        data = response.json()
        return data["note"]["noteId"]

    async def update_document(self, doc_id: str, content: str) -> None:
        """Update note content in Trilium.

        Args:
            doc_id: Note ID
            content: New content
        """
        response = await self.client.put(
            f"{self.api_base}/notes/{doc_id}/content",
            content=content,
        )
        response.raise_for_status()

    async def get_document(self, doc_id: str) -> UpstreamDocument:
        """
        Retrieve a single note by ID.

        Args:
            doc_id: Note ID

        Returns:
            Normalized UpstreamDocument
        """
        # Get note metadata
        response = await self.client.get(f"{self.api_base}/notes/{doc_id}")
        response.raise_for_status()
        note = response.json()

        # Get note content
        content_response = await self.client.get(
            f"{self.api_base}/notes/{doc_id}/content"
        )
        content_response.raise_for_status()
        content = content_response.text

        # Parse timestamps (Trilium uses format: "2024-01-29 14:30:45.123+0000")
        updated_at = self._parse_trilium_timestamp(note["utcDateModified"])
        created_at = self._parse_trilium_timestamp(note["utcDateCreated"])

        return UpstreamDocument(
            id=note["noteId"],
            title=note["title"],
            content=content,
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
        List notes under a parent note.

        Args:
            collection_id: Parent note ID
            limit: Number of notes per page (not used by Trilium, fetches all)
            offset: Pagination offset (not used by Trilium)

        Returns:
            DocumentPage with normalized documents
        """
        # Search for all notes under parent
        response = await self.client.get(
            f"{self.api_base}/notes/{collection_id}/children"
        )
        response.raise_for_status()

        children = response.json()

        # Fetch full details for each child note
        documents = []
        for child in children:
            note_id = child["noteId"]

            # Get note details
            note_response = await self.client.get(f"{self.api_base}/notes/{note_id}")
            note_response.raise_for_status()
            note = note_response.json()

            # Get content (lightweight - just check if exists)
            try:
                content_response = await self.client.get(
                    f"{self.api_base}/notes/{note_id}/content"
                )
                content = (
                    content_response.text if content_response.status_code == 200 else ""
                )
            except Exception:
                content = ""

            updated_at = self._parse_trilium_timestamp(note["utcDateModified"])
            created_at = self._parse_trilium_timestamp(note["utcDateCreated"])

            documents.append(
                UpstreamDocument(
                    id=note["noteId"],
                    title=note["title"],
                    content=content,
                    updated_at=updated_at,
                    created_at=created_at,
                )
            )

        # Sort by updated_at DESC
        documents.sort(key=lambda d: d.updated_at, reverse=True)

        # Apply pagination
        paginated_docs = documents[offset : offset + limit]
        has_more = (offset + limit) < len(documents)

        return DocumentPage(documents=paginated_docs, has_more=has_more)

    async def list_collections(self) -> List[UpstreamCollection]:
        """
        List all top-level notes (collections).

        Returns:
            List of normalized UpstreamCollection objects
        """
        # Get root note's children
        response = await self.client.get(f"{self.api_base}/notes/root/children")
        response.raise_for_status()

        children = response.json()
        collections = []

        for child in children:
            note_id = child["noteId"]

            # Get note details
            note_response = await self.client.get(f"{self.api_base}/notes/{note_id}")
            note_response.raise_for_status()
            note = note_response.json()

            collections.append(
                UpstreamCollection(
                    id=note["noteId"],
                    name=note["title"],
                    description="",  # Trilium doesn't have collection descriptions
                )
            )

        return collections

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

    @staticmethod
    def _parse_trilium_timestamp(timestamp_str: str) -> float:
        """
        Parse Trilium timestamp to Unix timestamp.

        Trilium format: "2024-01-29 14:30:45.123+0000"

        Args:
            timestamp_str: Trilium timestamp string

        Returns:
            Unix timestamp (float)
        """
        # Remove timezone suffix and parse
        # Format: "2024-01-29 14:30:45.123+0000" -> "2024-01-29 14:30:45.123"
        timestamp_clean = timestamp_str.split("+")[0].split("-")[0:3]
        timestamp_clean = (
            "-".join(timestamp_clean[:3])
            + " "
            + timestamp_str.split(" ")[1].split("+")[0]
        )

        # Parse datetime
        dt = datetime.strptime(timestamp_clean, "%Y-%m-%d %H:%M:%S.%f")

        return dt.timestamp()
