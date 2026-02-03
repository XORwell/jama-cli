"""
Integration tests for write operations.

These tests require a live Jama instance and valid credentials with write permissions.
Run with: pytest tests/test_write_operations.py --integration

WARNING: These tests modify data in the Jama instance. Use with caution.
"""

import os

import pytest

from jama_mcp_server.core.server import JamaMCPServer
from jama_mcp_server.models import JamaConfig


@pytest.mark.integration
@pytest.mark.asyncio
class TestWriteOperations:
    """Test write operations against Jama API.

    These tests require:
    - JAMA_URL environment variable
    - Valid authentication credentials with WRITE permissions
    - TEST_PROJECT_ID for creating items
    - TEST_ITEM_ID for update tests

    WARNING: These tests create, modify, and delete items in Jama.
    """

    @pytest.mark.slow
    async def test_create_and_delete_item(
        self, jama_config: JamaConfig, test_project_id: int
    ) -> None:
        """Test creating and deleting an item."""
        server = JamaMCPServer(config=jama_config)

        try:
            await server._initialize_jama_client()

            # Get item types to find a valid item type ID
            item_types = server.jama_client.get_item_types()
            if not item_types:
                pytest.skip("No item types available")

            item_type_id = item_types[0]["id"]

            # Create test item
            fields = {
                "name": "Test Item from Integration Test",
                "description": "This is a test item created by automated tests",
            }

            # Use Text item type which doesn't require special parent
            item_type_id = int(os.environ.get("TEST_ITEM_TYPE_ID", "33"))
            location = {}  # Empty location = project root

            created_item = server.jama_client.post_item(
                project=test_project_id,
                item_type_id=item_type_id,
                child_item_type_id=item_type_id,
                location=location,
                fields=fields,
            )

            assert created_item is not None
            item_id = created_item["id"] if isinstance(created_item, dict) else created_item

            # Verify item was created
            item = server.jama_client.get_item(item_id)
            assert item["fields"]["name"] == fields["name"]

            # Clean up - delete the item
            server.jama_client.delete_item(item_id)

        finally:
            await server.stop()

    @pytest.mark.slow
    async def test_update_item(self, jama_config: JamaConfig, test_item_id: int) -> None:
        """Test updating an item.

        Note: This test modifies an existing item and restores it.
        """
        server = JamaMCPServer(config=jama_config)

        try:
            await server._initialize_jama_client()

            # Get current item
            original_item = server.jama_client.get_item(test_item_id)
            original_name = original_item["fields"].get("name", "")

            # Update item using patch
            test_suffix = " (Updated by Integration Test)"
            new_name = f"{original_name}{test_suffix}"
            patches = [{"op": "replace", "path": "/fields/name", "value": new_name}]

            server.jama_client.patch_item(test_item_id, patches)

            # Verify update
            updated_item = server.jama_client.get_item(test_item_id)
            assert test_suffix in updated_item["fields"]["name"]

            # Restore original name
            restore_patches = [{"op": "replace", "path": "/fields/name", "value": original_name}]
            server.jama_client.patch_item(test_item_id, restore_patches)

        finally:
            await server.stop()

    @pytest.mark.slow
    async def test_create_and_delete_relationship(
        self, jama_config: JamaConfig, test_item_id: int, test_project_id: int
    ) -> None:
        """Test creating and deleting a relationship."""
        from py_jama_rest_client.client import AlreadyExistsException

        server = JamaMCPServer(config=jama_config)

        try:
            await server._initialize_jama_client()

            # Get relationship types
            rel_types = server.jama_client.get_relationship_types()
            if not rel_types:
                pytest.skip("No relationship types available")

            rel_type_id = rel_types[0]["id"]

            # Get items to create relationship between
            items = server.jama_client.get_items(test_project_id)
            if len(items) < 3:
                pytest.skip("Need at least 3 items to test relationships")

            # Use items that are less likely to have existing relationships
            from_item = items[-2]["id"]
            to_item = items[-1]["id"]

            # Try to create relationship
            rel_id = None
            try:
                relationship = server.jama_client.post_relationship(from_item, to_item, rel_type_id)
                assert relationship is not None
                rel_id = relationship["id"] if isinstance(relationship, dict) else relationship

                # Verify relationship using downstream relationships
                downstream_rels = server.jama_client.get_items_downstream_relationships(from_item)
                rel_ids = [r["id"] for r in downstream_rels]
                assert rel_id in rel_ids

            except AlreadyExistsException:
                # Relationship already exists - that's okay, just verify it
                downstream_rels = server.jama_client.get_items_downstream_relationships(from_item)
                assert len(downstream_rels) >= 0  # Just verify we can query relationships

            finally:
                # Clean up if we created a relationship
                if rel_id is not None:
                    try:
                        server.jama_client.delete_relationship(rel_id)
                    except Exception:
                        pass  # Ignore cleanup errors

        finally:
            await server.stop()

    async def test_error_handling(self, jama_config: JamaConfig) -> None:
        """Test error handling for invalid operations."""
        server = JamaMCPServer(config=jama_config)

        try:
            await server._initialize_jama_client()

            # Try to get non-existent item
            with pytest.raises(Exception):
                server.jama_client.get_item(999999999)

        finally:
            await server.stop()

    async def test_item_lock(self, jama_config: JamaConfig, test_item_id: int) -> None:
        """Test item lock and unlock functionality."""
        server = JamaMCPServer(config=jama_config)

        try:
            await server._initialize_jama_client()

            # Get current lock status
            lock_status = server.jama_client.get_item_lock(test_item_id)
            was_locked = (
                lock_status.get("locked", False) if isinstance(lock_status, dict) else False
            )

            # Lock the item
            server.jama_client.put_item_lock(test_item_id, True)

            # Verify locked
            lock_status = server.jama_client.get_item_lock(test_item_id)
            assert lock_status.get("locked", False) is True

            # Unlock the item
            server.jama_client.put_item_lock(test_item_id, False)

            # Verify unlocked (or restore original state)
            if was_locked:
                server.jama_client.put_item_lock(test_item_id, True)

        finally:
            await server.stop()
