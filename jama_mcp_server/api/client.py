"""
API module for the Jama MCP server.
"""

from __future__ import annotations

from typing import Any

import aiohttp
from loguru import logger

from jama_mcp_server.models import HealthCheckResponse, MCPRequest, MCPResponse


class JamaMCPClient:
    """Client for interacting with the Jama MCP server."""

    def __init__(self, url: str, api_key: str | None = None) -> None:
        """
        Initialize the Jama MCP client.

        Args:
            url: The URL of the Jama MCP server
            api_key: Optional API key for authentication
        """
        self.url = url
        self.api_key = api_key
        self.session: aiohttp.ClientSession | None = None

    async def connect(self) -> None:
        """Connect to the Jama MCP server."""
        if self.session is None:
            logger.info(f"Connecting to Jama MCP server at {self.url}")
            self.session = aiohttp.ClientSession()
            await self.health_check()

    async def disconnect(self) -> None:
        """Disconnect from the Jama MCP server."""
        if self.session:
            logger.info(f"Disconnecting from Jama MCP server at {self.url}")
            await self.session.close()
            self.session = None

    async def health_check(self) -> HealthCheckResponse:
        """
        Check if the server is healthy.

        Returns:
            Health check response
        """
        if self.session is None:
            await self.connect()

        assert self.session is not None  # for type checker

        try:
            async with self.session.get(f"{self.url}/health") as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"Health check: {data}")
                    return HealthCheckResponse(**data)
                else:
                    error_text = await response.text()
                    logger.error(f"Health check failed: {response.status} - {error_text}")
                    return HealthCheckResponse(
                        status="unhealthy",
                        jama_connected=False,
                        jama_url="",
                        error=f"Status {response.status}: {error_text}",
                    )
        except Exception as e:
            logger.error(f"Health check error: {e!s}")
            return HealthCheckResponse(
                status="unhealthy",
                jama_connected=False,
                jama_url="",
                error=str(e),
            )

    async def invoke(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
        model: str = "jama",
    ) -> MCPResponse:
        """
        Invoke the Jama MCP server.

        Args:
            prompt: The prompt describing the Jama operation to perform
            parameters: Additional parameters for the operation
            model: The model to use (default is "jama")

        Returns:
            The response from the Jama MCP server
        """
        if self.session is None:
            await self.connect()

        assert self.session is not None  # for type checker

        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = MCPRequest(prompt=prompt, model=model, parameters=parameters or {})

        try:
            async with self.session.post(
                f"{self.url}/v1/invoke",
                json=request.model_dump(),
                headers=headers,
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return MCPResponse(**data)
                else:
                    error_text = await response.text()
                    logger.error(f"Invoke error: {response.status} - {error_text}")
                    return MCPResponse(
                        response=f"Error: {error_text}",
                        metadata={"error": f"Status {response.status}: {error_text}"},
                    )
        except Exception as e:
            logger.error(f"Invoke exception: {e!s}")
            return MCPResponse(response=f"Error: {e!s}", metadata={"error": str(e)})

    # Convenience methods for common Jama operations

    async def get_projects(self) -> MCPResponse:
        """
        Get all projects from Jama.

        Returns:
            Response with project data
        """
        return await self.invoke("Get all projects", {"intent": "get_projects"})

    async def get_project(self, project_id: int) -> MCPResponse:
        """
        Get a project by ID.

        Args:
            project_id: The ID of the project

        Returns:
            Response with project data
        """
        return await self.invoke(
            f"Get project with ID {project_id}",
            {"intent": "get_project_by_id", "project_id": project_id},
        )

    async def get_items(self, project_id: int) -> MCPResponse:
        """
        Get all items in a project.

        Args:
            project_id: The ID of the project

        Returns:
            Response with items data
        """
        return await self.invoke(
            f"Get all items in project {project_id}",
            {"intent": "get_items", "project_id": project_id},
        )

    async def get_item(self, item_id: int) -> MCPResponse:
        """
        Get an item by ID.

        Args:
            item_id: The ID of the item

        Returns:
            Response with item data
        """
        return await self.invoke(
            f"Get item with ID {item_id}",
            {"intent": "get_item_by_id", "item_id": item_id},
        )

    async def create_item(
        self,
        project_id: int,
        item_type_id: int,
        child_item_type_id: int,
        location: dict[str, Any],
        fields: dict[str, Any],
    ) -> MCPResponse:
        """
        Create a new item in Jama.

        Args:
            project_id: The ID of the project
            item_type_id: The ID of the item type
            child_item_type_id: The ID of the child item type
            location: Location information
            fields: Fields to set on the item

        Returns:
            Response with created item data
        """
        return await self.invoke(
            f"Create new item in project {project_id}",
            {
                "intent": "create_item",
                "project_id": project_id,
                "item_type_id": item_type_id,
                "child_item_type_id": child_item_type_id,
                "location": location,
                "fields": fields,
            },
        )

    async def update_item(self, item_id: int, fields: dict[str, Any]) -> MCPResponse:
        """
        Update an item in Jama.

        Args:
            item_id: The ID of the item to update
            fields: Fields to update

        Returns:
            Response with updated item data
        """
        return await self.invoke(
            f"Update item with ID {item_id}",
            {"intent": "update_item", "item_id": item_id, "fields": fields},
        )

    async def patch_item(self, item_id: int, patches: list[dict[str, Any]]) -> MCPResponse:
        """
        Patch an item in Jama.

        Args:
            item_id: The ID of the item to patch
            patches: List of JSON patches

        Returns:
            Response with patched item data
        """
        return await self.invoke(
            f"Patch item with ID {item_id}",
            {"intent": "patch_item", "item_id": item_id, "patches": patches},
        )

    async def delete_item(self, item_id: int) -> MCPResponse:
        """
        Delete an item from Jama.

        Args:
            item_id: The ID of the item to delete

        Returns:
            Response with deletion status
        """
        return await self.invoke(
            f"Delete item with ID {item_id}",
            {"intent": "delete_item", "item_id": item_id},
        )
