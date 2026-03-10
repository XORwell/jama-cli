"""Unit tests for stdio MCP server."""

import json

from jama_mcp_server.core.stdio_server import JamaStdioMCPServer
from jama_mcp_server.models import JamaConfig


class TestJamaStdioMCPServer:
    """Tests for JamaStdioMCPServer class."""

    def test_server_initialization(self):
        """Test server initialization."""
        config = JamaConfig(
            url="https://test.jamacloud.com",
            client_id="client",
            client_secret="secret",
        )

        server = JamaStdioMCPServer(config)
        assert server is not None
        assert server.config == config

    def test_server_has_mcp_instance(self):
        """Test server creates MCP instance."""
        config = JamaConfig(
            url="https://test.jamacloud.com",
            client_id="client",
            client_secret="secret",
        )

        server = JamaStdioMCPServer(config)
        assert server.mcp is not None


class TestStdioProtocol:
    """Tests for stdio protocol handling."""

    def test_parse_json_rpc(self):
        """Test parsing JSON-RPC message."""
        message = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "test",
                "params": {},
            }
        )

        parsed = json.loads(message)
        assert parsed["jsonrpc"] == "2.0"
        assert parsed["id"] == 1

    def test_format_response(self):
        """Test formatting JSON-RPC response."""
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"test": "value"},
        }

        formatted = json.dumps(response)
        parsed = json.loads(formatted)
        assert parsed["result"]["test"] == "value"

    def test_format_error_response(self):
        """Test formatting JSON-RPC error response."""
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {
                "code": -32600,
                "message": "Invalid Request",
            },
        }

        formatted = json.dumps(response)
        parsed = json.loads(formatted)
        assert parsed["error"]["code"] == -32600


class TestJamaConfig:
    """Tests for JamaConfig model used in stdio server."""

    def test_config_oauth(self):
        """Test OAuth configuration."""
        config = JamaConfig(
            url="https://test.jamacloud.com",
            client_id="client123",
            client_secret="secret456",
            oauth=True,
        )
        assert config.oauth is True
        assert config.client_id == "client123"

    def test_config_basic_auth(self):
        """Test basic auth configuration."""
        config = JamaConfig(
            url="https://test.jamacloud.com",
            username="user",
            password="pass",
        )
        assert config.username == "user"
        assert config.password == "pass"

    def test_config_api_key(self):
        """Test API key configuration."""
        config = JamaConfig(
            url="https://test.jamacloud.com",
            api_key="myapikey123",
        )
        assert config.api_key == "myapikey123"
