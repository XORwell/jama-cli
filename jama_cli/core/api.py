"""Typed async API methods for the Jama REST API.

Thin layer over JamaHttpClient that maps Jama domain operations to HTTP calls.
Replaces all ~60 methods from py_jama_rest_client.client.JamaClient.
"""

from __future__ import annotations

import json
from typing import Any

from jama_cli.core.http_client import JamaHttpClient


class JamaApi:
    """Async Jama REST API with typed methods."""

    def __init__(self, http: JamaHttpClient) -> None:
        self._http = http

    # =========================================================================
    # Projects
    # =========================================================================

    async def get_projects(self) -> list[dict[str, Any]]:
        """Get all accessible projects."""
        return await self._http.get_all("projects")

    async def get_project(self, project_id: int) -> dict[str, Any]:
        """Get a specific project by ID."""
        data = await self._http.get(f"projects/{project_id}")
        return data.get("data", data)

    # =========================================================================
    # Items
    # =========================================================================

    async def get_items(self, project_id: int) -> list[dict[str, Any]]:
        """Get all items in a project."""
        return await self._http.get_all("items", params={"project": project_id})

    async def get_items_page(
        self,
        project_id: int,
        start_at: int = 0,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        """Get a single page of items (faster than fetching all)."""
        return await self._http.get_page(
            "items",
            params={"project": project_id},
            start_at=start_at,
            max_results=max_results,
        )

    async def get_item(self, item_id: int) -> dict[str, Any]:
        """Get a specific item by ID."""
        data = await self._http.get(f"items/{item_id}")
        return data.get("data", data)

    async def get_item_children(self, item_id: int) -> list[dict[str, Any]]:
        """Get children of an item."""
        return await self._http.get_all(f"items/{item_id}/children")

    async def get_abstract_items(
        self,
        project: int | None = None,
        item_type: int | None = None,
        contains: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get abstract items with optional filters."""
        params: dict[str, Any] = {}
        if project is not None:
            params["project"] = project
        if item_type is not None:
            params["itemType"] = item_type
        if contains is not None:
            params["contains"] = contains
        return await self._http.get_all("abstractitems", params=params)

    async def post_item(
        self,
        project: int,
        item_type_id: int,
        child_item_type_id: int | None,
        location: dict[str, Any],
        fields: dict[str, Any],
        global_id: str | None = None,
    ) -> int:
        """Create a new item. Returns the created item ID."""
        body: dict[str, Any] = {
            "project": project,
            "itemType": item_type_id,
            "location": {"parent": location},
            "fields": fields,
        }
        if child_item_type_id is not None:
            body["childItemType"] = child_item_type_id
        if global_id is not None:
            body["globalId"] = global_id
        resp = await self._http.post("items", json=body)
        return int(resp["meta"]["id"])

    async def patch_item(self, item_id: int, patches: list[dict[str, Any]]) -> int:
        """Update an item using JSON Patch operations."""
        resp = await self._http.patch(f"items/{item_id}", json=patches)
        return resp.get("meta", {}).get("status", 200)

    async def put_item(
        self,
        project: int,
        item_id: int,
        item_type_id: int,
        child_item_type_id: int | None,
        location: dict[str, Any],
        fields: dict[str, Any],
    ) -> int:
        """Replace an item entirely."""
        body: dict[str, Any] = {
            "project": project,
            "itemType": item_type_id,
            "location": {"parent": location},
            "fields": fields,
        }
        if child_item_type_id is not None:
            body["childItemType"] = child_item_type_id
        resp = await self._http.put(f"items/{item_id}", json=body)
        return resp.get("meta", {}).get("status", 200)

    async def delete_item(self, item_id: int) -> int:
        """Delete an item."""
        resp = await self._http.delete(f"items/{item_id}")
        return resp.get("meta", {}).get("status", 200)

    # =========================================================================
    # Item Versions
    # =========================================================================

    async def get_item_versions(self, item_id: int) -> list[dict[str, Any]]:
        """Get version history for an item."""
        return await self._http.get_all(f"items/{item_id}/versions")

    async def get_item_version(self, item_id: int, version_num: int) -> dict[str, Any]:
        """Get a specific version of an item."""
        data = await self._http.get(f"items/{item_id}/versions/{version_num}")
        return data.get("data", data)

    # =========================================================================
    # Relationships
    # =========================================================================

    async def get_relationships(self, project_id: int) -> list[dict[str, Any]]:
        """Get all relationships in a project."""
        return await self._http.get_all("relationships", params={"project": project_id})

    async def get_relationship(self, relationship_id: int) -> dict[str, Any]:
        """Get a specific relationship."""
        data = await self._http.get(f"relationships/{relationship_id}")
        return data.get("data", data)

    async def get_items_upstream_relationships(self, item_id: int) -> list[dict[str, Any]]:
        """Get upstream relationships for an item."""
        return await self._http.get_all(f"items/{item_id}/upstreamrelationships")

    async def get_items_downstream_relationships(self, item_id: int) -> list[dict[str, Any]]:
        """Get downstream relationships for an item."""
        return await self._http.get_all(f"items/{item_id}/downstreamrelationships")

    async def get_items_upstream_related(self, item_id: int) -> list[dict[str, Any]]:
        """Get upstream related items."""
        return await self._http.get_all(f"items/{item_id}/upstreamrelated")

    async def get_items_downstream_related(self, item_id: int) -> list[dict[str, Any]]:
        """Get downstream related items."""
        return await self._http.get_all(f"items/{item_id}/downstreamrelated")

    async def post_relationship(
        self,
        from_item: int,
        to_item: int,
        relationship_type: int | None = None,
    ) -> int:
        """Create a relationship between items. Returns relationship ID."""
        body: dict[str, Any] = {"fromItem": from_item, "toItem": to_item}
        if relationship_type is not None:
            body["relationshipType"] = relationship_type
        resp = await self._http.post("relationships", json=body)
        return int(resp["meta"]["id"])

    async def delete_relationship(self, relationship_id: int) -> int:
        """Delete a relationship."""
        resp = await self._http.delete(f"relationships/{relationship_id}")
        return resp.get("meta", {}).get("status", 200)

    # =========================================================================
    # Relationship Types
    # =========================================================================

    async def get_relationship_types(self) -> list[dict[str, Any]]:
        """Get all relationship types."""
        return await self._http.get_all("relationshiptypes")

    async def get_relationship_type(self, relationship_type_id: int) -> dict[str, Any]:
        """Get a specific relationship type."""
        data = await self._http.get(f"relationshiptypes/{relationship_type_id}")
        return data.get("data", data)

    # =========================================================================
    # Item Types
    # =========================================================================

    async def get_item_types(self) -> list[dict[str, Any]]:
        """Get all item types."""
        return await self._http.get_all("itemtypes")

    async def get_item_type(self, item_type_id: int) -> dict[str, Any]:
        """Get a specific item type."""
        data = await self._http.get(f"itemtypes/{item_type_id}")
        return data.get("data", data)

    # =========================================================================
    # Pick Lists
    # =========================================================================

    async def get_pick_lists(self) -> list[dict[str, Any]]:
        """Get all pick lists (global, not project-specific)."""
        return await self._http.get_all("picklists")

    async def get_pick_list(self, pick_list_id: int) -> dict[str, Any]:
        """Get a specific pick list."""
        data = await self._http.get(f"picklists/{pick_list_id}")
        return data.get("data", data)

    async def get_pick_list_options(self, pick_list_id: int) -> list[dict[str, Any]]:
        """Get options for a pick list."""
        return await self._http.get_all(f"picklists/{pick_list_id}/options")

    # =========================================================================
    # Tags
    # =========================================================================

    async def get_tags(self, project_id: int) -> list[dict[str, Any]]:
        """Get all tags in a project."""
        return await self._http.get_all("tags", params={"project": project_id})

    async def get_tagged_items(self, tag_id: int) -> list[dict[str, Any]]:
        """Get items with a specific tag."""
        return await self._http.get_all(f"tags/{tag_id}/items")

    async def get_item_tags(self, item_id: int) -> list[dict[str, Any]]:
        """Get tags for an item."""
        return await self._http.get_all(f"items/{item_id}/tags")

    async def post_item_tag(self, item_id: int, tag_id: int) -> int:
        """Add a tag to an item."""
        resp = await self._http.post(f"items/{item_id}/tags", json={"tag": tag_id})
        return resp.get("meta", {}).get("status", 200)

    async def post_tag(self, name: str, project: int) -> int:
        """Create a new tag."""
        resp = await self._http.post("tags", json={"name": name, "project": project})
        return int(resp["meta"]["id"])

    # =========================================================================
    # Tests
    # =========================================================================

    async def get_test_cycle(self, test_cycle_id: int) -> dict[str, Any]:
        """Get a specific test cycle."""
        data = await self._http.get(f"testcycles/{test_cycle_id}")
        return data.get("data", data)

    async def get_testruns(self, test_cycle_id: int) -> list[dict[str, Any]]:
        """Get test runs for a test cycle."""
        return await self._http.get_all(f"testcycles/{test_cycle_id}/testruns")

    async def create_test_plan(
        self,
        project_id: int,
        name: str,
        description: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        """Create a new test plan. Returns the test plan ID."""
        fields: dict[str, Any] = {"name": name}
        if description is not None:
            fields["description"] = description
        if start_date is not None:
            fields["startDate"] = start_date
        if end_date is not None:
            fields["endDate"] = end_date
        resp = await self._http.post("testplans", json={"project": project_id, "fields": fields})
        return int(resp["meta"]["id"])

    async def post_testplans_testcycles(
        self,
        testplan_id: int,
        testcycle_name: str,
        start_date: str,
        end_date: str,
        testgroups_to_include: list[int] | None = None,
        testrun_status_to_include: list[str] | None = None,
    ) -> int:
        """Create a test cycle under a test plan. Returns test cycle ID."""
        body: dict[str, Any] = {
            "fields": {"name": testcycle_name, "startDate": start_date, "endDate": end_date},
        }
        if testgroups_to_include is not None:
            body["testGroupsToInclude"] = testgroups_to_include
        if testrun_status_to_include is not None:
            body["testRunStatusToInclude"] = testrun_status_to_include
        resp = await self._http.post(f"testplans/{testplan_id}/testcycles", json=body)
        return int(resp["meta"]["id"])

    async def put_test_run(self, test_run_id: int, data: dict[str, Any] | None = None) -> int:
        """Update a test run."""
        resp = await self._http.put(f"testruns/{test_run_id}", json=data or {})
        return resp.get("meta", {}).get("status", 200)

    # =========================================================================
    # Baselines
    # =========================================================================

    async def get_baselines(self, project_id: int) -> list[dict[str, Any]]:
        """Get all baselines for a project."""
        return await self._http.get_all("baselines", params={"project": project_id})

    async def get_baseline(self, baseline_id: int) -> dict[str, Any]:
        """Get a specific baseline."""
        data = await self._http.get(f"baselines/{baseline_id}")
        return data.get("data", data)

    async def get_baselines_versioneditems(self, baseline_id: int) -> list[dict[str, Any]]:
        """Get versioned items in a baseline."""
        return await self._http.get_all(f"baselines/{baseline_id}/versioneditems")

    # =========================================================================
    # Users
    # =========================================================================

    async def get_users(self) -> list[dict[str, Any]]:
        """Get all users."""
        return await self._http.get_all("users")

    async def get_user(self, user_id: int) -> dict[str, Any]:
        """Get a specific user."""
        data = await self._http.get(f"users/{user_id}")
        return data.get("data", data)

    async def get_current_user(self) -> dict[str, Any]:
        """Get the current authenticated user."""
        data = await self._http.get("users/current")
        return data.get("data", data)

    # =========================================================================
    # Attachments
    # =========================================================================

    async def get_attachment(self, attachment_id: int) -> dict[str, Any]:
        """Get attachment metadata."""
        data = await self._http.get(f"attachments/{attachment_id}")
        return data.get("data", data)

    async def post_item_attachment(self, item_id: int, attachment_id: int) -> int:
        """Link an attachment to an item."""
        resp = await self._http.post(
            f"items/{item_id}/attachments", json={"attachment": attachment_id}
        )
        return resp.get("meta", {}).get("status", 200)

    # =========================================================================
    # Workflow
    # =========================================================================

    async def get_item_workflow_transitions(self, item_id: int) -> list[dict[str, Any]]:
        """Get available workflow transitions for an item."""
        data = await self._http.get(f"items/{item_id}/workflowtransitionoptions")
        return data.get("data", [])

    # =========================================================================
    # Filters
    # =========================================================================

    async def get_filter_results(
        self,
        filter_id: int,
        project_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a saved filter and get results."""
        params: dict[str, Any] = {}
        if project_id is not None:
            params["project"] = project_id
        return await self._http.get_all(f"filters/{filter_id}/results", params=params)

    # =========================================================================
    # Item Lock
    # =========================================================================

    async def get_item_lock(self, item_id: int) -> dict[str, Any]:
        """Get lock status for an item."""
        data = await self._http.get(f"items/{item_id}/lock")
        return data.get("data", data)

    async def put_item_lock(self, item_id: int, locked: bool) -> int:
        """Lock or unlock an item."""
        resp = await self._http.put(f"items/{item_id}/lock", json={"locked": locked})
        return resp.get("meta", {}).get("status", 200)
