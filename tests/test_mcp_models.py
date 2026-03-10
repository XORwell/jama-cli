"""Comprehensive tests for MCP models to achieve 100% coverage."""

import pytest
from pydantic import ValidationError

from jama_mcp_server.models import (
    BatchRequest,
    BatchResponse,
    ErrorResponse,
    HealthCheckResponse,
    JamaConfig,
    MCPRequest,
    MCPResponse,
    MultiServerConfig,
)


class TestJamaConfig:
    """Tests for JamaConfig model."""

    def test_create_with_oauth(self):
        """Test creating config with OAuth credentials."""
        config = JamaConfig(
            url="https://test.jamacloud.com",
            client_id="client123",
            client_secret="secret456",
            oauth=True,
        )
        assert config.url == "https://test.jamacloud.com"
        assert config.client_id == "client123"
        assert config.oauth is True

    def test_create_with_api_key(self):
        """Test creating config with API key."""
        config = JamaConfig(
            url="https://test.jamacloud.com",
            api_key="apikey123",
        )
        assert config.api_key == "apikey123"

    def test_create_with_basic_auth(self):
        """Test creating config with username/password."""
        config = JamaConfig(
            url="https://test.jamacloud.com",
            username="user",
            password="pass",
        )
        assert config.username == "user"
        assert config.password == "pass"

    def test_url_normalization_adds_https(self):
        """Test URL normalization adds https."""
        config = JamaConfig(url="test.jamacloud.com", api_key="key")
        assert config.url == "https://test.jamacloud.com"

    def test_url_normalization_removes_trailing_slash(self):
        """Test URL normalization removes trailing slash."""
        config = JamaConfig(url="https://test.jamacloud.com/", api_key="key")
        assert config.url == "https://test.jamacloud.com"

    def test_url_empty_raises_error(self):
        """Test empty URL raises validation error."""
        with pytest.raises(ValidationError):
            JamaConfig(url="", api_key="key")

    def test_get_masked_credentials(self):
        """Test masked credentials display."""
        config = JamaConfig(
            url="https://test.jamacloud.com",
            username="testuser",
            password="secretpassword",
            client_id="client12345",
            client_secret="secret",
        )
        masked = config.get_masked_credentials()
        assert masked["url"] == "https://test.jamacloud.com"
        assert masked["username"] == "te...er"  # masked
        assert masked["has_password"] is True
        assert masked["client_id"] == "cl...45"  # masked
        assert masked["has_client_secret"] is True

    def test_get_masked_credentials_short_values(self):
        """Test masking short values."""
        config = JamaConfig(
            url="https://test.jamacloud.com",
            username="ab",  # short value
            api_key="xyz",  # short value
        )
        masked = config.get_masked_credentials()
        assert masked["username"] == "****"  # fully masked
        assert masked["has_api_key"] is True

    def test_get_masked_credentials_empty_values(self):
        """Test masking empty values."""
        config = JamaConfig(
            url="https://test.jamacloud.com",
            api_key="key",
        )
        masked = config.get_masked_credentials()
        assert masked["username"] == ""
        assert masked["has_password"] is False

    def test_validate_auth_allows_no_credentials(self):
        """Test that config can be created without credentials (for later validation)."""
        # This should not raise during construction
        config = JamaConfig(url="https://test.jamacloud.com")
        assert config.url == "https://test.jamacloud.com"


class TestMultiServerConfig:
    """Tests for MultiServerConfig model."""

    def test_create_empty(self):
        """Test creating empty multi-server config."""
        config = MultiServerConfig()
        assert config.servers == {}
        assert config.default_server is None

    def test_create_with_servers(self):
        """Test creating config with multiple servers."""
        config = MultiServerConfig(
            servers={
                "prod": JamaConfig(url="https://prod.jamacloud.com", api_key="key1"),
                "sandbox": JamaConfig(url="https://sandbox.jamacloud.com", api_key="key2"),
            },
            default_server="prod",
        )
        assert "prod" in config.servers
        assert "sandbox" in config.servers
        assert config.default_server == "prod"

    def test_invalid_default_server(self):
        """Test that invalid default server raises error."""
        with pytest.raises(ValidationError) as exc_info:
            MultiServerConfig(
                servers={
                    "prod": JamaConfig(url="https://prod.jamacloud.com", api_key="key"),
                },
                default_server="nonexistent",
            )
        assert "not found" in str(exc_info.value)


class TestMCPRequest:
    """Tests for MCPRequest model."""

    def test_create_basic(self):
        """Test creating basic request."""
        request = MCPRequest(prompt="Get all projects")
        assert request.prompt == "Get all projects"
        assert request.model == "default"
        assert request.parameters is None

    def test_create_with_parameters(self):
        """Test creating request with parameters."""
        request = MCPRequest(
            prompt="Get project",
            model="jama",
            parameters={"project_id": 123},
        )
        assert request.parameters["project_id"] == 123

    def test_empty_prompt_raises_error(self):
        """Test empty prompt raises error."""
        with pytest.raises(ValidationError):
            MCPRequest(prompt="")

    def test_whitespace_prompt_raises_error(self):
        """Test whitespace-only prompt raises error."""
        with pytest.raises(ValidationError):
            MCPRequest(prompt="   ")

    def test_prompt_is_stripped(self):
        """Test prompt whitespace is stripped."""
        request = MCPRequest(prompt="  Get projects  ")
        assert request.prompt == "Get projects"

    def test_extra_fields_rejected(self):
        """Test extra fields are rejected."""
        with pytest.raises(ValidationError):
            MCPRequest(prompt="Test", unknown_field="value")


class TestMCPResponse:
    """Tests for MCPResponse model."""

    def test_create_basic(self):
        """Test creating basic response."""
        response = MCPResponse(response='{"data": "test"}')
        assert response.response == '{"data": "test"}'
        assert response.model is None
        assert response.metadata is None

    def test_create_full(self):
        """Test creating response with all fields."""
        response = MCPResponse(
            response='{"data": "test"}',
            model="jama",
            metadata={"intent": "get_projects", "count": 5},
        )
        assert response.model == "jama"
        assert response.metadata["count"] == 5


class TestHealthCheckResponse:
    """Tests for HealthCheckResponse model."""

    def test_create_healthy(self):
        """Test creating healthy response."""
        response = HealthCheckResponse(
            status="healthy",
            jama_connected=True,
            jama_url="https://jama.example.com",
        )
        assert response.status == "healthy"
        assert response.jama_connected is True

    def test_create_unhealthy(self):
        """Test creating unhealthy response."""
        response = HealthCheckResponse(
            status="unhealthy",
            jama_connected=False,
            jama_url="",
            error="Connection refused",
        )
        assert response.status == "unhealthy"
        assert response.error == "Connection refused"

    def test_create_degraded(self):
        """Test creating degraded response."""
        response = HealthCheckResponse(
            status="degraded",
            jama_connected=True,
            jama_url="https://jama.example.com",
            jama_projects_count=10,
        )
        assert response.status == "degraded"
        assert response.jama_projects_count == 10

    def test_with_optional_fields(self):
        """Test with all optional fields."""
        response = HealthCheckResponse(
            status="healthy",
            jama_connected=True,
            jama_url="https://jama.example.com",
            jama_projects_count=5,
            version="1.0.0",
            uptime_seconds=3600.5,
        )
        assert response.version == "1.0.0"
        assert response.uptime_seconds == 3600.5


class TestBatchRequest:
    """Tests for BatchRequest model."""

    def test_create_basic(self):
        """Test creating batch request."""
        batch = BatchRequest(
            requests=[
                MCPRequest(prompt="Get projects"),
                MCPRequest(prompt="Get items", parameters={"project_id": 1}),
            ]
        )
        assert len(batch.requests) == 2

    def test_empty_requests_raises_error(self):
        """Test empty requests raises error."""
        with pytest.raises(ValidationError):
            BatchRequest(requests=[])

    def test_extra_fields_rejected(self):
        """Test extra fields are rejected."""
        with pytest.raises(ValidationError):
            BatchRequest(
                requests=[MCPRequest(prompt="Test")],
                unknown="value",
            )


class TestBatchResponse:
    """Tests for BatchResponse model."""

    def test_create_basic(self):
        """Test creating batch response."""
        batch = BatchResponse(
            responses=[
                MCPResponse(response="OK"),
                MCPResponse(response="OK"),
            ],
            count=2,
        )
        assert batch.count == 2
        assert batch.errors_count == 0

    def test_with_errors(self):
        """Test batch response with errors."""
        batch = BatchResponse(
            responses=[
                MCPResponse(response="OK"),
                MCPResponse(response="Error", metadata={"error": True}),
            ],
            count=2,
            errors_count=1,
        )
        assert batch.errors_count == 1


class TestErrorResponse:
    """Tests for ErrorResponse model."""

    def test_create_basic(self):
        """Test creating error response."""
        error = ErrorResponse(
            error="Something went wrong",
            error_code="INTERNAL_ERROR",
        )
        assert error.success is False
        assert error.error == "Something went wrong"
        assert error.error_code == "INTERNAL_ERROR"

    def test_with_details(self):
        """Test error response with details."""
        error = ErrorResponse(
            error="Validation failed",
            error_code="VALIDATION_ERROR",
            details={"field": "project_id", "reason": "required"},
        )
        assert error.details["field"] == "project_id"
