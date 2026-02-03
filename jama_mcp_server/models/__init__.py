"""
Data models for the Jama MCP server.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class JamaConfig(BaseModel):
    """Jama configuration for a single server."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    url: str = Field(..., description="Jama instance URL", min_length=1)
    username: str = Field("", description="Jama username")
    password: str = Field("", description="Jama password")
    api_key: str = Field("", description="Jama API key")
    oauth: bool = Field(False, description="Whether to use OAuth authentication")
    client_id: str = Field("", description="OAuth client ID")
    client_secret: str = Field("", description="OAuth client secret")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate and normalize URL."""
        if not v:
            raise ValueError("URL cannot be empty")
        # Ensure URL has protocol
        if not v.startswith(("http://", "https://")):
            v = f"https://{v}"
        # Remove trailing slash
        return v.rstrip("/")

    @model_validator(mode="after")
    def validate_auth(self) -> JamaConfig:
        """Validate that authentication credentials are provided."""
        has_api_key = bool(self.api_key)
        has_oauth = bool(self.client_id and self.client_secret)
        has_basic = bool(self.username and self.password)

        if not (has_api_key or has_oauth or has_basic):
            # Don't raise during construction, let CLI handle validation
            pass
        return self

    def get_masked_credentials(self) -> dict[str, str | bool]:
        """Get masked credentials for logging."""

        def mask(value: str) -> str:
            if not value:
                return ""
            if len(value) <= 4:
                return "****"
            return f"{value[:2]}...{value[-2:]}"

        return {
            "url": self.url,
            "username": mask(self.username),
            "has_password": bool(self.password),
            "has_api_key": bool(self.api_key),
            "oauth": self.oauth,
            "client_id": mask(self.client_id),
            "has_client_secret": bool(self.client_secret),
        }


class MultiServerConfig(BaseModel):
    """Configuration for multiple Jama servers."""

    model_config = ConfigDict(validate_assignment=True)

    servers: dict[str, JamaConfig] = Field(
        default_factory=dict, description="Dictionary of named server configurations"
    )
    default_server: str | None = Field(
        default=None, description="Name of the default server to use"
    )

    @model_validator(mode="after")
    def validate_default_server(self) -> MultiServerConfig:
        """Validate that default server exists in servers dict."""
        if self.default_server and self.default_server not in self.servers:
            raise ValueError(
                f"Default server '{self.default_server}' not found in servers. "
                f"Available: {', '.join(self.servers.keys())}"
            )
        return self


class MCPRequest(BaseModel):
    """MCP request model."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",  # Reject unknown fields
    )

    prompt: str = Field(
        ...,
        description="The prompt text or operation name",
        min_length=1,
        max_length=10000,
    )
    model: str = Field("default", description="The model to use")
    parameters: dict[str, Any] | None = Field(
        default=None, description="Additional parameters for the operation"
    )

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, v: str) -> str:
        """Validate prompt content."""
        if not v or not v.strip():
            raise ValueError("Prompt cannot be empty")
        return v.strip()


class MCPResponse(BaseModel):
    """MCP response model."""

    model_config = ConfigDict(validate_assignment=True)

    response: str = Field(..., description="The response text (JSON-encoded)")
    model: str | None = Field(default=None, description="The model used")
    metadata: dict[str, Any] | None = Field(
        default=None, description="Additional metadata about the response"
    )


class HealthCheckResponse(BaseModel):
    """Health check response model."""

    model_config = ConfigDict(validate_assignment=True)

    status: Literal["healthy", "unhealthy", "degraded"] = Field(
        ..., description="Health status"
    )
    jama_connected: bool = Field(..., description="Whether connected to Jama")
    jama_url: str = Field(..., description="Jama URL")
    jama_projects_count: int | None = Field(
        default=None, description="Number of Jama projects (if connected)"
    )
    error: str | None = Field(default=None, description="Error message if any")
    version: str | None = Field(default=None, description="Server version")
    uptime_seconds: float | None = Field(
        default=None, description="Server uptime in seconds"
    )


class BatchRequest(BaseModel):
    """Batch request model for multiple operations."""

    model_config = ConfigDict(extra="forbid")

    requests: list[MCPRequest] = Field(
        ...,
        description="List of MCP requests to execute",
        min_length=1,
        max_length=100,  # Limit batch size
    )


class BatchResponse(BaseModel):
    """Batch response model."""

    responses: list[MCPResponse] = Field(..., description="List of responses")
    count: int = Field(..., description="Number of responses")
    errors_count: int = Field(default=0, description="Number of failed operations")


class ErrorResponse(BaseModel):
    """Standard error response model."""

    success: bool = Field(default=False, description="Always false for errors")
    error: str = Field(..., description="Error message")
    error_code: str = Field(..., description="Error code for programmatic handling")
    details: dict[str, Any] | None = Field(
        default=None, description="Additional error details"
    )


# Export all models
__all__ = [
    "JamaConfig",
    "MultiServerConfig",
    "MCPRequest",
    "MCPResponse",
    "HealthCheckResponse",
    "BatchRequest",
    "BatchResponse",
    "ErrorResponse",
]
