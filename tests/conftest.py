"""
Pytest configuration and fixtures for the test suite.

This module provides reusable fixtures for both unit tests and integration tests.

Environment variables for integration tests:
- JAMA_URL: Jama instance URL (e.g., https://your-instance.jamacloud.com)
- JAMA_CLIENT_ID: OAuth client ID
- JAMA_CLIENT_SECRET: OAuth client secret
- TEST_PROJECT_ID: Primary project ID for testing
- TEST_PROJECT_ID_2: Secondary project ID for diff/clone tests
- TEST_ITEM_ID: Item ID for testing
- TEST_PARENT_ID: Parent item ID for hierarchy tests
"""

import os
from collections.abc import Generator
from unittest import mock

import pytest

from jama_mcp_server.models import JamaConfig

# ============================================================================
# Configuration Fixtures
# ============================================================================


@pytest.fixture
def jama_config() -> JamaConfig:
    """Provide a test Jama configuration.

    Uses environment variables if available, otherwise uses test defaults.
    For integration tests, set:
    - JAMA_URL
    - JAMA_CLIENT_ID
    - JAMA_CLIENT_SECRET
    """
    # Check for OAuth credentials first
    client_id = os.environ.get("JAMA_CLIENT_ID", "")
    client_secret = os.environ.get("JAMA_CLIENT_SECRET", "")

    if client_id and client_secret:
        return JamaConfig(
            url=os.environ.get("JAMA_URL", "https://example.jamacloud.com/"),
            client_id=client_id,
            client_secret=client_secret,
            oauth=True,
        )

    # Fall back to basic auth
    return JamaConfig(
        url=os.environ.get("JAMA_URL", "https://example.jamacloud.com/"),
        username=os.environ.get("JAMA_USERNAME", "test_client_id"),
        password=os.environ.get("JAMA_PASSWORD", "test_client_secret"),
        oauth=True,
    )


@pytest.fixture
def api_key_config() -> JamaConfig:
    """Provide a test configuration with API key authentication."""
    return JamaConfig(
        url="https://example.jamacloud.com",
        api_key="test_api_key_12345",
    )


@pytest.fixture
def oauth_config() -> JamaConfig:
    """Provide a test configuration with OAuth authentication."""
    return JamaConfig(
        url="https://example.jamacloud.com",
        client_id="test_client_id",
        client_secret="test_client_secret",
        oauth=True,
    )


# ============================================================================
# Test Data Fixtures
# ============================================================================


@pytest.fixture
def test_project_id() -> int:
    """Test project ID for integration tests."""
    return int(os.environ.get("TEST_PROJECT_ID", "1"))


@pytest.fixture
def test_project_id_2() -> int:
    """Secondary test project ID for diff/clone tests."""
    return int(os.environ.get("TEST_PROJECT_ID_2", "2"))


@pytest.fixture
def test_item_id() -> int:
    """Test item ID for integration tests."""
    return int(os.environ.get("TEST_ITEM_ID", "100"))


@pytest.fixture
def test_parent_id() -> int:
    """Parent item ID for hierarchy tests."""
    return int(os.environ.get("TEST_PARENT_ID", "200"))


@pytest.fixture
def sample_projects() -> list:
    """Sample project data for testing."""
    return [
        {
            "id": 1,
            "projectKey": "PROJ1",
            "name": "Test Project 1",
            "description": "First test project",
            "createdDate": "2024-01-01T00:00:00.000Z",
        },
        {
            "id": 2,
            "projectKey": "PROJ2",
            "name": "Test Project 2",
            "description": "Second test project",
            "createdDate": "2024-01-02T00:00:00.000Z",
        },
    ]


@pytest.fixture
def sample_items() -> list:
    """Sample item data for testing."""
    return [
        {
            "id": 100,
            "documentKey": "PROJ1-REQ-001",
            "globalId": "GID-100",
            "project": 1,
            "itemType": 10,
            "fields": {
                "name": "Test Requirement 1",
                "description": "This is a test requirement",
                "status": "Draft",
            },
        },
        {
            "id": 101,
            "documentKey": "PROJ1-REQ-002",
            "globalId": "GID-101",
            "project": 1,
            "itemType": 10,
            "fields": {
                "name": "Test Requirement 2",
                "description": "This is another test requirement",
                "status": "Approved",
            },
        },
    ]


@pytest.fixture
def sample_item_types() -> list:
    """Sample item type data for testing."""
    return [
        {
            "id": 10,
            "display": "Requirement",
            "typeKey": "REQ",
            "description": "A requirement item type",
        },
        {
            "id": 20,
            "display": "Test Case",
            "typeKey": "TC",
            "description": "A test case item type",
        },
    ]


# ============================================================================
# Mock Fixtures
# ============================================================================


@pytest.fixture
def mock_jama_client() -> Generator:
    """Provide a mock JamaClient for testing."""
    with mock.patch("jama_mcp_server.core.server.JamaClient") as mock_client:
        mock_instance = mock_client.return_value

        # Setup default mock behaviors
        mock_instance.get_projects.return_value = []
        mock_instance.get_items.return_value = []
        mock_instance.get_item.return_value = {}
        mock_instance.get_item_types.return_value = []

        yield mock_instance


# ============================================================================
# Integration Test Markers
# ============================================================================


def pytest_configure(config: pytest.Config) -> None:
    """Configure custom pytest markers."""
    config.addinivalue_line("markers", "integration: mark test as an integration test")
    config.addinivalue_line("markers", "slow: mark test as slow running")


def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    """Skip integration tests unless --integration flag is provided."""
    if config.getoption("--integration", default=False):
        return

    skip_integration = pytest.mark.skip(
        reason="Integration tests skipped. Use --integration to run."
    )

    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom command line options."""
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests",
    )
