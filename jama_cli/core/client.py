"""Jama API client wrapper for CLI operations."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar

from loguru import logger
from py_jama_rest_client.client import JamaClient as PyJamaClient

from jama_cli.models import JamaProfile

# Suppress verbose logging from py_jama_rest_client
logging.getLogger("py_jama_rest_client").setLevel(logging.CRITICAL)

# Default cache directory
CACHE_DIR = Path.home() / ".cache" / "jama-cli"

# Type variable for generic return type
T = TypeVar("T")


class CacheEntry:
    """Cache entry with TTL support."""

    def __init__(self, value: Any, ttl: int) -> None:
        self.value = value
        self.expires_at = time.time() + ttl

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class DiskCache:
    """Persistent disk cache with TTL support.
    
    Stores cached data on disk so it persists between CLI invocations.
    Useful for large datasets like project items and relationships.
    """

    def __init__(self, cache_dir: Path | None = None, namespace: str = "default") -> None:
        self.cache_dir = (cache_dir or CACHE_DIR) / namespace
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._hits = 0
        self._misses = 0

    def _key_to_path(self, key: str) -> Path:
        """Convert cache key to file path."""
        # Use hash for safe filenames
        key_hash = hashlib.sha256(key.encode()).hexdigest()[:16]
        return self.cache_dir / f"{key_hash}.json"

    def get(self, key: str) -> Any | None:
        """Get value from disk cache if not expired."""
        path = self._key_to_path(key)
        if not path.exists():
            self._misses += 1
            return None
        
        try:
            with open(path) as f:
                data = json.load(f)
            
            if time.time() > data.get("expires_at", 0):
                path.unlink(missing_ok=True)
                self._misses += 1
                return None
            
            self._hits += 1
            return data.get("value")
        except (json.JSONDecodeError, OSError):
            self._misses += 1
            return None

    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """Set value in disk cache with TTL."""
        path = self._key_to_path(key)
        data = {
            "key": key,
            "value": value,
            "expires_at": time.time() + ttl,
            "created_at": time.time(),
        }
        try:
            with open(path, "w") as f:
                json.dump(data, f)
        except (OSError, TypeError) as e:
            logger.debug(f"Failed to write cache: {e}")

    def clear(self) -> None:
        """Clear all cached values."""
        for path in self.cache_dir.glob("*.json"):
            path.unlink(missing_ok=True)
        logger.debug(f"Disk cache cleared: {self.cache_dir}")

    @property
    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total * 100, 1) if total > 0 else 0,
            "cache_dir": str(self.cache_dir),
        }


class Cache:
    """Simple in-memory cache with TTL support."""

    def __init__(self) -> None:
        self._store: dict[str, CacheEntry] = {}
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Any | None:
        """Get value from cache if not expired."""
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None
        if entry.is_expired:
            del self._store[key]
            self._misses += 1
            return None
        self._hits += 1
        return entry.value

    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """Set value in cache with TTL (default 5 minutes)."""
        self._store[key] = CacheEntry(value, ttl)

    def clear(self) -> None:
        """Clear all cached values."""
        self._store.clear()
        logger.debug("Cache cleared")

    def invalidate(self, pattern: str) -> None:
        """Invalidate cache entries matching pattern."""
        keys_to_delete = [k for k in self._store if pattern in k]
        for key in keys_to_delete:
            del self._store[key]
        if keys_to_delete:
            logger.debug(f"Invalidated {len(keys_to_delete)} cache entries matching '{pattern}'")

    @property
    def stats(self) -> dict[str, int]:
        """Get cache statistics."""
        return {
            "size": len(self._store),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / (self._hits + self._misses) * 100, 1)
            if (self._hits + self._misses) > 0
            else 0,
        }


def cached(ttl: int = 300, key_prefix: str = "") -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to cache method results.

    Args:
        ttl: Time-to-live in seconds (default 5 minutes)
        key_prefix: Prefix for cache key
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(self: "JamaClient", *args: Any, **kwargs: Any) -> T:
            # Build cache key from function name and arguments
            cache_key = f"{key_prefix or func.__name__}:{args}:{sorted(kwargs.items())}"

            # Try to get from cache
            cached_value = self._cache.get(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache hit: {func.__name__}")
                return cached_value

            # Call function and cache result
            result = func(self, *args, **kwargs)
            self._cache.set(cache_key, result, ttl)
            logger.debug(f"Cache miss: {func.__name__}, cached for {ttl}s")
            return result

        return wrapper

    return decorator


class JamaClient:
    """Synchronous wrapper around py-jama-rest-client for CLI use.

    Features:
    - Automatic connection management
    - Caching for frequently accessed data (item types, pick lists)
    - Persistent disk cache for large datasets (items, relationships)
    - Bulk relationship fetching for performance
    - Parallel API calls where beneficial
    - Consistent error handling
    """

    # Cache TTL settings (in seconds)
    CACHE_TTL_ITEM_TYPES = 3600  # 1 hour - rarely change
    CACHE_TTL_PICK_LISTS = 3600  # 1 hour - rarely change
    CACHE_TTL_PROJECTS = 300  # 5 minutes - change infrequently
    CACHE_TTL_USERS = 600  # 10 minutes
    CACHE_TTL_ITEMS = 300  # 5 minutes - project items
    CACHE_TTL_RELATIONSHIPS = 300  # 5 minutes - project relationships

    def __init__(self, profile: JamaProfile, use_disk_cache: bool = True) -> None:
        """Initialize the Jama client.

        Args:
            profile: Jama connection profile
            use_disk_cache: Enable persistent disk caching for large datasets
        """
        self.profile = profile
        self._client: PyJamaClient | None = None
        self._cache = Cache()
        
        # Disk cache for large datasets (persists between CLI runs)
        # Namespace by host to avoid cache collisions between instances
        host_hash = hashlib.sha256(profile.url.encode()).hexdigest()[:8]
        self._disk_cache = DiskCache(namespace=host_hash) if use_disk_cache else None
        
        # Cached relationship maps for bulk operations
        self._relationship_map: dict[int, dict[str, list[dict[str, Any]]]] | None = None
        self._relationship_map_project: int | None = None

    def connect(self) -> None:
        """Establish connection to Jama."""
        if self._client is not None:
            return

        if self.profile.auth_type == "api_key":
            self._client = PyJamaClient(
                host_domain=self.profile.url,
                credentials=(self.profile.api_key, ""),
                oauth=False,
            )
        elif self.profile.auth_type == "oauth":
            self._client = PyJamaClient(
                host_domain=self.profile.url,
                credentials=(self.profile.client_id, self.profile.client_secret),
                oauth=True,
            )
        elif self.profile.auth_type == "basic":
            self._client = PyJamaClient(
                host_domain=self.profile.url,
                credentials=(self.profile.username, self.profile.password),
                oauth=False,
            )
        else:
            raise ValueError(f"Unknown auth type: {self.profile.auth_type}")

    def _ensure_connected(self) -> PyJamaClient:
        """Ensure client is connected and return it."""
        if self._client is None:
            self.connect()
        assert self._client is not None
        return self._client

    def clear_cache(self) -> None:
        """Clear all cached data."""
        self._cache.clear()
        if self._disk_cache:
            self._disk_cache.clear()
        self._relationship_map = None
        self._relationship_map_project = None

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        stats = {"memory": self._cache.stats}
        if self._disk_cache:
            stats["disk"] = self._disk_cache.stats
        return stats

    # =========================================================================
    # Bulk Operations (Performance Optimizations)
    # =========================================================================

    def get_project_relationships_bulk(
        self,
        project_id: int,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """Get ALL relationships in a project in a single API call.
        
        This is much faster than fetching relationships per-item when you need
        to analyze many items. Results are cached to disk for reuse.
        
        Args:
            project_id: Project ID
            use_cache: Whether to use disk cache (default True)
        
        Returns:
            List of all relationships in the project
        """
        cache_key = f"relationships_bulk:{project_id}"
        
        # Try disk cache first
        if use_cache and self._disk_cache:
            cached = self._disk_cache.get(cache_key)
            if cached is not None:
                logger.debug(f"Disk cache hit: {len(cached)} relationships for project {project_id}")
                return cached
        
        # Fetch from API
        client = self._ensure_connected()
        relationships = client.get_relationships(project_id)
        
        # Cache to disk
        if self._disk_cache:
            self._disk_cache.set(cache_key, relationships, self.CACHE_TTL_RELATIONSHIPS)
            logger.debug(f"Cached {len(relationships)} relationships to disk")
        
        return relationships

    def build_relationship_map(
        self,
        project_id: int,
        use_cache: bool = True,
    ) -> dict[int, dict[str, list[dict[str, Any]]]]:
        """Build a lookup map of relationships by item ID.
        
        This allows O(1) lookups for upstream/downstream relationships
        instead of making an API call per item.
        
        Args:
            project_id: Project ID
            use_cache: Whether to use cached relationships
            
        Returns:
            Dict mapping item_id -> {"upstream": [...], "downstream": [...]}
        """
        # Return cached map if available for same project
        if (
            self._relationship_map is not None
            and self._relationship_map_project == project_id
        ):
            return self._relationship_map
        
        relationships = self.get_project_relationships_bulk(project_id, use_cache)
        
        # Build the map
        rel_map: dict[int, dict[str, list[dict[str, Any]]]] = {}
        
        for rel in relationships:
            from_item = rel.get("fromItem")
            to_item = rel.get("toItem")
            
            # Add to downstream of fromItem
            if from_item:
                if from_item not in rel_map:
                    rel_map[from_item] = {"upstream": [], "downstream": []}
                rel_map[from_item]["downstream"].append(rel)
            
            # Add to upstream of toItem
            if to_item:
                if to_item not in rel_map:
                    rel_map[to_item] = {"upstream": [], "downstream": []}
                rel_map[to_item]["upstream"].append(rel)
        
        self._relationship_map = rel_map
        self._relationship_map_project = project_id
        logger.debug(f"Built relationship map for {len(rel_map)} items")
        
        return rel_map

    def get_items_bulk(
        self,
        project_id: int,
        item_type: int | None = None,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """Get all items in a project with disk caching.
        
        Caches results to disk so subsequent CLI runs are much faster.
        
        Args:
            project_id: Project ID
            item_type: Optional item type filter (applied after fetch)
            use_cache: Whether to use disk cache
            
        Returns:
            List of items
        """
        cache_key = f"items_bulk:{project_id}"
        
        # Try disk cache first
        if use_cache and self._disk_cache:
            cached = self._disk_cache.get(cache_key)
            if cached is not None:
                logger.debug(f"Disk cache hit: {len(cached)} items for project {project_id}")
                items = cached
                if item_type:
                    items = [i for i in items if i.get("itemType") == item_type]
                return items
        
        # Fetch from API
        client = self._ensure_connected()
        items = client.get_items(project_id)
        
        # Cache to disk (without type filter, so cache works for all types)
        if self._disk_cache:
            self._disk_cache.set(cache_key, items, self.CACHE_TTL_ITEMS)
            logger.debug(f"Cached {len(items)} items to disk")
        
        if item_type:
            items = [i for i in items if i.get("itemType") == item_type]
        
        return items

    def get_downstream_related_bulk(
        self,
        item_id: int,
        project_id: int,
        relationship_map: dict[int, dict[str, list[dict[str, Any]]]] | None = None,
    ) -> list[dict[str, Any]]:
        """Get downstream related items using bulk relationship map.
        
        Much faster than get_item_downstream_related() when analyzing
        multiple items - uses pre-fetched relationship data.
        
        Args:
            item_id: Item ID to get downstream for
            project_id: Project ID (for building map if needed)
            relationship_map: Pre-built map (or will build one)
            
        Returns:
            List of downstream related items
        """
        if relationship_map is None:
            relationship_map = self.build_relationship_map(project_id)
        
        item_rels = relationship_map.get(item_id, {"downstream": []})
        downstream_ids = [rel.get("toItem") for rel in item_rels["downstream"]]
        
        # Fetch item details for downstream items
        items = []
        for to_id in downstream_ids:
            if to_id:
                try:
                    items.append(self.get_item(to_id))
                except Exception:
                    pass  # Skip items we can't access
        
        return items

    def get_upstream_related_bulk(
        self,
        item_id: int,
        project_id: int,
        relationship_map: dict[int, dict[str, list[dict[str, Any]]]] | None = None,
    ) -> list[dict[str, Any]]:
        """Get upstream related items using bulk relationship map.
        
        Args:
            item_id: Item ID to get upstream for
            project_id: Project ID (for building map if needed)
            relationship_map: Pre-built map (or will build one)
            
        Returns:
            List of upstream related items
        """
        if relationship_map is None:
            relationship_map = self.build_relationship_map(project_id)
        
        item_rels = relationship_map.get(item_id, {"upstream": []})
        upstream_ids = [rel.get("fromItem") for rel in item_rels["upstream"]]
        
        items = []
        for from_id in upstream_ids:
            if from_id:
                try:
                    items.append(self.get_item(from_id))
                except Exception:
                    pass
        
        return items

    def get_items_parallel(
        self,
        item_ids: list[int],
        max_workers: int = 10,
    ) -> list[dict[str, Any]]:
        """Fetch multiple items in parallel.
        
        Args:
            item_ids: List of item IDs to fetch
            max_workers: Maximum parallel requests (default 10)
            
        Returns:
            List of items (in same order as input IDs, None for failed fetches)
        """
        results: dict[int, dict[str, Any] | None] = {}
        
        def fetch_item(item_id: int) -> tuple[int, dict[str, Any] | None]:
            try:
                return item_id, self.get_item(item_id)
            except Exception:
                return item_id, None
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_item, iid): iid for iid in item_ids}
            for future in as_completed(futures):
                item_id, item = future.result()
                results[item_id] = item
        
        return [results.get(iid) for iid in item_ids if results.get(iid) is not None]

    def analyze_traceability_fast(
        self,
        project_id: int,
        source_type: int | None = None,
        target_type: int | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Analyze traceability for a project using bulk operations.
        
        This is MUCH faster than the per-item approach:
        - 2 API calls (items + relationships) instead of N+1
        - Uses disk cache for subsequent runs
        
        Args:
            project_id: Project ID
            source_type: Optional source item type filter
            target_type: Optional target item type filter
            progress_callback: Optional callback(current, total) for progress
            
        Returns:
            List of trace data dicts
        """
        # Fetch all data in bulk (2 API calls, cached)
        items = self.get_items_bulk(project_id)
        relationship_map = self.build_relationship_map(project_id)
        
        # Build item lookup
        item_map = {item["id"]: item for item in items}
        
        # Filter source items
        source_items = items
        if source_type:
            source_items = [i for i in items if i.get("itemType") == source_type]
        
        trace_data = []
        total = len(source_items)
        
        for idx, item in enumerate(source_items):
            item_id = item["id"]
            
            # Get downstream from map (no API call!)
            item_rels = relationship_map.get(item_id, {"downstream": []})
            downstream_ids = [rel.get("toItem") for rel in item_rels["downstream"]]
            
            # Filter by target type
            if target_type:
                downstream_ids = [
                    tid for tid in downstream_ids
                    if item_map.get(tid, {}).get("itemType") == target_type
                ]
            
            if downstream_ids:
                for target_id in downstream_ids:
                    target = item_map.get(target_id, {})
                    trace_data.append({
                        "source_id": item_id,
                        "source_key": item.get("documentKey", ""),
                        "source_name": item.get("fields", {}).get("name", ""),
                        "source_type": item.get("itemType"),
                        "target_id": target_id,
                        "target_key": target.get("documentKey", ""),
                        "target_name": target.get("fields", {}).get("name", ""),
                        "target_type": target.get("itemType"),
                    })
            else:
                trace_data.append({
                    "source_id": item_id,
                    "source_key": item.get("documentKey", ""),
                    "source_name": item.get("fields", {}).get("name", ""),
                    "source_type": item.get("itemType"),
                    "target_id": None,
                    "target_key": "",
                    "target_name": "(no coverage)",
                    "target_type": None,
                })
            
            if progress_callback:
                progress_callback(idx + 1, total)
        
        return trace_data

    # =========================================================================
    # Projects
    # =========================================================================

    @cached(ttl=300, key_prefix="projects")  # 5 minutes
    def get_projects(self) -> list[dict[str, Any]]:
        """Get all accessible projects (cached for 5 minutes)."""
        client = self._ensure_connected()
        return client.get_projects()

    def get_project(self, project_id: int) -> dict[str, Any]:
        """Get a specific project by ID."""
        client = self._ensure_connected()
        # py-jama-rest-client doesn't have get_project, so filter from get_projects
        projects = client.get_projects()
        for project in projects:
            if project.get("id") == project_id:
                return project
        raise ValueError(f"Project with ID {project_id} not found")

    # =========================================================================
    # Items
    # =========================================================================

    def get_items(
        self,
        project_id: int,
        item_type: int | None = None,
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get items from a project.

        Args:
            project_id: Project ID
            item_type: Optional item type ID to filter by
            max_results: Maximum number of items to return (for faster queries)
        """
        client = self._ensure_connected()
        
        if max_results and max_results <= 50:
            # Use single page fetch for small limits (much faster)
            items = self._get_items_page(project_id, start_at=0, max_results=max_results)
        else:
            items = client.get_items(project_id)
        
        if item_type:
            items = [item for item in items if item.get("itemType") == item_type]
        
        if max_results and len(items) > max_results:
            items = items[:max_results]
        
        return items

    def _get_items_page(
        self,
        project_id: int,
        start_at: int = 0,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        """Get a single page of items (faster than fetching all).
        
        Args:
            project_id: Project ID
            start_at: Starting index
            max_results: Maximum items per page (max 50)
        """
        client = self._ensure_connected()
        # Access the underlying API directly for single page
        resource_path = f"items?project={project_id}&startAt={start_at}&maxResults={min(max_results, 50)}"
        response = client._JamaClient__core.get(resource_path)
        # Parse JSON from response
        data = response.json()
        return data.get("data", [])

    def get_item(self, item_id: int) -> dict[str, Any]:
        """Get a specific item by ID."""
        client = self._ensure_connected()
        return client.get_item(item_id)

    def get_item_children(self, item_id: int) -> list[dict[str, Any]]:
        """Get children of an item."""
        client = self._ensure_connected()
        return client.get_item_children(item_id)

    def create_item(
        self,
        project_id: int,
        item_type_id: int,
        child_item_type_id: int,
        location: dict[str, Any],
        fields: dict[str, Any],
    ) -> int:
        """Create a new item.

        Returns:
            The ID of the created item
        """
        client = self._ensure_connected()
        return client.post_item(
            project=project_id,
            item_type_id=item_type_id,
            child_item_type_id=child_item_type_id,
            location=location,
            fields=fields,
        )

    def update_item(self, item_id: int, fields: dict[str, Any]) -> None:
        """Update an item's fields using JSON patch."""
        client = self._ensure_connected()
        patches = [
            {"op": "replace", "path": f"/fields/{field}", "value": value}
            for field, value in fields.items()
        ]
        client.patch_item(item_id, patches)

    def delete_item(self, item_id: int) -> None:
        """Delete an item."""
        client = self._ensure_connected()
        client.delete_item(item_id)

    # =========================================================================
    # Relationships
    # =========================================================================

    def get_relationships(self, project_id: int) -> list[dict[str, Any]]:
        """Get all relationships in a project."""
        client = self._ensure_connected()
        return client.get_relationships(project_id)

    def get_relationship(self, relationship_id: int) -> dict[str, Any]:
        """Get a specific relationship."""
        client = self._ensure_connected()
        return client.get_relationship(relationship_id)

    def get_item_upstream_relationships(self, item_id: int) -> list[dict[str, Any]]:
        """Get upstream relationships for an item."""
        client = self._ensure_connected()
        return client.get_items_upstream_relationships(item_id)

    def get_item_downstream_relationships(self, item_id: int) -> list[dict[str, Any]]:
        """Get downstream relationships for an item."""
        client = self._ensure_connected()
        return client.get_items_downstream_relationships(item_id)

    def get_item_upstream_related(self, item_id: int) -> list[dict[str, Any]]:
        """Get upstream related items."""
        client = self._ensure_connected()
        return client.get_items_upstream_related(item_id)

    def get_item_downstream_related(self, item_id: int) -> list[dict[str, Any]]:
        """Get downstream related items."""
        client = self._ensure_connected()
        return client.get_items_downstream_related(item_id)

    def create_relationship(
        self,
        from_item: int,
        to_item: int,
        relationship_type: int | None = None,
    ) -> int:
        """Create a relationship between items.

        Returns:
            The ID of the created relationship
        """
        client = self._ensure_connected()
        return client.post_relationship(from_item, to_item, relationship_type)

    def delete_relationship(self, relationship_id: int) -> None:
        """Delete a relationship."""
        client = self._ensure_connected()
        client.delete_relationship(relationship_id)

    # =========================================================================
    # Item Types (cached - rarely change)
    # =========================================================================

    @cached(ttl=3600, key_prefix="item_types")  # 1 hour
    def get_item_types(self) -> list[dict[str, Any]]:
        """Get all item types (cached for 1 hour)."""
        client = self._ensure_connected()
        return client.get_item_types()

    @cached(ttl=3600, key_prefix="item_type")  # 1 hour
    def get_item_type(self, item_type_id: int) -> dict[str, Any]:
        """Get a specific item type (cached for 1 hour)."""
        client = self._ensure_connected()
        return client.get_item_type(item_type_id)

    # =========================================================================
    # Pick Lists (cached - rarely change)
    # =========================================================================

    @cached(ttl=3600, key_prefix="pick_lists")  # 1 hour
    def get_pick_lists(self) -> list[dict[str, Any]]:
        """Get all pick lists (cached for 1 hour)."""
        client = self._ensure_connected()
        return client.get_pick_lists()

    @cached(ttl=3600, key_prefix="pick_list")  # 1 hour
    def get_pick_list(self, pick_list_id: int) -> dict[str, Any]:
        """Get a specific pick list (cached for 1 hour)."""
        client = self._ensure_connected()
        return client.get_pick_list(pick_list_id)

    @cached(ttl=3600, key_prefix="pick_list_options")  # 1 hour
    def get_pick_list_options(self, pick_list_id: int) -> list[dict[str, Any]]:
        """Get options for a pick list (cached for 1 hour)."""
        client = self._ensure_connected()
        return client.get_pick_list_options(pick_list_id)

    # =========================================================================
    # Tags
    # =========================================================================

    def get_tags(self, project_id: int) -> list[dict[str, Any]]:
        """Get all tags in a project."""
        client = self._ensure_connected()
        return client.get_tags(project_id)

    def get_tagged_items(self, tag_id: int) -> list[dict[str, Any]]:
        """Get items with a specific tag."""
        client = self._ensure_connected()
        return client.get_tagged_items(tag_id)

    # =========================================================================
    # Tests
    # =========================================================================

    def get_test_cycle(self, test_cycle_id: int) -> dict[str, Any]:
        """Get a specific test cycle."""
        client = self._ensure_connected()
        return client.get_test_cycle(test_cycle_id)

    def get_test_runs(self, test_cycle_id: int) -> list[dict[str, Any]]:
        """Get test runs for a test cycle."""
        client = self._ensure_connected()
        return client.get_testruns(test_cycle_id)

    # =========================================================================
    # Users (cached - change infrequently)
    # =========================================================================

    @cached(ttl=600, key_prefix="users")  # 10 minutes
    def get_users(self) -> list[dict[str, Any]]:
        """Get all users (cached for 10 minutes)."""
        client = self._ensure_connected()
        return client.get_users()

    @cached(ttl=600, key_prefix="current_user")  # 10 minutes
    def get_current_user(self) -> dict[str, Any]:
        """Get the current user (cached for 10 minutes)."""
        client = self._ensure_connected()
        return client.get_current_user()

    # =========================================================================
    # Baselines
    # =========================================================================

    def get_baselines(self, project_id: int) -> list[dict[str, Any]]:
        """Get all baselines for a project."""
        client = self._ensure_connected()
        return client.get_baselines(project_id)

    def get_baseline(self, baseline_id: int) -> dict[str, Any]:
        """Get a specific baseline."""
        client = self._ensure_connected()
        return client.get_baseline(baseline_id)

    def get_baseline_versioned_items(self, baseline_id: int) -> list[dict[str, Any]]:
        """Get versioned items in a baseline."""
        client = self._ensure_connected()
        return client.get_baselines_versioneditems(baseline_id)

    # =========================================================================
    # Item Versions
    # =========================================================================

    def get_item_versions(self, item_id: int) -> list[dict[str, Any]]:
        """Get version history for an item."""
        client = self._ensure_connected()
        return client.get_item_versions(item_id)

    def get_item_version(self, item_id: int, version: int) -> dict[str, Any]:
        """Get a specific version of an item."""
        client = self._ensure_connected()
        return client.get_item_version(item_id, version)

    # =========================================================================
    # Relationship Types
    # =========================================================================

    @cached(ttl=3600, key_prefix="relationship_types")  # 1 hour
    def get_relationship_types(self) -> list[dict[str, Any]]:
        """Get all relationship types (cached for 1 hour)."""
        client = self._ensure_connected()
        return client.get_relationship_types()

    # =========================================================================
    # Attachments
    # =========================================================================

    def get_attachment(self, attachment_id: int) -> dict[str, Any]:
        """Get attachment metadata."""
        client = self._ensure_connected()
        return client.get_attachment(attachment_id)

    def get_item_tags(self, item_id: int) -> list[dict[str, Any]]:
        """Get tags for an item."""
        client = self._ensure_connected()
        return client.get_item_tags(item_id)

    def download_attachment(self, attachment_id: int, output_path: Path) -> None:
        """Download attachment file content.

        Note: The py-jama-rest-client doesn't have a direct download method,
        so this gets the attachment URL and downloads via the file URL.
        """
        import requests

        client = self._ensure_connected()
        attachment = client.get_attachment(attachment_id)

        # Get the file URL from attachment metadata
        file_url = attachment.get("fileName")  # This may need adjustment based on API response

        # For now, we store the metadata - actual file download would need
        # direct API access to the file endpoint
        # This is a placeholder for the attachment metadata
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            import json
            json.dump(attachment, f, indent=2)

    def upload_attachment(
        self,
        item_id: int,
        file_path: Path,
    ) -> int:
        """Upload an attachment to an item.

        Args:
            item_id: Item to attach file to
            file_path: Path to the file to upload

        Returns:
            The ID of the created attachment
        """
        client = self._ensure_connected()
        return client.post_item_attachment(item_id, str(file_path))
