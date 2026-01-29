"""Base protocol and data classes for upstream knowledge base clients."""

from dataclasses import dataclass
from typing import Optional, List, Protocol


@dataclass
class UpstreamDocument:
    """Normalized document from any upstream provider."""
    id: str
    title: str
    content: str  # normalized from 'text' (Outline) or other field names
    updated_at: float  # Unix timestamp (normalized from ISO strings, etc.)
    created_at: Optional[float] = None


@dataclass
class UpstreamCollection:
    """Normalized collection/folder from any upstream provider."""
    id: str
    name: str
    description: str = ""


@dataclass
class DocumentPage:
    """Paginated list of document summaries."""
    documents: List[UpstreamDocument]
    has_more: bool


class UpstreamClient(Protocol):
    """Protocol for upstream knowledge base clients."""

    async def create_document(
        self, title: str, content: str, collection_id: Optional[str] = None
    ) -> str:
        """Create document, return document ID. Used by add_content()."""
        ...

    async def get_document(self, doc_id: str) -> UpstreamDocument:
        """Get full document by ID."""
        ...

    async def list_documents(
        self, collection_id: str, limit: int = 100, offset: int = 0
    ) -> DocumentPage:
        """List documents sorted by updated_at DESC."""
        ...

    async def list_collections(self) -> List[UpstreamCollection]:
        """List all collections."""
        ...

    async def close(self) -> None:
        """Close client resources."""
        ...
