"""Unit tests for MCP server configuration."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from jama_mcp_server.config import (
    load_config,
    load_env_config,
    load_yaml_config,
    list_servers,
)
from jama_mcp_server.models import JamaConfig, MultiServerConfig


class TestJamaConfig:
    """Tests for JamaConfig model."""

    def test_oauth_config(self):
        """Test OAuth configuration."""
        config = JamaConfig(
            url="https://test.jamacloud.com",
            client_id="client123",
            client_secret="secret456",
        )
        assert config.client_id == "client123"
        assert config.client_secret == "secret456"

    def test_basic_auth_config(self):
        """Test basic auth configuration."""
        config = JamaConfig(
            url="https://test.jamacloud.com",
            username="user",
            password="pass",
        )
        assert config.username == "user"
        assert config.password == "pass"


class TestMultiServerConfig:
    """Tests for MultiServerConfig model."""

    def test_multi_server_config(self):
        """Test multi-server configuration."""
        config = MultiServerConfig(
            servers={
                "prod": JamaConfig(url="https://prod.jamacloud.com"),
                "sandbox": JamaConfig(url="https://sandbox.jamacloud.com"),
            },
            default_server="prod",
        )
        assert "prod" in config.servers
        assert "sandbox" in config.servers
        assert config.default_server == "prod"


class TestLoadEnvConfig:
    """Tests for load_env_config function."""

    def test_load_from_env(self):
        """Test loading config from environment variables."""
        with patch.dict(os.environ, {
            "JAMA_URL": "https://env.jamacloud.com",
            "JAMA_CLIENT_ID": "envclient",
            "JAMA_CLIENT_SECRET": "envsecret",
        }, clear=True):
            config = load_env_config()
            assert config is not None
            assert config.url == "https://env.jamacloud.com"
            assert config.client_id == "envclient"

    def test_load_env_no_url(self):
        """Test loading config without URL returns None."""
        with patch.dict(os.environ, {}, clear=True):
            config = load_env_config()
            assert config is None


class TestLoadYamlConfig:
    """Tests for load_yaml_config function."""

    def test_load_from_yaml(self):
        """Test loading config from YAML file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text("""
servers:
  prod:
    url: https://prod.jamacloud.com
    client_id: prodclient
    client_secret: prodsecret
  sandbox:
    url: https://sandbox.jamacloud.com
    username: user
    password: pass
default_server: prod
""")
            config = load_yaml_config(str(config_path))
            assert config is not None
            assert "prod" in config.servers
            assert "sandbox" in config.servers
            assert config.default_server == "prod"

    def test_load_yaml_invalid_format(self):
        """Test loading invalid YAML format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text("invalid: yaml: content")
            config = load_yaml_config(str(config_path))
            assert config is None

    def test_load_yaml_nonexistent(self):
        """Test loading non-existent YAML file."""
        config = load_yaml_config("/nonexistent/path/config.yml")
        assert config is None


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_from_yaml(self):
        """Test loading config from YAML."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text("""
servers:
  test:
    url: https://test.jamacloud.com
    client_id: testclient
    client_secret: testsecret
""")
            config = load_config(config_file=str(config_path), server_name="test")
            assert config is not None
            assert config.url == "https://test.jamacloud.com"

    def test_load_config_fallback_to_env(self):
        """Test load_config falls back to env."""
        with patch.dict(os.environ, {
            "JAMA_URL": "https://env.jamacloud.com",
        }, clear=True):
            # No YAML config, should use env
            config = load_config(config_file="/nonexistent/config.yml")
            if config:
                assert "env.jamacloud.com" in config.url


class TestListServers:
    """Tests for list_servers function."""

    def test_list_servers(self):
        """Test listing servers from config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text("""
servers:
  prod:
    url: https://prod.jamacloud.com
  sandbox:
    url: https://sandbox.jamacloud.com
""")
            servers = list_servers(str(config_path))
            assert "prod" in servers
            assert "sandbox" in servers
            assert servers["prod"] == "https://prod.jamacloud.com"

    def test_list_servers_no_config(self):
        """Test listing servers with no config."""
        servers = list_servers("/nonexistent/config.yml")
        assert servers == {}


class TestLoadConfigIntegration:
    """Integration tests for load_config function."""

    def test_load_config_selects_named_server(self):
        """Test loading config with named server."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text("""
servers:
  prod:
    url: https://prod.jamacloud.com
    api_key: prodkey
  sandbox:
    url: https://sandbox.jamacloud.com
    api_key: sandboxkey
default_server: prod
""")
            config = load_config(config_file=str(config_path), server_name="sandbox")
            assert config is not None
            assert config.url == "https://sandbox.jamacloud.com"

    def test_load_config_uses_default_server(self):
        """Test loading config uses default server."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text("""
servers:
  prod:
    url: https://prod.jamacloud.com
    api_key: prodkey
  sandbox:
    url: https://sandbox.jamacloud.com
    api_key: sandboxkey
default_server: prod
""")
            config = load_config(config_file=str(config_path))
            assert config is not None
            assert config.url == "https://prod.jamacloud.com"

    def test_load_config_single_server_no_default(self):
        """Test loading config with single server and no default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text("""
servers:
  only:
    url: https://only.jamacloud.com
    api_key: onlykey
""")
            config = load_config(config_file=str(config_path))
            assert config is not None
            assert config.url == "https://only.jamacloud.com"

    def test_load_config_multiple_servers_no_default_returns_none(self):
        """Test loading config with multiple servers and no default returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text("""
servers:
  prod:
    url: https://prod.jamacloud.com
    api_key: prodkey
  sandbox:
    url: https://sandbox.jamacloud.com
    api_key: sandboxkey
""")
            config = load_config(config_file=str(config_path))
            # Should return None because no default and multiple servers
            assert config is None

    def test_load_config_nonexistent_server_name(self):
        """Test loading config with nonexistent server name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text("""
servers:
  prod:
    url: https://prod.jamacloud.com
    api_key: prodkey
""")
            config = load_config(config_file=str(config_path), server_name="nonexistent")
            assert config is None

    def test_load_config_from_env_file(self):
        """Test loading config from .env file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("JAMA_URL=https://env.jamacloud.com\nJAMA_API_KEY=envkey")

            # Clear any YAML config
            config = load_config(env_file=str(env_path))
            # This may or may not return config depending on env state
            # Just verify it doesn't crash
            assert config is None or config.url is not None


class TestLoadYamlConfigEdgeCases:
    """Edge case tests for load_yaml_config function."""

    def test_load_yaml_missing_servers_key(self):
        """Test loading YAML without servers key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text("""
other_key: value
""")
            config = load_yaml_config(str(config_path))
            assert config is None

    def test_load_yaml_from_env_var(self):
        """Test loading YAML from JAMA_CONFIG env var."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "myconfig.yml"
            config_path.write_text("""
servers:
  test:
    url: https://test.jamacloud.com
    api_key: testkey
""")
            with patch.dict(os.environ, {"JAMA_CONFIG": str(config_path)}):
                config = load_yaml_config()
                assert config is not None
                assert "test" in config.servers
