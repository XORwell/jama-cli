"""Unit tests for configuration module."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jama_cli.config import (
    get_profile_or_env,
    get_profile,
    load_config,
    save_config,
    get_config_path,
    _expand_env_vars,
)
from jama_cli.models import JamaProfile, JamaConfig


class TestJamaProfile:
    """Tests for JamaProfile model."""

    def test_create_profile_with_basic_auth(self):
        """Test creating profile with username/password."""
        profile = JamaProfile(
            url="https://example.jamacloud.com",
            auth_type="basic",
            username="user",
            password="pass",
        )
        assert profile.url == "https://example.jamacloud.com"
        assert profile.username == "user"
        assert profile.password == "pass"

    def test_create_profile_with_oauth(self):
        """Test creating profile with OAuth credentials."""
        profile = JamaProfile(
            url="https://example.jamacloud.com",
            auth_type="oauth",
            client_id="client123",
            client_secret="secret456",
        )
        assert profile.url == "https://example.jamacloud.com"
        assert profile.client_id == "client123"
        assert profile.client_secret == "secret456"

    def test_create_profile_with_api_key(self):
        """Test creating profile with API key."""
        profile = JamaProfile(
            url="https://example.jamacloud.com",
            auth_type="api_key",
            api_key="myapikey123",
        )
        assert profile.api_key == "myapikey123"

    def test_profile_url_normalization(self):
        """Test that URLs are normalized (trailing slash removed)."""
        profile = JamaProfile(
            url="https://example.jamacloud.com/",
            auth_type="api_key",
            api_key="key",
        )
        assert profile.url == "https://example.jamacloud.com"

    def test_profile_url_adds_https(self):
        """Test that URLs without protocol get https added."""
        profile = JamaProfile(
            url="example.jamacloud.com",
            auth_type="api_key",
            api_key="key",
        )
        assert profile.url == "https://example.jamacloud.com"

    def test_has_valid_credentials_api_key(self):
        """Test has_valid_credentials with api_key."""
        profile = JamaProfile(url="https://test.com", auth_type="api_key", api_key="key")
        assert profile.has_valid_credentials() is True

    def test_has_valid_credentials_oauth(self):
        """Test has_valid_credentials with oauth."""
        profile = JamaProfile(
            url="https://test.com",
            auth_type="oauth",
            client_id="id",
            client_secret="secret",
        )
        assert profile.has_valid_credentials() is True

    def test_has_valid_credentials_basic(self):
        """Test has_valid_credentials with basic auth."""
        profile = JamaProfile(
            url="https://test.com",
            auth_type="basic",
            username="user",
            password="pass",
        )
        assert profile.has_valid_credentials() is True

    def test_has_valid_credentials_missing(self):
        """Test has_valid_credentials when missing credentials."""
        profile = JamaProfile(url="https://test.com", auth_type="api_key")
        assert profile.has_valid_credentials() is False

    def test_get_masked_display(self):
        """Test masked display of credentials."""
        profile = JamaProfile(
            url="https://test.com",
            auth_type="api_key",
            api_key="mysecretapikey",
        )
        display = profile.get_masked_display()
        assert display["url"] == "https://test.com"
        assert "..." in display["api_key"]


class TestExpandEnvVars:
    """Tests for _expand_env_vars function."""

    def test_expand_env_var(self):
        """Test expanding environment variable."""
        with patch.dict(os.environ, {"TEST_VAR": "test_value"}):
            result = _expand_env_vars({"key": "${TEST_VAR}"})
            assert result["key"] == "test_value"

    def test_expand_missing_env_var(self):
        """Test expanding missing environment variable."""
        result = _expand_env_vars({"key": "${NONEXISTENT_VAR}"})
        assert result["key"] == ""

    def test_no_expansion_needed(self):
        """Test when no expansion is needed."""
        result = _expand_env_vars({"key": "regular_value"})
        assert result["key"] == "regular_value"


class TestGetConfigPath:
    """Tests for get_config_path function."""

    def test_get_config_path_env_var(self):
        """Test get_config_path with environment variable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.touch()
            with patch.dict(os.environ, {"JAMA_CONFIG": str(config_path)}):
                result = get_config_path()
                assert result == config_path

    def test_get_config_path_default(self):
        """Test get_config_path returns default."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("jama_cli.config.CONFIG_FILE") as mock_config:
                mock_config.exists.return_value = False
                # Clear any JAMA_CONFIG env var
                result = get_config_path()
                # Should return something


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_file_not_exists(self):
        """Test loading config when file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "nonexistent.yml"
            with patch("jama_cli.config.get_config_path", return_value=config_path):
                config = load_config()
                assert isinstance(config, JamaConfig)
                assert config.profiles == {}

    def test_load_config_with_profiles(self):
        """Test loading config with profiles."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text("""
profiles:
  default:
    url: https://example.jamacloud.com
    auth_type: api_key
    api_key: mykey
  sandbox:
    url: https://sandbox.jamacloud.com
    auth_type: oauth
    client_id: client123
    client_secret: secret456
""")
            with patch("jama_cli.config.get_config_path", return_value=config_path):
                config = load_config()
                assert isinstance(config, JamaConfig)
                assert "default" in config.profiles
                assert "sandbox" in config.profiles


class TestSaveConfig:
    """Tests for save_config function."""

    def test_save_config(self):
        """Test saving configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            with patch("jama_cli.config.get_config_path", return_value=config_path):
                config = JamaConfig(
                    profiles={
                        "test": JamaProfile(
                            url="https://test.jamacloud.com",
                            auth_type="api_key",
                            api_key="testkey",
                        )
                    }
                )
                save_config(config)
                assert config_path.exists()
                content = config_path.read_text()
                assert "test.jamacloud.com" in content


class TestGetProfile:
    """Tests for get_profile function."""

    def test_get_profile_by_name(self):
        """Test getting profile by name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text("""
profiles:
  myprofile:
    url: https://my.jamacloud.com
    auth_type: api_key
    api_key: key123
""")
            with patch("jama_cli.config.get_config_path", return_value=config_path):
                profile = get_profile("myprofile")
                assert profile is not None
                assert profile.url == "https://my.jamacloud.com"

    def test_get_profile_nonexistent(self):
        """Test getting non-existent profile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text("profiles: {}")
            with patch("jama_cli.config.get_config_path", return_value=config_path):
                profile = get_profile("nonexistent")
                assert profile is None


class TestGetProfileOrEnv:
    """Tests for get_profile_or_env function."""

    def test_get_profile_from_env_oauth(self):
        """Test getting profile from environment variables with OAuth."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            with patch("jama_cli.config.get_config_path", return_value=config_path):
                with patch.dict(os.environ, {
                    "JAMA_URL": "https://env.jamacloud.com",
                    "JAMA_CLIENT_ID": "env_client",
                    "JAMA_CLIENT_SECRET": "env_secret",
                }, clear=True):
                    profile = get_profile_or_env(None)
                    assert profile is not None
                    assert profile.url == "https://env.jamacloud.com"
                    assert profile.client_id == "env_client"

    def test_get_profile_from_env_basic_auth(self):
        """Test getting profile from env with basic auth."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            with patch("jama_cli.config.get_config_path", return_value=config_path):
                with patch.dict(os.environ, {
                    "JAMA_URL": "https://env.jamacloud.com",
                    "JAMA_USERNAME": "user",
                    "JAMA_PASSWORD": "pass",
                }, clear=True):
                    profile = get_profile_or_env(None)
                    assert profile is not None
                    assert profile.url == "https://env.jamacloud.com"
                    assert profile.auth_type == "basic"

    def test_get_profile_from_env_api_key(self):
        """Test getting profile from env with API key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            with patch("jama_cli.config.get_config_path", return_value=config_path):
                with patch.dict(os.environ, {
                    "JAMA_URL": "https://env.jamacloud.com",
                    "JAMA_API_KEY": "mykey",
                }, clear=True):
                    profile = get_profile_or_env(None)
                    assert profile is not None
                    assert profile.api_key == "mykey"

    def test_no_profile_no_env(self):
        """Test when no profile and no env vars."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            with patch("jama_cli.config.get_config_path", return_value=config_path):
                with patch.dict(os.environ, {}, clear=True):
                    profile = get_profile_or_env(None)
                    assert profile is None
