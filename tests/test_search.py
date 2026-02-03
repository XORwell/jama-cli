"""Tests for the search module."""

import pytest

from jama_cli.commands.search import _get_nested_value, _search_items


class TestGetNestedValue:
    """Tests for _get_nested_value."""

    def test_top_level_field(self) -> None:
        """Test getting a top-level field."""
        item = {"id": 123, "documentKey": "REQ-001"}
        assert _get_nested_value(item, "id") == 123
        assert _get_nested_value(item, "documentKey") == "REQ-001"

    def test_fields_dict(self) -> None:
        """Test getting a field from the fields dict."""
        item = {"id": 123, "fields": {"name": "Test Item", "description": "A test"}}
        assert _get_nested_value(item, "name") == "Test Item"
        assert _get_nested_value(item, "description") == "A test"

    def test_dot_notation(self) -> None:
        """Test getting a nested field with dot notation."""
        item = {"location": {"parent": {"item": 456}}}
        assert _get_nested_value(item, "location.parent.item") == 456

    def test_missing_field(self) -> None:
        """Test getting a field that doesn't exist."""
        item = {"id": 123}
        assert _get_nested_value(item, "nonexistent") is None


class TestSearchItems:
    """Tests for _search_items."""

    @pytest.fixture
    def sample_items(self) -> list[dict]:
        """Sample items for testing."""
        return [
            {"id": 1, "fields": {"name": "Login Feature", "status": "Active"}},
            {"id": 2, "fields": {"name": "Logout Feature", "status": "Draft"}},
            {"id": 3, "fields": {"name": "User Profile", "status": "Active"}},
            {"id": 4, "documentKey": "REQ-001", "fields": {"name": "Requirement 1"}},
            {"id": 5, "documentKey": "REQ-002", "fields": {"name": "Requirement 2"}},
        ]

    def test_simple_search(self, sample_items: list[dict]) -> None:
        """Test simple text search."""
        matches = _search_items(sample_items, "Login", "name")
        assert len(matches) == 1
        assert matches[0]["id"] == 1

    def test_case_insensitive_search(self, sample_items: list[dict]) -> None:
        """Test case-insensitive search."""
        matches = _search_items(sample_items, "login", "name", case_sensitive=False)
        assert len(matches) == 1
        assert matches[0]["id"] == 1

    def test_case_sensitive_search(self, sample_items: list[dict]) -> None:
        """Test case-sensitive search."""
        matches = _search_items(sample_items, "login", "name", case_sensitive=True)
        assert len(matches) == 0  # "Login" != "login"

    def test_regex_search(self, sample_items: list[dict]) -> None:
        """Test regex search."""
        matches = _search_items(sample_items, "REQ-\\d+", "documentKey", regex=True)
        assert len(matches) == 2

    def test_partial_match(self, sample_items: list[dict]) -> None:
        """Test partial match search."""
        matches = _search_items(sample_items, "Feature", "name")
        assert len(matches) == 2  # Login Feature, Logout Feature

    def test_search_different_field(self, sample_items: list[dict]) -> None:
        """Test searching a different field."""
        matches = _search_items(sample_items, "Active", "status")
        assert len(matches) == 2

    def test_no_matches(self, sample_items: list[dict]) -> None:
        """Test search with no matches."""
        matches = _search_items(sample_items, "nonexistent", "name")
        assert len(matches) == 0
