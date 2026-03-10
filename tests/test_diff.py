"""Tests for the diff module."""

from jama_cli.commands.diff import (
    _build_item_map,
    _calculate_diff,
    _get_field_value,
    _get_item_key,
)


class TestGetItemKey:
    """Tests for _get_item_key."""

    def test_top_level_key(self) -> None:
        """Test getting key from top-level field."""
        item = {"documentKey": "REQ-001", "id": 123}
        assert _get_item_key(item, "documentKey") == "REQ-001"
        assert _get_item_key(item, "id") == "123"

    def test_fields_key(self) -> None:
        """Test getting key from fields dict."""
        item = {"id": 123, "fields": {"name": "Test Item"}}
        assert _get_item_key(item, "name") == "Test Item"

    def test_missing_key(self) -> None:
        """Test missing key returns None."""
        item = {"id": 123}
        assert _get_item_key(item, "nonexistent") is None


class TestGetFieldValue:
    """Tests for _get_field_value."""

    def test_top_level_value(self) -> None:
        """Test getting value from top-level."""
        item = {"id": 123, "status": "Active"}
        assert _get_field_value(item, "id") == 123
        assert _get_field_value(item, "status") == "Active"

    def test_fields_value(self) -> None:
        """Test getting value from fields dict."""
        item = {"fields": {"name": "Test", "description": "A test item"}}
        assert _get_field_value(item, "name") == "Test"
        assert _get_field_value(item, "description") == "A test item"


class TestBuildItemMap:
    """Tests for _build_item_map."""

    def test_builds_map(self) -> None:
        """Test building a map by key field."""
        items = [
            {"documentKey": "REQ-001", "fields": {"name": "Item 1"}},
            {"documentKey": "REQ-002", "fields": {"name": "Item 2"}},
        ]
        item_map = _build_item_map(items, "documentKey")

        assert len(item_map) == 2
        assert "REQ-001" in item_map
        assert "REQ-002" in item_map
        assert item_map["REQ-001"]["fields"]["name"] == "Item 1"

    def test_skips_items_without_key(self) -> None:
        """Test that items without the key field are skipped."""
        items = [
            {"documentKey": "REQ-001", "fields": {"name": "Item 1"}},
            {"fields": {"name": "Item 2"}},  # No documentKey
        ]
        item_map = _build_item_map(items, "documentKey")

        assert len(item_map) == 1
        assert "REQ-001" in item_map


class TestCalculateDiff:
    """Tests for _calculate_diff."""

    def test_only_in_source(self) -> None:
        """Test items only in source."""
        source_map = {
            "REQ-001": {"fields": {"name": "Item 1"}},
            "REQ-002": {"fields": {"name": "Item 2"}},
        }
        target_map = {
            "REQ-001": {"fields": {"name": "Item 1"}},
        }

        result = _calculate_diff(source_map, target_map, ["name"])

        assert len(result["only_in_source"]) == 1
        assert result["only_in_source"][0]["key"] == "REQ-002"

    def test_only_in_target(self) -> None:
        """Test items only in target."""
        source_map = {
            "REQ-001": {"fields": {"name": "Item 1"}},
        }
        target_map = {
            "REQ-001": {"fields": {"name": "Item 1"}},
            "REQ-003": {"fields": {"name": "Item 3"}},
        }

        result = _calculate_diff(source_map, target_map, ["name"])

        assert len(result["only_in_target"]) == 1
        assert result["only_in_target"][0]["key"] == "REQ-003"

    def test_modified_items(self) -> None:
        """Test items that differ."""
        source_map = {
            "REQ-001": {"fields": {"name": "Old Name", "status": "Draft"}},
        }
        target_map = {
            "REQ-001": {"fields": {"name": "New Name", "status": "Draft"}},
        }

        result = _calculate_diff(source_map, target_map, ["name", "status"])

        assert len(result["modified"]) == 1
        assert result["modified"][0]["key"] == "REQ-001"
        assert len(result["modified"][0]["differences"]) == 1
        assert result["modified"][0]["differences"][0]["field"] == "name"

    def test_unchanged_items(self) -> None:
        """Test items that are the same."""
        source_map = {
            "REQ-001": {"fields": {"name": "Same Name", "status": "Active"}},
        }
        target_map = {
            "REQ-001": {"fields": {"name": "Same Name", "status": "Active"}},
        }

        result = _calculate_diff(source_map, target_map, ["name", "status"])

        assert len(result["unchanged"]) == 1
        assert result["unchanged"][0]["key"] == "REQ-001"

    def test_comprehensive_diff(self) -> None:
        """Test a comprehensive diff scenario."""
        source_map = {
            "A": {"fields": {"name": "Item A", "status": "Active"}},
            "B": {"fields": {"name": "Item B", "status": "Draft"}},
            "C": {"fields": {"name": "Item C", "status": "Active"}},
        }
        target_map = {
            "A": {"fields": {"name": "Item A", "status": "Active"}},  # Unchanged
            "B": {"fields": {"name": "Item B Modified", "status": "Draft"}},  # Modified
            "D": {"fields": {"name": "Item D", "status": "New"}},  # Only in target
        }

        result = _calculate_diff(source_map, target_map, ["name", "status"])

        assert len(result["only_in_source"]) == 1  # C
        assert len(result["only_in_target"]) == 1  # D
        assert len(result["modified"]) == 1  # B
        assert len(result["unchanged"]) == 1  # A
