"""
Integration tests for read operations.

These tests require a live Jama instance and valid credentials.
Run with: pytest tests/test_read_operations.py --integration
"""

import pytest

from jama_mcp_server.core.server import JamaMCPServer
from jama_mcp_server.models import JamaConfig


@pytest.mark.integration
@pytest.mark.asyncio
class TestReadOperations:
    """Test read operations against Jama API.

    These tests require:
    - JAMA_URL environment variable
    - Valid authentication credentials
    - TEST_PROJECT_ID and TEST_ITEM_ID for specific tests
    """

    async def test_get_projects(self, jama_config: JamaConfig) -> None:
        """Test getting all projects."""
        server = JamaMCPServer(config=jama_config)

        try:
            await server._initialize_jama_client()

            projects = server.jama_client.get_projects()
            assert isinstance(projects, list)
            if projects:
                assert "id" in projects[0]
                assert "projectKey" in projects[0]
        finally:
            await server.stop()

    async def test_get_project(self, jama_config: JamaConfig, test_project_id: int) -> None:
        """Test getting a specific project."""
        server = JamaMCPServer(config=jama_config)

        try:
            await server._initialize_jama_client()

            # Get all projects and find the one we need
            projects = server.jama_client.get_projects()
            project = next((p for p in projects if p["id"] == test_project_id), None)
            assert project is not None
            assert project["id"] == test_project_id
            assert "projectKey" in project
        finally:
            await server.stop()

    async def test_get_item(self, jama_config: JamaConfig, test_item_id: int) -> None:
        """Test getting a specific item."""
        server = JamaMCPServer(config=jama_config)

        try:
            await server._initialize_jama_client()

            item = server.jama_client.get_item(test_item_id)
            assert item["id"] == test_item_id
            assert "fields" in item
        finally:
            await server.stop()

    async def test_get_items(self, jama_config: JamaConfig, test_project_id: int) -> None:
        """Test getting items from a project."""
        server = JamaMCPServer(config=jama_config)

        try:
            await server._initialize_jama_client()

            items = server.jama_client.get_items(test_project_id)
            assert isinstance(items, list)
            if items:
                assert "id" in items[0]
                assert "fields" in items[0]
        finally:
            await server.stop()

    async def test_get_item_children(self, jama_config: JamaConfig, test_item_id: int) -> None:
        """Test getting children of an item."""
        server = JamaMCPServer(config=jama_config)

        try:
            await server._initialize_jama_client()

            children = server.jama_client.get_item_children(test_item_id)
            assert isinstance(children, list)
        finally:
            await server.stop()

    async def test_get_relationship_types(self, jama_config: JamaConfig) -> None:
        """Test getting relationship types."""
        server = JamaMCPServer(config=jama_config)

        try:
            await server._initialize_jama_client()

            rel_types = server.jama_client.get_relationship_types()
            assert isinstance(rel_types, list)
            if rel_types:
                assert "id" in rel_types[0]
        finally:
            await server.stop()

    async def test_get_relationships(self, jama_config: JamaConfig, test_item_id: int) -> None:
        """Test getting relationships for an item."""
        server = JamaMCPServer(config=jama_config)

        try:
            await server._initialize_jama_client()

            # Get downstream relationships for the item
            relationships = server.jama_client.get_items_downstream_relationships(test_item_id)
            assert isinstance(relationships, list)
        finally:
            await server.stop()

    async def test_get_tags(self, jama_config: JamaConfig, test_project_id: int) -> None:
        """Test getting tags for a project."""
        server = JamaMCPServer(config=jama_config)

        try:
            await server._initialize_jama_client()

            tags = server.jama_client.get_tags(test_project_id)
            assert isinstance(tags, list)
        finally:
            await server.stop()

    async def test_get_current_user(self, jama_config: JamaConfig) -> None:
        """Test getting current user information."""
        server = JamaMCPServer(config=jama_config)

        try:
            await server._initialize_jama_client()

            user = server.jama_client.get_current_user()
            assert isinstance(user, dict)
            assert "id" in user
        finally:
            await server.stop()

    async def test_get_pick_lists(self, jama_config: JamaConfig) -> None:
        """Test getting pick lists."""
        server = JamaMCPServer(config=jama_config)

        try:
            await server._initialize_jama_client()

            pick_lists = server.jama_client.get_pick_lists()
            assert isinstance(pick_lists, list)
        finally:
            await server.stop()
