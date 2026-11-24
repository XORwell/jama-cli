"""Tests for the stdio MCP tools that expose the remaining JamaApi methods."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from mcp import types

from jama_mcp_server.core.stdio_server import JamaStdioMCPServer
from jama_mcp_server.models import JamaConfig

# tool name, arguments, expected JamaApi method, expected positional args, expected kwargs
CASES: list[tuple[str, dict[str, Any], str, tuple[Any, ...], dict[str, Any]]] = [
    ("get_items_page", {"project_id": 1}, "get_items_page", (1, 0, 50), {}),
    (
        "get_items_page",
        {"project_id": 1, "start_at": 100, "max_results": 20},
        "get_items_page",
        (1, 100, 20),
        {},
    ),
    (
        "search_items",
        {"contains": "brake", "project_id": 1, "item_type_id": 5},
        "get_abstract_items",
        (),
        {"project": 1, "item_type": 5, "contains": "brake"},
    ),
    (
        "search_items",
        {"contains": "brake"},
        "get_abstract_items",
        (),
        {"project": None, "item_type": None, "contains": "brake"},
    ),
    (
        "replace_item",
        {
            "project_id": 1,
            "item_id": 2,
            "item_type_id": 3,
            "location": {"item": 4},
            "fields": {"name": "n"},
        },
        "put_item",
        (1, 2, 3, None, {"item": 4}, {"name": "n"}),
        {},
    ),
    ("get_item_version", {"item_id": 2, "version_num": 7}, "get_item_version", (2, 7), {}),
    ("get_item_lock", {"item_id": 2}, "get_item_lock", (2,), {}),
    ("set_item_lock", {"item_id": 2, "locked": True}, "put_item_lock", (2, True), {}),
    ("get_relationships", {"project_id": 1}, "get_relationships", (1,), {}),
    ("get_relationship", {"relationship_id": 9}, "get_relationship", (9,), {}),
    ("get_item_upstream_related", {"item_id": 2}, "get_items_upstream_related", (2,), {}),
    ("get_item_downstream_related", {"item_id": 2}, "get_items_downstream_related", (2,), {}),
    ("delete_relationship", {"relationship_id": 9}, "delete_relationship", (9,), {}),
    ("get_relationship_type", {"relationship_type_id": 4}, "get_relationship_type", (4,), {}),
    ("get_item_types", {}, "get_item_types", (), {}),
    ("get_pick_list", {"pick_list_id": 6}, "get_pick_list", (6,), {}),
    ("get_pick_list_options", {"pick_list_id": 6}, "get_pick_list_options", (6,), {}),
    ("get_tagged_items", {"tag_id": 8}, "get_tagged_items", (8,), {}),
    ("create_tag", {"name": "safety", "project_id": 1}, "post_tag", ("safety", 1), {}),
    (
        "get_baseline_versioned_items",
        {"baseline_id": 3},
        "get_baselines_versioneditems",
        (3,),
        {},
    ),
    ("get_user", {"user_id": 11}, "get_user", (11,), {}),
    ("get_filter_results", {"filter_id": 5}, "get_filter_results", (5, None), {}),
    (
        "get_filter_results",
        {"filter_id": 5, "project_id": 1},
        "get_filter_results",
        (5, 1),
        {},
    ),
]

WRITE_TOOLS = {"replace_item", "set_item_lock", "delete_relationship", "create_tag"}


@pytest.fixture
def server() -> JamaStdioMCPServer:
    server = JamaStdioMCPServer(JamaConfig(url="https://jama.example.com", api_key="k"))
    server._api = AsyncMock()
    return server


async def _listed_tools(server: JamaStdioMCPServer) -> list[types.Tool]:
    handler = server.mcp.request_handlers[types.ListToolsRequest]
    result = await handler(types.ListToolsRequest(method="tools/list"))
    return list(result.root.tools)


@pytest.mark.parametrize(("tool", "arguments", "method", "args", "kwargs"), CASES)
async def test_tool_calls_api_method(
    server: JamaStdioMCPServer,
    tool: str,
    arguments: dict[str, Any],
    method: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    api_method = getattr(server._api, method)
    api_method.return_value = {"ok": True}

    result = await server._execute_tool(tool, arguments)

    assert result == {"ok": True}
    api_method.assert_awaited_once_with(*args, **kwargs)


async def test_new_tools_are_listed_with_valid_schemas(server: JamaStdioMCPServer) -> None:
    tools = {tool.name: tool for tool in await _listed_tools(server)}
    assert len(tools) == len(await _listed_tools(server)), "duplicate tool names"

    for name, arguments, _method, _args, _kwargs in CASES:
        assert name in tools, f"{name} is not listed"
        schema = tools[name].inputSchema
        assert set(arguments) <= set(schema["properties"])
        assert set(schema.get("required", [])) <= set(schema["properties"])


async def test_write_tools_say_they_modify_jama(server: JamaStdioMCPServer) -> None:
    tools = {tool.name: tool for tool in await _listed_tools(server)}
    for name in WRITE_TOOLS:
        assert "Modifies Jama" in (tools[name].description or "")


async def test_every_listed_tool_is_dispatched(server: JamaStdioMCPServer) -> None:
    """A tool that is listed but not handled would fail with 'Unknown tool'."""
    samples: dict[str, Any] = {"integer": 1, "string": "x", "object": {}, "boolean": True}
    for tool in await _listed_tools(server):
        properties = tool.inputSchema.get("properties", {})
        arguments = {
            key: samples.get(properties[key].get("type"), 1)
            for key in tool.inputSchema.get("required", [])
        }
        try:
            await server._execute_tool(tool.name, arguments)
        except ValueError as e:
            assert "Unknown tool" not in str(e), f"{tool.name} is listed but not dispatched"
