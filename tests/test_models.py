"""
Unit tests for the data models.
"""

import pytest
from pydantic import ValidationError

from jama_mcp_server.models import (
    BatchRequest,
    ErrorResponse,
    HealthCheckResponse,
    JamaConfig,
    MCPRequest,
    MCPResponse,
    MultiServerConfig,
)


class TestJamaConfig:
    """Tests for JamaConfig model."""

    def test_valid_config_with_api_key(self) -> None:
        """Test creating config with API key."""
        config = JamaConfig(url="https://example.jamacloud.com", api_key="test_api_key")
        assert config.url == "https://example.jamacloud.com"
        assert config.api_key == "test_api_key"

    def test_valid_config_with_oauth(self) -> None:
        """Test creating config with OAuth credentials."""
        config = JamaConfig(
            url="https://example.jamacloud.com",
            oauth=True,
            client_id="client_id",
            client_secret="client_secret",
        )
        assert config.oauth is True
        assert config.client_id == "client_id"

    def test_valid_config_with_basic_auth(self) -> None:
        """Test creating config with username/password."""
        config = JamaConfig(url="https://example.jamacloud.com", username="user", password="pass")
        assert config.username == "user"
        assert config.password == "pass"

    def test_url_validation_adds_https(self) -> None:
        """Test that URL without protocol gets https added."""
        config = JamaConfig(url="example.jamacloud.com", api_key="key")
        assert config.url == "https://example.jamacloud.com"

    def test_url_validation_removes_trailing_slash(self) -> None:
        """Test that trailing slash is removed from URL."""
        config = JamaConfig(url="https://example.jamacloud.com/", api_key="key")
        assert config.url == "https://example.jamacloud.com"

    def test_url_validation_empty_fails(self) -> None:
        """Test that empty URL fails validation."""
        with pytest.raises(ValidationError):
            JamaConfig(url="")

    def test_get_masked_credentials(self) -> None:
        """Test credential masking for logging."""
        config = JamaConfig(
            url="https://example.jamacloud.com",
            username="testuser",
            password="secretpass",
            client_id="my_client_id",
            client_secret="my_secret",
        )
        masked = config.get_masked_credentials()

        assert masked["url"] == "https://example.jamacloud.com"
        assert masked["username"] == "te...er"
        assert masked["has_password"] is True
        assert masked["client_id"] == "my...id"
        assert masked["has_client_secret"] is True


class TestMultiServerConfig:
    """Tests for MultiServerConfig model."""

    def test_valid_multi_server_config(self) -> None:
        """Test creating valid multi-server config."""
        config = MultiServerConfig(
            servers={
                "prod": JamaConfig(url="https://prod.jama.com", api_key="key1"),
                "dev": JamaConfig(url="https://dev.jama.com", api_key="key2"),
            },
            default_server="prod",
        )
        assert len(config.servers) == 2
        assert config.default_server == "prod"

    def test_invalid_default_server(self) -> None:
        """Test that invalid default server raises error."""
        with pytest.raises(ValidationError) as exc_info:
            MultiServerConfig(
                servers={
                    "prod": JamaConfig(url="https://prod.jama.com", api_key="key"),
                },
                default_server="nonexistent",
            )
        assert "not found in servers" in str(exc_info.value)


class TestMCPRequest:
    """Tests for MCPRequest model."""

    def test_valid_request(self) -> None:
        """Test creating valid request."""
        request = MCPRequest(prompt="get all projects", parameters={"intent": "get_projects"})
        assert request.prompt == "get all projects"
        assert request.parameters["intent"] == "get_projects"

    def test_request_with_defaults(self) -> None:
        """Test request with default values."""
        request = MCPRequest(prompt="test")
        assert request.model == "default"
        assert request.parameters is None

    def test_empty_prompt_fails(self) -> None:
        """Test that empty prompt fails validation."""
        with pytest.raises(ValidationError):
            MCPRequest(prompt="")

    def test_whitespace_prompt_fails(self) -> None:
        """Test that whitespace-only prompt fails validation."""
        with pytest.raises(ValidationError):
            MCPRequest(prompt="   ")

    def test_prompt_stripped(self) -> None:
        """Test that prompt is stripped of whitespace."""
        request = MCPRequest(prompt="  test prompt  ")
        assert request.prompt == "test prompt"

    def test_extra_fields_forbidden(self) -> None:
        """Test that extra fields are rejected."""
        with pytest.raises(ValidationError):
            MCPRequest(prompt="test", unknown_field="value")

    def test_prompt_max_length(self) -> None:
        """Test prompt max length validation."""
        with pytest.raises(ValidationError):
            MCPRequest(prompt="x" * 10001)


class TestMCPResponse:
    """Tests for MCPResponse model."""

    def test_valid_response(self) -> None:
        """Test creating valid response."""
        response = MCPResponse(response='{"data": "test"}', metadata={"status": "success"})
        assert response.response == '{"data": "test"}'
        assert response.metadata["status"] == "success"

    def test_response_with_defaults(self) -> None:
        """Test response with default values."""
        response = MCPResponse(response="test")
        assert response.model is None
        assert response.metadata is None


class TestHealthCheckResponse:
    """Tests for HealthCheckResponse model."""

    def test_healthy_response(self) -> None:
        """Test healthy status response."""
        response = HealthCheckResponse(
            status="healthy",
            jama_connected=True,
            jama_url="https://example.jama.com",
            jama_projects_count=5,
        )
        assert response.status == "healthy"
        assert response.jama_connected is True

    def test_unhealthy_response(self) -> None:
        """Test unhealthy status response."""
        response = HealthCheckResponse(
            status="unhealthy",
            jama_connected=False,
            jama_url="https://example.jama.com",
            error="Connection failed",
        )
        assert response.status == "unhealthy"
        assert response.error == "Connection failed"

    def test_invalid_status(self) -> None:
        """Test that invalid status raises error."""
        with pytest.raises(ValidationError):
            HealthCheckResponse(
                status="invalid", jama_connected=False, jama_url="https://example.jama.com"
            )


class TestBatchRequest:
    """Tests for BatchRequest model."""

    def test_valid_batch_request(self) -> None:
        """Test creating valid batch request."""
        batch = BatchRequest(
            requests=[
                MCPRequest(prompt="get projects"),
                MCPRequest(prompt="get items", parameters={"project_id": 1}),
            ]
        )
        assert len(batch.requests) == 2

    def test_empty_batch_fails(self) -> None:
        """Test that empty batch fails validation."""
        with pytest.raises(ValidationError):
            BatchRequest(requests=[])

    def test_batch_max_size(self) -> None:
        """Test batch max size validation."""
        with pytest.raises(ValidationError):
            BatchRequest(requests=[MCPRequest(prompt=f"test {i}") for i in range(101)])


class TestErrorResponse:
    """Tests for ErrorResponse model."""

    def test_error_response(self) -> None:
        """Test creating error response."""
        error = ErrorResponse(
            error="Something went wrong", error_code="INTERNAL_ERROR", details={"traceback": "..."}
        )
        assert error.success is False
        assert error.error == "Something went wrong"
        assert error.error_code == "INTERNAL_ERROR"
