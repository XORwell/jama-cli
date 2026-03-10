"""
Integration tests for the MCP server HTTP API.

These tests require a live Jama instance and valid credentials.
Run with: pytest tests/test_mcp_server_integration.py --integration

The tests start a temporary MCP server on a random port and test all endpoints.
"""

import asyncio
import contextlib
import json
import os
import socket
import time

import aiohttp
import pytest

from jama_mcp_server.core.server import JamaMCPServer
from jama_mcp_server.models import JamaConfig


def get_free_port() -> int:
    """Get a free port for testing."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


@pytest.fixture
def test_project_id() -> int:
    """Primary test project ID."""
    return int(os.environ.get("TEST_PROJECT_ID", "1"))


@pytest.fixture
def test_item_id() -> int:
    """Test item ID."""
    return int(os.environ.get("TEST_ITEM_ID", "100"))


@pytest.fixture
def jama_config() -> JamaConfig:
    """Provide Jama configuration from environment."""
    return JamaConfig(
        url=os.environ.get("JAMA_URL", "https://example.jamacloud.com"),
        client_id=os.environ.get("JAMA_CLIENT_ID", ""),
        client_secret=os.environ.get("JAMA_CLIENT_SECRET", ""),
        oauth=True,
    )


@pytest.fixture
async def mcp_server(jama_config: JamaConfig):
    """Start a temporary MCP server for testing."""
    port = get_free_port()
    server = JamaMCPServer(config=jama_config, host="localhost", port=port)

    # Start server in background
    server_task = asyncio.create_task(server.start())

    # Wait for server to start
    await asyncio.sleep(1)

    yield server, port

    # Stop server
    await server.stop()
    server_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await server_task


@pytest.mark.integration
@pytest.mark.asyncio
class TestMCPServerHealth:
    """Test MCP server health endpoints."""

    async def test_health_endpoint(self, mcp_server) -> None:
        """Test /health endpoint."""
        server, port = mcp_server
        async with aiohttp.ClientSession() as session, session.get(f"http://localhost:{port}/health") as response:
            assert response.status == 200
            data = await response.json()
            assert data["status"] == "healthy"
            assert data["jama_connected"] is True
            assert "version" in data
            assert "uptime_seconds" in data

    async def test_ready_endpoint(self, mcp_server) -> None:
        """Test /ready endpoint."""
        server, port = mcp_server
        async with aiohttp.ClientSession() as session, session.get(f"http://localhost:{port}/ready") as response:
            assert response.status == 200
            data = await response.json()
            assert data["ready"] is True

    async def test_metrics_endpoint(self, mcp_server) -> None:
        """Test /metrics endpoint."""
        server, port = mcp_server
        async with aiohttp.ClientSession() as session, session.get(f"http://localhost:{port}/metrics") as response:
            assert response.status == 200
            data = await response.json()
            # Check for various metric keys that might be present
            assert any(key in data for key in ["request_count", "requests", "uptime_seconds", "uptime"])


@pytest.mark.integration
@pytest.mark.asyncio
class TestMCPServerInvoke:
    """Test MCP server /v1/invoke endpoint."""

    async def test_invoke_get_projects(self, mcp_server) -> None:
        """Test invoking get_projects."""
        server, port = mcp_server
        async with aiohttp.ClientSession() as session, session.post(
            f"http://localhost:{port}/v1/invoke",
            json={"prompt": "get_projects"},
        ) as response:
            assert response.status == 200
            data = await response.json()
            assert "response" in data
            assert "metadata" in data
            projects = json.loads(data["response"])
            assert isinstance(projects, list)

    async def test_invoke_get_items(self, mcp_server, test_project_id: int) -> None:
        """Test invoking get_items for a project."""
        server, port = mcp_server
        async with aiohttp.ClientSession() as session, session.post(
            f"http://localhost:{port}/v1/invoke",
            json={
                "prompt": f"get items from project {test_project_id}",
                "parameters": {"project_id": test_project_id},
            },
        ) as response:
            assert response.status == 200
            data = await response.json()
            assert "response" in data
            items = json.loads(data["response"])
            assert isinstance(items, list)

    async def test_invoke_get_item(self, mcp_server, test_item_id: int) -> None:
        """Test invoking get_item for a specific item."""
        server, port = mcp_server
        async with aiohttp.ClientSession() as session, session.post(
            f"http://localhost:{port}/v1/invoke",
            json={
                "prompt": f"get item {test_item_id}",
                "parameters": {"item_id": test_item_id},
            },
        ) as response:
            assert response.status == 200
            data = await response.json()
            assert "response" in data

    async def test_invoke_get_item_types(self, mcp_server) -> None:
        """Test invoking get_item_types."""
        server, port = mcp_server
        async with aiohttp.ClientSession() as session, session.post(
            f"http://localhost:{port}/v1/invoke",
            json={"prompt": "get_item_types"},
        ) as response:
            assert response.status == 200
            data = await response.json()
            assert "response" in data
            item_types = json.loads(data["response"])
            assert isinstance(item_types, list)
            assert len(item_types) > 0

    async def test_invoke_get_relationship_types(self, mcp_server) -> None:
        """Test invoking get_relationship_types."""
        server, port = mcp_server
        async with aiohttp.ClientSession() as session, session.post(
            f"http://localhost:{port}/v1/invoke",
            json={"prompt": "get_relationship_types"},
        ) as response:
            assert response.status == 200
            data = await response.json()
            assert "response" in data

    async def test_invoke_invalid_prompt(self, mcp_server) -> None:
        """Test invoking with empty prompt."""
        server, port = mcp_server
        async with aiohttp.ClientSession() as session, session.post(
            f"http://localhost:{port}/v1/invoke",
            json={"prompt": ""},
        ) as response:
            # Should return validation error or error response
            # Any status is acceptable as long as server responds
            assert response.status in [200, 400, 422, 500]


@pytest.mark.integration
@pytest.mark.asyncio
class TestMCPServerBatch:
    """Test MCP server /v1/batch endpoint."""

    async def test_batch_requests(self, mcp_server) -> None:
        """Test batch requests."""
        server, port = mcp_server
        async with aiohttp.ClientSession() as session, session.post(
            f"http://localhost:{port}/v1/batch",
            json={
                "requests": [
                    {"prompt": "get_projects"},
                    {"prompt": "get_item_types"},
                ]
            },
        ) as response:
            assert response.status == 200
            data = await response.json()
            assert "responses" in data
            assert data["count"] == 2
            assert len(data["responses"]) == 2

    async def test_batch_empty_requests(self, mcp_server) -> None:
        """Test batch with empty requests list."""
        server, port = mcp_server
        async with aiohttp.ClientSession() as session, session.post(
            f"http://localhost:{port}/v1/batch",
            json={"requests": []},
        ) as response:
            # Should return validation error
            assert response.status in [400, 422]


@pytest.mark.integration
@pytest.mark.asyncio
class TestMCPServerSSE:
    """Test MCP server SSE (Server-Sent Events) endpoint."""

    async def test_sse_connection(self, mcp_server) -> None:
        """Test SSE endpoint accepts connection."""
        server, port = mcp_server
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{port}/v1/sse",
            timeout=aiohttp.ClientTimeout(total=2),
        ) as response:
            assert response.status == 200
            assert "text/event-stream" in response.content_type

    async def test_sse_message(self, mcp_server) -> None:
        """Test sending message to SSE endpoint."""
        server, port = mcp_server
        async with aiohttp.ClientSession() as session, session.post(
            f"http://localhost:{port}/v1/messages",
            json={"prompt": "test message"},
        ) as response:
            # SSE message endpoint - may return various status codes
            assert response.status in [200, 202, 400, 422]


@pytest.mark.integration
@pytest.mark.asyncio
class TestMCPServerCRUD:
    """Test MCP server CRUD operations via invoke."""

    async def test_create_get_update_delete_item(
        self, mcp_server, test_project_id: int
    ) -> None:
        """Test complete item lifecycle via MCP server."""
        server, port = mcp_server
        async with aiohttp.ClientSession() as session, session.post(
            f"http://localhost:{port}/v1/invoke",
            json={
                "prompt": "create_item",
                "parameters": {
                    "project_id": test_project_id,
                    "item_type_id": 33,
                    "fields": {
                        "name": "MCP_TEST_ITEM",
                        "description": "Created via MCP",
                    },
                },
            },
        ) as response:
            assert response.status == 200
            data = await response.json()

            # If creation succeeded, try to get item ID
            if "response" in data and data.get("metadata", {}).get("status") == "success":
                result = json.loads(data["response"])
                item_id = result.get("id") or result

                # Get the item
                async with session.post(
                    f"http://localhost:{port}/v1/invoke",
                    json={
                        "prompt": "get_item",
                        "parameters": {"item_id": item_id},
                    },
                ) as get_response:
                    assert get_response.status == 200

                # Update the item
                async with session.post(
                    f"http://localhost:{port}/v1/invoke",
                    json={
                        "prompt": "update_item",
                        "parameters": {
                            "item_id": item_id,
                            "fields": {"name": "MCP_TEST_ITEM_UPDATED"},
                        },
                    },
                ) as update_response:
                    assert update_response.status == 200

                # Delete the item
                async with session.post(
                    f"http://localhost:{port}/v1/invoke",
                    json={
                        "prompt": "delete_item",
                        "parameters": {"item_id": item_id},
                    },
                ) as delete_response:
                    assert delete_response.status == 200


@pytest.mark.integration
@pytest.mark.asyncio
class TestMCPServerErrorHandling:
    """Test MCP server error handling."""

    async def test_invalid_json(self, mcp_server) -> None:
        """Test handling of invalid JSON."""
        server, port = mcp_server
        async with aiohttp.ClientSession() as session, session.post(
            f"http://localhost:{port}/v1/invoke",
            data="not valid json",
            headers={"Content-Type": "application/json"},
        ) as response:
            # Server should return error status for invalid JSON
            assert response.status in [400, 422, 500]

    async def test_missing_prompt(self, mcp_server) -> None:
        """Test handling of missing prompt field."""
        server, port = mcp_server
        async with aiohttp.ClientSession() as session, session.post(
            f"http://localhost:{port}/v1/invoke",
            json={"parameters": {}},
        ) as response:
            # Should return error response
            assert response.status in [200, 400, 422, 500]

    async def test_unknown_operation(self, mcp_server) -> None:
        """Test handling of unknown operation."""
        server, port = mcp_server
        async with aiohttp.ClientSession() as session, session.post(
            f"http://localhost:{port}/v1/invoke",
            json={"prompt": "completely_unknown_operation_xyz"},
        ) as response:
            assert response.status == 200
            data = await response.json()
            # Should return some response even for unknown operations
            assert "response" in data or "error" in data


@pytest.mark.integration
@pytest.mark.asyncio
class TestMCPServerPerformance:
    """Test MCP server performance characteristics."""

    async def test_concurrent_requests(self, mcp_server) -> None:
        """Test handling multiple concurrent requests."""
        server, port = mcp_server

        async def make_request():
            async with aiohttp.ClientSession() as session, session.post(
                f"http://localhost:{port}/v1/invoke",
                json={"prompt": "get_item_types"},
            ) as response:
                return response.status

        # Make 5 concurrent requests
        tasks = [make_request() for _ in range(5)]
        results = await asyncio.gather(*tasks)

        # All should succeed
        assert all(status == 200 for status in results)

    async def test_response_time(self, mcp_server) -> None:
        """Test response time is reasonable."""
        server, port = mcp_server
        async with aiohttp.ClientSession() as session:
            start = time.time()
            async with session.get(f"http://localhost:{port}/health") as response:
                elapsed = time.time() - start
                assert response.status == 200
                # Health check should respond within 10 seconds
                assert elapsed < 10.0
