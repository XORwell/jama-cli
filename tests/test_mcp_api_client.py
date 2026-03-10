"""Comprehensive tests for MCP API client to achieve 100% coverage."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jama_mcp_server.api.client import JamaMCPClient
from jama_mcp_server.models import HealthCheckResponse, MCPResponse


class TestJamaMCPClientInit:
    """Tests for JamaMCPClient initialization."""

    def test_init_without_api_key(self):
        """Test initialization without API key."""
        client = JamaMCPClient("http://localhost:8000")
        assert client.url == "http://localhost:8000"
        assert client.api_key is None
        assert client.session is None

    def test_init_with_api_key(self):
        """Test initialization with API key."""
        client = JamaMCPClient("http://localhost:8000", api_key="secret123")
        assert client.url == "http://localhost:8000"
        assert client.api_key == "secret123"


class TestConnect:
    """Tests for connect method."""

    @pytest.mark.asyncio
    async def test_connect_creates_session(self):
        """Test that connect creates a session."""
        client = JamaMCPClient("http://localhost:8000")

        with patch.object(client, "health_check", new_callable=AsyncMock) as mock_health:
            mock_health.return_value = HealthCheckResponse(
                status="healthy", jama_connected=True, jama_url="http://jama"
            )
            await client.connect()
            assert client.session is not None
            mock_health.assert_called_once()
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_connect_reuses_session(self):
        """Test that connect reuses existing session."""
        client = JamaMCPClient("http://localhost:8000")
        mock_session = MagicMock()
        client.session = mock_session

        with patch.object(client, "health_check", new_callable=AsyncMock):
            await client.connect()
            # Session should not be replaced
            assert client.session == mock_session


class TestDisconnect:
    """Tests for disconnect method."""

    @pytest.mark.asyncio
    async def test_disconnect_closes_session(self):
        """Test that disconnect closes the session."""
        client = JamaMCPClient("http://localhost:8000")
        mock_session = AsyncMock()
        client.session = mock_session

        await client.disconnect()
        mock_session.close.assert_called_once()
        assert client.session is None

    @pytest.mark.asyncio
    async def test_disconnect_without_session(self):
        """Test disconnect when no session exists."""
        client = JamaMCPClient("http://localhost:8000")
        await client.disconnect()  # Should not raise
        assert client.session is None


class TestHealthCheck:
    """Tests for health_check method."""

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """Test successful health check."""
        client = JamaMCPClient("http://localhost:8000")

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "status": "healthy",
                "jama_connected": True,
                "jama_url": "http://jama.example.com",
            }
        )

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_context)
        client.session = mock_session

        result = await client.health_check()
        assert result.status == "healthy"
        assert result.jama_connected is True

    @pytest.mark.asyncio
    async def test_health_check_failure_status(self):
        """Test health check with error status."""
        client = JamaMCPClient("http://localhost:8000")

        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Server Error")

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_context)
        client.session = mock_session

        result = await client.health_check()
        assert result.status == "unhealthy"
        assert "500" in result.error

    @pytest.mark.asyncio
    async def test_health_check_exception(self):
        """Test health check with exception."""
        client = JamaMCPClient("http://localhost:8000")

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(side_effect=Exception("Connection refused"))
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_context)
        client.session = mock_session

        result = await client.health_check()
        assert result.status == "unhealthy"
        assert "Connection refused" in result.error

    @pytest.mark.asyncio
    async def test_health_check_connects_if_no_session(self):
        """Test health check connects if no session."""
        client = JamaMCPClient("http://localhost:8000")

        with patch.object(client, "connect", new_callable=AsyncMock) as mock_connect:
            # After connect, session will exist
            def set_session():
                mock_response = MagicMock()
                mock_response.status = 200
                mock_response.json = AsyncMock(
                    return_value={
                        "status": "healthy",
                        "jama_connected": True,
                        "jama_url": "http://jama",
                    }
                )

                mock_context = MagicMock()
                mock_context.__aenter__ = AsyncMock(return_value=mock_response)
                mock_context.__aexit__ = AsyncMock(return_value=None)

                mock_session = MagicMock()
                mock_session.get = MagicMock(return_value=mock_context)
                client.session = mock_session

            mock_connect.side_effect = set_session
            await client.health_check()
            mock_connect.assert_called_once()


class TestInvoke:
    """Tests for invoke method."""

    @pytest.mark.asyncio
    async def test_invoke_success(self):
        """Test successful invoke."""
        client = JamaMCPClient("http://localhost:8000")

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "response": "Success",
                "metadata": {"intent": "get_projects"},
            }
        )

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)
        client.session = mock_session

        result = await client.invoke("Get all projects")
        assert result.response == "Success"

    @pytest.mark.asyncio
    async def test_invoke_with_api_key(self):
        """Test invoke includes API key in headers."""
        client = JamaMCPClient("http://localhost:8000", api_key="secret123")

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"response": "OK", "metadata": {}})

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)
        client.session = mock_session

        await client.invoke("Test")

        # Check that headers include Authorization
        call_args = mock_session.post.call_args
        headers = call_args.kwargs.get("headers", {})
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer secret123"

    @pytest.mark.asyncio
    async def test_invoke_error_status(self):
        """Test invoke with error status."""
        client = JamaMCPClient("http://localhost:8000")

        mock_response = MagicMock()
        mock_response.status = 400
        mock_response.text = AsyncMock(return_value="Bad Request")

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)
        client.session = mock_session

        result = await client.invoke("Test")
        assert "Error" in result.response

    @pytest.mark.asyncio
    async def test_invoke_exception(self):
        """Test invoke with exception."""
        client = JamaMCPClient("http://localhost:8000")

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(side_effect=Exception("Network error"))
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)
        client.session = mock_session

        result = await client.invoke("Test")
        assert "Error" in result.response
        assert "Network error" in result.response

    @pytest.mark.asyncio
    async def test_invoke_connects_if_no_session(self):
        """Test invoke connects if no session."""
        client = JamaMCPClient("http://localhost:8000")

        with patch.object(client, "connect", new_callable=AsyncMock) as mock_connect:

            def set_session():
                mock_response = MagicMock()
                mock_response.status = 200
                mock_response.json = AsyncMock(return_value={"response": "OK", "metadata": {}})

                mock_context = MagicMock()
                mock_context.__aenter__ = AsyncMock(return_value=mock_response)
                mock_context.__aexit__ = AsyncMock(return_value=None)

                mock_session = MagicMock()
                mock_session.post = MagicMock(return_value=mock_context)
                client.session = mock_session

            mock_connect.side_effect = set_session
            await client.invoke("Test")
            mock_connect.assert_called_once()


class TestConvenienceMethods:
    """Tests for convenience methods."""

    @pytest.fixture
    def client_with_mock_invoke(self):
        """Create client with mocked invoke method."""
        client = JamaMCPClient("http://localhost:8000")
        client.invoke = AsyncMock(return_value=MCPResponse(response="OK", metadata={}))
        return client

    @pytest.mark.asyncio
    async def test_get_projects(self, client_with_mock_invoke):
        """Test get_projects convenience method."""
        await client_with_mock_invoke.get_projects()
        client_with_mock_invoke.invoke.assert_called_once()
        call_args = client_with_mock_invoke.invoke.call_args
        assert "projects" in call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_get_project(self, client_with_mock_invoke):
        """Test get_project convenience method."""
        await client_with_mock_invoke.get_project(123)
        client_with_mock_invoke.invoke.assert_called_once()
        call_args = client_with_mock_invoke.invoke.call_args
        # Second argument is a dict with parameters
        params = call_args[0][1]
        assert params["intent"] == "get_project_by_id"
        assert params["project_id"] == 123

    @pytest.mark.asyncio
    async def test_get_items(self, client_with_mock_invoke):
        """Test get_items convenience method."""
        await client_with_mock_invoke.get_items(123)
        client_with_mock_invoke.invoke.assert_called_once()
        call_args = client_with_mock_invoke.invoke.call_args
        params = call_args[0][1]
        assert params["intent"] == "get_items"
        assert params["project_id"] == 123

    @pytest.mark.asyncio
    async def test_get_item(self, client_with_mock_invoke):
        """Test get_item convenience method."""
        await client_with_mock_invoke.get_item(456)
        client_with_mock_invoke.invoke.assert_called_once()
        call_args = client_with_mock_invoke.invoke.call_args
        params = call_args[0][1]
        assert params["intent"] == "get_item_by_id"
        assert params["item_id"] == 456

    @pytest.mark.asyncio
    async def test_create_item(self, client_with_mock_invoke):
        """Test create_item convenience method."""
        await client_with_mock_invoke.create_item(
            project_id=1,
            item_type_id=33,
            child_item_type_id=34,
            location={"parent": {"item": 100}},
            fields={"name": "Test"},
        )
        client_with_mock_invoke.invoke.assert_called_once()
        call_args = client_with_mock_invoke.invoke.call_args
        params = call_args[0][1]
        assert params["intent"] == "create_item"
        assert params["project_id"] == 1
        assert params["fields"]["name"] == "Test"

    @pytest.mark.asyncio
    async def test_update_item(self, client_with_mock_invoke):
        """Test update_item convenience method."""
        await client_with_mock_invoke.update_item(456, {"name": "Updated"})
        client_with_mock_invoke.invoke.assert_called_once()
        call_args = client_with_mock_invoke.invoke.call_args
        params = call_args[0][1]
        assert params["intent"] == "update_item"
        assert params["item_id"] == 456

    @pytest.mark.asyncio
    async def test_patch_item(self, client_with_mock_invoke):
        """Test patch_item convenience method."""
        patches = [{"op": "replace", "path": "/fields/name", "value": "New"}]
        await client_with_mock_invoke.patch_item(456, patches)
        client_with_mock_invoke.invoke.assert_called_once()
        call_args = client_with_mock_invoke.invoke.call_args
        params = call_args[0][1]
        assert params["intent"] == "patch_item"
        assert params["patches"] == patches

    @pytest.mark.asyncio
    async def test_delete_item(self, client_with_mock_invoke):
        """Test delete_item convenience method."""
        await client_with_mock_invoke.delete_item(456)
        client_with_mock_invoke.invoke.assert_called_once()
        call_args = client_with_mock_invoke.invoke.call_args
        params = call_args[0][1]
        assert params["intent"] == "delete_item"
        assert params["item_id"] == 456
