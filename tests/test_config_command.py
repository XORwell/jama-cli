"""Unit tests for config CLI command."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from jama_cli.commands.config_cmd import app

runner = CliRunner()


class TestConfigListCommand:
    """Tests for config list command."""

    def test_list_help(self):
        """Test list --help."""
        result = runner.invoke(app, ["list", "--help"])
        assert result.exit_code == 0

    def test_list_with_profiles(self):
        """Test listing profiles."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text(
                """
profiles:
  default:
    url: https://default.jamacloud.com
    auth_type: api_key
    api_key: key123
  sandbox:
    url: https://sandbox.jamacloud.com
    auth_type: oauth
    client_id: client123
    client_secret: secret456
"""
            )
            with patch("jama_cli.config.get_config_path", return_value=config_path):
                result = runner.invoke(app, ["list"])
                assert result.exit_code == 0


class TestConfigAddCommand:
    """Tests for config add command."""

    def test_add_help(self):
        """Test add --help."""
        result = runner.invoke(app, ["add", "--help"])
        assert result.exit_code == 0
        assert "add" in result.stdout.lower()

    def test_add_profile_api_key(self):
        """Test adding a profile with API key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            with patch("jama_cli.config.get_config_path", return_value=config_path):
                result = runner.invoke(
                    app,
                    [
                        "add",
                        "testprofile",
                        "-u",
                        "https://test.jamacloud.com",
                        "--api-key",
                        "myapikey",
                    ],
                )
                assert result.exit_code == 0


class TestConfigRemoveCommand:
    """Tests for config remove command."""

    def test_remove_help(self):
        """Test remove --help."""
        result = runner.invoke(app, ["remove", "--help"])
        assert result.exit_code == 0

    def test_remove_profile(self):
        """Test removing a profile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text(
                """
profiles:
  toremove:
    url: https://remove.jamacloud.com
    auth_type: api_key
    api_key: key123
"""
            )
            with patch("jama_cli.config.get_config_path", return_value=config_path):
                result = runner.invoke(app, ["remove", "toremove"])
                assert result.exit_code == 0

    def test_remove_nonexistent_profile(self):
        """Test removing a non-existent profile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text("profiles: {}")
            with patch("jama_cli.config.get_config_path", return_value=config_path):
                result = runner.invoke(app, ["remove", "nonexistent"])
                # Should fail or warn
                assert "not found" in result.stdout.lower() or result.exit_code != 0


class TestConfigShowCommand:
    """Tests for config show command."""

    def test_show_help(self):
        """Test show --help."""
        result = runner.invoke(app, ["show", "--help"])
        assert result.exit_code == 0

    def test_show_profile(self):
        """Test showing a profile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text(
                """
profiles:
  showme:
    url: https://show.jamacloud.com
    auth_type: api_key
    api_key: key123
"""
            )
            with patch("jama_cli.config.get_config_path", return_value=config_path):
                result = runner.invoke(app, ["show", "showme"])
                assert result.exit_code == 0
                assert "show.jamacloud.com" in result.stdout

    def test_show_nonexistent_profile(self):
        """Test showing a non-existent profile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text("profiles: {}")
            with patch("jama_cli.config.get_config_path", return_value=config_path):
                result = runner.invoke(app, ["show", "nonexistent"])
                assert "not found" in result.stdout.lower() or result.exit_code != 0


class TestConfigSetDefaultCommand:
    """Tests for config set-default command."""

    def test_set_default_help(self):
        """Test set-default --help."""
        result = runner.invoke(app, ["set-default", "--help"])
        assert result.exit_code == 0


class TestConfigCacheCommand:
    """Tests for config cache command."""

    def test_cache_help(self):
        """Test cache --help."""
        result = runner.invoke(app, ["cache", "--help"])
        assert result.exit_code == 0


class TestConfigPathCommand:
    """Tests for config path command."""

    def test_path_help(self):
        """Test path --help."""
        result = runner.invoke(app, ["path", "--help"])
        assert result.exit_code == 0

    def test_path_shows_path(self):
        """Test path command shows config path."""
        result = runner.invoke(app, ["path"])
        assert result.exit_code == 0
        # Should contain some path information
        assert "/" in result.stdout or "\\" in result.stdout
