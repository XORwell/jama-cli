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
                            "fields": {"type": "object", "description": "Item fields"},
                        },
                        "required": ["project_id", "item_type_id", "fields"],
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
                    name="get_relationships",
                    description="Get all relationship types",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="get_item_relationships",
                    description="Get relationships for an item",
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
                    description="Get all pick lists in a project",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project_id": {"type": "integer", "description": "Project ID"},
                        },
                        "required": ["project_id"],
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
            return await loop.run_in_executor(
                None, self.jama_client.get_project, arguments["project_id"]
            )

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
                None, self.jama_client.get_items_children, arguments["item_id"]
            )

        elif name == "get_relationships":
            return await loop.run_in_executor(None, self.jama_client.get_relationship_types)

        elif name == "get_item_relationships":
            return await loop.run_in_executor(
                None, self.jama_client.get_relationships, arguments["item_id"]
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
            return await loop.run_in_executor(
                None, self.jama_client.get_pick_lists, arguments["project_id"]
            )

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
