"""Unit tests for main CLI application."""

from typer.testing import CliRunner

from jama_cli.main import app

runner = CliRunner()


class TestMainApp:
    """Tests for main CLI application."""

    def test_help(self):
        """Test main --help."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "jama" in result.stdout.lower() or "cli" in result.stdout.lower()

    def test_version(self):
        """Test --version flag."""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0

    def test_projects_subcommand(self):
        """Test projects subcommand exists."""
        result = runner.invoke(app, ["projects", "--help"])
        assert result.exit_code == 0
        assert "list" in result.stdout.lower() or "get" in result.stdout.lower()

    def test_items_subcommand(self):
        """Test items subcommand exists."""
        result = runner.invoke(app, ["items", "--help"])
        assert result.exit_code == 0

    def test_types_subcommand(self):
        """Test types subcommand exists."""
        result = runner.invoke(app, ["types", "--help"])
        assert result.exit_code == 0

    def test_relationships_subcommand(self):
        """Test relationships subcommand exists."""
        result = runner.invoke(app, ["relationships", "--help"])
        assert result.exit_code == 0

    def test_config_subcommand(self):
        """Test config subcommand exists."""
        result = runner.invoke(app, ["config", "--help"])
        assert result.exit_code == 0

    def test_serve_subcommand(self):
        """Test serve subcommand exists."""
        result = runner.invoke(app, ["serve", "--help"])
        assert result.exit_code == 0

    def test_search_subcommand(self):
        """Test search subcommand exists."""
        result = runner.invoke(app, ["search", "--help"])
        assert result.exit_code == 0

    def test_diff_subcommand(self):
        """Test diff subcommand exists."""
        result = runner.invoke(app, ["diff", "--help"])
        assert result.exit_code == 0

    def test_migrate_subcommand(self):
        """Test migrate subcommand exists."""
        result = runner.invoke(app, ["migrate", "--help"])
        assert result.exit_code == 0

    def test_tags_subcommand(self):
        """Test tags subcommand exists."""
        result = runner.invoke(app, ["tags", "--help"])
        assert result.exit_code == 0

    def test_users_subcommand(self):
        """Test users subcommand exists."""
        result = runner.invoke(app, ["users", "--help"])
        assert result.exit_code == 0

    def test_picklists_subcommand(self):
        """Test picklists subcommand exists."""
        result = runner.invoke(app, ["picklists", "--help"])
        assert result.exit_code == 0

    def test_tests_subcommand(self):
        """Test tests subcommand exists."""
        result = runner.invoke(app, ["tests", "--help"])
        assert result.exit_code == 0

    def test_attachments_subcommand(self):
        """Test attachments subcommand exists."""
        result = runner.invoke(app, ["attachments", "--help"])
        assert result.exit_code == 0


class TestGlobalOptions:
    """Tests for global options."""

    def test_profile_option(self):
        """Test --profile option."""
        result = runner.invoke(app, ["--help"])
        assert "profile" in result.stdout.lower()

    def test_output_format_option(self):
        """Test output format is available."""
        result = runner.invoke(app, ["projects", "--help"])
        assert result.exit_code == 0


class TestInvalidCommands:
    """Tests for invalid command handling."""

    def test_invalid_subcommand(self):
        """Test invalid subcommand."""
        result = runner.invoke(app, ["invalid_command"])
        assert result.exit_code != 0

    def test_missing_required_args(self):
        """Test missing required arguments."""
        result = runner.invoke(app, ["items", "get"])
        assert result.exit_code != 0
