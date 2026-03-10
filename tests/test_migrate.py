"""Tests for the migration module."""

import json
import tempfile
from pathlib import Path

from jama_cli.commands.migrate import (
    ExportData,
    ExportMetadata,
    _sort_by_hierarchy,
)


class TestExportMetadata:
    """Tests for ExportMetadata."""

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        metadata = ExportMetadata(
            source_url="https://test.jamacloud.com",
            source_project=123,
            export_date="2024-01-01T00:00:00",
            item_count=10,
            relationship_count=5,
            attachment_count=3,
        )

        result = metadata.to_dict()

        assert result["source_url"] == "https://test.jamacloud.com"
        assert result["source_project"] == 123
        assert result["export_date"] == "2024-01-01T00:00:00"
        assert result["item_count"] == 10
        assert result["relationship_count"] == 5
        assert result["attachment_count"] == 3
        assert result["version"] == "1.1"


class TestExportData:
    """Tests for ExportData."""

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        metadata = ExportMetadata(
            source_url="https://test.jamacloud.com",
            source_project=123,
            export_date="2024-01-01T00:00:00",
        )
        export_data = ExportData(metadata)
        export_data.items = [{"id": 1, "fields": {"name": "Test"}}]
        export_data.relationships = [{"id": 10, "fromItem": 1, "toItem": 2}]
        export_data.hierarchy = {1: [2, 3]}

        result = export_data.to_dict()

        assert "metadata" in result
        assert result["items"] == [{"id": 1, "fields": {"name": "Test"}}]
        assert result["relationships"] == [{"id": 10, "fromItem": 1, "toItem": 2}]
        assert result["hierarchy"] == {"1": [2, 3]}  # Keys converted to strings

    def test_from_dict(self) -> None:
        """Test loading from dictionary."""
        data = {
            "metadata": {
                "source_url": "https://test.jamacloud.com",
                "source_project": 123,
                "export_date": "2024-01-01T00:00:00",
                "version": "1.0",
                "item_count": 2,
                "relationship_count": 1,
            },
            "items": [
                {"id": 1, "fields": {"name": "Item 1"}},
                {"id": 2, "fields": {"name": "Item 2"}},
            ],
            "relationships": [{"id": 10, "fromItem": 1, "toItem": 2}],
            "hierarchy": {"1": [2]},
            "item_types": [{"id": 45, "name": "Requirement"}],
        }

        export_data = ExportData.from_dict(data)

        assert export_data.metadata.source_url == "https://test.jamacloud.com"
        assert export_data.metadata.source_project == 123
        assert export_data.metadata.item_count == 2
        assert len(export_data.items) == 2
        assert len(export_data.relationships) == 1
        assert export_data.hierarchy == {1: [2]}  # Keys converted to ints
        assert len(export_data.item_types) == 1

    def test_roundtrip(self) -> None:
        """Test that data survives a to_dict/from_dict roundtrip."""
        metadata = ExportMetadata(
            source_url="https://test.jamacloud.com",
            source_project=123,
            export_date="2024-01-01T00:00:00",
            item_count=2,
        )
        original = ExportData(metadata)
        original.items = [{"id": 1}, {"id": 2}]
        original.hierarchy = {1: [2]}

        # Roundtrip
        data = original.to_dict()
        restored = ExportData.from_dict(data)

        assert restored.metadata.source_url == original.metadata.source_url
        assert restored.metadata.source_project == original.metadata.source_project
        assert len(restored.items) == len(original.items)
        assert restored.hierarchy == original.hierarchy


class TestSortByHierarchy:
    """Tests for _sort_by_hierarchy."""

    def test_sorts_parents_first(self) -> None:
        """Test that parents come before children."""
        items = [
            {"id": 3, "name": "Child"},
            {"id": 1, "name": "Root"},
            {"id": 2, "name": "Parent"},
        ]
        hierarchy = {
            1: [2],  # 1 is parent of 2
            2: [3],  # 2 is parent of 3
        }

        sorted_items = _sort_by_hierarchy(items, hierarchy)

        # Root should come first, then Parent, then Child
        ids = [item["id"] for item in sorted_items]
        assert ids.index(1) < ids.index(2)
        assert ids.index(2) < ids.index(3)

    def test_handles_empty_hierarchy(self) -> None:
        """Test with no hierarchy."""
        items = [{"id": 1}, {"id": 2}, {"id": 3}]
        hierarchy: dict[int, list[int]] = {}

        sorted_items = _sort_by_hierarchy(items, hierarchy)

        # Should return items unchanged (all at same level)
        assert len(sorted_items) == 3

    def test_handles_flat_list(self) -> None:
        """Test with all items at same level."""
        items = [{"id": 1}, {"id": 2}, {"id": 3}]
        hierarchy = {0: [1, 2, 3]}  # All children of non-existent parent

        sorted_items = _sort_by_hierarchy(items, hierarchy)

        assert len(sorted_items) == 3


class TestExportFile:
    """Tests for export file operations."""

    def test_write_and_read_export_file(self) -> None:
        """Test writing and reading an export file."""
        metadata = ExportMetadata(
            source_url="https://test.jamacloud.com",
            source_project=123,
            export_date="2024-01-01T00:00:00",
            item_count=1,
        )
        export_data = ExportData(metadata)
        export_data.items = [{"id": 1, "fields": {"name": "Test Item"}}]
        export_data.item_types = [{"id": 45, "name": "Requirement"}]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(export_data.to_dict(), f)
            temp_path = Path(f.name)

        try:
            # Read back
            with open(temp_path) as f:
                loaded_data = json.load(f)

            restored = ExportData.from_dict(loaded_data)

            assert restored.metadata.source_url == "https://test.jamacloud.com"
            assert len(restored.items) == 1
            assert restored.items[0]["fields"]["name"] == "Test Item"
        finally:
            temp_path.unlink()
