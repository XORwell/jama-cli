"""Tests for history command."""

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from jama_cli.commands.history import app, _format_value, _truncate, _get_change_type

runner = CliRunner()


class TestHistoryList:
    """Tests for history list command."""

    def test_list_help(self):
        """Test list --help."""
        result = runner.invoke(app, ["list", "--help"])
        assert result.exit_code == 0
        assert "list" in result.stdout.lower()

    @patch("jama_cli.commands.history.JamaClient")
    @patch("jama_cli.commands.history.get_profile_or_env")
    def test_list_versions(self, mock_get_profile, mock_client_class):
        """Test listing item versions."""
        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_item_versions.return_value = [
            {"version": 1, "type": "MINOR", "createdDate": "2024-01-01T10:00:00"},
            {"version": 2, "type": "MAJOR", "createdDate": "2024-01-02T11:00:00"},
            {"version": 3, "type": "MINOR", "createdDate": "2024-01-03T12:00:00"},
        ]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["list", "12345"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.history.get_profile_or_env")
    def test_list_no_profile(self, mock_get_profile):
        """Test list without profile."""
        mock_get_profile.return_value = None
        result = runner.invoke(app, ["list", "12345"])
        assert result.exit_code == 1


class TestHistoryGet:
    """Tests for history get command."""

    def test_get_help(self):
        """Test get --help."""
        result = runner.invoke(app, ["get", "--help"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.history.JamaClient")
    @patch("jama_cli.commands.history.get_profile_or_env")
    def test_get_version(self, mock_get_profile, mock_client_class):
        """Test getting a specific version."""
        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_item_version.return_value = {
            "version": 2,
            "versionedItem": {
                "id": 12345,
                "fields": {"name": "Test Item", "description": "Test description"},
            },
        }
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["get", "12345", "2"])
        assert result.exit_code == 0


class TestHistoryDiff:
    """Tests for history diff command."""

    def test_diff_help(self):
        """Test diff --help."""
        result = runner.invoke(app, ["diff", "--help"])
        assert result.exit_code == 0
        assert "diff" in result.stdout.lower()

    @patch("jama_cli.commands.history.JamaClient")
    @patch("jama_cli.commands.history.get_profile_or_env")
    def test_diff_versions(self, mock_get_profile, mock_client_class):
        """Test comparing versions."""
        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_item_version.side_effect = [
            {
                "version": 1,
                "versionedItem": {
                    "fields": {"name": "Original Name", "status": "Draft"},
                },
            },
            {
                "version": 2,
                "versionedItem": {
                    "fields": {"name": "Updated Name", "status": "Draft", "priority": "High"},
                },
            },
        ]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["diff", "12345", "1", "2"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.history.JamaClient")
    @patch("jama_cli.commands.history.get_profile_or_env")
    def test_diff_no_changes(self, mock_get_profile, mock_client_class):
        """Test comparing identical versions."""
        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        same_data = {
            "version": 1,
            "versionedItem": {"fields": {"name": "Same Name"}},
        }
        mock_client.get_item_version.side_effect = [same_data, same_data]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["diff", "12345", "1", "2"])
        assert result.exit_code == 0
        assert "no differences" in result.stdout.lower()


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_format_value_none(self):
        """Test formatting None value."""
        assert _format_value(None) == "(none)"

    def test_format_value_dict(self):
        """Test formatting dict value."""
        result = _format_value({"key": "value"})
        assert "key" in result
        assert "value" in result

    def test_format_value_list(self):
        """Test formatting list value."""
        result = _format_value([1, 2, 3])
        assert "1" in result

    def test_format_value_string(self):
        """Test formatting string value."""
        assert _format_value("test") == "test"

    def test_truncate_short(self):
        """Test truncating short text."""
        assert _truncate("short", 10) == "short"

    def test_truncate_long(self):
        """Test truncating long text."""
        result = _truncate("this is a very long string", 10)
        assert len(result) == 10
        assert result.endswith("...")

    def test_get_change_type_added(self):
        """Test detecting added field."""
        assert _get_change_type(None, "value") == "added"

    def test_get_change_type_removed(self):
        """Test detecting removed field."""
        assert _get_change_type("value", None) == "removed"

    def test_get_change_type_modified(self):
        """Test detecting modified field."""
        assert _get_change_type("old", "new") == "modified"
