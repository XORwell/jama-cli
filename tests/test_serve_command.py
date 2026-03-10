"""Unit tests for serve command."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from jama_cli.commands.serve import _get_pid, _remove_pid, _write_pid, app

runner = CliRunner()


class TestServeCommand:
    """Tests for serve command."""

    def test_serve_help(self):
        """Test serve --help."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "serve" in result.stdout.lower() or "mcp" in result.stdout.lower()

    @patch("jama_cli.commands.serve.get_profile_or_env")
    def test_serve_no_profile(self, mock_get_profile):
        """Test serve without profile."""
        mock_get_profile.return_value = None
        result = runner.invoke(app, [])
        assert result.exit_code == 1

    @patch("jama_cli.commands.serve.get_profile_or_env")
    def test_serve_with_invalid_credentials(self, mock_get_profile):
        """Test serve with profile missing credentials."""
        mock_profile = MagicMock()
        mock_profile.has_valid_credentials.return_value = False
        mock_get_profile.return_value = mock_profile
        result = runner.invoke(app, [])
        assert result.exit_code == 1


class TestServeSubcommands:
    """Tests for serve subcommands."""

    def test_status_help(self):
        """Test serve status --help."""
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0

    def test_stop_help(self):
        """Test serve stop --help."""
        result = runner.invoke(app, ["stop", "--help"])
        assert result.exit_code == 0


class TestDaemonHelpers:
    """Tests for daemon helper functions."""

    @patch("jama_cli.commands.serve.PID_FILE")
    def test_get_pid_no_file(self, mock_pid_file):
        """Test _get_pid when no PID file exists."""
        mock_pid_file.exists.return_value = False
        assert _get_pid() is None

    @patch("jama_cli.commands.serve.RUNTIME_DIR")
    @patch("jama_cli.commands.serve.PID_FILE")
    def test_write_pid(self, mock_pid_file, mock_runtime_dir):
        """Test _write_pid function."""
        _write_pid(12345)
        mock_runtime_dir.mkdir.assert_called_once()
        mock_pid_file.write_text.assert_called_with("12345")

    @patch("jama_cli.commands.serve.PID_FILE")
    def test_remove_pid(self, mock_pid_file):
        """Test _remove_pid function."""
        _remove_pid()
        mock_pid_file.unlink.assert_called_with(missing_ok=True)


class TestServerModes:
    """Tests for different server modes."""

    def test_help_shows_options(self):
        """Test help shows stdio and daemon options."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "stdio" in result.stdout.lower() or "daemon" in result.stdout.lower()
