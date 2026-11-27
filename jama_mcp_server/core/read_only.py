"""Read-only mode of the MCP servers: which tools may run, and a guard for py-jama-rest-client.

Two layers keep a read-only server from changing Jama:

1. Tool layer (this module's lists). Only tools and intents on the read lists
   are listed and dispatched. Every tool must be on exactly one of the two lists
   of its server; a test fails when a new tool is not classified, so a new
   tool is never allowed by accident.
2. Transport layer. ``JamaHttpClient(read_only=True)`` refuses every request
   other than GET/HEAD/OPTIONS before sending it, and :func:`guard_jama_client`
   does the same for the py-jama-rest-client session the HTTP server uses. It
   holds even if a tool is classified wrongly.
"""

from __future__ import annotations

from typing import Any

import requests
from requests.adapters import BaseAdapter

from jama_cli.core.exceptions import ReadOnlyModeError
from jama_cli.core.read_only import SAFE_METHODS, refusal_message

# Shared attachment / test run tools (both servers).
SHARED_READ_TOOLS: frozenset[str] = frozenset(
    {
        "get_test_run",
        # Reads from Jama; may write a local file where local paths are allowed.
        "download_attachment",
    }
)
SHARED_WRITE_TOOLS: frozenset[str] = frozenset(
    {"update_test_run", "upload_attachment", "attach_screenshot_to_test_run"}
)

# Tools of the stdio server.
STDIO_READ_TOOLS: frozenset[str] = (
    frozenset(
        {
            # Local login session management, not Jama data.
            "get_session_status",
            "logout_session",
            "get_projects",
            "get_project",
            "get_item",
            "get_items",
            "get_items_page",
            "search_items",
            "get_item_children",
            "get_item_type",
            "get_item_types",
            "get_item_versions",
            "get_item_version",
            "get_item_lock",
            "get_item_tags",
            "get_item_workflow_transitions",
            "get_relationship_types",
            "get_relationship_type",
            "get_relationships",
            "get_relationship",
            "get_item_upstream_relationships",
            "get_item_downstream_relationships",
            "get_item_upstream_related",
            "get_item_downstream_related",
            "get_tags",
            "get_tagged_items",
            "get_pick_lists",
            "get_pick_list",
            "get_pick_list_options",
            "get_baselines",
            "get_baseline",
            "get_baseline_versioned_items",
            "get_current_user",
            "get_users",
            "get_user",
            "get_attachment",
            "get_filter_results",
            "get_test_cycle",
            "get_test_runs",
        }
    )
    | SHARED_READ_TOOLS
)
STDIO_WRITE_TOOLS: frozenset[str] = (
    frozenset(
        {
            "create_item",
            "update_item",
            "replace_item",
            "delete_item",
            "set_item_lock",
            "post_item_tag",
            "create_tag",
            "create_relationship",
            "delete_relationship",
            "create_test_plan",
            "create_test_cycle",
        }
    )
    | SHARED_WRITE_TOOLS
)

# Intents of the HTTP server (``parameters.intent`` or parsed from the prompt).
HTTP_READ_INTENTS: frozenset[str] = (
    frozenset(
        {
            "get_projects",
            "get_project_by_id",
            "get_items",
            "get_item_by_id",
            "get_item_types",
            "get_item_type",
            "get_item_children",
            "get_item_versions",
            "get_item_version",
            "get_versioned_item",
            "get_abstract_items",
            "get_abstract_items_from_doc_key",
            "get_abstract_item_versions",
            "get_abstract_versioned_item",
            "get_item_lock",
            "get_item_tags",
            "get_item_workflow_transitions",
            "get_items_synceditems",
            "get_items_synceditems_status",
            "get_relationships",
            "get_relationship",
            "get_item_upstream_relationships",
            "get_item_downstream_relationships",
            "get_item_upstream_related",
            "get_item_downstream_related",
            "get_relationship_rule_sets",
            "get_relationship_rule_set",
            "get_relationship_rule_set_projects",
            "get_pick_lists",
            "get_pick_list",
            "get_pick_list_options",
            "get_pick_list_option",
            "get_tags",
            "get_tagged_items",
            "get_test_cycle",
            "get_test_runs",
            "get_attachment",
            "get_baselines",
            "get_baseline",
            "get_baselines_versioneditems",
            "get_current_user",
            "get_user",
            "get_users",
            "get_filter_results",
        }
    )
    | SHARED_READ_TOOLS
)
HTTP_WRITE_INTENTS: frozenset[str] = (
    frozenset(
        {
            "create_item",
            "update_item",
            "patch_item",
            "delete_item",
            "put_item_lock",
            "post_item_tag",
            "post_tag",
            "post_item_sync",
            "post_item_attachment",
            "post_project_attachment",
            "put_attachments_file",
            "post_testplans_testcycles",
            "put_test_run",
            "post_user",
            "put_user",
            "put_user_active",
        }
    )
    | SHARED_WRITE_TOOLS
)


def check_tool(name: str, allowed: frozenset[str]) -> None:
    """Refuse a tool that is not on the read list of a read-only server."""
    if name not in allowed:
        raise ReadOnlyModeError(refusal_message(f"the tool '{name}'"))


class ReadOnlyAdapter(BaseAdapter):
    """A requests adapter that refuses every method other than GET/HEAD/OPTIONS.

    It wraps the adapter it replaces, so allowed requests are sent unchanged.
    """

    def __init__(self, inner: BaseAdapter) -> None:
        super().__init__()
        self.inner = inner

    def send(  # type: ignore[override]
        self, request: requests.PreparedRequest, **kwargs: Any
    ) -> requests.Response:
        method = (request.method or "").upper()
        if method not in SAFE_METHODS:
            raise ReadOnlyModeError(refusal_message(f"{method} {request.path_url}"))
        return self.inner.send(request, **kwargs)

    def close(self) -> None:
        self.inner.close()


def guard_jama_client(client: Any) -> None:
    """Make a py-jama-rest-client ``JamaClient`` refuse every request that could change Jama.

    The library keeps its ``requests.Session`` in private attributes. If they
    are not where this expects them, read-only mode cannot be enforced and this
    raises instead of letting the server start without the guard.
    """
    core = getattr(client, "_JamaClient__core", None)
    session = getattr(core, "_Core__session", None)
    if not isinstance(session, requests.Session):
        raise RuntimeError(
            "Cannot enforce read-only mode: the py-jama-rest-client session was not found "
            "(the library's internals changed). Refusing to start."
        )
    for prefix, adapter in list(session.adapters.items()):
        if not isinstance(adapter, ReadOnlyAdapter):
            session.mount(prefix, ReadOnlyAdapter(adapter))
