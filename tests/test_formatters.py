"""Unit tests for output formatters."""

import json
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from jama_cli.output.formatters import (
    OutputFormat,
    format_output,
    format_single_item,
    _format_column_name,
    _format_cell_value,
)


class TestOutputFormat:
    """Tests for OutputFormat enum."""

    def test_output_format_values(self):
        """Test output format enum values."""
        assert OutputFormat.TABLE.value == "table"
        assert OutputFormat.JSON.value == "json"
        assert OutputFormat.CSV.value == "csv"
        assert OutputFormat.YAML.value == "yaml"

    def test_output_format_is_str(self):
        """Test OutputFormat inherits from str."""
        assert isinstance(OutputFormat.TABLE, str)
        assert OutputFormat.JSON == "json"


class TestFormatColumnName:
    """Tests for _format_column_name function."""

    def test_format_basic(self):
        """Test basic column name formatting."""
        assert _format_column_name("name") == "Name"
        assert _format_column_name("id") == "Id"

    def test_format_underscore(self):
        """Test column name with underscores."""
        assert _format_column_name("item_type") == "Item Type"
        assert _format_column_name("created_at") == "Created At"

    def test_format_already_titled(self):
        """Test already titled column name."""
        result = _format_column_name("Name")
        assert result == "Name"


class TestFormatCellValue:
    """Tests for _format_cell_value function."""

    def test_format_none(self):
        """Test formatting None value."""
        assert _format_cell_value(None) == ""

    def test_format_bool(self):
        """Test formatting boolean values."""
        assert _format_cell_value(True) == "Yes"
        assert _format_cell_value(False) == "No"

    def test_format_string(self):
        """Test formatting string value."""
        assert _format_cell_value("test") == "test"

    def test_format_int(self):
        """Test formatting integer value."""
        assert _format_cell_value(123) == "123"

    def test_format_dict_with_name(self):
        """Test formatting dict with name key."""
        assert _format_cell_value({"name": "Test"}) == "Test"

    def test_format_dict_with_id(self):
        """Test formatting dict with id key."""
        assert _format_cell_value({"id": 123}) == "[123]"

    def test_format_dict_empty(self):
        """Test formatting dict without name/id."""
        assert _format_cell_value({"other": "value"}) == "[...]"

    def test_format_list_empty(self):
        """Test formatting empty list."""
        assert _format_cell_value([]) == ""

    def test_format_list_small(self):
        """Test formatting small list."""
        assert _format_cell_value([1, 2, 3]) == "1, 2, 3"

    def test_format_list_large(self):
        """Test formatting large list."""
        assert _format_cell_value([1, 2, 3, 4, 5]) == "5 items"


class TestFormatOutput:
    """Tests for format_output function."""

    @patch("jama_cli.output.formatters.console")
    def test_format_output_empty(self, mock_console):
        """Test format_output with empty data."""
        format_output([])
        mock_console.print.assert_called()

    @patch("jama_cli.output.formatters.console")
    def test_format_output_table(self, mock_console):
        """Test format_output with table format."""
        data = [{"id": 1, "name": "Test"}]
        format_output(data, OutputFormat.TABLE)
        mock_console.print.assert_called()

    @patch("jama_cli.output.formatters.console")
    def test_format_output_json(self, mock_console):
        """Test format_output with JSON format."""
        data = [{"id": 1, "name": "Test"}]
        format_output(data, OutputFormat.JSON)
        mock_console.print_json.assert_called()

    @patch("jama_cli.output.formatters.console")
    def test_format_output_csv(self, mock_console):
        """Test format_output with CSV format."""
        data = [{"id": 1, "name": "Test"}]
        format_output(data, OutputFormat.CSV)
        mock_console.print.assert_called()

    @patch("jama_cli.output.formatters.console")
    def test_format_output_yaml(self, mock_console):
        """Test format_output with YAML format."""
        data = [{"id": 1, "name": "Test"}]
        format_output(data, OutputFormat.YAML)
        mock_console.print.assert_called()

    @patch("jama_cli.output.formatters.console")
    def test_format_output_dict(self, mock_console):
        """Test format_output with single dict (not list)."""
        data = {"id": 1, "name": "Test"}
        format_output(data, OutputFormat.JSON)
        mock_console.print_json.assert_called()


class TestFormatSingleItem:
    """Tests for format_single_item function."""

    @patch("jama_cli.output.formatters.console")
    def test_format_single_item_table(self, mock_console):
        """Test format_single_item with table format."""
        data = {"id": 1, "name": "Test"}
        format_single_item(data, OutputFormat.TABLE)
        mock_console.print.assert_called()

    @patch("jama_cli.output.formatters.console")
    def test_format_single_item_json(self, mock_console):
        """Test format_single_item with JSON format."""
        data = {"id": 1, "name": "Test"}
        format_single_item(data, OutputFormat.JSON)
        mock_console.print_json.assert_called()

    @patch("jama_cli.output.formatters.console")
    def test_format_single_item_with_title(self, mock_console):
        """Test format_single_item with title."""
        data = {"id": 1, "name": "Test"}
        format_single_item(data, OutputFormat.TABLE, title="Test Item")
        mock_console.print.assert_called()
