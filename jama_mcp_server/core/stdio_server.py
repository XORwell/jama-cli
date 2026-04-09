"""
Stdio-based MCP server implementation for Jama integration.

This implementation uses the MCP protocol's stdio transport for native MCP client
compatibility with Claude Desktop, Cline, VS Code, and other MCP clients.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger
from mcp.server import Server
from mcp.types import TextContent, Tool
from py_jama_rest_client.client import JamaClient

from jama_mcp_server.models import JamaConfig


class JamaStdioMCPServer:
    """Stdio-based MCP server implementation for Jama API with read and write capabilities."""

    def __init__(self, config: JamaConfig):
        """
        Initialize the Jama stdio MCP server.

        Args:
            config: Jama configuration
        """
        self.config = config
        self.jama_client: JamaClient | None = None
        self.mcp = Server("jama-mcp-server")

        # Register request handlers
        self._register_tools()

    def _register_tools(self):
        """Register all MCP tools."""

        @self.mcp.list_tools()
        async def list_tools() -> list[Tool]:
            """List all available Jama tools."""
            return [
                Tool(
                    name="get_projects",
                    description="Get all accessible Jama projects",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="get_project",
                    description="Get a specific project by ID",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project_id": {"type": "integer", "description": "Project ID"},
                        },
                        "required": ["project_id"],
                    },
                ),
                Tool(
                    name="get_item",
                    description="Get a specific item by ID",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "integer", "description": "Item ID"},
                        },
                        "required": ["item_id"],
                    },
                ),
                Tool(
                    name="get_items",
                    description="Get items from a project",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project_id": {"type": "integer", "description": "Project ID"},
                        },
                        "required": ["project_id"],
                    },
                ),
                Tool(
                    name="create_item",
                    description="Create a new item in a project",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project_id": {"type": "integer", "description": "Project ID"},
                            "item_type_id": {"type": "integer", "description": "Item type ID"},
                            "child_item_type_id": {
                                "type": "integer",
                                "description": "Child item type ID (for Sets/Components). Omit if not applicable.",
                            },
                            "location": {
                                "type": "object",
                                "description": (
                                    'Parent location. E.g. {"item": 12345} for child of item, '
                                    'or {"project": 42} for project root'
                                ),
                            },
                            "fields": {"type": "object", "description": "Item fields (name, description, etc.)"},
                        },
                        "required": ["project_id", "item_type_id", "location", "fields"],
                    },
                ),
                Tool(
                    name="update_item",
                    description="Update an existing item",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "integer", "description": "Item ID"},
                            "fields": {"type": "object", "description": "Fields to update"},
                        },
                        "required": ["item_id", "fields"],
                    },
                ),
                Tool(
                    name="delete_item",
                    description="Delete an item",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "integer", "description": "Item ID"},
                        },
                        "required": ["item_id"],
                    },
                ),
                Tool(
                    name="get_item_children",
                    description="Get children of an item",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "integer", "description": "Item ID"},
                        },
                        "required": ["item_id"],
                    },
                ),
                Tool(
                    name="get_relationship_types",
                    description="Get all relationship types",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="get_item_upstream_relationships",
                    description="Get upstream relationships for an item",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "integer", "description": "Item ID"},
                        },
                        "required": ["item_id"],
                    },
                ),
                Tool(
                    name="get_item_downstream_relationships",
                    description="Get downstream relationships for an item",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "integer", "description": "Item ID"},
                        },
                        "required": ["item_id"],
                    },
                ),
                Tool(
                    name="get_tags",
                    description="Get all tags in a project",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project_id": {"type": "integer", "description": "Project ID"},
                        },
                        "required": ["project_id"],
                    },
                ),
                Tool(
                    name="get_item_type",
                    description="Get item type information",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "item_type_id": {"type": "integer", "description": "Item type ID"},
                        },
                        "required": ["item_type_id"],
                    },
                ),
                Tool(
                    name="get_pick_lists",
                    description="Get all pick lists (global, not project-specific)",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="get_baselines",
                    description="Get all baselines for a project",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project_id": {"type": "integer", "description": "Project ID"},
                        },
                        "required": ["project_id"],
                    },
                ),
                Tool(
                    name="get_baseline",
                    description="Get a specific baseline by ID",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "baseline_id": {"type": "integer", "description": "Baseline ID"},
                        },
                        "required": ["baseline_id"],
                    },
                ),
                Tool(
                    name="get_current_user",
                    description="Get information about the current authenticated user",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="get_users",
                    description="Get all users in the system",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="get_item_versions",
                    description="Get version history for an item",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "integer", "description": "Item ID"},
                        },
                        "required": ["item_id"],
                    },
                ),
                Tool(
                    name="get_item_tags",
                    description="Get tags associated with an item",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "integer", "description": "Item ID"},
                        },
                        "required": ["item_id"],
                    },
                ),
                Tool(
                    name="post_item_tag",
                    description="Add a tag to an item",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "integer", "description": "Item ID"},
                            "tag_id": {"type": "integer", "description": "Tag ID"},
                        },
                        "required": ["item_id", "tag_id"],
                    },
                ),
                Tool(
                    name="get_item_workflow_transitions",
                    description="Get available workflow transitions for an item",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "integer", "description": "Item ID"},
                        },
                        "required": ["item_id"],
                    },
                ),
                Tool(
                    name="get_attachment",
                    description="Get attachment metadata by ID",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "attachment_id": {"type": "integer", "description": "Attachment ID"},
                        },
                        "required": ["attachment_id"],
                    },
                ),
                Tool(
                    name="get_filter_results",
                    description="Execute a saved filter and get results",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "filter_id": {"type": "integer", "description": "Filter ID"},
                        },
                        "required": ["filter_id"],
                    },
                ),
                Tool(
                    name="create_relationship",
                    description="Create a relationship (traceability link) between two items",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "from_item": {"type": "integer", "description": "Source item ID"},
                            "to_item": {"type": "integer", "description": "Target item ID"},
                            "relationship_type": {
                                "type": "integer",
                                "description": "Relationship type ID. Omit for default 'Related to'.",
                            },
                        },
                        "required": ["from_item", "to_item"],
                    },
                ),
                Tool(
                    name="create_test_plan",
                    description="Create a new test plan in a project",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project_id": {"type": "integer", "description": "Project ID"},
                            "name": {"type": "string", "description": "Test plan name"},
                            "description": {
                                "type": "string",
                                "description": "Test plan description (optional)",
                            },
                            "start_date": {
                                "type": "string",
                                "description": "Start date YYYY-MM-DD (optional)",
                            },
                            "end_date": {
                                "type": "string",
                                "description": "End date YYYY-MM-DD (optional)",
                            },
                        },
                        "required": ["project_id", "name"],
                    },
                ),
                Tool(
                    name="get_test_cycle",
                    description="Get a specific test cycle by ID",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "test_cycle_id": {"type": "integer", "description": "Test cycle ID"},
                        },
                        "required": ["test_cycle_id"],
                    },
                ),
                Tool(
                    name="get_test_runs",
                    description="Get test runs for a test cycle",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "test_cycle_id": {"type": "integer", "description": "Test cycle ID"},
                        },
                        "required": ["test_cycle_id"],
                    },
                ),
                Tool(
                    name="create_test_cycle",
                    description="Create a test cycle under a test plan",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "testplan_id": {"type": "integer", "description": "Test plan ID"},
                            "name": {"type": "string", "description": "Test cycle name"},
                            "start_date": {
                                "type": "string",
                                "description": "Start date (YYYY-MM-DD)",
                            },
                            "end_date": {
                                "type": "string",
                                "description": "End date (YYYY-MM-DD)",
                            },
                            "testgroups_to_include": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "Test group IDs to include (optional)",
                            },
                            "testrun_status_to_include": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Test run statuses to include (optional)",
                            },
                        },
                        "required": ["testplan_id", "name", "start_date", "end_date"],
                    },
                ),
                Tool(
                    name="update_test_run",
                    description="Update a test run (e.g. set status/result)",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "test_run_id": {"type": "integer", "description": "Test run ID"},
                            "data": {"type": "object", "description": "Test run data to update"},
                        },
                        "required": ["test_run_id", "data"],
                    },
                ),
            ]

        @self.mcp.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            """Execute a tool with the given arguments."""
            try:
                if not self.jama_client:
                    raise RuntimeError("Jama client not initialized")

                result = await self._execute_tool(name, arguments)

                return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

            except Exception as e:
                logger.error(f"Error executing tool {name}: {e}")
                return [TextContent(type="text", text=json.dumps({"error": str(e), "tool": name}))]

    async def _execute_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Execute the specified tool with arguments.

        Args:
            name: Tool name to execute
            arguments: Tool arguments

        Returns:
            Tool execution result

        Raises:
            ValueError: If tool is unknown
            RuntimeError: If Jama client is not initialized
        """
        if not self.jama_client:
            raise RuntimeError("Jama client not initialized")

        # Run synchronous Jama client methods in executor
        loop = asyncio.get_running_loop()

        if name == "get_projects":
            return await loop.run_in_executor(None, self.jama_client.get_projects)

        elif name == "get_project":

            def get_single_project() -> Any:
                projects = self.jama_client.get_projects()  # type: ignore[union-attr]
                project_id = arguments["project_id"]
                return next((p for p in projects if p["id"] == project_id), None)

            return await loop.run_in_executor(None, get_single_project)

        elif name == "get_item":
            return await loop.run_in_executor(None, self.jama_client.get_item, arguments["item_id"])

        elif name == "get_items":
            return await loop.run_in_executor(
                None, self.jama_client.get_items, arguments["project_id"]
            )

        elif name == "create_item":
            return await loop.run_in_executor(
                None,
                self.jama_client.post_item,
                arguments["project_id"],
                arguments["item_type_id"],
                arguments.get("child_item_type_id"),
                arguments["location"],
                arguments["fields"],
            )

        elif name == "update_item":
            # Use patch_item for updates
            def update_fn() -> Any:
                patches = []
                for field, value in arguments["fields"].items():
                    patches.append({"op": "replace", "path": f"/fields/{field}", "value": value})
                return self.jama_client.patch_item(arguments["item_id"], patches)

            return await loop.run_in_executor(None, update_fn)

        elif name == "delete_item":
            return await loop.run_in_executor(
                None, self.jama_client.delete_item, arguments["item_id"]
            )

        elif name == "get_item_children":
            return await loop.run_in_executor(
                None, self.jama_client.get_item_children, arguments["item_id"]
            )

        elif name == "get_relationship_types":
            return await loop.run_in_executor(None, self.jama_client.get_relationship_types)

        elif name == "get_item_upstream_relationships":
            return await loop.run_in_executor(
                None, self.jama_client.get_items_upstream_relationships, arguments["item_id"]
            )

        elif name == "get_item_downstream_relationships":
            return await loop.run_in_executor(
                None, self.jama_client.get_items_downstream_relationships, arguments["item_id"]
            )

        elif name == "get_tags":
            return await loop.run_in_executor(
                None, self.jama_client.get_tags, arguments["project_id"]
            )

        elif name == "get_item_type":
            return await loop.run_in_executor(
                None, self.jama_client.get_item_type, arguments["item_type_id"]
            )

        elif name == "get_pick_lists":
            return await loop.run_in_executor(None, self.jama_client.get_pick_lists)

        elif name == "get_baselines":
            return await loop.run_in_executor(
                None, self.jama_client.get_baselines, arguments["project_id"]
            )

        elif name == "get_baseline":
            return await loop.run_in_executor(
                None, self.jama_client.get_baseline, arguments["baseline_id"]
            )

        elif name == "get_current_user":
            return await loop.run_in_executor(None, self.jama_client.get_current_user)

        elif name == "get_users":
            return await loop.run_in_executor(None, self.jama_client.get_users)

        elif name == "get_item_versions":
            return await loop.run_in_executor(
                None, self.jama_client.get_item_versions, arguments["item_id"]
            )

        elif name == "get_item_tags":
            return await loop.run_in_executor(
                None, self.jama_client.get_item_tags, arguments["item_id"]
            )

        elif name == "post_item_tag":
            return await loop.run_in_executor(
                None, self.jama_client.post_item_tag, arguments["item_id"], arguments["tag_id"]
            )

        elif name == "get_item_workflow_transitions":
            return await loop.run_in_executor(
                None, self.jama_client.get_item_workflow_transitions, arguments["item_id"]
            )

        elif name == "get_attachment":
            return await loop.run_in_executor(
                None, self.jama_client.get_attachment, arguments["attachment_id"]
            )

        elif name == "get_filter_results":
            return await loop.run_in_executor(
                None, self.jama_client.get_filter_results, arguments["filter_id"]
            )

        elif name == "create_relationship":
            return await loop.run_in_executor(
                None,
                self.jama_client.post_relationship,
                arguments["from_item"],
                arguments["to_item"],
                arguments.get("relationship_type"),
            )

        elif name == "create_test_plan":

            def _create_test_plan() -> int:
                """Bypass py_jama_rest_client (no upstream method) — POST /testplans directly."""
                fields: dict[str, Any] = {"name": arguments["name"]}
                if arguments.get("description"):
                    fields["description"] = arguments["description"]
                if arguments.get("start_date"):
                    fields["startDate"] = arguments["start_date"]
                if arguments.get("end_date"):
                    fields["endDate"] = arguments["end_date"]

                body = {"project": arguments["project_id"], "fields": fields}
                headers = {"content-type": "application/json"}
                response = self.jama_client._JamaClient__core.post(  # type: ignore[union-attr]
                    "testplans", data=json.dumps(body), headers=headers
                )
                if not (200 <= response.status_code < 300):
                    msg = response.json().get("meta", {}).get("message", "Unknown error")
                    raise RuntimeError(f"POST testplans failed [{response.status_code}]: {msg}")
                return int(response.json()["meta"]["id"])

            return await loop.run_in_executor(None, _create_test_plan)

        elif name == "get_test_cycle":
            return await loop.run_in_executor(
                None, self.jama_client.get_test_cycle, arguments["test_cycle_id"]
            )

        elif name == "get_test_runs":
            return await loop.run_in_executor(
                None, self.jama_client.get_testruns, arguments["test_cycle_id"]
            )

        elif name == "create_test_cycle":
            return await loop.run_in_executor(
                None,
                self.jama_client.post_testplans_testcycles,
                arguments["testplan_id"],
                arguments["name"],
                arguments["start_date"],
                arguments["end_date"],
                arguments.get("testgroups_to_include"),
                arguments.get("testrun_status_to_include"),
            )

        elif name == "update_test_run":
            return await loop.run_in_executor(
                None,
                self.jama_client.put_test_run,
                arguments["test_run_id"],
                arguments["data"],
            )

        else:
            raise ValueError(f"Unknown tool: {name}")

    async def initialize_client(self):
        """Initialize the Jama client."""
        try:
            logger.info(f"Initializing Jama client for {self.config.url}")

            # Use OAuth client credentials if provided
            if self.config.client_id and self.config.client_secret:
                logger.info("Using OAuth client credentials authentication")
                self.jama_client = JamaClient(
                    host_domain=self.config.url,
                    credentials=(self.config.client_id, self.config.client_secret),
                    oauth=True,
                )
            # Use API key if provided
            elif self.config.api_key:
                logger.info("Using API key authentication")
                self.jama_client = JamaClient(
                    host_domain=self.config.url, credentials=(self.config.api_key,)
                )
            # Fall back to username/password
            else:
                logger.info("Using username/password authentication")
                self.jama_client = JamaClient(
                    host_domain=self.config.url,
                    credentials=(self.config.username, self.config.password),
                    oauth=self.config.oauth,
                )

            logger.info("Jama client initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Jama client: {e}")
            raise

    async def run(self):
        """Run the stdio MCP server."""
        from mcp.server.stdio import stdio_server

        # Initialize Jama client
        await self.initialize_client()

        logger.info("Starting Jama stdio MCP server")

        async with stdio_server() as (read_stream, write_stream):
            await self.mcp.run(read_stream, write_stream, self.mcp.create_initialization_options())
