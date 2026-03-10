"""Comprehensive tests for stdio MCP server to achieve 100% coverage."""

from unittest.mock import MagicMock, patch

import pytest

from jama_mcp_server.core.stdio_server import JamaStdioMCPServer
from jama_mcp_server.models import JamaConfig


class TestJamaStdioMCPServerInit:
    """Tests for JamaStdioMCPServer initialization."""

    def test_init_with_oauth(self):
        """Test initialization with OAuth config."""
        config = JamaConfig(
            url="https://test.jamacloud.com",
            client_id="client123",
            client_secret="secret456",
            oauth=True,
        )
        server = JamaStdioMCPServer(config)
        assert server.config == config
        assert server.jama_client is None
        assert server.mcp is not None

    def test_init_with_api_key(self):
        """Test initialization with API key."""
        config = JamaConfig(
            url="https://test.jamacloud.com",
            api_key="apikey123",
        )
        server = JamaStdioMCPServer(config)
        assert server.config == config

    def test_init_with_basic_auth(self):
        """Test initialization with username/password."""
        config = JamaConfig(
            url="https://test.jamacloud.com",
            username="user",
            password="pass",
        )
        server = JamaStdioMCPServer(config)
        assert server.config == config


class TestInitializeClient:
    """Tests for client initialization."""

    @pytest.mark.asyncio
    async def test_initialize_client_oauth(self):
        """Test initializing client with OAuth."""
        config = JamaConfig(
            url="https://test.jamacloud.com",
            client_id="client123",
            client_secret="secret456",
        )
        server = JamaStdioMCPServer(config)

        with patch("jama_mcp_server.core.stdio_server.JamaClient") as mock_client:
            await server.initialize_client()
            mock_client.assert_called_once_with(
                host_domain="https://test.jamacloud.com",
                credentials=("client123", "secret456"),
                oauth=True,
            )
            assert server.jama_client is not None

    @pytest.mark.asyncio
    async def test_initialize_client_api_key(self):
        """Test initializing client with API key."""
        config = JamaConfig(
            url="https://test.jamacloud.com",
            api_key="apikey123",
        )
        server = JamaStdioMCPServer(config)

        with patch("jama_mcp_server.core.stdio_server.JamaClient") as mock_client:
            await server.initialize_client()
            mock_client.assert_called_once_with(
                host_domain="https://test.jamacloud.com",
                credentials=("apikey123",),
            )

    @pytest.mark.asyncio
    async def test_initialize_client_basic_auth(self):
        """Test initializing client with basic auth."""
        config = JamaConfig(
            url="https://test.jamacloud.com",
            username="user",
            password="pass",
            oauth=False,
        )
        server = JamaStdioMCPServer(config)

        with patch("jama_mcp_server.core.stdio_server.JamaClient") as mock_client:
            await server.initialize_client()
            mock_client.assert_called_once_with(
                host_domain="https://test.jamacloud.com",
                credentials=("user", "pass"),
                oauth=False,
            )

    @pytest.mark.asyncio
    async def test_initialize_client_failure(self):
        """Test client initialization failure."""
        config = JamaConfig(
            url="https://test.jamacloud.com",
            client_id="client123",
            client_secret="secret456",
        )
        server = JamaStdioMCPServer(config)

        with patch("jama_mcp_server.core.stdio_server.JamaClient") as mock_client:
            mock_client.side_effect = Exception("Connection failed")
            with pytest.raises(Exception, match="Connection failed"):
                await server.initialize_client()


class TestExecuteTool:
    """Tests for tool execution."""

    @pytest.fixture
    def server_with_client(self):
        """Create server with mocked client."""
        config = JamaConfig(
            url="https://test.jamacloud.com",
            client_id="client123",
            client_secret="secret456",
        )
        server = JamaStdioMCPServer(config)
        server.jama_client = MagicMock()
        return server

    @pytest.mark.asyncio
    async def test_execute_tool_no_client(self):
        """Test executing tool without initialized client."""
        config = JamaConfig(url="https://test.jamacloud.com", api_key="key")
        server = JamaStdioMCPServer(config)

        with pytest.raises(RuntimeError, match="Jama client not initialized"):
            await server._execute_tool("get_projects", {})

    @pytest.mark.asyncio
    async def test_execute_get_projects(self, server_with_client):
        """Test get_projects tool."""
        server_with_client.jama_client.get_projects.return_value = [{"id": 1}]
        result = await server_with_client._execute_tool("get_projects", {})
        assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_execute_get_project(self, server_with_client):
        """Test get_project tool."""
        server_with_client.jama_client.get_project.return_value = {"id": 1, "name": "Test"}
        result = await server_with_client._execute_tool("get_project", {"project_id": 1})
        assert result["id"] == 1

    @pytest.mark.asyncio
    async def test_execute_get_item(self, server_with_client):
        """Test get_item tool."""
        server_with_client.jama_client.get_item.return_value = {"id": 100}
        result = await server_with_client._execute_tool("get_item", {"item_id": 100})
        assert result["id"] == 100

    @pytest.mark.asyncio
    async def test_execute_get_items(self, server_with_client):
        """Test get_items tool."""
        server_with_client.jama_client.get_items.return_value = [{"id": 1}, {"id": 2}]
        result = await server_with_client._execute_tool("get_items", {"project_id": 1})
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_execute_create_item(self, server_with_client):
        """Test create_item tool."""
        server_with_client.jama_client.post_item.return_value = 123
        result = await server_with_client._execute_tool(
            "create_item",
            {"project_id": 1, "item_type_id": 33, "fields": {"name": "Test"}},
        )
        assert result == 123

    @pytest.mark.asyncio
    async def test_execute_update_item(self, server_with_client):
        """Test update_item tool."""
        server_with_client.jama_client.patch_item.return_value = True
        result = await server_with_client._execute_tool(
            "update_item",
            {"item_id": 100, "fields": {"name": "Updated"}},
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_execute_delete_item(self, server_with_client):
        """Test delete_item tool."""
        server_with_client.jama_client.delete_item.return_value = True
        result = await server_with_client._execute_tool("delete_item", {"item_id": 100})
        assert result is True

    @pytest.mark.asyncio
    async def test_execute_get_item_children(self, server_with_client):
        """Test get_item_children tool."""
        server_with_client.jama_client.get_items_children.return_value = [{"id": 2}]
        result = await server_with_client._execute_tool("get_item_children", {"item_id": 1})
        assert result == [{"id": 2}]

    @pytest.mark.asyncio
    async def test_execute_get_relationships(self, server_with_client):
        """Test get_relationships tool."""
        server_with_client.jama_client.get_relationship_types.return_value = [{"id": 1}]
        result = await server_with_client._execute_tool("get_relationships", {})
        assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_execute_get_item_relationships(self, server_with_client):
        """Test get_item_relationships tool."""
        server_with_client.jama_client.get_relationships.return_value = [{"id": 1}]
        result = await server_with_client._execute_tool("get_item_relationships", {"item_id": 100})
        assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_execute_get_tags(self, server_with_client):
        """Test get_tags tool."""
        server_with_client.jama_client.get_tags.return_value = [{"id": 1, "name": "Tag1"}]
        result = await server_with_client._execute_tool("get_tags", {"project_id": 1})
        assert result[0]["name"] == "Tag1"

    @pytest.mark.asyncio
    async def test_execute_get_item_type(self, server_with_client):
        """Test get_item_type tool."""
        server_with_client.jama_client.get_item_type.return_value = {"id": 33, "display": "Requirement"}
        result = await server_with_client._execute_tool("get_item_type", {"item_type_id": 33})
        assert result["display"] == "Requirement"

    @pytest.mark.asyncio
    async def test_execute_get_pick_lists(self, server_with_client):
        """Test get_pick_lists tool."""
        server_with_client.jama_client.get_pick_lists.return_value = [{"id": 1}]
        result = await server_with_client._execute_tool("get_pick_lists", {"project_id": 1})
        assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_execute_get_baselines(self, server_with_client):
        """Test get_baselines tool."""
        server_with_client.jama_client.get_baselines.return_value = [{"id": 1}]
        result = await server_with_client._execute_tool("get_baselines", {"project_id": 1})
        assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_execute_get_baseline(self, server_with_client):
        """Test get_baseline tool."""
        server_with_client.jama_client.get_baseline.return_value = {"id": 1}
        result = await server_with_client._execute_tool("get_baseline", {"baseline_id": 1})
        assert result["id"] == 1

    @pytest.mark.asyncio
    async def test_execute_get_current_user(self, server_with_client):
        """Test get_current_user tool."""
        server_with_client.jama_client.get_current_user.return_value = {"id": 1, "username": "user"}
        result = await server_with_client._execute_tool("get_current_user", {})
        assert result["username"] == "user"

    @pytest.mark.asyncio
    async def test_execute_get_users(self, server_with_client):
        """Test get_users tool."""
        server_with_client.jama_client.get_users.return_value = [{"id": 1}]
        result = await server_with_client._execute_tool("get_users", {})
        assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_execute_get_item_versions(self, server_with_client):
        """Test get_item_versions tool."""
        server_with_client.jama_client.get_item_versions.return_value = [{"version": 1}]
        result = await server_with_client._execute_tool("get_item_versions", {"item_id": 100})
        assert result[0]["version"] == 1

    @pytest.mark.asyncio
    async def test_execute_get_item_tags(self, server_with_client):
        """Test get_item_tags tool."""
        server_with_client.jama_client.get_item_tags.return_value = [{"id": 1}]
        result = await server_with_client._execute_tool("get_item_tags", {"item_id": 100})
        assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_execute_post_item_tag(self, server_with_client):
        """Test post_item_tag tool."""
        server_with_client.jama_client.post_item_tag.return_value = True
        result = await server_with_client._execute_tool(
            "post_item_tag", {"item_id": 100, "tag_id": 1}
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_execute_get_item_workflow_transitions(self, server_with_client):
        """Test get_item_workflow_transitions tool."""
        server_with_client.jama_client.get_item_workflow_transitions.return_value = [{"id": 1}]
        result = await server_with_client._execute_tool(
            "get_item_workflow_transitions", {"item_id": 100}
        )
        assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_execute_get_attachment(self, server_with_client):
        """Test get_attachment tool."""
        server_with_client.jama_client.get_attachment.return_value = {"id": 1, "fileName": "test.txt"}
        result = await server_with_client._execute_tool("get_attachment", {"attachment_id": 1})
        assert result["fileName"] == "test.txt"

    @pytest.mark.asyncio
    async def test_execute_get_filter_results(self, server_with_client):
        """Test get_filter_results tool."""
        server_with_client.jama_client.get_filter_results.return_value = [{"id": 1}]
        result = await server_with_client._execute_tool("get_filter_results", {"filter_id": 1})
        assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, server_with_client):
        """Test executing unknown tool."""
        with pytest.raises(ValueError, match="Unknown tool"):
            await server_with_client._execute_tool("unknown_tool", {})


class TestToolRegistration:
    """Tests for tool registration and listing."""

    def test_tools_registered(self):
        """Test that tools are properly registered."""
        config = JamaConfig(url="https://test.jamacloud.com", api_key="key")
        server = JamaStdioMCPServer(config)
        # The mcp server should have handlers registered
        assert server.mcp is not None


class TestRunServer:
    """Tests for server run method."""

    @pytest.mark.asyncio
    async def test_initialize_client_sets_client(self):
        """Test that initialize_client sets jama_client."""
        config = JamaConfig(
            url="https://test.jamacloud.com",
            client_id="client123",
            client_secret="secret456",
        )
        server = JamaStdioMCPServer(config)
        assert server.jama_client is None

        with patch("jama_mcp_server.core.stdio_server.JamaClient") as mock_client:
            mock_client.return_value = MagicMock()
            await server.initialize_client()
            assert server.jama_client is not None
