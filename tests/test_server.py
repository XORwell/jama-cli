"""
Unit tests for the Jama MCP server.
"""

import json
from unittest import mock

import pytest

from jama_mcp_server.core.server import JamaMCPServer
from jama_mcp_server.models import JamaConfig, MCPRequest, MCPResponse


@pytest.fixture
def jama_config() -> JamaConfig:
    """Create a test Jama configuration."""
    return JamaConfig(
        url="https://example.jama.com",
        username="test_user",
        password="test_password",
    )


@pytest.fixture
def mcp_server(jama_config: JamaConfig) -> JamaMCPServer:
    """Create a test MCP server instance."""
    return JamaMCPServer(jama_config)


class TestHealthCheck:
    """Tests for health check functionality."""

    @pytest.mark.asyncio
    async def test_health_check_not_running(self, mcp_server: JamaMCPServer) -> None:
        """Test health check when server is not running."""
        result = await mcp_server.health_check()

        assert result.status == "unhealthy"
        assert result.jama_connected is False
        assert result.jama_url == "https://example.jama.com"

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_health_check_running(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test health check when server is running."""
        # Setup mock
        mock_instance = mock_jama_client.return_value
        mock_instance.get_projects.return_value = [{"id": 1}, {"id": 2}]

        server = JamaMCPServer(jama_config)
        server._running = True
        server.jama_client = mock_instance

        result = await server.health_check()

        assert result.status == "healthy"
        assert result.jama_connected is True
        assert result.jama_projects_count == 2


class TestRequestHandling:
    """Tests for MCP request handling."""

    @pytest.mark.asyncio
    async def test_handle_request_no_client(self, mcp_server: JamaMCPServer) -> None:
        """Test handling request when Jama client is not initialized."""
        request = MCPRequest(prompt="get projects", parameters={})

        response = await mcp_server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data["success"] is False
        assert response_data["error_code"] == "CLIENT_NOT_INITIALIZED"

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_projects(self, mock_jama_client: mock.Mock, jama_config: JamaConfig) -> None:
        """Test get_projects operation."""
        # Setup mock
        mock_instance = mock_jama_client.return_value
        mock_projects = [
            {"id": 1, "name": "Project 1", "projectKey": "P1"},
            {"id": 2, "name": "Project 2", "projectKey": "P2"},
        ]
        mock_instance.get_projects.return_value = mock_projects

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(prompt="get all projects", parameters={"intent": "get_projects"})

        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_projects
        assert response.metadata["status"] == "success"
        mock_instance.get_projects.assert_called_once()

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_item(self, mock_jama_client: mock.Mock, jama_config: JamaConfig) -> None:
        """Test get_item operation."""
        # Setup mock
        mock_instance = mock_jama_client.return_value
        mock_item = {"id": 123, "fields": {"name": "Test Item"}}
        mock_instance.get_item.return_value = mock_item

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="get item", parameters={"intent": "get_item_by_id", "item_id": 123}
        )

        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_item
        mock_instance.get_item.assert_called_once_with(123)

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_items(self, mock_jama_client: mock.Mock, jama_config: JamaConfig) -> None:
        """Test get_items operation."""
        # Setup mock
        mock_instance = mock_jama_client.return_value
        mock_items = [
            {"id": 1, "fields": {"name": "Item 1"}},
            {"id": 2, "fields": {"name": "Item 2"}},
        ]
        mock_instance.get_items.return_value = mock_items

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="get items", parameters={"intent": "get_items", "project_id": 10}
        )

        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_items
        mock_instance.get_items.assert_called_once_with(10)

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_create_item(self, mock_jama_client: mock.Mock, jama_config: JamaConfig) -> None:
        """Test create_item operation."""
        # Setup mock
        mock_instance = mock_jama_client.return_value
        mock_created = {"id": 456, "fields": {"name": "New Item"}}
        mock_instance.post_item.return_value = mock_created

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="create item",
            parameters={
                "intent": "create_item",
                "project_id": 10,
                "item_type_id": 45,
                "child_item_type_id": 45,
                "location": {"parent": {"item": 100}},
                "fields": {"name": "New Item", "description": "Test description"},
            },
        )

        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_created
        mock_instance.post_item.assert_called_once()

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_update_item(self, mock_jama_client: mock.Mock, jama_config: JamaConfig) -> None:
        """Test update_item operation."""
        # Setup mock
        mock_instance = mock_jama_client.return_value
        mock_updated = {"id": 123, "fields": {"name": "Updated Item"}}
        mock_instance.patch_item.return_value = mock_updated

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="update item",
            parameters={
                "intent": "update_item",
                "item_id": 123,
                "fields": {"name": "Updated Item"},
            },
        )

        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_updated
        mock_instance.patch_item.assert_called_once()

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_delete_item(self, mock_jama_client: mock.Mock, jama_config: JamaConfig) -> None:
        """Test delete_item operation."""
        # Setup mock
        mock_instance = mock_jama_client.return_value
        mock_instance.delete_item.return_value = None

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="delete item", parameters={"intent": "delete_item", "item_id": 123}
        )

        await server.handle_request(request)

        mock_instance.delete_item.assert_called_once_with(123)

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_unsupported_operation(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test handling of unsupported operations."""
        mock_instance = mock_jama_client.return_value

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="unsupported operation", parameters={"intent": "unsupported_operation"}
        )

        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data["success"] is False
        assert "Unsupported operation" in response_data["error"]

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_validation_error(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test validation error handling."""
        mock_instance = mock_jama_client.return_value

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        # Missing required project_id
        request = MCPRequest(prompt="get items", parameters={"intent": "get_items"})

        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data["success"] is False
        assert response_data["error_code"] == "VALIDATION_ERROR"


class TestBatchOperations:
    """Tests for batch operations."""

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_batch_request(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test batch request handling."""
        # Setup mock
        mock_instance = mock_jama_client.return_value
        mock_instance.get_projects.return_value = [{"id": 1}]
        mock_instance.get_item.return_value = {"id": 123}

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        requests = [
            MCPRequest(prompt="get projects", parameters={"intent": "get_projects"}),
            MCPRequest(prompt="get item", parameters={"intent": "get_item_by_id", "item_id": 123}),
        ]

        responses = await server.handle_batch_request(requests)

        assert len(responses) == 2
        assert all(isinstance(r, MCPResponse) for r in responses)


class TestPromptParsing:
    """Tests for prompt parsing."""

    def test_parse_prompt_with_intent(self, mcp_server: JamaMCPServer) -> None:
        """Test prompt parsing when intent is explicitly provided."""
        intent, params = mcp_server._parse_prompt("any prompt", {"intent": "get_projects"})

        assert intent == "get_projects"

    def test_parse_prompt_get_projects(self, mcp_server: JamaMCPServer) -> None:
        """Test prompt parsing for get projects."""
        intent, params = mcp_server._parse_prompt("get all projects", {})

        assert intent == "get_projects"

    def test_parse_prompt_get_items(self, mcp_server: JamaMCPServer) -> None:
        """Test prompt parsing for get items."""
        intent, params = mcp_server._parse_prompt("get items from project 123", {"project_id": 123})

        assert intent == "get_items"
        assert params["project_id"] == 123

    def test_parse_prompt_create_item(self, mcp_server: JamaMCPServer) -> None:
        """Test prompt parsing for create item."""
        intent, params = mcp_server._parse_prompt("create new item", {})

        assert intent == "create_item"

    def test_parse_prompt_update_item(self, mcp_server: JamaMCPServer) -> None:
        """Test prompt parsing for update item."""
        intent, params = mcp_server._parse_prompt("update item 123", {"item_id": 123})

        assert intent == "update_item"

    def test_parse_prompt_delete_item(self, mcp_server: JamaMCPServer) -> None:
        """Test prompt parsing for delete item."""
        intent, params = mcp_server._parse_prompt("delete item 123", {"item_id": 123})

        assert intent == "delete_item"

    def test_parse_prompt_extract_project_id(self, mcp_server: JamaMCPServer) -> None:
        """Test extraction of project ID from prompt."""
        intent, params = mcp_server._parse_prompt("get items from project: 456", {})

        assert params["project_id"] == 456

    def test_parse_prompt_extract_item_id(self, mcp_server: JamaMCPServer) -> None:
        """Test extraction of item ID from prompt."""
        intent, params = mcp_server._parse_prompt("get item id: 789", {})

        assert params["item_id"] == 789


class TestReadOperations:
    """Tests for all MCP read operations."""

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_item_children(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test get_item_children operation."""
        mock_instance = mock_jama_client.return_value
        mock_children = [{"id": 1}, {"id": 2}]
        mock_instance.get_item_children.return_value = mock_children

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="get children", parameters={"intent": "get_item_children", "item_id": 100}
        )
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_children
        mock_instance.get_item_children.assert_called_once_with(100)

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_item_types(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test get_item_types operation."""
        mock_instance = mock_jama_client.return_value
        mock_types = [{"id": 1, "name": "Requirement"}]
        mock_instance.get_item_types.return_value = mock_types

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="get types", parameters={"intent": "get_item_types", "project_id": 10}
        )
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_types

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_item_type(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test get_item_type operation."""
        mock_instance = mock_jama_client.return_value
        mock_type = {"id": 33, "name": "Text"}
        mock_instance.get_item_type.return_value = mock_type

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="get type", parameters={"intent": "get_item_type", "item_type_id": 33}
        )
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_type

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_relationships(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test get_relationships operation."""
        mock_instance = mock_jama_client.return_value
        mock_rels = [{"id": 1, "fromItem": 10, "toItem": 20}]
        mock_instance.get_relationships.return_value = mock_rels

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="get relationships", parameters={"intent": "get_relationships", "project_id": 10}
        )
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_rels

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_relationship(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test get_relationship operation."""
        mock_instance = mock_jama_client.return_value
        mock_rel = {"id": 1, "fromItem": 10, "toItem": 20}
        mock_instance.get_relationship.return_value = mock_rel

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="get relationship",
            parameters={"intent": "get_relationship", "relationship_id": 1},
        )
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_rel

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_item_upstream_relationships(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test get_item_upstream_relationships operation."""
        mock_instance = mock_jama_client.return_value
        mock_rels = [{"id": 1}]
        mock_instance.get_items_upstream_relationships.return_value = mock_rels

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="get upstream",
            parameters={"intent": "get_item_upstream_relationships", "item_id": 100},
        )
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_rels

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_item_downstream_relationships(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test get_item_downstream_relationships operation."""
        mock_instance = mock_jama_client.return_value
        mock_rels = [{"id": 2}]
        mock_instance.get_items_downstream_relationships.return_value = mock_rels

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="get downstream",
            parameters={"intent": "get_item_downstream_relationships", "item_id": 100},
        )
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_rels

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_pick_lists(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test get_pick_lists operation."""
        mock_instance = mock_jama_client.return_value
        mock_lists = [{"id": 1, "name": "Status"}]
        mock_instance.get_pick_lists.return_value = mock_lists

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(prompt="get pick lists", parameters={"intent": "get_pick_lists"})
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_lists

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_pick_list(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test get_pick_list operation."""
        mock_instance = mock_jama_client.return_value
        mock_list = {"id": 1, "name": "Status"}
        mock_instance.get_pick_list.return_value = mock_list

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="get pick list", parameters={"intent": "get_pick_list", "pick_list_id": 1}
        )
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_list

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_pick_list_options(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test get_pick_list_options operation."""
        mock_instance = mock_jama_client.return_value
        mock_options = [{"id": 1, "name": "Open"}]
        mock_instance.get_pick_list_options.return_value = mock_options

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="get options", parameters={"intent": "get_pick_list_options", "pick_list_id": 1}
        )
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_options

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_tags(self, mock_jama_client: mock.Mock, jama_config: JamaConfig) -> None:
        """Test get_tags operation."""
        mock_instance = mock_jama_client.return_value
        mock_tags = [{"id": 1, "name": "Important"}]
        mock_instance.get_tags.return_value = mock_tags

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(prompt="get tags", parameters={"intent": "get_tags", "project_id": 10})
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_tags

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_tagged_items(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test get_tagged_items operation."""
        mock_instance = mock_jama_client.return_value
        mock_items = [{"id": 100}]
        mock_instance.get_tagged_items.return_value = mock_items

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="get tagged items", parameters={"intent": "get_tagged_items", "tag_id": 1}
        )
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_items

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_users(self, mock_jama_client: mock.Mock, jama_config: JamaConfig) -> None:
        """Test get_users operation."""
        mock_instance = mock_jama_client.return_value
        mock_users = [{"id": 1, "username": "admin"}]
        mock_instance.get_users.return_value = mock_users

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(prompt="get users", parameters={"intent": "get_users"})
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_users

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_current_user(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test get_current_user operation."""
        mock_instance = mock_jama_client.return_value
        mock_user = {"id": 1, "username": "current"}
        mock_instance.get_current_user.return_value = mock_user

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(prompt="get current user", parameters={"intent": "get_current_user"})
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_user

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_baselines(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test get_baselines operation."""
        mock_instance = mock_jama_client.return_value
        mock_baselines = [{"id": 1, "name": "Baseline 1"}]
        mock_instance.get_baselines.return_value = mock_baselines

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="get baselines", parameters={"intent": "get_baselines", "project_id": 10}
        )
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_baselines

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_item_versions(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test get_item_versions operation."""
        mock_instance = mock_jama_client.return_value
        mock_versions = [{"id": 1, "version": 1}]
        mock_instance.get_item_versions.return_value = mock_versions

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="get versions", parameters={"intent": "get_item_versions", "item_id": 100}
        )
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_versions

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_item_lock(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test get_item_lock operation."""
        mock_instance = mock_jama_client.return_value
        mock_lock = {"locked": True, "lockedBy": 1}
        mock_instance.get_item_lock.return_value = mock_lock

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="get lock", parameters={"intent": "get_item_lock", "item_id": 100}
        )
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_lock

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_test_cycle(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test get_test_cycle operation."""
        mock_instance = mock_jama_client.return_value
        mock_cycle = {"id": 1, "name": "Cycle 1"}
        mock_instance.get_test_cycle.return_value = mock_cycle

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="get test cycle", parameters={"intent": "get_test_cycle", "test_cycle_id": 1}
        )
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_cycle

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_test_runs(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test get_test_runs operation."""
        mock_instance = mock_jama_client.return_value
        mock_runs = [{"id": 1, "status": "PASSED"}]
        # Server uses get_testruns (no underscore)
        mock_instance.get_testruns.return_value = mock_runs

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="get test runs", parameters={"intent": "get_test_runs", "test_cycle_id": 1}
        )
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_runs
        mock_instance.get_testruns.assert_called_once_with(1)

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_filter_results(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test get_filter_results operation."""
        mock_instance = mock_jama_client.return_value
        mock_results = [{"id": 100}]
        mock_instance.get_filter_results.return_value = mock_results

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="get filter results", parameters={"intent": "get_filter_results", "filter_id": 1}
        )
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_results

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_item_tags(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test get_item_tags operation."""
        mock_instance = mock_jama_client.return_value
        mock_tags = [{"id": 1, "name": "Important"}]
        mock_instance.get_item_tags.return_value = mock_tags

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="get item tags", parameters={"intent": "get_item_tags", "item_id": 100}
        )
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_tags


class TestWriteOperations:
    """Tests for all MCP write operations."""

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_patch_item(self, mock_jama_client: mock.Mock, jama_config: JamaConfig) -> None:
        """Test patch_item operation."""
        mock_instance = mock_jama_client.return_value
        mock_instance.patch_item.return_value = None

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="patch item",
            parameters={
                "intent": "patch_item",
                "item_id": 123,
                "patches": [{"op": "replace", "path": "/fields/name", "value": "New Name"}],
            },
        )
        await server.handle_request(request)

        mock_instance.patch_item.assert_called_once()

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_put_item_lock(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test put_item_lock operation."""
        mock_instance = mock_jama_client.return_value
        mock_instance.put_item_lock.return_value = None

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="lock item",
            parameters={"intent": "put_item_lock", "item_id": 123, "locked": True},
        )
        await server.handle_request(request)

        mock_instance.put_item_lock.assert_called_once_with(123, True)

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_get_attachment(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test get_attachment operation."""
        mock_instance = mock_jama_client.return_value
        mock_attachment = {"id": 1, "fileName": "test.pdf"}
        mock_instance.get_attachment.return_value = mock_attachment

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="get attachment", parameters={"intent": "get_attachment", "attachment_id": 1}
        )
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == mock_attachment

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_post_item_attachment(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test post_item_attachment operation."""
        mock_instance = mock_jama_client.return_value
        mock_instance.post_item_attachment.return_value = 456

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="upload attachment",
            parameters={
                "intent": "post_item_attachment",
                "item_id": 123,
                "file_path": "/path/to/file.pdf",
            },
        )
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data == 456

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_post_item_tag(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test post_item_tag operation."""
        mock_instance = mock_jama_client.return_value
        mock_instance.post_item_tag.return_value = None

        server = JamaMCPServer(jama_config)
        server.jama_client = mock_instance

        request = MCPRequest(
            prompt="add tag",
            parameters={"intent": "post_item_tag", "item_id": 123, "tag_id": 1},
        )
        await server.handle_request(request)

        mock_instance.post_item_tag.assert_called_once_with(123, 1)


class TestErrorClassification:
    """Tests for error classification."""

    def test_classify_authentication_error(self, mcp_server: JamaMCPServer) -> None:
        """Test classification of authentication errors."""
        error = Exception("401 Unauthorized")
        assert mcp_server._classify_error(error) == "AUTHENTICATION_ERROR"

    def test_classify_permission_error(self, mcp_server: JamaMCPServer) -> None:
        """Test classification of permission errors."""
        error = Exception("403 Forbidden")
        assert mcp_server._classify_error(error) == "PERMISSION_ERROR"

    def test_classify_not_found_error(self, mcp_server: JamaMCPServer) -> None:
        """Test classification of not found errors."""
        error = Exception("404 Not Found")
        assert mcp_server._classify_error(error) == "NOT_FOUND"

    def test_classify_server_error(self, mcp_server: JamaMCPServer) -> None:
        """Test classification of server errors."""
        error = Exception("500 Internal Server Error")
        assert mcp_server._classify_error(error) == "SERVER_ERROR"

    def test_classify_timeout_error(self, mcp_server: JamaMCPServer) -> None:
        """Test classification of timeout errors."""
        error = Exception("Connection timeout")
        assert mcp_server._classify_error(error) == "TIMEOUT_ERROR"

    def test_classify_connection_error(self, mcp_server: JamaMCPServer) -> None:
        """Test classification of connection errors."""
        error = Exception("Connection refused")
        assert mcp_server._classify_error(error) == "CONNECTION_ERROR"

    def test_classify_unknown_error(self, mcp_server: JamaMCPServer) -> None:
        """Test classification of unknown errors."""
        error = Exception("Some random error")
        assert mcp_server._classify_error(error) == "UNKNOWN_ERROR"


class TestValidationErrors:
    """Tests for validation error handling."""

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_missing_item_id(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test validation error when item_id is missing."""
        server = JamaMCPServer(jama_config)
        server.jama_client = mock_jama_client.return_value

        request = MCPRequest(prompt="get item", parameters={"intent": "get_item_by_id"})
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data["success"] is False
        assert "Item ID is required" in response_data["error"]

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_missing_project_id(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test validation error when project_id is missing."""
        server = JamaMCPServer(jama_config)
        server.jama_client = mock_jama_client.return_value

        request = MCPRequest(prompt="get items", parameters={"intent": "get_items"})
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data["success"] is False
        assert "Project ID is required" in response_data["error"]

    @pytest.mark.asyncio
    @mock.patch("jama_mcp_server.core.server.JamaClient")
    async def test_missing_create_item_fields(
        self, mock_jama_client: mock.Mock, jama_config: JamaConfig
    ) -> None:
        """Test validation error when create_item fields are missing."""
        server = JamaMCPServer(jama_config)
        server.jama_client = mock_jama_client.return_value

        request = MCPRequest(
            prompt="create item", parameters={"intent": "create_item", "project_id": 10}
        )
        response = await server.handle_request(request)

        response_data = json.loads(response.response)
        assert response_data["success"] is False
        assert "Required field" in response_data["error"]
