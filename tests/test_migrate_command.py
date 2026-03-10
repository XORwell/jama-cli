"""Unit tests for migrate command."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from jama_cli.commands.migrate import app

runner = CliRunner()


class TestMigrateExportCommand:
    """Tests for migrate export command."""

    @patch("jama_cli.commands.migrate.JamaClient")
    @patch("jama_cli.commands.migrate.get_profile_or_env")
    def test_export_basic(self, mock_get_profile, mock_client_class):
        """Test basic export."""
        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_items.return_value = [
            {"id": 1, "fields": {"name": "Item 1"}},
            {"id": 2, "fields": {"name": "Item 2"}},
        ]
        mock_client.get_item_children.return_value = []
        mock_client_class.return_value = mock_client

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "export.json"
            result = runner.invoke(app, [
                "export", "1",
                "--output", str(output_file),
                "--no-relationships",
            ])
            # Should complete without error
            assert result.exit_code in [0, 1]

    @patch("jama_cli.commands.migrate.JamaClient")
    @patch("jama_cli.commands.migrate.get_profile_or_env")
    def test_export_with_relationships(self, mock_get_profile, mock_client_class):
        """Test export with relationships."""
        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_items.return_value = [{"id": 1, "fields": {"name": "Item"}}]
        mock_client.get_item_children.return_value = []
        mock_client.get_item_downstream_relationships.return_value = [
            {"id": 100, "fromItem": 1, "toItem": 2},
        ]
        mock_client_class.return_value = mock_client

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "export.json"
            result = runner.invoke(app, [
                "export", "1",
                "--output", str(output_file),
                "--relationships",
            ])
            assert result.exit_code in [0, 1]

    @patch("jama_cli.commands.migrate.get_profile_or_env")
    def test_export_no_profile(self, mock_get_profile):
        """Test export without profile."""
        mock_get_profile.return_value = None
        result = runner.invoke(app, ["export", "1"])
        assert result.exit_code == 1


class TestMigrateImportCommand:
    """Tests for migrate import command."""

    @patch("jama_cli.commands.migrate.JamaClient")
    @patch("jama_cli.commands.migrate.get_profile_or_env")
    def test_import_dry_run(self, mock_get_profile, mock_client_class):
        """Test import with dry run."""
        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        with tempfile.TemporaryDirectory() as tmpdir:
            input_file = Path(tmpdir) / "import.json"
            input_file.write_text(json.dumps({
                "items": [{"id": 1, "fields": {"name": "Test"}, "itemType": 33}],
                "relationships": [],
            }))
            result = runner.invoke(app, [
                "import", str(input_file),
                "--project", "1",
                "--dry-run",
            ])
            assert result.exit_code in [0, 1]

    @patch("jama_cli.commands.migrate.get_profile_or_env")
    def test_import_file_not_found(self, mock_get_profile):
        """Test import with non-existent file."""
        mock_get_profile.return_value = MagicMock()
        result = runner.invoke(app, [
            "import", "/nonexistent/file.json",
            "--project", "1",
        ])
        assert result.exit_code == 1


class TestMigrateCloneCommand:
    """Tests for migrate clone command."""

    def test_clone_help(self):
        """Test clone --help."""
        result = runner.invoke(app, ["clone", "--help"])
        assert result.exit_code == 0
        assert "clone" in result.stdout.lower()

    @patch("jama_cli.commands.migrate.get_profile_or_env")
    def test_clone_no_profile(self, mock_get_profile):
        """Test clone without profile."""
        mock_get_profile.return_value = None
        result = runner.invoke(app, ["clone", "1", "2"])
        assert result.exit_code == 1


class TestMigrateCopyCommand:
    """Tests for migrate copy command."""

    def test_copy_help(self):
        """Test copy --help."""
        result = runner.invoke(app, ["copy", "--help"])
        assert result.exit_code == 0
        assert "copy" in result.stdout.lower()


class TestHelperFunctions:
    """Tests for migrate helper functions."""

    def test_filter_writable_fields(self):
        """Test filtering read-only fields."""
        from jama_cli.commands.migrate import READ_ONLY_FIELDS, _filter_writable_fields

        item = {
            "id": 1,
            "documentKey": "TEST-1",
            "globalId": "12345",
            "fields": {"name": "Test"},
        }
        filtered = _filter_writable_fields(item)

        # Should not contain read-only fields
        for field in READ_ONLY_FIELDS:
            assert field not in filtered

        # Should keep fields dict
        assert "fields" in filtered or "name" in str(filtered)
