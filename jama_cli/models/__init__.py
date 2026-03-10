"""Data models for Jama CLI."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class JamaProfile(BaseModel):
    """Configuration for a Jama server connection."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    url: str = Field(..., description="Jama instance URL", min_length=1)
    auth_type: Literal["api_key", "oauth", "basic"] = Field(
        "api_key", description="Authentication type"
    )

    # API Key auth
    api_key: str | None = Field(default=None, description="Jama API key")

    # OAuth auth
    client_id: str | None = Field(default=None, description="OAuth client ID")
    client_secret: str | None = Field(default=None, description="OAuth client secret")

    # Basic auth
    username: str | None = Field(default=None, description="Jama username")
    password: str | None = Field(default=None, description="Jama password")

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

    def get_masked_display(self) -> dict[str, str]:
        """Get masked credentials for display."""

        def mask(value: str | None) -> str:
            if not value:
                return ""
            if len(value) <= 4:
                return "****"
            return f"{value[:2]}...{value[-2:]}"

        return {
            "url": self.url,
            "auth_type": self.auth_type,
            "api_key": mask(self.api_key) if self.api_key else "",
            "client_id": mask(self.client_id) if self.client_id else "",
            "username": mask(self.username) if self.username else "",
        }

    def has_valid_credentials(self) -> bool:
        """Check if credentials are configured for the auth type."""
        if self.auth_type == "api_key":
            return bool(self.api_key)
        elif self.auth_type == "oauth":
            return bool(self.client_id and self.client_secret)
        elif self.auth_type == "basic":
            return bool(self.username and self.password)
        return False


class JamaConfig(BaseModel):
    """CLI configuration with multiple profiles."""

    model_config = ConfigDict(validate_assignment=True)

    default_profile: str = Field(default="default", description="Default profile name")
    profiles: dict[str, JamaProfile] = Field(default_factory=dict, description="Named profiles")

    # Default output settings
    output_format: Literal["table", "json", "csv", "yaml"] = Field(
        default="table", description="Default output format"
    )
    default_limit: int = Field(default=50, description="Default pagination limit")

    def get_profile(self, name: str | None = None) -> JamaProfile | None:
        """Get a profile by name, or the default profile."""
        profile_name = name or self.default_profile
        return self.profiles.get(profile_name)


class JamaItem(BaseModel):
    """Jama item model for display."""

    id: int
    name: str
    document_key: str | None = Field(default=None, alias="documentKey")
    item_type: int | None = Field(default=None, alias="itemType")
    project: int | None = None
    parent: int | None = None
    status: str | None = None
    created_date: str | None = Field(default=None, alias="createdDate")
    modified_date: str | None = Field(default=None, alias="modifiedDate")
    fields: dict[str, Any] = Field(default_factory=dict)


class JamaProject(BaseModel):
    """Jama project model for display."""

    id: int
    name: str
    project_key: str | None = Field(default=None, alias="projectKey")
    description: str | None = None
    status: str | None = None
    created_date: str | None = Field(default=None, alias="createdDate")
    modified_date: str | None = Field(default=None, alias="modifiedDate")


# Export all models
__all__ = [
    "JamaProfile",
    "JamaConfig",
    "JamaItem",
    "JamaProject",
]
