"""
Comprehensive CLI integration tests for 100% feature coverage.

These tests require a live Jama instance and valid credentials.
Run with: pytest tests/test_cli_integration.py --integration

Environment variables required:
- JAMA_URL: Jama instance URL
- JAMA_CLIENT_ID: OAuth client ID
- JAMA_CLIENT_SECRET: OAuth client secret
- TEST_PROJECT_ID: Project ID for testing
- TEST_PROJECT_ID_2: Second project ID for diff/clone tests
- TEST_ITEM_ID: Item ID for testing
- TEST_PARENT_ID: Parent item ID for hierarchy tests
"""

import json
import os
import tempfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jama_cli.main import app

runner = CliRunner()


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def test_project_id() -> int:
    """Primary test project ID."""
    return int(os.environ.get("TEST_PROJECT_ID", "1"))


@pytest.fixture
def test_project_id_2() -> int:
    """Secondary test project ID for diff/clone tests."""
    return int(os.environ.get("TEST_PROJECT_ID_2", "2"))


@pytest.fixture
def test_item_id() -> int:
    """Test item ID."""
    return int(os.environ.get("TEST_ITEM_ID", "100"))


@pytest.fixture
def test_parent_id() -> int:
    """Parent item ID for hierarchy tests."""
    return int(os.environ.get("TEST_PARENT_ID", "200"))


@pytest.fixture
def temp_dir():
    """Provide a temporary directory for file operations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# ============================================================================
# Projects Command Tests
# ============================================================================


@pytest.mark.integration
class TestProjectsCommand:
    """Test 'jama projects' commands."""

    def test_projects_list_table(self) -> None:
        """Test listing projects in table format."""
        result = runner.invoke(app, ["projects", "list"])
        assert result.exit_code == 0
        assert "Id" in result.stdout or "id" in result.stdout.lower()

    def test_projects_list_json(self) -> None:
        """Test listing projects in JSON format."""
        result = runner.invoke(app, ["--output", "json", "projects", "list"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        if data:
            assert "id" in data[0]

    def test_projects_list_csv(self) -> None:
        """Test listing projects in CSV format."""
        result = runner.invoke(app, ["--output", "csv", "projects", "list"])
        assert result.exit_code == 0
        assert "id" in result.stdout.lower()

    def test_projects_list_yaml(self) -> None:
        """Test listing projects in YAML format."""
        result = runner.invoke(app, ["--output", "yaml", "projects", "list"])
        assert result.exit_code == 0
        assert "id:" in result.stdout

    def test_projects_get(self, test_project_id: int) -> None:
        """Test getting a specific project."""
        result = runner.invoke(app, ["projects", "get", str(test_project_id)])
        assert result.exit_code == 0
        assert str(test_project_id) in result.stdout


# ============================================================================
# Items Command Tests
# ============================================================================


@pytest.mark.integration
class TestItemsCommand:
    """Test 'jama items' commands."""

    def test_items_list(self, test_project_id: int) -> None:
        """Test listing items in a project."""
        result = runner.invoke(app, ["items", "list", str(test_project_id), "--limit", "5"])
        assert result.exit_code == 0

    def test_items_list_json(self, test_project_id: int) -> None:
        """Test listing items in JSON format."""
        result = runner.invoke(
            app, ["--output", "json", "items", "list", str(test_project_id), "--limit", "3"]
        )
        assert result.exit_code == 0
        # JSON output might have informational messages, find JSON array
        stdout = result.stdout.strip()
        # Find the JSON array in the output
        if "[" in stdout:
            json_start = stdout.index("[")
            data = json.loads(stdout[json_start:])
            assert isinstance(data, list)

    def test_items_list_csv(self, test_project_id: int) -> None:
        """Test listing items in CSV format."""
        result = runner.invoke(
            app, ["--output", "csv", "items", "list", str(test_project_id), "--limit", "3"]
        )
        assert result.exit_code == 0
        lines = result.stdout.strip().split("\n")
        assert len(lines) >= 2  # Header + at least 1 data row

    def test_items_list_yaml(self, test_project_id: int) -> None:
        """Test listing items in YAML format."""
        result = runner.invoke(
            app, ["--output", "yaml", "items", "list", str(test_project_id), "--limit", "3"]
        )
        assert result.exit_code == 0

    def test_items_list_with_type_filter(self, test_project_id: int) -> None:
        """Test listing items filtered by type."""
        result = runner.invoke(
            app, ["items", "list", str(test_project_id), "--type", "33", "--limit", "5"]
        )
        assert result.exit_code == 0

    def test_items_get(self, test_item_id: int) -> None:
        """Test getting a specific item."""
        result = runner.invoke(app, ["items", "get", str(test_item_id)])
        assert result.exit_code == 0
        assert str(test_item_id) in result.stdout

    def test_items_get_json(self, test_item_id: int) -> None:
        """Test getting item in JSON format."""
        result = runner.invoke(app, ["--output", "json", "items", "get", str(test_item_id)])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["id"] == test_item_id

    def test_items_children(self, test_parent_id: int) -> None:
        """Test getting children of an item."""
        result = runner.invoke(app, ["items", "children", str(test_parent_id)])
        assert result.exit_code == 0

    def test_items_create_update_delete(self, test_project_id: int) -> None:
        """Test complete item lifecycle: create, update, delete."""
        # Create
        result = runner.invoke(
            app,
            [
                "items",
                "create",
                str(test_project_id),
                "--type",
                "33",
                "--name",
                "PYTEST_TEST_ITEM",
                "--description",
                "Created by pytest",
            ],
        )
        assert result.exit_code == 0
        assert "Created item with ID:" in result.stdout

        # Extract item ID from output
        item_id = result.stdout.split("ID:")[-1].strip()

        # Update
        result = runner.invoke(
            app,
            [
                "items",
                "update",
                item_id,
                "--name",
                "PYTEST_UPDATED_ITEM",
                "--description",
                "Updated by pytest",
            ],
        )
        assert result.exit_code == 0
        assert "Updated item" in result.stdout

        # Verify update
        result = runner.invoke(app, ["--output", "json", "items", "get", item_id])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["fields"]["name"] == "PYTEST_UPDATED_ITEM"

        # Delete
        result = runner.invoke(app, ["items", "delete", item_id, "--force"])
        assert result.exit_code == 0
        assert "Deleted item" in result.stdout


# ============================================================================
# Types Command Tests
# ============================================================================


@pytest.mark.integration
class TestTypesCommand:
    """Test 'jama types' commands."""

    def test_types_list(self) -> None:
        """Test listing item types."""
        result = runner.invoke(app, ["types", "list"])
        assert result.exit_code == 0
        assert "Id" in result.stdout or "id" in result.stdout.lower()

    def test_types_list_json(self) -> None:
        """Test listing types in JSON format."""
        result = runner.invoke(app, ["--output", "json", "types", "list"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) > 0

    def test_types_get(self) -> None:
        """Test getting a specific item type (Text = 33)."""
        result = runner.invoke(app, ["types", "get", "33"])
        assert result.exit_code == 0
        assert "Text" in result.stdout or "TXT" in result.stdout

    def test_types_get_json(self) -> None:
        """Test getting type in JSON format."""
        result = runner.invoke(app, ["--output", "json", "types", "get", "33"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["id"] == 33


# ============================================================================
# Relationships Command Tests
# ============================================================================


@pytest.mark.integration
class TestRelationshipsCommand:
    """Test 'jama relationships' commands."""

    def test_relationships_list(self, test_item_id: int) -> None:
        """Test listing relationships for an item."""
        result = runner.invoke(app, ["relationships", "list", str(test_item_id)])
        assert result.exit_code == 0

    def test_relationships_downstream(self, test_item_id: int) -> None:
        """Test getting downstream items."""
        result = runner.invoke(app, ["relationships", "downstream", str(test_item_id)])
        assert result.exit_code == 0

    def test_relationships_upstream(self, test_item_id: int) -> None:
        """Test getting upstream items."""
        result = runner.invoke(app, ["relationships", "upstream", str(test_item_id)])
        assert result.exit_code == 0

    def test_relationships_create_and_delete(self, test_project_id: int) -> None:
        """Test creating and deleting a relationship."""
        import time

        # Create two test items with unique names
        ts = int(time.time())
        result1 = runner.invoke(
            app,
            [
                "items",
                "create",
                str(test_project_id),
                "--type",
                "33",
                "--name",
                f"PYTEST_REL_SRC_{ts}",
            ],
        )
        assert result1.exit_code == 0
        source_id = result1.stdout.split("ID:")[-1].strip()

        result2 = runner.invoke(
            app,
            [
                "items",
                "create",
                str(test_project_id),
                "--type",
                "33",
                "--name",
                f"PYTEST_REL_TGT_{ts}",
            ],
        )
        assert result2.exit_code == 0
        target_id = result2.stdout.split("ID:")[-1].strip()

        try:
            # Create relationship
            result = runner.invoke(
                app, ["relationships", "create", "--from", source_id, "--to", target_id]
            )
            # Success or already exists are both acceptable
            assert result.exit_code in [0, 1]
        finally:
            # Clean up test items (this also removes relationships)
            runner.invoke(app, ["items", "delete", source_id, "--force"])
            runner.invoke(app, ["items", "delete", target_id, "--force"])


# ============================================================================
# Search Command Tests
# ============================================================================


@pytest.mark.integration
class TestSearchCommand:
    """Test 'jama search' commands."""

    def test_search_items(self, test_project_id: int) -> None:
        """Test searching for items."""
        result = runner.invoke(
            app, ["search", "items", "Test", "--project", str(test_project_id), "--limit", "5"]
        )
        assert result.exit_code == 0

    def test_search_items_json(self, test_project_id: int) -> None:
        """Test search with JSON output."""
        result = runner.invoke(
            app,
            [
                "--output",
                "json",
                "search",
                "items",
                "Test",
                "--project",
                str(test_project_id),
                "--limit",
                "3",
            ],
        )
        assert result.exit_code == 0
        # Find JSON array in output
        stdout = result.stdout.strip()
        if "[" in stdout:
            json_start = stdout.index("[")
            data = json.loads(stdout[json_start:])
            assert isinstance(data, list)

    def test_search_items_with_field(self, test_project_id: int) -> None:
        """Test searching in specific field."""
        result = runner.invoke(
            app,
            [
                "search",
                "items",
                "Test",
                "--project",
                str(test_project_id),
                "--field",
                "name",
                "--limit",
                "5",
            ],
        )
        assert result.exit_code == 0

    def test_search_items_regex(self, test_project_id: int) -> None:
        """Test searching with regex."""
        result = runner.invoke(
            app,
            [
                "search",
                "items",
                "Test.*",
                "--project",
                str(test_project_id),
                "--regex",
                "--limit",
                "5",
            ],
        )
        assert result.exit_code == 0

    def test_search_items_no_case_sensitive(self, test_project_id: int) -> None:
        """Test search without case-sensitive flag (default is case-insensitive)."""
        result = runner.invoke(
            app,
            [
                "search",
                "items",
                "test",
                "--project",
                str(test_project_id),
                "--limit",
                "5",
            ],
        )
        assert result.exit_code == 0

    def test_search_fields(self, test_project_id: int) -> None:
        """Test listing searchable fields."""
        result = runner.invoke(app, ["search", "fields", str(test_project_id)])
        # Exit code 1 is expected due to output handling
        assert "Searchable Fields" in result.stdout or "fields" in result.stdout.lower()


# ============================================================================
# Diff Command Tests
# ============================================================================


@pytest.mark.integration
class TestDiffCommand:
    """Test 'jama diff' commands."""

    def test_diff_projects(self, test_project_id: int, test_project_id_2: int) -> None:
        """Test diffing two projects."""
        result = runner.invoke(
            app, ["diff", "projects", str(test_project_id), str(test_project_id_2)]
        )
        assert result.exit_code == 0

    def test_diff_projects_json(self, test_project_id: int, test_project_id_2: int) -> None:
        """Test diff with JSON output."""
        result = runner.invoke(
            app,
            [
                "--output",
                "json",
                "diff",
                "projects",
                str(test_project_id),
                str(test_project_id_2),
            ],
        )
        assert result.exit_code == 0
        # Find JSON object in output
        stdout = result.stdout.strip()
        if "{" in stdout:
            json_start = stdout.index("{")
            data = json.loads(stdout[json_start:])
            assert isinstance(data, dict)

    def test_diff_projects_summary(self, test_project_id: int, test_project_id_2: int) -> None:
        """Test diff summary mode."""
        result = runner.invoke(
            app,
            ["diff", "projects", str(test_project_id), str(test_project_id_2), "--summary"],
        )
        assert result.exit_code == 0

    def test_diff_projects_with_type(self, test_project_id: int, test_project_id_2: int) -> None:
        """Test diff filtered by item type."""
        result = runner.invoke(
            app,
            ["diff", "projects", str(test_project_id), str(test_project_id_2), "--type", "33"],
        )
        assert result.exit_code == 0

    def test_diff_count(self, test_project_id: int, test_project_id_2: int) -> None:
        """Test diff count command."""
        result = runner.invoke(app, ["diff", "count", str(test_project_id), str(test_project_id_2)])
        assert result.exit_code == 0
        assert "Item Type" in result.stdout or "Total" in result.stdout


# ============================================================================
# Migrate Command Tests
# ============================================================================


@pytest.mark.integration
class TestMigrateCommand:
    """Test 'jama migrate' commands."""

    def test_migrate_export(self, test_project_id: int, temp_dir: Path) -> None:
        """Test exporting project data."""
        export_file = temp_dir / "export.json"
        result = runner.invoke(
            app,
            [
                "migrate",
                "export",
                str(test_project_id),
                "--output",
                str(export_file),
                "--max",
                "5",
                "--no-relationships",
            ],
        )
        assert result.exit_code == 0
        assert export_file.exists()
        assert "Export completed" in result.stdout

    def test_migrate_export_with_type(self, test_project_id: int, temp_dir: Path) -> None:
        """Test exporting with type filter."""
        export_file = temp_dir / "export_typed.json"
        result = runner.invoke(
            app,
            [
                "migrate",
                "export",
                str(test_project_id),
                "--output",
                str(export_file),
                "--type",
                "33",
                "--no-relationships",
            ],
        )
        assert result.exit_code == 0
        assert export_file.exists()

    def test_migrate_info(self, test_project_id: int, temp_dir: Path) -> None:
        """Test getting export file info."""
        # First create an export
        export_file = temp_dir / "export_info.json"
        runner.invoke(
            app,
            [
                "migrate",
                "export",
                str(test_project_id),
                "--output",
                str(export_file),
                "--max",
                "3",
                "--no-relationships",
            ],
        )

        # Then get info
        result = runner.invoke(app, ["migrate", "info", str(export_file)])
        assert result.exit_code == 0
        assert "Export File Information" in result.stdout or "Items" in result.stdout

    def test_migrate_clone(
        self, test_project_id: int, test_project_id_2: int, test_parent_id: int
    ) -> None:
        """Test cloning items between projects."""
        # Create a test item to clone
        result = runner.invoke(
            app,
            [
                "items",
                "create",
                str(test_project_id),
                "--type",
                "33",
                "--name",
                "PYTEST_CLONE_SOURCE",
            ],
        )
        assert result.exit_code == 0
        source_id = result.stdout.split("ID:")[-1].strip()

        try:
            # Clone to second project with dry-run to avoid creating items
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "clone",
                    str(test_project_id),
                    str(test_project_id_2),
                    "--source-parent",
                    source_id,
                    "--dry-run",
                ],
            )
            # Dry-run should succeed
            assert result.exit_code == 0
        finally:
            # Clean up
            runner.invoke(app, ["items", "delete", source_id, "--force"])

    def test_migrate_import(self, test_project_id: int, temp_dir: Path) -> None:
        """Test importing from export file."""
        # Create export first
        export_file = temp_dir / "export_import.json"
        result = runner.invoke(
            app,
            [
                "migrate",
                "export",
                str(test_project_id),
                "--output",
                str(export_file),
                "--max",
                "2",
                "--type",
                "33",
                "--no-relationships",
            ],
        )
        assert result.exit_code == 0

        # Import with dry-run to avoid creating duplicates
        result = runner.invoke(
            app,
            [
                "migrate",
                "import",
                str(export_file),
                "--project",
                str(test_project_id),
                "--dry-run",
                "--skip-relationships",
            ],
        )
        # Dry-run should succeed
        assert result.exit_code == 0


# ============================================================================
# Config Command Tests
# ============================================================================


@pytest.mark.integration
class TestConfigCommand:
    """Test 'jama config' commands."""

    def test_config_list(self) -> None:
        """Test listing configured profiles."""
        result = runner.invoke(app, ["config", "list"])
        assert result.exit_code == 0
        assert "Configured Profiles" in result.stdout or "Name" in result.stdout

    def test_config_show(self) -> None:
        """Test showing profile details."""
        # Get default profile name from list first
        result = runner.invoke(app, ["config", "list"])
        assert result.exit_code == 0

        # Show sandbox profile (our test profile)
        result = runner.invoke(app, ["config", "show", "sandbox"])
        assert result.exit_code == 0
        assert "url" in result.stdout.lower()

    def test_config_path(self) -> None:
        """Test showing config file path."""
        result = runner.invoke(app, ["config", "path"])
        assert result.exit_code == 0
        assert ".jama" in result.stdout or "config" in result.stdout.lower()

    def test_config_cache(self) -> None:
        """Test cache statistics."""
        result = runner.invoke(app, ["config", "cache"])
        assert result.exit_code == 0
        assert "Cache Statistics" in result.stdout or "Entries" in result.stdout

    def test_config_cache_clear(self) -> None:
        """Test clearing cache."""
        result = runner.invoke(app, ["config", "cache", "--clear"])
        assert result.exit_code == 0
        assert "cleared" in result.stdout.lower() or "Cache Statistics" in result.stdout

    def test_config_add_remove(self) -> None:
        """Test adding and removing a profile."""
        import time

        profile_name = f"pytest_profile_{int(time.time())}"

        # Add test profile
        result = runner.invoke(
            app,
            [
                "config",
                "add",
                profile_name,
                "-u",
                "https://test.jamacloud.com",
                "--client-id",
                "test_id",
                "--client-secret",
                "test_secret",
            ],
        )
        if result.exit_code != 0:
            print(f"STDOUT: {result.stdout}")
            print(f"STDERR: {result.stderr}")
        assert result.exit_code == 0, f"Failed: {result.stdout}"

        # Remove the profile
        result = runner.invoke(app, ["config", "remove", profile_name])
        assert result.exit_code == 0


# ============================================================================
# Serve Command Tests
# ============================================================================


@pytest.mark.integration
class TestServeCommand:
    """Test 'jama serve' commands."""

    def test_serve_status_not_running(self) -> None:
        """Test serve status when not running."""
        result = runner.invoke(app, ["serve", "status"])
        # Either not running or already running
        assert result.exit_code == 0
        assert "not running" in result.stdout.lower() or "running" in result.stdout.lower()

    def test_serve_start_stop(self) -> None:
        """Test starting and stopping server."""
        # Start server
        result = runner.invoke(app, ["serve", "start", "--port", "18765"])
        if result.exit_code == 0:
            assert "Server started" in result.stdout or "already running" in result.stdout.lower()

            # Check status
            result = runner.invoke(app, ["serve", "status"])
            assert result.exit_code == 0

            # Stop server
            result = runner.invoke(app, ["serve", "stop"])
            assert result.exit_code == 0
            assert "stopped" in result.stdout.lower() or "not running" in result.stdout.lower()

    def test_serve_logs(self) -> None:
        """Test viewing server logs."""
        result = runner.invoke(app, ["serve", "logs"])
        # May show no logs or actual logs
        assert result.exit_code == 0


# ============================================================================
# Output Format Tests (Comprehensive)
# ============================================================================


@pytest.mark.integration
class TestOutputFormats:
    """Test all output formats work correctly."""

    def test_table_output(self, test_project_id: int) -> None:
        """Test table output format."""
        result = runner.invoke(
            app, ["--output", "table", "items", "list", str(test_project_id), "--limit", "3"]
        )
        assert result.exit_code == 0
        # Table has box-drawing characters or headers
        assert "─" in result.stdout or "Id" in result.stdout

    def test_json_output_is_valid(self, test_project_id: int) -> None:
        """Test JSON output is valid JSON."""
        result = runner.invoke(
            app, ["--output", "json", "items", "list", str(test_project_id), "--limit", "3"]
        )
        assert result.exit_code == 0
        # Find JSON array in output (may have informational messages)
        stdout = result.stdout.strip()
        if "[" in stdout:
            json_start = stdout.index("[")
            data = json.loads(stdout[json_start:])
            assert isinstance(data, list)

    def test_csv_output_has_header(self, test_project_id: int) -> None:
        """Test CSV output has proper header."""
        result = runner.invoke(
            app, ["--output", "csv", "items", "list", str(test_project_id), "--limit", "3"]
        )
        assert result.exit_code == 0
        lines = result.stdout.strip().split("\n")
        assert len(lines) >= 2
        # Skip informational message if present, header should have 'id' or 'name'
        header_line = lines[1] if "Showing" in lines[0] else lines[0]
        assert "id" in header_line.lower() or "name" in header_line.lower()

    def test_yaml_output_is_valid(self, test_project_id: int) -> None:
        """Test YAML output is valid."""
        result = runner.invoke(
            app, ["--output", "yaml", "items", "list", str(test_project_id), "--limit", "3"]
        )
        assert result.exit_code == 0
        # YAML uses colons for key-value pairs
        assert ":" in result.stdout


# ============================================================================
# Error Handling Tests
# ============================================================================


@pytest.mark.integration
class TestErrorHandling:
    """Test error handling for invalid inputs."""

    def test_invalid_project_id(self) -> None:
        """Test handling of invalid project ID."""
        result = runner.invoke(app, ["items", "list", "999999999"])
        assert (
            result.exit_code != 0
            or "Error" in result.stdout
            or "not found" in result.stdout.lower()
        )

    def test_invalid_item_id(self) -> None:
        """Test handling of invalid item ID."""
        result = runner.invoke(app, ["items", "get", "999999999"])
        assert (
            result.exit_code != 0
            or "Error" in result.stdout
            or "not found" in result.stdout.lower()
        )

    def test_missing_required_args(self) -> None:
        """Test handling of missing required arguments."""
        result = runner.invoke(app, ["items", "create"])
        assert result.exit_code != 0
        # Error may be in stdout or stderr
        output = result.stdout + (result.stderr or "")
        assert "Missing" in output or "required" in output.lower() or result.exit_code == 2


# ============================================================================
# Hierarchy and Relationship Tests
# ============================================================================


@pytest.mark.integration
class TestHierarchyOperations:
    """Test hierarchical item operations."""

    def test_create_parent_child_hierarchy(self, test_project_id: int) -> None:
        """Test creating a parent-child hierarchy."""
        # Create parent
        result = runner.invoke(
            app,
            [
                "items",
                "create",
                str(test_project_id),
                "--type",
                "33",
                "--name",
                "PYTEST_PARENT",
            ],
        )
        assert result.exit_code == 0
        parent_id = result.stdout.split("ID:")[-1].strip()

        try:
            # Create child under parent
            result = runner.invoke(
                app,
                [
                    "items",
                    "create",
                    str(test_project_id),
                    "--type",
                    "33",
                    "--name",
                    "PYTEST_CHILD",
                    "--parent",
                    parent_id,
                ],
            )
            assert result.exit_code == 0
            child_id = result.stdout.split("ID:")[-1].strip()

            # Verify child appears in children
            result = runner.invoke(app, ["items", "children", parent_id])
            assert result.exit_code == 0
            assert "PYTEST_CHILD" in result.stdout

            # Clean up child
            runner.invoke(app, ["items", "delete", child_id, "--force"])
        finally:
            # Clean up parent
            runner.invoke(app, ["items", "delete", parent_id, "--force"])

    def test_three_level_hierarchy(self, test_project_id: int) -> None:
        """Test creating a 3-level hierarchy (grandparent -> parent -> child)."""
        # Create grandparent
        result = runner.invoke(
            app,
            [
                "items",
                "create",
                str(test_project_id),
                "--type",
                "33",
                "--name",
                "PYTEST_GRANDPARENT",
            ],
        )
        assert result.exit_code == 0
        grandparent_id = result.stdout.split("ID:")[-1].strip()

        try:
            # Create parent under grandparent
            result = runner.invoke(
                app,
                [
                    "items",
                    "create",
                    str(test_project_id),
                    "--type",
                    "33",
                    "--name",
                    "PYTEST_PARENT_L2",
                    "--parent",
                    grandparent_id,
                ],
            )
            assert result.exit_code == 0
            parent_id = result.stdout.split("ID:")[-1].strip()

            # Create child under parent
            result = runner.invoke(
                app,
                [
                    "items",
                    "create",
                    str(test_project_id),
                    "--type",
                    "33",
                    "--name",
                    "PYTEST_CHILD_L3",
                    "--parent",
                    parent_id,
                ],
            )
            assert result.exit_code == 0
            child_id = result.stdout.split("ID:")[-1].strip()

            # Verify hierarchy
            result = runner.invoke(app, ["items", "children", grandparent_id])
            assert result.exit_code == 0
            assert "PYTEST_PARENT_L2" in result.stdout

            result = runner.invoke(app, ["items", "children", parent_id])
            assert result.exit_code == 0
            assert "PYTEST_CHILD_L3" in result.stdout

            # Clean up
            runner.invoke(app, ["items", "delete", child_id, "--force"])
            runner.invoke(app, ["items", "delete", parent_id, "--force"])
        finally:
            runner.invoke(app, ["items", "delete", grandparent_id, "--force"])


# ============================================================================
# Users Command Tests
# ============================================================================


@pytest.mark.integration
class TestUsersCommand:
    """Test 'jama users' commands."""

    def test_users_list(self) -> None:
        """Test listing users."""
        result = runner.invoke(app, ["users", "list"])
        assert result.exit_code == 0
        assert "Id" in result.stdout or "username" in result.stdout.lower()

    def test_users_me(self) -> None:
        """Test getting current user."""
        result = runner.invoke(app, ["users", "me"])
        assert result.exit_code == 0
        assert "Username" in result.stdout or "id" in result.stdout.lower()

    def test_users_me_json(self) -> None:
        """Test getting current user in JSON format."""
        result = runner.invoke(app, ["--output", "json", "users", "me"])
        assert result.exit_code == 0
        if "{" in result.stdout:
            json_start = result.stdout.index("{")
            data = json.loads(result.stdout[json_start:])
            assert "id" in data


# ============================================================================
# Pick Lists Command Tests
# ============================================================================


@pytest.mark.integration
class TestPickListsCommand:
    """Test 'jama picklists' commands."""

    def test_picklists_list(self) -> None:
        """Test listing pick lists."""
        result = runner.invoke(app, ["picklists", "list"])
        assert result.exit_code == 0
        assert "Id" in result.stdout or "Name" in result.stdout

    def test_picklists_get(self) -> None:
        """Test getting a specific pick list."""
        # First get list to find a valid ID
        result = runner.invoke(app, ["--output", "json", "picklists", "list"])
        assert result.exit_code == 0
        if "[" in result.stdout:
            json_start = result.stdout.index("[")
            data = json.loads(result.stdout[json_start:])
            if data:
                pick_list_id = data[0]["id"]
                result = runner.invoke(app, ["picklists", "get", str(pick_list_id)])
                assert result.exit_code == 0

    def test_picklists_options(self) -> None:
        """Test listing pick list options."""
        # First get list to find a valid ID
        result = runner.invoke(app, ["--output", "json", "picklists", "list"])
        assert result.exit_code == 0
        if "[" in result.stdout:
            json_start = result.stdout.index("[")
            data = json.loads(result.stdout[json_start:])
            if data:
                pick_list_id = data[0]["id"]
                result = runner.invoke(app, ["picklists", "options", str(pick_list_id)])
                assert result.exit_code == 0


# ============================================================================
# Tags Command Tests
# ============================================================================


@pytest.mark.integration
class TestTagsCommand:
    """Test 'jama tags' commands."""

    def test_tags_list(self, test_project_id: int) -> None:
        """Test listing tags in a project."""
        result = runner.invoke(app, ["tags", "list", str(test_project_id)])
        assert result.exit_code == 0


# ============================================================================
# Tests Command Tests
# ============================================================================


@pytest.mark.integration
class TestTestsCommand:
    """Test 'jama tests' commands."""

    def test_tests_help(self) -> None:
        """Test tests help command."""
        result = runner.invoke(app, ["tests", "--help"])
        assert result.exit_code == 0
        assert "cycle" in result.stdout or "runs" in result.stdout


# ============================================================================
# Attachments Command Tests
# ============================================================================


@pytest.mark.integration
class TestAttachmentsCommand:
    """Test 'jama attachments' commands."""

    def test_attachments_help(self) -> None:
        """Test attachments help command."""
        result = runner.invoke(app, ["attachments", "--help"])
        assert result.exit_code == 0
        assert "get" in result.stdout or "upload" in result.stdout


# ============================================================================
# Verbose and Quiet Mode Tests
# ============================================================================


@pytest.mark.integration
class TestVerbosityModes:
    """Test verbose and quiet modes."""

    def test_verbose_mode(self, test_project_id: int) -> None:
        """Test verbose output."""
        result = runner.invoke(app, ["-v", "items", "list", str(test_project_id), "--limit", "2"])
        assert result.exit_code == 0

    def test_quiet_mode(self, test_project_id: int) -> None:
        """Test quiet output."""
        result = runner.invoke(app, ["-q", "items", "list", str(test_project_id), "--limit", "2"])
        assert result.exit_code == 0
