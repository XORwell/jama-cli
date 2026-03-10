"""
Unit tests for the JamaMCPClient.
"""

import json
from unittest import mock

import pytest

from jama_mcp_server.api.client import JamaMCPClient
from jama_mcp_server.models import HealthCheckResponse, MCPResponse


@pytest.fixture
def mcp_client() -> JamaMCPClient:
    """Create a test MCP client."""
    return JamaMCPClient(url="http://localhost:8000")


class TestJamaMCPClient:
    """Tests for JamaMCPClient."""

    def test_init(self) -> None:
        """Test client initialization."""
        client = JamaMCPClient(url="http://example.com", api_key="test_key")

        assert client.url == "http://example.com"
        assert client.api_key == "test_key"
        assert client.session is None

    @pytest.mark.asyncio
    async def test_connect(self, mcp_client: JamaMCPClient) -> None:
        """Test client connection."""
        with mock.patch.object(mcp_client, "health_check") as mock_health:
            mock_health.return_value = HealthCheckResponse(
                status="healthy", jama_connected=True, jama_url="https://example.jama.com"
            )

            await mcp_client.connect()

            assert mcp_client.session is not None
            mock_health.assert_called_once()

        # Cleanup
        await mcp_client.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect(self, mcp_client: JamaMCPClient) -> None:
        """Test client disconnection."""
        # First connect
        with mock.patch.object(mcp_client, "health_check"):
            await mcp_client.connect()
            assert mcp_client.session is not None

        # Then disconnect
        await mcp_client.disconnect()
        assert mcp_client.session is None

    @pytest.mark.asyncio
    async def test_get_projects(self, mcp_client: JamaMCPClient) -> None:
        """Test get_projects convenience method."""
        with mock.patch.object(mcp_client, "invoke") as mock_invoke:
            mock_invoke.return_value = MCPResponse(
                response=json.dumps([{"id": 1}]), metadata={"status": "success"}
            )

            result = await mcp_client.get_projects()

            mock_invoke.assert_called_once_with("Get all projects", {"intent": "get_projects"})
            assert isinstance(result, MCPResponse)

    @pytest.mark.asyncio
    async def test_get_project(self, mcp_client: JamaMCPClient) -> None:
        """Test get_project convenience method."""
        with mock.patch.object(mcp_client, "invoke") as mock_invoke:
            mock_invoke.return_value = MCPResponse(
                response=json.dumps({"id": 123}), metadata={"status": "success"}
            )

            await mcp_client.get_project(123)

            mock_invoke.assert_called_once_with(
                "Get project with ID 123", {"intent": "get_project_by_id", "project_id": 123}
            )

    @pytest.mark.asyncio
    async def test_get_items(self, mcp_client: JamaMCPClient) -> None:
        """Test get_items convenience method."""
        with mock.patch.object(mcp_client, "invoke") as mock_invoke:
            mock_invoke.return_value = MCPResponse(
                response=json.dumps([{"id": 1}]), metadata={"status": "success"}
            )

            await mcp_client.get_items(project_id=10)

            mock_invoke.assert_called_once_with(
                "Get all items in project 10", {"intent": "get_items", "project_id": 10}
            )

    @pytest.mark.asyncio
    async def test_get_item(self, mcp_client: JamaMCPClient) -> None:
        """Test get_item convenience method."""
        with mock.patch.object(mcp_client, "invoke") as mock_invoke:
            mock_invoke.return_value = MCPResponse(
                response=json.dumps({"id": 456}), metadata={"status": "success"}
            )

            await mcp_client.get_item(456)

            mock_invoke.assert_called_once_with(
                "Get item with ID 456", {"intent": "get_item_by_id", "item_id": 456}
            )

    @pytest.mark.asyncio
    async def test_create_item(self, mcp_client: JamaMCPClient) -> None:
        """Test create_item convenience method."""
        with mock.patch.object(mcp_client, "invoke") as mock_invoke:
            mock_invoke.return_value = MCPResponse(
                response=json.dumps({"id": 789}), metadata={"status": "success"}
            )

            await mcp_client.create_item(
                project_id=10,
                item_type_id=45,
                child_item_type_id=45,
                location={"parent": {"item": 100}},
                fields={"name": "Test"},
            )

            # Check invoke was called with correct parameters
            mock_invoke.assert_called_once()
            call_args = mock_invoke.call_args
            params = call_args[0][1]  # Second positional argument
            assert params["intent"] == "create_item"
            assert params["project_id"] == 10
            assert params["item_type_id"] == 45

    @pytest.mark.asyncio
    async def test_update_item(self, mcp_client: JamaMCPClient) -> None:
        """Test update_item convenience method."""
        with mock.patch.object(mcp_client, "invoke") as mock_invoke:
            mock_invoke.return_value = MCPResponse(
                response=json.dumps({"id": 123}), metadata={"status": "success"}
            )

            await mcp_client.update_item(item_id=123, fields={"name": "Updated"})

            # Check invoke was called with correct parameters
            mock_invoke.assert_called_once()
            call_args = mock_invoke.call_args
            params = call_args[0][1]  # Second positional argument
            assert params["intent"] == "update_item"
            assert params["item_id"] == 123

    @pytest.mark.asyncio
    async def test_delete_item(self, mcp_client: JamaMCPClient) -> None:
        """Test delete_item convenience method."""
        with mock.patch.object(mcp_client, "invoke") as mock_invoke:
            mock_invoke.return_value = MCPResponse(response="null", metadata={"status": "success"})

            await mcp_client.delete_item(123)

            mock_invoke.assert_called_once_with(
                "Delete item with ID 123", {"intent": "delete_item", "item_id": 123}
            )

    @pytest.mark.asyncio
    async def test_patch_item(self, mcp_client: JamaMCPClient) -> None:
        """Test patch_item convenience method."""
        with mock.patch.object(mcp_client, "invoke") as mock_invoke:
            mock_invoke.return_value = MCPResponse(
                response=json.dumps({"id": 123}), metadata={"status": "success"}
            )

            patches = [{"op": "replace", "path": "/fields/name", "value": "New Name"}]
            await mcp_client.patch_item(123, patches)

            # Check invoke was called with correct parameters
            mock_invoke.assert_called_once()
            call_args = mock_invoke.call_args
            params = call_args[0][1]  # Second positional argument
            assert params["intent"] == "patch_item"
            assert params["item_id"] == 123
            assert params["patches"] == patches
