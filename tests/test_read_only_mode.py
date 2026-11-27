"""Read-only mode: nothing that could change Jama is listed, dispatched or sent.

Two layers are tested separately, so that each one alone is shown to hold:

- the tool layer (allowlists of the stdio and the HTTP server), and
- the transport layer (``JamaHttpClient(read_only=True)`` and the guard on the
  py-jama-rest-client session), with the tool layer switched off.
"""

from __future__ import annotations

import base64
import contextlib
import copy
import inspect
import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
import requests
from mcp import types
from py_jama_rest_client.client import JamaClient as PyJamaClient
from requests.adapters import BaseAdapter
from typer.testing import CliRunner

from jama_cli.core.api import JamaApi
from jama_cli.core.attachments import UploadCache
from jama_cli.core.exceptions import ReadOnlyModeError
from jama_cli.core.http_client import JamaHttpClient
from jama_cli.core.read_only import SAFE_METHODS, parse_flag
from jama_mcp_server.core import attachment_tools, read_only
from jama_mcp_server.core.attachment_tools import AttachmentTools
from jama_mcp_server.core.server import JamaMCPServer
from jama_mcp_server.core.stdio_server import JamaStdioMCPServer
from jama_mcp_server.models import JamaConfig, MCPRequest
from tests.fake_jama_attachments import FakeJamaAttachments
from tests.test_attachments import PNG

RUN = 77
URL = "https://jama.example.com"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# Arguments for every write tool of the stdio server, valid against the fake.
STDIO_WRITE_ARGUMENTS: dict[str, dict[str, Any]] = {
    "create_item": {
        "project_id": 3,
        "item_type_id": 33,
        "location": {"item": 10},
        "fields": {"name": "x"},
    },
    "update_item": {"item_id": 10, "fields": {"name": "y"}},
    "replace_item": {
        "project_id": 3,
        "item_id": 10,
        "item_type_id": 33,
        "location": {"item": 10},
        "fields": {"name": "y"},
    },
    "delete_item": {"item_id": 10},
    "set_item_lock": {"item_id": 10, "locked": True},
    "post_item_tag": {"item_id": 10, "tag_id": 1},
    "create_tag": {"name": "safety", "project_id": 3},
    "create_relationship": {"from_item": 10, "to_item": 11},
    "delete_relationship": {"relationship_id": 5},
    "create_test_plan": {"project_id": 3, "name": "Plan"},
    "create_test_cycle": {
        "testplan_id": 1,
        "name": "Cycle",
        "start_date": "2026-01-01",
        "end_date": "2026-02-01",
    },
    "update_test_run": {"test_run_id": RUN, "data": {"fields": {"actualResults": "x"}}},
    "upload_attachment": {"item_id": 10, "content_base64": b64(PNG), "file_name": "a.png"},
    "attach_screenshot_to_test_run": {
        "test_run_id": RUN,
        "step": 2,
        "content_base64": b64(PNG),
        "file_name": "shot.png",
    },
}


def writes(fake: FakeJamaAttachments) -> list[tuple[str, str]]:
    return [(m, r) for m, r in fake.requests if m.upper() not in SAFE_METHODS]


async def listed_tools(server: JamaStdioMCPServer) -> list[types.Tool]:
    handler = server.mcp.request_handlers[types.ListToolsRequest]
    result = await handler(types.ListToolsRequest(method="tools/list"))
    return list(result.root.tools)


async def call_tool(server: JamaStdioMCPServer, name: str, args: dict[str, Any]) -> Any:
    handler = server.mcp.request_handlers[types.CallToolRequest]
    request = types.CallToolRequest(
        method="tools/call", params=types.CallToolRequestParams(name=name, arguments=args)
    )
    result = await handler(request)
    return json.loads(result.root.content[0].text)


def stdio_server(fake: FakeJamaAttachments, tmp_path: Path, ro: bool) -> JamaStdioMCPServer:
    """A stdio server on the fake Jama whose HTTP client is read-only too when ``ro``."""
    config = JamaConfig(url=fake.base, username="user", password="pw", read_only=ro)  # noqa: S106
    server = JamaStdioMCPServer(config)
    http = JamaHttpClient(
        base_url=fake.base,
        credentials=("user", "pw"),
        transport=fake.transport(),
        read_only=ro,
    )
    api = JamaApi(http)
    server._api = api
    server._attachment_tools = AttachmentTools(api, UploadCache(tmp_path / "uploads.json"))
    return server


@pytest.fixture
def fake() -> FakeJamaAttachments:
    return FakeJamaAttachments()


# --------------------------------------------------------------------------
# Classification: every tool is on exactly one list
# --------------------------------------------------------------------------


class TestClassification:
    async def test_every_stdio_tool_is_classified(self) -> None:
        server = JamaStdioMCPServer(JamaConfig(url=URL, api_key="k"))
        names = {tool.name for tool in await listed_tools(server)}

        assert not read_only.STDIO_READ_TOOLS & read_only.STDIO_WRITE_TOOLS
        unclassified = names - read_only.STDIO_READ_TOOLS - read_only.STDIO_WRITE_TOOLS
        assert not unclassified, f"classify these tools in read_only.py: {unclassified}"
        stale = (read_only.STDIO_READ_TOOLS | read_only.STDIO_WRITE_TOOLS) - names
        assert not stale, f"tools classified but not listed: {stale}"

    def test_every_http_intent_is_classified(self) -> None:
        source = inspect.getsource(JamaMCPServer._execute_jama_operation)
        intents = set(re.findall(r'intent == "([a-z_]+)"', source)) | attachment_tools.TOOL_NAMES

        assert not read_only.HTTP_READ_INTENTS & read_only.HTTP_WRITE_INTENTS
        unclassified = intents - read_only.HTTP_READ_INTENTS - read_only.HTTP_WRITE_INTENTS
        assert not unclassified, f"classify these intents in read_only.py: {unclassified}"
        stale = (read_only.HTTP_READ_INTENTS | read_only.HTTP_WRITE_INTENTS) - intents
        assert not stale, f"intents classified but not handled: {stale}"

    def test_shared_tools_are_classified(self) -> None:
        assert (
            read_only.SHARED_READ_TOOLS | read_only.SHARED_WRITE_TOOLS
            == attachment_tools.TOOL_NAMES
        )

    async def test_tools_that_say_they_modify_jama_are_write_tools(self) -> None:
        server = JamaStdioMCPServer(JamaConfig(url=URL, api_key="k"))
        for tool in await listed_tools(server):
            if "Modifies Jama" in (tool.description or ""):
                assert tool.name in read_only.STDIO_WRITE_TOOLS, tool.name

    def test_write_arguments_cover_every_write_tool(self) -> None:
        assert set(STDIO_WRITE_ARGUMENTS) == read_only.STDIO_WRITE_TOOLS


# --------------------------------------------------------------------------
# stdio server, tool layer
# --------------------------------------------------------------------------


class TestStdioToolLayer:
    async def test_write_tools_are_not_listed(
        self, fake: FakeJamaAttachments, tmp_path: Path
    ) -> None:
        names = {t.name for t in await listed_tools(stdio_server(fake, tmp_path, ro=True))}
        assert names == read_only.STDIO_READ_TOOLS

    async def test_all_tools_are_listed_without_read_only(
        self, fake: FakeJamaAttachments, tmp_path: Path
    ) -> None:
        names = {t.name for t in await listed_tools(stdio_server(fake, tmp_path, ro=False))}
        assert names >= read_only.STDIO_WRITE_TOOLS

    @pytest.mark.parametrize("tool", sorted(read_only.STDIO_WRITE_TOOLS))
    async def test_write_tool_is_refused_and_nothing_is_sent(
        self, fake: FakeJamaAttachments, tmp_path: Path, tool: str
    ) -> None:
        server = stdio_server(fake, tmp_path, ro=True)
        before = copy.deepcopy(fake.test_runs)

        result = await call_tool(server, tool, STDIO_WRITE_ARGUMENTS[tool])

        assert result["error_code"] == "READ_ONLY_MODE"
        assert "Read-only mode" in result["error"]
        assert fake.requests == []
        assert fake.test_runs == before
        assert fake.attachments == {}

    async def test_unknown_tool_is_refused(self, fake: FakeJamaAttachments, tmp_path: Path) -> None:
        server = stdio_server(fake, tmp_path, ro=True)
        with pytest.raises(ReadOnlyModeError):
            await server._execute_tool("no_such_tool", {})

    async def test_read_tools_still_work(self, fake: FakeJamaAttachments, tmp_path: Path) -> None:
        server = stdio_server(fake, tmp_path, ro=True)

        run = await call_tool(server, "get_test_run", {"test_run_id": RUN})

        assert run["id"] == RUN
        assert fake.requests and writes(fake) == []

    async def test_session_status_is_allowed(
        self, fake: FakeJamaAttachments, tmp_path: Path
    ) -> None:
        server = stdio_server(fake, tmp_path, ro=True)
        result = await call_tool(server, "get_session_status", {})
        assert result == {"auth_type": "credentials", "session": None}

    async def test_initialize_client_builds_a_read_only_http_client(self) -> None:
        for config in (
            JamaConfig(url=URL, api_key="k", read_only=True),
            JamaConfig(url=URL, client_id="c", client_secret="s", read_only=True),
            JamaConfig(url=URL, username="u", password="p", read_only=True),  # noqa: S106
        ):
            server = JamaStdioMCPServer(config)
            await server.initialize_client()
            assert server._http is not None and server._http.read_only
            await server._http.close()


# --------------------------------------------------------------------------
# stdio server, transport layer alone (tool layer switched off)
# --------------------------------------------------------------------------


class TestStdioTransportLayer:
    @pytest.mark.parametrize("tool", sorted(read_only.STDIO_WRITE_TOOLS))
    async def test_write_tool_is_stopped_at_the_transport(
        self,
        fake: FakeJamaAttachments,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        tool: str,
    ) -> None:
        """Even a write tool that slipped through the allowlist sends no write.

        Read-modify-write tools (test run updates, screenshots) do their reads
        and are stopped at the first write.
        """
        monkeypatch.setattr(read_only, "check_tool", lambda name, allowed: None)
        server = stdio_server(fake, tmp_path, ro=True)
        before = copy.deepcopy(fake.test_runs)

        with pytest.raises(ReadOnlyModeError):
            await server._execute_tool(tool, STDIO_WRITE_ARGUMENTS[tool])

        assert writes(fake) == []
        assert fake.test_runs == before
        assert fake.attachments == {}

    async def test_the_fake_accepts_these_writes_without_read_only(
        self, fake: FakeJamaAttachments, tmp_path: Path
    ) -> None:
        """Control: the same calls do reach the wire when read-only mode is off."""
        server = stdio_server(fake, tmp_path, ro=False)
        for tool in ("update_test_run", "upload_attachment", "delete_item"):
            # The fake does not serve every route; only the requests sent matter here.
            with contextlib.suppress(Exception):
                await server._execute_tool(tool, STDIO_WRITE_ARGUMENTS[tool])
        assert {method for method, _ in writes(fake)} >= {"PUT", "POST", "DELETE"}


# --------------------------------------------------------------------------
# JamaHttpClient and JamaApi
# --------------------------------------------------------------------------


class Recorder:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.sent.append((request.method, request.url.path))
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return httpx.Response(200, json={"meta": {"status": "OK"}, "data": {"id": 1}})


def recording_client(recorder: Recorder, **kwargs: Any) -> JamaHttpClient:
    kwargs.setdefault("credentials", ("u", "p"))
    return JamaHttpClient(
        base_url=URL, transport=httpx.MockTransport(recorder.handle), read_only=True, **kwargs
    )


class TestHttpClient:
    async def test_writes_raise_before_sending(self) -> None:
        recorder = Recorder()
        http = recording_client(recorder)
        calls = [
            http.post("items", json={}),
            http.put("items/1", json={}),
            http.patch("items/1", json=[]),
            http.delete("items/1"),
            http.request("PUT", "attachments/1/file", content=b"x"),
            http.request("post", f"{URL}/ui/internal/attachments"),
        ]
        for call in calls:
            with pytest.raises(ReadOnlyModeError):
                await call
        assert recorder.sent == []
        await http.close()

    async def test_reads_are_sent(self) -> None:
        recorder = Recorder()
        http = recording_client(recorder)
        assert await http.get("items/1") == {"meta": {"status": "OK"}, "data": {"id": 1}}
        await http.request("HEAD", "items/1")
        assert [m for m, _ in recorder.sent] == ["GET", "HEAD"]
        await http.close()

    async def test_oauth_token_request_still_works(self) -> None:
        recorder = Recorder()
        http = recording_client(recorder, credentials=("id", "secret"), oauth=True)
        await http.get("projects")
        assert recorder.sent[0] == ("POST", "/rest/oauth/token")
        assert recorder.sent[1][0] == "GET"
        await http.close()

    def test_off_by_default(self) -> None:
        assert not JamaHttpClient(base_url=URL).read_only


# Every JamaApi method that changes Jama, with arguments.
API_WRITES: dict[str, tuple[Any, ...]] = {
    "post_item": (3, 33, None, {"item": 10}, {"name": "x"}),
    "patch_item": (10, []),
    "put_item": (3, 10, 33, None, {"item": 10}, {"name": "x"}),
    "delete_item": (10,),
    "post_relationship": (10, 11),
    "delete_relationship": (5,),
    "post_item_tag": (10, 1),
    "post_tag": ("t", 3),
    "create_test_plan": (3, "Plan"),
    "post_testplans_testcycles": (1, "Cycle", "2026-01-01", "2026-02-01"),
    "put_test_run": (RUN, {"fields": {}}),
    "post_item_attachment": (10, 500),
    "post_project_attachment": (3, "a.png"),
    "put_attachment_file": (500, "a.png", b"x", "image/png"),
    "post_internal_attachment": (10, 3, "a", "", "a.png", b"x", "image/png"),
    "put_item_lock": (10, True),
}


class TestJamaApi:
    def test_list_covers_every_write_method(self) -> None:
        prefixes = ("post_", "put_", "patch_", "delete_", "create_")
        methods = {name for name in dir(JamaApi) if name.startswith(prefixes)}
        assert methods == set(API_WRITES)

    @pytest.mark.parametrize("method", sorted(API_WRITES))
    async def test_write_method_raises(self, method: str) -> None:
        recorder = Recorder()
        http = recording_client(recorder)
        with pytest.raises(ReadOnlyModeError):
            await getattr(JamaApi(http), method)(*API_WRITES[method])
        assert recorder.sent == []
        await http.close()


# --------------------------------------------------------------------------
# HTTP server
# --------------------------------------------------------------------------


def http_server(ro: bool = True) -> JamaMCPServer:
    server = JamaMCPServer(config=JamaConfig(url=URL, api_key="k", read_only=ro))
    server.jama_client = MagicMock()
    return server


async def invoke(server: JamaMCPServer, intent: str, **params: Any) -> dict[str, Any]:
    request = MCPRequest(prompt=f"run {intent}", parameters={"intent": intent, **params})
    response = await server.handle_request(request)
    result: dict[str, Any] = json.loads(response.response)
    return result


class TestHttpServer:
    @pytest.mark.parametrize("intent", sorted(read_only.HTTP_WRITE_INTENTS))
    async def test_write_intent_is_refused(self, intent: str) -> None:
        server = http_server()
        shared = MagicMock()
        server._shared_tool_handlers = shared  # type: ignore[method-assign]

        result = await invoke(server, intent, item_id=1, project_id=1, test_run_id=1)

        assert result["success"] is False
        assert result["error_code"] == "READ_ONLY_MODE"
        assert server.jama_client.method_calls == []
        shared.assert_not_called()

    async def test_read_intent_works(self) -> None:
        server = http_server()
        server.jama_client.get_projects.return_value = [{"id": 1}]
        result = await invoke(server, "get_projects")
        assert "READ_ONLY_MODE" not in json.dumps(result)
        server.jama_client.get_projects.assert_called_once_with()

    async def test_batch_is_gated_too(self) -> None:
        server = http_server()
        requests_ = [
            MCPRequest(prompt="x", parameters={"intent": "delete_item", "item_id": 1}),
            MCPRequest(prompt="x", parameters={"intent": "get_projects"}),
        ]
        server.jama_client.get_projects.return_value = []
        responses = await server.handle_batch_request(requests_)
        assert json.loads(responses[0].response)["error_code"] == "READ_ONLY_MODE"
        server.jama_client.delete_item.assert_not_called()

    async def test_write_intent_works_without_read_only(self) -> None:
        server = http_server(ro=False)
        server.jama_client.delete_item.return_value = 204
        await invoke(server, "delete_item", item_id=1)
        server.jama_client.delete_item.assert_called_once_with(1)

    async def test_tool_listing_is_filtered(self) -> None:
        response = await http_server()._handle_tools(MagicMock())
        body = json.loads(response.text or "")
        assert {tool["name"] for tool in body["tools"]} == read_only.SHARED_READ_TOOLS
        assert body["read_only"] is True

        response = await http_server(ro=False)._handle_tools(MagicMock())
        names = {tool["name"] for tool in json.loads(response.text or "")["tools"]}
        assert names == attachment_tools.TOOL_NAMES

    async def test_health_reports_the_mode(self) -> None:
        assert (await http_server().health_check()).read_only is True
        assert (await http_server(ro=False).health_check()).read_only is False

    def test_shared_tools_get_a_read_only_client(self) -> None:
        server = JamaMCPServer(config=JamaConfig(url=URL, api_key="k", read_only=True))
        handlers = server._shared_tool_handlers()
        assert server._shared_http is not None and server._shared_http.read_only
        assert handlers is not None


# --------------------------------------------------------------------------
# py-jama-rest-client guard
# --------------------------------------------------------------------------


class RecordingAdapter(BaseAdapter):
    """Answers every request with an empty Jama page and records it."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[tuple[str, str]] = []

    def send(  # type: ignore[override]
        self, request: requests.PreparedRequest, **kwargs: Any
    ) -> requests.Response:
        self.sent.append((request.method or "", request.url or ""))
        response = requests.Response()
        response.status_code = 200
        response.headers["Content-Type"] = "application/json"
        page = {"startIndex": 0, "resultCount": 0, "totalResults": 0}
        response._content = json.dumps(
            {"meta": {"status": "OK", "pageInfo": page}, "data": []}
        ).encode()
        response.url = request.url or ""
        response.request = request
        return response

    def close(self) -> None:
        pass


def py_jama_client(adapter: RecordingAdapter, **kwargs: Any) -> PyJamaClient:
    kwargs.setdefault("host_domain", URL)
    kwargs.setdefault("credentials", ("u", "p"))
    client = PyJamaClient(**kwargs)
    session = client._JamaClient__core._Core__session  # type: ignore[attr-defined]
    session.mount("https://", adapter)
    return client


class TestPyJamaGuard:
    def test_non_get_is_refused_and_get_passes(self) -> None:
        adapter = RecordingAdapter()
        client = py_jama_client(adapter)
        read_only.guard_jama_client(client)

        assert client.get_projects() == []
        for call in (
            lambda: client.delete_item(1),
            lambda: client.patch_item(1, []),
            lambda: client.post_tag("t", 1),
            lambda: client.put_item_lock(1, True),
        ):
            with pytest.raises(ReadOnlyModeError):
                call()

        assert [method for method, _ in adapter.sent] == ["GET"]

    def test_guard_is_idempotent(self) -> None:
        client = py_jama_client(RecordingAdapter())
        read_only.guard_jama_client(client)
        read_only.guard_jama_client(client)
        session = client._JamaClient__core._Core__session  # type: ignore[attr-defined]
        adapter = session.get_adapter(URL)
        assert isinstance(adapter, read_only.ReadOnlyAdapter)
        assert not isinstance(adapter.inner, read_only.ReadOnlyAdapter)

    def test_fails_closed_when_the_session_is_not_found(self) -> None:
        with pytest.raises(RuntimeError, match="Cannot enforce read-only mode"):
            read_only.guard_jama_client(object())

    async def test_server_startup_applies_the_guard(self) -> None:
        adapter = RecordingAdapter()
        server = JamaMCPServer(config=JamaConfig(url=URL, api_key="k", read_only=True))
        with patch(
            "jama_mcp_server.core.server.JamaClient",
            side_effect=lambda **kw: py_jama_client(adapter, **kw),
        ):
            await server._initialize_jama_client()

        assert server.jama_client is not None
        with pytest.raises(ReadOnlyModeError):
            server.jama_client.delete_item(1)
        assert [method for method, _ in adapter.sent] == ["GET"]

    async def test_server_does_not_start_without_the_guard(self) -> None:
        server = JamaMCPServer(config=JamaConfig(url=URL, api_key="k", read_only=True))
        with (
            patch("jama_mcp_server.core.server.JamaClient", return_value=MagicMock()),
            pytest.raises(RuntimeError, match="Cannot enforce read-only mode"),
        ):
            await server._initialize_jama_client()


# --------------------------------------------------------------------------
# Switch: profile, environment, jama serve, CLI client
# --------------------------------------------------------------------------


class TestSwitch:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("1", True),
            ("true", True),
            ("YES", True),
            (" on ", True),
            ("", False),
            (None, False),
            ("0", False),
            ("false", False),
            ("off", False),
            ("maybe", True),  # unrecognised: fail closed
        ],
    )
    def test_parse_flag(self, value: str | None, expected: bool) -> None:
        assert parse_flag(value) is expected

    def test_env_turns_it_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from jama_cli.config import get_profile_or_env

        monkeypatch.setenv("JAMA_URL", URL)
        monkeypatch.setenv("JAMA_API_KEY", "k")
        monkeypatch.delenv("JAMA_READ_ONLY", raising=False)
        profile = get_profile_or_env()
        assert profile is not None and not profile.read_only

        monkeypatch.setenv("JAMA_READ_ONLY", "1")
        profile = get_profile_or_env()
        assert profile is not None and profile.read_only

    def test_env_cannot_turn_off_a_read_only_profile(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from jama_cli.config import get_profile_or_env

        config = tmp_path / "config.yml"
        config.write_text(
            "default_profile: prod\n"
            "profiles:\n"
            "  prod:\n"
            f"    url: {URL}\n"
            "    auth_type: api_key\n"
            "    api_key: k\n"
            "    read_only: true\n"
        )
        monkeypatch.setenv("JAMA_CONFIG", str(config))
        monkeypatch.delenv("JAMA_URL", raising=False)
        monkeypatch.setenv("JAMA_READ_ONLY", "0")

        profile = get_profile_or_env()
        assert profile is not None and profile.read_only

    def test_profile_key_is_saved(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from jama_cli.config import load_config, save_config
        from jama_cli.models import JamaConfig as CliConfig
        from jama_cli.models import JamaProfile

        config_file = tmp_path / "config.yml"
        config_file.write_text("profiles: {}\n")
        monkeypatch.setenv("JAMA_CONFIG", str(config_file))
        save_config(
            CliConfig(
                default_profile="prod",
                profiles={"prod": JamaProfile(url=URL, api_key="k", read_only=True)},
            )
        )
        assert "read_only: true" in config_file.read_text()
        assert load_config().profiles["prod"].read_only

    def test_config_show_displays_the_mode(self) -> None:
        from jama_cli.models import JamaProfile

        assert JamaProfile(url=URL, api_key="k", read_only=True).get_masked_display()[
            "read_only"
        ] == ("yes")
        assert JamaProfile(url=URL, api_key="k").get_masked_display()["read_only"] == ""

    def test_mcp_env_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from jama_mcp_server.config import load_env_config

        monkeypatch.setenv("JAMA_URL", URL)
        monkeypatch.setenv("JAMA_API_KEY", "k")
        monkeypatch.setenv("JAMA_READ_ONLY", "true")
        config = load_env_config(env_file=str(Path("/nonexistent/.env")))
        assert config is not None and config.read_only

    @pytest.mark.parametrize("profile_read_only", [False, True])
    @pytest.mark.parametrize("flag", [False, True])
    def test_serve_passes_the_mode_to_both_servers(
        self, flag: bool, profile_read_only: bool
    ) -> None:
        from jama_cli.commands.serve import app
        from jama_cli.models import JamaProfile

        profile = JamaProfile(url=URL, api_key="k", read_only=profile_read_only)
        expected = flag or profile_read_only
        args = ["--read-only"] if flag else []
        with (
            patch("jama_cli.commands.serve.get_profile_or_env", return_value=profile),
            patch("jama_cli.commands.serve._run_stdio_server") as stdio,
            patch("jama_cli.commands.serve._run_http_server") as http,
        ):
            assert CliRunner().invoke(app, ["--stdio", *args]).exit_code == 0
            assert CliRunner().invoke(app, args).exit_code == 0

        assert stdio.call_args.args[0].read_only is expected
        assert http.call_args.args[0].read_only is expected

    def test_daemon_passes_the_flag_on(self) -> None:
        from jama_cli.commands import serve

        process = MagicMock()
        process.poll.return_value = None
        process.pid = 4242
        with (
            patch.object(serve.subprocess, "Popen", return_value=process) as popen,
            patch.object(serve.time, "sleep"),
            patch.object(serve, "_write_pid"),
            patch.object(serve, "LOG_FILE", Path("/dev/null")),
            patch.object(serve, "RUNTIME_DIR", Path("/tmp")),  # noqa: S108
            patch.object(serve, "MODE_FILE", Path("/dev/null")),
        ):
            serve._start_daemon("localhost", 8000, None, None, read_only=True)
        assert "--read-only" in popen.call_args.args[0]

    @pytest.mark.parametrize(
        ("previous", "flag", "expected"),
        [("read-only", False, True), ("read-write", False, False), (None, True, True)],
    )
    def test_restart_keeps_read_only_mode(
        self, tmp_path: Path, previous: str | None, flag: bool, expected: bool
    ) -> None:
        from jama_cli.commands import serve

        mode_file = tmp_path / "server.mode"
        if previous:
            mode_file.write_text(previous)
        with (
            patch.object(serve, "MODE_FILE", mode_file),
            patch.object(serve, "_get_pid", return_value=None),
            patch.object(serve, "_start_daemon") as start,
        ):
            result = CliRunner().invoke(serve.app, ["restart", *(["--read-only"] if flag else [])])
        assert result.exit_code == 0, result.output
        assert start.call_args.kwargs["read_only"] is expected

    def test_daemon_start_records_the_mode(self, tmp_path: Path) -> None:
        from jama_cli.commands import serve

        process = MagicMock()
        process.poll.return_value = None
        with (
            patch.object(serve.subprocess, "Popen", return_value=process),
            patch.object(serve.time, "sleep"),
            patch.object(serve, "_write_pid"),
            patch.object(serve, "LOG_FILE", tmp_path / "server.log"),
            patch.object(serve, "RUNTIME_DIR", tmp_path),
            patch.object(serve, "MODE_FILE", tmp_path / "server.mode"),
        ):
            serve._start_daemon("localhost", 8000, None, None, read_only=True)
            assert serve._daemon_was_read_only()
            serve._start_daemon("localhost", 8000, None, None, read_only=False)
            assert not serve._daemon_was_read_only()

    @pytest.mark.parametrize(
        ("value", "expected"), [("true", True), (True, True), ("false", False), (None, False)]
    )
    def test_mcp_yaml_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: Any, expected: bool
    ) -> None:
        import yaml

        from jama_mcp_server.config import load_yaml_config

        monkeypatch.delenv("JAMA_READ_ONLY", raising=False)
        server: dict[str, Any] = {"url": URL, "api_key": "k"}
        if value is not None:
            server["read_only"] = value
        path = tmp_path / "servers.yml"
        path.write_text(yaml.safe_dump({"servers": {"prod": server}}))
        config = load_yaml_config(str(path))
        assert config is not None and config.servers["prod"].read_only is expected

    @pytest.mark.parametrize(("profile_flag", "env"), [(True, "0"), (False, "1")])
    def test_cli_client_refuses_writes(
        self, monkeypatch: pytest.MonkeyPatch, profile_flag: bool, env: str
    ) -> None:
        from jama_cli.core.client import JamaClient
        from jama_cli.models import JamaProfile

        monkeypatch.setenv("JAMA_READ_ONLY", env)
        client = JamaClient(
            JamaProfile(url=URL, api_key="k", read_only=profile_flag), use_disk_cache=False
        )
        api = client._ensure_connected()
        try:
            assert api._http.read_only
            with pytest.raises(ReadOnlyModeError):
                api.delete_item(1)
        finally:
            api.close()

    def test_cli_client_is_read_write_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from jama_cli.core.client import JamaClient
        from jama_cli.models import JamaProfile

        monkeypatch.delenv("JAMA_READ_ONLY", raising=False)
        client = JamaClient(JamaProfile(url=URL, api_key="k"), use_disk_cache=False)
        api = client._ensure_connected()
        try:
            assert not api._http.read_only
        finally:
            api.close()
