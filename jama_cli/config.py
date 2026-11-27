"""Configuration management for Jama CLI."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from loguru import logger

from jama_cli.core.read_only import read_only_from_env
from jama_cli.models import JamaConfig, JamaProfile

# Session-auth settings: profile key -> environment variable. Like the
# credential variables, these override the config file.
SESSION_ENV_VARS = {
    "session_file": "JAMA_SESSION_FILE",
    "login_mode": "JAMA_LOGIN_MODE",
    "login_timeout": "JAMA_LOGIN_TIMEOUT",
    "login_interactive": "JAMA_LOGIN_INTERACTIVE",
    "browser_channel": "JAMA_BROWSER_CHANNEL",
    "browser_profile_dir": "JAMA_BROWSER_PROFILE_DIR",
    "sso_selectors": "JAMA_SSO_SELECTORS",
    "login_debug_dir": "JAMA_LOGIN_DEBUG_DIR",
    "session_keepalive_minutes": "JAMA_SESSION_KEEPALIVE_MINUTES",
    "session_source": "JAMA_SESSION_SOURCE",
    "browser_cookie_profile": "JAMA_BROWSER_COOKIE_PROFILE",
    "browser_cookies_path": "JAMA_BROWSER_COOKIES_PATH",
}

# Default config location
CONFIG_DIR = Path.home() / ".jama"
CONFIG_FILE = CONFIG_DIR / "config.yml"


def get_config_path() -> Path:
    """Get the configuration file path.

    Checks in order:
    1. JAMA_CONFIG environment variable
    2. ~/.jama/config.yml
    3. ./config.yml (current directory)
    """
    # Check environment variable
    env_config = os.environ.get("JAMA_CONFIG")
    if env_config:
        path = Path(env_config)
        if path.exists():
            return path

    # Check user config directory
    if CONFIG_FILE.exists():
        return CONFIG_FILE

    # Check current directory
    local_config = Path.cwd() / "config.yml"
    if local_config.exists():
        return local_config

    # Return default location (may not exist)
    return CONFIG_FILE


def load_config() -> JamaConfig:
    """Load configuration from file.

    Returns:
        JamaConfig with loaded profiles, or empty config if file doesn't exist
    """
    config_path = get_config_path()

    if not config_path.exists():
        logger.debug(f"Config file not found: {config_path}")
        return JamaConfig()

    try:
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

        # Parse profiles
        profiles: dict[str, JamaProfile] = {}
        for name, profile_data in data.get("profiles", {}).items():
            # Expand environment variables in values
            expanded_data = _expand_env_vars(profile_data)
            profiles[name] = JamaProfile(**expanded_data)

        return JamaConfig(
            default_profile=data.get("default_profile", "default"),
            profiles=profiles,
            output_format=data.get("defaults", {}).get("output", "table"),
            default_limit=data.get("defaults", {}).get("limit", 50),
        )

    except Exception as e:
        logger.error(f"Error loading config from {config_path}: {e}")
        return JamaConfig()


def save_config(config: JamaConfig) -> None:
    """Save configuration to file."""
    config_path = get_config_path()

    # Ensure directory exists
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert to dict for YAML
    data = {
        "default_profile": config.default_profile,
        "profiles": {},
        "defaults": {
            "output": config.output_format,
            "limit": config.default_limit,
        },
    }

    for name, profile in config.profiles.items():
        profile_data = {
            "url": profile.url,
            "auth_type": profile.auth_type,
        }
        if profile.api_key:
            profile_data["api_key"] = profile.api_key
        if profile.client_id:
            profile_data["client_id"] = profile.client_id
        if profile.client_secret:
            profile_data["client_secret"] = profile.client_secret
        if profile.username:
            profile_data["username"] = profile.username
        if profile.password:
            profile_data["password"] = profile.password
        if profile.read_only:
            profile_data["read_only"] = True
        if profile.auth_type == "session":
            # Only non-default session settings are written back.
            defaults = JamaProfile.model_fields
            for key in SESSION_ENV_VARS:
                value = getattr(profile, key)
                if value is not None and value != defaults[key].default:
                    profile_data[key] = value

        data["profiles"][name] = profile_data

    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    logger.info(f"Config saved to {config_path}")


def _expand_env_vars(data: dict) -> dict:
    """Expand environment variables in dict values.

    Supports ${VAR_NAME} syntax.
    """
    result = {}
    for key, value in data.items():
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            env_var = value[2:-1]
            result[key] = os.environ.get(env_var, "")
        else:
            result[key] = value
    return result


def get_profile(profile_name: str | None = None) -> JamaProfile | None:
    """Get a profile by name or the default profile.

    Args:
        profile_name: Profile name, or None for default

    Returns:
        JamaProfile if found, None otherwise
    """
    config = load_config()
    return config.get_profile(profile_name)


def get_profile_or_env(profile_name: str | None = None) -> JamaProfile | None:
    """Get a profile from environment variables, or fall back to config file.

    Environment variables take precedence over the config file when JAMA_URL
    is set, following the standard convention (like AWS_ACCESS_KEY_ID overriding
    ~/.aws/credentials). This is critical for MCP server usage where mcp.json
    passes credentials as env vars.
    """
    # Check environment variables first (they take precedence)
    jama_url = os.environ.get("JAMA_URL")
    if jama_url:
        api_key = os.environ.get("JAMA_API_KEY")
        client_id = os.environ.get("JAMA_CLIENT_ID")
        client_secret = os.environ.get("JAMA_CLIENT_SECRET")
        username = os.environ.get("JAMA_USERNAME")
        password = os.environ.get("JAMA_PASSWORD")

        # Determine auth type. JAMA_AUTH_TYPE=session selects the browser-session
        # mode explicitly; without it the credentials decide, as before.
        if os.environ.get("JAMA_AUTH_TYPE", "").strip().lower() == "session":
            auth_type = "session"
        elif api_key:
            auth_type = "api_key"
        elif client_id and client_secret:
            auth_type = "oauth"
        elif username and password:
            auth_type = "basic"
        else:
            auth_type = None

        if auth_type:
            return _apply_read_only_env(
                _apply_session_env(
                    JamaProfile(
                        url=jama_url,
                        auth_type=auth_type,
                        api_key=api_key,
                        client_id=client_id,
                        client_secret=client_secret,
                        username=username,
                        password=password,
                    )
                )
            )

    # Fall back to config file
    profile = get_profile(profile_name)
    if profile and profile.auth_type == "session":
        profile = _apply_session_env(profile)

    return _apply_read_only_env(profile) if profile else None


def _apply_read_only_env(profile: JamaProfile) -> JamaProfile:
    """Turn read-only mode on when JAMA_READ_ONLY says so.

    The variable can only turn the mode on: ``read_only: true`` in a profile
    stays on whatever the environment says.
    """
    if profile.read_only or not read_only_from_env():
        return profile
    return profile.model_copy(update={"read_only": True})


def _apply_session_env(profile: JamaProfile) -> JamaProfile:
    """Overlay JAMA_* session settings from the environment onto a profile."""
    if profile.auth_type != "session":
        return profile
    overrides = {
        key: os.environ[env_var]
        for key, env_var in SESSION_ENV_VARS.items()
        if os.environ.get(env_var)
    }
    if not overrides:
        return profile
    return JamaProfile(**{**profile.model_dump(), **overrides})
