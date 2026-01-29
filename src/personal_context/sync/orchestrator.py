"""Sync orchestrator for managing background sync tasks."""

import asyncio
import logging
from typing import Optional, Dict
from dataclasses import dataclass

from ..embeddings.client import EmbeddingClient
from ..upstream.base import UpstreamClient
from ..upstream.registry import UpstreamRegistry
from ..db.connection import get_connection
from ..config import settings
from .pull import pull_from_upstream, PullResult


logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Result of a sync operation."""
    collection_id: str
    success: bool
    result: Optional[PullResult] = None
    error: Optional[str] = None


class SyncOrchestrator:
    """Manages background sync tasks for upstream knowledge bases."""

    def __init__(
        self,
        upstream_registry: UpstreamRegistry,
        embedding_client: EmbeddingClient,
        sync_interval: int = 300,  # 5 minutes
    ):
        """
        Initialize sync orchestrator.

        Args:
            upstream_registry: Registry of upstream clients
            embedding_client: Embedding API client
            sync_interval: Sync interval in seconds
        """
        self.upstream_registry = upstream_registry
        self.embedding_client = embedding_client
        self.sync_interval = sync_interval
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    @staticmethod
    def get_collections_to_sync(collection_ids: Optional[list[str]] = None) -> list[str]:
        """
        Determine which collections to sync based on configuration.

        Args:
            collection_ids: Optional explicit list of collection IDs

        Returns:
            List of collection IDs to sync

        Raises:
            ValueError: If no collections are configured
        """
        if collection_ids:
            return collection_ids

        # Use configured collections or default to both outline and prompts collections
        if settings.sync_collections:
            return settings.sync_collections

        collections = []
        if settings.outline_collection_id:
            collections.append(settings.outline_collection_id)
        if settings.prompts_collection_id and settings.prompts_collection_id not in collections:
            collections.append(settings.prompts_collection_id)

        if not collections:
            raise ValueError("No collections configured for sync")

        return collections

    async def start(self) -> None:
        """Start background sync task."""
        if self._task is not None:
            logger.warning("Sync orchestrator already running")
            return

        logger.info(f"Starting sync orchestrator (interval: {self.sync_interval}s)")
        self._stop_event.clear()
        self._task = asyncio.create_task(self._sync_loop())

    async def stop(self) -> None:
        """Stop background sync gracefully."""
        if self._task is None:
            return

        logger.info("Stopping sync orchestrator")
        self._stop_event.set()

        try:
            await asyncio.wait_for(self._task, timeout=30.0)
        except asyncio.TimeoutError:
            logger.warning("Sync task did not stop gracefully, cancelling")
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._task = None

    async def sync_collection(self, collection_id: str, provider_name: str) -> SyncResult:
        """
        Sync a single collection from upstream knowledge base.

        Args:
            collection_id: Collection ID to sync
            provider_name: Provider name (e.g., 'outline', 'trilium')

        Returns:
            SyncResult with statistics
        """
        conn = get_connection()

        # Get the upstream client for this provider
        upstream_client = self.upstream_registry.get(provider_name)
        if not upstream_client:
            return SyncResult(
                collection_id=collection_id,
                success=False,
                error=f"Provider '{provider_name}' not registered"
            )

        try:
            # Check if sync is already in progress
            state = conn.execute(
                "SELECT status FROM sync_state WHERE collection_id = ?",
                (collection_id,)
            ).fetchone()

            if state and state[0] == "syncing":
                return SyncResult(
                    collection_id=collection_id,
                    success=False,
                    error="Sync already in progress"
                )

            # Mark as syncing
            conn.execute(
                "INSERT OR REPLACE INTO sync_state (collection_id, status, updated_at) "
                "VALUES (?, 'syncing', unixepoch('now'))",
                (collection_id,)
            )
            conn.commit()

            # Get last pull timestamp
            last_pull = conn.execute(
                "SELECT last_pull_at FROM sync_state WHERE collection_id = ?",
                (collection_id,)
            ).fetchone()
            last_pull_at = last_pull[0] if last_pull and last_pull[0] else None

            # Perform sync
            result = await pull_from_upstream(
                conn=conn,
                upstream_client=upstream_client,
                embedding_client=self.embedding_client,
                collection_id=collection_id,
                upstream_provider=provider_name,
                last_pull_at=last_pull_at,
            )

            # Update status
            if result.errors:
                conn.execute(
                    "UPDATE sync_state SET status = 'error', error_message = ?, updated_at = unixepoch('now') "
                    "WHERE collection_id = ?",
                    ("; ".join(result.errors[:3]), collection_id)
                )
            else:
                conn.execute(
                    "UPDATE sync_state SET status = 'idle', error_message = NULL, updated_at = unixepoch('now') "
                    "WHERE collection_id = ?",
                    (collection_id,)
                )
            conn.commit()

            logger.info(
                f"Synced {provider_name} collection {collection_id}: "
                f"created={result.created}, updated={result.updated}, "
                f"skipped={result.skipped}, errors={len(result.errors)}"
            )

            return SyncResult(
                collection_id=collection_id,
                success=len(result.errors) == 0,
                result=result
            )

        except Exception as e:
            logger.error(f"Failed to sync {provider_name} collection {collection_id}: {e}")

            # Mark as error
            try:
                conn.execute(
                    "UPDATE sync_state SET status = 'error', error_message = ?, updated_at = unixepoch('now') "
                    "WHERE collection_id = ?",
                    (str(e), collection_id)
                )
                conn.commit()
            except Exception:
                pass

            return SyncResult(
                collection_id=collection_id,
                success=False,
                error=str(e)
            )

    async def full_resync(self, collection_ids: Optional[list[str]] = None) -> dict:
        """
        Clear all local content and resync from upstream.

        This will:
        1. Delete all content, embeddings, and tags from local database
        2. Reset sync state
        3. Pull all documents from specified collections (or all configured collections)

        Args:
            collection_ids: Optional list of collection IDs to sync (uses configured collections if not provided)

        Returns:
            Statistics about the resync operation (collections synced, documents created, errors)
        """
        conn = get_connection()

        # Determine which collections to sync
        collection_ids = self.get_collections_to_sync(collection_ids)

        # Clear all local data
        try:
            conn.execute("DELETE FROM content_tags")
            conn.execute("DELETE FROM tags")
            conn.execute("DELETE FROM content_vec")
            conn.execute("DELETE FROM content")
            conn.execute("DELETE FROM sync_log")
            conn.execute("DELETE FROM sync_state")
            conn.commit()
            logger.info("Cleared all local data for full resync")
        except Exception as e:
            raise RuntimeError(f"Failed to clear local data: {str(e)}")

        # Resync each collection from all providers
        total_created = 0
        total_updated = 0
        total_errors = 0
        collection_results = []

        for collection_id in collection_ids:
            # Try to sync from each configured provider
            # (In practice, each collection belongs to one provider, but we try all)
            synced = False
            for provider_name in self.upstream_registry.get_providers():
                try:
                    sync_result = await self.sync_collection(collection_id, provider_name)

                    if sync_result.success and sync_result.result:
                        collection_results.append({
                            "collection_id": collection_id,
                            "provider": provider_name,
                            "created": sync_result.result.created,
                            "updated": sync_result.result.updated,
                            "errors": len(sync_result.result.errors),
                        })
                        total_created += sync_result.result.created
                        total_updated += sync_result.result.updated
                        total_errors += len(sync_result.result.errors)
                        synced = True
                        break  # Successfully synced from this provider
                    elif sync_result.result and sync_result.result.created == 0 and sync_result.result.updated == 0:
                        # Collection doesn't exist in this provider, try next
                        continue
                    else:
                        collection_results.append({
                            "collection_id": collection_id,
                            "provider": provider_name,
                            "error": sync_result.error or "Unknown error",
                        })
                        total_errors += 1

                except Exception as e:
                    logger.error(f"Error during full resync of {provider_name} collection {collection_id}: {e}")
                    collection_results.append({
                        "collection_id": collection_id,
                        "provider": provider_name,
                        "error": str(e),
                    })
                    total_errors += 1

            if not synced:
                logger.warning(f"Collection {collection_id} not found in any configured provider")

        logger.info(
            f"Full resync complete: {total_created} created, {total_updated} updated, "
            f"{total_errors} errors across {len(collection_ids)} collections"
        )

        return {
            "collections_synced": len(collection_ids),
            "total_created": total_created,
            "total_updated": total_updated,
            "total_errors": total_errors,
            "collection_results": collection_results,
            "message": f"Full resync complete: {total_created} documents created, {total_updated} updated from {len(collection_ids)} collections, {total_errors} errors",
        }

    async def _sync_loop(self) -> None:
        """Background sync loop."""
        while not self._stop_event.is_set():
            try:
                # Determine which collections to sync
                try:
                    collections = self.get_collections_to_sync()
                except ValueError as e:
                    logger.warning(str(e))
                    await asyncio.sleep(self.sync_interval)
                    continue

                # Sync each collection from all configured providers
                for collection_id in collections:
                    if self._stop_event.is_set():
                        break

                    # Try each provider for this collection
                    for provider_name in self.upstream_registry.get_providers():
                        if self._stop_event.is_set():
                            break

                        try:
                            await self.sync_collection(collection_id, provider_name)
                        except Exception as e:
                            logger.error(f"Error syncing {provider_name} collection {collection_id}: {e}")

            except Exception as e:
                logger.error(f"Error in sync loop: {e}")

            # Wait for next sync interval
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.sync_interval
                )
            except asyncio.TimeoutError:
                pass  # Normal timeout, continue loop
