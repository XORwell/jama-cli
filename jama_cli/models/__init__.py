"""Data models for Jama CLI."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from jama_cli.core.session import SessionSettings


class JamaProfile(BaseModel):
    """Configuration for a Jama server connection."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    url: str = Field(..., description="Jama instance URL", min_length=1)
    auth_type: Literal["api_key", "oauth", "basic", "session"] = Field(
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

    # Session auth (browser / SSO web session). username/password above are
    # only used by the "form" login mode.
    session_file: str | None = Field(default=None, description="Session store file")
    login_mode: Literal["browser", "form"] = Field(default="browser", description="How to log in")
    login_timeout: float = Field(default=300.0, description="Seconds to wait for a login", gt=0)
    login_interactive: Literal["auto", "always", "never"] = Field(
        default="auto", description="Whether a browser window may be opened for a login"
    )
    browser_channel: str | None = Field(default=None, description="chrome, msedge, ...")
    browser_profile_dir: str | None = Field(
        default=None, description="Persistent browser profile directory"
    )
    sso_selectors: list[str] | None = Field(
        default=None, description="CSS selectors of the SSO login button"
    )
    login_debug_dir: str | None = Field(
        default=None, description="Directory for login step screenshots"
    )
    session_keepalive_minutes: float = Field(
        default=0.0, description="Keepalive interval for the MCP server (0 = off)", ge=0
    )
    session_source: str | None = Field(
        default=None,
        description="Reuse the browser's session: firefox (None = log in)",
    )
    browser_cookie_profile: str | None = Field(
        default=None, description="Browser profile to read cookies from (default: the main one)"
    )
    browser_cookies_path: str | None = Field(
        default=None, description="Override path to the browser cookie store / User Data dir"
    )

    # Refuse every request that could change Jama (CLI and MCP server).
    read_only: bool = Field(default=False, description="Never change anything in Jama")

    @field_validator("sso_selectors", mode="before")
    @classmethod
    def split_selectors(cls, v: Any) -> Any:
        """Accept a comma-separated string (env var) as well as a list."""
        if isinstance(v, str):
            return [part.strip() for part in v.split(",") if part.strip()] or None
        return v

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
            "read_only": "yes" if self.read_only else "",
        }

    def has_valid_credentials(self) -> bool:
        """Check if credentials are configured for the auth type."""
        if self.auth_type == "api_key":
            return bool(self.api_key)
        elif self.auth_type == "oauth":
            return bool(self.client_id and self.client_secret)
        elif self.auth_type == "basic":
            return bool(self.username and self.password)
        elif self.auth_type == "session":
            # The credential is the web session in the store; form login
            # additionally needs username/password, checked at login time.
            return True
        return False

    def session_settings(self) -> SessionSettings:
        """Build the settings for ``auth_type=session`` from this profile."""
        from jama_cli.core.session import DEFAULT_SSO_SELECTORS, SessionSettings

        def as_path(value: str | None) -> Path | None:
            return Path(value).expanduser() if value else None

        return SessionSettings(
            base_url=self.url,
            username=self.username,
            password=self.password,
            login_mode=self.login_mode,
            login_timeout=self.login_timeout,
            login_interactive=self.login_interactive,
            browser_channel=self.browser_channel,
            browser_profile_dir=as_path(self.browser_profile_dir),
            sso_selectors=tuple(self.sso_selectors or DEFAULT_SSO_SELECTORS),
            debug_dir=as_path(self.login_debug_dir),
            session_file=as_path(self.session_file),
            keepalive_minutes=self.session_keepalive_minutes,
            session_source=self.session_source,
            browser_cookie_profile=self.browser_cookie_profile,
            browser_cookies_path=as_path(self.browser_cookies_path),
        )


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
