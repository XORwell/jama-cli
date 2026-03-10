"""Tests for trace command."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from jama_cli.commands.trace import app

runner = CliRunner()


class TestTraceMatrix:
    """Tests for trace matrix command."""

    def test_matrix_help(self):
        """Test matrix --help."""
        result = runner.invoke(app, ["matrix", "--help"])
        assert result.exit_code == 0
        assert "matrix" in result.stdout.lower()

    @patch("jama_cli.commands.trace.JamaClient")
    @patch("jama_cli.commands.trace.get_profile_or_env")
    def test_matrix_basic(self, mock_get_profile, mock_client_class):
        """Test basic matrix generation."""
        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_items.return_value = [
            {"id": 1, "documentKey": "REQ-001", "itemType": 33, "fields": {"name": "Requirement 1"}},
            {"id": 2, "documentKey": "TC-001", "itemType": 45, "fields": {"name": "Test Case 1"}},
        ]
        mock_client.get_item_types.return_value = [
            {"id": 33, "display": "Requirement"},
            {"id": 45, "display": "Test Case"},
        ]
        mock_client.get_item_downstream_related.return_value = [
            {"id": 2, "documentKey": "TC-001", "itemType": 45, "fields": {"name": "Test Case 1"}},
        ]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["matrix", "1172"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.trace.get_profile_or_env")
    def test_matrix_no_profile(self, mock_get_profile):
        """Test matrix without profile."""
        mock_get_profile.return_value = None
        result = runner.invoke(app, ["matrix", "1172"])
        assert result.exit_code == 1


class TestTraceCoverage:
    """Tests for trace coverage command."""

    def test_coverage_help(self):
        """Test coverage --help."""
        result = runner.invoke(app, ["coverage", "--help"])
        assert result.exit_code == 0
        assert "coverage" in result.stdout.lower()

    @patch("jama_cli.commands.trace.JamaClient")
    @patch("jama_cli.commands.trace.get_profile_or_env")
    def test_coverage_basic(self, mock_get_profile, mock_client_class):
        """Test basic coverage analysis."""
        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_items.return_value = [
            {"id": 1, "itemType": 33, "fields": {"name": "Item 1"}},
        ]
        mock_client.get_item_types.return_value = [{"id": 33, "display": "Requirement"}]
        mock_client.get_item_upstream_related.return_value = []
        mock_client.get_item_downstream_related.return_value = []
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["coverage", "1172"])
        assert result.exit_code == 0


class TestTraceTree:
    """Tests for trace tree command."""

    def test_tree_help(self):
        """Test tree --help."""
        result = runner.invoke(app, ["tree", "--help"])
        assert result.exit_code == 0
        assert "tree" in result.stdout.lower()

    @patch("jama_cli.commands.trace.JamaClient")
    @patch("jama_cli.commands.trace.get_profile_or_env")
    def test_tree_basic(self, mock_get_profile, mock_client_class):
        """Test basic trace tree."""
        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_item.return_value = {
            "id": 1, "documentKey": "REQ-001", "itemType": 33, "fields": {"name": "Requirement 1"}
        }
        mock_client.get_item_types.return_value = [{"id": 33, "display": "Requirement"}]
        mock_client.get_item_upstream_related.return_value = []
        mock_client.get_item_downstream_related.return_value = []
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["tree", "12345"])
        assert result.exit_code == 0
