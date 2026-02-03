"""Unit tests for CLI commands with mocked JamaClient."""

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

runner = CliRunner()


# ==================== Projects Command Tests ====================
class TestProjectsCommand:
    """Tests for projects command."""

    @patch("jama_cli.commands.projects.JamaClient")
    @patch("jama_cli.commands.projects.get_profile_or_env")
    def test_list_projects(self, mock_get_profile, mock_client_class):
        """Test listing projects."""
        from jama_cli.commands.projects import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_projects.return_value = [
            {"id": 1, "name": "Project 1", "projectKey": "P1"},
            {"id": 2, "name": "Project 2", "projectKey": "P2"},
        ]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        mock_client.get_projects.assert_called_once()

    @patch("jama_cli.commands.projects.JamaClient")
    @patch("jama_cli.commands.projects.get_profile_or_env")
    def test_get_project(self, mock_get_profile, mock_client_class):
        """Test getting a specific project."""
        from jama_cli.commands.projects import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_project.return_value = {"id": 1, "name": "Test Project"}
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["get", "1"])
        assert result.exit_code == 0
        mock_client.get_project.assert_called_once_with(1)

    @patch("jama_cli.commands.projects.get_profile_or_env")
    def test_list_projects_no_profile(self, mock_get_profile):
        """Test listing projects without profile."""
        from jama_cli.commands.projects import app

        mock_get_profile.return_value = None

        result = runner.invoke(app, ["list"])
        assert result.exit_code == 1


# ==================== Items Command Tests ====================
class TestItemsCommand:
    """Tests for items command."""

    @patch("jama_cli.commands.items.JamaClient")
    @patch("jama_cli.commands.items.get_profile_or_env")
    def test_list_items(self, mock_get_profile, mock_client_class):
        """Test listing items."""
        from jama_cli.commands.items import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_items.return_value = [
            {"id": 1, "documentKey": "TEST-1", "fields": {"name": "Item 1"}},
        ]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["list", "1"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.items.JamaClient")
    @patch("jama_cli.commands.items.get_profile_or_env")
    def test_get_item(self, mock_get_profile, mock_client_class):
        """Test getting a specific item."""
        from jama_cli.commands.items import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_item.return_value = {"id": 1, "fields": {"name": "Test"}}
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["get", "1"])
        assert result.exit_code == 0
        mock_client.get_item.assert_called_once_with(1)

    @patch("jama_cli.commands.items.JamaClient")
    @patch("jama_cli.commands.items.get_profile_or_env")
    def test_create_item(self, mock_get_profile, mock_client_class):
        """Test creating an item."""
        from jama_cli.commands.items import app

        mock_profile = MagicMock()
        mock_profile.has_valid_credentials.return_value = True
        mock_get_profile.return_value = mock_profile
        mock_client = MagicMock()
        mock_client.create_item.return_value = 123
        mock_client_class.return_value = mock_client

        # Use correct option names: -t for type, -n for name
        result = runner.invoke(
            app, ["create", "1", "-n", "New Item", "-t", "33"]
        )
        assert result.exit_code == 0

    @patch("jama_cli.commands.items.JamaClient")
    @patch("jama_cli.commands.items.get_profile_or_env")
    def test_update_item(self, mock_get_profile, mock_client_class):
        """Test updating an item."""
        from jama_cli.commands.items import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["update", "1", "--name", "Updated Name"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.items.JamaClient")
    @patch("jama_cli.commands.items.get_profile_or_env")
    def test_delete_item(self, mock_get_profile, mock_client_class):
        """Test deleting an item."""
        from jama_cli.commands.items import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["delete", "1", "--force"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.items.JamaClient")
    @patch("jama_cli.commands.items.get_profile_or_env")
    def test_children_item(self, mock_get_profile, mock_client_class):
        """Test getting item children."""
        from jama_cli.commands.items import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_item_children.return_value = [{"id": 2, "fields": {"name": "Child"}}]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["children", "1"])
        assert result.exit_code == 0


# ==================== Types Command Tests ====================
class TestTypesCommand:
    """Tests for types command."""

    @patch("jama_cli.commands.types.JamaClient")
    @patch("jama_cli.commands.types.get_profile_or_env")
    def test_list_types(self, mock_get_profile, mock_client_class):
        """Test listing item types."""
        from jama_cli.commands.types import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_item_types.return_value = [
            {"id": 1, "display": "Requirement", "typeKey": "REQ"},
        ]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.types.JamaClient")
    @patch("jama_cli.commands.types.get_profile_or_env")
    def test_get_type(self, mock_get_profile, mock_client_class):
        """Test getting a specific item type."""
        from jama_cli.commands.types import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_item_type.return_value = {"id": 1, "display": "Requirement"}
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["get", "1"])
        assert result.exit_code == 0


# ==================== Relationships Command Tests ====================
class TestRelationshipsCommand:
    """Tests for relationships command."""

    @patch("jama_cli.commands.relationships.JamaClient")
    @patch("jama_cli.commands.relationships.get_profile_or_env")
    def test_list_upstream(self, mock_get_profile, mock_client_class):
        """Test listing upstream relationships."""
        from jama_cli.commands.relationships import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_item_upstream_relationships.return_value = [
            {"id": 1, "fromItem": 10, "toItem": 20},
        ]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["upstream", "1"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.relationships.JamaClient")
    @patch("jama_cli.commands.relationships.get_profile_or_env")
    def test_list_downstream(self, mock_get_profile, mock_client_class):
        """Test listing downstream relationships."""
        from jama_cli.commands.relationships import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_item_downstream_relationships.return_value = [
            {"id": 1, "fromItem": 10, "toItem": 20},
        ]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["downstream", "1"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.relationships.JamaClient")
    @patch("jama_cli.commands.relationships.get_profile_or_env")
    def test_create_relationship(self, mock_get_profile, mock_client_class):
        """Test creating a relationship."""
        from jama_cli.commands.relationships import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.create_relationship.return_value = 123
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["create", "--from", "1", "--to", "2", "--type", "1"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.relationships.JamaClient")
    @patch("jama_cli.commands.relationships.get_profile_or_env")
    def test_delete_relationship(self, mock_get_profile, mock_client_class):
        """Test deleting a relationship."""
        from jama_cli.commands.relationships import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["delete", "1", "--force"])
        assert result.exit_code == 0


# ==================== Tags Command Tests ====================
class TestTagsCommand:
    """Tests for tags command."""

    @patch("jama_cli.commands.tags.JamaClient")
    @patch("jama_cli.commands.tags.get_profile_or_env")
    def test_list_tags(self, mock_get_profile, mock_client_class):
        """Test listing tags."""
        from jama_cli.commands.tags import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_tags.return_value = [
            {"id": 1, "name": "Tag1"},
            {"id": 2, "name": "Tag2"},
        ]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["list", "1"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.tags.JamaClient")
    @patch("jama_cli.commands.tags.get_profile_or_env")
    def test_tag_items(self, mock_get_profile, mock_client_class):
        """Test listing items with a tag."""
        from jama_cli.commands.tags import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_tagged_items.return_value = [{"id": 1, "fields": {"name": "Item"}}]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["items", "1"])
        assert result.exit_code == 0


# ==================== Picklists Command Tests ====================
class TestPicklistsCommand:
    """Tests for picklists command."""

    @patch("jama_cli.commands.picklists.JamaClient")
    @patch("jama_cli.commands.picklists.get_profile_or_env")
    def test_list_picklists(self, mock_get_profile, mock_client_class):
        """Test listing picklists."""
        from jama_cli.commands.picklists import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_pick_lists.return_value = [
            {"id": 1, "name": "Status"},
            {"id": 2, "name": "Priority"},
        ]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.picklists.JamaClient")
    @patch("jama_cli.commands.picklists.get_profile_or_env")
    def test_get_picklist(self, mock_get_profile, mock_client_class):
        """Test getting a specific picklist."""
        from jama_cli.commands.picklists import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_pick_list.return_value = {"id": 1, "name": "Status"}
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["get", "1"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.picklists.JamaClient")
    @patch("jama_cli.commands.picklists.get_profile_or_env")
    def test_picklist_options(self, mock_get_profile, mock_client_class):
        """Test listing picklist options."""
        from jama_cli.commands.picklists import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_pick_list_options.return_value = [
            {"id": 1, "name": "Open"},
            {"id": 2, "name": "Closed"},
        ]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["options", "1"])
        assert result.exit_code == 0


# ==================== Users Command Tests ====================
class TestUsersCommand:
    """Tests for users command."""

    @patch("jama_cli.commands.users.JamaClient")
    @patch("jama_cli.commands.users.get_profile_or_env")
    def test_list_users(self, mock_get_profile, mock_client_class):
        """Test listing users."""
        from jama_cli.commands.users import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_users.return_value = [
            {"id": 1, "username": "user1"},
            {"id": 2, "username": "user2"},
        ]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.users.JamaClient")
    @patch("jama_cli.commands.users.get_profile_or_env")
    def test_current_user(self, mock_get_profile, mock_client_class):
        """Test getting current user."""
        from jama_cli.commands.users import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_current_user.return_value = {"id": 1, "username": "me"}
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["me"])
        assert result.exit_code == 0


# ==================== Tests Command Tests ====================
class TestTestsCommand:
    """Tests for tests command."""

    @patch("jama_cli.commands.tests.JamaClient")
    @patch("jama_cli.commands.tests.get_profile_or_env")
    def test_get_cycle(self, mock_get_profile, mock_client_class):
        """Test getting a test cycle."""
        from jama_cli.commands.tests import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_test_cycle.return_value = {"id": 1, "name": "Cycle 1"}
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["cycle", "1"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.tests.JamaClient")
    @patch("jama_cli.commands.tests.get_profile_or_env")
    def test_get_runs(self, mock_get_profile, mock_client_class):
        """Test getting test runs."""
        from jama_cli.commands.tests import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_test_runs.return_value = [
            {"id": 1, "name": "Run 1"},
            {"id": 2, "name": "Run 2"},
        ]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["runs", "1"])
        assert result.exit_code == 0


# ==================== Attachments Command Tests ====================
class TestAttachmentsCommand:
    """Tests for attachments command."""

    @patch("jama_cli.commands.attachments.JamaClient")
    @patch("jama_cli.commands.attachments.get_profile_or_env")
    def test_get_attachment(self, mock_get_profile, mock_client_class):
        """Test getting an attachment."""
        from jama_cli.commands.attachments import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_attachment.return_value = {"id": 1, "fileName": "test.txt"}
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["get", "1"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.attachments.JamaClient")
    @patch("jama_cli.commands.attachments.get_profile_or_env")
    def test_upload_attachment_file_not_found(self, mock_get_profile, mock_client_class):
        """Test uploading attachment with non-existent file."""
        from jama_cli.commands.attachments import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["upload", "1", "/nonexistent/file.txt"])
        assert result.exit_code == 1


# ==================== Search Command Tests ====================
class TestSearchCommand:
    """Tests for search command."""

    @patch("jama_cli.commands.search.JamaClient")
    @patch("jama_cli.commands.search.get_profile_or_env")
    def test_search_items(self, mock_get_profile, mock_client_class):
        """Test searching items."""
        from jama_cli.commands.search import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_items.return_value = [
            {"id": 1, "fields": {"name": "Login Feature", "description": "Test"}},
            {"id": 2, "fields": {"name": "Other", "description": "Login here"}},
        ]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["items", "Login", "--project", "1"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.search.JamaClient")
    @patch("jama_cli.commands.search.get_profile_or_env")
    def test_search_fields(self, mock_get_profile, mock_client_class):
        """Test searching in specific fields."""
        from jama_cli.commands.search import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_item_types.return_value = [
            {"id": 1, "display": "Requirement", "fields": [{"name": "name"}, {"name": "description"}]},
        ]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["fields", "1"])
        assert result.exit_code == 0


# ==================== Diff Command Tests ====================
class TestDiffCommand:
    """Tests for diff command."""

    @patch("jama_cli.commands.diff.JamaClient")
    @patch("jama_cli.commands.diff.get_profile_or_env")
    def test_diff_projects(self, mock_get_profile, mock_client_class):
        """Test comparing projects."""
        from jama_cli.commands.diff import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_items.return_value = [
            {"id": 1, "fields": {"name": "Item1"}},
        ]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["projects", "1", "2"])
        assert result.exit_code == 0

    @patch("jama_cli.commands.diff.JamaClient")
    @patch("jama_cli.commands.diff.get_profile_or_env")
    def test_diff_count(self, mock_get_profile, mock_client_class):
        """Test counting differences."""
        from jama_cli.commands.diff import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_items.return_value = [{"id": 1}, {"id": 2}]
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["count", "1", "2"])
        assert result.exit_code == 0


# ==================== Error Handling Tests ====================
class TestErrorHandling:
    """Tests for error handling in commands."""

    @patch("jama_cli.commands.projects.JamaClient")
    @patch("jama_cli.commands.projects.get_profile_or_env")
    def test_api_error_handling(self, mock_get_profile, mock_client_class):
        """Test handling of API errors."""
        from jama_cli.commands.projects import app

        mock_profile = MagicMock()
        mock_profile.has_valid_credentials.return_value = True
        mock_get_profile.return_value = mock_profile
        mock_client = MagicMock()
        mock_client.get_projects.side_effect = Exception("API Error")
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["list"])
        assert result.exit_code == 1

    @patch("jama_cli.commands.items.JamaClient")
    @patch("jama_cli.commands.items.get_profile_or_env")
    def test_item_not_found(self, mock_get_profile, mock_client_class):
        """Test handling of item not found."""
        from jama_cli.commands.items import app

        mock_get_profile.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_item.side_effect = Exception("Item not found")
        mock_client_class.return_value = mock_client

        result = runner.invoke(app, ["get", "99999"])
        assert result.exit_code == 1
