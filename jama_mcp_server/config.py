"""
Configuration loader for Jama MCP Server.
Supports both .env files and YAML config files with multi-server definitions.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from loguru import logger

from jama_mcp_server.models import JamaConfig, MultiServerConfig


def load_env_config(env_file: str | None = None) -> JamaConfig | None:
    """
    Load configuration from .env file (legacy single-server format).

    Args:
        env_file: Optional path to .env file

    Returns:
        JamaConfig if successfully loaded, None otherwise
    """
    load_dotenv(dotenv_path=env_file)

    jama_url = os.environ.get("JAMA_URL")
    if not jama_url:
        return None

    return JamaConfig(
        url=jama_url,
        username=os.environ.get("JAMA_USERNAME", ""),
        password=os.environ.get("JAMA_PASSWORD", ""),
        api_key=os.environ.get("JAMA_API_KEY", ""),
        oauth=os.environ.get("JAMA_OAUTH", "false").lower() == "true",
        client_id=os.environ.get("JAMA_CLIENT_ID", ""),
        client_secret=os.environ.get("JAMA_CLIENT_SECRET", ""),
    )


def load_yaml_config(config_file: str | None = None) -> MultiServerConfig | None:
    """
    Load configuration from YAML file (multi-server format).

    Looks for config file in the following order:
    1. Explicitly provided config_file path
    2. JAMA_CONFIG environment variable
    3. ~/.jama/config.yml (user home directory)
    4. ./config.yml (current working directory)
    5. ./config.yaml (current working directory)

    Args:
        config_file: Optional path to YAML config file

    Returns:
        MultiServerConfig if successfully loaded, None otherwise
    """
    # Try to find config file
    config_paths: list[Path] = []

    if config_file:
        config_paths.append(Path(config_file))

    # Check JAMA_CONFIG environment variable
    env_config = os.environ.get("JAMA_CONFIG")
    if env_config:
        config_paths.append(Path(env_config))

    # Check user home directory (~/.jama/config.yml)
    home_config = Path.home() / ".jama" / "config.yml"
    config_paths.append(home_config)

    # Check current directory
    for filename in ["config.yml", "config.yaml"]:
        config_paths.append(Path.cwd() / filename)

    # Try each path
    config_path: Path | None = None
    for path in config_paths:
        if path.exists():
            config_path = path
            logger.info(f"Found config file: {config_path}")
            break

    if not config_path:
        logger.debug(f"No config file found in: {config_paths}")
        return None

    try:
        with open(config_path) as f:
            data = yaml.safe_load(f)

        if not data or "servers" not in data:
            logger.warning(f"Invalid config file format: {config_path}")
            return None

        # Parse servers
        servers: dict[str, JamaConfig] = {}
        for name, server_data in data["servers"].items():
            servers[name] = JamaConfig(
                url=server_data.get("url", ""),
                username=server_data.get("username", ""),
                password=server_data.get("password", ""),
                api_key=server_data.get("api_key", ""),
                oauth=server_data.get("oauth", False),
                client_id=server_data.get("client_id", ""),
                client_secret=server_data.get("client_secret", ""),
            )

        return MultiServerConfig(servers=servers, default_server=data.get("default_server"))
    except Exception as e:
        logger.error(f"Error loading config file {config_path}: {e}")
        return None


def load_config(
    config_file: str | None = None,
    env_file: str | None = None,
    server_name: str | None = None,
) -> JamaConfig | None:
    """
    Load Jama configuration from YAML or .env file.

    Priority:
    1. YAML config file (multi-server support)
    2. .env file (single-server, legacy)

    Args:
        config_file: Optional path to YAML config file
        env_file: Optional path to .env file
        server_name: Optional server name to select from multi-server config

    Returns:
        JamaConfig for the selected server, or None if not found
    """
    # Try YAML config first (multi-server)
    multi_config = load_yaml_config(config_file)
    if multi_config:
        # Select server
        if server_name:
            if server_name not in multi_config.servers:
                logger.error(f"Server '{server_name}' not found in config")
                return None
            logger.info(f"Using server configuration: {server_name}")
            return multi_config.servers[server_name]
        elif multi_config.default_server:
            logger.info(f"Using default server configuration: {multi_config.default_server}")
            return multi_config.servers[multi_config.default_server]
        elif len(multi_config.servers) == 1:
            # If only one server, use it
            name = list(multi_config.servers.keys())[0]
            logger.info(f"Using only available server configuration: {name}")
            return multi_config.servers[name]
        else:
            logger.error(
                "Multiple servers configured but no server name specified and no default set"
            )
            available = ", ".join(multi_config.servers.keys())
            logger.error(f"Available servers: {available}")
            return None

    # Fall back to .env config (single-server, legacy)
    logger.info("No YAML config found, trying .env file")
    return load_env_config(env_file)


def list_servers(config_file: str | None = None) -> dict[str, str]:
    """
    List all configured servers.

    Args:
        config_file: Optional path to YAML config file

    Returns:
        Dictionary mapping server names to their URLs
    """
    multi_config = load_yaml_config(config_file)
    if not multi_config:
        return {}

    return {name: config.url for name, config in multi_config.servers.items()}
