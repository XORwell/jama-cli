"""Tests for the caching layer."""

import time
from unittest.mock import MagicMock, patch

import pytest

from jama_cli.core.client import Cache, CacheEntry, JamaClient
from jama_cli.models import JamaProfile


class TestCacheEntry:
    """Tests for CacheEntry."""

    def test_is_expired_false(self) -> None:
        """Test that entry is not expired when TTL hasn't passed."""
        entry = CacheEntry("value", ttl=60)
        assert entry.is_expired is False

    def test_is_expired_true(self) -> None:
        """Test that entry is expired when TTL has passed."""
        entry = CacheEntry("value", ttl=0)
        time.sleep(0.01)  # Small delay to ensure expiration
        assert entry.is_expired is True


class TestCache:
    """Tests for Cache."""

    def test_get_miss(self) -> None:
        """Test cache miss returns None."""
        cache = Cache()
        assert cache.get("nonexistent") is None

    def test_set_and_get(self) -> None:
        """Test setting and getting a value."""
        cache = Cache()
        cache.set("key", "value", ttl=60)
        assert cache.get("key") == "value"

    def test_get_expired(self) -> None:
        """Test that expired entries return None."""
        cache = Cache()
        cache.set("key", "value", ttl=0)
        time.sleep(0.01)
        assert cache.get("key") is None

    def test_clear(self) -> None:
        """Test clearing the cache."""
        cache = Cache()
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.clear()
        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_invalidate(self) -> None:
        """Test invalidating cache entries by pattern."""
        cache = Cache()
        cache.set("item_types:123", "value1")
        cache.set("item_types:456", "value2")
        cache.set("projects:789", "value3")

        cache.invalidate("item_types")

        assert cache.get("item_types:123") is None
        assert cache.get("item_types:456") is None
        assert cache.get("projects:789") == "value3"

    def test_stats(self) -> None:
        """Test cache statistics."""
        cache = Cache()
        cache.set("key", "value")

        # Miss
        cache.get("nonexistent")
        # Hit
        cache.get("key")

        stats = cache.stats
        assert stats["size"] == 1
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 50.0


class TestJamaClientCaching:
    """Tests for JamaClient caching behavior."""

    @pytest.fixture
    def profile(self) -> JamaProfile:
        """Create a test profile."""
        return JamaProfile(
            url="https://test.jamacloud.com",
            auth_type="api_key",
            api_key="test_key",
        )

    @pytest.fixture
    def client(self, profile: JamaProfile) -> JamaClient:
        """Create a test client."""
        return JamaClient(profile)

    def test_clear_cache(self, client: JamaClient) -> None:
        """Test clearing the client cache."""
        client._cache.set("key", "value")
        client.clear_cache()
        assert client._cache.get("key") is None

    def test_get_cache_stats(self, client: JamaClient) -> None:
        """Test getting cache statistics."""
        stats = client.get_cache_stats()
        assert "memory" in stats
        assert "disk" in stats
        assert "size" in stats["memory"]
        assert "hits" in stats["memory"]
        assert "misses" in stats["memory"]
        assert "hit_rate" in stats["memory"]

    def test_cached_method_uses_cache(self, client: JamaClient) -> None:
        """Test that cached methods use the cache."""
        mock_jama_client = MagicMock()
        mock_jama_client.get_item_types.return_value = [{"id": 1, "name": "Test"}]

        with patch.object(client, "_client", mock_jama_client):
            # First call - should hit the API
            result1 = client.get_item_types()

            # Second call - should use cache
            result2 = client.get_item_types()

            # API should only be called once
            assert mock_jama_client.get_item_types.call_count == 1
            assert result1 == result2

    def test_cached_method_respects_ttl(self, client: JamaClient) -> None:
        """Test that cached methods respect TTL."""
        mock_jama_client = MagicMock()
        mock_jama_client.get_projects.return_value = [{"id": 1}]

        # Set a very short TTL for testing
        client._cache.set("projects:():[]", [{"id": 1}], ttl=0)

        with patch.object(client, "_client", mock_jama_client):
            time.sleep(0.01)  # Wait for cache to expire

            # Should call API because cache expired
            client.get_projects()

            assert mock_jama_client.get_projects.call_count == 1
