"""Synchronous wrapper around JamaApi for CLI use.

Runs an asyncio event loop on a background daemon thread and dispatches
all async API calls to it via run_coroutine_threadsafe. This avoids
creating a new event loop per call and allows httpx connection reuse.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from jama_cli.core.api import JamaApi
from jama_cli.core.http_client import JamaHttpClient


class SyncJamaApi:
    """Synchronous facade over JamaApi for CLI use.

    Usage:
        api = SyncJamaApi.from_credentials(url, credentials, oauth=True)
        projects = api.get_projects()
        api.close()
    """

    def __init__(self, api: JamaApi, http: JamaHttpClient) -> None:
        self._api = api
        self._http = http
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    @classmethod
    def from_credentials(
        cls,
        base_url: str,
        credentials: tuple[str, str],
        oauth: bool = False,
        timeout: float = 30.0,
    ) -> SyncJamaApi:
        """Create a SyncJamaApi from connection credentials."""
        http = JamaHttpClient(
            base_url=base_url,
            credentials=credentials,
            oauth=oauth,
            timeout=timeout,
        )
        api = JamaApi(http)
        return cls(api, http)

    def _run(self, coro: Any) -> Any:
        """Run an async coroutine synchronously via the background event loop."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def close(self) -> None:
        """Shut down the background event loop and HTTP client."""
        asyncio.run_coroutine_threadsafe(self._http.close(), self._loop).result()
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)

    # =========================================================================
    # Projects
    # =========================================================================

    def get_projects(self) -> list[dict[str, Any]]:
        return self._run(self._api.get_projects())

    def get_project(self, project_id: int) -> dict[str, Any]:
        return self._run(self._api.get_project(project_id))

    # =========================================================================
    # Items
    # =========================================================================

    def get_items(self, project_id: int) -> list[dict[str, Any]]:
        return self._run(self._api.get_items(project_id))

    def get_items_page(
        self,
        project_id: int,
        start_at: int = 0,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        return self._run(self._api.get_items_page(project_id, start_at, max_results))

    def get_item(self, item_id: int) -> dict[str, Any]:
        return self._run(self._api.get_item(item_id))

    def get_item_children(self, item_id: int) -> list[dict[str, Any]]:
        return self._run(self._api.get_item_children(item_id))

    def post_item(
        self,
        project: int,
        item_type_id: int,
        child_item_type_id: int | None,
        location: dict[str, Any],
        fields: dict[str, Any],
        global_id: str | None = None,
    ) -> int:
        return self._run(
            self._api.post_item(
                project, item_type_id, child_item_type_id, location, fields, global_id
            )
        )

    def patch_item(self, item_id: int, patches: list[dict[str, Any]]) -> int:
        return self._run(self._api.patch_item(item_id, patches))

    def delete_item(self, item_id: int) -> int:
        return self._run(self._api.delete_item(item_id))

    # =========================================================================
    # Item Versions
    # =========================================================================

    def get_item_versions(self, item_id: int) -> list[dict[str, Any]]:
        return self._run(self._api.get_item_versions(item_id))

    def get_item_version(self, item_id: int, version_num: int) -> dict[str, Any]:
        return self._run(self._api.get_item_version(item_id, version_num))

    # =========================================================================
    # Relationships
    # =========================================================================

    def get_relationships(self, project_id: int) -> list[dict[str, Any]]:
        return self._run(self._api.get_relationships(project_id))

    def get_relationship(self, relationship_id: int) -> dict[str, Any]:
        return self._run(self._api.get_relationship(relationship_id))

    def get_items_upstream_relationships(self, item_id: int) -> list[dict[str, Any]]:
        return self._run(self._api.get_items_upstream_relationships(item_id))

    def get_items_downstream_relationships(self, item_id: int) -> list[dict[str, Any]]:
        return self._run(self._api.get_items_downstream_relationships(item_id))

    def get_items_upstream_related(self, item_id: int) -> list[dict[str, Any]]:
        return self._run(self._api.get_items_upstream_related(item_id))

    def get_items_downstream_related(self, item_id: int) -> list[dict[str, Any]]:
        return self._run(self._api.get_items_downstream_related(item_id))

    def post_relationship(
        self,
        from_item: int,
        to_item: int,
        relationship_type: int | None = None,
    ) -> int:
        return self._run(self._api.post_relationship(from_item, to_item, relationship_type))

    def delete_relationship(self, relationship_id: int) -> int:
        return self._run(self._api.delete_relationship(relationship_id))

    # =========================================================================
    # Relationship Types
    # =========================================================================

    def get_relationship_types(self) -> list[dict[str, Any]]:
        return self._run(self._api.get_relationship_types())

    def get_relationship_type(self, relationship_type_id: int) -> dict[str, Any]:
        return self._run(self._api.get_relationship_type(relationship_type_id))

    # =========================================================================
    # Item Types
    # =========================================================================

    def get_item_types(self) -> list[dict[str, Any]]:
        return self._run(self._api.get_item_types())

    def get_item_type(self, item_type_id: int) -> dict[str, Any]:
        return self._run(self._api.get_item_type(item_type_id))

    # =========================================================================
    # Pick Lists
    # =========================================================================

    def get_pick_lists(self) -> list[dict[str, Any]]:
        return self._run(self._api.get_pick_lists())

    def get_pick_list(self, pick_list_id: int) -> dict[str, Any]:
        return self._run(self._api.get_pick_list(pick_list_id))

    def get_pick_list_options(self, pick_list_id: int) -> list[dict[str, Any]]:
        return self._run(self._api.get_pick_list_options(pick_list_id))

    # =========================================================================
    # Tags
    # =========================================================================

    def get_tags(self, project_id: int) -> list[dict[str, Any]]:
        return self._run(self._api.get_tags(project_id))

    def get_tagged_items(self, tag_id: int) -> list[dict[str, Any]]:
        return self._run(self._api.get_tagged_items(tag_id))

    def get_item_tags(self, item_id: int) -> list[dict[str, Any]]:
        return self._run(self._api.get_item_tags(item_id))

    def post_item_tag(self, item_id: int, tag_id: int) -> int:
        return self._run(self._api.post_item_tag(item_id, tag_id))

    # =========================================================================
    # Tests
    # =========================================================================

    def get_test_cycle(self, test_cycle_id: int) -> dict[str, Any]:
        return self._run(self._api.get_test_cycle(test_cycle_id))

    def get_testruns(self, test_cycle_id: int) -> list[dict[str, Any]]:
        return self._run(self._api.get_testruns(test_cycle_id))

    def create_test_plan(
        self,
        project_id: int,
        name: str,
        description: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        return self._run(
            self._api.create_test_plan(project_id, name, description, start_date, end_date)
        )

    def post_testplans_testcycles(
        self,
        testplan_id: int,
        testcycle_name: str,
        start_date: str,
        end_date: str,
        testgroups_to_include: list[int] | None = None,
        testrun_status_to_include: list[str] | None = None,
    ) -> int:
        return self._run(
            self._api.post_testplans_testcycles(
                testplan_id,
                testcycle_name,
                start_date,
                end_date,
                testgroups_to_include,
                testrun_status_to_include,
            )
        )

    def put_test_run(self, test_run_id: int, data: dict[str, Any] | None = None) -> int:
        return self._run(self._api.put_test_run(test_run_id, data))

    # =========================================================================
    # Baselines
    # =========================================================================

    def get_baselines(self, project_id: int) -> list[dict[str, Any]]:
        return self._run(self._api.get_baselines(project_id))

    def get_baseline(self, baseline_id: int) -> dict[str, Any]:
        return self._run(self._api.get_baseline(baseline_id))

    def get_baselines_versioneditems(self, baseline_id: int) -> list[dict[str, Any]]:
        return self._run(self._api.get_baselines_versioneditems(baseline_id))

    # =========================================================================
    # Users
    # =========================================================================

    def get_users(self) -> list[dict[str, Any]]:
        return self._run(self._api.get_users())

    def get_current_user(self) -> dict[str, Any]:
        return self._run(self._api.get_current_user())

    # =========================================================================
    # Attachments
    # =========================================================================

    def get_attachment(self, attachment_id: int) -> dict[str, Any]:
        return self._run(self._api.get_attachment(attachment_id))

    def post_item_attachment(self, item_id: int, attachment_id: int) -> int:
        return self._run(self._api.post_item_attachment(item_id, attachment_id))

    # =========================================================================
    # Workflow
    # =========================================================================

    def get_item_workflow_transitions(self, item_id: int) -> list[dict[str, Any]]:
        return self._run(self._api.get_item_workflow_transitions(item_id))

    # =========================================================================
    # Filters
    # =========================================================================

    def get_filter_results(
        self,
        filter_id: int,
        project_id: int | None = None,
    ) -> list[dict[str, Any]]:
        return self._run(self._api.get_filter_results(filter_id, project_id))

    # =========================================================================
    # Item Lock
    # =========================================================================

    def get_item_lock(self, item_id: int) -> dict[str, Any]:
        return self._run(self._api.get_item_lock(item_id))

    def put_item_lock(self, item_id: int, locked: bool) -> int:
        return self._run(self._api.put_item_lock(item_id, locked))
