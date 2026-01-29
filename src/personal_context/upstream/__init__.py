"""Upstream integration module initialization."""

from .base import (
    DocumentPage,
    UpstreamClient,
    UpstreamCollection,
    UpstreamDocument,
)
from .outline import OutlineClient
from .trilium import TriliumClient
from .registry import UpstreamRegistry

__all__ = [
    "DocumentPage",
    "OutlineClient",
    "TriliumClient",
    "UpstreamClient",
    "UpstreamCollection",
    "UpstreamDocument",
    "UpstreamRegistry",
]
