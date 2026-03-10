"""Tests for baseline command."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from jama_cli.commands.baseline import app

runner = CliRunner()


class TestBaselineList:
    """Tests for baseline list command."""

    def test_list_help(self):
        """Test list --help."""
        result = runner.invoke(app, ["list", "--help"])
        assert result.exit_code == 0
        assert "list" in result.stdout.lower()

    @patch("jama_cli.commands.baseline.JamaClient")
    @patch("jama_cli.commands.baseline.get_profile_or_env")
    def test_list_baselines(self, mock_get_profile, mock_client_class):
        """Test listing baselines."""
        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_baselines.return_value = [
            {"id": 1, "name": "Baseline 1", "description": "First baseline", "createdDate": "2024-01-01T00:00:00"},
            {"id": 2, "name": "Baseline 2", "description": "Second baseline", "createdDate": "2024-01-02T00:00:00"},
        ]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["list", "1172"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.baseline.get_profile_or_env")
    def test_list_no_profile(self, mock_get_profile):
        """Test list without profile."""
        mock_get_profile.return_value = None
        result = runner.invoke(app, ["list", "1172"])
        assert result.exit_code == 1


class TestBaselineGet:
    """Tests for baseline get command."""

    def test_get_help(self):
        """Test get --help."""
        result = runner.invoke(app, ["get", "--help"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.baseline.JamaClient")
    @patch("jama_cli.commands.baseline.get_profile_or_env")
    def test_get_baseline(self, mock_get_profile, mock_client_class):
        """Test getting a baseline."""
        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_baseline.return_value = {
            "id": 1, "name": "Baseline 1", "description": "Test baseline"
        }
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["get", "100"])
        assert result.exit_code == 0


class TestBaselineItems:
    """Tests for baseline items command."""

    def test_items_help(self):
        """Test items --help."""
        result = runner.invoke(app, ["items", "--help"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.baseline.JamaClient")
    @patch("jama_cli.commands.baseline.get_profile_or_env")
    def test_items_in_baseline(self, mock_get_profile, mock_client_class):
        """Test listing items in a baseline."""
        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_baseline_versioned_items.return_value = [
            {"id": 1, "documentKey": "REQ-001", "version": 1, "fields": {"name": "Item 1"}},
            {"id": 2, "documentKey": "REQ-002", "version": 2, "fields": {"name": "Item 2"}},
        ]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["items", "100"])
        assert result.exit_code == 0


class TestBaselineDiff:
    """Tests for baseline diff command."""

    def test_diff_help(self):
        """Test diff --help."""
        result = runner.invoke(app, ["diff", "--help"])
        assert result.exit_code == 0
        assert "diff" in result.stdout.lower()

    @patch("jama_cli.commands.baseline.JamaClient")
    @patch("jama_cli.commands.baseline.get_profile_or_env")
    def test_diff_baselines(self, mock_get_profile, mock_client_class):
        """Test comparing baselines."""
        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_baseline.side_effect = [
            {"id": 100, "name": "Baseline 1"},
            {"id": 101, "name": "Baseline 2"},
        ]
        mock_client.get_baseline_versioned_items.side_effect = [
            # Baseline 1 items
            [
                {"id": 1, "documentKey": "REQ-001", "version": 1, "fields": {"name": "Item 1"}},
                {"id": 2, "documentKey": "REQ-002", "version": 1, "fields": {"name": "Item 2"}},
            ],
            # Baseline 2 items (one modified, one removed, one added)
            [
                {"id": 1, "documentKey": "REQ-001", "version": 2, "fields": {"name": "Item 1 Updated"}},
                {"id": 3, "documentKey": "REQ-003", "version": 1, "fields": {"name": "Item 3 New"}},
            ],
        ]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["diff", "100", "101"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.baseline.JamaClient")
    @patch("jama_cli.commands.baseline.get_profile_or_env")
    def test_diff_identical_baselines(self, mock_get_profile, mock_client_class):
        """Test comparing identical baselines."""
        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_baseline.side_effect = [
            {"id": 100, "name": "Baseline 1"},
            {"id": 101, "name": "Baseline 2"},
        ]
        items = [{"id": 1, "documentKey": "REQ-001", "version": 1, "fields": {"name": "Item 1"}}]
        mock_client.get_baseline_versioned_items.side_effect = [items, items]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["diff", "100", "101"])
        assert result.exit_code == 0
        assert "identical" in result.stdout.lower()
